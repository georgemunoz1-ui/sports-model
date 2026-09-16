import math

import numpy as np
import pytest

from sportsim.backtest import backtest_elo, compare_models, walk_forward
from sportsim.core.metrics import (
    accuracy,
    ats_record,
    brier_score,
    calibration,
    calibration_report,
    evaluate,
    expected_calibration_error,
    log_loss,
    margin_errors,
    skill_score,
)
from sportsim.data import generate_season


# -- scoring rules ---------------------------------------------------------
def test_perfect_forecasts_score_zero():
    probs, outcomes = [1.0, 0.0, 1.0], [1, 0, 1]
    assert brier_score(probs, outcomes) == 0.0
    assert log_loss(probs, outcomes) < 1e-10
    assert accuracy(probs, outcomes) == 1.0


def test_coin_flips_score_the_known_constants():
    probs, outcomes = [0.5] * 4, [1, 0, 1, 0]
    assert brier_score(probs, outcomes) == pytest.approx(0.25)
    assert log_loss(probs, outcomes) == pytest.approx(math.log(2))


def test_confident_and_wrong_is_punished_hardest():
    assert log_loss([0.99], [0]) > log_loss([0.6], [0]) > log_loss([0.4], [0])


def test_log_loss_is_finite_even_at_the_extremes():
    assert np.isfinite(log_loss([1.0], [0]))


def test_skill_score_is_zero_for_the_base_rate():
    outcomes = [1, 1, 1, 0]
    assert skill_score([0.75] * 4, outcomes) == pytest.approx(0.0)
    assert skill_score([1.0, 1.0, 1.0, 0.0], outcomes) == pytest.approx(1.0)


def test_margin_errors_report_bias():
    m = margin_errors([3, 3, 3], [1, 1, 1])
    assert m["mae"] == pytest.approx(2.0)
    assert m["rmse"] == pytest.approx(2.0)
    assert m["bias"] == pytest.approx(2.0)
    assert m["n"] == 3


# -- calibration -----------------------------------------------------------
def test_a_calibrated_model_has_near_zero_error():
    rng = np.random.default_rng(0)
    probs = rng.uniform(0.05, 0.95, 20_000)
    outcomes = (rng.random(20_000) < probs).astype(int)
    assert expected_calibration_error(probs, outcomes) < 0.02


def test_an_overconfident_model_is_flagged():
    rng = np.random.default_rng(1)
    truth = rng.uniform(0.3, 0.7, 20_000)
    outcomes = (rng.random(20_000) < truth).astype(int)
    overconfident = np.clip((truth - 0.5) * 3 + 0.5, 0.01, 0.99)
    assert expected_calibration_error(overconfident, outcomes) > 0.05


def test_calibration_bins_cover_every_prediction():
    probs = [0.05, 0.15, 0.95, 0.5]
    bins = calibration(probs, [0, 0, 1, 1], n_bins=10)
    assert sum(b.n for b in bins) == 4
    assert "ECE" in calibration_report(probs, [0, 0, 1, 1])


def test_evaluate_returns_the_headline_bundle():
    out = evaluate([0.6, 0.4], [1, 0])
    assert set(out) == {"n", "log_loss", "brier", "accuracy", "skill_score", "ece"}


# -- ATS -------------------------------------------------------------------
def test_ats_record_counts_wins_losses_and_pushes():
    # Model likes the home side by a lot; home wins by 10 against a -3 line.
    out = ats_record(predicted_margins=[10], actual_margins=[10], market_spreads=[-3])
    assert out["wins"] == 1 and out["losses"] == 0

    # Model likes the road side; home still covers.
    out = ats_record([-10], [10], [-3])
    assert out["losses"] == 1

    # Exact push.
    out = ats_record([10], [3], [-3])
    assert out["pushes"] == 1 and out["bets"] == 1


def test_ats_threshold_skips_small_disagreements():
    out = ats_record([1.0], [10], [-0.5], threshold=3.0)
    assert out["bets"] == 0


def test_break_even_is_just_above_52_percent():
    out = ats_record([1] * 100, [1] * 100, [0] * 100)
    # 100 wins at -110 pays 90.9 units of profit.
    assert out["units_at_-110"] == pytest.approx(90.909, abs=0.01)


# -- backtesting -----------------------------------------------------------
@pytest.fixture(scope="module")
def nba_games():
    return generate_season("nba", seed=31).games


def test_elo_backtest_beats_a_coin_flip(nba_games):
    result = backtest_elo(nba_games, "nba")
    m = result.metrics()
    assert m["n"] == len(nba_games)
    assert m["log_loss"] < math.log(2)
    assert m["accuracy"] > 0.55


def test_walk_forward_predicts_only_games_it_has_not_seen(nba_games):
    result = walk_forward(nba_games, "nba", method="ridge", min_games=300, refit_every=100)
    assert len(result.probs) == len(nba_games) - 300
    assert result.games[0] is nba_games[300]


def test_simulator_backtest_is_calibrated_and_skilful(nba_games):
    result = walk_forward(nba_games, "nba", min_games=300, refit_every=150, sims=2_000)
    m = result.metrics()
    assert m["log_loss"] < 0.68
    assert m["skill_score"] > 0.02
    assert m["ece"] < 0.08
    # The margin model should be unbiased and land within a sensible error.
    assert abs(m["margin_bias"]) < 2.0
    assert m["margin_mae"] < 14.0


def test_backtest_report_renders(nba_games):
    text = walk_forward(nba_games, "nba", method="ridge", min_games=400).report()
    assert "log loss" in text and "ECE" in text


def test_compare_models_scores_all_three_on_the_same_games(nba_games):
    table = compare_models(nba_games, "nba", min_games=600, refit_every=200, sims=1_000)
    assert "Elo" in table and "ridge" in table and "simulator" in table
    # Column layout: "<label> <sport>  n  log_loss  brier  acc  skill".
    counts = [line.split()[-5] for line in table.splitlines()[2:]]
    assert len(set(counts)) == 1


def test_backtest_needs_enough_history(nba_games):
    with pytest.raises(ValueError):
        walk_forward(nba_games[:10], "nba", min_games=150)
