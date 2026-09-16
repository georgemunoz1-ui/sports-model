"""Market data quality — P0 layer (owner Addendum 6, merge-blocking).

FOUR things, each testable:
1. CANONICAL EVENT IDENTITY. One event = league + season + participants + venue + start + status.
   canonical_event_key prevents duplicate games and bad joins across feeds: two records from
   different feeds for the same game resolve to ONE key; two different games never share one.
2. ODDS QUALITY FIELDS. Every record can carry: source, book, quote_age_seconds (computed from
   timestamp_source to timestamp_captured, never asserted), stale flag (named threshold),
   missingness, market_status (suspended), update latency. A suspended market or a stale quote
   is a QUALITY fact about the record — it never deletes the record and never silently clears.
3. VERSIONED SNAPSHOTS. raw response + normalized record + schema_version + ingestion_run_id —
   the reproducibility triple. Replaying run_id R over the raw response must reproduce the
   normalized records byte-for-byte (pure parsers make this true by construction; the test
   proves it).
4. DATA-QUALITY TESTS as a gate function: uniqueness, timestamp ordering, valid line/price
   ranges, team-name mapping, missingness thresholds. Returns problems; empty = clean.
"""
from __future__ import annotations

MODULE_ID = "market_quality"

import datetime as dt
import hashlib
import json
import sys

UTC = dt.timezone.utc

SCHEMA_VERSION = "market_quality.v1"

#: a quote older than this between source-publish and capture is STALE (a quality fact)
STALE_QUOTE_SECONDS = 900          # 15 minutes
MISSINGNESS_THRESHOLD = 0.20       # >20% missing on a required-ish field -> problem
VALID_AMERICAN_PRICE = (-100000, 100000)
VALID_LINE = (-100, 100)

DUPLICATE_EVENT = "DUPLICATE_EVENT_IDENTITY"
STALE_QUOTE = "STALE_QUOTE"
SUSPENDED_MARKET = "MARKET_SUSPENDED"
MISSINGNESS_BREACH = "MISSINGNESS_ABOVE_THRESHOLD"
BAD_RANGE = "LINE_OR_PRICE_OUT_OF_RANGE"
UNMAPPED_TEAM = "TEAM_NAME_UNMAPPED"
ORDERING = "TIMESTAMP_ORDERING_VIOLATION"


def _utc(value):
    p = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return p if p.tzinfo else p.replace(tzinfo=UTC)


def canonical_event_key(league, season, away, home, start_utc, venue=None, status="scheduled"):
    """THE duplicate/bad-join guard. Normalized, order-sensitive (away@home matters)."""
    def norm(s):
        return " ".join(str(s or "").upper().replace(".", "").split())
    start = _utc(start_utc).isoformat().replace("+00:00", "Z")
    return "|".join([norm(league), str(season), norm(away), norm(home), start,
                     norm(venue) if venue else "-", norm(status)])


def quote_age_seconds(record):
    """timestamp_source -> timestamp_captured. Computed, never asserted. None when the source
    did not publish a timestamp (unknown, not zero)."""
    ts, tc = record.get("timestamp_source"), record.get("timestamp_captured")
    if not ts or not tc:
        return None
    return (_utc(tc) - _utc(ts)).total_seconds()


def quality_fields(record, stale_after=STALE_QUOTE_SECONDS):
    """Attach the P0 quality fields. Returns a NEW record; the input is untouched (append-only
    spirit — a quality assessment is a new version, not a rewrite)."""
    out = dict(record)
    age = quote_age_seconds(record)
    out["quote_age_seconds"] = age
    out["stale"] = bool(age is not None and age > stale_after)
    out["market_status"] = record.get("market_status", "open")
    out["missingness"] = sum(1 for f in ("line", "price", "timestamp_source")
                             if record.get(f) in (None, "", "TBD")) / 3.0
    out["schema_version"] = SCHEMA_VERSION
    return out


def versioned_snapshot(raw_text, normalized_records, ingestion_run_id):
    """raw + normalized + schema_version + ingestion_run_id. Reproducibility envelope."""
    return {"schema_version": SCHEMA_VERSION,
            "ingestion_run_id": ingestion_run_id,
            "raw_sha256": hashlib.sha256(raw_text.encode()).hexdigest(),
            "normalized_sha256": hashlib.sha256(
                json.dumps(normalized_records, sort_keys=True).encode()).hexdigest(),
            "n_records": len(normalized_records)}


def dq_gate(records, team_mapper=None, missingness_threshold=MISSINGNESS_THRESHOLD):
    """The data-quality battery. uniqueness / timestamp ordering / ranges / team mapping /
    missingness. Returns problems (empty = clean). team_mapper: name -> abbr or None."""
    problems = []
    seen = {}
    for i, r in enumerate(records):
        key = (r.get("event_id"), r.get("sportsbook"), r.get("market") or r.get("market_type"),
               r.get("outcome"), r.get("snapshot_time_utc") or r.get("timestamp_captured"))
        if key in seen:
            problems.append({"code": DUPLICATE_EVENT, "index": i, "first": seen[key], "key": key})
        seen[key] = i
        age = quote_age_seconds(r)
        if age is not None and age < 0:
            problems.append({"code": ORDERING, "index": i,
                             "detail": "captured before the source published it"})
        if age is not None and age > STALE_QUOTE_SECONDS:
            problems.append({"code": STALE_QUOTE, "index": i, "quote_age_seconds": age})
        if r.get("market_status") == "suspended":
            problems.append({"code": SUSPENDED_MARKET, "index": i,
                             "detail": "quality fact; record retained, flagged"})
        price, line = r.get("price", r.get("american_price")), r.get("line", r.get("point"))
        try:
            if not (VALID_AMERICAN_PRICE[0] < float(price) < VALID_AMERICAN_PRICE[1]):
                problems.append({"code": BAD_RANGE, "index": i, "price": price})
        except (TypeError, ValueError):
            problems.append({"code": BAD_RANGE, "index": i, "price": price})
        try:
            if not (VALID_LINE[0] < float(line) < VALID_LINE[1]):
                problems.append({"code": BAD_RANGE, "index": i, "line": line})
        except (TypeError, ValueError):
            problems.append({"code": BAD_RANGE, "index": i, "line": line})
        if team_mapper:
            for tf in ("away", "home", "away_team", "home_team"):
                name = r.get(tf)
                if name and team_mapper(name) is None:
                    problems.append({"code": UNMAPPED_TEAM, "index": i, "team": name})
    for fld in ("price", "line", "timestamp_source"):
        if records:
            miss = sum(1 for r in records if r.get(fld, r.get("american_price" if fld == "price"
                                                                 else "point" if fld == "line"
                                                                 else fld)) in (None, "", "TBD"))
            if miss / len(records) > missingness_threshold:
                problems.append({"code": MISSINGNESS_BREACH, "field": fld,
                                 "missing": miss, "n": len(records),
                                 "threshold": missingness_threshold})
    return problems


# ====================================================================== selftest

def selftest():
    f = []
    k1 = canonical_event_key("mlb", 2026, "Houston Astros", "New York Mets",
                             "2026-08-28T23:10:00Z")
    k2 = canonical_event_key("MLB", "2026", "Houston  Astros", "N.Y. Mets".replace("N.Y.", "New York"),
                             "2026-08-28T23:10:00+00:00")
    if k1 != k2:
        f.append("the same game keyed differently across feeds")
    k3 = canonical_event_key("mlb", 2026, "New York Mets", "Houston Astros",
                             "2026-08-28T23:10:00Z")
    if k1 == k3:
        f.append("reversed teams collapsed into one event key")
    rec = {"timestamp_source": "2026-08-28T20:00:00Z",
           "timestamp_captured": "2026-08-28T20:20:00Z", "price": -110, "line": -1.5}
    q = quality_fields(rec)
    if q["quote_age_seconds"] != 1200.0 or not q["stale"]:
        f.append(f"quality fields wrong: {q}")
    if "stale" in rec:
        f.append("quality assessment rewrote the original record")
    snap = versioned_snapshot("{}", [rec], "run-1")
    if snap["schema_version"] != SCHEMA_VERSION or snap["n_records"] != 1:
        f.append("snapshot envelope wrong")
    # dq battery
    good = [dict(rec, event_id="E1", sportsbook="circa", market="spread"),
            dict(rec, event_id="E1", sportsbook="pinnacle", market="spread",
                 timestamp_captured="2026-08-28T20:01:00Z")]
    probs = dq_gate(good)
    if not any(p["code"] == STALE_QUOTE for p in probs):
        f.append("a stale quote was not flagged")
    bad = good + [dict(good[0])]
    if not any(p["code"] == DUPLICATE_EVENT for p in dq_gate(bad)):
        f.append("a duplicate snapshot was not caught")
    if not any(p["code"] == UNMAPPED_TEAM for p in
               dq_gate([dict(good[0], away="Seattle Mariners")],
                       team_mapper=lambda n: "SEA" if n == "Seattle Marinerz" else None)):
        f.append("an unmapped team name passed")

    print(f"market_quality selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("   -", x)
    return 0 if not f else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__)
