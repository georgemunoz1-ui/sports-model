"""Route/receipt engineering checks; synthetic fixtures, no predictive claims."""
import copy
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from models.common import discrete_research as D, volatility_matrix_v1 as V
from pipelines.cards import volatility_routing as R

spec = importlib.util.spec_from_file_location("volatility_test_fixtures", Path(__file__).with_name("test_volatility_matrix_v1.py"))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


def write(path, value):
    path.write_text(json.dumps(value))
    return path


def inputs(tmp_path, *, separate=False):
    card, settlement = fixtures._card("nhl")
    card["card_date"] = "2026-02-01"
    card["research_routes"] = {"other_explicit_child": {"status": "UNAVAILABLE"}}
    # Explicit synthetic identities only. No production card is relabeled.
    card["forecasts"][0].update({
        "home_id": "synthetic-home-1", "away_id": "synthetic-away-2",
        "team_id_namespace": "SYNTHETIC_NHL_TEST_ONLY",
        "event_id_namespace": "SYNTHETIC_NHL_EVENTS_TEST_ONLY",
        "projected_margin_orientation": R.PARENT_ORIENTATION,
        "target": R.PARENT_TARGET, "settlement": settlement,
        "information_set": "PREGAME_TEST",
    })
    model = fixtures.fit(league="nhl", settlement=settlement)
    model_path = write(tmp_path / "fit.json", model)
    config = {"schema": R.CONFIG_SCHEMA, "action_authority": False,
              "information_set": "PREGAME_TEST", "contracts": [],
              "models": [{"path": model_path.name, "sha256": R.file_hash(model_path)}]}
    if separate:
        parent = write(tmp_path / "parent.json", card)
        config["parent_card"] = {"path": parent.name, "sha256": R.file_hash(parent)}
        card = copy.deepcopy(card)
        card["forecasts"][0]["model_id"] = "nhl.selected.winner"
    return write(tmp_path / "card.json", card), write(tmp_path / "config.json", config)


def test_receipt_actual_joint_100k_and_explicit_parent_preserves_inputs(tmp_path):
    card, config = inputs(tmp_path, separate=True)
    before = {str(p): R.file_hash(p) for p in tmp_path.glob("*.json")}
    receipt = R.run_joint_route(card, config, tmp_path / "out", simulations=100000)
    assert receipt["status"] == "COMPLETED"
    assert receipt["actual_joint_draws"] == 100000
    assert receipt["requested_route"] == receipt["executed_route"] == R.ROUTE
    assert receipt["explicit_separate_parent"] and receipt["input_files_unchanged"]
    assert not receipt["fallback_executed"] and not receipt["action_authority"]
    assert receipt["observed_checkout_sha"] and receipt["process_argv"]
    assert receipt["code_file_sha256"]["pipelines/cards/volatility_routing.py"]
    binding = receipt["parent_identity_bindings"]["card-nhl"]
    parent_row = json.loads((tmp_path / "parent.json").read_text())["forecasts"][0]
    assert binding["parent_forecast_sha256"] == D.digest(parent_row)
    assert binding["home_id"] == "synthetic-home-1"
    assert binding["away_id"] == "synthetic-away-2"
    assert binding["team_id_namespace"] == "SYNTHETIC_NHL_TEST_ONLY"
    assert binding["information_set"] == "PREGAME_TEST"
    report = json.loads((tmp_path / "out/joint/volatility_report.json").read_text())
    result = report["results"][0]
    h, a, metadata = V.simulate(result["distribution"], draws=100000)
    with np.load(tmp_path / "out/joint" / result["simulation"]["file"]) as draws:
        assert np.array_equal(h, draws["home"]) and np.array_equal(a, draws["away"])
    assert metadata["draw_sha256"] == result["simulation"]["draw_sha256"]
    assert {str(p): R.file_hash(p) for p in tmp_path.glob("*.json")} == before
    display = json.loads((tmp_path / "out/card_with_research_routes.json").read_text())
    assert display["forecasts"][0]["model_id"] == "nhl.selected.winner"
    assert display["research_routes"]["joint_volatility"]["explicit_separate_parent"]
    assert display["research_routes"]["other_explicit_child"] == {"status": "UNAVAILABLE"}


@pytest.mark.parametrize("failure", ["missing_config", "bad_hash", "duplicate_fit", "parent_event", "future_fit", "missing_total"])
def test_refusals_visible_no_fallback_or_draws(tmp_path, failure):
    card, config = inputs(tmp_path, separate=True)
    c = json.loads(config.read_text())
    expected = None
    if failure == "missing_config":
        config.unlink()
    elif failure == "bad_hash":
        c["models"][0]["sha256"] = "0"*64; expected = "CONFIG_MODEL_FILE_HASH_MISMATCH"
    elif failure == "duplicate_fit":
        c["models"].append(copy.deepcopy(c["models"][0])); expected = "DUPLICATE_CONFIG_MODEL"
    else:
        p = tmp_path / "parent.json"; parent = json.loads(p.read_text())
        if failure == "parent_event":
            parent["forecasts"][0]["event_id"] = "other"; expected = "EXPLICIT_PARENT_EVENT_SET_OR_START_MISMATCH"
        elif failure == "future_fit":
            parent["as_of_utc"] = "2025-12-01T00:00:00Z"; expected = "FUTURE_FITTED_ARTIFACT"
        elif failure == "missing_total":
            r = parent["forecasts"][0]
            r.pop("projected_home_points"); r.pop("projected_away_points")
            r["diagnostics"]["home_margin"] = 5; expected = "POINT_HEAD_UNAVAILABLE:total"
        write(p, parent); c["parent_card"]["sha256"] = R.file_hash(p)
    if failure != "missing_config": write(config, c)
    receipt = R.run_joint_route(card, config, tmp_path / "out", simulations=100)
    assert receipt["status"] == "BLOCKED"
    assert receipt["actual_joint_draws"] == 0 and receipt["executed_route"] is None
    assert not receipt["fallback_executed"]
    assert (tmp_path / "out/route_receipt.json").exists()
    assert len(receipt["per_market_availability"]) == 3
    if expected:
        assert expected in json.dumps(receipt)


def test_fit_required_is_distinct_from_invocation_failure(tmp_path):
    card, config = inputs(tmp_path)
    c = json.loads(config.read_text()); c["models"] = []; write(config, c)
    r = R.run_joint_route(card, config, tmp_path / "out", simulations=100)
    assert r["adapter_invoked"] and r["status"] == "BLOCKED"
    assert r["coverage"][0]["status"] == "FIT_REQUIRED"
    assert len(r["per_market_availability"]) == 3


def test_shared_cli_shows_requested_joint_route_and_keeps_parent_json(tmp_path, monkeypatch):
    from scripts import generate_card_force as runner
    from pipelines.cards import disclosures, selection_integration
    card, config = inputs(tmp_path)
    value = json.loads(card.read_text()); value["coverage_breach_event_ids"] = []
    monkeypatch.setattr(runner, "generate", lambda *a, **k: copy.deepcopy(value))
    monkeypatch.setattr(runner, "render_md", lambda *a: "# Synthetic card\n")
    monkeypatch.setattr(disclosures, "write_report", lambda *a: {"errors": []})
    monkeypatch.setattr(selection_integration, "write_card_selection", lambda *a, **k: {"decision_counts": {}})
    monkeypatch.setenv("SPORTS_RESEARCH_DRAW_OUTPUT", "test")
    monkeypatch.setattr(sys, "argv", ["generate_card_force.py", "--date", "2026-02-01", "--league", "nhl",
        "--output-dir", str(tmp_path / "shared"), "--volatility-research-config", str(config), "--simulations", "100"])
    with pytest.raises(SystemExit) as result: runner.main()
    assert result.value.code == 0
    assert json.loads((tmp_path / "shared/diagnostic_card.json").read_text()) == value
    assert R.ROUTE in (tmp_path / "shared/diagnostic_card.md").read_text()
    assert (tmp_path / "shared/volatility_research/card_with_research_routes.json").exists()


def test_output_collision_refused_without_overwrite(tmp_path):
    card, config = inputs(tmp_path)
    out = tmp_path / "out"
    R.run_joint_route(card, config, out, simulations=10)
    before = R.file_hash(out / "route_receipt.json")
    with pytest.raises(FileExistsError): R.run_joint_route(card, config, out, simulations=10)
    assert R.file_hash(out / "route_receipt.json") == before


@pytest.mark.parametrize("failure", [
    "swapped_ids", "unrelated_ids", "unrelated_home_only", "unrelated_away_only",
    "matching_names_conflicting_ids",
    "missing_event_id", "missing_home_id", "missing_away_id", "missing_namespace", "different_namespace",
    "missing_event_id_namespace", "different_event_namespace",
    "same_team", "wrong_orientation", "missing_orientation", "winner_target",
    "missing_target", "wrong_settlement", "missing_settlement", "wrong_information_set",
    "missing_information_set", "wrong_parent_model", "missing_state_hash",
])
def test_parent_identity_refused_before_adapter_or_draws(tmp_path, monkeypatch, failure):
    card, config = inputs(tmp_path, separate=True)
    parent_path = tmp_path / "parent.json"
    parent = json.loads(parent_path.read_text())
    row = parent["forecasts"][0]
    if failure == "swapped_ids":
        row["home_id"], row["away_id"] = row["away_id"], row["home_id"]
    elif failure == "unrelated_home_only":
        row["home_id"] = "other-home"
    elif failure == "unrelated_away_only":
        row["away_id"] = "other-away"
    elif failure in {"unrelated_ids", "matching_names_conflicting_ids"}:
        row["home_id"], row["away_id"] = "other-home", "other-away"
        if failure == "unrelated_ids":
            row["home_team"], row["away_team"] = "Other Home", "Other Away"
    elif failure.startswith("missing_"):
        key = {"missing_namespace": "team_id_namespace",
               "missing_orientation": "projected_margin_orientation",
               "missing_state_hash": "model_state_config_hash"}.get(failure, failure[8:])
        row.pop(key)
    elif failure == "different_namespace":
        row["team_id_namespace"] = "OTHER_PROVIDER_TEST_ONLY"
    elif failure == "different_event_namespace":
        row["event_id_namespace"] = "OTHER_PROVIDER_EVENTS_TEST_ONLY"
    elif failure == "same_team":
        row["away_id"] = row["home_id"]
    elif failure == "wrong_orientation":
        row["projected_margin_orientation"] = "AWAY_MINUS_HOME"
    elif failure == "winner_target":
        row["target"] = "WINNER_ONLY"
    elif failure == "wrong_settlement":
        row["settlement"] = "REGULATION"
    elif failure == "wrong_information_set":
        row["information_set"] = "DIFFERENT_INFORMATION_SET"
    elif failure == "wrong_parent_model":
        row["model_id"] = "nhl.unrelated.parent"
    write(parent_path, parent)
    settings = json.loads(config.read_text())
    settings["parent_card"]["sha256"] = R.file_hash(parent_path)
    write(config, settings)
    before = {str(p): R.file_hash(p) for p in tmp_path.glob("*.json")}
    calls = []
    monkeypatch.setattr(R.V, "build", lambda *a, **k: calls.append("adapter"))
    monkeypatch.setattr(V, "simulate", lambda *a, **k: calls.append("draws"))
    receipt = R.run_joint_route(card, config, tmp_path / "out", simulations=100)
    assert calls == []
    assert receipt["status"] == "BLOCKED"
    assert receipt["actual_joint_draws"] == 0
    assert receipt["executed_route"] is None and not receipt["adapter_invoked"]
    assert all(r["status"] != "COMPLETED" for r in receipt["coverage"])
    assert not (tmp_path / "out/joint").exists()
    assert not list((tmp_path / "out").rglob("*.npz"))
    assert (tmp_path / "out/route_receipt.json").is_file()
    assert receipt["input_files_unchanged"]
    assert {str(p): R.file_hash(p) for p in tmp_path.glob("*.json")} == before


def test_team_display_aliases_do_not_override_ordered_canonical_ids(tmp_path):
    card, config = inputs(tmp_path, separate=True)
    displayed = json.loads(card.read_text())
    displayed["forecasts"][0].update(home_team="Home City Club", away_team="Away City Club")
    write(card, displayed)
    receipt = R.run_joint_route(card, config, tmp_path / "out", simulations=100)
    assert receipt["status"] == "COMPLETED"
    assert receipt["actual_joint_draws"] == 100


@pytest.mark.parametrize("failure", ["legacy_config", "legacy_missing_ids", "legacy_missing_scope"])
def test_legacy_inputs_are_not_silently_upgraded(tmp_path, failure):
    card, config = inputs(tmp_path)
    if failure == "legacy_config":
        settings = json.loads(config.read_text())
        settings["schema"] = "sports.volatility_card_config.research.v1"
        write(config, settings)
    else:
        value = json.loads(card.read_text())
        keys = ("home_id", "away_id", "team_id_namespace", "event_id_namespace") if failure == "legacy_missing_ids" else (
            "projected_margin_orientation", "target", "settlement", "information_set")
        for key in keys:
            value["forecasts"][0].pop(key)
        write(card, value)
    before = R.file_hash(card)
    receipt = R.run_joint_route(card, config, tmp_path / "out", simulations=100)
    assert receipt["status"] == "BLOCKED"
    assert not receipt["adapter_invoked"] and receipt["actual_joint_draws"] == 0
    assert receipt["schema"] == "sports.volatility_route_receipt.research.v2"
    assert not (tmp_path / "out/joint").exists()
    assert R.file_hash(card) == before


@pytest.mark.parametrize("field,value", [
    ("settlement", "REGULATION"), ("information_set", "DIFFERENT_INFORMATION_SET"),
])
def test_matching_display_and_config_cannot_override_fitted_scope(tmp_path, field, value):
    card, config = inputs(tmp_path, separate=True)
    for path in (card, tmp_path / "parent.json"):
        data = json.loads(path.read_text())
        data["forecasts"][0][field] = value
        write(path, data)
    settings = json.loads(config.read_text())
    settings["parent_card"]["sha256"] = R.file_hash(tmp_path / "parent.json")
    if field == "information_set":
        settings[field] = value
    write(config, settings)
    receipt = R.run_joint_route(card, config, tmp_path / "out", simulations=100)
    assert receipt["status"] == "BLOCKED"
    assert not receipt["adapter_invoked"] and receipt["actual_joint_draws"] == 0
    assert "SCOPE_MISMATCH" in receipt["reason"] or "INFORMATION_SET_MISMATCH" in receipt["reason"]
    assert not (tmp_path / "out/joint").exists()


def test_missing_displayed_event_id_retains_refusal_receipt(tmp_path):
    card, config = inputs(tmp_path, separate=True)
    displayed = json.loads(card.read_text())
    displayed["forecasts"][0].pop("event_id")
    write(card, displayed)
    receipt = R.run_joint_route(card, config, tmp_path / "out", simulations=100)
    assert receipt["status"] == "BLOCKED"
    assert not receipt["adapter_invoked"] and receipt["actual_joint_draws"] == 0
    assert receipt["coverage"][0]["event_id"] is None
    assert (tmp_path / "out/route_receipt.json").is_file()


def test_all_parent_rows_validated_before_any_draw(tmp_path, monkeypatch):
    card, config = inputs(tmp_path)
    displayed = json.loads(card.read_text())
    second = copy.deepcopy(displayed["forecasts"][0])
    second["event_id"] = "card-nhl-second"
    second["projected_margin_orientation"] = "AWAY_MINUS_HOME"
    displayed["forecasts"].append(second)
    write(card, displayed)
    calls = []
    monkeypatch.setattr(R.V, "build", lambda *a, **k: calls.append("adapter"))
    receipt = R.run_joint_route(card, config, tmp_path / "out", simulations=100)
    assert calls == []
    assert receipt["status"] == "BLOCKED" and receipt["actual_joint_draws"] == 0
    assert len(receipt["coverage"]) == 2
    assert not (tmp_path / "out/joint").exists()


@pytest.mark.parametrize("field,value", [
    ("projected_margin_orientation", "AWAY_MINUS_HOME"),
    ("target", "WINNER_PROBABILITY"), ("information_set", "INPLAY_TEST"),
    ("projected_margin_orientation", None), ("target", None), ("information_set", None),
])
def test_displayed_scope_cannot_borrow_incompatible_parent(tmp_path, monkeypatch, field, value):
    card, config = inputs(tmp_path, separate=True)
    displayed = json.loads(card.read_text())
    displayed["forecasts"][0][field] = value
    write(card, displayed)
    calls = []
    monkeypatch.setattr(R.V, "build", lambda *a, **k: calls.append("adapter"))
    receipt = R.run_joint_route(card, config, tmp_path / "out", simulations=100)
    assert calls == []
    assert receipt["status"] == "BLOCKED" and not receipt["adapter_invoked"]
    assert receipt["actual_joint_draws"] == 0
    assert not (tmp_path / "out/joint").exists()
    assert (tmp_path / "out/route_receipt.json").is_file()


@pytest.mark.parametrize("payload", [
    {"forecasts": [None]}, {"forecasts": ["bad"]}, {"forecasts": [3]},
    [1], {"forecasts": {"bad": 1}}, {"forecasts": [{}]},
])
def test_malformed_cards_retain_diagnostic_receipt(tmp_path, monkeypatch, payload):
    card, config = inputs(tmp_path, separate=True)
    write(card, payload)
    before = R.file_hash(card)
    calls = []
    monkeypatch.setattr(R.V, "build", lambda *a, **k: calls.append("adapter"))
    receipt = R.run_joint_route(card, config, tmp_path / "out", simulations=100)
    assert calls == []
    assert receipt["status"] == "BLOCKED" and receipt["actual_joint_draws"] == 0
    assert not receipt["adapter_invoked"] and not (tmp_path / "out/joint").exists()
    assert (tmp_path / "out/route_receipt.json").is_file()
    assert R.file_hash(card) == before


@pytest.mark.parametrize("location", ["card.json", "parent.json", "config.json", "fit.json"])
@pytest.mark.parametrize("invalid_member", [
    '"unused_input": NaN', '"unused_input": Infinity', '"unused_input": 1e999',
    '"duplicate_identity": "first", "duplicate_identity": "second"',
])
def test_nonfinite_and_ambiguous_json_retains_refusal_before_adapter(
        tmp_path, monkeypatch, location, invalid_member):
    card, config = inputs(tmp_path, separate=True)
    bad_path = tmp_path / location
    original = bad_path.read_text()
    bad_path.write_text(original[:-1] + ", " + invalid_member + "}")
    if location in {"parent.json", "fit.json"}:
        settings = json.loads(config.read_text())
        entry = settings["parent_card"] if location == "parent.json" else settings["models"][0]
        entry["sha256"] = R.file_hash(bad_path)
        write(config, settings)
    before = {str(p): R.file_hash(p) for p in tmp_path.glob("*.json")}
    calls = []
    monkeypatch.setattr(R.V, "build", lambda *a, **k: calls.append("adapter"))
    receipt = R.run_joint_route(card, config, tmp_path / "out", simulations=100)
    assert calls == []
    assert receipt["status"] == "BLOCKED" and not receipt["adapter_invoked"]
    assert receipt["actual_joint_draws"] == 0
    assert "JSON" in receipt["reason"]
    assert not (tmp_path / "out/joint").exists()
    assert not list((tmp_path / "out").rglob("*.npz"))
    assert (tmp_path / "out/route_receipt.json").is_file()
    assert {str(p): R.file_hash(p) for p in tmp_path.glob("*.json")} == before
