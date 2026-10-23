"""Integration attacks against immutable selection/evaluation and card receipts."""
import copy
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from models.current.baseline import IDS, feature
from models.nfl.contextual.recovered_inference import digest
from pipelines.cards.research_selection import seal_forecast, select_research, content_hash
from scripts.evaluate_research_selections import build_evaluation
from scripts.generate_card_force import attach_state_receipt

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 1, 20, tzinfo=timezone.utc)


def packet(root, *, outcome="LOSS", status="FINAL"):
    config = {"schema": "research-selector-config-v1", "objective": "unconditional_win",
              "threshold": .6, "require_quality_receipt": True}
    forecast = seal_forecast({"schema": "research-forecast-v1", "procedure_id": "a"*64,
        "input_snapshot_sha256": "b"*64,
        "target": {"event_id": "NBA:test", "league": "nba", "product": "winner",
                   "period": "full_game", "side": "home", "line": None,
                   "settlement_rules_id": "test:includes_overtime", "starts_at_utc": "2026-01-11T01:00:00Z"},
        "probabilities": {"win": .6, "loss": .35, "push": 0., "void": .05},
        "forecast_cutoff_utc": "2026-01-10T23:00:00Z", "forecast_created_at_utc": "2026-01-10T23:01:00Z"})
    decision = select_research(forecast, config, decision_at_utc="2026-01-10T23:02:00Z",
                               replay_at_utc="2026-01-20T00:00:00Z")
    population = [{"event_id": "NBA:test", "target_id": decision["target_id"], "slate_id": "2026-01-10"}]
    result = {"event_id": "NBA:test", "target_id": decision["target_id"], "outcome": outcome,
              "status": status, "observed_at_utc": "2026-01-11T04:00:00Z",
              "settled_at_utc": "2026-01-11T03:50:00Z", "source_sha256": "c"*64,
              "source_ref": "TEST_ONLY retained synthetic outcome"}
    documents = {"decisions": {"decisions": [decision]}, "population": population, "outcomes": [result]}
    manifest = {"schema": "research-selection-evaluation-input-v1", "evidence_scope": "DISCOVERY"}
    for key, value in documents.items():
        path = root / (key + ".json")
        path.write_text(json.dumps(value))
        manifest[key] = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return manifest_path, forecast


def edit_ref(manifest_path, key, change):
    manifest = json.loads(manifest_path.read_text())
    path = manifest_path.parent / manifest[key]["path"]
    value = json.loads(path.read_text())
    change(value)
    path.write_text(json.dumps(value))
    manifest[key]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))


def evaluate(manifest):
    return build_evaluation(manifest, bootstrap_samples=20, seed=17, executed_at=NOW)


def test_blocked_loss_is_not_an_abstention_win_and_inputs_are_immutable(tmp_path):
    manifest, _ = packet(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = evaluate(manifest)
    report = result["report"]
    assert report["n_events"] == report["n_blocked"] == 1
    assert report["n_selected"] == 0 and report["total_coverage"] == 0
    assert report["selected_settlement"]["unconditional_win_accuracy"] is None
    assert report["full_slate_raw_forecast_scores"]["brier"] == pytest.approx(.36)
    assert result["publication_allowed"] is False
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_live_excluded_and_void_preserves_unconditional_score(tmp_path):
    manifest, _ = packet(tmp_path, outcome="LIVE", status="LIVE")
    assert evaluate(manifest)["report"]["full_slate_raw_forecast_scores"]["n"] == 0
    edit_ref(manifest, "outcomes", lambda x: x[0].update(outcome="VOID", status="VOID"))
    report = evaluate(manifest)["report"]
    assert report["full_slate_raw_forecast_scores"]["n"] == 1
    assert report["full_slate_raw_forecast_scores"]["brier"] == pytest.approx(.36)


def test_rehashed_packet_cannot_hide_decision_edit(tmp_path):
    manifest, _ = packet(tmp_path)
    edit_ref(manifest, "decisions", lambda x: x["decisions"][0].update(raw_probability=.99))
    with pytest.raises(ValueError, match="DECISION_ID_MISMATCH"):
        evaluate(manifest)


@pytest.mark.parametrize("patch,reason", [
    ({"target_id": "d"*64}, "OUTCOME_TARGET_MISMATCH"),
    ({"status": "LIVE"}, "RESOLVED_OUTCOME_REQUIRES"),
    ({"settled_at_utc": "2026-01-10T20:00:00Z"}, "SETTLEMENT_CHRONOLOGY"),
    ({"observed_at_utc": "2099-01-01T00:00:00Z"}, "OBSERVATION_FROM_FUTURE"),
    ({"source_sha256": "not a hash"}, "SHA256_REQUIRED"),
])
def test_hostile_settlements_rejected(tmp_path, patch, reason):
    manifest, _ = packet(tmp_path)
    edit_ref(manifest, "outcomes", lambda x: x[0].update(patch))
    with pytest.raises(ValueError, match=reason):
        evaluate(manifest)


def test_population_cannot_drop_blocked_event(tmp_path):
    manifest, _ = packet(tmp_path)
    edit_ref(manifest, "population", lambda x: x.clear())
    with pytest.raises(ValueError, match="EVERY_POPULATION_EVENT"):
        evaluate(manifest)


def test_replay_cannot_be_declared_confirmation(tmp_path):
    manifest, _ = packet(tmp_path)
    value = json.loads(manifest.read_text())
    value["evidence_scope"] = "CONFIRMATION"
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="PROSPECTIVE_REGISTRATION"):
        evaluate(manifest)


def test_control_must_be_same_target_and_available_at_original_decision(tmp_path):
    manifest, forecast = packet(tmp_path)
    forecast.pop("forecast_id")
    forecast["forecast_created_at_utc"] = "2026-01-10T23:03:00Z"
    control = seal_forecast(forecast)
    path = tmp_path / "controls.json"
    path.write_text(json.dumps([control]))
    value = json.loads(manifest.read_text())
    value["controls"] = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="CONTROL_NOT_AVAILABLE"):
        evaluate(manifest)
    forecast["forecast_created_at_utc"] = "2026-01-10T23:01:00Z"
    edit_ref(manifest, "controls", lambda x: x.__setitem__(0, seal_forecast(forecast)))
    assert evaluate(manifest)["report"]["full_slate_same_event_control"]["n"] == 1


def test_real_evaluation_cli_writes_new_child_and_refuses_overwrite(tmp_path):
    manifest, _ = packet(tmp_path)
    output = tmp_path / "new-evaluation"
    command = [sys.executable, str(ROOT / "scripts/evaluate_research_selections.py"),
               "--manifest", str(manifest), "--output-dir", str(output), "--bootstrap-samples", "20"]
    one = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert one.returncode == 0, one.stderr
    saved = (output / "evaluation.json").read_bytes()
    receipt = json.loads((output / "receipt.json").read_text())
    assert receipt["evaluation_sha256"] == hashlib.sha256(saved).hexdigest()
    two = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert two.returncode == 2 and "ALREADY_EXISTS" in two.stderr
    assert (output / "evaluation.json").read_bytes() == saved


def test_card_receipt_exposes_april_state_without_changing_frozen_inputs_or_probabilities():
    event = {"event_id": "NBA:test", "home_id": "1", "away_id": "2",
             "start_time_utc": "2026-10-23T01:00:00Z", "neutral_site": False}
    state = {team: {"last": "2026-04-13T00:30:00Z", "n": 82, "for": 110, "against": 105} for team in ("1", "2")}
    features = feature(state, event, 105)
    package = {"model_id": IDS["nba"], "team_state": state, "model_sha256": "a"*64,
               "training_cutoff_utc": "2026-10-22T00:00:00Z"}
    raw = {"model_id": IDS["nba"], "model_p": .537, "sim_p": .536,
           "model_input_snapshot": features, "input_snapshot_hash": digest(features),
           "model_state_config_hash": "a"*64, "diagnostics": {"home_margin": -.28}}
    before = copy.deepcopy(raw)
    result = attach_state_receipt(raw, event, {"package": package, "cutoff": "2026-10-22T06:00:00Z"}, "nba")
    receipt = result["diagnostics"].pop("state_freshness_receipt")
    assert receipt["per_side"]["home"]["consumed_state_last_start_utc"].startswith("2026-04-13")
    assert receipt["per_side"]["home"]["state_age_at_cutoff_hours"] > 4000
    assert receipt["per_side"]["home"]["feature_matches_consumed_state"] is True
    assert raw == before == result


def test_receipt_parent_hash_mismatch_is_visible_without_erasing_raw_evidence():
    event = {"event_id": "NBA:test", "home_id": "1", "away_id": "2", "start_time_utc": "2026-10-23T01:00:00Z"}
    package = {"model_id": IDS["nba"], "team_state": {}, "model_sha256": "a"*64}
    raw = {"model_id": IDS["nba"], "model_p": .6, "model_input_snapshot": {"home_rest": 14., "away_rest": 14.},
           "input_snapshot_hash": "wrong", "model_state_config_hash": "a"*64}
    result = attach_state_receipt(raw, event, {"package": package, "cutoff": "2026-10-22T06:00:00Z"}, "nba")
    assert result["model_p"] == .6
    assert "PARENT_HASH_MISMATCH" in result["diagnostics"]["state_freshness_receipt_error"]
    assert "diagnostics" not in raw
