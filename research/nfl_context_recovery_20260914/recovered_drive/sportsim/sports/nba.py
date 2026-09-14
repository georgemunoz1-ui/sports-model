"""NBA game simulator.

Basketball is the easiest of the four to model well: possessions are shared
between the two teams, points per possession is stable, and the resulting score
distribution is close to normal.  Drawing the possession count once per game and
using it for both teams reproduces the real positive correlation between the two
final scores -- which is what makes totals and sides consistent with each other.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.types import ScoreSamples, TeamRating
from .base import GameSimulator, broadcast_rate, resolve_rng


@dataclass
class NBAConfig:
    #: league-average possessions per team per 48 minutes
    league_pace: float = 99.0
    #: game-to-game variation in pace
    pace_sd: float = 6.0
    #: league-average points per possession
    league_ppp: float = 1.145
    #: per-possession scoring noise; sd(team score) ~= ppp_sd * sqrt(possessions)
    ppp_sd: float = 0.97
    #: shared per-game shooting environment, as a fraction of efficiency. Along
    #: with the shared possession count this reproduces the ~0.4 correlation
    #: between the two final scores, which sides and totals both depend on.
    env_sd: float = 0.035
    #: home scoring edge (about +2.3 points on a neutral-court baseline)
    home_factor: float = 1.021
    #: overtime length as a fraction of regulation
    ot_fraction: float = 5.0 / 48.0


class NBASimulator(GameSimulator):
    """Possession-based normal scoring with 5-minute overtime periods."""

    sport = "nba"

    def __init__(self, config: NBAConfig | None = None, playoff: bool = False):
        self.config = config or NBAConfig()
        self.playoff = playoff

    def simulate(
        self,
        home: TeamRating,
        away: TeamRating,
        n: int | None = None,
        rng: np.random.Generator | int | None = None,
        neutral: bool = False,
    ) -> ScoreSamples:
        n = self._n(n)
        rng = resolve_rng(rng)
        cfg = self.config

        # Both teams face the same number of possessions (+/- one), so pace is a
        # single shared draw per simulated game.
        pace_mult = np.asarray(home.pace, dtype=float) * np.asarray(away.pace, dtype=float)
        mean_poss = broadcast_rate(cfg.league_pace * pace_mult, n)
        possessions = np.maximum(rng.normal(mean_poss, cfg.pace_sd), 60.0)

        hf = 1.0 if neutral else np.sqrt(cfg.home_factor)
        env = rng.normal(1.0, cfg.env_sd, n) if cfg.env_sd > 0 else 1.0
        h_ppp = broadcast_rate(cfg.league_ppp * np.asarray(home.attack) * np.asarray(away.defense) * hf, n) * env
        a_ppp = broadcast_rate(cfg.league_ppp * np.asarray(away.attack) * np.asarray(home.defense) / hf, n) * env

        sd = cfg.ppp_sd * np.sqrt(possessions)
        hs = np.rint(rng.normal(possessions * h_ppp, sd)).astype(int)
        as_ = np.rint(rng.normal(possessions * a_ppp, sd)).astype(int)

        ot = hs == as_
        # NBA plays 5-minute overtimes until someone leads. Only the still-tied
        # games are carried into each extra period.
        tied = np.nonzero(ot)[0]
        ot_poss = possessions * cfg.ot_fraction
        ot_sd = cfg.ppp_sd * np.sqrt(ot_poss)
        for _ in range(12):
            if tied.size == 0:
                break
            hs[tied] += np.rint(rng.normal(ot_poss[tied] * h_ppp[tied], ot_sd[tied])).astype(int)
            as_[tied] += np.rint(rng.normal(ot_poss[tied] * a_ppp[tied], ot_sd[tied])).astype(int)
            tied = tied[hs[tied] == as_[tied]]
        if tied.size:
            # Guarantee a winner rather than leaking a tie into the standings.
            coin = rng.random(tied.size) < 0.5
            hs[tied] += coin
            as_[tied] += ~coin

        return self._tag(ScoreSamples(home=hs, away=as_, ot=ot), home, away)

