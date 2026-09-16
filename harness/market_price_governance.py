#!/usr/bin/env python3
"""Price governance: missing/stale/reference prices never erase forecasts or authorize wagers."""
from __future__ import annotations
from datetime import datetime

MODULE_ID = "market_price_governance"

MARKET_STATES = {
    "CAPTURED_FRESH", "CAPTURED_RECHECK_REQUIRED", "CROSS_SOURCE_CONFIRMED",
    "CACHE_FRESH", "STALE_PRICE", "CONSENSUS_ONLY", "NO_PRICE",
    "MARKET_MISMATCH", "SUSPENDED", "POST_START"
}
ACTION_ELIGIBLE = {"CAPTURED_FRESH", "CROSS_SOURCE_CONFIRMED"}
REFERENCE_ONLY = {"CAPTURED_RECHECK_REQUIRED", "CACHE_FRESH", "STALE_PRICE", "CONSENSUS_ONLY"}
FORECAST_FIELDS = (
    "model_lean", "model_p_raw", "sim_p", "conservative_p", "fair_ml",
    "model_margin", "model_total", "grade_selection"
)


def _dt(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def freshness_limit_seconds(minutes_to_start):
    if minutes_to_start is None:
        return None
    if minutes_to_start < 0:
        return 0
    if minutes_to_start < 10:
        return 60
    if minutes_to_start < 30:
        return 120
    if minutes_to_start < 120:
        return 300
    if minutes_to_start < 360:
        return 900
    return 1800


def validate_row(row):
    v = []
    state = row.get("market_state")
    status = row.get("status")
    registered = row.get("forecast_registered") is True

    if state not in MARKET_STATES:
        v.append(f"UNKNOWN_MARKET_STATE:{state}")
        return v

    # Cardinal separation rule: price failure cannot erase an existing forecast.
    if state in {"NO_PRICE", "STALE_PRICE", "CONSENSUS_ONLY", "CACHE_FRESH",
                 "CAPTURED_RECHECK_REQUIRED", "MARKET_MISMATCH", "SUSPENDED"}:
        if registered and status not in {"NO_PRICE", "BLOCKED", "LEAN", "PASS"}:
            v.append("PRICE_DEGRADED_STATUS_CANNOT_AUTHORIZE_PLAY")
        if registered and not any(row.get(k) not in (None, "") for k in FORECAST_FIELDS):
            v.append("NO_PRICE_MUST_NOT_ERASE_FORECAST_FIELDS")

    executable_ev = row.get("executable_ev_per_unit")
    reference_ev = row.get("reference_ev_per_unit")
    wager_authorized = row.get("wager_authorized") is True
    stake = row.get("stake_units")

    if state not in ACTION_ELIGIBLE and executable_ev is not None:
        v.append("NON_EXECUTABLE_MARKET_STATE_CANNOT_HAVE_EXECUTABLE_EV")
    if state in REFERENCE_ONLY and reference_ev is not None and wager_authorized:
        v.append("REFERENCE_EV_CANNOT_AUTHORIZE_WAGER")
    if state not in ACTION_ELIGIBLE and wager_authorized:
        v.append("NON_EXECUTABLE_MARKET_STATE_CANNOT_AUTHORIZE_WAGER")
    if status == "PLAY" and state not in ACTION_ELIGIBLE:
        v.append("PLAY_REQUIRES_ACTION_ELIGIBLE_MARKET_STATE")
    if status == "PLAY" and executable_ev is None:
        v.append("PLAY_REQUIRES_EXECUTABLE_EV")
    if status != "PLAY" and stake not in (None, "", 0, 0.0):
        v.append("NON_PLAY_CANNOT_HAVE_STAKE")

    # Exact execution evidence is mandatory for PLAY.
    if status == "PLAY":
        required = ("event_id", "market_type", "selection_key", "book",
                    "american_odds", "quote_timestamp_utc", "ingested_at_utc", "source_tier")
        for key in required:
            if row.get(key) in (None, ""):
                v.append(f"PLAY_MISSING_{key.upper()}")
        if row.get("execution_verified") is not True:
            v.append("PLAY_REQUIRES_EXECUTION_VERIFIED")

    # Source quote time controls freshness; ingestion time cannot rescue an old quote.
    qt, it, start = _dt(row.get("quote_timestamp_utc")), _dt(row.get("ingested_at_utc")), _dt(row.get("game_start_timestamp_utc"))
    if qt and it and qt > it:
        v.append("QUOTE_TIMESTAMP_AFTER_INGESTION")
    if qt and start and qt >= start and status == "PLAY":
        v.append("POST_START_QUOTE_CANNOT_AUTHORIZE_PREGAME_PLAY")
    if qt and start and state in ACTION_ELIGIBLE:
        mins = (start - qt).total_seconds() / 60.0
        limit = freshness_limit_seconds(mins)
        decision = _dt(row.get("decision_timestamp_utc"))
        if decision and limit is not None:
            age = (decision - qt).total_seconds()
            if age < 0:
                v.append("QUOTE_AFTER_DECISION_TIMESTAMP")
            elif age > limit:
                v.append("ACTION_QUOTE_EXCEEDS_FRESHNESS_SLA")

    # Spread/RL/total number mismatch changes the event; require frozen distribution repricing.
    market_type = str(row.get("market_type") or "").upper()
    if market_type in {"SPREAD", "RL", "RUN_LINE", "TOTAL"}:
        forecast_line, market_line = row.get("forecast_line"), row.get("market_line")
        if forecast_line is not None and market_line is not None and float(forecast_line) != float(market_line):
            if row.get("repriced_from_frozen_distribution") is not True:
                v.append("LINE_MISMATCH_REQUIRES_FROZEN_DISTRIBUTION_REPRICE")

    if row.get("fallback_used") is True:
        for key in ("source_tier", "source_name", "quote_timestamp_utc"):
            if row.get(key) in (None, ""):
                v.append(f"FALLBACK_MISSING_{key.upper()}")

    return v


def validate_board(rows):
    out = []
    for i, row in enumerate(rows):
        for problem in validate_row(row):
            out.append(f"row[{i}]/{row.get('event_id','?')}/{row.get('market_type','?')}:{problem}")
    return out


def selftest():
    forecast = {
        "event_id": "E1", "market_type": "ML", "selection_key": "HOME_ML",
        "forecast_registered": True, "model_lean": "HOME ML", "model_p_raw": .60,
        "sim_p": .58, "conservative_p": .56, "grade_selection": "HOME ML",
        "status": "NO_PRICE", "market_state": "NO_PRICE", "executable_ev_per_unit": None,
        "reference_ev_per_unit": None, "wager_authorized": False, "stake_units": None
    }
    assert validate_row(forecast) == []
    bad = {**forecast, "status": "PLAY", "wager_authorized": True, "stake_units": 1.0}
    assert "PLAY_REQUIRES_ACTION_ELIGIBLE_MARKET_STATE" in validate_row(bad)
    ref = {**forecast, "market_state": "CONSENSUS_ONLY", "reference_ev_per_unit": .03,
           "wager_authorized": True}
    assert "REFERENCE_EV_CANNOT_AUTHORIZE_WAGER" in validate_row(ref)
    mismatch = {**forecast, "market_type": "SPREAD", "market_state": "CAPTURED_RECHECK_REQUIRED",
                "forecast_line": 6.5, "market_line": 5.5}
    assert "LINE_MISMATCH_REQUIRES_FROZEN_DISTRIBUTION_REPRICE" in validate_row(mismatch)
    print("market_price_governance selftest: PASS")


if __name__ == "__main__":
    selftest()
