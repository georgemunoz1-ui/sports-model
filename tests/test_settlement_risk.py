import math

import numpy as np
import pytest

from models.common.settlement_risk import decimal_odds, payoff_moments


@pytest.mark.parametrize("bad", [True, np.bool_(True), "0.5", None, float("nan"), float("inf"), -float("inf"), -0.01, 1.01])
def test_probability_validation(bad):
    with pytest.raises(ValueError):
        payoff_moments({"win": bad, "push": 0., "loss": .5}, odds=-110)


@pytest.mark.parametrize("bad", [True, "-110", None, float("nan"), float("inf"), 0, 99, -99])
def test_american_odds_validation(bad):
    with pytest.raises(ValueError):
        payoff_moments({"win": .5, "push": 0., "loss": .5}, odds=bad)


@pytest.mark.parametrize("bad", [True, "1.9", None, float("nan"), float("inf"), 0, 1, -2])
def test_decimal_odds_validation(bad):
    with pytest.raises(ValueError):
        decimal_odds(bad, "decimal")


def test_fixed_probability_sum_validation_without_normalization():
    for p in ({"win": .6, "push": .2, "loss": .3}, {"win": .5, "push": 0., "loss": .499999},
              {"win": .5, "loss": .5}, {"win": .5, "push": 0., "loss": .5, "unknown": 0.}):
        with pytest.raises(ValueError):
            payoff_moments(p, odds=-110)


def test_centered_variance_with_push_matches_hand_calculation():
    result = payoff_moments({"win": .4, "push": .2, "loss": .4}, odds=150)
    assert result["expected_return_per_unit"] == pytest.approx(.2)
    # .4*(1.5-.2)^2 + .2*(0-.2)^2 + .4*(-1-.2)^2
    assert result["return_variance_per_unit"] == pytest.approx(1.26)
    assert result["return_sd_per_unit"] == pytest.approx(math.sqrt(1.26))
    assert not result["action_authority"]


def test_all_push_all_win_and_all_void_have_zero_sd_without_false_standardization():
    for p in ({"win": 0., "push": 1., "loss": 0.}, {"win": 1., "push": 0., "loss": 0.},
              {"win": 0., "push": 0., "loss": 0., "void": 1.}):
        result = payoff_moments(p, odds=150)
        assert result["return_sd_per_unit"] == 0.
        assert result["standardized_expected_return"] is None
        assert result["standardized_return_status"] == "UNDEFINED_ZERO_SD"


def test_quarter_outcomes_use_full_payoff_map():
    result = payoff_moments({"win": .2, "half_win": .3, "push": .1, "half_loss": .15, "loss": .25}, odds=200)
    assert result["expected_return_per_unit"] == pytest.approx(.375)
    returns, masses = [2., 1., 0., -.5, -1.], [.2, .3, .1, .15, .25]
    variance = sum(p * (r - .375)**2 for r, p in zip(returns, masses))
    assert result["return_sd_per_unit"] == pytest.approx(math.sqrt(variance))


def test_negative_ev_is_preserved():
    result = payoff_moments({"win": .7, "push": 0., "loss": .3}, odds=-258)
    assert result["expected_return_per_unit"] < 0
    assert result["price_assessment"] == "NEGATIVE_MODEL_EV"


def test_nonfinite_variance_cannot_become_zero():
    with pytest.raises(ValueError, match="NONFINITE"):
        payoff_moments({"win": .5, "push": 0., "loss": .5}, odds=1e308, odds_format="decimal")


def test_extreme_zero_mass_payoffs_do_not_poison_valid_deterministic_return():
    result = payoff_moments({"win": 0., "push": 0., "loss": 1.}, odds=1e308, odds_format="decimal")
    assert result["expected_return_per_unit"] == -1
    assert result["return_sd_per_unit"] == 0


def test_near_deterministic_variance_is_not_cancelled_to_zero():
    result = payoff_moments({"win": 1 - 1e-15, "push": 0., "loss": 1e-15}, odds=100)
    assert result["return_variance_per_unit"] == pytest.approx(4e-15, rel=1e-12, abs=0)


def test_weighted_centering_preserves_finite_rare_event_variance():
    result = payoff_moments({"win": 1e-320, "push": 0., "loss": 1.}, odds=1e308, odds_format="decimal")
    assert math.isfinite(result["return_variance_per_unit"])
    assert result["return_variance_per_unit"] > 1e295
