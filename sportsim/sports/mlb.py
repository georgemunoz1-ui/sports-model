"""MLB game simulator.

Baseball is simulated at the plate-appearance level with a base-out state
machine.  That extra detail buys three things a score-level model cannot give
you: the strong right skew of run distributions (the occasional 11-run inning),
correct handling of the home team not batting in the ninth when it already
leads, and walk-off innings that stop the moment the winning run scores.  All
three matter for run lines and team totals.

Every simulated game is advanced in lockstep with numpy, so a plate appearance
is one vectorised draw across all simulations rather than a Python loop per
game.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.types import ScoreSamples, TeamRating
from .base import GameSimulator, broadcast_rate, resolve_rng

# League-average plate-appearance outcome rates: out, walk/HBP, 1B, 2B, 3B, HR.
LEAGUE_PA_RATES = np.array([0.6740, 0.0925, 0.1470, 0.0470, 0.0040, 0.0355])


@dataclass
class MLBConfig:
    pa_rates: tuple[float, ...] = tuple(LEAGUE_PA_RATES)
    #: Home scoring edge *per inning batted*. It looks large next to the other
    #: sports because the home team bats only ~8.5 innings: the per-game gap
    #: (about 4.44 vs 4.32 runs) needs a bigger per-inning edge to survive the
    #: skipped bottom of the ninth.
    home_factor: float = 1.085
    #: on-base events scale as strength**exponent; runs are convex in OBP, so
    #: this exponent is what makes runs scale roughly linearly with the rating
    event_exponent: float = 0.44
    innings: int = 9
    #: extra innings start with a runner on second (the "ghost runner")
    ghost_runner: bool = True
    #: hard stop so a pathological matchup cannot loop forever
    max_extra_innings: int = 20
    # -- baserunning tendencies --
    double_play_rate: float = 0.115
    sac_fly_rate: float = 0.16
    score_from_second_on_single: float = 0.55
    first_to_third_on_single: float = 0.28
    score_from_first_on_double: float = 0.42


class MLBSimulator(GameSimulator):
    """Plate-appearance Markov simulator with real extra-innings rules."""

    sport = "mlb"

    def __init__(self, config: MLBConfig | None = None, playoff: bool = False):
        self.config = config or MLBConfig()
        #: the postseason drops the ghost runner
        self.playoff = playoff
        if playoff:
            self.config.ghost_runner = False

    # -- outcome probabilities --------------------------------------------
    def _cumulative(self, strength: np.ndarray, n: int) -> np.ndarray:
        """Cumulative PA-outcome thresholds, shape (n, 5).

        Order is out, walk, single, double, triple; home runs are the remainder.
        """
        rates = np.asarray(self.config.pa_rates, dtype=float)
        mult = np.power(np.maximum(broadcast_rate(strength, n), 0.2), self.config.event_exponent)

        on_base = rates[1:] * mult[:, None]  # (n, 5)
        total_on_base = on_base.sum(axis=1)
        # An offence can't reach base every time; leave room for outs.
        scale = np.where(total_on_base > 0.75, 0.75 / np.maximum(total_on_base, 1e-9), 1.0)
        on_base = on_base * scale[:, None]

        probs = np.empty((n, 6))
        probs[:, 0] = 1.0 - on_base.sum(axis=1)
        probs[:, 1:] = on_base
        return np.cumsum(probs, axis=1)[:, :5]

    # -- one half inning ---------------------------------------------------
    def _half_inning(
        self,
        rng: np.random.Generator,
        cum: np.ndarray,
        active: np.ndarray,
        target: np.ndarray | None = None,
        start_on_second: bool = False,
    ) -> np.ndarray:
        """Runs scored by the batting team in every ``active`` simulation.

        ``target`` is the number of runs that ends the inning immediately (a
        walk-off); use ``np.inf`` for simulations that must play all three outs.
        """
        cfg = self.config
        n = cum.shape[0]
        total = np.zeros(n, dtype=np.int32)
        if target is None:
            target = np.full(n, np.inf)

        # Only the simulations still batting are carried forward. Innings end at
        # wildly different points, so without this compaction every array
        # operation would keep paying for simulations that finished long ago --
        # which is most of them after the first few plate appearances.
        live = np.nonzero(active)[0]
        if live.size == 0:
            return total

        c = cum[live]
        tgt = target[live]
        m = live.size
        runs = np.zeros(m, dtype=np.int32)
        outs = np.zeros(m, dtype=np.int8)
        b1 = np.zeros(m, dtype=bool)
        b2 = np.full(m, start_on_second)
        b3 = np.zeros(m, dtype=bool)

        # A half inning cannot last forever in practice; the cap is a safety net
        # far beyond any plausible inning.
        for _ in range(150):
            if live.size == 0:
                break
            m = live.size
            u = rng.random(m)
            is_out = u < c[:, 0]
            is_bb = (u >= c[:, 0]) & (u < c[:, 1])
            is_1b = (u >= c[:, 1]) & (u < c[:, 2])
            is_2b = (u >= c[:, 2]) & (u < c[:, 3])
            is_3b = (u >= c[:, 3]) & (u < c[:, 4])
            is_hr = u >= c[:, 4]

            r1, r2, r3 = rng.random(m), rng.random(m), rng.random(m)
            ob1, ob2, ob3 = b1.copy(), b2.copy(), b3.copy()

            # ---- out: double play, sacrifice fly, or nothing ----
            dp = is_out & ob1 & (outs < 2) & (r1 < cfg.double_play_rate)
            sac = is_out & ob3 & (outs < 2) & ~dp & (r2 < cfg.sac_fly_rate)
            runs += sac
            b3 = np.where(sac, False, b3)
            b1 = np.where(dp, False, b1)
            outs = outs + is_out.astype(np.int8) + dp.astype(np.int8)

            # ---- walk / HBP: forced advances only ----
            runs += (is_bb & ob1 & ob2 & ob3).astype(np.int32)
            b3 = np.where(is_bb, ob3 | (ob1 & ob2), b3)
            b2 = np.where(is_bb, ob2 | ob1, b2)
            b1 = np.where(is_bb, True, b1)

            # ---- single ----
            second_scores = ob2 & (r1 < cfg.score_from_second_on_single)
            first_to_third = ob1 & (r2 < cfg.first_to_third_on_single)
            runs += (is_1b * (ob3.astype(np.int32) + second_scores.astype(np.int32))).astype(np.int32)
            b3 = np.where(is_1b, (ob2 & ~second_scores) | first_to_third, b3)
            b2 = np.where(is_1b, ob1 & ~first_to_third, b2)
            b1 = np.where(is_1b, True, b1)

            # ---- double ----
            first_scores = ob1 & (r3 < cfg.score_from_first_on_double)
            runs += (is_2b * (ob3.astype(np.int32) + ob2.astype(np.int32) + first_scores.astype(np.int32))).astype(
                np.int32
            )
            b3 = np.where(is_2b, ob1 & ~first_scores, b3)
            b2 = np.where(is_2b, True, b2)
            b1 = np.where(is_2b, False, b1)

            # ---- triple ----
            runs += (is_3b * (ob1.astype(np.int32) + ob2.astype(np.int32) + ob3.astype(np.int32))).astype(np.int32)
            b3 = np.where(is_3b, True, b3)
            b2 = np.where(is_3b, False, b2)
            b1 = np.where(is_3b, False, b1)

            # ---- home run ----
            runs += (
                is_hr * (1 + ob1.astype(np.int32) + ob2.astype(np.int32) + ob3.astype(np.int32))
            ).astype(np.int32)
            b1 = np.where(is_hr, False, b1)
            b2 = np.where(is_hr, False, b2)
            b3 = np.where(is_hr, False, b3)

            keep = (outs < 3) & (runs < tgt)
            if keep.all():
                continue
            total[live[~keep]] = runs[~keep]
            live = live[keep]
            c, tgt = c[keep], tgt[keep]
            runs, outs = runs[keep], outs[keep]
            b1, b2, b3 = b1[keep], b2[keep], b3[keep]

        # Anything still batting when the safety cap hit keeps its runs.
        if live.size:
            total[live] = runs
        return total

    # -- full game ---------------------------------------------------------
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

        hf = 1.0 if neutral else np.sqrt(cfg.home_factor)
        h_strength = np.asarray(home.attack) * np.asarray(away.defense) * hf
        a_strength = np.asarray(away.attack) * np.asarray(home.defense) / hf
        h_cum = self._cumulative(h_strength, n)
        a_cum = self._cumulative(a_strength, n)

        hs = np.zeros(n, dtype=np.int32)
        as_ = np.zeros(n, dtype=np.int32)
        all_on = np.ones(n, dtype=bool)
        no_target = np.full(n, np.inf)

        for inning in range(1, cfg.innings + 1):
            as_ += self._half_inning(rng, a_cum, all_on, no_target)

            if inning < cfg.innings:
                hs += self._half_inning(rng, h_cum, all_on, no_target)
            else:
                # The home team does not bat in the ninth if it already leads,
                # and stops the moment it takes the lead.
                bats = hs <= as_
                target = np.where(bats, (as_ - hs + 1).astype(float), np.inf)
                hs += self._half_inning(rng, h_cum, bats, target)

        # ---- extra innings ----
        ot = hs == as_
        tied = ot.copy()
        for _ in range(cfg.max_extra_innings):
            if not tied.any():
                break
            as_ += self._half_inning(rng, a_cum, tied, no_target, start_on_second=cfg.ghost_runner)
            bats = tied & (hs <= as_)
            target = np.where(bats, (as_ - hs + 1).astype(float), np.inf)
            hs += self._half_inning(rng, h_cum, bats, target, start_on_second=cfg.ghost_runner)
            tied = tied & (hs == as_)
        if tied.any():
            coin = rng.random(n) < 0.5
            hs = hs + (tied & coin)
            as_ = as_ + (tied & ~coin)

        return self._tag(ScoreSamples(home=hs.astype(int), away=as_.astype(int), ot=ot), home, away)
