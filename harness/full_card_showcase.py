#!/usr/bin/env python3
"""Deterministic SHOWCASE_FULL_CARD completeness gate.

This module does not forecast, price, or select wagers. It binds a canonical schedule to normalized
market rows and refuses to call a board a full card unless every event and required core market is
represented. Forecast/action semantics are delegated to forecast_action_governance.
"""
from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

MODULE_ID = "full_card_showcase"
TIMEZONE = ZoneInfo("America/Los_Angeles")
REQUIRED_MARKETS = {
    "MLB": ("ML", "RL", "TOTAL"),
    "NFL": ("ML", "SPREAD", "TOTAL"),
    "CFB": ("ML", "SPREAD", "TOTAL"),
    "WNBA": ("ML", "SPREAD", "TOTAL"),
    "NBA": ("ML", "SPREAD", "TOTAL"),
}


def resolve_card_date(text: str, now: dt.datetime) -> dt.date:
    """Resolve supported US-style date expressions in America/Los_Angeles."""
    local_now = now.astimezone(TIMEZONE)
    lowered = text.lower()
    if "tomorrow" in lowered:
        return local_now.date() + dt.timedelta(days=1)
    if "today" in lowered:
        return local_now.date()
    m = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?:/(\d{2}|\d{4}))?(?!\d)", text)
    if not m:
        raise ValueError("CARD_DATE_UNRESOLVED")
    month, day = int(m.group(1)), int(m.group(2))
    raw_year = m.group(3)
    year = local_now.year if raw_year is None else int(raw_year)
    if raw_year is not None and len(raw_year) == 2:
        year += 2000
    return dt.date(year, month, day)


def classify_intent(text: str) -> str | None:
    lowered = " ".join(text.lower().split())
    full_patterns = (
        "show me full card", "full card", "show the whole slate", "display every game", "all games"
    )
    if any(p in lowered for p in full_patterns):
        return "SHOWCASE_FULL_CARD"
    if "action card" in lowered or re.search(r"\bplays\b", lowered):
        return "SHOWCASE_ACTION_CARD"
    if "what's missing" in lowered or "what is missing" in lowered:
        return "SHOWCASE_DIAGNOSTICS"
    if "grade" in lowered and "card" in lowered:
        return "SETTLE_FORECAST_CARD"
    return None


def validate_full_card(schedule_events: list[dict], market_rows: list[dict]) -> dict:
    """Return deterministic integrity summary. Does not silently deduplicate or fill missing rows."""
    errors = []
    schedule_ids = [str(e.get("game_id") or e.get("canonical_event_id") or "") for e in schedule_events]
    if any(not x for x in schedule_ids):
        errors.append("SCHEDULE_EVENT_ID_MISSING")
    duplicates = sorted({x for x in schedule_ids if x and schedule_ids.count(x) > 1})
    if duplicates:
        errors.extend(f"DUPLICATE_SCHEDULE_EVENT:{x}" for x in duplicates)

    expected = set()
    for event, game_id in zip(schedule_events, schedule_ids):
        league = str(event.get("league") or event.get("sport") or "").upper()
        required = REQUIRED_MARKETS.get(league)
        if required is None:
            errors.append(f"UNSUPPORTED_LEAGUE:{league}:{game_id}")
            continue
        for market in required:
            expected.add((game_id, market))

    actual_pairs = []
    for row in market_rows:
        game_id = str(row.get("game_id") or row.get("canonical_event_id") or "")
        market = str(row.get("market_type") or "").upper()
        actual_pairs.append((game_id, market))
    actual = set(actual_pairs)
    row_duplicates = sorted({x for x in actual_pairs if actual_pairs.count(x) > 1})
    errors.extend(f"DUPLICATE_MARKET_ROW:{g}:{m}" for g, m in row_duplicates)

    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    errors.extend(f"MISSING_MARKET:{g}:{m}" for g, m in missing)
    errors.extend(f"UNEXPECTED_MARKET:{g}:{m}" for g, m in extra)

    try:
        import forecast_action_governance
        governance_errors = forecast_action_governance.validate_board(market_rows)
    except Exception as exc:
        governance_errors = [f"GOVERNANCE_VALIDATOR_ERROR:{type(exc).__name__}:{exc}"]
    errors.extend(f"GOVERNANCE:{e}" for e in governance_errors)

    return {
        "status": "PASS" if not errors else "CARD_REJECTED",
        "expected_scheduled_events": len(schedule_events),
        "rendered_scheduled_events": len({g for g, _ in actual if g in set(schedule_ids)}),
        "expected_core_market_rows": len(expected),
        "rendered_core_market_rows": len(actual & expected),
        "duplicate_events": len(duplicates),
        "missing_events": sorted(set(schedule_ids) - {g for g, _ in actual}),
        "missing_required_markets": [{"game_id": g, "market_type": m} for g, m in missing],
        "errors": errors,
    }


def selftest():
    now = dt.datetime(2026, 9, 3, 15, 51, tzinfo=TIMEZONE)
    assert classify_intent("Show me full card for 9/3") == "SHOWCASE_FULL_CARD"
    assert resolve_card_date("Show me full card for 9/3", now) == dt.date(2026, 9, 3)
    schedule = [{"game_id": "G1", "league": "MLB"}]
    base = {
        "game_id": "G1", "status": "NO_MODEL", "forecast_registered": False,
        "model_p_raw": None, "sim_p": None, "conservative_p": None, "action_pnl_units": None,
    }
    rows = [{**base, "market_type": m} for m in ("ML", "RL", "TOTAL")]
    result = validate_full_card(schedule, rows)
    assert result["status"] == "PASS", result
    rejected = validate_full_card(schedule, rows[:-1])
    assert rejected["status"] == "CARD_REJECTED"
    assert rejected["missing_required_markets"] == [{"game_id": "G1", "market_type": "TOTAL"}]
    print("full_card_showcase selftest: PASS")


if __name__ == "__main__":
    selftest()
