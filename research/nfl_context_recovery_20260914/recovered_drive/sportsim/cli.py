"""Command line interface.

    python -m sportsim demo    --sport nhl
    python -m sportsim game    --sport nba --home BOS --away LAL --ratings r.csv
    python -m sportsim rate    --sport nfl --games games.csv --out ratings.csv
    python -m sportsim season  --sport mlb --games games.csv --sims 5000
    python -m sportsim backtest --sport nba --games games.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from .backtest import compare_models, walk_forward
from .core.market import scan_edges
from .core.ratings import EloModel, fit_for_sport, fit_ridge_margin
from .core.types import Game, TeamRating
from .data import generate_season, read_games_csv, read_ratings_csv, write_ratings_csv
from .leagues import SEASON_LENGTH, get_league
from .season import SeasonSimulator, build_schedule, compute_standings, standings_table
from .sports import get_simulator

SPORTS = ("nfl", "nba", "mlb", "nhl")


# --------------------------------------------------------------------------
def _load_ratings(args, games: list[Game] | None):
    """Ratings come from a file if given, otherwise they are fit from games."""
    if args.ratings:
        return read_ratings_csv(args.ratings)
    if games:
        fit = fit_for_sport(games, args.sport)
        elo = EloModel(args.sport).fit(games)
        ratings = fit.ratings()
        for team, r in ratings.items():
            r.elo = elo.get(team)
        return ratings
    return {}


def _games_for(args) -> list[Game]:
    if args.games:
        return read_games_csv(args.games)
    return []


# --------------------------------------------------------------------------
def cmd_game(args) -> int:
    games = _games_for(args)
    ratings = _load_ratings(args, games)
    sim = get_simulator(args.sport, playoff=args.playoff)
    home = ratings.get(args.home, TeamRating(args.home))
    away = ratings.get(args.away, TeamRating(args.away))
    home.team, away.team = args.home, args.away

    forecast = sim.forecast(home, away, n=args.sims, rng=args.seed, neutral=args.neutral)
    if args.json:
        print(json.dumps(forecast.to_dict(), indent=2))
        return 0

    print(forecast.report())
    if args.spread is not None:
        print(f"  P({args.home} {args.spread:+g}) = {forecast.cover_prob(args.spread):.1%}")
    if args.total is not None:
        print(f"  P(over {args.total:g})   = {forecast.over_prob(args.total):.1%}")

    if args.odds:
        lines = json.loads(args.odds)
        edges = scan_edges(forecast, lines, kelly_multiplier=args.kelly)
        print("\nmodel vs market")
        print("-" * 52)
        for e in edges:
            print(f"  {e}")
    return 0


def cmd_rate(args) -> int:
    games = _games_for(args)
    if not games:
        print("no games supplied; use --games or run the demo command", file=sys.stderr)
        return 2
    played = [g for g in games if g.played]
    fit = fit_for_sport(played, args.sport)
    elo = EloModel(args.sport).fit(played)
    margin = fit_ridge_margin(played)

    print(f"{args.sport.upper()} ratings from {len(played):,} games")
    print(f"home advantage: {fit.home_factor:.3f}x scoring, {margin.home_advantage:+.2f} points\n")
    print(f"{'team':<6} {'attack':>8} {'defense':>8} {'net':>8} {'elo':>7} {'pts':>7}")
    print("-" * 50)
    for team, att, dfn, net in fit.table():
        print(f"{team:<6} {att:>8.3f} {dfn:>8.3f} {net:>+8.3f} {elo.get(team):>7.0f} {margin.ratings[team]:>+7.2f}")

    if args.out:
        ratings = fit.ratings()
        for team, r in ratings.items():
            r.elo = elo.get(team)
        write_ratings_csv(args.out, ratings)
        print(f"\nwrote {args.out}")
    return 0


def cmd_season(args) -> int:
    games = _games_for(args)
    league = get_league(args.sport)
    ratings = _load_ratings(args, [g for g in games if g.played])
    if not ratings:
        print("no ratings and no games to fit them from", file=sys.stderr)
        return 2

    schedule = [g for g in games if not g.played]
    if not schedule:
        # Nothing left to play: project a fresh season instead.
        schedule = build_schedule(league, SEASON_LENGTH[args.sport], sport=args.sport, rng=args.seed)

    if games:
        played = [g for g in games if g.played]
        if played and args.standings:
            print(standings_table(compute_standings(played, league.teams, args.sport == "nhl"), league, args.sport == "nhl"))

    sim = SeasonSimulator(args.sport, ratings, league=league)
    result = sim.run(schedule, n_sims=args.sims, rng=args.seed, include_playoffs=not args.no_playoffs)
    if args.json:
        print(json.dumps(result.summary(), indent=2))
    else:
        print(result.report(top=args.top))
    return 0


def cmd_backtest(args) -> int:
    games = [g for g in _games_for(args) if g.played]
    if len(games) < 200:
        print("backtesting needs a few hundred completed games", file=sys.stderr)
        return 2
    if args.compare:
        print(compare_models(games, args.sport, min_games=args.min_games, refit_every=args.refit_every, sims=args.sims))
        return 0
    result = walk_forward(
        games,
        args.sport,
        method=args.method,
        min_games=args.min_games,
        refit_every=args.refit_every,
        sims=args.sims,
    )
    print(result.report())
    return 0


def cmd_demo(args) -> int:
    """Fit ratings on a simulated season and project the next one."""
    sport = args.sport
    print(f"generating a synthetic {sport.upper()} season...")
    season = generate_season(sport, seed=args.seed)
    played = [g for g in season.games if g.played]

    fit = fit_for_sport(played, sport)
    ratings = fit.ratings()
    elo = EloModel(sport).fit(played)
    for team, r in ratings.items():
        r.elo = elo.get(team)

    print(f"\n{len(played):,} games played. Top rated teams:")
    print(f"{'team':<6} {'attack':>8} {'defense':>8} {'net':>8} {'elo':>7}")
    print("-" * 42)
    for team, att, dfn, net in fit.table()[:6]:
        print(f"{team:<6} {att:>8.3f} {dfn:>8.3f} {net:>+8.3f} {elo.get(team):>7.0f}")

    best, worst = fit.table()[0][0], fit.table()[-1][0]
    sim = get_simulator(sport)
    print()
    print(sim.forecast(ratings[best], ratings[worst], n=args.sims, rng=args.seed).report())

    print(f"\nprojecting the next {sport.upper()} season ({args.season_sims:,} simulations)...")
    schedule = build_schedule(season.league, SEASON_LENGTH[sport], sport=sport, rng=args.seed)
    result = SeasonSimulator(sport, ratings, league=season.league).run(
        schedule, n_sims=args.season_sims, rng=args.seed
    )
    print()
    print(result.report(top=args.top))
    return 0


# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sportsim", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--sport", choices=SPORTS, required=True)
        p.add_argument("--games", type=Path, help="CSV of results and/or fixtures")
        p.add_argument("--ratings", type=Path, help="CSV of team ratings (skips fitting)")
        p.add_argument("--seed", type=int, default=0)

    g = sub.add_parser("game", help="forecast a single game")
    common(g)
    g.add_argument("--home", required=True)
    g.add_argument("--away", required=True)
    g.add_argument("--sims", type=int, default=40_000)
    g.add_argument("--neutral", action="store_true", help="neutral site")
    g.add_argument("--playoff", action="store_true", help="use postseason rules")
    g.add_argument("--spread", type=float, help="home spread to price, e.g. -3.5")
    g.add_argument("--total", type=float, help="game total to price")
    g.add_argument("--odds", help='market prices as JSON, e.g. \'{"moneyline":{"home":-140,"away":120}}\'')
    g.add_argument("--kelly", type=float, default=0.25, help="Kelly fraction for staking")
    g.add_argument("--json", action="store_true")
    g.set_defaults(func=cmd_game)

    r = sub.add_parser("rate", help="fit team ratings from results")
    common(r)
    r.add_argument("--out", type=Path, help="write ratings to this CSV")
    r.set_defaults(func=cmd_rate)

    s = sub.add_parser("season", help="simulate a season and the playoffs")
    common(s)
    s.add_argument("--sims", type=int, default=5_000)
    s.add_argument("--top", type=int, default=None, help="only show this many teams")
    s.add_argument("--standings", action="store_true", help="print current standings first")
    s.add_argument("--no-playoffs", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_season)

    b = sub.add_parser("backtest", help="walk-forward evaluation")
    common(b)
    b.add_argument("--method", choices=("simulator", "ridge"), default="simulator")
    b.add_argument("--min-games", type=int, default=150)
    b.add_argument("--refit-every", type=int, default=50)
    b.add_argument("--sims", type=int, default=4_000)
    b.add_argument("--compare", action="store_true", help="score Elo, ridge and the simulator together")
    b.set_defaults(func=cmd_backtest)

    d = sub.add_parser("demo", help="run the whole pipeline on synthetic data")
    d.add_argument("--sport", choices=SPORTS, default="nfl")
    d.add_argument("--seed", type=int, default=0)
    d.add_argument("--sims", type=int, default=40_000)
    d.add_argument("--season-sims", type=int, default=2_000)
    d.add_argument("--top", type=int, default=10)
    d.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

