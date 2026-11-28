"""SportsGameOdds client — PRIMARY structured odds feed (FU-1 market layer).

Free tier: 2,500 objects/month, 10 req/min. Normalized JSON: scores, settlements, fair odds,
consensus, spreads/totals/moneylines across 9 bookmakers and 8 leagues. The API key drops in via
the SPORTSGAMEODDS_API_KEY env var. With NO key the client runs in STUB MODE: it refuses network
calls loudly and must be driven by a fixture (parse_sgo_payload). A stub that silently fabricates
prices would be the 8/8 incident reborn; stub mode returns no records unless given a payload.

Grade: structured feed responses carry GRADE=CONFIRMED — the feed is the source of record for its
own quotes. This is a statement about a market price only (VALUATION_ONLY namespace); it says
nothing about any forecast input, and no forecast module may import this module (market_capture
firewall).
"""
from __future__ import annotations

MODULE_ID = "market_sportsgameodds"

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market_capture

UTC = dt.timezone.utc
ENV_KEY = "SPORTSGAMEODDS_API_KEY"
API_ROOT = "https://api.sportsgameodds.com/v2"

RATE_LIMIT_NOTE = "free tier: 10 req/min, 2500 objects/mo — the sweep caches snapshots so a " \
                  "re-run costs no objects (content-hash dedup)"


class StubModeNoKey(RuntimeError):
    """Raised when a live call is attempted without SPORTSGAMEODDS_API_KEY. Never silent."""


def have_key():
    return bool(os.environ.get(ENV_KEY))


def events_url(sport="mlb"):
    return f"{API_ROOT}/events/?sport={sport}&oddsAvailable=true"


def _moneyline_price(v):
    """SGO-style odd object -> american price int where possible."""
    if isinstance(v, dict):
        for k in ("price", "american", "odds"):
            if k in v:
                return v[k]
        return None
    return v


def parse_sgo_payload(payload, timestamp_captured, source_url="feed://sportsgameodds"):
    """Normalized SGO events payload -> owner-schema records. Pure parse, no I/O.

    Expected shape (documented in the SGO API): events with eventID/teams, and an odds map keyed
    by market whose values carry per-book {line, price} entries. Unknown shapes yield nothing
    rather than invented numbers.
    """
    records = []
    events = payload.get("events") or payload.get("data") or []
    for ev in events:
        eid = str(ev.get("eventID") or ev.get("event_id") or ev.get("id"))
        odds = ev.get("odds") or {}
        for market_key, market in (("moneyline", "moneyline"), ("spreads", "spread"),
                                   ("totals", "total")):
            entries = odds.get(market_key) or {}
            # entries: {sportsbook: {"line": x, "price": y}} or list of {book, line, price}
            if isinstance(entries, list):
                entries = {e.get("sportsbook") or e.get("book"): e for e in entries}
            for book, val in entries.items():
                line = val.get("line") if isinstance(val, dict) else None
                price = _moneyline_price(val) if market == "moneyline" else (
                    val.get("price") if isinstance(val, dict) else None)
                if line is None and market == "moneyline":
                    line = 0.0  # moneyline carries no run line; schema requires a number
                if price is None or line is None:
                    continue
                records.append(market_capture.make_record(
                    eid, str(book).lower(), market, line, price,
                    timestamp_captured, source_url,
                    # Event start is not the quote's update time. This adapter
                    # has no verified source-update field for the retained schema.
                    timestamp_source=None,
                    grade=market_capture.GRADE_CONFIRMED,
                    grade_basis="structured SportsGameOdds feed response; the feed is the "
                                "source of record for its own quotes (valuation-only)",
                    feed="sportsgameodds",
                    away=(ev.get("teams") or {}).get("away", {}).get("name")
                    if isinstance(ev.get("teams"), dict) else None,
                    home=(ev.get("teams") or {}).get("home", {}).get("name")
                    if isinstance(ev.get("teams"), dict) else None))
    return records


def fetch_events(sport="mlb", get=None):
    """Live fetch. STUB MODE without a key: raises StubModeNoKey, never fabricates."""
    if not have_key():
        raise StubModeNoKey(
            f"{ENV_KEY} not set — SportsGameOdds client is in stub mode. Drive it with a fixture "
            "via parse_sgo_payload; a stub must never invent prices.")
    if get is None:
        def get(url):
            import requests
            r = requests.get(url, timeout=20,
                             headers={"Authorization": f"Bearer {os.environ[ENV_KEY]}",
                                      "User-Agent": "sports-model-fu1/1.0"})
            r.raise_for_status()
            return r.text
    import json
    text = get(events_url(sport))
    captured = dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return parse_sgo_payload(json.loads(text), captured), text, market_capture.snapshot_hash(text)


# ====================================================================== selftest

def selftest():
    f = []
    payload = {"events": [{
        "eventID": "SGO1", "status": {"startsAt": "2026-08-28T23:10Z"},
        "teams": {"away": {"name": "Houston Astros"}, "home": {"name": "New York Mets"}},
        "odds": {"spreads": {"draftkings": {"line": -1.5, "price": -110},
                             "fanduel": {"line": -1.5, "price": -105},
                             "betmgm": {"line": -2.5, "price": -110},
                             "circa": {"line": -1.5, "price": -108}},
                 "moneyline": {"draftkings": {"price": -130}, "circa": {"price": -125}}}}]}
    recs = parse_sgo_payload(payload, "2026-08-30T00:00:00Z")
    if len(recs) != 6:
        f.append(f"expected 6 records, got {len(recs)}")
    if any(r["grade"] != "CONFIRMED" for r in recs):
        f.append("structured feed records lost the feed grade")
    c = market_capture.consensus(recs, "SGO1", "spread")
    if c["n_books"] != 3 or c["sharp_reference"]["sportsbook"] != "circa":
        f.append(f"circa handling wrong: {c}")
    # stub mode: no key -> loud refusal, no fabrication
    old = os.environ.pop(ENV_KEY, None)
    try:
        fetch_events("mlb", get=lambda u: "{}")
        f.append("stub mode fabricated a live fetch")
    except StubModeNoKey:
        pass
    finally:
        if old:
            os.environ[ENV_KEY] = old

    print(f"market_sportsgameodds selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("   -", x)
    return 0 if not f else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__)
