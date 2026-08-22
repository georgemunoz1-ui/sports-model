#!/usr/bin/env python3
"""THE ACQUISITION LADDER — owner ruling 2026-08-22.

WHY THIS EXISTS. On 2026-08-22 I treated "no owner board" as a terminal blocker, tried one HTTP
rail, got a 403, and asked the owner to post screenshots. That violated standing acquisition
autonomy and it was also factually wrong: approved browsing tools remained available, and when they
were finally used they produced a corroborated 15-game schedule. A failed CONNECT on one rail does
not establish that no public board exists.

The owner's correction, implemented here as a state machine with no dead ends:

  MISSING_UNTRIED            -> acquire automatically. NEVER surfaced to the user as a blocker.
  ONLINE_ACQUIRED            -> proceed normally.
  PARTIAL_ONLINE_ACQUISITION -> register everything safely available, name the exact remaining gaps.
  ACQUISITION_EXHAUSTED      -> report every source tried and how it failed, then ask ONLY for the
                                missing fields.
  NO_GAMES_SCHEDULED         -> ONLY after an official schedule confirms an empty slate.
  ACQUISITION_BLOCKED        -> a network/capability failure. NEVER relabel this "no slate".

THE ORDER IS PART OF THE CONTRACT (forecast first, price second):
  1. schedule / game ids / start times / venues / starters
  2. generate, hash and REGISTER the price-independent forecast
  3. missing MLB starters take the frozen CAP rule and do NOT block v1; verified starters arriving
     later fork an immutable v2
  4. only then acquire attributable same-book prices
  5. missing prices give PRICE_DATA_BLOCKED, never NO_FORECAST
  6. partial / cross-book / snippet-only / unattributable prices are EVIDENCE ONLY and can never be
     de-vigged, and can never produce an edge or a selection

A rail that is denied is recorded as denied. Shell HTTP is never used to evade the org proxy;
approved browsing/search/fetch tools are the rail.
"""
from __future__ import annotations

import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MISSING_UNTRIED = "MISSING_UNTRIED"
ONLINE_ACQUIRED = "ONLINE_ACQUIRED"
PARTIAL_ONLINE_ACQUISITION = "PARTIAL_ONLINE_ACQUISITION"
ACQUISITION_EXHAUSTED = "ACQUISITION_EXHAUSTED"
NO_GAMES_SCHEDULED = "NO_GAMES_SCHEDULED"
ACQUISITION_BLOCKED = "ACQUISITION_BLOCKED"

STATES = (MISSING_UNTRIED, ONLINE_ACQUIRED, PARTIAL_ONLINE_ACQUISITION,
          ACQUISITION_EXHAUSTED, NO_GAMES_SCHEDULED, ACQUISITION_BLOCKED)

# States that may be shown to the owner as something needing THEM. Everything else is mine to do.
USER_ACTIONABLE = (ACQUISITION_EXHAUSTED,)

# The banned phrasing. "No slate to time against" asserts that the system ESTABLISHED an empty
# slate; when schedule acquisition merely failed, that is false and it is what turned a recoverable
# gap into a dead end.
BANNED_PREFLIGHT_PHRASES = ("MISSING_NO_SLATE_TO_TIME_AGAINST", "NO_SLATE_TO_TIME_AGAINST")
CORRECT_UNOBTAINED = "ACQUISITION_BLOCKED—SCHEDULE_NOT_YET_OBTAINED"


def classify(rails_attempted, games_found, official_empty_confirmed=False, fields_missing=None):
    """The state machine. `rails_attempted` is a list of {"rail","host","result"} records.

    games_found is None when nothing was obtained, an int otherwise. official_empty_confirmed is
    True ONLY when an official schedule affirmatively reported zero games."""
    fields_missing = list(fields_missing or [])
    tried = [r for r in (rails_attempted or []) if r.get("result") not in (None, "", "untried")]
    if not tried:
        return MISSING_UNTRIED
    if official_empty_confirmed:
        # An affirmative official zero. Never inferred from a failure.
        return NO_GAMES_SCHEDULED
    if games_found:
        return PARTIAL_ONLINE_ACQUISITION if fields_missing else ONLINE_ACQUIRED
    # Nothing obtained. Distinguish "every approved rail is spent" from "the network denied us".
    approved_rails = {r.get("rail") for r in tried}
    # ORDER MATTERS, and getting it wrong is the 2026-08-22 failure exactly: a single denied rail
    # must NOT reach a terminal state while another approved rail sits untried. Rail diversity is
    # therefore checked BEFORE any conclusion about the network.
    if len(approved_rails) < 2:
        return MISSING_UNTRIED
    denied = [r for r in tried if str(r.get("result", "")).upper().startswith(
        ("EGRESS_BLOCKED", "403", "CONNECT_REJECTED", "BLOCKED"))]
    if denied and len(denied) == len(tried):
        # Several DISTINCT approved rails, every one refused by policy/network. A capability
        # failure — and NOT the same statement as "there are no games".
        return ACQUISITION_BLOCKED
    return ACQUISITION_EXHAUSTED


def may_ask_user(state):
    """User input is requested ONLY after acquisition is exhausted."""
    return state in USER_ACTIONABLE


def preflight_label(state):
    """The wording preflight is allowed to print for a missing schedule."""
    if state in (ACQUISITION_BLOCKED, MISSING_UNTRIED):
        return CORRECT_UNOBTAINED
    if state == NO_GAMES_SCHEDULED:
        return "NO_GAMES_SCHEDULED — official schedule confirms an empty slate"
    return state


def price_state(prices_available, attributable_same_book):
    """Missing or unusable prices block BETTING, never FORECASTING."""
    if not prices_available:
        return "PRICE_DATA_BLOCKED", ("no attributable price was acquired; the forecast stands and "
                                      "betting output is zero")
    if not attributable_same_book:
        return "PRICE_DATA_BLOCKED", ("prices are partial, cross-book, snippet-only or "
                                      "unattributable — EVIDENCE ONLY. They cannot be de-vigged and "
                                      "cannot produce an edge or a selection (8/3 ruling)")
    return "PRICE_OK", None


def starter_state(verified_starters, total_slots):
    """Missing starters take CAP and do NOT block v1."""
    if verified_starters >= total_slots:
        return "STARTERS_RESOLVED", False
    return "STARTERS_CAPPED", False       # second value = blocks_v1, always False


def gate(report):
    """Refuse a cycle report that reintroduces the dead end."""
    fails = []
    st = report.get("state")
    if st not in STATES:
        fails.append(f"unknown acquisition state {st!r}")
    txt = json.dumps(report)
    for bad in BANNED_PREFLIGHT_PHRASES:
        if bad in txt:
            fails.append(f"banned phrasing {bad!r} — it asserts the system established an empty "
                         f"slate when acquisition merely failed; use {CORRECT_UNOBTAINED!r}")
    if report.get("asked_user") and not may_ask_user(st):
        fails.append(f"user input requested in state {st} — the owner is asked ONLY after "
                     f"{ACQUISITION_EXHAUSTED}, and never as a substitute for acquiring")
    if st == NO_GAMES_SCHEDULED and not report.get("official_empty_confirmed"):
        fails.append("NO_GAMES_SCHEDULED without an official confirmation of an empty slate — a "
                     "failed acquisition is not an empty schedule")
    if st == ACQUISITION_BLOCKED and not (report.get("rails_attempted") or []):
        fails.append("ACQUISITION_BLOCKED with no recorded rail attempts")
    if report.get("odds_consulted_before_forecast"):
        fails.append("odds were consulted BEFORE forecast registration — forecast first, price "
                     "second, always")
    if report.get("starters_missing") and report.get("v1_blocked"):
        fails.append("missing starters blocked v1 — they take CAP and never block the forecast")
    if report.get("prices_missing") and report.get("forecast_blocked"):
        fails.append("missing prices blocked the FORECAST — they block betting only "
                     "(PRICE_DATA_BLOCKED, never NO_FORECAST)")
    if report.get("edge_from_unattributable_prices"):
        fails.append("an edge or selection was produced from partial/cross-book/unattributable "
                     "prices — evidence only, never de-vigged")
    return (not fails), fails


# ------------------------------------------------------------------------------------- fixtures
def selftest():
    f = []
    A = lambda rail, host, result: {"rail": rail, "host": host, "result": result}  # noqa: E731

    # No owner board + an accessible schedule STILL generates a pregame card.
    if classify([A("websearch", "publishers", "OK")], games_found=15) != ONLINE_ACQUIRED:
        f.append("an accessible schedule with no owner board did not reach ONLINE_ACQUIRED — this "
                 "is the dead end the ruling exists to remove")
    ok, gf = gate({"state": ONLINE_ACQUIRED, "asked_user": False,
                   "rails_attempted": [A("websearch", "publishers", "OK")]})
    if not ok:
        f.append(f"a healthy online-acquired cycle was refused: {gf}")

    # Nothing tried yet is NEVER a user blocker.
    if classify([], games_found=None) != MISSING_UNTRIED:
        f.append("an untried acquisition was not MISSING_UNTRIED")
    if may_ask_user(MISSING_UNTRIED):
        f.append("MISSING_UNTRIED was treated as user-actionable — that is the exact violation")
    ok, gf = gate({"state": MISSING_UNTRIED, "asked_user": True, "rails_attempted": []})
    if ok or not any("asked ONLY after" in x for x in gf):
        f.append("asking the owner before trying anything was permitted")

    # ONE failed rail does not stop acquisition while another approved rail exists.
    one = classify([A("curl", "statsapi.mlb.com", "403")], games_found=None)
    if one != MISSING_UNTRIED:
        f.append(f"a single denied rail short-circuited acquisition: {one} — another approved rail "
                 f"was still untried, which is what actually happened on 2026-08-22")
    if may_ask_user(one):
        f.append("a single failed rail was treated as grounds to ask the owner")

    # Every approved rail denied => ACQUISITION_BLOCKED, never "no slate".
    allblocked = classify([A("curl", "statsapi.mlb.com", "403"),
                           A("webfetch", "www.mlb.com", "EGRESS_BLOCKED"),
                           A("websearch", "search", "EGRESS_BLOCKED")], games_found=None)
    if allblocked != ACQUISITION_BLOCKED:
        f.append(f"all-rails-denied gave {allblocked}, not ACQUISITION_BLOCKED")
    if preflight_label(allblocked) != CORRECT_UNOBTAINED:
        f.append(f"blocked acquisition printed {preflight_label(allblocked)!r}")
    for bad in BANNED_PREFLIGHT_PHRASES:
        if bad in preflight_label(allblocked):
            f.append(f"the banned phrase {bad} is still printed")
    ok, gf = gate({"state": ACQUISITION_BLOCKED, "rails_attempted": [A("curl", "x", "403")],
                   "note": "MISSING_NO_SLATE_TO_TIME_AGAINST"})
    if ok or not any("banned phrasing" in x for x in gf):
        f.append("the banned 'no slate to time against' phrasing passed the gate")

    # Exhaustion: several DIFFERENT approved rails tried, not all merely denied.
    exh = classify([A("websearch", "s", "no usable result"),
                    A("webfetch", "a", "no usable result"),
                    A("dataset", "github", "no 2026 coverage")], games_found=None)
    if exh != ACQUISITION_EXHAUSTED:
        f.append(f"multiple spent rails gave {exh}, not ACQUISITION_EXHAUSTED")
    if not may_ask_user(ACQUISITION_EXHAUSTED):
        f.append("the owner may not be asked even after exhaustion — that is the other failure mode")
    ok, _ = gate({"state": ACQUISITION_EXHAUSTED, "asked_user": True, "rails_attempted": [1]})
    if not ok:
        f.append("asking the owner AFTER exhaustion was refused")

    # An empty slate requires an OFFICIAL confirmation.
    if classify([A("official", "league", "OK")], games_found=0,
                official_empty_confirmed=True) != NO_GAMES_SCHEDULED:
        f.append("an officially confirmed empty slate was not NO_GAMES_SCHEDULED")
    ok, gf = gate({"state": NO_GAMES_SCHEDULED, "official_empty_confirmed": False,
                   "rails_attempted": [1]})
    if ok or not any("failed acquisition is not an empty schedule" in x for x in gf):
        f.append("NO_GAMES_SCHEDULED was allowed without official confirmation")

    # Partial acquisition registers what is safe and names the gaps.
    part = classify([A("websearch", "s", "OK")], games_found=15,
                    fields_missing=["starters", "prices"])
    if part != PARTIAL_ONLINE_ACQUISITION:
        f.append(f"a partial acquisition gave {part}")

    # Missing starters take CAP and do NOT block v1.
    st, blocks = starter_state(verified_starters=0, total_slots=30)
    if st != "STARTERS_CAPPED" or blocks:
        f.append(f"missing starters blocked v1: {st} blocks={blocks}")
    ok, gf = gate({"state": ONLINE_ACQUIRED, "starters_missing": True, "v1_blocked": True,
                   "rails_attempted": [1]})
    if ok or not any("take CAP and never block" in x for x in gf):
        f.append("a cycle that let missing starters block v1 passed the gate")

    # Missing prices block BETTING only.
    ps, why = price_state(prices_available=False, attributable_same_book=False)
    if ps != "PRICE_DATA_BLOCKED" or not why:
        f.append(f"missing prices did not give PRICE_DATA_BLOCKED: {ps}")
    ok, gf = gate({"state": ONLINE_ACQUIRED, "prices_missing": True, "forecast_blocked": True,
                   "rails_attempted": [1]})
    if ok or not any("block betting only" in x for x in gf):
        f.append("missing prices were allowed to block the FORECAST")

    # Partial / cross-book prices are evidence only.
    ps, why = price_state(prices_available=True, attributable_same_book=False)
    if ps != "PRICE_DATA_BLOCKED" or "cannot be de-vigged" not in (why or ""):
        f.append(f"unattributable prices were not held to EVIDENCE ONLY: {ps} {why}")
    ok, gf = gate({"state": ONLINE_ACQUIRED, "edge_from_unattributable_prices": True,
                   "rails_attempted": [1]})
    if ok or not any("evidence only" in x for x in gf):
        f.append("an edge was produced from unattributable prices")

    # Odds may never be consumed before the forecast is registered.
    ok, gf = gate({"state": ONLINE_ACQUIRED, "odds_consulted_before_forecast": True,
                   "rails_attempted": [1]})
    if ok or not any("forecast first, price second" in x for x in gf):
        f.append("odds were consumed before forecast registration")

    print("acquisition_ladder selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("untried acquisition presented as a user blocker",
     "USER_ACTIONABLE = (ACQUISITION_EXHAUSTED,)",
     "USER_ACTIONABLE = (ACQUISITION_EXHAUSTED, MISSING_UNTRIED)"),
    ("one denied rail ends acquisition", "    if len(approved_rails) < 2:", "    if False:"),
    ("all-rails-denied relabelled as an empty slate",
     "        return ACQUISITION_BLOCKED", "        return NO_GAMES_SCHEDULED"),
    ("empty slate no longer needs official confirmation",
     "    if official_empty_confirmed:", "    if True:"),
    ("banned preflight phrasing permitted", "    for bad in BANNED_PREFLIGHT_PHRASES:", "    for bad in ():"),
    ("preflight prints the banned label again",
     'CORRECT_UNOBTAINED = "ACQUISITION_BLOCKED—SCHEDULE_NOT_YET_OBTAINED"',
     'CORRECT_UNOBTAINED = "MISSING_NO_SLATE_TO_TIME_AGAINST"'),
    ("missing starters block v1", '    return "STARTERS_CAPPED", False',
     '    return "STARTERS_CAPPED", True'),
    ("v1-blocking not caught by the gate",
     '    if report.get("starters_missing") and report.get("v1_blocked"):', "    if False:"),
    ("missing prices block the forecast",
     '    if report.get("prices_missing") and report.get("forecast_blocked"):', "    if False:"),
    ("unattributable prices become usable",
     "    if not attributable_same_book:", "    if False:"),
    ("edge from unattributable prices not caught",
     '    if report.get("edge_from_unattributable_prices"):', "    if False:"),
    ("odds before forecast not caught",
     '    if report.get("odds_consulted_before_forecast"):', "    if False:"),
    ("asking the user is never gated", '    if report.get("asked_user") and not may_ask_user(st):',
     "    if False:"),
    ("partial acquisition collapses into fully acquired",
     "        return PARTIAL_ONLINE_ACQUISITION if fields_missing else ONLINE_ACQUIRED",
     "        return ONLINE_ACQUIRED"),
    ("an accessible schedule no longer proceeds", "    if games_found:", "    if False:"),
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
            unapp.append(f"{name}: pattern not found in executable source")
            continue
        mut = (head.replace(old, new, 1) + block + tail) if where == "head" \
            else (head + block + tail.replace(old, new, 1))
        if mut == src:
            unapp.append(f"{name}: no-op replacement")
            continue
        with _tf.NamedTemporaryFile("w", suffix="_mutant.py", delete=False,
                                    dir=os.path.dirname(os.path.abspath(__file__))) as fh:
            fh.write(mut)
            path = fh.name
        try:
            pr = _sp.run([sys.executable, path, "--selftest"], capture_output=True, text=True,
                         timeout=120)
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
    print(f"mutation suite: {len(MUTANTS) - len(surv) - len(unapp)}/{len(MUTANTS)} killed"
          f"{'' if not (surv or unapp) else '  — SURVIVORS MEAN DECORATIVE FIXTURES'}")
    return surv + unapp


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    if "--mutants" in sys.argv:
        sys.exit(1 if mutation_suite() else 0)
    print(__doc__)
