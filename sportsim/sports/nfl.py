"""NFL game simulator.

Football scores are lumpy -- 3s and 7s, not a smooth curve -- so simulating the
final score directly with a normal distribution gets the key numbers wrong.  This
model works drive by drive instead: each possession ends in a touchdown, a field
goal, nothing, or a defensive score, and the points accumulate in realistic
increments.  That reproduces the spikes at margins of 3, 7, 4 and 10 that make
NFL key numbers matter so much when pricing a spread.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.types import ScoreSamples, TeamRating
from .base import GameSimulator, broadcast_rate, resolve_rng


@dataclass
class NFLConfig:
    #: possessions per team in regulation, before the opening-kickoff extra one
    drives_per_team: float = 10.6
    drives_sd: float = 1.1
    #: baseline drive outcomes for a league-average offence
    td_prob: float = 0.213
    fg_prob: float = 0.155
    #: turnover returned for a touchdown by the defence
    defensive_td_prob: float = 0.013
    safety_prob: float = 0.004
    #: How team quality splits between touchdowns and field goals. A better
    #: offence converts drives into touchdowns rather than field goals, so the
    #: touchdown rate is the elastic one. The pair is chosen so that total points
    #: scale linearly with the attack multiplier -- the same units the rating
    #: fitters produce -- while the scoring mix still shifts with quality.
    td_elasticity: float = 1.3
    fg_elasticity: float = 0.2
    #: Home edge as a scoring multiplier: about +1.9 points on the spread once
    #: it is split between the two offences.
    home_factor: float = 1.085
    #: shared per-game scoring environment (weather, tempo, officiating). Both
    #: offences move together, which is why NFL final scores are positively
    #: correlated rather than independent.
    env_sd: float = 0.06
    #: scoring plays
    xp_success: float = 0.945
    two_point_attempt_rate: float = 0.11
    two_point_success: float = 0.475
    #: regular-season overtime is 10 minutes and may end in a tie
    ot_drives_per_team: int = 2
    allow_ties: bool = True


class NFLSimulator(GameSimulator):
    """Drive-outcome simulator producing football-shaped score distributions."""

    sport = "nfl"

    def __init__(self, config: NFLConfig | None = None, playoff: bool = False):
        self.config = config or NFLConfig()
        self.playoff = playoff
        if playoff:
            self.config.allow_ties = False

    # -- internals ---------------------------------------------------------
    def _drive_probs(self, strength: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Per-drive outcome probabilities for an offence of the given strength.

        ``strength`` is the offence's attack multiplier times the defence's
        multiplier, i.e. 1.0 for a league-average matchup.
        """
        cfg = self.config
        td = cfg.td_prob * strength**cfg.td_elasticity
        fg = cfg.fg_prob * strength**cfg.fg_elasticity
        # A better offence also gives the ball away for scores less often.
        def_td = cfg.defensive_td_prob / np.maximum(strength, 0.4)
        safety = np.full_like(td, cfg.safety_prob)

        scoring = td + fg + def_td + safety
        # Keep everything a valid distribution even for extreme rating inputs.
        over = scoring > 0.95
        if np.any(over):
            scale = np.where(over, 0.95 / np.maximum(scoring, 1e-9), 1.0)
            td, fg, def_td, safety = td * scale, fg * scale, def_td * scale, safety * scale
        return td, fg, def_td, safety

    def _drive_points(
        self,
        rng: np.random.Generator,
        n_drives: np.ndarray,
        td: np.ndarray,
        fg: np.ndarray,
        def_td: np.ndarray,
        safety: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Points scored by the offence and by the defending team.

        Drives within a game are independent draws from the same outcome
        distribution, so the whole game's worth of drives is one multinomial
        rather than a loop -- identical in distribution and far quicker.
        """
        cfg = self.config
        none = 1.0 - (td + fg + def_td + safety)
        pvals = np.stack([td, fg, def_td, safety, none], axis=1)
        counts = rng.multinomial(n_drives, pvals)
        n_td, n_fg, n_dtd, n_saf = counts[:, 0], counts[:, 1], counts[:, 2], counts[:, 3]

        # Every touchdown is followed by a kick or a two-point try.
        n_two = rng.binomial(n_td, cfg.two_point_attempt_rate)
        two_good = rng.binomial(n_two, cfg.two_point_success)
        xp_good = rng.binomial(n_td - n_two, cfg.xp_success)
        offense = 6 * n_td + 2 * two_good + xp_good + 3 * n_fg

        # A defensive touchdown gets the extra point too; safeties are worth 2.
        defense = 6 * n_dtd + rng.binomial(n_dtd, cfg.xp_success) + 2 * n_saf
        return offense.astype(int), defense.astype(int)

    def _play_drives(
        self,
        rng: np.random.Generator,
        h_strength: np.ndarray,
        a_strength: np.ndarray,
        h_drives: np.ndarray,
        a_drives: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        h_td, h_fg, h_dtd, h_saf = self._drive_probs(h_strength)
        a_td, a_fg, a_dtd, a_saf = self._drive_probs(a_strength)

        h_off, a_def_pts = self._drive_points(rng, h_drives, h_td, h_fg, h_dtd, h_saf)
        a_off, h_def_pts = self._drive_points(rng, a_drives, a_td, a_fg, a_dtd, a_saf)
        return h_off + h_def_pts, a_off + a_def_pts

    # -- public ------------------------------------------------------------
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
        env = np.maximum(rng.normal(1.0, cfg.env_sd, n), 0.3) if cfg.env_sd > 0 else 1.0
        h_strength = broadcast_rate(np.asarray(home.attack) * np.asarray(away.defense) * hf, n) * env
        a_strength = broadcast_rate(np.asarray(away.attack) * np.asarray(home.defense) / hf, n) * env

        # Possessions alternate, so the two teams are within one drive of each
        # other; the extra one goes to whoever received the opening kickoff.
        base = np.maximum(np.rint(rng.normal(cfg.drives_per_team, cfg.drives_sd, n)), 6).astype(int)
        extra_home = rng.random(n) < 0.5
        h_drives = base + extra_home
        a_drives = base + ~extra_home

        hs, as_ = self._play_drives(rng, h_strength, a_strength, h_drives, a_drives)

        # ---- overtime ----
        # Only the tied games play on. Overtime is rare, so simulating the whole
        # batch each round would dominate the cost of the entire function.
        ot = hs == as_
        tied = np.nonzero(ot)[0]
        rounds = 1 if cfg.allow_ties else 8
        for _ in range(rounds):
            if tied.size == 0:
                break
            ot_drives = np.full(tied.size, cfg.ot_drives_per_team, dtype=int)
            add_h, add_a = self._play_drives(rng, h_strength[tied], a_strength[tied], ot_drives, ot_drives)
            hs[tied] += add_h
            as_[tied] += add_a
            tied = tied[hs[tied] == as_[tied]]
        if tied.size and not cfg.allow_ties:
            # A playoff game has to produce a winner; award a field goal.
            coin = rng.random(tied.size) < 0.5
            hs[tied] += 3 * coin
            as_[tied] += 3 * ~coin

        return self._tag(ScoreSamples(home=hs, away=as_, ot=ot), home, away)
