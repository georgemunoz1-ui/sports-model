"""Integrity tests use synthetic evidence and do not establish model performance."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from research.efficiency.integrity import (
    IntegrityError, build_component_receipt, reconcile_nba_game, reconcile_rate,
    reconcile_sources, reconcile_team_boxscore, resolve_event_identity,
    verify_component_receipt, write_shadow_receipt,
)
from research.validation_registry import ArtifactStore, content_id

NOW = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
CUTOFF = "2030-01-01T11:59:00Z"
START = "2030-01-01T13:00:00Z"


@pytest.fixture
def args(tmp_path):
    source = tmp_path / "source.json"
    source.write_text('{"event_id":"prior","points":100}')
    return dict(model_id="nba.possession_efficiency.research.v1", stage_id="EFFICIENCY",
        event_id="NBA:1", cutoff_utc=CUTOFF, start_utc=START,
        inputs={"home": {"pace": 99}, "history_event_ids": ["prior"]},
        state={"coefficient": 0.9}, config={"prior_weight": 10},
        code_files=[__file__],
        sources=[{"source": "https://example.invalid/test-only", "path": str(source),
                  "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                  "retrieved_at_utc": "2030-01-01T11:50:00Z"}],
        components={"expected_possessions": {"value": 99.2, "unit": "possessions",
                    "input_paths": ["home.pace"]}, "home_ppp": 1.1},
        forecast={"home_score": 109.12, "away_score": 105.3, "p_home": 0.6},
        mode="SHADOW", history_max_event_time_utc="2029-12-31T04:00:00Z")


def build(args):
    with patch("research.efficiency.integrity._now", return_value=NOW):
        return build_component_receipt(**args)


def resign(receipt):
    value = copy.deepcopy(receipt)
    value.pop("receipt_sha256", None)
    value["receipt_sha256"] = content_id(value)
    return value


def team():
    return dict(points=100, fgm=35, fga=80, fg3m=10, fg3a=30, ftm=20, fta=25,
                orb=10, drb=30, tov=12, rebounds=40, team_orb=3, team_drb=2)


def players():
    return [dict(player_id=str(i), minutes=48.0, points=20, status="PLAYED", orb=2, drb=6)
            for i in range(5)]


def test_receipt_binds_actual_components_and_retained_bytes(args):
    receipt = build(args)
    assert verify_component_receipt(receipt) == receipt
    assert receipt["components"]["home_ppp"]["status"] == "USED"
    assert receipt["components"]["home_ppp"]["input_snapshot_sha256"] == content_id(args["inputs"])
    assert receipt["sources"][0]["bytes_verified"]
    assert not receipt["canonical_prospective_eligible"]
    assert not receipt["action_authority"]


@pytest.mark.parametrize("payload,key,bad,error", [
    ("event", "event_id", "NBA:OTHER", "EVENT_IDENTITY"),
    ("forecast", "event_id", "NBA:OTHER", "EVENT_IDENTITY"),
    ("event", "start_time_utc", "2030-01-01T14:00:00Z", "EVENT_START"),
    ("event", "forecast_cutoff_utc", "2030-01-01T11:58:00Z", "EVENT_CUTOFF"),
    ("state", "model_id", "other.model", "MODEL_IDENTITY"),
    ("forecast", "model_id", "other.model", "MODEL_IDENTITY"),
    ("state", "stage", "joint", "STAGE_IDENTITY"),
    ("forecast", "stage_id", "joint", "STAGE_IDENTITY"),
    ("forecast", "model_state_sha256", "b" * 64, "FORECAST_STATE"),
])
def test_builder_rejects_contradictory_inference_identity(args, payload, key, bad, error):
    args["inputs"]["event"] = {"event_id": args["event_id"], "start_time_utc": START,
                                "forecast_cutoff_utc": CUTOFF}
    args["state"].update(model_id=args["model_id"], stage="efficiency", state_sha256="a" * 64)
    args["forecast"].update(model_id=args["model_id"], event_id=args["event_id"],
                            stage_id="efficiency", model_state_sha256="a" * 64)
    target = args["inputs"]["event"] if payload == "event" else args[payload]
    target[key] = bad
    with pytest.raises(IntegrityError, match=error):
        build(args)


@pytest.mark.parametrize("field,replacement,error", [
    ("event_id", "NBA:OTHER", "EVENT_IDENTITY"),
    ("model_id", "other.model", "MODEL_IDENTITY"),
    ("stage_id", "joint", "STAGE_IDENTITY"),
    ("start_utc", "2030-01-01T14:00:00Z", "EVENT_START"),
    ("cutoff_utc", "2030-01-01T11:58:00Z", "EVENT_CUTOFF"),
])
def test_resigned_envelope_cannot_relabel_retained_inference(args, field, replacement, error):
    args["inputs"]["event"] = {"event_id": args["event_id"], "start_time_utc": START,
                                "forecast_cutoff_utc": CUTOFF}
    args["state"].update(model_id=args["model_id"], stage="efficiency")
    args["forecast"].update(model_id=args["model_id"], event_id=args["event_id"], stage="efficiency")
    receipt = build(args)
    receipt[field] = replacement
    with pytest.raises(IntegrityError, match=error):
        verify_component_receipt(resign(receipt))


def test_existing_cfb_stage_alias_and_equal_timezones_remain_valid(args):
    args["inputs"]["event"] = {"event_id": args["event_id"],
                                "start_time_utc": "2030-01-01T08:00:00-05:00"}
    args["state"]["stage_id"] = "matchup_efficiency"
    args["forecast"]["stage_id"] = "matchup_efficiency"
    receipt = build(args)
    assert verify_component_receipt(receipt) == receipt


def test_component_or_snapshot_mutation_rejected(args):
    receipt = build(args)
    receipt["components"]["home_ppp"]["value"] = 1.3
    with pytest.raises(IntegrityError, match="RECEIPT_HASH"):
        verify_component_receipt(receipt)
    with pytest.raises(IntegrityError, match="TRACE_HASH"):
        verify_component_receipt(resign(receipt))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "0.8", None])
def test_invalid_used_components_rejected(args, bad):
    args["components"]["home_ppp"] = bad
    with pytest.raises(IntegrityError):
        build(args)


@pytest.mark.parametrize("bad", [-0.1, 1.1, True, float("nan")])
def test_invalid_forecast_probability_rejected(args, bad):
    args["forecast"]["p_home"] = bad
    with pytest.raises(IntegrityError):
        build(args)


def test_unsupported_total_is_null_and_disclosed_not_zero(args):
    args["forecast"]["total"] = None
    receipt = build(args)
    assert receipt["forecast"]["total"] is None
    assert receipt["unsupported_forecast_fields"] == ["total"]
    verify_component_receipt(receipt)
    receipt["unsupported_forecast_fields"] = []
    with pytest.raises(IntegrityError, match="UNSUPPORTED_FORECAST_FIELD"):
        verify_component_receipt(resign(receipt))


def test_component_names_a_real_input_path(args):
    args["components"]["expected_possessions"]["input_paths"] = ["away.missing"]
    with pytest.raises(IntegrityError, match="INPUT_PATH_MISSING"):
        build(args)


def test_component_unknown_source_rejected(args):
    args["components"]["expected_possessions"]["source_sha256"] = ["f" * 64]
    with pytest.raises(IntegrityError, match="SOURCE_NOT_BOUND"):
        build(args)


@pytest.mark.parametrize("field", ["history_max_event_time_utc", "input_max_available_at_utc"])
def test_future_feature_or_label_rejected(args, field):
    args[field] = "2030-01-01T12:30:00Z"
    with pytest.raises(IntegrityError, match="FEATURE_OR_LABEL_AFTER_CUTOFF"):
        build(args)


def test_future_component_rejected(args):
    args["components"]["expected_possessions"]["max_available_at_utc"] = START
    with pytest.raises(IntegrityError, match="COMPONENT_AFTER_CUTOFF"):
        build(args)


def test_source_hash_is_checked(args):
    Path(args["sources"][0]["path"]).write_text("changed")
    with pytest.raises(IntegrityError, match="SOURCE_BYTES_HASH_MISMATCH"):
        build(args)


def test_late_source_cannot_enter_live_shadow(args):
    args["sources"][0]["retrieved_at_utc"] = "2030-01-01T12:00:00Z"
    with pytest.raises(IntegrityError, match="SOURCE_AFTER_CUTOFF"):
        build(args)


def test_later_historical_retrieval_disclosed_not_backdated(args, tmp_path):
    args["mode"] = "HISTORICAL_REPLAY"
    args["sources"][0]["retrieved_at_utc"] = "2030-01-01T12:00:00Z"
    receipt = build(args)
    assert receipt["sources"][0]["historical_availability_status"] == "UNVERIFIED_LATER_RECONSTRUCTION"
    with pytest.raises(IntegrityError, match="REPLAY_CANNOT_REGISTER"):
        write_shadow_receipt(receipt, tmp_path / "shadow")
    assert not (tmp_path / "shadow").exists()


def test_declared_historical_availability_requires_evidence(args):
    args["sources"][0]["historical_available_at_utc"] = "2029-12-31T23:00:00Z"
    with pytest.raises(IntegrityError, match="SHA256_REQUIRED"):
        build(args)


def test_naive_timestamp_rejected(args):
    args["cutoff_utc"] = "2030-01-01T11:59:00"
    with pytest.raises(IntegrityError, match="NAIVE_TIMESTAMP"):
        build(args)


def test_stage_inherits_parent_reference_not_parent_identity(args):
    args["parent_model_id"] = args["model_id"]
    with pytest.raises(IntegrityError, match="DISTINCT_IDENTITY"):
        build(args)


def test_simulation_metadata_is_explicit(args):
    args["simulation"] = dict(count=100000, seed=12, rng="PCG64", distribution_id="TEST_ONLY",
                              draws_encoding="numpy-int64", draws_sha256="a" * 64)
    assert build(args)["simulation"]["count"] == 100000
    assert build(args)["simulation"]["draws_verification"] == "METADATA_ONLY_NO_DRAW_FILE"
    args["simulation"]["count"] = True
    with pytest.raises(IntegrityError, match="SIMULATION_COUNT"):
        build(args)


def test_simulation_array_count_and_bytes_are_actually_verified(args, tmp_path):
    import numpy as np
    draws = np.array([[99, 101], [102, 100]], dtype="int64")
    path = tmp_path / "draws.npy"; np.save(path, draws, allow_pickle=False)
    args["simulation"] = dict(count=2, seed=12, rng="PCG64", distribution_id="TEST_ONLY",
                              draws_encoding="numpy-int64", draws_path=str(path),
                              draws_file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                              draws_sha256=hashlib.sha256(draws.tobytes()).hexdigest())
    assert build(args)["simulation"]["draws_verification"] == "ARRAY_COUNT_AND_HASH_VERIFIED"
    args["simulation"]["count"] = 3
    with pytest.raises(IntegrityError, match="DRAW_COUNT"):
        build(args)


def test_market_and_action_firewall(args):
    args["inputs"]["nested"] = {"market_features_used": True}
    with pytest.raises(IntegrityError, match="MARKET_ACTION_FIREWALL"):
        build(args)


def test_before_start_writer_uses_own_clock_and_refuses_overwrite(args, tmp_path):
    receipt = build(args)
    root = tmp_path / "shadow"
    with patch("research.efficiency.integrity._now", return_value=NOW + timedelta(seconds=5)):
        registration = write_shadow_receipt(receipt, root)
    assert registration["registered_at_utc"] == "2030-01-01T12:00:05Z"
    assert not registration["external_timestamp_verified"]
    assert not registration["canonical_prospective_eligible"]
    assert ArtifactStore(root / "components").read(registration["component_artifact_id"]) == receipt
    original = Path(registration["registration_path"]).read_bytes()
    with pytest.raises(IntegrityError, match="ALREADY_REGISTERED"):
        write_shadow_receipt(receipt, root)
    assert original == Path(registration["registration_path"]).read_bytes()


@pytest.mark.parametrize("delay", [timedelta(hours=1), timedelta(hours=2)])
def test_at_or_after_start_writer_rejects_without_components(args, tmp_path, delay):
    receipt = build(args)
    root = tmp_path / "shadow"
    with patch("research.efficiency.integrity._now", return_value=NOW + delay):
        with pytest.raises(IntegrityError, match="NOT_PREGAME"):
            write_shadow_receipt(receipt, root)
    assert not (root / "components").exists()
    assert not (root / "registrations").exists()


def test_actual_clock_has_no_callers_backdate_argument(args, tmp_path):
    receipt = build(args)
    with pytest.raises(TypeError):
        write_shadow_receipt(receipt, tmp_path / "shadow", now="2030-01-01T12:01:00Z")


def test_score_identity_reconciles():
    assert reconcile_team_boxscore(team(), players())["status"] == "PASS"
    bad = team(); bad["points"] += 1
    report = reconcile_team_boxscore(bad, players())
    assert "SHOOTING_POINTS_MISMATCH" in report["issues"]
    assert "PLAYER_POINTS_SUM_MISMATCH" in report["issues"]


def test_dnp_with_points_is_quarantined():
    roster = players(); roster[0]["status"] = "DNP"
    assert "DNP_WITH_PRODUCTION" in reconcile_team_boxscore(team(), roster)["issues"]


def test_missing_player_points_and_minutes_not_silently_repaired():
    report = reconcile_team_boxscore(team(), players()[:-1])
    assert report["status"] == "QUARANTINED"
    assert "PLAYER_POINTS_SUM_MISMATCH" in report["issues"]
    assert "PLAYER_MINUTES_SUM_MISMATCH" in report["issues"]


def test_duplicate_player_id_rejected():
    roster = players(); roster[1]["player_id"] = roster[0]["player_id"]
    assert "DUPLICATE_PLAYER_ID" in reconcile_team_boxscore(team(), roster)["issues"]


def test_team_rebounds_are_not_double_counted():
    assert reconcile_team_boxscore(team(), players())["status"] == "PASS"
    bad = team(); bad["orb"] += bad["team_orb"]
    assert "PLAYER_REBOUND_TOTAL_MISMATCH" in reconcile_team_boxscore(bad, players())["issues"]
    bad = team(); bad["rebound_scope"] = "PLAYER_AND_TEAM_UNKNOWN"
    assert "AMBIGUOUS_REBOUND_SCOPE" in reconcile_team_boxscore(bad)["issues"]


def test_overtime_minutes_contract():
    roster = players()
    for p in roster: p["minutes"] = 53
    assert reconcile_team_boxscore(team(), roster, overtime_periods=1)["status"] == "PASS"
    assert reconcile_team_boxscore(team(), roster)["status"] == "QUARANTINED"


def test_declared_integer_minutes_rounding_is_not_exact_seconds():
    roster = [dict(player_id=str(i), minutes=24.0, points=10, status="PLAYED") for i in range(10)]
    roster[0]["minutes"] = 26.0  # Provider-rounded sum is 242; ten rounded values permit +/-5.
    assert reconcile_team_boxscore(team(), roster, minutes_decimal_places=0)["status"] == "PASS"
    assert reconcile_team_boxscore(team(), roster, minutes_decimal_places=1)["status"] == "QUARANTINED"


def test_summary_without_player_rows_does_not_claim_player_reconciliation():
    report = reconcile_team_boxscore(team())
    assert report["status"] == "PASS"
    assert report["player_table_checked"] is False


@pytest.mark.parametrize("bad", [True, float("inf"), -1, 5.5])
def test_noninteger_or_invalid_counts_rejected(bad):
    value = team(); value["tov"] = bad
    assert reconcile_team_boxscore(value)["status"] == "QUARANTINED"


def test_attempt_denominators():
    assert reconcile_rate(3, 10, reported_rate=0.3)["status"] == "PASS"
    assert reconcile_rate(0, 0)["status"] == "QUARANTINED"
    assert reconcile_rate(11, 10)["status"] == "QUARANTINED"
    assert reconcile_rate(3, 10, reported_rate=0.4)["status"] == "QUARANTINED"
    assert reconcile_rate(-4, 10, bounded=False)["rate"] == -0.4


def test_conflicting_sources_retained_without_priority_guess():
    rows = [dict(event_id="1", team_id="DEN", points=84), dict(event_id="1", team_id="DEN", points=79)]
    report = reconcile_sources(rows)
    assert report["status"] == "QUARANTINED"
    assert report["selected_source"] is None
    assert rows[1]["points"] == 79


def test_event_scoped_aliases_and_id_conflicts():
    participants = [{"id": "166", "name": "New Mexico State Aggies", "verified_aliases": ["New Mexico State"]},
                    {"id": "2534", "name": "Sam Houston Bearkats", "verified_aliases": ["Sam Houston"]}]
    assert resolve_event_identity(provider_id=None, name="New Mexico State", participants=participants)["resolved_id"] == "166"
    assert resolve_event_identity(provider_id="2534", name="New Mexico State", participants=participants)["status"] == "QUARANTINED"
    participants[1]["verified_aliases"].append("New Mexico State")
    assert resolve_event_identity(provider_id=None, name="New Mexico State", participants=participants)["status"] == "QUARANTINED"


def test_nba_normalized_game_wrapper():
    game = dict(event_id="NBA:1", home_id="A", away_id="B", home_score=100, away_score=100,
                home_stats=team(), away_stats=team())
    assert reconcile_nba_game(game)["status"] == "PASS"
    game["away_score"] = 101
    assert reconcile_nba_game(game)["status"] == "QUARANTINED"
