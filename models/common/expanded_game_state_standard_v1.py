"""Repository-wide expanded game-state forecast standard.

The baseline team-strength model remains a required fallback/benchmark arm. The
primary current research card must attempt to bind sport-specific pregame state
before inference. Missing enrichment is explicit UNKNOWN/UNAVAILABLE and may not
be silently replaced with invented values. Sportsbook/market data is forbidden
from this predictive context.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

STANDARD_ID = "expanded_game_state.v1"
STANDARD_VERSION = "1.0.0"

DIMENSION_STATES = frozenset({"RESOLVED", "PARTIAL", "UNKNOWN", "UNAVAILABLE", "NOT_APPLICABLE"})

LEAGUE_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "MLB": (
        "team_strength", "starter", "lineup", "bullpen", "schedule_load", "environment"
    ),
    "NFL": (
        "team_strength", "quarterback", "availability", "practice", "position_group_health",
        "workload", "schedule_load", "environment"
    ),
    "CFB": (
        "team_strength", "quarterback", "availability", "depth_chart", "position_group_health",
        "schedule_load", "environment"
    ),
    "NBA": (
        "team_strength", "availability", "starting_lineup", "minutes_workload", "schedule_load",
        "travel", "venue"
    ),
    "WNBA": (
        "team_strength", "availability", "starting_lineup", "minutes_workload", "schedule_load",
        "travel", "venue"
    ),
    "NHL": (
        "team_strength", "goaltender", "availability", "line_combinations", "schedule_load",
        "travel", "venue"
    ),
    "MLS": (
        "team_strength", "starting_xi", "goalkeeper", "availability", "fixture_load", "travel",
        "environment"
    ),
}

BASELINE_REQUIRED_DIMENSION = "team_strength"
ENRICHMENT_STATUSES = frozenset({"SHADOW_UNVALIDATED", "SHADOW_VALIDATED", "PRODUCTION_VALIDATED"})
COVERAGE_LABELS = frozenset({
    "FULL_INFORMATION_SHADOW",
    "BASELINE_ONLY",
    "BASELINE_WITH_UNRESOLVED_INPUTS",
    "SOURCE_CONFLICT_BASELINE",
    "INVALID_EVENT",
})


@dataclass(frozen=True)
class GameStatePolicy:
    league: str
    dimensions: tuple[str, ...]
    baseline_required: bool = True
    market_input_forbidden: bool = True
    subjective_sentiment_forbidden: bool = True
    missing_information_behavior: str = "EXPLICIT_UNKNOWN_ZERO_ADJUSTMENT"
    baseline_fallback_behavior: str = "EMIT_BASELINE_DO_NOT_OMIT_VALID_EVENT"
    action_authority_default: bool = False


def policy_for_league(league: str) -> GameStatePolicy:
    key = str(league).upper()
    if key not in LEAGUE_DIMENSIONS:
        raise ValueError(f"UNSUPPORTED_LEAGUE:{key}")
    return GameStatePolicy(league=key, dimensions=LEAGUE_DIMENSIONS[key])


def required_dimensions(league: str) -> tuple[str, ...]:
    return policy_for_league(league).dimensions


def _state(value: Any) -> str:
    if isinstance(value, str):
        state = value.upper()
    elif isinstance(value, Mapping):
        state = str(value.get("status", "UNKNOWN")).upper()
    elif value is None:
        state = "UNKNOWN"
    else:
        raise ValueError("GAME_STATE_DIMENSION_MUST_BE_STRING_MAPPING_OR_NULL")
    if state not in DIMENSION_STATES:
        raise ValueError(f"INVALID_GAME_STATE_DIMENSION_STATUS:{state}")
    return state


def _nonzero_contributions(feature_contributions: Mapping[str, Any] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, raw in (feature_contributions or {}).items():
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"INVALID_FEATURE_CONTRIBUTION:{key}") from exc
        if value != 0.0:
            out[str(key)] = value
    return out


def build_game_state_envelope(
    *,
    league: str,
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
) -> dict[str, Any]:
    """Normalize and validate an expanded game-state envelope.

    This function deliberately does not invent league-specific impact values. It
    establishes the common contract surrounding any separately versioned impact
    transform. A valid event with unresolved enrichment still receives a baseline
    forecast; only invalid authoritative event identity may suppress a forecast.
    """
    policy = policy_for_league(league)
    if market_input_used:
        raise ValueError("MARKET_INPUT_FORBIDDEN")
    if subjective_sentiment_used:
        raise ValueError("SUBJECTIVE_SENTIMENT_PREDICTIVE_INPUT_FORBIDDEN")
    if action_authority:
        raise ValueError("ACTION_AUTHORITY_NOT_GRANTED_BY_GAME_STATE_STANDARD")
    if not event_id:
        raise ValueError("EVENT_ID_REQUIRED")
    if not cutoff_utc:
        raise ValueError("PIT_CUTOFF_REQUIRED")
    if not baseline_model_id:
        raise ValueError("BASELINE_MODEL_ID_REQUIRED")

    supplied = dict(dimensions or {})
    unknown_keys = sorted(set(supplied) - set(policy.dimensions))
    if unknown_keys:
        raise ValueError(f"UNKNOWN_GAME_STATE_DIMENSIONS:{','.join(unknown_keys)}")

    normalized: dict[str, dict[str, Any]] = {}
    for name in policy.dimensions:
        raw = supplied.get(name)
        state = _state(raw)
        if isinstance(raw, Mapping):
            normalized[name] = {**dict(raw), "status": state}
        else:
            normalized[name] = {"status": state}

    if not event_valid:
        coverage = "INVALID_EVENT"
    else:
        if normalized[BASELINE_REQUIRED_DIMENSION]["status"] not in {"RESOLVED", "PARTIAL"}:
            raise ValueError("BASELINE_TEAM_STRENGTH_UNAVAILABLE")
        enrichment = [normalized[d]["status"] for d in policy.dimensions if d != BASELINE_REQUIRED_DIMENSION]
        resolved = sum(s in {"RESOLVED", "NOT_APPLICABLE"} for s in enrichment)
        unresolved = sum(s in {"PARTIAL", "UNKNOWN", "UNAVAILABLE"} for s in enrichment)
        if source_conflict:
            coverage = "SOURCE_CONFLICT_BASELINE"
        elif resolved == 0:
            coverage = "BASELINE_ONLY"
        elif unresolved:
            coverage = "BASELINE_WITH_UNRESOLVED_INPUTS"
        else:
            coverage = "FULL_INFORMATION_SHADOW"

    nonzero = _nonzero_contributions(feature_contributions)
    transform = dict(impact_transform or {})
    if nonzero:
        for key in ("id", "version", "status"):
            if not transform.get(key):
                raise ValueError(f"IMPACT_TRANSFORM_{key.upper()}_REQUIRED_FOR_NONZERO_ADJUSTMENT")
        if str(transform["status"]).upper() not in ENRICHMENT_STATUSES:
            raise ValueError(f"INVALID_IMPACT_TRANSFORM_STATUS:{transform['status']}")

    return {
        "schema_version": "expanded_game_state_envelope.v1",
        "standard_id": STANDARD_ID,
        "standard_version": STANDARD_VERSION,
        "league": policy.league,
        "event_id": str(event_id),
        "cutoff_utc": str(cutoff_utc),
        "baseline_model_id": str(baseline_model_id),
        "baseline_forecast_required": True,
        "primary_research_forecast_policy": "EXPANDED_GAME_STATE_WHEN_VERIFIED_CONTEXT_AVAILABLE",
        "dimensions": normalized,
        "coverage_label": coverage,
        "information_enhancement_available": any(
            normalized[d]["status"] in {"RESOLVED", "PARTIAL"}
            for d in policy.dimensions if d != BASELINE_REQUIRED_DIMENSION
        ),
        "impact_transform": transform or {"id": None, "version": None, "status": "DISABLED"},
        "feature_contributions": dict(feature_contributions or {}),
        "source_conflict": bool(source_conflict),
        "market_input_used": False,
        "subjective_sentiment_used": False,
        "missing_information_behavior": policy.missing_information_behavior,
        "baseline_fallback_behavior": policy.baseline_fallback_behavior,
        "action_authority": False,
    }


def validate_game_state_envelope(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild an envelope through the same fail-closed validator."""
    return build_game_state_envelope(
        league=str(envelope.get("league", "")),
        event_id=str(envelope.get("event_id", "")),
        cutoff_utc=str(envelope.get("cutoff_utc", "")),
        baseline_model_id=str(envelope.get("baseline_model_id", "")),
        dimensions=envelope.get("dimensions") or {},
        impact_transform=envelope.get("impact_transform") or {},
        feature_contributions=envelope.get("feature_contributions") or {},
        source_conflict=bool(envelope.get("source_conflict", False)),
        event_valid=envelope.get("coverage_label") != "INVALID_EVENT",
        market_input_used=bool(envelope.get("market_input_used", False)),
        subjective_sentiment_used=bool(envelope.get("subjective_sentiment_used", False)),
        action_authority=bool(envelope.get("action_authority", False)),
    )
