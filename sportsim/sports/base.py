"""Shared plumbing for the per-sport game simulators."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np

from ..core.types import GameForecast, ScoreSamples, TeamRating


def resolve_rng(rng: np.random.Generator | int | None) -> np.random.Generator:
    if isinstance(rng, np.random.Generator):
        return rng
    return np.random.default_rng(rng)


def as_rating(rating: TeamRating | str | None) -> TeamRating:
    """Accept a team name or a full rating; unknown teams are league-average."""
    if rating is None:
        return TeamRating()
    if isinstance(rating, str):
        return TeamRating(team=rating)
    return rating


class GameSimulator(ABC):
    """Base class for a single-game Monte Carlo engine.

    Subclasses implement :meth:`simulate`, which must return one simulated
    final score per draw with ties already resolved by the sport's overtime
    rules.  All internal math is elementwise, so a :class:`TeamRating` whose
    fields are length-``n`` arrays simulates ``n`` games with per-draw ratings.
    """

    sport: str = "generic"
    #: default number of draws when the caller does not say
    default_sims: int = 20_000

    @abstractmethod
    def simulate(
        self,
        home: TeamRating,
        away: TeamRating,
        n: int | None = None,
        rng: np.random.Generator | int | None = None,
        neutral: bool = False,
    ) -> ScoreSamples:
        """Simulate ``n`` independent games and return the final scores."""

    # -- conveniences ------------------------------------------------------
    def forecast(
        self,
        home: TeamRating | str,
        away: TeamRating | str,
        n: int | None = None,
        rng: np.random.Generator | int | None = None,
        neutral: bool = False,
    ) -> GameForecast:
        samples = self.simulate(as_rating(home), as_rating(away), n=n, rng=rng, neutral=neutral)
        return samples.forecast()

    def win_prob(
        self,
        home: TeamRating | str,
        away: TeamRating | str,
        n: int | None = None,
        rng: np.random.Generator | int | None = None,
        neutral: bool = False,
    ) -> float:
        return self.forecast(home, away, n=n, rng=rng, neutral=neutral).home_win_prob

    def _n(self, n: int | None) -> int:
        return int(self.default_sims if n is None else n)

    def _tag(self, samples: ScoreSamples, home: TeamRating, away: TeamRating) -> ScoreSamples:
        samples.home_team = home.team
        samples.away_team = away.team
        return samples


def scoring_rates(
    home: TeamRating,
    away: TeamRating,
    league_mean: float,
    home_factor: float,
    neutral: bool = False,
) -> tuple[Any, Any]:
    """Expected scoring for each side from multiplicative attack/defence.

    The home effect is split symmetrically (``sqrt`` on each side) so the
    league-wide mean is unchanged by who is hosting.
    """
    hf = 1.0 if neutral else np.sqrt(home_factor)
    home_rate = league_mean * np.asarray(home.attack) * np.asarray(away.defense) * hf
    away_rate = league_mean * np.asarray(away.attack) * np.asarray(home.defense) / hf
    return home_rate, away_rate


def broadcast_rate(rate: Any, n: int) -> np.ndarray:
    """Expand a scalar or length-n rate to a length-n array."""
    arr = np.asarray(rate, dtype=float)
    if arr.ndim == 0:
        return np.full(n, float(arr))
    if arr.size == n:
        return arr.astype(float, copy=False)
    raise ValueError(f"rate array of size {arr.size} cannot be broadcast to {n} simulations")
