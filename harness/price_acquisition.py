#!/usr/bin/env python3
"""PRICE ACQUISITION — a rail failure advances to the next route; it does not end the workflow.

OWNER DIRECTIVE 2026-08-24, and a defect of mine it names exactly:

    "That confuses a blocked acquisition rail with absent market prices."

I wrote "no prices exist for this slate" after a fetch rail returned EGRESS_BLOCKED. Sportsbooks
priced those games all day. What had actually happened is that ONE route failed and I treated the
failure as a fact about the world instead of a fact about my access — and then stopped, while two
other authorized routes were available and one of them could supply a complete board.

THE LADDER, and the rule that makes it a ladder rather than a list:

    DIRECT_BOOK  ->  NAMED_BOOK_AGGREGATOR  ->  OWNER_RELAY

A rail failure ADVANCES to the next authorized route. It may not terminate acquisition while a later
route remains untried, and it may never be reported as an absence of prices. The terminal state is
NO_ELIGIBLE_CAPTURED_PRICE_BOARD only after every route has been attempted and none produced an
admissible board — and even then the wording is about the evidence package, not about the market.

WHAT DEGRADES AS YOU DESCEND. Each rung is weaker provenance than the one above, and the record says
which rung supplied the board. A direct book capture is the book's own bytes. An aggregator is a
named third party displaying a named book. An owner relay is a person reading a page. All three can
be admissible; none of them are the same evidence, and a board must never be described as stronger
than its rung.

THE VALIDATIONS, all of which are refusals rather than warnings:
  exactly one sportsbook          two books in one board is a cross-book de-vig, which is invalid
                                  for market probability under the 2026-08-03 ruling
  current quotes only             an opening price and a current price are different forecasts of
                                  the market; mixing them silently backdates half the board
  both sides of every market      a one-sided market has no hold and therefore no no-vig probability
  complete game pairing           a partial board invites picking the games that happened to arrive
  canonical team identities       the join defect that has bitten this repository three times
  captured before first start     a post-start quote is not a pregame price
  no alternate rungs mixed        an alternate total at a different line is a different market

API
  LADDER, attempt_ladder(attempts)      -> which rung supplied the board, or the terminal status
  validate_board(board, expected_games) -> (ok, problems)
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import franchise_identity as FI

DIRECT_BOOK = "DIRECT_BOOK"
NAMED_AGGREGATOR = "NAMED_BOOK_AGGREGATOR"
OWNER_RELAY = "OWNER_RELAY"
LADDER = (DIRECT_BOOK, NAMED_AGGREGATOR, OWNER_RELAY)

SUPPLIED = "PRICE_BOARD_SUPPLIED"
EXHAUSTED = "NO_ELIGIBLE_CAPTURED_PRICE_BOARD"
PREMATURE = "ACQUISITION_TERMINATED_WITH_ROUTES_UNTRIED"

# --- validation codes ------------------------------------------------------------------------------
MULTI_BOOK = "MORE_THAN_ONE_SPORTSBOOK_IN_ONE_BOARD"
MIXED_CURRENT_OPEN = "CURRENT_AND_OPENING_PRICES_MIXED"
ONE_SIDED = "MARKET_MISSING_A_SIDE"
INCOMPLETE_PAIRING = "INCOMPLETE_GAME_PAIRING"
UNCANONICAL_ID = "UNCANONICAL_TEAM_IDENTITY"
NOT_PREGAME = "QUOTE_NOT_CAPTURED_BEFORE_FIRST_START"
ALT_RUNG_MIXED = "ALTERNATE_LINE_RUNGS_MIXED_IN_ONE_MARKET"
STALE_QUOTE = "QUOTE_OLDER_THAN_FRESHNESS_CEILING"

FRESHNESS_CEILING_HOURS = 12.0


def attempt_ladder(attempts):
    """`attempts`: [{"route", "outcome", "board"?}, ...] in the order tried.

    outcome: "SUPPLIED" or anything else (a failure). Returns which rung supplied the board, or a
    terminal status — and PREMATURE if acquisition stopped with an authorized route untried.
    """
    tried, supplier = [], None
    for a in (attempts or []):
        route = a.get("route")
        if route not in LADDER:
            return {"status": "UNAUTHORIZED_ROUTE", "route": route, "tried": tried}
        tried.append(route)
        if a.get("outcome") == "SUPPLIED" and a.get("board"):
            supplier = a
            break
    if supplier:
        return {"status": SUPPLIED, "supplying_route": supplier["route"],
                "rung_index": LADDER.index(supplier["route"]), "tried": tried,
                "provenance_note": f"supplied at rung {LADDER.index(supplier['route'])+1} of "
                                   f"{len(LADDER)}; the board is exactly as strong as this rung and "
                                   f"must never be described as stronger"}
    untried = [r for r in LADDER if r not in tried]
    if untried:
        return {"status": PREMATURE, "tried": tried, "untried": untried,
                "why_this_is_an_error": "a rail failure is a fact about access, not about the "
                                        "market. Acquisition may not stop while an authorized route "
                                        "remains untried, and may never report prices as absent."}
    return {"status": EXHAUSTED, "tried": tried,
            "wording_rule": "every route was attempted and none produced an admissible board. This "
                            "is a statement about the evidence package, NOT a claim that no prices "
                            "existed."}


def _both_sides(m):
    return isinstance(m, dict) and m.get("away") is not None and m.get("home") is not None


def validate_board(board, expected_games=None, sport="mlb"):
    """(ok, problems). Every check is a refusal."""
    p = []
    b = board or {}
    books = {r.get("book") for r in (b.get("rows") or [])} | ({b["book"]} if b.get("book") else set())
    books = {x for x in books if x}
    if len(books) > 1:
        p.append(f"{MULTI_BOOK}: {sorted(books)}")
    quote_kinds = {r.get("quote_kind") for r in (b.get("rows") or [])}
    quote_kinds = {x for x in quote_kinds if x}
    if len(quote_kinds) > 1:
        p.append(f"{MIXED_CURRENT_OPEN}: {sorted(quote_kinds)}")
    elif quote_kinds and quote_kinds != {"CURRENT"}:
        p.append(f"{MIXED_CURRENT_OPEN}: board carries {sorted(quote_kinds)}, not CURRENT")
    seen = []
    for r in (b.get("rows") or []):
        g = r.get("game")
        try:
            seen.append(FI.bind(sport if r.get("sport") is None else r["sport"], g.split(":")[-1]))
        except Exception:
            p.append(f"{UNCANONICAL_ID}: {g!r}")
            continue
        for name in ("moneyline", "total"):
            m = r.get(name)
            if m is None:
                continue
            if not _both_sides(m):
                p.append(f"{ONE_SIDED}: {g} {name}")
            if name == "total":
                lines = {m.get("line")}
                if r.get("alternate_totals"):
                    lines |= {a.get("line") for a in r["alternate_totals"]}
                if len(lines) > 1:
                    p.append(f"{ALT_RUNG_MIXED}: {g} total carries lines {sorted(x for x in lines if x is not None)}")
        cap, start = b.get("observed_upper_bound_utc"), r.get("game_start_utc")
        if cap and start and str(cap) >= str(start):
            p.append(f"{NOT_PREGAME}: {g} start {start} at or before capture bound {cap}")
    if expected_games is not None:
        want = set(expected_games)
        got = set(seen)
        if want != got:
            p.append(f"{INCOMPLETE_PAIRING}: {len(got)}/{len(want)} paired; missing {sorted(want-got)}"
                     + (f"; unexpected {sorted(got-want)}" if got - want else ""))
    return (not p), p


def freshness(board, now_utc):
    """Hours between the observation bound and now, against the ceiling."""
    import datetime as dt
    cap = (board or {}).get("observed_upper_bound_utc")
    if not cap or not now_utc:
        return None, "NO_OBSERVATION_BOUND"
    try:
        a = dt.datetime.fromisoformat(str(cap).replace("Z", "+00:00"))
        b = dt.datetime.fromisoformat(str(now_utc).replace("Z", "+00:00"))
    except ValueError:
        return None, "UNPARSEABLE_INSTANT"
    h = (b - a).total_seconds() / 3600.0
    return h, (STALE_QUOTE if h > FRESHNESS_CEILING_HOURS else None)


# =================================================================================================
def selftest():
    f = []

    # --- the ladder --------------------------------------------------------------------------------
    blocked = {"route": DIRECT_BOOK, "outcome": "EGRESS_BLOCKED"}
    relay = {"route": OWNER_RELAY, "outcome": "SUPPLIED", "board": {"rows": []}}
    # THE DEFECT: stopping at a blocked direct rail
    stop = attempt_ladder([blocked])
    if stop["status"] != PREMATURE or NAMED_AGGREGATOR not in stop["untried"]:
        f.append(f"stopping at a blocked rail with routes untried must be PREMATURE, got {stop}")
    if "fact about access" not in stop.get("why_this_is_an_error", ""):
        f.append("the premature status must say why it is an error")
    # descending the ladder to a relay is a supply, and the rung is recorded
    full = attempt_ladder([blocked, {"route": NAMED_AGGREGATOR, "outcome": "EGRESS_BLOCKED"}, relay])
    if full["status"] != SUPPLIED or full["supplying_route"] != OWNER_RELAY:
        f.append(f"a relay after two failures must supply, got {full}")
    if full["rung_index"] != 2:
        f.append("the supplying rung must be recorded")
    if "never be described as stronger" not in full["provenance_note"]:
        f.append("the record must warn that the board is only as strong as its rung")
    # every route attempted and none supplied is the only terminal absence, and it is worded carefully
    ex = attempt_ladder([blocked, {"route": NAMED_AGGREGATOR, "outcome": "X"},
                         {"route": OWNER_RELAY, "outcome": "X"}])
    if ex["status"] != EXHAUSTED or "NOT a claim that no prices existed" not in ex["wording_rule"]:
        f.append("exhaustion must be worded as an evidence statement, not a market claim")
    if attempt_ladder([{"route": "SOME_GUY", "outcome": "SUPPLIED", "board": {}}])["status"] \
            != "UNAUTHORIZED_ROUTE":
        f.append("an unauthorized route must be refused")
    # a board supplied at rung 1 stops the ladder there
    early = attempt_ladder([{"route": DIRECT_BOOK, "outcome": "SUPPLIED", "board": {"rows": []}}, relay])
    if early["supplying_route"] != DIRECT_BOOK or early["tried"] != [DIRECT_BOOK]:
        f.append("a rung-1 supply must not descend further")

    # --- validations -------------------------------------------------------------------------------
    def row(game, **kw):
        d = {"game": game, "sport": "mlb", "book": "DRAFTKINGS", "quote_kind": "CURRENT",
             "game_start_utc": "2026-08-24T22:40:00Z",
             "moneyline": {"away": -124, "home": 115},
             "total": {"line": 7.0, "away": None, "home": None, "over": -119, "under": -101}}
        d["total"] = {"line": 7.0, "away": -119, "home": -101}
        d.update(kw); return d
    board = {"book": "DRAFTKINGS", "observed_upper_bound_utc": "2026-08-24T16:41:27Z",
             "rows": [row("mlb:BOS@MIA"), row("mlb:TB@DET")]}
    want = ["mlb:BOS@MIA", "mlb:TB@DET"]
    ok, pr = validate_board(board, want)
    if not ok:
        f.append(f"a clean board must validate, got {pr}")
    # exactly one book
    two = {**board, "rows": [row("mlb:BOS@MIA"), row("mlb:TB@DET", book="FANDUEL")]}
    if validate_board(two, want)[0] or not any(MULTI_BOOK in x for x in validate_board(two, want)[1]):
        f.append("two books in one board must be refused")
    # current vs opening
    mixed = {**board, "rows": [row("mlb:BOS@MIA"), row("mlb:TB@DET", quote_kind="OPENING")]}
    mp = [x for x in validate_board(mixed, want)[1] if MIXED_CURRENT_OPEN in x]
    if not mp:
        f.append("mixing current and opening prices must be refused")
    # the MIXING rule and the NOT-CURRENT rule are different rules and must be separately visible:
    # a board carrying both kinds is caught as a MIX, not merely as "not current". Asserting only
    # the code would let the not-current branch mask a deleted mixing branch (lesson 24).
    elif "board carries" in mp[0]:
        f.append("a board holding BOTH kinds must be reported as a mix, not as a not-current board")
    allopen = {**board, "rows": [row("mlb:BOS@MIA", quote_kind="OPENING")]}
    if not any(MIXED_CURRENT_OPEN in x for x in validate_board(allopen, ["mlb:BOS@MIA"])[1]):
        f.append("an all-opening board is not a current board")
    # both sides
    half = {**board, "rows": [row("mlb:BOS@MIA", moneyline={"away": -124}), row("mlb:TB@DET")]}
    if not any(ONE_SIDED in x for x in validate_board(half, want)[1]):
        f.append("a one-sided market must be refused")
    # pairing
    if not any(INCOMPLETE_PAIRING in x for x in
               validate_board({**board, "rows": [row("mlb:BOS@MIA")]}, want)[1]):
        f.append("an incomplete board must be refused")
    # canonical ids
    if not any(UNCANONICAL_ID in x for x in
               validate_board({**board, "rows": [row("mlb:QQQ@ZZZ")]}, want)[1]):
        f.append("an unresolvable team id must be refused")
    # pregame
    early_start = {**board, "rows": [row("mlb:BOS@MIA", game_start_utc="2026-08-24T10:00:00Z")]}
    if not any(NOT_PREGAME in x for x in validate_board(early_start, ["mlb:BOS@MIA"])[1]):
        f.append("a quote bound at or after the start is not pregame")
    # alternate rungs
    alt = {**board, "rows": [row("mlb:BOS@MIA", alternate_totals=[{"line": 7.5}])]}
    if not any(ALT_RUNG_MIXED in x for x in validate_board(alt, ["mlb:BOS@MIA"])[1]):
        f.append("mixing total rungs in one market must be refused")

    # --- freshness ---------------------------------------------------------------------------------
    h, why = freshness(board, "2026-08-24T18:00:00Z")
    if why is not None or abs(h - 1.30917) > 1e-4:
        f.append(f"a 1.3h-old board is fresh, got {h} {why}")
    h2, why2 = freshness(board, "2026-08-25T18:00:00Z")
    if why2 != STALE_QUOTE:
        f.append("a board older than the ceiling must be stale")
    if freshness({}, "2026-08-24T18:00:00Z")[1] != "NO_OBSERVATION_BOUND":
        f.append("no observation bound must be reported, not assumed fresh")

    for x in f:
        print("FAIL:", x)
    if not f:
        print("price_acquisition selftest: OK")
    return f


MUTANTS = [
    ("stopping at a blocked rail is treated as exhaustion",
     "    untried = [r for r in LADDER if r not in tried]\n    if untried:", "    untried = []\n    if untried:"),
    ("exhaustion is worded as a claim about the market",
     '            "wording_rule": "every route was attempted and none produced an admissible board. This "\n                            "is a statement about the evidence package, NOT a claim that no prices "\n                            "existed."}',
     '            "wording_rule": "no prices existed."}'),
    ("the premature status stops explaining itself",
     '                "why_this_is_an_error": "a rail failure is a fact about access, not about the "', '                "why_this_is_an_error": "" or ("'),
    ("an unauthorized route is accepted",
     "        if route not in LADDER:", "        if False:"),
    ("the supplying rung stops being recorded",
     '                "provenance_note": f"supplied at rung {LADDER.index(supplier[\'route\'])+1} of "', '                "provenance_note": "" or (f"'),
    ("a rung-1 supply keeps descending the ladder",
     "            supplier = a\n            break", "            supplier = a"),
    ("two sportsbooks in one board are accepted",
     "    if len(books) > 1:", "    if False:"),
    ("current and opening prices may be mixed",
     "    if len(quote_kinds) > 1:", "    if False:"),
    ("an all-opening board passes as current",
     '    elif quote_kinds and quote_kinds != {"CURRENT"}:', "    elif False:"),
    ("a one-sided market is accepted",
     "            if not _both_sides(m):", "            if False:"),
    ("both-sides means either side",
     '    return isinstance(m, dict) and m.get("away") is not None and m.get("home") is not None',
     '    return isinstance(m, dict) and (m.get("away") is not None or m.get("home") is not None)'),
    ("an incomplete board is accepted",
     "        if want != got:", "        if False:"),
    ("an unresolvable team id is passed through",
     '            p.append(f"{UNCANONICAL_ID}: {g!r}")\n            continue', "            continue"),
    ("a post-start quote counts as pregame",
     "        if cap and start and str(cap) >= str(start):", "        if False:"),
    ("alternate total rungs may be mixed",
     "                if len(lines) > 1:", "                if False:"),
    ("a stale board passes the freshness ceiling",
     "    return h, (STALE_QUOTE if h > FRESHNESS_CEILING_HOURS else None)", "    return h, None"),
    ("a board with no observation bound is assumed fresh",
     '    if not cap or not now_utc:\n        return None, "NO_OBSERVATION_BOUND"', "    if not cap or not now_utc:\n        return 0.0, None"),
]


def mutation_suite(verbose=True):
    import subprocess as _sp, tempfile as _tf
    src = open(os.path.abspath(__file__)).read()
    i = src.index("MUTANTS = [")
    j = src.index("\ndef mutation_suite", i)
    head, block, tail = src[:i], src[i:j], src[j:]
    surv, unapp = [], []
    for name, old, new in MUTANTS:
        where = "head" if old in head else ("tail" if old in tail else None)
        if where is None:
            unapp.append(f"{name}: pattern not found"); continue
        mut = (head.replace(old, new, 1) + block + tail) if where == "head" \
            else (head + block + tail.replace(old, new, 1))
        if mut == src:
            unapp.append(f"{name}: no-op"); continue
        with _tf.NamedTemporaryFile("w", suffix="_mutant.py", delete=False,
                                    dir=os.path.dirname(os.path.abspath(__file__))) as fh:
            fh.write(mut); path = fh.name
        try:
            pr = _sp.run([sys.executable, path, "--selftest"], capture_output=True, text=True, timeout=120)
            killed = pr.returncode != 0
        except _sp.TimeoutExpired:
            killed = True
        finally:
            os.unlink(path)
        if verbose:
            print(f"  {'KILLED  ' if killed else 'SURVIVED'}  {name}")
        if not killed:
            surv.append(name)
    for u in unapp:
        print(f"  UNAPPLIED  {u}")
    print(f"mutation suite: {len(MUTANTS)-len(surv)-len(unapp)}/{len(MUTANTS)} killed"
          f"{'' if not (surv or unapp) else '  — SURVIVORS MEAN DECORATIVE FIXTURES'}")
    return surv + unapp


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    if "--mutants" in sys.argv:
        sys.exit(1 if mutation_suite() else 0)
    print(__doc__)
