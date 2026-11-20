"""Market capture — shared schema, consensus, disagreement surfacing, and the firewall.

GOVERNANCE (load-bearing, unchanged): this layer is VALUATION/AUDIT ONLY. Market records live in
their own namespace (market_* modules, sportsbook-keyed records) and no forecast module may
import them. `assert_no_market_imports` is the mechanical check; harness/market_independence.py
remains the policy gate. Consensus is a SET of book prices plus a computed consensus — never
"the Vegas line" as a single number. Circa Sports is captured as its own labelled sharp-reference
book and is NEVER folded into consensus.

RECORD SCHEMA (owner-specified): every observation carries
  event_id, sportsbook, market, line, price, timestamp_captured, timestamp_source (if published),
  source_url/feed, plus grade + provenance. Structured feed responses (SportsGameOdds, The Odds
  API) may carry the feed grade (CONFIRMED: the feed is the source of record for ITS OWN quotes —
  this says nothing about any forecast input). Browser-readable scrapers (Covers, VegasInsider,
  OddsTrader) are always IDENTIFIED_UNCONFIRMED and are supplemental verification, never the only
  source for a number.
"""
from __future__ import annotations

MODULE_ID = "market_capture"

import hashlib
import json
import datetime as dt
import math
import statistics
import sys

INFORMATION_CLASS = "VALUATION_ONLY"

#: modules a forecast path must never import (the firewall list; kept in one place)
MARKET_MODULES = ("market_capture", "market_sportsgameodds", "market_theoddsapi",
                  "market_history", "market_moneyline", "backtest_causal", "calibration")

REQUIRED_FIELDS = ("event_id", "sportsbook", "market", "line", "price",
                   "timestamp_captured", "source_url")
OPTIONAL_FIELDS = ("timestamp_source", "grade", "grade_basis", "feed", "away", "home",
                   "date_et", "fetched_utc")

GRADE_CONFIRMED = "CONFIRMED"                      # structured feed asserts its own quote
GRADE_UNCONFIRMED = "IDENTIFIED_UNCONFIRMED"       # scraped / browser-readable, always

SHARP_REFERENCE_BOOK = "circa"   # Las Vegas sharp book: own label, never in consensus

VALID_MARKETS = ("moneyline", "spread", "total")

MISSING_FIELD = "MISSING_IDENTITY_FIELD"
BAD_MARKET = "UNKNOWN_MARKET"
BAD_PRICE = "UNPARSEABLE_PRICE"
BAD_TIMESTAMP = "INVALID_QUOTE_TIMESTAMP"
CONFLICT = "CONFLICT"
DISAGREEMENT_POINTS = 2.0   # two books this far apart on a line -> CONFLICT, never a silent pick


def validate_record(rec):
    """One observation against the owner-specified schema. Returns a list of problems (empty=ok)."""
    problems = []
    for f in REQUIRED_FIELDS:
        if rec.get(f) in (None, "", "TBD"):
            problems.append({"code": MISSING_FIELD, "field": f})
    for field in ("event_id", "sportsbook", "source_url"):
        if not isinstance(rec.get(field), str) or not rec[field].strip() or rec[field] == "None":
            problems.append({"code": MISSING_FIELD, "field": field})
    if problems:
        return problems
    if rec["market"] not in VALID_MARKETS:
        problems.append({"code": BAD_MARKET, "market": rec["market"]})
    try:
        price = _finite_number(rec["price"])
        if abs(price) < 100:
            raise ValueError("American odds require magnitude >= 100")
    except (TypeError, ValueError, OverflowError):
        problems.append({"code": BAD_PRICE, "price": rec["price"]})
    try:
        _finite_number(rec["line"])
    except (TypeError, ValueError, OverflowError):
        problems.append({"code": BAD_PRICE, "field": "line", "line": rec["line"]})
    for field in ("timestamp_captured", "timestamp_source"):
        if field == "timestamp_source" and rec.get(field) is None:
            continue
        try:
            _instant(rec[field])
        except (TypeError, ValueError, OverflowError):
            problems.append({"code": BAD_TIMESTAMP, "field": field})
    if not any(p["code"] == BAD_TIMESTAMP for p in problems) and rec.get("timestamp_source") is not None:
        if _instant(rec["timestamp_source"]) > _instant(rec["timestamp_captured"]):
            problems.append({"code": BAD_TIMESTAMP, "field": "timestamp_source", "reason": "SOURCE_AFTER_CAPTURE"})
    if rec.get("information_class", INFORMATION_CLASS) != INFORMATION_CLASS:
        problems.append({"code": "INVALID_INFORMATION_CLASS"})
    return problems


def _finite_number(value):
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("nonfinite number")
    return value


def _instant(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone required")
    return value.astimezone(dt.timezone.utc)


def validate_records(records):
    bad = [(i, validate_record(r)) for i, r in enumerate(records)]
    return [(i, p) for i, p in bad if p]


def make_record(event_id, sportsbook, market, line, price, timestamp_captured,
                source_url, timestamp_source=None, grade=GRADE_UNCONFIRMED,
                grade_basis="", feed=None, **extra):
    rec = {"event_id": str(event_id) if event_id is not None and not isinstance(event_id, bool) else None, "sportsbook": sportsbook, "market": market,
           "line": line, "price": price, "timestamp_captured": timestamp_captured,
           "source_url": source_url, "feed": feed or source_url,
           "grade": grade, "grade_basis": grade_basis,
           "information_class": INFORMATION_CLASS}
    if timestamp_source is not None:
        rec["timestamp_source"] = timestamp_source
    rec.update(extra)
    problems = validate_record(rec)
    if problems:
        raise ValueError(f"record fails schema: {problems}")
    return rec


def consensus(records, event_id, market, exclude_books=(SHARP_REFERENCE_BOOK,)):
    """The set of book prices + a computed consensus. NEVER a single 'Vegas line'.

    Returns {event_id, market, books: {book: (line, price)}, n_books,
             consensus_line, consensus_price (medians across books), sharp_reference}.
    The sharp-reference book (Circa) is reported separately and excluded from the medians.
    """
    books = {}
    sharp = None
    for r in records:
        if r["event_id"] != str(event_id) or r["market"] != market:
            continue
        if validate_record(r):
            raise ValueError("INVALID_CONSENSUS_RECORD")
        if r["sportsbook"] in exclude_books:
            sharp = {"sportsbook": r["sportsbook"], "line": r["line"], "price": r["price"],
                     "label": "SHARP_REFERENCE_not_in_consensus"}
            continue
        books[r["sportsbook"]] = (float(r["line"]), float(r["price"]))
    out = {"event_id": str(event_id), "market": market, "books": books,
           "n_books": len(books), "sharp_reference": sharp,
           "rule": "consensus is this set of book prices plus the computed medians; "
                   "no single book is 'the' line"}
    if books:
        out["consensus_line"] = statistics.median(l for l, _ in books.values())
        out["consensus_price"] = statistics.median(p for _, p in books.values())
    else:
        out["consensus_line"] = out["consensus_price"] = None
    return out


def disagreements(records, event_id, market, threshold=DISAGREEMENT_POINTS):
    """Two books >= threshold points apart on a line -> CONFLICT status. Surfaced, never picked."""
    threshold = _finite_number(threshold)
    if threshold < 0:
        raise ValueError("INVALID_DISAGREEMENT_THRESHOLD")
    cons = consensus(records, event_id, market)
    lines = {b: l for b, (l, _) in cons["books"].items()}
    out = []
    bs = sorted(lines)
    for i in range(len(bs)):
        for j in range(i + 1, len(bs)):
            gap = abs(lines[bs[i]] - lines[bs[j]])
            if gap >= threshold:
                out.append({"code": CONFLICT, "kind": "BOOK_LINE_DISAGREEMENT",
                            "event_id": str(event_id), "market": market,
                            "books": {bs[i]: lines[bs[i]], bs[j]: lines[bs[j]]},
                            "gap_points": gap, "threshold": threshold,
                            "detail": "surfaced, not resolved — no book is silently preferred"})
    return out


def assert_no_market_imports(path):
    """THE FIREWALL CHECK. A forecast-path file importing any market_* module fails.

    Returns a list of violations (empty = clean). Import text is scanned statically so the check
    works without executing the target.
    """
    violations = []
    with open(path) as fh:
        for n, line in enumerate(fh, 1):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                for mod in MARKET_MODULES:
                    if f" {mod}" in f" {stripped}" and (stripped.startswith(f"import {mod}")
                                                        or stripped.startswith(f"from {mod}")):
                        violations.append({"file": path, "line": n, "module": mod,
                                           "code": "MARKET_IMPORT_IN_FORECAST_PATH"})
    return violations


def snapshot_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


# ====================================================================== selftest

def selftest():
    import tempfile, os
    f = []
    books = [("draftkings", -3.5, -110), ("fanduel", -3.5, -108), ("betmgm", -4.0, -110),
             ("circa", -4.5, -105)]
    recs = [make_record("EV1", b, "spread", l, p, "2026-08-30T00:00:00Z",
                        f"fixture://{b}", grade=GRADE_CONFIRMED, feed="fixture")
            for b, l, p in books]
    if validate_records(recs):
        f.append("valid records failed schema")
    broken = dict(recs[0], price=None)
    if not validate_record(broken):
        f.append("a None price passed schema")
    c = consensus(recs, "EV1", "spread")
    if c["n_books"] != 3 or c["sharp_reference"]["sportsbook"] != "circa":
        f.append(f"circa leaked into consensus: {c}")
    if c["consensus_line"] != -3.5:
        f.append(f"consensus median wrong: {c['consensus_line']}")
    # a sub-2pt spread of opinion is NOT a conflict
    if disagreements(recs, "EV1", "spread"):
        f.append("sub-2pt book differences were falsely surfaced as CONFLICT")
    # the 2+ point rule itself: -3.5 vs -6.0 must CONFLICT
    recs2 = recs + [make_record("EV1", "pinnacle", "spread", -6.0, -110,
                                "2026-08-30T00:00:00Z", "fixture://pinnacle",
                                grade=GRADE_CONFIRMED, feed="fixture")]
    if not any(x["gap_points"] == 2.5 for x in disagreements(recs2, "EV1", "spread")):
        f.append("a 2.5pt book disagreement was not surfaced as CONFLICT")
    # firewall: a file importing a market module is caught; a clean file passes
    with tempfile.TemporaryDirectory() as td:
        dirty = os.path.join(td, "forecast_x.py")
        clean = os.path.join(td, "forecast_y.py")
        open(dirty, "w").write("import market_capture\nx = 1\n")
        open(clean, "w").write("import json\nx = 1\n")
        if not assert_no_market_imports(dirty):
            f.append("the firewall missed a market import in a forecast-path file")
        if assert_no_market_imports(clean):
            f.append("the firewall flagged a clean file")

    print(f"market_capture selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("   -", x)
    return 0 if not f else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__)
