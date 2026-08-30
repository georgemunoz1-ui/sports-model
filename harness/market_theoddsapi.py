"""The Odds API client — SECONDARY structured odds feed (FU-1 market layer).

500 credits/month, 40+ books incl. DraftKings/FanDuel/BetMGM/Caesars/Pinnacle. Key drops in via
THE_ODDS_API_KEY env var; without a key the client is in STUB MODE (loud refusal, fixture-driven
only — never a fabricated price). Docs: https://the-odds-api.com/liveapi/guides/v4/

Grade: structured feed responses carry CONFIRMED for their own quotes (valuation-only namespace).
"""
from __future__ import annotations

MODULE_ID = "market_theoddsapi"

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import market_capture

UTC = dt.timezone.utc
ENV_KEY = "THE_ODDS_API_KEY"
API_ROOT = "https://api.the-odds-api.com/v4/sports"

SPORT_KEYS = {"mlb": "baseball_mlb", "wnba": "basketball_wnba", "nfl": "americanfootball_nfl",
              "college-football": "americanfootball_ncaaf"}

CREDIT_NOTE = "500 credits/mo; every markets=x param multiplies credit cost — the sweep " \
              "snapshots once per date and reuses the content-hashed file"


class StubModeNoKey(RuntimeError):
    """Raised when a live call is attempted without THE_ODDS_API_KEY. Never silent."""


def have_key():
    return bool(os.environ.get(ENV_KEY))


def odds_url(league="mlb"):
    return f"{API_ROOT}/{SPORT_KEYS[league]}/odds"


def parse_oddsapi_payload(payload, timestamp_captured, source_url="feed://theoddsapi"):
    """The Odds API v4 odds payload -> owner-schema records. Pure parse.

    Shape: list of events {id, home_team, away_team, commence_time, bookmakers: [{key, title,
    last_update, markets: [{key: h2h|spreads|totals, outcomes: [{name, price, point?}]}]}]}.
    h2h maps to moneyline (line recorded as 0.0 — the schema requires a numeric line and a
    moneyline carries none); spreads->spread, totals->total. The outcome name is preserved.
    """
    records = []
    for ev in payload or []:
        eid = str(ev.get("id"))
        for bk in ev.get("bookmakers") or []:
            book = str(bk.get("key", "")).lower()
            for mk in bk.get("markets") or []:
                mkey = mk.get("key")
                market = {"h2h": "moneyline", "spreads": "spread", "totals": "total"}.get(mkey)
                if market is None:
                    continue
                for oc in mk.get("outcomes") or []:
                    price = oc.get("price")
                    if price is None:
                        continue
                    line = 0.0 if market == "moneyline" else oc.get("point")
                    if line is None:
                        continue
                    records.append(market_capture.make_record(
                        eid, book, market, float(line), price, timestamp_captured,
                        source_url,
                        timestamp_source=bk.get("last_update"),
                        grade=market_capture.GRADE_CONFIRMED,
                        grade_basis="structured The Odds API response; the feed is the source "
                                    "of record for its own quotes (valuation-only)",
                        feed="theoddsapi",
                        outcome=oc.get("name"),
                        away=ev.get("away_team"), home=ev.get("home_team")))
    return records


def fetch_odds(league="mlb", get=None):
    if not have_key():
        raise StubModeNoKey(
            f"{ENV_KEY} not set — The Odds API client is in stub mode. Drive it with a fixture "
            "via parse_oddsapi_payload; a stub must never invent prices.")
    if get is None:
        def get(url):
            import requests
            r = requests.get(url, timeout=20, params={
                "apiKey": os.environ[ENV_KEY], "regions": "us",
                "markets": "h2h,spreads,totals", "oddsFormat": "american"},
                headers={"User-Agent": "sports-model-fu1/1.0"})
            r.raise_for_status()
            return r.text
    import json
    captured = dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")
    text = get(odds_url(league))
    return parse_oddsapi_payload(json.loads(text), captured), text, market_capture.snapshot_hash(text)


# ====================================================================== selftest

def selftest():
    f = []
    payload = [{"id": "OA1", "home_team": "New York Mets", "away_team": "Houston Astros",
                "commence_time": "2026-08-28T23:10:00Z",
                "bookmakers": [
                    {"key": "draftkings", "last_update": "2026-08-28T20:00:00Z",
                     "markets": [{"key": "h2h", "outcomes": [{"name": "Houston Astros", "price": -130},
                                                             {"name": "New York Mets", "price": 110}]},
                                 {"key": "spreads", "outcomes": [{"name": "Houston Astros", "price": -110, "point": -1.5}]}]},
                    {"key": "pinnacle", "last_update": "2026-08-28T20:01:00Z",
                     "markets": [{"key": "totals", "outcomes": [{"name": "Over", "price": -105, "point": 8.5}]}]}]}]
    recs = parse_oddsapi_payload(payload, "2026-08-30T00:00:00Z")
    if len(recs) != 4:
        f.append(f"expected 4 records, got {len(recs)}: {recs}")
    if any(r["grade"] != "CONFIRMED" for r in recs):
        f.append("structured records lost the feed grade")
    ml = [r for r in recs if r["market"] == "moneyline"]
    if not ml or ml[0]["line"] != 0.0 or ml[0]["outcome"] != "Houston Astros":
        f.append(f"moneyline mapping wrong: {ml}")
    old = os.environ.pop(ENV_KEY, None)
    try:
        fetch_odds("mlb", get=lambda u: "[]")
        f.append("stub mode fabricated a live fetch")
    except StubModeNoKey:
        pass
    finally:
        if old:
            os.environ[ENV_KEY] = old

    print(f"market_theoddsapi selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("   -", x)
    return 0 if not f else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__)
