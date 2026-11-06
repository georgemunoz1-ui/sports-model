"""Synthetic contract tests, not evidence of personnel predictive value."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from models.experiments import cfb_efficiency as c
from models.experiments import cfb_personnel as p
from research.efficiency.runner import prepare, fit_stage, predict_stage, component_receipt
from test_cfb_efficiency_experiment import history


def with_personnel(tmp_path):
    h = history()
    for game in h["games"]:
        event = c.canonical_game(game)
        stamp = (c.utc(event["start_time_utc"]) - pd.Timedelta(days=2)).isoformat()
        evidence = {"schema": p.SCHEMA, "event_id": event["event_id"]}
        for side in ("home", "away"):
            path = tmp_path / (event["event_id"].replace(":", "_") + side + ".json")
            evidence[side] = {"team_id": event[side + "_id"],
                "quarterback": {"player_id": "QB-" + event[side + "_id"], "status": "PROJECTED",
                    "expected_participation_probability": .8 if side == "home" else .6,
                    "participation_method": "SYNTHETIC_ASSUMPTION_NOT_A_FIT",
                    "workload_limitations": ["fixture"],
                    "prior_pass_attempt_share": {"numerator": 18, "denominator": 20, "population_definition": "prior game"}},
                "returning_snaps": {unit: {"numerator": 40, "denominator": 50, "population_definition": "prior game"}
                                    for unit in ("offense", "defense")},
                "sources": [{"source": "synthetic://personnel", "path": str(path),
                    "sha256": None, "event_id": event["event_id"],
                    "team_id": event[side + "_id"], "observed_at_utc": stamp,
                    "retrieved_at_utc": stamp, "available_at_utc": stamp,
                    "field_bindings": {field: "/" + field.replace(".", "/") for field in p.SOURCED_FIELDS}}]}
            side_record = evidence[side]
            raw = json.dumps({"event_id": event["event_id"], "team_id": event[side + "_id"],
                "quarterback": {key: side_record["quarterback"][key] for key in
                ("player_id", "status", "prior_pass_attempt_share")}, "returning_snaps": side_record["returning_snaps"]}).encode()
            path.write_bytes(raw)
            source = side_record["sources"][0]
            source["sha256"] = hashlib.sha256(raw).hexdigest()
            assumption = {"schema": "cfb.qb-participation-assumption.v1", "event_id": event["event_id"],
                "team_id": event[side + "_id"], "created_at_utc": stamp,
                "evidence_source_sha256": [source["sha256"]],
                "assumptions": {key: side_record["quarterback"][key] for key in (
                    "player_id", "expected_participation_probability", "participation_method", "workload_limitations")}}
            assumption_raw = json.dumps(assumption).encode()
            assumption_path = path.with_name(path.stem + "-assumption.json")
            assumption_path.write_bytes(assumption_raw)
            side_record["participation_assumption"] = {"path": str(assumption_path),
                "sha256": hashlib.sha256(assumption_raw).hexdigest()}
        game["personnel_evidence"] = evidence
    return h


def final_example(tmp_path):
    return c.prepare_examples(with_personnel(tmp_path))[-1]


def test_transport_preserves_baseline_values_and_constructs_explicit_features(tmp_path):
    original = c.prepare_examples(history())
    enhanced = prepare("cfb", with_personnel(tmp_path))
    assert [r["features"] for r in original] == [r["features"] for r in enhanced]
    assert [r["eligible"] for r in original] == [r["eligible"] for r in enhanced]
    row = enhanced[-1]
    assert p.values(row) == {"home_qb_availability": .8, "away_qb_availability": .6,
        "home_offense_returning_snap_share": .8, "home_defense_returning_snap_share": .8,
        "away_offense_returning_snap_share": .8, "away_defense_returning_snap_share": .8}
    assert row["personnel_schedule_coverage"]["provider_schedule_completeness"] == "NOT_ESTABLISHED"


@pytest.mark.parametrize("bad", [None, "UNKNOWN", "OUT", "AVAILABLE"])
def test_status_never_invents_confirmed_starter_or_availability(tmp_path, bad):
    row = final_example(tmp_path)
    row["personnel_evidence"]["home"]["quarterback"]["status"] = bad
    with pytest.raises(ValueError, match="QUARTERBACK_UNKNOWN"):
        p.values(row)


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -0.1, 1.1, "1"])
def test_invalid_participation_is_not_coerced(tmp_path, bad):
    row = final_example(tmp_path)
    row["personnel_evidence"]["home"]["quarterback"]["expected_participation_probability"] = bad
    with pytest.raises(ValueError, match="CFB_PERSONNEL"):
        p.values(row)


def test_source_event_team_and_bytes_are_bound(tmp_path):
    row = final_example(tmp_path)
    source = row["personnel_evidence"]["home"]["sources"][0]
    original = copy.deepcopy(source)
    source["team_id"] = "wrong"
    with pytest.raises(ValueError, match="SOURCE_IDENTITY_MISMATCH"):
        p.values(row)
    source.update(original)
    Path(source["path"]).write_text("changed")
    with pytest.raises(ValueError, match="SOURCE_BYTES_MISMATCH"):
        p.values(row)


def test_late_or_unbound_personnel_remains_blocked(tmp_path):
    row = final_example(tmp_path)
    source = row["personnel_evidence"]["away"]["sources"][0]
    source["retrieved_at_utc"] = row["cutoff_utc"]
    with pytest.raises(ValueError, match="AFTER_CUTOFF"):
        p.values(row)
    source["retrieved_at_utc"] = source["observed_at_utc"]
    source["field_bindings"] = {"quarterback.player_id": "/quarterback/player_id"}
    with pytest.raises(ValueError, match="SOURCE_FIELD_COVERAGE_INCOMPLETE"):
        p.values(row)


def test_missing_nonlatest_single_team_record_blocks_only_v2(tmp_path):
    h = with_personnel(tmp_path)
    missing = h["team_games"].pop(-8)
    row = c.prepare_examples(h)[-1]
    assert row["eligible"]  # legacy v1 policy remains explicitly unchanged
    assert [missing["event_id"], missing["team_id"]] in row["personnel_schedule_coverage"]["missing_team_game_rows"]
    with pytest.raises(ValueError, match="INCOMPLETE_SCHEDULE_HISTORY"):
        p.values(row)


def test_fcs_coverage_does_not_grant_cross_population_eligibility(tmp_path):
    h = with_personnel(tmp_path)
    event = c.canonical_game(h["games"][-1])
    event["away_division"] = "fcs"
    report = p.schedule_coverage([c.canonical_game(g) for g in h["games"]], h["team_games"], event,
                                 c.utc(event["start_time_utc"]) - pd.Timedelta(seconds=1))
    assert report["matchup_supported"] is False
    assert report["cross_population_validation"] == "NOT_ASSESSED"


def test_personnel_v2_fit_predict_and_real_runner_receipt(tmp_path):
    h = with_personnel(tmp_path)
    rows = prepare("cfb", h)
    train = [r for r in rows if r["season"] <= 2024]
    state = c.fit_personnel_v2(train, {"minimum_training_rows": 10})
    prediction = predict_stage(c, "cfb", state, rows[-1])
    assert state["model_id"] == c.PERSONNEL_V2_ID
    assert state["parent_personnel_model_id"] == c.PERSONNEL_ID
    assert prediction["personnel_consumption"]["feature_values"] == p.values(rows[-1])
    assert "NO_PERSONNEL_FEATURES" not in prediction["limitations"]
    receipt = component_receipt("cfb", "personnel_v2", rows[-1], state, prediction, h, mode="HISTORICAL_REPLAY")
    assert receipt["inputs"]["consumed_personnel_features"] == p.values(rows[-1])
    assert receipt["forecast"]["personnel_consumption"] == prediction["personnel_consumption"]
    assert all(s["bytes_verified"] for s in receipt["sources"] if s["source"] == "synthetic://personnel")
    assert prediction["action_authority"] is False


def test_v1_personnel_replay_retains_original_identity(tmp_path):
    rows = c.prepare_examples(history())
    for row in rows:
        row["personnel_features"] = {key: .5 for key in c.PERSONNEL_FEATURES}
        row["personnel_sources"] = [{"source": "synthetic://legacy", "sha256": "a" * 64,
            "available_at_utc": (c.utc(row["cutoff_utc"]) - pd.Timedelta(days=1)).isoformat()}]
    state = c.fit_personnel([r for r in rows if r["season"] <= 2024], {"minimum_training_rows": 10})
    assert state["model_id"] == c.LEGACY_PERSONNEL_ID
    assert state["stage_id"] == "personnel"
    assert "personnel_consumption" not in c.predict(state, rows[-1])


def test_new_stage_dispatch_and_cli_are_opt_in():
    class Module:
        def fit_personnel_v2(self, rows):
            return {"received": rows}
    assert fit_stage(Module(), "cfb", [1], "personnel_v2") == {"received": [1]}
    with pytest.raises(ValueError, match="CFB_ONLY"):
        fit_stage(Module(), "nba", [], "personnel_v2")
    result = subprocess.run([sys.executable, "scripts/run_efficiency_experiments.py", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "personnel_v2" in result.stdout


@pytest.mark.parametrize("field,value", [
    ("quarterback.player_id", "unbound-player"),
    ("quarterback.status", "CONFIRMED"),
    ("quarterback.prior_pass_attempt_share.numerator", 17),
    ("returning_snaps.offense.numerator", 39),
    ("returning_snaps.defense.population_definition", "different population")])
def test_changed_source_fields_cannot_reuse_original_bytes(tmp_path, field, value):
    row = final_example(tmp_path)
    record = row["personnel_evidence"]["home"]
    target = record
    parts = field.split(".")
    for key in parts[:-1]:
        target = target[key]
    target[parts[-1]] = value
    with pytest.raises(ValueError, match="SOURCE_VALUE_MISMATCH"):
        p.values(row)


@pytest.mark.parametrize("field,value", [
    ("expected_participation_probability", .2),
    ("participation_method", "different scenario"),
    ("workload_limitations", [])])
def test_changed_assumption_requires_a_new_bound_record(tmp_path, field, value):
    row = final_example(tmp_path)
    row["personnel_evidence"]["home"]["quarterback"][field] = value
    with pytest.raises(ValueError, match="ASSUMPTION_VALUE_MISMATCH"):
        p.values(row)


def test_future_event_personnel_overlay_is_consumed_and_identity_checked(tmp_path):
    h = history()
    future = copy.deepcopy(with_personnel(tmp_path)["games"][-1])
    future = c.canonical_game(future)
    h["games"][-1]["completed"] = False
    future["completed"] = False
    row = prepare("cfb", h, future_events=[future])[-1]
    assert row["personnel_evidence"] == future["personnel_evidence"]
    assert p.values(row)["home_qb_availability"] == .8
    with pytest.raises(ValueError, match="DUPLICATE_FUTURE_EVENT"):
        prepare("cfb", h, future_events=[future, future])
    with pytest.raises(ValueError, match="FUTURE_EVENT_NOT_IN_HISTORY"):
        prepare("cfb", {**h, "games": h["games"][:-1]}, future_events=[future])
    future["home_id"] = "999"
    with pytest.raises(ValueError, match="FUTURE_EVENT_IDENTITY_CONFLICT"):
        prepare("cfb", h, future_events=[future])


def test_schedule_semantics_conflict_cannot_hide_an_excluded_state_row(tmp_path):
    h = with_personnel(tmp_path)
    h["team_games"][-8]["season"] = 2099
    row = c.prepare_examples(h)[-1]
    assert row["eligible"]  # existing v1 scope is unchanged
    assert row["personnel_schedule_coverage"]["status"] == "INCOMPLETE"
    with pytest.raises(ValueError, match="SCHEDULE_SEASON_WEEK_MISMATCH"):
        p.values(row)


@pytest.mark.parametrize("flags", [{"control": True}, {"matched_control": True}, {"personnel": True}])
def test_v2_cannot_claim_another_fitted_identity(flags):
    with pytest.raises(ValueError, match="INCOMPATIBLE_FIT_FLAGS"):
        c.fit([], personnel_v2=True, **flags)
