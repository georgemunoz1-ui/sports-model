"""Standings bookkeeping and seeding.

Real leagues have long, baroque tiebreaker lists (head-to-head, division
record, common games, strength of victory...).  This module implements the
first two levels -- points/wins, then differential -- and breaks anything still
level with a per-simulation random draw, which is the honest way to represent
"a coin flip we are not modelling" inside a Monte Carlo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from ..core.types import Game, LeagueStructure


@dataclass
class TeamRecord:
    team: str
    wins: float = 0.0
    losses: float = 0.0
    ties: float = 0.0
    ot_losses: float = 0.0
    points_for: float = 0.0
    points_against: float = 0.0

    @property
    def games(self) -> float:
        return self.wins + self.losses + self.ties

    @property
    def win_pct(self) -> float:
        played = self.games
        return (self.wins + 0.5 * self.ties) / played if played else 0.0

    @property
    def differential(self) -> float:
        return self.points_for - self.points_against

    def points(self, ot_points: bool = False) -> float:
        """Standings points. Hockey awards 2 for a win and 1 for an OT loss."""
        if ot_points:
            return 2 * self.wins + self.ot_losses
        return self.wins + 0.5 * self.ties


def compute_standings(
    games: Sequence[Game],
    teams: Sequence[str] | None = None,
    ot_points: bool = False,
) -> dict[str, TeamRecord]:
    """Build records from completed games."""
    records: dict[str, TeamRecord] = {}

    def rec(team: str) -> TeamRecord:
        return records.setdefault(team, TeamRecord(team=team))

    for t in teams or []:
        rec(t)

    for g in games:
        if not g.played:
            continue
        h, a = rec(g.home), rec(g.away)
        h.points_for += g.home_score
        h.points_against += g.away_score
        a.points_for += g.away_score
        a.points_against += g.home_score
        if g.margin > 0:
            h.wins += 1
            a.losses += 1
            if g.went_ot and ot_points:
                a.ot_losses += 1
        elif g.margin < 0:
            a.wins += 1
            h.losses += 1
            if g.went_ot and ot_points:
                h.ot_losses += 1
        else:
            h.ties += 1
            a.ties += 1
    return records


def standings_table(records: dict[str, TeamRecord], league: LeagueStructure | None = None, ot_points: bool = False) -> str:
    lines: list[str] = []
    groups: dict[str, list[str]]
    if league is None:
        groups = {"League": sorted(records)}
    else:
        groups = {f"{conf} / {div}": members for conf, divs in league.conferences.items() for div, members in divs.items()}

    for title, members in groups.items():
        rows = [records[t] for t in members if t in records]
        rows.sort(key=lambda r: (-r.points(ot_points), -r.differential))
        lines.append(title)
        header = f"  {'team':<6} {'W':>4} {'L':>4}"
        if ot_points:
            header += f" {'OTL':>4} {'PTS':>5}"
        else:
            header += f" {'T':>4} {'PCT':>6}"
        lines.append(header + f" {'DIFF':>7}")
        for r in rows:
            line = f"  {r.team:<6} {r.wins:>4.0f} {r.losses:>4.0f}"
            if ot_points:
                line += f" {r.ot_losses:>4.0f} {r.points(True):>5.0f}"
            else:
                line += f" {r.ties:>4.0f} {r.win_pct:>6.3f}"
            lines.append(line + f" {r.differential:>+7.0f}")
        lines.append("")
    return "\n".join(lines)


def rank_within(
    points: np.ndarray,
    differential: np.ndarray,
    indices: Sequence[int],
    tiebreak: np.ndarray,
) -> np.ndarray:
    """Order ``indices`` best-to-worst for every simulation at once.

    ``points`` and ``differential`` are ``(n_sims, n_teams)``; ``tiebreak`` is a
    random array of the same shape that settles exact ties.  Returns an
    ``(n_sims, len(indices))`` array of team indices.
    """
    idx = np.asarray(indices)
    # A single sort key: points dominate, differential breaks ties, and the
    # random term separates anything still level.
    key = points[:, idx] * 1e6 + np.clip(differential[:, idx], -4e5, 4e5) + tiebreak[:, idx]
    order = np.argsort(-key, axis=1, kind="stable")
    return idx[order]
