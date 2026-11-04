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
    model = fixtures.fit(league="nhl", settlement=settlement)
    model_path = write(tmp_path / "fit.json", model)
    config = {"schema": "sports.volatility_card_config.research.v1", "action_authority": False,
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
    assert "JOINT_VOLATILITY_RESEARCH_V1" in (tmp_path / "shared/diagnostic_card.md").read_text()
    assert (tmp_path / "shared/volatility_research/card_with_research_routes.json").exists()


def test_output_collision_refused_without_overwrite(tmp_path):
    card, config = inputs(tmp_path)
    out = tmp_path / "out"
    R.run_joint_route(card, config, out, simulations=10)
    before = R.file_hash(out / "route_receipt.json")
    with pytest.raises(FileExistsError): R.run_joint_route(card, config, out, simulations=10)
    assert R.file_hash(out / "route_receipt.json") == before
