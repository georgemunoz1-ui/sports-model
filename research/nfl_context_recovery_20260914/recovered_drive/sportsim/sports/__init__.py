"""Per-sport game simulators."""

from __future__ import annotations

from .base import GameSimulator, as_rating, resolve_rng
from .mlb import MLBConfig, MLBSimulator
from .nba import NBAConfig, NBASimulator
from .nfl import NFLConfig, NFLSimulator
from .nhl import NHLConfig, NHLSimulator

SIMULATORS: dict[str, type[GameSimulator]] = {
    "nfl": NFLSimulator,
    "nba": NBASimulator,
    "mlb": MLBSimulator,
    "nhl": NHLSimulator,
}


def get_simulator(sport: str, playoff: bool = False, **kwargs) -> GameSimulator:
    """Look up a simulator by sport code (``nfl``, ``nba``, ``mlb``, ``nhl``)."""
    key = sport.lower()
    if key not in SIMULATORS:
        raise KeyError(f"unknown sport {sport!r}; choose from {sorted(SIMULATORS)}")
    return SIMULATORS[key](playoff=playoff, **kwargs)


__all__ = [
    "GameSimulator",
    "MLBConfig",
    "MLBSimulator",
    "NBAConfig",
    "NBASimulator",
    "NFLConfig",
    "NFLSimulator",
    "NHLConfig",
    "NHLSimulator",
    "SIMULATORS",
    "as_rating",
    "get_simulator",
    "resolve_rng",
]

