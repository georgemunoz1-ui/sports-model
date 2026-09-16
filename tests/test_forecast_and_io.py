import json

import numpy as np
import pytest

from sportsim.cli import main
from sportsim.core.market import scan_edges
from sportsim.core.types import Game, LeagueStructure, ScoreSamples, TeamRating
from sportsim.data import generate_season, read_games_csv, read_ratings_csv, write_games_csv, write_ratings_csv
from sportsim.sports import get_simulator


# -- forecast maths --------------------------------------------------------
@pytest.fixture
def forecast():
    return get_simulator("nba").forecast(TeamRating("BOS", attack=1.04), TeamRating("LAL"), n=20_000, rng=3)


def test_win_probabilities_sum_to_one(forecast):
    assert forecast.home_win_prob + forecast.away_win_prob == pytest.approx(1.0)


def test_cover_probability_moves_with_the_line(forecast):
    generous = forecast.cover_prob(+7)
    fair = forecast.cover_prob(0)
    harsh = forecast.cover_prob(-7)
    assert generous > fair > harsh


def test_the_fair_spread_is_a_coin_flip(forecast):
    assert forecast.cover_prob(forecast.fair_spread()) == pytest.approx(0.5, abs=0.03)


def test_over_probability_falls_as_the_total_rises(forecast):
    assert forecast.over_prob(200) > forecast.over_prob(forecast.mean_total) > forecast.over_prob(260)


def test_moneyline_at_the_fair_spread_is_even(forecast):
    assert forecast.cover_prob(0) == pytest.approx(forecast.home_win_prob, abs=1e-9)


def test_score_intervals_bracket_the_mean(forecast):
    (hlo, hhi), _ = forecast.score_interval(0.9)
    assert hlo < forecast.mean_home_score < hhi


def test_team_totals_reference_the_right_team(forecast):
    assert forecast.team_total_over_prob("BOS", 0) == 1.0
    assert forecast.team_total_over_prob("BOS", 500) == 0.0


def test_margin_distribution_is_a_probability_distribution(forecast):
    dist = forecast.margin_distribution()
    assert sum(dist.values()) == pytest.approx(1.0)
    assert 0 not in dist  # basketball has no ties


def test_forecast_dict_and_report(forecast):
    d = forecast.to_dict()
    assert d["home"] == "BOS" and d["away"] == "LAL"
    assert 0 < d["home_win_prob"] < 1
    assert "BOS" in forecast.report()


def test_scan_edges_finds_a_mispriced_side(forecast):
    lines = {
        "moneyline": {"home": 200, "away": -240},  # market has BOS as a big dog
        "spread": {"line": -3.5, "home": -110, "away": -110},
        "total": {"line": 220.5, "over": -110, "under": -110},
    }
    edges = scan_edges(forecast, lines, min_edge=0.0)
    assert edges[0].edge > 0
    assert edges[0].kelly > 0
    assert "BOS" in edges[0].label or "Over" in edges[0].label


def test_score_samples_reject_mismatched_shapes():
    with pytest.raises(ValueError):
        ScoreSamples(home=np.zeros(3), away=np.zeros(4))


# -- league structure helpers ---------------------------------------------
def test_flat_league_splits_teams_evenly():
    league = LeagueStructure.flat("test", [f"T{i}" for i in range(8)], n_conferences=2, n_divisions=2)
    assert len(league.teams) == 8
    assert len(league.conferences) == 2
    assert league.conference_of("T0") != league.conference_of("T7")


def test_unknown_team_lookup_raises():
    league = LeagueStructure.flat("test", ["A", "B"], 1, 1)
    with pytest.raises(KeyError):
        league.conference_of("Z")


# -- CSV round trips -------------------------------------------------------
def test_games_csv_round_trip(tmp_path):
    games = [
        Game("KC", "BAL", 27, 20, date="2025-09-05", season=2025, went_ot=True),
        Game("SF", "NYJ", date="2025-09-12", neutral=True),
    ]
    path = tmp_path / "games.csv"
    write_games_csv(path, games)
    loaded = read_games_csv(path)
    assert len(loaded) == 2
    assert loaded[0].home_score == 27 and loaded[0].went_ot and loaded[0].season == 2025
    assert not loaded[1].played and loaded[1].neutral


def test_games_csv_accepts_alternative_column_names(tmp_path):
    path = tmp_path / "alt.csv"
    path.write_text("date,home_team,away_team,home_points,away_points\n2025-01-01,BOS,LAL,110,104\n")
    loaded = read_games_csv(path)
    assert loaded[0].home == "BOS" and loaded[0].home_score == 110


def test_blank_scores_become_fixtures(tmp_path):
    path = tmp_path / "part.csv"
    path.write_text("date,home,away,home_score,away_score\n2025-01-01,A,B,3,1\n2025-01-02,B,A,,\n")
    loaded = read_games_csv(path)
    assert loaded[0].played and not loaded[1].played


def test_ratings_csv_round_trip(tmp_path):
    ratings = {"BOS": TeamRating("BOS", attack=1.07, defense=0.94, elo=1620.0)}
    path = tmp_path / "r.csv"
    write_ratings_csv(path, ratings)
    loaded = read_ratings_csv(path)
    assert loaded["BOS"].attack == pytest.approx(1.07)
    assert loaded["BOS"].elo == pytest.approx(1620.0)


def test_partial_ratings_csv_defaults_to_average(tmp_path):
    path = tmp_path / "r.csv"
    path.write_text("team\nBOS\n")
    assert read_ratings_csv(path)["BOS"].attack == 1.0


# -- synthetic data --------------------------------------------------------
def test_synthetic_season_is_complete():
    season = generate_season("nfl", seed=1)
    assert all(g.played for g in season.games)
    assert len(season.true_ratings) == 32
    assert all(not g.played for g in season.schedule)


def test_partial_season_leaves_fixtures():
    season = generate_season("nba", seed=1, played_fraction=0.5)
    played = [g for g in season.games if g.played]
    assert 0.45 < len(played) / len(season.games) < 0.55


# -- CLI smoke tests -------------------------------------------------------
def test_cli_game_json(capsys, tmp_path):
    assert main(["game", "--sport", "nhl", "--home", "BOS", "--away", "MTL", "--sims", "2000", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["home"] == "BOS"
    assert 0 < payload["home_win_prob"] < 1


def test_cli_game_with_market_lines(capsys):
    code = main(
        [
            "game", "--sport", "nfl", "--home", "KC", "--away", "LV", "--sims", "3000",
            "--spread", "-6.5", "--total", "44.5",
            "--odds", '{"moneyline": {"home": -260, "away": 220}}',
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "P(KC -6.5)" in out and "model vs market" in out


def test_cli_rate_and_season(capsys, tmp_path):
    season = generate_season("nhl", seed=2)
    games_path = tmp_path / "games.csv"
    ratings_path = tmp_path / "ratings.csv"
    write_games_csv(games_path, season.games)

    assert main(["rate", "--sport", "nhl", "--games", str(games_path), "--out", str(ratings_path)]) == 0
    assert "attack" in capsys.readouterr().out
    assert read_ratings_csv(ratings_path)

    code = main(["season", "--sport", "nhl", "--ratings", str(ratings_path), "--sims", "60", "--top", "5"])
    assert code == 0
    assert "season projection" in capsys.readouterr().out


def test_cli_rejects_missing_games(capsys):
    assert main(["rate", "--sport", "nba"]) == 2
