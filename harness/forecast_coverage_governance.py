#!/usr/bin/env python3
"""Fail-closed governance for forecast production coverage.

This module separates forecast-production obligations from market/action authority.
If minimum required inputs are ready for a supported pregame market, a valid frozen
forecast is mandatory. Missing output is an incident, not NO_MODEL.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Tuple

MODULE_ID = "forecast_coverage_governance"
INCIDENT_CODES = {
    "FORECAST_JOB_NOT_RUN", "FORECAST_JOB_FAILED", "FORECAST_ARTIFACT_WRITE_FAILED",
    "FORECAST_ARTIFACT_JOIN_FAILED", "FORECAST_SCHEMA_INVALID",
    "FORECAST_DEADLINE_MISSED", "FORECAST_OUTPUT_MISSING",
}
ALLOWED_NO_MODEL = {
    "REQUIRED_INPUT_ABSENT", "REQUIRED_INPUT_INVALID", "MARKET_UNSUPPORTED_BY_DESIGN",
    "OUTSIDE_DECLARED_COVERAGE", "ADDED_AFTER_CUTOFF_AND_EXCLUDED_BY_POLICY",
    "MANUAL_INTEGRITY_SUSPENSION",
}


def _dt(value: str) -> datetime:
    v = value.replace("Z", "+00:00")
    d = datetime.fromisoformat(v)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _key(row: Mapping[str, Any]) -> Tuple[str, str]:
    return str(row.get("event_id")), str(row.get("market_type"))


def inputs_ready(context: Mapping[str, Any] | None, required_inputs: Iterable[str]) -> bool:
    if not context:
        return False
    missing = set(context.get("missing_required_inputs", []))
    invalid = set(context.get("invalid_required_inputs", []))
    return all(k in context and context.get(k) is not None and k not in missing and k not in invalid
               for k in required_inputs)


def validate_forecast_coverage(schedule_events: List[Mapping[str, Any]],
                               team_context: Mapping[str, Mapping[str, Any]],
                               forecast_rows: List[Mapping[str, Any]],
                               capability_matrix: Mapping[str, Mapping[str, Any]],
                               now_utc: str) -> Dict[str, Any]:
    now = _dt(now_utc)
    forecasts = {_key(r): r for r in forecast_rows}
    incidents: List[Dict[str, Any]] = []
    eligible_rows = valid_rows = 0

    for event in schedule_events:
        event_id = str(event["event_id"])
        league = str(event["league"])
        start = _dt(str(event["start_time_utc"]))
        if start <= now:
            continue
        league_cap = capability_matrix.get(league, {})
        for market in league_cap.get("required_markets", []):
            cap = league_cap.get("markets", {}).get(market, {})
            context = team_context.get(event_id)
            ready = inputs_ready(context, cap.get("required_inputs", league_cap.get("required_inputs", [])))
            row = forecasts.get((event_id, market))

            if not ready:
                if row and row.get("forecast_state") == "NO_MODEL":
                    reasons = set(row.get("reason_codes", []))
                    if not reasons.intersection(ALLOWED_NO_MODEL):
                        incidents.append({"severity": "HIGH", "event_id": event_id,
                                          "market_type": market, "code": "INVALID_NO_MODEL_REASON"})
                continue

            eligible_rows += 1
            if row is None:
                incidents.append({"severity": "CRITICAL", "event_id": event_id,
                                  "market_type": market, "code": "FORECAST_OUTPUT_MISSING",
                                  "message": "Required inputs available but no forecast artifact was produced."})
                continue
            if row.get("forecast_state") == "NO_MODEL":
                incidents.append({"severity": "CRITICAL", "event_id": event_id,
                                  "market_type": market, "code": "FORECAST_OUTPUT_MISSING",
                                  "message": "NO_MODEL is forbidden when minimum required inputs are ready."})
                continue
            required_fields = cap.get("required_model_fields", [])
            absent = [f for f in required_fields if row.get(f) is None]
            if absent:
                incidents.append({"severity": "CRITICAL", "event_id": event_id,
                                  "market_type": market, "code": "FORECAST_SCHEMA_INVALID",
                                  "missing_fields": absent})
                continue
            if _dt(str(row["forecast_timestamp_utc"])) >= start:
                incidents.append({"severity": "CRITICAL", "event_id": event_id,
                                  "market_type": market, "code": "FORECAST_DEADLINE_MISSED"})
                continue
            valid_rows += 1

    coverage = 100.0 if eligible_rows == 0 else 100.0 * valid_rows / eligible_rows
    return {
        "module_id": MODULE_ID,
        "eligible_required_rows": eligible_rows,
        "valid_forecast_rows": valid_rows,
        "forecast_coverage_pct": coverage,
        "incidents": incidents,
        "coverage_pass": not incidents and coverage >= 99.0,
        "card_can_be_called_forecast_ready": not incidents and coverage >= 99.0,
    }


def _selftest() -> None:
    schedule = [{"event_id": "E1", "league": "CFB", "start_time_utc": "2026-09-04T00:00:00Z"}]
    ctx = {"E1": {"ratings": {}, "qb": "QB1"}}
    caps = {"CFB": {"required_markets": ["ML"], "markets": {"ML": {
        "required_inputs": ["ratings", "qb"], "required_model_fields": ["model_p_raw", "selection"]}}}}
    failed = validate_forecast_coverage(schedule, ctx, [], caps, "2026-09-03T18:00:00Z")
    assert failed["incidents"][0]["code"] == "FORECAST_OUTPUT_MISSING"
    rows = [{"event_id": "E1", "market_type": "ML", "forecast_state": "REGISTERED",
             "model_p_raw": 0.61, "selection": "HOME", "forecast_timestamp_utc": "2026-09-03T18:01:00Z"}]
    passed = validate_forecast_coverage(schedule, ctx, rows, caps, "2026-09-03T18:00:00Z")
    assert passed["coverage_pass"] is True


if __name__ == "__main__":
    _selftest()
    print("forecast_coverage_governance selftest: PASS")
