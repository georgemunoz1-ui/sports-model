"""Schedule construction.

Real league schedules are the output of a constraint solver (travel, TV windows,
stadium availability).  What a season simulation actually needs is the right
*opponent mix* -- how often a team plays inside its division versus outside its
conference -- because that is what determines strength of schedule.  This module
builds a balanced schedule with the correct mix and leaves the calendar details
alone.

For real projections, load the actual schedule with
:func:`sportsim.data.read_games_csv` instead.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Sequence

import numpy as np

from ..core.types import Game, LeagueStructure

#: Relative frequency of division / conference / inter-conference games.
OPPONENT_WEIGHTS: dict[str, tuple[float, float, float]] = {
    "nfl": (6.0, 1.6, 1.0),
    "nba": (3.9, 3.4, 2.0),
    "nhl": (3.5, 3.0, 2.0),
    "mlb": (13.0, 6.0, 1.0),
}


def build_schedule(
    league: LeagueStructure,
    games_per_team: int,
    sport: str | None = None,
    rng: np.random.Generator | int | None = None,
    start_date: date | None = None,
    games_per_day: int | None = None,
) -> list[Game]:
    """Build a balanced unplayed schedule with a realistic opponent mix.

    Each team ends up with ``games_per_team`` games (within rounding), split
    home and away as evenly as the pairing counts allow.
    """
    rng = rng if isinstance(rng, np.random.Generator) else np.random.default_rng(rng)
    teams = league.teams
    n = len(teams)
    if n < 2:
        raise ValueError("need at least two teams")

    w_div, w_conf, w_inter = OPPONENT_WEIGHTS.get((sport or league.name).lower(), (3.0, 2.0, 1.0))

    def tier(a: str, b: str) -> float:
        if league.division_of(a) == league.division_of(b):
            return w_div
        if league.conference_of(a) == league.conference_of(b):
            return w_conf
        return w_inter

    # Scale the weights so each team's games sum to the target.
    pairs = [(teams[i], teams[j]) for i in range(n) for j in range(i + 1, n)]
    weights = {p: tier(*p) for p in pairs}
    per_team_weight = np.zeros(n)
    index = {t: i for i, t in enumerate(teams)}
    for (a, b), w in weights.items():
        per_team_weight[index[a]] += w
        per_team_weight[index[b]] += w
    scale = games_per_team / per_team_weight.mean()

    counts: dict[tuple[str, str], int] = {}
    for p, w in weights.items():
        exact = w * scale
        base = int(np.floor(exact))
        counts[p] = base + int(rng.random() < (exact - base))

    # Rounding leaves some teams a game or two off target, so trade games
    # between the most over-scheduled and most under-scheduled teams until
    # everyone is level.
    totals = np.zeros(n)
    for (a, b), c in counts.items():
        totals[index[a]] += c
        totals[index[b]] += c

    by_team: dict[str, list[tuple[str, str]]] = {t: [] for t in teams}
    for p in pairs:
        by_team[p[0]].append(p)
        by_team[p[1]].append(p)

    def partner(pair: tuple[str, str], team: str) -> str:
        return pair[1] if pair[0] == team else pair[0]

    for _ in range(20 * n):
        over_i, under_i = int(np.argmax(totals)), int(np.argmin(totals))
        if totals[over_i] <= games_per_team and totals[under_i] >= games_per_team:
            break
        if totals[over_i] > games_per_team:
            team = teams[over_i]
            options = [p for p in by_team[team] if counts[p] > 0 and totals[index[partner(p, team)]] > games_per_team]
            options = options or [p for p in by_team[team] if counts[p] > 0]
            # Trim the most-played opponent first to keep the mix balanced.
            pick = max(options, key=lambda p: (counts[p], -totals[index[partner(p, team)]]))
            counts[pick] -= 1
            totals[index[pick[0]]] -= 1
            totals[index[pick[1]]] -= 1
        else:
            team = teams[under_i]
            pick = min(by_team[team], key=lambda p: (totals[index[partner(p, team)]], -weights[p]))
            counts[pick] += 1
            totals[index[pick[0]]] += 1
            totals[index[pick[1]]] += 1

    games: list[Game] = []
    for (a, b), c in counts.items():
        # Split hosting duties; an odd game goes to a random side.
        home_a = c // 2 + (int(rng.random() < 0.5) if c % 2 else 0)
        for _ in range(home_a):
            games.append(Game(home=a, away=b))
        for _ in range(c - home_a):
            games.append(Game(home=b, away=a))

    rng.shuffle(games)
    if start_date is not None:
        per_day = games_per_day or max(1, n // 4)
        for i, g in enumerate(games):
            g.date = (start_date + timedelta(days=i // per_day)).isoformat()
    return games


def remaining_schedule(schedule: Sequence[Game]) -> list[Game]:
    return [g for g in schedule if not g.played]


def merge_results(schedule: Sequence[Game], results: Sequence[Game]) -> list[Game]:
    """Overlay completed results onto a schedule, matching on teams and date.

    Anything that does not match is appended, so partial-season files still
    work.
    """
    out = [Game(**vars(g)) for g in schedule]
    keyed: dict[tuple[str, str, str | None], list[Game]] = {}
    for g in out:
        keyed.setdefault((g.home, g.away, g.date), []).append(g)
    loose: dict[tuple[str, str], list[Game]] = {}
    for g in out:
        loose.setdefault((g.home, g.away), []).append(g)

    # A result the schedule already carries must not be applied a second time,
    # or the same game gets counted twice -- once where it belongs and once on a
    # future fixture between the same teams.
    already = set()
    for g in out:
        if g.played:
            already.add((g.home, g.away, g.date, g.home_score, g.away_score))

    for r in results:
        if not r.played:
            continue
        if (r.home, r.away, r.date, r.home_score, r.away_score) in already:
            continue
        target = None
        exact = keyed.get((r.home, r.away, r.date))
        if exact:
            target = next((g for g in exact if not g.played), None)
        if target is None:
            candidates = loose.get((r.home, r.away), [])
            target = next((g for g in candidates if not g.played), None)
        if target is None:
            out.append(Game(**vars(r)))
            continue
        target.home_score = r.home_score
        target.away_score = r.away_score
        target.went_ot = r.went_ot
        if r.date:
            target.date = r.date
    return out
