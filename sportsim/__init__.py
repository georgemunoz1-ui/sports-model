"""sportsim -- Monte Carlo simulation and prediction for NFL, NBA, MLB and NHL.

Typical use::

    from sportsim import fit_poisson_strength, get_simulator, read_games_csv

    games = read_games_csv("nba_2025.csv")
    fit = fit_poisson_strength(games, decay_half_life=250)
    sim = get_simulator("nba")

    print(sim.forecast(fit.rating("BOS"), fit.rating("LAL"), n=20_000).report())

Only numpy is required.
"""

from __future__ import annotations

from .backtest import BacktestResult, backtest_elo, backtest_simulator, walk_forward
from .core import (
    EloConfig,
    EloModel,
    Game,
    GameForecast,
    LeagueStructure,
    ScoreSamples,
    StrengthFit,
    TeamRating,
    ats_record,
    blend_ratings,
    calibration_report,
    evaluate,
    find_edge,
    fit_poisson_strength,
    fit_ridge_margin,
    kelly_fraction,
    prob_to_american,
    scan_edges,
)
from .data import generate_season, read_games_csv, read_ratings_csv, write_games_csv, write_ratings_csv
from .leagues import LEAGUES, get_league, get_playoff_format
from .season import SeasonResult, SeasonSimulator, build_schedule, compute_standings, standings_table
from .sports import get_simulator

__version__ = "0.1.0"

__all__ = [
    "BacktestResult",
    "EloConfig",
    "EloModel",
    "Game",
    "GameForecast",
    "LEAGUES",
    "LeagueStructure",
    "ScoreSamples",
    "SeasonResult",
    "SeasonSimulator",
    "StrengthFit",
    "TeamRating",
    "ats_record",
    "backtest_elo",
    "backtest_simulator",
    "blend_ratings",
    "build_schedule",
    "calibration_report",
    "compute_standings",
    "evaluate",
    "find_edge",
    "fit_poisson_strength",
    "fit_ridge_margin",
    "generate_season",
    "get_league",
    "get_playoff_format",
    "get_simulator",
    "kelly_fraction",
    "prob_to_american",
    "read_games_csv",
    "read_ratings_csv",
    "scan_edges",
    "standings_table",
    "walk_forward",
    "write_games_csv",
    "write_ratings_csv",
]
