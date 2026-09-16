import numpy as np
import pytest

from sportsim.core.market import (
    american_to_decimal,
    american_to_prob,
    closing_line_value,
    decimal_to_american,
    expected_value,
    find_edge,
    kelly_fraction,
    no_vig_probs,
    overround,
    prob_to_american,
    remove_vig,
)


def test_american_probability_round_trip():
    for odds in (-350, -140, -110, 100, 145, 900):
        assert prob_to_american(american_to_prob(odds)) == pytest.approx(odds, abs=1)


def test_even_money_is_plus_100():
    assert prob_to_american(0.5) == 100
    assert american_to_prob(100) == pytest.approx(0.5)
    assert american_to_decimal(100) == pytest.approx(2.0)
    assert decimal_to_american(2.0) == 100


def test_favourite_and_underdog_directions():
    assert american_to_prob(-200) > 0.5 > american_to_prob(200)
    assert prob_to_american(0.75) < 0
    assert prob_to_american(0.25) > 0


def test_standard_juice_has_positive_hold():
    implied = [american_to_prob(-110), american_to_prob(-110)]
    assert overround(implied) == pytest.approx(1.0476, abs=1e-3)


@pytest.mark.parametrize("method", ["multiplicative", "power", "shin"])
def test_devig_methods_produce_a_distribution(method):
    fair = remove_vig([american_to_prob(-250), american_to_prob(200)], method=method)
    assert fair.sum() == pytest.approx(1.0)
    assert np.all(fair > 0)
    # The favourite stays the favourite whichever method is used.
    assert fair[0] > fair[1]


def test_power_devig_shades_the_longshot_lower_than_multiplicative():
    odds = [american_to_prob(-600), american_to_prob(450)]
    mult = remove_vig(odds, "multiplicative")
    power = remove_vig(odds, "power")
    assert power[1] < mult[1]


def test_symmetric_market_devigs_to_a_coin_flip():
    fair = no_vig_probs([-110, -110])
    assert fair[0] == pytest.approx(0.5)


def test_kelly_scales_with_edge_and_respects_the_cap():
    none = kelly_fraction(0.5, -110)
    small = kelly_fraction(0.55, -110, fraction=1.0, cap=1.0)
    large = kelly_fraction(0.70, -110, fraction=1.0, cap=1.0)
    assert none == 0.0
    assert 0 < small < large
    assert kelly_fraction(0.99, 100, fraction=1.0, cap=0.05) == 0.05


def test_quarter_kelly_is_a_quarter_of_full_kelly():
    full = kelly_fraction(0.60, -110, fraction=1.0, cap=1.0)
    quarter = kelly_fraction(0.60, -110, fraction=0.25, cap=1.0)
    assert quarter == pytest.approx(full * 0.25)


def test_expected_value_is_zero_at_the_fair_price():
    assert expected_value(0.5, 100) == pytest.approx(0.0)
    assert expected_value(0.6, 100) == pytest.approx(0.2)


def test_edge_is_measured_against_the_devigged_price():
    with_vig = find_edge("test", 0.55, -110)
    devigged = find_edge("test", 0.55, -110, opposing_odds=-110)
    assert devigged.market_prob == pytest.approx(0.5)
    assert devigged.edge > with_vig.edge
    assert devigged.kelly > 0


def test_closing_line_value_signs():
    # Betting +120 on something that closes -110 is positive CLV.
    assert closing_line_value(120, -110) > 0
    assert closing_line_value(-130, -110) < 0


def test_devig_rejects_bad_input():
    with pytest.raises(ValueError):
        remove_vig([0.5])
    with pytest.raises(ValueError):
        remove_vig([0.5, 0.5], method="nonsense")
    with pytest.raises(ValueError):
        prob_to_american(0.0)
