import copy
import math

import pytest

from research.efficiency.selection_diagnostics import (
    analyze, fixed_grid_curve, probability_diagnostics, normal_crps, joint_diagnostics,
)
from research.efficiency.evaluation import _rows, EvaluationError


def fixture():
    rows = []
    for i, (candidate, truth) in enumerate(((.9, 1), (.1, 1), (.65, 0))):
        rows.append({"event_id": f"NBA:{i}", "season": 2025, "block_id": f"2025-W{i//2+1:02}",
            "start_time_utc": f"2025-01-{i+1:02}T20:00:00Z", "actual_home_win": truth,
            "actual_home_margin": 2 if truth else -2, "actual_total": 20,
            "baseline": {"model_id": "baseline.v1", "p_home": .55, "home_margin": 1., "total": 20.},
            "challenger": {"model_id": "challenger.v1", "p_home": candidate, "home_margin": 1., "total": 20.}})
    population = [{"event_id": r["event_id"], "block_id": r["block_id"], "actual_home_win": r["actual_home_win"]} for r in rows]
    population.append({"event_id": "NBA:3", "block_id": "2025-W02", "actual_home_win": 1})
    return rows, population, [{"event_id": "NBA:3", "reasons": ["NO_BOX"]}]


def test_full_denominator_and_no_abstention_success():
    rows, population, excluded = fixture()
    result = analyze(rows, population, excluded, league="nba", bootstrap_count=25)
    curve = result["selectors"]["challenger"]["curve"]
    assert curve[0]["n_selected"] == 3
    assert curve[0]["coverage_all_opportunities"] == .75
    assert curve[0]["coverage_common_forecasts"] == 1
    high = next(r for r in curve if r["threshold"] == .9)
    assert high["n_selected"] == 2
    assert high["wins"] == 1 and high["losses"] == 1
    assert high["risk"] == .5
    assert curve[-1]["n_selected"] == 0 and curve[-1]["risk"] is None
    assert curve[-1]["accuracy"] is None
    assert result["operational_eligibility"]["n_selected"] == 0
    assert result["operational_eligibility"]["n_blocked"] == 4
    assert result["operational_eligibility"]["full_slate_raw_forecast_scores"]["n"] == 3
    assert result["operational_eligibility"]["selected_settlement"]["unconditional_win_accuracy"] is None
    assert result["best_selector_threshold"] is None


def test_tied_confidence_is_not_selectively_split():
    rows, population, _ = fixture()
    clean, _ = _rows(rows)
    curve = fixed_grid_curve(clean, population, "challenger", bootstrap_count=25)["curve"]
    assert next(r for r in curve if r["threshold"] == .9)["n_selected"] == 2
    assert all(r["n_selected"] != 1 for r in curve)


def test_control_home_tie_rule_survives_selected_away_target_conversion():
    rows, population, excluded = fixture()
    for row in rows:
        row["baseline"]["p_home"] = .5
    result = analyze(rows, population, excluded, league="nba", bootstrap_count=10)
    control = result["operational_eligibility"]["full_slate_same_event_control"]
    assert control["control_unconditional_win_accuracy"] == pytest.approx(2/3)
    assert control["control_unconditional_win_accuracy"] == result["forecast_metrics"]["products"]["winner"]["baseline"]["accuracy"]


def test_unavailable_events_stay_in_full_block_bootstrap():
    rows, population, _ = fixture()
    population[-1]["block_id"] = "2025-W03"
    clean, _ = _rows(rows)
    curve = fixed_grid_curve(clean, population, "challenger", bootstrap_count=50)["curve"]
    assert curve[0]["bootstrap"]["n_blocks"] == 3
    assert curve[-1]["bootstrap"]["empty_selection_resamples"] == 50


@pytest.mark.parametrize("kind", ["duplicate_population", "missing_exclusion", "predicted_excluded", "wrong_block"])
def test_population_contract_rejects_silent_denominator_changes(kind):
    rows, population, excluded = fixture()
    if kind == "duplicate_population": population.append(population[0])
    if kind == "missing_exclusion": excluded = []
    if kind == "predicted_excluded": excluded.append({"event_id": rows[0]["event_id"]})
    if kind == "wrong_block": population[0]["block_id"] = "2025-W99"
    with pytest.raises(EvaluationError):
        analyze(rows, population, excluded, league="nba", bootstrap_count=10)


def test_discovery_events_cannot_enter_evaluation():
    rows, population, excluded = fixture()
    with pytest.raises(EvaluationError, match="DISCOVERY_EVENT"):
        analyze(rows, population, excluded, league="nba", discovery_ids=[rows[0]["event_id"]], bootstrap_count=10)


def test_probability_bin_boundaries_and_zero_mass_are_not_clipped():
    rows, population, excluded = fixture()
    rows[0]["challenger"]["p_home"] = 0.
    rows[1]["challenger"]["p_home"] = 1.
    clean, _ = _rows(rows)
    diagnostics = probability_diagnostics(clean, "challenger")
    assert diagnostics["reliability_bins"][0]["n"] == 1
    assert diagnostics["reliability_bins"][-1]["n"] == 1
    result = analyze(rows, population, excluded, league="nba", bootstrap_count=10)
    assert result["forecast_metrics"]["products"]["winner"]["challenger"]["log_loss"] is None
    assert result["forecast_metrics"]["products"]["winner"]["challenger"]["infinite_log_loss_count"] == 1


def test_frozen_grid_cannot_be_replaced_after_results():
    rows, population, _ = fixture()
    clean, _ = _rows(rows)
    with pytest.raises(EvaluationError, match="FROZEN_THRESHOLD_GRID"):
        fixed_grid_curve(clean, population, "challenger", thresholds=[.731])


def test_normal_crps_at_center_and_continuous_interval_scope():
    assert normal_crps(0, 1, 0) == pytest.approx((math.sqrt(2)-1)/math.sqrt(math.pi))
    with pytest.raises(EvaluationError): normal_crps(0, 0, 0)
    rows, _, _ = fixture()
    for row in rows:
        row["challenger"].update(margin_sd=2., total_sd=4.)
    result = joint_diagnostics(rows, league="nba")
    assert result["products"]["home_margin"]["n"] == 3
    assert result["exact_ats_validation"] is False
    assert result["products"]["total"]["intervals"][0]["empirical_coverage"] == 1


def test_scoring_does_not_mutate_raw_forecasts_or_population():
    rows, population, excluded = fixture()
    before = copy.deepcopy((rows, population, excluded))
    analyze(rows, population, excluded, league="nba", bootstrap_count=10)
    assert (rows, population, excluded) == before
