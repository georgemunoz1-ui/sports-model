"""NHL game simulator.

Goals are close to Poisson in hockey, so regulation is two independent Poisson
draws scaled by attack/defence.  What actually needs care is the tail: roughly
a quarter of NHL games reach 3-on-3 overtime, and the winner there is nearly a
coin flip regardless of team quality -- which is exactly why hockey moneylines
compress toward even money.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.types import ScoreSamples, TeamRating
from .base import GameSimulator, broadcast_rate, resolve_rng, scoring_rates


@dataclass
class NHLConfig:
    #: regulation goals per team for a league-average matchup
    league_mean_goals: float = 2.92
    #: home teams score this much more than road teams
    home_factor: float = 1.045
    #: P(a one-goal game is levelled late). Independent Poisson draws produce
    #: about 17% regulation ties, but real hockey sees ~23%: the trailing team
    #: pulls its goalie and the leading team sits back, so one-goal leads
    #: collapse more often than independence implies.
    late_equalizer_prob: float = 0.16
    #: P(a goal is scored in the 5-minute 3-on-3 overtime)
    ot_goal_prob: float = 0.63
    #: how much team strength carries over into OT/shootout (1.0 = full)
    ot_strength_weight: float = 0.55
    #: shootouts are close to a coin flip; this damps strength further
    shootout_strength_weight: float = 0.25


class NHLSimulator(GameSimulator):
    """Poisson regulation scoring plus 3-on-3 overtime and a shootout."""

    sport = "nhl"

    def __init__(self, config: NHLConfig | None = None, playoff: bool = False):
        self.config = config or NHLConfig()
        #: playoff overtime is full 5-on-5 sudden death -- no shootout, and it
        #: keeps going until someone scores
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

        h_rate, a_rate = scoring_rates(home, away, cfg.league_mean_goals, cfg.home_factor, neutral)
        h_rate = broadcast_rate(h_rate, n)
        a_rate = broadcast_rate(a_rate, n)

        hs = rng.poisson(h_rate)
        as_ = rng.poisson(a_rate)

        # Late equaliser: the trailing side in a one-goal game ties it up.
        if cfg.late_equalizer_prob > 0:
            one_goal = np.abs(hs - as_) == 1
            equalize = one_goal & (rng.random(n) < cfg.late_equalizer_prob)
            hs = hs + (equalize & (hs < as_))
            as_ = as_ + (equalize & (as_ < hs))

        tied = hs == as_
        ot = tied.copy()
        if tied.any():
            # Strength edge in the extra session, damped toward a coin flip.
            share = h_rate / (h_rate + a_rate)
            ot_share = 0.5 + (share - 0.5) * cfg.ot_strength_weight
            so_share = 0.5 + (share - 0.5) * cfg.shootout_strength_weight

            if self.playoff:
                home_wins_extra = rng.random(n) < ot_share
            else:
                scored_in_ot = rng.random(n) < cfg.ot_goal_prob
                ot_winner = rng.random(n) < ot_share
                so_winner = rng.random(n) < so_share
                home_wins_extra = np.where(scored_in_ot, ot_winner, so_winner)

            hs = hs + (tied & home_wins_extra)
            as_ = as_ + (tied & ~home_wins_extra)

        return self._tag(ScoreSamples(home=hs.astype(int), away=as_.astype(int), ot=ot), home, away)

