"""Every sport simulator has to satisfy the same structural contract, plus a
handful of rules specific to its own sport."""

import numpy as np
import pytest

from sportsim.core.types import TeamRating
from sportsim.sports import SIMULATORS, get_simulator

SPORTS = sorted(SIMULATORS)

# Real league averages the simulators are calibrated against: total points/goals
# /runs per game, and the home team's share of wins in an even matchup.
LEAGUE_TOTALS = {"nfl": (45.5, 3.0), "nba": (227.0, 6.0), "nhl": (6.1, 0.35), "mlb": (8.8, 0.5)}


@pytest.fixture(params=SPORTS)
def sport(request):
    return request.param


def test_scores_are_non_negative_integers(sport):
    s = get_simulator(sport).simulate(TeamRating("H"), TeamRating("A"), n=2_000, rng=1)
    for arr in (s.home, s.away):
        assert np.issubdtype(np.asarray(arr).dtype, np.integer)
        assert np.all(np.asarray(arr) >= 0)


def test_same_seed_reproduces_the_same_games(sport):
    a = get_simulator(sport).simulate(TeamRating("H"), TeamRating("A"), n=500, rng=7)
    b = get_simulator(sport).simulate(TeamRating("H"), TeamRating("A"), n=500, rng=7)
    assert np.array_equal(a.home, b.home)
    assert np.array_equal(a.away, b.away)


def test_different_seeds_produce_different_games(sport):
    a = get_simulator(sport).simulate(TeamRating("H"), TeamRating("A"), n=500, rng=1)
    b = get_simulator(sport).simulate(TeamRating("H"), TeamRating("A"), n=500, rng=2)
    assert not np.array_equal(a.home, b.home)


def test_home_advantage_shows_up(sport):
    sim = get_simulator(sport)
    home_wp = sim.forecast(TeamRating("H"), TeamRating("A"), n=40_000, rng=3).home_win_prob
    neutral_wp = sim.forecast(TeamRating("H"), TeamRating("A"), n=40_000, rng=3, neutral=True).home_win_prob
    assert home_wp > neutral_wp
    assert 0.50 < home_wp < 0.60
    assert neutral_wp == pytest.approx(0.5, abs=0.02)


def test_league_average_totals_are_calibrated(sport):
    expected, tol = LEAGUE_TOTALS[sport]
    f = get_simulator(sport).forecast(TeamRating("H"), TeamRating("A"), n=40_000, rng=11)
    assert f.mean_total == pytest.approx(expected, abs=tol)


def test_the_better_team_wins_more_often(sport):
    sim = get_simulator(sport)
    strong = TeamRating("STR", attack=1.05, defense=0.96)
    weak = TeamRating("WEK", attack=0.96, defense=1.05)
    # Strong team on the road still has to be favoured.
    assert sim.forecast(weak, strong, n=30_000, rng=5).away_win_prob > 0.5
    assert sim.forecast(strong, weak, n=30_000, rng=5).home_win_prob > 0.6


def test_ratings_may_be_arrays_so_each_draw_uses_its_own_teams(sport):
    n = 4_000
    attack = np.concatenate([np.full(n // 2, 1.12), np.full(n // 2, 0.88)])
    home = TeamRating("H", attack=attack, defense=np.ones(n))
    s = get_simulator(sport).simulate(home, TeamRating("A"), n=n, rng=9)
    assert s.home[: n // 2].mean() > s.home[n // 2 :].mean()


@pytest.mark.parametrize("attack", [0.85, 1.15, 1.30])
def test_scoring_is_linear_in_the_attack_rating(sport, attack):
    """The rating fitters produce multipliers meaning "scores X% more".

    Every simulator has to honour those units, or ratings fit in one place mean
    something different when they reach the other. The NFL and MLB engines are
    the ones at risk: both apply team quality through an intermediate quantity
    (drive outcomes, on-base rate) whose relationship to points is non-linear,
    so their exponents are tuned to undo exactly that.
    """
    sim = get_simulator(sport)
    base = sim.forecast(TeamRating("H"), TeamRating("A"), n=60_000, rng=0, neutral=True).mean_home_score
    scaled = sim.forecast(
        TeamRating("H", attack=attack), TeamRating("A"), n=60_000, rng=1, neutral=True
    ).mean_home_score
    assert scaled / (base * attack) == pytest.approx(1.0, abs=0.03)


def test_playoff_mode_never_leaves_a_tie(sport):
    s = get_simulator(sport, playoff=True).simulate(TeamRating("H"), TeamRating("A"), n=20_000, rng=4)
    assert not np.any(s.home == s.away)


def test_regular_season_ties_only_happen_in_the_nfl(sport):
    s = get_simulator(sport).simulate(TeamRating("H"), TeamRating("A"), n=20_000, rng=6)
    ties = int(np.sum(s.home == s.away))
    if sport == "nfl":
        assert 0 < ties / len(s) < 0.02
    else:
        assert ties == 0


# -- sport-specific behaviour ---------------------------------------------
def test_nfl_scores_cluster_on_football_numbers():
    f = get_simulator("nfl").forecast(TeamRating("H"), TeamRating("A"), n=80_000, rng=2)
    dist = f.margin_distribution()
    # Key numbers: 3 and 7 must be more common than their neighbours.
    assert dist.get(3, 0) > dist.get(2, 0)
    assert dist.get(7, 0) > dist.get(8, 0)
    # Scoring 1 point is impossible.
    assert not np.any(f.samples.home == 1)


def test_nhl_overtime_rate_matches_the_real_league():
    f = get_simulator("nhl").forecast(TeamRating("H"), TeamRating("A"), n=60_000, rng=8)
    assert 0.18 < f.ot_prob < 0.27
    # Every overtime game is decided by exactly one goal.
    ot = np.asarray(f.samples.ot)
    assert np.all(np.abs(f.samples.margin[ot]) == 1)


def test_nba_scores_are_positively_correlated_through_pace():
    s = get_simulator("nba").simulate(TeamRating("H"), TeamRating("A"), n=40_000, rng=12)
    corr = np.corrcoef(s.home, s.away)[0, 1]
    assert 0.2 < corr < 0.6


def test_mlb_home_team_bats_less_but_scores_more():
    s = get_simulator("mlb").simulate(TeamRating("H"), TeamRating("A"), n=40_000, rng=13)
    assert s.home.mean() > s.away.mean()
    # A home win in the ninth is a walk-off, so home wins skew to small margins.
    home_wins = s.margin[s.margin > 0]
    away_wins = -s.margin[s.margin < 0]
    assert home_wins.mean() < away_wins.mean()


def test_mlb_run_distribution_is_right_skewed():
    s = get_simulator("mlb").simulate(TeamRating("H"), TeamRating("A"), n=40_000, rng=14)
    runs = np.asarray(s.away, dtype=float)
    assert np.median(runs) < runs.mean()
    assert runs.max() > 12


def test_unknown_sport_is_rejected():
    with pytest.raises(KeyError):
        get_simulator("cricket")
