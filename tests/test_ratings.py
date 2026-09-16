import numpy as np
import pytest

from sportsim.core.ratings import (
    ELO_PRESETS,
    EloConfig,
    EloModel,
    blend_ratings,
    elo_to_win_prob,
    fit_for_sport,
    fit_poisson_strength,
    fit_ridge_margin,
)
from sportsim.core.types import Game
from sportsim.data import generate_season


def game(home, away, hs, as_, **kw):
    return Game(home=home, away=away, home_score=hs, away_score=as_, **kw)


# -- Elo -------------------------------------------------------------------
def test_equal_teams_on_a_neutral_field_are_a_coin_flip():
    m = EloModel(EloConfig(k=20, home_advantage=60))
    assert m.win_prob("A", "B", neutral=True) == pytest.approx(0.5)
    assert m.win_prob("A", "B") > 0.5


def test_elo_is_zero_sum_and_moves_toward_the_winner():
    m = EloModel(EloConfig(k=20, home_advantage=0, mov_factor=False))
    m.update(game("A", "B", 30, 10))
    assert m.get("A") > 1500 > m.get("B")
    assert m.get("A") + m.get("B") == pytest.approx(3000)


def test_a_bigger_win_moves_the_rating_further():
    close = EloModel(EloConfig(k=20, home_advantage=0, mov_factor=True))
    blowout = EloModel(EloConfig(k=20, home_advantage=0, mov_factor=True))
    close.update(game("A", "B", 21, 20))
    blowout.update(game("A", "B", 49, 0))
    assert blowout.get("A") > close.get("A")


def test_upsets_move_ratings_more_than_expected_results():
    strong_wins = EloModel(EloConfig(k=20, home_advantage=0, mov_factor=False), {"A": 1800, "B": 1400})
    upset = EloModel(EloConfig(k=20, home_advantage=0, mov_factor=False), {"A": 1800, "B": 1400})
    strong_wins.update(game("A", "B", 30, 10))
    upset.update(game("B", "A", 30, 10))
    assert abs(upset.get("B") - 1400) > abs(strong_wins.get("A") - 1800)


def test_regression_pulls_ratings_back_toward_the_mean():
    m = EloModel(EloConfig(season_regression=0.5), {"A": 1700, "B": 1300})
    m.regress_to_mean()
    assert m.get("A") == pytest.approx(1600)
    assert m.get("B") == pytest.approx(1400)


def test_elo_ranks_a_dominant_team_first():
    games = [game("A", "B", 30, 10), game("A", "C", 28, 14), game("B", "C", 20, 17)] * 6
    m = EloModel("nfl").fit(games)
    assert m.table()[0][0] == "A"


def test_elo_win_prob_curve():
    assert elo_to_win_prob(0) == pytest.approx(0.5)
    assert elo_to_win_prob(400) == pytest.approx(10 / 11)
    assert elo_to_win_prob(-400) == pytest.approx(1 / 11)


def test_every_sport_has_an_elo_preset():
    for sport in ("nfl", "nba", "nhl", "mlb"):
        assert ELO_PRESETS[sport].k > 0
    # Short seasons need to move faster than long ones.
    assert ELO_PRESETS["nfl"].k > ELO_PRESETS["mlb"].k


def test_elo_refuses_unplayed_games():
    with pytest.raises(ValueError):
        EloModel("nba").update(Game(home="A", away="B"))


# -- strength fitting ------------------------------------------------------
def test_strength_fit_recovers_the_true_ratings():
    season = generate_season("nba", seed=11)
    fit = fit_poisson_strength(season.games, shrinkage=0.2)
    teams = sorted(season.true_ratings)
    true_net = np.array([season.true_ratings[t].attack / season.true_ratings[t].defense for t in teams])
    est_net = np.array([fit.attack[t] / fit.defense[t] for t in teams])
    assert np.corrcoef(true_net, est_net)[0, 1] > 0.85


def test_strength_ratings_are_centred_on_one():
    season = generate_season("nhl", seed=2)
    fit = fit_poisson_strength(season.games)
    assert np.mean(list(fit.attack.values())) == pytest.approx(1.0, abs=0.02)
    assert np.mean(list(fit.defense.values())) == pytest.approx(1.0, abs=0.02)


def test_home_factor_is_detected():
    season = generate_season("mlb", seed=4)
    fit = fit_poisson_strength(season.games)
    assert 1.0 < fit.home_factor < 1.15


def test_shrinkage_flattens_the_ratings():
    season = generate_season("nfl", seed=5)
    loose = fit_poisson_strength(season.games, shrinkage=0.05)
    tight = fit_poisson_strength(season.games, shrinkage=2.0)
    assert np.std(list(tight.attack.values())) < np.std(list(loose.attack.values()))


def test_expected_score_favours_the_better_team():
    games = [game("A", "B", 6, 1), game("B", "A", 1, 5), game("A", "C", 7, 2), game("C", "B", 3, 3)] * 5
    fit = fit_poisson_strength(games)
    h, a = fit.expected_score("A", "B")
    assert h > a


def test_decay_weights_recent_form_more():
    early = [game("A", "B", 1, 5)] * 20
    late = [game("A", "B", 5, 1)] * 20
    fit = fit_poisson_strength(early + late, decay_half_life=5)
    assert fit.attack["A"] > fit.attack["B"]


def test_fit_for_sport_uses_league_defaults():
    season = generate_season("nfl", seed=6)
    assert fit_for_sport(season.games, "nfl").n_games == len(season.games)


def test_fitting_requires_results():
    with pytest.raises(ValueError):
        fit_poisson_strength([Game(home="A", away="B")])


# -- ridge margin model ----------------------------------------------------
def test_ridge_ratings_recover_the_ordering_and_home_field():
    season = generate_season("nba", seed=8)
    fit = fit_ridge_margin(season.games)
    teams = sorted(season.true_ratings)
    true_net = np.array([season.true_ratings[t].attack / season.true_ratings[t].defense for t in teams])
    est = np.array([fit.ratings[t] for t in teams])
    assert np.corrcoef(true_net, est)[0, 1] > 0.85
    assert 1.0 < fit.home_advantage < 4.5
    assert sum(fit.ratings.values()) == pytest.approx(0.0, abs=1e-6)


def test_ridge_win_prob_tracks_the_predicted_margin():
    season = generate_season("nfl", seed=9)
    fit = fit_ridge_margin(season.games)
    best = max(fit.ratings, key=fit.ratings.get)
    worst = min(fit.ratings, key=fit.ratings.get)
    assert fit.predicted_margin(best, worst) > 0
    assert fit.win_prob(best, worst) > 0.5
    assert fit.win_prob(worst, best) < 0.5


def test_capping_margins_limits_the_effect_of_blowouts():
    # Alternate hosts so a team's rating is not collinear with home field.
    base = [game("A", "B", 21, 20), game("B", "A", 20, 21), game("A", "C", 24, 21), game("C", "A", 21, 24)] * 3
    uncapped = fit_ridge_margin(base + [game("A", "B", 66, 0)])
    capped = fit_ridge_margin(base + [game("A", "B", 66, 0)], cap_margin=21)
    assert capped.ratings["A"] < uncapped.ratings["A"]


# -- blending --------------------------------------------------------------
def test_blend_attaches_elo_and_can_nudge_strength():
    season = generate_season("nhl", seed=12)
    fit = fit_poisson_strength(season.games)
    elo = EloModel("nhl").fit(season.games)
    plain = blend_ratings(fit, elo, elo_weight=0.0)
    nudged = blend_ratings(fit, elo, elo_weight=1.0)
    top = elo.table()[0][0]
    assert plain[top].elo == elo.get(top)
    assert nudged[top].attack > plain[top].attack
    assert nudged[top].defense < plain[top].defense
