"""MoneyLine historical odds API client — STRUCTURED line movement (FU-1 market layer, history leg).

Free tier 1,000 credits/month. Timestamped snapshots, consensus, best price, NO-VIG fair odds,
ML/spread/totals/props; NFL/NBA/MLB/NHL/NCAAF/NCAAB; history begins at provider tracking. Key via
MONEYLINE_API_KEY env var; without a key the client is STUB MODE (loud refusal, fixture only).

Every emitted record carries the owner history schema (harness/market_history.py) with the typed
line_kind preserved: MoneyLine's own snapshot roles map as
  opening -> OPENING, consensus -> CONSENSUS, best price -> BEST_AVAILABLE, circa -> SHARP_BOOK,
  closing -> CLOSING. Never folded into one "historical odds" column.
"""
from __future__ import annotations

MODULE_ID = "market_moneyline"

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market_capture
import market_history

UTC = dt.timezone.utc
ENV_KEY = "MONEYLINE_API_KEY"
API_ROOT = "https://api.moneyline.com/v1"   # provider docs: historical odds + movement endpoints

CREDIT_NOTE = "1000 credits/mo; movement backfill pages by event, not by day, so a slate of 15 " \
              "events costs ~15 credits plus one odds index call"

ROLE_TO_KIND = {"opening": "OPENING", "consensus": "CONSENSUS", "best": "BEST_AVAILABLE",
                "best_price": "BEST_AVAILABLE", "circa": "SHARP_BOOK", "sharp": "SHARP_BOOK",
                "closing": "CLOSING", "close": "CLOSING"}


class StubModeNoKey(RuntimeError):
    """Raised when a live call is attempted without MONEYLINE_API_KEY. Never silent."""


def have_key():
    return bool(os.environ.get(ENV_KEY))


def movement_url(event_id):
    return f"{API_ROOT}/events/{event_id}/odds/history"


def parse_moneyline_payload(payload, event_id, timestamp_captured,
                            source_url="feed://moneyline_api"):
    """MoneyLine movement payload -> owner history-schema records. Pure parse.

    Expected shape: {event: {id, league, starts_at, home, away}, snapshots: [{snapshot_time,
    role: opening|consensus|best|closing|circa, market, outcome, point, american_price,
    sportsbook}]}; unknown roles are SKIPPED WITH A RECORDED PROBLEM, never guessed into a kind.
    Returns (records, skipped).
    """
    records, skipped = [], []
    ev = payload.get("event") or {}
    for snap in payload.get("snapshots") or []:
        kind = ROLE_TO_KIND.get(str(snap.get("role", "")).lower())
        if kind is None:
            skipped.append({"snapshot": snap, "reason": f"unmapped role {snap.get('role')!r}; "
                                                       "skipped, not guessed into a line_kind"})
            continue
        records.append(market_history.make_history_record(
            event_id=ev.get("id", event_id), league=ev.get("league"),
            start_time_utc=ev.get("starts_at"), home_team=ev.get("home"),
            away_team=ev.get("away"), sportsbook=str(snap.get("sportsbook", "")).lower(),
            market_type=snap.get("market"), outcome=snap.get("outcome"),
            point=snap.get("point"), american_price=snap.get("american_price"),
            snapshot_time_utc=snap.get("snapshot_time"), source="moneyline_api",
            line_kind=kind, timestamp_captured=timestamp_captured))
    return records, skipped


def fetch_movement(event_id, get=None):
    if not have_key():
        raise StubModeNoKey(
            f"{ENV_KEY} not set — MoneyLine client is in stub mode. Drive it with a fixture via "
            "parse_moneyline_payload; a stub must never invent prices.")
    if get is None:
        def get(url):
            import requests
            r = requests.get(url, timeout=20,
                             headers={"Authorization": f"Bearer {os.environ[ENV_KEY]}",
                                      "User-Agent": "sports-model-fu1/1.0"})
            r.raise_for_status()
            return r.text
    import json
    captured = dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")
    text = get(movement_url(event_id))
    recs, skipped = parse_moneyline_payload(json.loads(text), event_id, captured)
    return recs, skipped, text, market_capture.snapshot_hash(text)


# ====================================================================== selftest

def selftest():
    f = []
    payload = {"event": {"id": "ML1", "league": "mlb", "starts_at": "2026-08-28T23:10:00Z",
                         "home": "New York Mets", "away": "Houston Astros"},
               "snapshots": [
                   {"snapshot_time": "2026-08-26T12:00:00Z", "role": "opening", "market": "spread",
                    "outcome": "Houston Astros -1.5", "point": -1.5, "american_price": -110,
                    "sportsbook": "consensus"},
                   {"snapshot_time": "2026-08-28T19:00:00Z", "role": "best_price", "market": "spread",
                    "outcome": "Houston Astros -1.5", "point": -1.5, "american_price": -105,
                    "sportsbook": "circa"},
                   {"snapshot_time": "2026-08-28T23:05:00Z", "role": "closing", "market": "spread",
                    "outcome": "Houston Astros -2.5", "point": -2.5, "american_price": -115,
                    "sportsbook": "consensus"},
                   {"snapshot_time": "2026-08-28T20:00:00Z", "role": "mystery", "market": "spread",
                    "outcome": "?", "point": -1.5, "american_price": -110, "sportsbook": "x"}]}
    recs, skipped = parse_moneyline_payload(payload, "ML1", "2026-08-30T00:00:00Z")
    if len(recs) != 3 or len(skipped) != 1:
        f.append(f"parse wrong: {len(recs)} records {len(skipped)} skipped")
    kinds = {r["line_kind"] for r in recs}
    if kinds != {"OPENING", "BEST_AVAILABLE", "CLOSING"}:
        f.append(f"typed kinds lost: {kinds}")
    if any(r["grade"] != "CONFIRMED" for r in recs):
        f.append("structured history records lost the feed grade")
    old = os.environ.pop(ENV_KEY, None)
    try:
        fetch_movement("ML1", get=lambda u: "{}")
        f.append("stub mode fabricated a live fetch")
    except StubModeNoKey:
        pass
    finally:
        if old:
            os.environ[ENV_KEY] = old

    print(f"market_moneyline selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("   -", x)
    return 0 if not f else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__)
