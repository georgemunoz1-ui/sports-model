import numpy as np
import pytest

from sportsim.core.ratings import fit_for_sport
from sportsim.core.types import Game, TeamRating
from sportsim.data import generate_season
from sportsim.leagues import LEAGUES, SEASON_LENGTH, get_league, get_playoff_format
from sportsim.season import (
    SeasonSimulator,
    build_schedule,
    compute_standings,
    merge_results,
    series_win_prob,
    standings_table,
)
from sportsim.season.playoffs import SeriesOracle, seed_conference, seed_nhl_bracket


# -- league structures -----------------------------------------------------
@pytest.mark.parametrize("sport", ["nfl", "nba", "nhl", "mlb"])
def test_league_structures_are_complete(sport):
    league = get_league(sport)
    teams = league.teams
    expected = {"nfl": 32, "nba": 30, "nhl": 32, "mlb": 30}[sport]
    assert len(teams) == expected
    assert len(set(teams)) == expected
    for t in teams:
        assert league.conference_of(t)
        assert league.division_of(t)


def test_conferences_are_evenly_sized():
    for league in LEAGUES.values():
        sizes = {conf: len(league.teams_in_conference(conf)) for conf in league.conferences}
        assert len(set(sizes.values())) == 1


# -- standings -------------------------------------------------------------
def test_standings_count_wins_losses_and_differential():
    games = [
        Game("A", "B", 3, 1),
        Game("B", "A", 5, 2),
        Game("A", "C", 4, 4),
    ]
    rec = compute_standings(games)
    assert (rec["A"].wins, rec["A"].losses, rec["A"].ties) == (1, 1, 1)
    assert rec["A"].points_for == 9 and rec["A"].points_against == 10
    assert rec["A"].differential == -1
    assert rec["A"].win_pct == pytest.approx(0.5)


def test_hockey_awards_a_point_for_an_overtime_loss():
    games = [Game("A", "B", 3, 2, went_ot=True)]
    rec = compute_standings(games, ot_points=True)
    assert rec["A"].points(ot_points=True) == 2
    assert rec["B"].points(ot_points=True) == 1
    assert rec["B"].ot_losses == 1


def test_standings_table_renders_every_team():
    season = generate_season("nhl", seed=1)
    text = standings_table(compute_standings(season.games, season.league.teams, True), season.league, True)
    for team in season.league.teams:
        assert team in text


# -- schedules -------------------------------------------------------------
@pytest.mark.parametrize("sport", ["nfl", "nba", "nhl", "mlb"])
def test_schedule_gives_every_team_the_right_number_of_games(sport):
    league = get_league(sport)
    target = SEASON_LENGTH[sport]
    schedule = build_schedule(league, target, sport=sport, rng=0)
    counts = {t: 0 for t in league.teams}
    for g in schedule:
        counts[g.home] += 1
        counts[g.away] += 1
    assert set(counts.values()) == {target}
    assert all(not g.played for g in schedule)


def test_schedule_favours_division_opponents():
    league = get_league("nba")
    schedule = build_schedule(league, 82, sport="nba", rng=1)
    div, other = 0, 0
    for g in schedule:
        if league.division_of(g.home) == league.division_of(g.away):
            div += 1
        else:
            other += 1
    # Four division opponents should account for more games each than the rest.
    assert div / 4 > other / 25


def test_home_and_away_are_roughly_balanced():
    league = get_league("nhl")
    schedule = build_schedule(league, 82, sport="nhl", rng=2)
    home = {t: 0 for t in league.teams}
    for g in schedule:
        home[g.home] += 1
    assert all(30 < h < 52 for h in home.values())


def test_merge_results_does_not_apply_a_result_twice():
    # Overlaying a season onto itself must be a no-op. Without a guard the
    # already-played result would be copied onto the next fixture between the
    # same teams and every completed game would count twice.
    season = generate_season("nhl", seed=3, played_fraction=0.5)
    merged = merge_results(season.games, [g for g in season.games if g.played])
    assert sum(g.played for g in merged) == sum(g.played for g in season.games)


def test_merge_results_fills_in_played_games():
    schedule = [Game("A", "B", date="2025-01-01"), Game("B", "A", date="2025-02-01")]
    merged = merge_results(schedule, [Game("A", "B", 5, 3, date="2025-01-01")])
    assert merged[0].played and merged[0].home_score == 5
    assert not merged[1].played


# -- playoff series maths --------------------------------------------------
def test_a_coin_flip_series_is_a_coin_flip():
    for length in (1, 3, 5, 7):
        assert series_win_prob(0.5, 0.5, length) == pytest.approx(0.5)


def test_longer_series_favour_the_better_team():
    # Best-of-3 is excluded: MLB plays that round entirely at the higher seed's
    # park, so it favours the better team more than a longer split-venue series.
    p = [series_win_prob(0.65, 0.55, n) for n in (1, 5, 7)]
    assert p == sorted(p)
    assert p[0] < p[-1]


def test_the_all_home_wild_card_round_is_worth_more_than_its_length_suggests():
    all_home = series_win_prob(0.65, 0.55, 3)
    split_venue = series_win_prob(0.65, 0.55, 5)
    assert all_home > split_venue


def test_a_certain_winner_wins_the_series():
    assert series_win_prob(1.0, 1.0, 7) == pytest.approx(1.0)
    assert series_win_prob(0.0, 0.0, 7) == pytest.approx(0.0)


def test_home_court_matters():
    with_edge = series_win_prob(0.60, 0.50, 7)
    without = series_win_prob(0.55, 0.55, 7)
    assert with_edge > without


def test_series_oracle_caches_and_resolves():
    calls = []

    def p(home, away):
        calls.append((home, away))
        return 0.6 if home == "A" else 0.4

    oracle = SeriesOracle(p)
    first = oracle.prob("A", "B", 7)
    second = oracle.prob("A", "B", 7)
    assert first == second
    assert len(calls) == 2  # one per direction, then cached
    assert oracle.play("A", "B", 7, 0.0) == "A"
    assert oracle.play("A", "B", 7, 0.999) == "B"


# -- seeding ---------------------------------------------------------------
def test_division_winners_are_seeded_ahead_of_better_wild_cards():
    ranked = ["W", "X", "Y", "Z", "Q"]
    divisions = [["X", "Q"], ["Y", "Z"], ["W"]]
    field = seed_conference(ranked, divisions, n_teams=4, division_winners_seeded=True)
    # X and Y win divisions, so they outrank W's division-mates... W wins its own.
    assert set(field[:3]) == {"W", "X", "Y"}
    assert field[3] == "Z"


def test_seeding_by_record_ignores_divisions():
    ranked = ["W", "X", "Y", "Z"]
    divisions = [["Z"], ["W", "X", "Y"]]
    assert seed_conference(ranked, divisions, 3, division_winners_seeded=False) == ["W", "X", "Y"]


def test_nhl_bracket_pairs_the_top_seed_with_the_weaker_wild_card():
    div_a = ["A1", "A2", "A3", "A4"]
    div_b = ["B1", "B2", "B3", "B4"]
    ranked = ["A1", "B1", "A2", "B2", "A3", "B3", "A4", "B4"]
    pairs = seed_nhl_bracket([div_a, div_b], ranked)
    assert pairs[0] == ("A1", "B4")  # best division winner draws the last wild card
    assert pairs[1] == ("A2", "A3")
    assert pairs[2] == ("B1", "A4")
    assert pairs[3] == ("B2", "B3")


# -- full season Monte Carlo ----------------------------------------------
@pytest.fixture(scope="module")
def nhl_result():
    season = generate_season("nhl", seed=21)
    fit = fit_for_sport(season.games, "nhl")
    sim = SeasonSimulator("nhl", fit.ratings(), league=season.league)
    return sim.run(season.schedule, n_sims=200, n_scenarios=4, samples_per_matchup=300, playoff_samples=600, rng=5)


def test_every_season_produces_exactly_one_champion(nhl_result):
    assert np.all(nhl_result.championships.sum(axis=1) == 1)
    assert np.all(nhl_result.conference_titles.sum(axis=1) == 2)


def test_the_playoff_field_is_the_right_size(nhl_result):
    fmt = get_playoff_format("nhl")
    assert np.all(nhl_result.made_playoffs.sum(axis=1) == fmt.teams_per_conference * 2)


def test_division_titles_go_to_one_team_per_division(nhl_result):
    assert np.all(nhl_result.division_titles.sum(axis=1) == 4)


def test_games_played_matches_the_schedule(nhl_result):
    played = nhl_result.wins + nhl_result.losses + nhl_result.ties
    assert np.all(played == SEASON_LENGTH["nhl"])


def test_the_champion_always_made_the_playoffs(nhl_result):
    assert np.all(~nhl_result.championships | nhl_result.made_playoffs)


def test_probabilities_are_consistent_across_rounds(nhl_result):
    title = nhl_result.championships.mean(axis=0)
    conf = nhl_result.conference_titles.mean(axis=0)
    playoffs = nhl_result.made_playoffs.mean(axis=0)
    assert np.all(title <= conf + 1e-9)
    assert np.all(conf <= playoffs + 1e-9)


def test_better_teams_get_better_odds(nhl_result):
    rows = nhl_result.summary()
    assert rows[0]["mean_wins"] > rows[-1]["mean_wins"]
    assert rows[0]["playoffs"] > rows[-1]["playoffs"]


def test_completed_games_are_treated_as_facts():
    season = generate_season("nba", seed=22)
    ratings = {t: TeamRating(t) for t in season.league.teams}
    sim = SeasonSimulator("nba", ratings, league=season.league)
    # A schedule that is already fully played must reproduce itself exactly.
    result = sim.run(season.games, n_sims=20, n_scenarios=1, samples_per_matchup=50, playoff_samples=200, rng=1)
    actual = compute_standings(season.games, season.league.teams)
    for i, team in enumerate(result.teams):
        assert np.all(result.wins[:, i] == actual[team].wins)


def test_rating_noise_widens_the_win_distribution():
    season = generate_season("nhl", seed=23)
    ratings = {t: TeamRating(t) for t in season.league.teams}
    sim = SeasonSimulator("nhl", ratings, league=season.league)
    kw = dict(n_sims=150, samples_per_matchup=250, playoff_samples=400, include_playoffs=False, rng=2)
    certain = sim.run(season.schedule, rating_noise=0.0, **kw)
    uncertain = sim.run(season.schedule, rating_noise=0.06, n_scenarios=10, **kw)
    assert uncertain.wins.std(axis=0).mean() > certain.wins.std(axis=0).mean()


def test_an_empty_schedule_is_rejected():
    sim = SeasonSimulator("nba", {t: TeamRating(t) for t in get_league("nba").teams})
    with pytest.raises(ValueError):
        sim.run([])
