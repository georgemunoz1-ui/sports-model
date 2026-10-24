"""Hand-oracle and adversarial checks for paired efficiency forecast scoring."""
from copy import deepcopy
import json
import math

import numpy as np
import pytest

from research.efficiency.evaluation import EvaluationError, evaluate


def row(event="A", *, day="2025-01-01", block="2025-W01", season=2025,
        home_win=1, margin=10, total=210, p=.6, q=.8):
    return {"event_id": event, "season": season, "block_id": block,
            "start_time_utc": day+"T20:00:00Z", "actual_home_win": home_win,
            "actual_home_margin": margin, "actual_total": total,
            "baseline": {"model_id": "control.v1", "p_home": p, "home_margin": 6., "total": 220.},
            "challenger": {"model_id": "candidate.v1", "p_home": q, "home_margin": 8., "total": 214.}}


def test_hand_oracle_and_insufficient_block_interval():
    report = evaluate([row()], bootstrap_count=100)
    winner = report["products"]["winner"]
    assert winner["baseline"]["brier"] == pytest.approx(.16)
    assert winner["challenger"]["brier"] == pytest.approx(.04)
    assert winner["delta"]["brier"]["estimate"] == pytest.approx(-.12)
    assert winner["baseline"]["log_loss"] == pytest.approx(-math.log(.6))
    assert winner["delta"]["brier"]["status"] == "INSUFFICIENT_BLOCKS"
    assert winner["delta"]["brier"]["ci_lower"] is None
    assert report["products"]["home_margin"]["baseline"]["mae"] == 4
    assert report["products"]["total"]["challenger"]["rmse"] == 4
    assert report["promotion"] is False and report["action_authority"] is False
    json.dumps(report, allow_nan=False)


def test_missing_total_head_never_imputes_cfb_control():
    a = row()
    a["baseline"]["total"] = None
    report = evaluate([a], bootstrap_count=10)
    assert report["products"]["winner"]["n_paired"] == 1
    total = report["products"]["total"]
    assert total["n_population"] == 1 and total["n_paired"] == 0
    assert total["exclusions"] == [{"event_id": "A", "reasons": ["BASELINE_HEAD_UNAVAILABLE"]}]
    assert total["baseline"]["mae"] is None
    assert total["challenger"]["mae"] is None


def test_per_product_pairing_and_cohorts():
    a, b = row(), row("B", day="2026-01-01", season=2026, block="2026-W01")
    b["challenger"]["p_home"] = None
    report = evaluate([b, a], bootstrap_count=10)
    assert report["n_events"] == 2
    assert report["products"]["winner"]["n_paired"] == 1
    assert report["products"]["home_margin"]["n_paired"] == 2
    assert report["seasons"]["2026"]["products"]["winner"]["n_paired"] == 0
    assert report["period"]["first_start_time_utc"].startswith("2025")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "0.7", -0.1, 1.1])
def test_invalid_probability_refused(value):
    a = row(); a["challenger"]["p_home"] = value
    with pytest.raises(EvaluationError):
        evaluate([a])


@pytest.mark.parametrize("patch", [
    {"actual_home_win": 0}, {"actual_home_win": .5}, {"actual_home_win": True},
    {"actual_home_margin": 0}, {"actual_home_margin": 9}, {"actual_total": 9},
    {"actual_total": float("nan")}, {"actual_home_margin": 10.5},
    {"start_time_utc": "2025-01-01T20:00:00"},
])
def test_wrong_outcomes_and_chronology_refused(patch):
    a = row(); a.update(patch)
    with pytest.raises(EvaluationError):
        evaluate([a])


def test_duplicate_event_and_mixed_model_rejected():
    with pytest.raises(EvaluationError, match="DUPLICATE_EVENT"):
        evaluate([row(), row()])
    a, b = row(), row("B")
    b["challenger"]["model_id"] = "candidate.v2"
    with pytest.raises(EvaluationError, match="MIXED_ARM_IDENTITY"):
        evaluate([a, b])


def test_missing_identity_cannot_mix_with_named_arm():
    a, b = row(), row("B")
    b["baseline"].pop("model_id")
    with pytest.raises(EvaluationError, match="MIXED_ARM_IDENTITY"):
        evaluate([a, b])


@pytest.mark.parametrize("key", ["orientation", "probability_orientation", "margin_orientation"])
def test_explicit_away_orientation_refused(key):
    a = row(); a["baseline"][key] = "away"
    with pytest.raises(EvaluationError, match="HOME_ORIENTATION_REQUIRED"):
        evaluate([a])


def test_independent_winner_and_mean_heads_may_disagree():
    a = row(); a["challenger"].update(p_home=.4, home_margin=8.)
    assert evaluate([a], bootstrap_count=10)["products"]["winner"]["n_paired"] == 1


def test_forecast_for_wrong_event_refused():
    a = row(); a["baseline"]["event_id"] = "B"
    with pytest.raises(EvaluationError, match="FORECAST_EVENT_MISMATCH"):
        evaluate([a])


def test_exact_zero_probability_not_silently_clipped():
    a, b = row(q=0.), row("B", day="2025-01-08", block="2025-W02")
    report = evaluate([a, b], bootstrap_count=10)
    winner = report["products"]["winner"]
    assert winner["challenger"]["log_loss"] is None
    assert winner["challenger"]["infinite_log_loss_count"] == 1
    assert winner["delta"]["log_loss"]["status"] == "UNAVAILABLE_INFINITE_LOG_LOSS"
    assert winner["delta"]["brier"]["status"] == "AVAILABLE"
    assert winner["n_paired"] == 2
    json.dumps(report, allow_nan=False)


def test_whole_blocks_weight_events_and_rmse_correctly():
    rows = [row("A"), row("B"), row("C", day="2025-01-08", block="2025-W02")]
    rows[0]["baseline"]["home_margin"] = 10
    rows[1]["baseline"]["home_margin"] = 10
    rows[2]["baseline"]["home_margin"] = 1
    for r in rows:
        r["challenger"]["home_margin"] = 7
    report = evaluate(rows, bootstrap_count=200, seed=5)
    metric = report["products"]["home_margin"]["delta"]["rmse"]
    assert metric["estimate"] == pytest.approx(3-math.sqrt(27))
    assert metric["ci_lower"] <= metric["estimate"] <= metric["ci_upper"]
    assert metric["n_blocks"] == 2
    assert report == evaluate(list(reversed(rows)), bootstrap_count=200, seed=5)


def test_constant_paired_differences_give_exact_interval():
    rows = [row("A"), row("B", day="2025-01-08", block="2025-W02")]
    d = evaluate(rows, bootstrap_count=200)["products"]["winner"]["delta"]["brier"]
    assert d["ci_lower"] == pytest.approx(-.12)
    assert d["ci_upper"] == pytest.approx(-.12)


def test_empty_report_and_input_immutability():
    report = evaluate([], bootstrap_count=10)
    assert report["n_events"] == 0
    assert report["products"]["winner"]["delta"]["brier"]["status"] == "NO_PAIRED_EVENTS"
    rows = [row()]; before = deepcopy(rows)
    evaluate(rows, bootstrap_count=10)
    assert rows == before


def test_optional_cutoff_and_feature_times_enforce_order():
    a = row(); a["forecast_cutoff_utc"] = "2025-01-01T20:00:00Z"
    with pytest.raises(EvaluationError, match="POST_START_FORECAST"):
        evaluate([a])
    a["forecast_cutoff_utc"] = "2025-01-01T19:00:00Z"
    a["challenger"]["feature_max_available_at_utc"] = "2025-01-01T19:01:00Z"
    with pytest.raises(EvaluationError, match="FUTURE_INPUT"):
        evaluate([a])


def test_block_names_must_disambiguate_seasons():
    a, b = row(), row("B", season=2026, day="2026-01-01")
    with pytest.raises(EvaluationError, match="BLOCK_SPANS_SEASONS"):
        evaluate([a, b])


@pytest.mark.parametrize("kwargs", [{"bootstrap_count": 0}, {"bootstrap_count": True}, {"seed": -1}, {"seed": True}])
def test_invalid_bootstrap_plan_refused(kwargs):
    with pytest.raises(EvaluationError):
        evaluate([row()], **kwargs)
