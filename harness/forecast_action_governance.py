#!/usr/bin/env python3
"""Hard governance validator: forecasts survive wager-status decisions.

This module is intentionally sport-agnostic. It validates normalized market rows before a board is
released or later graded. PLAY/LEAN/PASS/BLOCKED/NO_PRICE describe capital authorization; they do
not erase a legitimate forecast. NO_MODEL is the fail-closed state when no legitimate forecast
artifact exists. POST_START cannot create a new prospective prediction.
"""
from __future__ import annotations

MODULE_ID = "forecast_action_governance"

ALLOWED = {"PLAY", "LEAN", "PASS", "BLOCKED", "NO_PRICE", "NO_MODEL", "POST_START"}
FORECAST_STATUSES = {"PLAY", "LEAN", "PASS", "BLOCKED", "NO_PRICE"}
NO_FORECAST_STATUSES = {"NO_MODEL", "POST_START"}
PROBABILITY_FIELDS = ("model_p_raw", "sim_p", "conservative_p")


def divergence(model_p, sim_p):
    if model_p is None or sim_p is None:
        return "UNAVAILABLE"
    gap = abs(float(model_p) - float(sim_p)) * 100.0
    if gap >= 12.0:
        return "CRITICAL"
    if gap >= 8.0:
        return "SEVERE"
    if gap >= 4.0:
        return "MODERATE"
    return "NONE"


def validate_row(row):
    """Return violations for one normalized market row."""
    v = []
    status = row.get("status")
    if status not in ALLOWED:
        return [f"UNKNOWN_STATUS:{status}"]

    registered = row.get("forecast_registered")
    if status in FORECAST_STATUSES:
        if registered is not True:
            v.append("FORECAST_MUST_BE_REGISTERED")
        if not row.get("grade_selection"):
            v.append("GRADE_SELECTION_REQUIRED")
        if not row.get("model_lean"):
            v.append("MODEL_LEAN_REQUIRED")
        if not row.get("evidence_snapshot_id"):
            v.append("EVIDENCE_SNAPSHOT_REQUIRED")
        if not row.get("decision_timestamp_pt") or not row.get("game_start_timestamp_pt"):
            v.append("PREGAME_TIMESTAMPS_REQUIRED")

    if status == "NO_MODEL":
        if registered not in (False, None):
            v.append("NO_MODEL_CANNOT_REGISTER_FORECAST")
        for key in PROBABILITY_FIELDS:
            if row.get(key) is not None:
                v.append(f"NO_MODEL_CANNOT_HAVE_{key.upper()}")
        if row.get("grade_selection"):
            v.append("NO_MODEL_CANNOT_HAVE_GRADE_SELECTION")

    if status == "POST_START":
        if registered not in (False, None):
            v.append("POST_START_CANNOT_REGISTER_NEW_FORECAST")
        if row.get("grade_selection") and not row.get("preexisting_forecast_id"):
            v.append("POST_START_CANNOT_CREATE_RETROACTIVE_SELECTION")

    if status != "PLAY" and row.get("action_pnl_units") not in (None, ""):
        v.append("NON_PLAY_CANNOT_HAVE_ACTION_PNL")

    expected_divergence = divergence(row.get("model_p_raw"), row.get("sim_p"))
    supplied = row.get("divergence_flag")
    if supplied not in (None, "", expected_divergence):
        v.append(f"DIVERGENCE_FLAG_MISMATCH:{supplied}!={expected_divergence}")
    if expected_divergence in {"SEVERE", "CRITICAL"} and status == "PLAY":
        v.append("SEVERE_MODEL_SIM_DIVERGENCE_BLOCKS_PLAY")

    return v


def validate_board(rows):
    violations = []
    for i, row in enumerate(rows):
        for problem in validate_row(row):
            violations.append(f"row[{i}]/{row.get('game_id','?')}/{row.get('market_type','?')}:{problem}")
    return violations


def selftest():
    base = {
        "game_id": "G1", "market_type": "ML", "decision_timestamp_pt": "2026-09-03T12:00:00-07:00",
        "game_start_timestamp_pt": "2026-09-03T17:00:00-07:00", "model_p_raw": .60, "sim_p": .58,
        "conservative_p": .56, "model_lean": "HOME ML", "grade_selection": "HOME ML",
        "evidence_snapshot_id": "E1", "forecast_registered": True, "action_pnl_units": None,
        "divergence_flag": "NONE"
    }
    for status in ("LEAN", "PASS", "BLOCKED", "NO_PRICE"):
        assert validate_row({**base, "status": status}) == []
    assert "FORECAST_MUST_BE_REGISTERED" in validate_row({**base, "status": "PASS", "forecast_registered": False})
    assert "NO_MODEL_CANNOT_HAVE_MODEL_P_RAW" in validate_row({
        "status": "NO_MODEL", "forecast_registered": False, "model_p_raw": .55, "sim_p": None,
        "conservative_p": None, "action_pnl_units": None})
    severe = {**base, "status": "PLAY", "model_p_raw": .68, "sim_p": .57, "divergence_flag": "SEVERE"}
    assert "SEVERE_MODEL_SIM_DIVERGENCE_BLOCKS_PLAY" in validate_row(severe)
    print("forecast_action_governance selftest: PASS")


if __name__ == "__main__":
    selftest()
