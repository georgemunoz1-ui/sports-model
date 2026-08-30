"""Market history — historical odds + line movement schema and the TEMPORAL FIREWALL.

OWNER-SPECIFIED SCHEMA (use exactly — these fields, these names):
  event_id, league, start_time_utc, home_team, away_team, sportsbook, market_type, outcome,
  point, american_price, snapshot_time_utc, source
plus the load-bearing typed field `line_kind`:
  OPENING | CONSENSUS | BEST_AVAILABLE | SHARP_BOOK | CLOSING
The five line KINDS are separate typed values, never mixed into one "historical odds" column:
an opener is a different fact from a close, and a model trained or scored on the wrong one has
look-ahead bias.

TEMPORAL FIREWALL (owner emphasis). A forecast path may consume only lines whose
snapshot_time_utc precedes the model's information cutoff, and a CLOSING line can never be read
by a PREGAME forecast path, whatever its timestamp. `pregame_read` enforces both and RAISES
TemporalFirewallError on violation — fail-loud, never a silent filter that "forgets" the late
line existed (the audit trail must show the refusal).

SOURCE ROLES (owner-supplied):
  - Covers: deep HTML archive (NFL spreads to 1952, open/close level) — scrape carefully.
  - TeamRankings matchup pages: open/current/high/low + timestamped movement, multiple books.
  - OddsPortal: international/broad history, dynamic HTML — targeted collection only.
  - MoneyLine historical odds API: structured movement (see harness/market_moneyline.py).
  - SportsGameOdds doubles as structured backtest source (open/close, per-book, settlements).
  - OddsShark: trend validation ONLY. ESPN odds endpoints: supplemental fragile JSON.
HTML sources (Covers/TeamRankings/OddsPortal/OddsShark) are browser-readable: their records are
always IDENTIFIED_UNCONFIRMED, and they are never the only source for a number.
"""
from __future__ import annotations

MODULE_ID = "market_history"

import datetime as dt
import sys

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import market_capture

UTC = dt.timezone.utc

HISTORY_FIELDS = ("event_id", "league", "start_time_utc", "home_team", "away_team",
                  "sportsbook", "market_type", "outcome", "point", "american_price",
                  "snapshot_time_utc", "source")

LINE_KINDS = ("OPENING", "CONSENSUS", "BEST_AVAILABLE", "SHARP_BOOK", "CLOSING")

#: provenance grade per source class. Structured APIs may carry the feed grade; HTML never can.
SOURCE_GRADES = {
    "moneyline_api": market_capture.GRADE_CONFIRMED,
    "sportsgameodds": market_capture.GRADE_CONFIRMED,
    "covers": market_capture.GRADE_UNCONFIRMED,
    "teamrankings": market_capture.GRADE_UNCONFIRMED,
    "oddsportal": market_capture.GRADE_UNCONFIRMED,
    "oddsshark": market_capture.GRADE_UNCONFIRMED,
    "espn_odds": market_capture.GRADE_UNCONFIRMED,
}

#: sources that are TREND VALIDATION ONLY — their numbers may corroborate, never originate
TREND_VALIDATION_ONLY = ("oddsshark",)

MISSING_FIELD = "MISSING_IDENTITY_FIELD"
BAD_KIND = "UNKNOWN_LINE_KIND"
TEMPORAL_VIOLATION = "POST_CUTOFF_LINE_READ"
CLOSING_IN_PREGAME = "CLOSING_LINE_IN_PREGAME_PATH"


class TemporalFirewallError(RuntimeError):
    """A forecast path asked for a line it must not see. Raised, never filtered away quietly."""


def _utc(value):
    p = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return p if p.tzinfo else p.replace(tzinfo=UTC)


def validate_history_record(rec):
    problems = []
    for f in HISTORY_FIELDS:
        if rec.get(f) in (None, "", "TBD"):
            problems.append({"code": MISSING_FIELD, "field": f})
    if rec.get("line_kind") not in LINE_KINDS:
        problems.append({"code": BAD_KIND, "line_kind": rec.get("line_kind"),
                         "valid": list(LINE_KINDS)})
    if rec.get("source") in TREND_VALIDATION_ONLY:
        # trend-validation sources may exist in the store but are flagged on every record so a
        # downstream consumer cannot mistake them for a price source
        rec.setdefault("trend_validation_only", True)
    return problems


def make_history_record(event_id, league, start_time_utc, home_team, away_team, sportsbook,
                        market_type, outcome, point, american_price, snapshot_time_utc,
                        source, line_kind, timestamp_captured=None, grade=None):
    rec = {"event_id": str(event_id), "league": league, "start_time_utc": start_time_utc,
           "home_team": home_team, "away_team": away_team, "sportsbook": sportsbook,
           "market_type": market_type, "outcome": outcome, "point": float(point),
           "american_price": american_price, "snapshot_time_utc": snapshot_time_utc,
           "source": source, "line_kind": line_kind,
           "timestamp_captured": timestamp_captured or snapshot_time_utc,
           "grade": grade or SOURCE_GRADES.get(source, market_capture.GRADE_UNCONFIRMED),
           "information_class": market_capture.INFORMATION_CLASS}
    problems = validate_history_record(rec)
    if problems:
        raise ValueError(f"history record fails schema: {problems}")
    return rec


def movement(records, event_id, market_type):
    """The OPEN -> CURRENT -> PREGAME CLOSE track for one event/market (the CFB early-board use).

    Returns snapshots sorted by snapshot_time_utc, each with its typed line_kind. The kind of the
    LATEST snapshot before a forecast's cutoff is that forecast's CURRENT; nothing here relabels
    a kind — an OPENING stays an OPENING forever.
    """
    rows = [r for r in records
            if r["event_id"] == str(event_id) and r["market_type"] == market_type]
    return sorted(rows, key=lambda r: (_utc(r["snapshot_time_utc"]), r["sportsbook"]))


def pregame_read(records, cutoff_utc, event_id=None, market_type=None):
    """THE TEMPORAL FIREWALL. What a pregame forecast path may read, and nothing else.

    Raises TemporalFirewallError when the candidate set contains:
      - any record whose snapshot_time_utc is at/after the model's information cutoff, or
      - any CLOSING record (a pregame path never sees the close, even an early-stamped one:
        the kind is the boundary, not the clock).
    Refusals are returned in the error's .refused so the audit shows exactly what was withheld.
    """
    cutoff = _utc(cutoff_utc)
    cand = [r for r in records
            if (event_id is None or r["event_id"] == str(event_id))
            and (market_type is None or r["market_type"] == market_type)]
    refused = []
    for r in cand:
        if r["line_kind"] == "CLOSING":
            refused.append({"code": CLOSING_IN_PREGAME, "record": r,
                            "detail": "a pregame path never reads a closing line; the kind is "
                                      "the boundary, not the timestamp"})
        elif _utc(r["snapshot_time_utc"]) >= cutoff:
            refused.append({"code": TEMPORAL_VIOLATION, "record": r,
                            "cutoff_utc": cutoff.isoformat(),
                            "detail": "snapshot at/after the model information cutoff — "
                                      "look-ahead bias if consumed"})
    if refused:
        err = TemporalFirewallError(
            f"{len(refused)} market record(s) refused to a pregame forecast path")
        err.refused = refused
        raise err
    return cand


# ====================================================================== selftest

def selftest():
    f = []
    base = dict(event_id="H1", league="mlb", start_time_utc="2026-08-28T23:10:00Z",
                home_team="New York Mets", away_team="Houston Astros", sportsbook="draftkings",
                market_type="spread", outcome="Houston Astros -1.5", point=-1.5,
                american_price=-110, source="moneyline_api")
    opener = make_history_record(**base, snapshot_time_utc="2026-08-26T12:00:00Z",
                                 line_kind="OPENING")
    closer = make_history_record(**dict(base, point=-2.5, american_price=-115),
                                 snapshot_time_utc="2026-08-28T23:05:00Z", line_kind="CLOSING")
    if validate_history_record(opener):
        f.append("a valid history record failed schema")
    broken = dict(base, snapshot_time_utc="2026-08-26T12:00:00Z", line_kind="THE_VEGAS_LINE")
    try:
        make_history_record(**broken)
        f.append("a mixed 'vegas line' kind passed schema")
    except ValueError:
        pass
    # temporal firewall: the close is refused to a pregame path, loudly, with the refusal recorded
    try:
        pregame_read([opener, closer], "2026-08-28T20:00:00Z", event_id="H1")
        f.append("a closing line was readable by a pregame path")
    except TemporalFirewallError as e:
        if e.refused[0]["code"] != CLOSING_IN_PREGAME:
            f.append(f"wrong refusal code: {e.refused}")
    # a post-cutoff NON-closing snapshot is refused too
    late = make_history_record(**base, snapshot_time_utc="2026-08-28T21:00:00Z",
                               line_kind="BEST_AVAILABLE")
    try:
        pregame_read([opener, late], "2026-08-28T20:00:00Z", event_id="H1")
        f.append("a post-cutoff line was readable")
    except TemporalFirewallError:
        pass
    # a clean pre-cutoff set reads fine, and movement ordering is OPEN then CURRENT
    ok = pregame_read([opener], "2026-08-28T20:00:00Z", event_id="H1")
    if ok != [opener]:
        f.append("a legal opening line was refused")
    mv = movement([closer, opener], "H1", "spread")
    if [r["line_kind"] for r in mv] != ["OPENING", "CLOSING"]:
        f.append(f"movement order wrong: {[r['line_kind'] for r in mv]}")

    print(f"market_history selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("   -", x)
    return 0 if not f else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__)
