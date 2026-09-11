"""Pregame confidence-calibration governance contract.

This module does not rewrite model means or historical forecasts. It evaluates whether
reported confidence is supported by the pregame input state. The first named rule is
NFL-specific and targets early-season forecasts built from prior-season ratings while
current-state information was captured but not applied and a known disruption existed.

The numeric support-dose cap is a preregistered, unvalidated governance cap. It is NOT
a probability multiplier, margin adjustment, or causal estimate. Exact variance-widening
magnitude remains NOT_ESTABLISHED until separately estimated and validated.
"""
from __future__ import annotations

from typing import Any, Mapping

STANDARD_ID = "pregame_confidence_calibration.v1"
STANDARD_VERSION = "1.0.0"
RULE_ID = "early_season_input_quality_gate.v1"

RATING_FRESHNESS = frozenset({"CURRENT_SEASON", "MIXED_CURRENT_AND_PRIOR", "PRIOR_SEASON_ONLY", "UNKNOWN"})
CURRENT_STATE_APPLICATION = frozenset({"APPLIED", "CAPTURED_NOT_APPLIED", "NOT_CAPTURED", "UNKNOWN"})
CURRENT_FORM_STATE = frozenset({"AVAILABLE", "PARTIAL", "UNAVAILABLE", "UNKNOWN"})
FORECAST_TIERS = frozenset({"STANDARD", "REDUCED"})


def _enum(value: Any, allowed: frozenset[str], name: str) -> str:
    normalized = str(value).upper()
    if normalized not in allowed:
        raise ValueError(f"INVALID_{name}:{normalized}")
    return normalized


def evaluate_pregame_confidence(
    *,
    league: str,
    event_id: str,
    season_week: int,
    rating_freshness: str,
    current_state_application: str,
    known_disruption: bool,
    current_season_form_state: str = "UNKNOWN",
    action_authority: bool = False,
) -> dict[str, Any]:
    """Return a fail-closed confidence-support classification.

    The rule changes confidence support/uncertainty labeling only. It does not alter the
    baseline mean, win probability, spread, total, or official grade. A future model may
    consume this record to widen a predictive distribution only after a separately
    versioned mapping from support state to variance has been preregistered and validated.
    """
    if action_authority:
        raise ValueError("ACTION_AUTHORITY_NOT_GRANTED_BY_CONFIDENCE_STANDARD")
    if not event_id:
        raise ValueError("EVENT_ID_REQUIRED")
    try:
        week = int(season_week)
    except (TypeError, ValueError) as exc:
        raise ValueError("SEASON_WEEK_MUST_BE_INTEGER") from exc
    if week < 1:
        raise ValueError("SEASON_WEEK_MUST_BE_POSITIVE")

    league_key = str(league).upper()
    freshness = _enum(rating_freshness, RATING_FRESHNESS, "RATING_FRESHNESS")
    application = _enum(current_state_application, CURRENT_STATE_APPLICATION, "CURRENT_STATE_APPLICATION")
    form_state = _enum(current_season_form_state, CURRENT_FORM_STATE, "CURRENT_SEASON_FORM_STATE")

    trigger = (
        league_key == "NFL"
        and week <= 2
        and freshness == "PRIOR_SEASON_ONLY"
        and application == "CAPTURED_NOT_APPLIED"
        and bool(known_disruption)
    )

    limitations = []
    if freshness == "PRIOR_SEASON_ONLY":
        limitations.append("prior_season_ratings_only")
    if application == "CAPTURED_NOT_APPLIED":
        limitations.append("current_state_info_captured_not_applied")
    if bool(known_disruption):
        limitations.append("known_disruption")
    if form_state in {"UNAVAILABLE", "UNKNOWN"}:
        limitations.append("current_season_form_unavailable")

    if trigger:
        forecast_tier = "REDUCED"
        support_dose_cap = 0.6
        uncertainty_policy = "WIDEN_REQUIRED_EXACT_SCALE_NOT_ESTABLISHED"
        rationale = "Confidence exceeds input support"
    else:
        forecast_tier = "STANDARD"
        support_dose_cap = 1.0
        uncertainty_policy = "STANDARD_UNLESS_OTHER_RULE_REDUCES"
        rationale = "Named early-season input-quality gate not triggered"

    return {
        "schema_version": "pregame_confidence_calibration_record.v1",
        "standard_id": STANDARD_ID,
        "standard_version": STANDARD_VERSION,
        "rule_id": RULE_ID,
        "league": league_key,
        "event_id": str(event_id),
        "season_week": week,
        "inputs": {
            "rating_freshness": freshness,
            "current_state_application": application,
            "known_disruption": bool(known_disruption),
            "current_season_form_state": form_state,
        },
        "rule_triggered": trigger,
        "forecast_tier": forecast_tier,
        "confidence_support_dose_cap": support_dose_cap,
        "confidence_support_dose_status": (
            "PREREGISTERED_UNVALIDATED_GOVERNANCE_CAP" if trigger else "NOT_REDUCED_BY_THIS_RULE"
        ),
        "uncertainty_policy": uncertainty_policy,
        "uncertainty_scale_numeric": None,
        "probability_rescaling_permitted": False,
        "mean_forecast_adjustment_permitted": False,
        "historical_forecast_rewrite_permitted": False,
        "causal_attribution": "NOT_CLAIMED",
        "hindsight_outcome_used_by_rule": False,
        "known_limitations": limitations,
        "rationale": rationale,
        "implementation_target": "nfl.elo_margin_monte_carlo.v1.1",
        "action_authority": False,
    }


def validate_confidence_record(record: Mapping[str, Any]) -> dict[str, Any]:
    rebuilt = evaluate_pregame_confidence(
        league=record.get("league", ""),
        event_id=record.get("event_id", ""),
        season_week=record.get("season_week"),
        rating_freshness=(record.get("inputs") or {}).get("rating_freshness", "UNKNOWN"),
        current_state_application=(record.get("inputs") or {}).get("current_state_application", "UNKNOWN"),
        known_disruption=bool((record.get("inputs") or {}).get("known_disruption", False)),
        current_season_form_state=(record.get("inputs") or {}).get("current_season_form_state", "UNKNOWN"),
        action_authority=bool(record.get("action_authority", False)),
    )
    protected = (
        "rule_triggered", "forecast_tier", "confidence_support_dose_cap",
        "uncertainty_policy", "uncertainty_scale_numeric", "probability_rescaling_permitted",
        "mean_forecast_adjustment_permitted", "historical_forecast_rewrite_permitted",
        "causal_attribution", "hindsight_outcome_used_by_rule", "action_authority",
    )
    for key in protected:
        if record.get(key) != rebuilt.get(key):
            raise ValueError(f"CONFIDENCE_RECORD_MISMATCH:{key}")
    return rebuilt
