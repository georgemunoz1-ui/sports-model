"""Shared operational interface for first-class sport forecast adapters.

Adapters own sport-specific PIT acquisition and inference. The card orchestrator
owns chronology, rendering, coverage accounting, and action separation.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

@dataclass(frozen=True)
class AdapterCapabilities:
    moneyline: bool = True
    spread: bool = True
    total: bool = True
    team_points: bool = True

class ForecastAdapter(ABC):
    league: str
    capabilities = AdapterCapabilities()

    @abstractmethod
    def load_schedule(self, card_date: str, as_of_utc: str) -> Sequence[Mapping[str, Any]]:
        """Return canonical events known by the PIT cutoff."""

    @abstractmethod
    def build_context(self, schedule, as_of_utc: str, allow_stale: bool = True, overrides_path: str | None = None) -> Mapping[str, Any]:
        """Freeze PIT features/model state and return immutable inference context."""

    @abstractmethod
    def forecast_event(self, event, context, simulations: int = 100_000) -> Mapping[str, Any]:
        """Return Model P, empirical Sim P, scoring distribution and provenance."""

    def quality_from_missing(self, missing_required: int, missing_optional: int) -> tuple[str, float, list[str]]:
        if missing_required:
            return "EMERGENCY", 0.35, [f"MISSING_REQUIRED_INPUTS:{missing_required}"]
        if missing_optional >= 3:
            return "BASELINE", 0.50, [f"MISSING_OPTIONAL_INPUTS:{missing_optional}"]
        if missing_optional:
            return "REDUCED", 0.75, [f"MISSING_OPTIONAL_INPUTS:{missing_optional}"]
        return "PRIMARY_SHADOW", 1.0, []
