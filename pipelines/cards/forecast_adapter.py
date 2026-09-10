"""Shared operational interface for first-class sport forecast adapters.

Adapters own sport-specific PIT acquisition and inference. The card orchestrator
owns chronology, rendering, coverage accounting, and action separation.

Repository-wide default: valid-event forecasts are expanded-game-state forecasts.
A league baseline remains mandatory as the fallback/benchmark arm; missing
information may reduce coverage quality but may not silently erase a valid game.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from models.common.expanded_game_state_standard_v1 import (
    STANDARD_ID as EXPANDED_GAME_STATE_STANDARD_ID,
    STANDARD_VERSION as EXPANDED_GAME_STATE_STANDARD_VERSION,
    build_game_state_envelope as _build_game_state_envelope,
    policy_for_league,
)


@dataclass(frozen=True)
class AdapterCapabilities:
    moneyline: bool = True
    spread: bool = True
    total: bool = True
    team_points: bool = True


class ForecastAdapter(ABC):
    league: str
    capabilities = AdapterCapabilities()

    # This is a repository-wide contract, not an opt-in capability flag.
    game_state_standard_id = EXPANDED_GAME_STATE_STANDARD_ID
    game_state_standard_version = EXPANDED_GAME_STATE_STANDARD_VERSION
    primary_forecast_mode = "EXPANDED_GAME_STATE"
    baseline_forecast_required = True
    market_input_permitted = False

    @abstractmethod
    def load_schedule(self, card_date: str, as_of_utc: str) -> Sequence[Mapping[str, Any]]:
        """Return canonical events known by the PIT cutoff."""

    @abstractmethod
    def build_context(self, schedule, as_of_utc: str, allow_stale: bool = True, overrides_path: str | None = None) -> Mapping[str, Any]:
        """Freeze PIT baseline plus sport-specific expanded game state.

        Implementations should attempt every dimension defined by
        expanded_game_state_standard_v1 for this league. A missing enrichment
        dimension must be explicit UNKNOWN/UNAVAILABLE; it must never be invented
        or silently treated as resolved. Baseline team strength is mandatory.
        """

    @abstractmethod
    def forecast_event(self, event, context, simulations: int = 100_000) -> Mapping[str, Any]:
        """Return the current research forecast plus baseline/provenance.

        The preferred/current research opinion uses verified expanded game state
        when a separately versioned impact transform exists. If enrichment is
        unavailable, emit the league baseline and label the missing state rather
        than omitting a valid event. Market data is never a predictive input.
        """

    def game_state_policy(self):
        """Return the mandatory expanded-game-state policy for this adapter."""
        return policy_for_league(self.league)

    def build_game_state_envelope(
        self,
        *,
        event_id: str,
        cutoff_utc: str,
        baseline_model_id: str,
        dimensions: Mapping[str, Any] | None = None,
        impact_transform: Mapping[str, Any] | None = None,
        feature_contributions: Mapping[str, Any] | None = None,
        source_conflict: bool = False,
        event_valid: bool = True,
        market_input_used: bool = False,
        subjective_sentiment_used: bool = False,
        action_authority: bool = False,
    ) -> Mapping[str, Any]:
        """Create the common fail-closed envelope used by every sport adapter."""
        return _build_game_state_envelope(
            league=self.league,
            event_id=event_id,
            cutoff_utc=cutoff_utc,
            baseline_model_id=baseline_model_id,
            dimensions=dimensions,
            impact_transform=impact_transform,
            feature_contributions=feature_contributions,
            source_conflict=source_conflict,
            event_valid=event_valid,
            market_input_used=market_input_used,
            subjective_sentiment_used=subjective_sentiment_used,
            action_authority=action_authority,
        )

    def quality_from_missing(self, missing_required: int, missing_optional: int) -> tuple[str, float, list[str]]:
        """Legacy quality score retained for adapter compatibility.

        Coverage labels from the expanded game-state envelope are authoritative
        for whether a card is FULL_INFORMATION_SHADOW, BASELINE_ONLY, or
        BASELINE_WITH_UNRESOLVED_INPUTS.
        """
        if missing_required:
            return "EMERGENCY", 0.35, [f"MISSING_REQUIRED_INPUTS:{missing_required}"]
        if missing_optional >= 3:
            return "BASELINE", 0.50, [f"MISSING_OPTIONAL_INPUTS:{missing_optional}"]
        if missing_optional:
            return "REDUCED", 0.75, [f"MISSING_OPTIONAL_INPUTS:{missing_optional}"]
        return "PRIMARY_SHADOW", 1.0, []
