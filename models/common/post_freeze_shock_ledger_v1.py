"""Post-freeze realized-state shock ledger contract.

This module separates official prospective forecast grading from postgame
realized-state diagnostics. A post-kickoff shock may explain context, but it may
never mutate, replace, excuse, or rescore the frozen pregame forecast.

Classification precedes valuation. Numeric player-value deltas remain unavailable
until a separately versioned player-value subsystem establishes them. Even then,
any counterfactual is research-only and cannot rewrite official Brier, log-loss,
margin, total, team-point, calibration, or promotion evidence.
"""
from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Mapping

SCHEMA_VERSION = "post_freeze_shock_ledger.v1"
STANDARD_ID = "post_freeze_realized_state.v1"
STANDARD_VERSION = "1.0.0"

SHOCK_TYPES = frozenset({
    "STARTING_QB_INJURY",
    "STARTING_GOALIE_INJURY",
    "STARTER_INJURY",
    "POSITION_GROUP_INJURY_CLUSTER",
    "EJECTION",
    "WEATHER_REGIME_CHANGE",
    "OTHER_MATERIAL_POST_FREEZE_STATE_CHANGE",
})

SEVERITIES = frozenset({"LOW", "MEDIUM", "HIGH", "UNKNOWN"})
VALUE_DELTA_STATUSES = frozenset({
    "NOT_ESTABLISHED",
    "UNVALIDATED_RESEARCH_ESTIMATE",
    "VALIDATED_RESEARCH_ESTIMATE",
})
COUNTERFACTUAL_STATUSES = frozenset({"DISABLED", "RESEARCH_ONLY"})
CLEAN_CONTEXT_STATES = frozenset({"CLEAN", "FLAGGED"})


def _finite_number(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"INVALID_NUMERIC_FIELD:{field}") from exc
    if not math.isfinite(out):
        raise ValueError(f"NONFINITE_NUMERIC_FIELD:{field}")
    return out


def _probability(value: Any, field: str) -> float:
    out = _finite_number(value, field)
    if not 0.0 <= out <= 1.0:
        raise ValueError(f"PROBABILITY_OUT_OF_BOUNDS:{field}")
    return out


def compute_official_grade(*, forecast_home_win_probability: float, forecast_home_margin: float,
                           forecast_total: float, observed_home_score: int,
                           observed_away_score: int) -> dict[str, Any]:
    """Grade the frozen forecast against the observed outcome without shock adjustment."""
    p = _probability(forecast_home_win_probability, "forecast_home_win_probability")
    margin = _finite_number(forecast_home_margin, "forecast_home_margin")
    total = _finite_number(forecast_total, "forecast_total")
    home_score = int(observed_home_score)
    away_score = int(observed_away_score)
    if home_score == away_score:
        raise ValueError("TIED_FINAL_UNSUPPORTED_BY_BINARY_WIN_GRADE")

    y = 1.0 if home_score > away_score else 0.0
    actual_margin = float(home_score - away_score)
    actual_total = float(home_score + away_score)
    selected_probability = p if y == 1.0 else 1.0 - p
    if selected_probability <= 0.0:
        log_loss = math.inf
    else:
        log_loss = -math.log(selected_probability)

    return {
        "home_won": bool(y),
        "brier": (p - y) ** 2,
        "log_loss": log_loss,
        "actual_home_margin": actual_margin,
        "actual_total": actual_total,
        "margin_absolute_error": abs(actual_margin - margin),
        "total_absolute_error": abs(actual_total - total),
        "official_grade_unchanged": True,
        "shock_adjustment_applied": False,
    }


def _validate_value_delta(value_delta: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(value_delta or {})
    status = str(raw.get("status", "NOT_ESTABLISHED")).upper()
    if status not in VALUE_DELTA_STATUSES:
        raise ValueError(f"INVALID_VALUE_DELTA_STATUS:{status}")

    out = {
        "status": status,
        "method": raw.get("method", "UNVALIDATED_RESEARCH_ESTIMATE"),
        "metric": raw.get("metric", "EXPECTED_OFFENSIVE_POINTS_PER_FULL_GAME"),
        "outgoing_value": raw.get("outgoing_value"),
        "incoming_value": raw.get("incoming_value"),
        "incoming_minus_outgoing": raw.get("incoming_minus_outgoing"),
        "posterior_interval_50": raw.get("posterior_interval_50"),
        "posterior_interval_90": raw.get("posterior_interval_90"),
        "model_confidence": raw.get("model_confidence"),
        "source_model_id": raw.get("source_model_id"),
        "source_model_version": raw.get("source_model_version"),
        "eligible_for_pregame_adjustment": False,
        "eligible_for_official_rescoring": False,
        "eligible_for_model_promotion": False,
    }

    numeric_fields = ("outgoing_value", "incoming_value", "incoming_minus_outgoing")
    interval_fields = ("posterior_interval_50", "posterior_interval_90")

    if status == "NOT_ESTABLISHED":
        if any(out[name] is not None for name in numeric_fields + interval_fields):
            raise ValueError("VALUE_DELTA_NOT_ESTABLISHED_MUST_NOT_CONTAIN_ESTIMATES")
        if out["source_model_id"] is not None or out["source_model_version"] is not None:
            raise ValueError("VALUE_DELTA_NOT_ESTABLISHED_MUST_NOT_CLAIM_SOURCE_MODEL")
        return out

    if not out["source_model_id"] or not out["source_model_version"]:
        raise ValueError("VALUE_DELTA_ESTIMATE_REQUIRES_VERSIONED_SOURCE_MODEL")
    for name in numeric_fields:
        if out[name] is None:
            raise ValueError(f"VALUE_DELTA_ESTIMATE_MISSING:{name}")
        out[name] = _finite_number(out[name], name)
    for name in interval_fields:
        interval = out[name]
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            raise ValueError(f"VALUE_DELTA_INTERVAL_INVALID:{name}")
        lo = _finite_number(interval[0], f"{name}.lower")
        hi = _finite_number(interval[1], f"{name}.upper")
        if lo > hi:
            raise ValueError(f"VALUE_DELTA_INTERVAL_REVERSED:{name}")
        out[name] = [lo, hi]

    return out


def build_shock_record(*, shock_id: str, event_id: str, forecast_identity: Mapping[str, Any],
                       pregame_state: Mapping[str, Any], observed_final: Mapping[str, Any],
                       realized_state: Mapping[str, Any], value_delta: Mapping[str, Any] | None = None,
                       evidence: list[Mapping[str, Any]] | None = None,
                       counterfactual_status: str = "DISABLED") -> dict[str, Any]:
    """Build a fail-closed two-layer post-freeze shock record."""
    if not shock_id or not event_id:
        raise ValueError("SHOCK_AND_EVENT_ID_REQUIRED")

    identity = dict(forecast_identity)
    for field in ("forecast_output_hash", "registered_at_utc", "scheduled_start_utc", "model_id", "model_version"):
        if not identity.get(field):
            raise ValueError(f"FORECAST_IDENTITY_REQUIRED:{field}")

    pre = dict(pregame_state)
    for field in ("team_id", "expected_player_id", "expected_player_role",
                  "forecast_home_win_probability", "forecast_home_margin", "forecast_total"):
        if field not in pre:
            raise ValueError(f"PREGAME_STATE_REQUIRED:{field}")
    _probability(pre["forecast_home_win_probability"], "forecast_home_win_probability")
    _finite_number(pre["forecast_home_margin"], "forecast_home_margin")
    _finite_number(pre["forecast_total"], "forecast_total")

    final = dict(observed_final)
    for field in ("home_score", "away_score"):
        if field not in final:
            raise ValueError(f"OBSERVED_FINAL_REQUIRED:{field}")
    grade = compute_official_grade(
        forecast_home_win_probability=pre["forecast_home_win_probability"],
        forecast_home_margin=pre["forecast_home_margin"],
        forecast_total=pre["forecast_total"],
        observed_home_score=final["home_score"],
        observed_away_score=final["away_score"],
    )

    realized = dict(realized_state)
    shock_type = str(realized.get("shock_type", "")).upper()
    if shock_type not in SHOCK_TYPES:
        raise ValueError(f"INVALID_SHOCK_TYPE:{shock_type or 'MISSING'}")
    if realized.get("occurred_after_kickoff") is not True:
        raise ValueError("POST_FREEZE_SHOCK_MUST_OCCUR_AFTER_KICKOFF")
    severity = str(realized.get("severity", "UNKNOWN")).upper()
    if severity not in SEVERITIES:
        raise ValueError(f"INVALID_SHOCK_SEVERITY:{severity}")
    realized["shock_type"] = shock_type
    realized["severity"] = severity

    delta = _validate_value_delta(value_delta)
    cf_status = str(counterfactual_status).upper()
    if cf_status not in COUNTERFACTUAL_STATUSES:
        raise ValueError(f"INVALID_COUNTERFACTUAL_STATUS:{cf_status}")
    if cf_status == "RESEARCH_ONLY" and delta["status"] != "VALIDATED_RESEARCH_ESTIMATE":
        raise ValueError("COUNTERFACTUAL_REQUIRES_VALIDATED_RESEARCH_VALUE_MODEL")

    clean_context = "FLAGGED"
    record = {
        "schema_version": SCHEMA_VERSION,
        "standard_id": STANDARD_ID,
        "standard_version": STANDARD_VERSION,
        "shock_id": str(shock_id),
        "event_id": str(event_id),
        "layer_1_official_prospective_grade": {
            "forecast_identity": identity,
            "pregame_state": deepcopy(pre),
            "observed_final": final,
            "official_grade": grade,
            "counterfactual_qb_replacement_applied": False,
            "primary_scores_retained": True,
        },
        "layer_2_realized_state_diagnostic": {
            "realized_state": realized,
            "value_delta": delta,
            "clean_context_slice": clean_context,
            "causal_attribution_status": "NOT_ESTABLISHED",
            "counterfactual_status": cf_status,
            "counterfactual_analysis_allowed": cf_status == "RESEARCH_ONLY",
            "counterfactual_rescoring_of_official_grade": False,
            "realized_player_output_usage": "DESCRIPTIVE_ONLY",
            "player_value_update_from_single_game": "DEFERRED_TO_PREDECLARED_PLAYER_VALUE_MODEL",
        },
        "evidence": [dict(item) for item in (evidence or [])],
        "governance": {
            "official_pregame_forecast_immutable": True,
            "official_grade_unchanged": True,
            "postgame_shock_is_explanatory_context_only": True,
            "causal_claim_permitted": False,
            "market_input_used": False,
            "action_authority": False,
        },
    }
    return record


def validate_shock_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild an existing record through the same fail-closed contract."""
    layer1 = dict(record.get("layer_1_official_prospective_grade") or {})
    layer2 = dict(record.get("layer_2_realized_state_diagnostic") or {})
    rebuilt = build_shock_record(
        shock_id=str(record.get("shock_id", "")),
        event_id=str(record.get("event_id", "")),
        forecast_identity=layer1.get("forecast_identity") or {},
        pregame_state=layer1.get("pregame_state") or {},
        observed_final=layer1.get("observed_final") or {},
        realized_state=layer2.get("realized_state") or {},
        value_delta=layer2.get("value_delta") or {},
        evidence=list(record.get("evidence") or []),
        counterfactual_status=str(layer2.get("counterfactual_status", "DISABLED")),
    )
    if rebuilt["layer_1_official_prospective_grade"]["official_grade"] != layer1.get("official_grade"):
        raise ValueError("OFFICIAL_GRADE_MUTATION_OR_MISMATCH")
    return rebuilt
