"""Generate a synthetic league season with known true ratings.

Useful for two things: running the whole pipeline end to end without hunting
down a data feed, and validating the rating fitters -- since the true strengths
are known, you can check that the estimates recover them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.types import Game, LeagueStructure, TeamRating
from ..leagues import SEASON_LENGTH, get_league
from ..season.schedule import build_schedule
from ..sports import get_simulator

#: Realistic spread of true team strength, as a standard deviation of the
#: attack/defence multipliers. These are set so that a +2 sigma team lands where
#: the best real teams land: about +11 points a game in the NFL, +11 net rating
#: in the NBA, +0.7 goals in the NHL and +1.0 runs in MLB.
STRENGTH_SD: dict[str, float] = {"nfl": 0.065, "nba": 0.033, "nhl": 0.050, "mlb": 0.045}


@dataclass
class SyntheticSeason:
    sport: str
    league: LeagueStructure
    true_ratings: dict[str, TeamRating]
    games: list[Game]

    @property
    def schedule(self) -> list[Game]:
        """The same fixtures with results stripped out."""
        return [Game(home=g.home, away=g.away, date=g.date, season=g.season) for g in self.games]


def generate_season(
    sport: str = "nfl",
    seed: int | None = 0,
    games_per_team: int | None = None,
    strength_sd: float | None = None,
    season: int = 2025,
    played_fraction: float = 1.0,
) -> SyntheticSeason:
    """Draw team strengths, build a schedule, and play it out.

    ``played_fraction`` below 1.0 leaves the tail of the schedule unplayed,
    which is how you get a mid-season "rest of season" projection.
    """
    rng = np.random.default_rng(seed)
    sport = sport.lower()
    league = get_league(sport)
    teams = league.teams
    sd = STRENGTH_SD[sport] if strength_sd is None else strength_sd

    true_ratings = {
        t: TeamRating(
            team=t,
            attack=float(np.exp(rng.normal(0, sd))),
            defense=float(np.exp(rng.normal(0, sd))),
        )
        for t in teams
    }

    schedule = build_schedule(
        league,
        games_per_team or SEASON_LENGTH[sport],
        sport=sport,
        rng=rng,
        start_date=None,
    )
    for i, g in enumerate(schedule):
        g.season = season
        g.date = f"{season}-{1 + i * 6 // len(schedule):02d}-01"

    sim = get_simulator(sport)
    n_played = int(len(schedule) * played_fraction)
    if n_played:
        # One simulate() call for the whole season: the rating fields are arrays,
        # so each draw uses its own game's teams.
        played = schedule[:n_played]
        home = TeamRating(
            team="home",
            attack=np.array([true_ratings[g.home].attack for g in played]),
            defense=np.array([true_ratings[g.home].defense for g in played]),
        )
        away = TeamRating(
            team="away",
            attack=np.array([true_ratings[g.away].attack for g in played]),
            defense=np.array([true_ratings[g.away].defense for g in played]),
        )
        s = sim.simulate(home, away, n=n_played, rng=rng)
        for g, hs, as_, ot in zip(played, s.home, s.away, s.ot):
            g.home_score = int(hs)
            g.away_score = int(as_)
            g.went_ot = bool(ot)

    return SyntheticSeason(sport=sport, league=league, true_ratings=true_ratings, games=schedule)
