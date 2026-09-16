#!/usr/bin/env python3
"""ECHO GATE — refuse a claimed final that reproduces an ALREADY-GRADED result for the same matchup.

WHY THIS EXISTS (2026-08-22/23, five instances in one night).
Search summarisers repeatedly returned the PREVIOUS day's result and attached it to the requested
date. Every instance involved a continuing series, where the same two teams play on consecutive days
and the only thing distinguishing the games is the date:

  claimed for 8/22        actually 8/21 (already in this registry)
  "Diamondbacks 9-0 Reds"  CIN 0 @ AZ 9      caught twice, in two separate sweeps
  "White Sox 6, Mets 4"    NYM 4 @ CWS 6
  "Royals 5, Tigers 2"     DET 2 @ KC 5
  "Red Sox 6, Giants 4"    SF 4 @ BOS 6
  "Dodgers 5, Pirates 4"   PIT 4 @ LAD 5

One search returned FOUR echoes at once, presented as "the final scores for August 22", with player
details stitched in from other games. Nothing in the prose flagged them. What caught every single
one was comparing the claim against results ALREADY IN THE REGISTRY — a check the machine can do
better and faster than a reader, and one that never gets tired on the fifth instance.

THE RULE: a claimed final whose score EXACTLY matches the same matchup's most recent graded result
is REFUSED pending independent confirmation. A repeated score is not impossible — teams do replay
identical scorelines — so this is a REFUSAL PENDING CONFIRMATION, not a declaration of falsehood.
The asymmetry is deliberate: wrongly ingesting a phantom result corrupts the canonical record and
grades a forecast against a game that never happened, while wrongly deferring costs one cycle.
"""
from __future__ import annotations

MODULE_ID = "echo_gate"

import csv
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(BASE, "data/backfill/mlb/2026/results.csv")


def load_results(path=None):
    p = path or RESULTS
    if not os.path.exists(p):
        return []
    return list(csv.DictReader(open(p)))


def prior_results(away, home, before_date, rows):
    """Every graded result for this exact matchup STRICTLY BEFORE the claimed date, newest first."""
    hits = [r for r in rows
            if r.get("away") == away and r.get("home") == home
            and (r.get("date") or "") < before_date
            and str(r.get("status", "")).lower() == "final"]
    return sorted(hits, key=lambda r: r.get("date", ""), reverse=True)


def check_claim(away, home, date, away_score, home_score, rows=None, window_days=3):
    """(ok, verdict, detail) for one claimed final."""
    rows = load_results() if rows is None else rows
    prior = prior_results(away, home, date, rows)
    if not prior:
        return True, "NO_PRIOR_MEETING", {"checked": 0}
    recent = [r for r in prior if _within(r.get("date", ""), date, window_days)]
    for r in recent:
        try:
            pa, ph = int(r["away_score"]), int(r["home_score"])
        except (KeyError, TypeError, ValueError):
            continue
        if pa == int(away_score) and ph == int(home_score):
            return False, "ECHO_SUSPECTED", {
                "claimed": f"{away} {away_score} @ {home} {home_score} on {date}",
                "matches_graded": f"{away} {pa} @ {home} {ph} on {r['date']}",
                "reason": (
                    "The claimed final reproduces this matchup's most recent graded result exactly, "
                    "and the two dates are inside a continuing series. Five such echoes appeared in "
                    "one night on 2026-08-22/23. REFUSED PENDING INDEPENDENT CONFIRMATION — a "
                    "repeated scoreline is possible, so this is a deferral, not a verdict of "
                    "falsehood. Confirm with a source that carries BOTH the score and the date in "
                    "the same string (an MLB.com Gameday title does; a summary paragraph does not)."),
                "prior_date": r["date"]}
    return True, "NO_ECHO", {"checked": len(recent), "prior_dates": [r["date"] for r in recent]}


def _within(d1, d2, days):
    import datetime
    try:
        a = datetime.date.fromisoformat(d1)
        b = datetime.date.fromisoformat(d2)
    except (ValueError, TypeError):
        return False
    return 0 < (b - a).days <= days


def screen(claims, rows=None):
    """Screen a batch. Returns (accepted, refused)."""
    acc, ref = [], []
    for c in claims:
        ok, verdict, detail = check_claim(c["away"], c["home"], c["date"],
                                          c["away_score"], c["home_score"], rows=rows)
        (acc if ok else ref).append({**c, "verdict": verdict, "detail": detail})
    return acc, ref


def selftest():
    f = []
    rows = [
        {"away": "NYM", "home": "CWS", "date": "2026-08-21", "status": "final",
         "away_score": "4", "home_score": "6"},
        {"away": "CIN", "home": "AZ", "date": "2026-08-21", "status": "final",
         "away_score": "0", "home_score": "9"},
        {"away": "TOR", "home": "NYY", "date": "2026-08-21", "status": "final",
         "away_score": "1", "home_score": "2"},
        {"away": "NYM", "home": "CWS", "date": "2026-06-01", "status": "final",
         "away_score": "4", "home_score": "6"},
        # a LATER-dated meeting: must never be consulted for a claim about an earlier date
        {"away": "SF", "home": "BOS", "date": "2026-08-24", "status": "final",
         "away_score": "4", "home_score": "6"},
        # a NON-FINAL row with a matching score: a suspended game is not a graded result
        {"away": "LAA", "home": "TEX", "date": "2026-08-21", "status": "suspended",
         "away_score": "3", "home_score": "5"},
    ]
    # THE REAL ECHOES from 2026-08-22/23 must all be refused
    for a, h, sa, sh in (("NYM", "CWS", 4, 6), ("CIN", "AZ", 0, 9)):
        ok, v, d = check_claim(a, h, "2026-08-22", sa, sh, rows=rows)
        if ok or v != "ECHO_SUSPECTED":
            f.append(f"the real {a}@{h} echo was ACCEPTED: {v}")
        elif "REFUSED PENDING" not in d.get("reason", ""):
            f.append(f"{a}@{h} refusal does not state it is a deferral rather than a verdict")
    # a DIFFERENT score for the same matchup is fine — series continue and scores differ
    ok, v, _ = check_claim("NYM", "CWS", "2026-08-22", 3, 7, rows=rows)
    if not ok or v != "NO_ECHO":
        f.append(f"a genuinely different score for a continuing series was refused: {v}")
    ok, v, _ = check_claim("TOR", "NYY", "2026-08-22", 4, 3, rows=rows)
    if not ok:
        f.append("the real TOR@NYY 4-3 result was refused (8/21 was 1-2, a different score)")
    # ONE side matching is not an echo — both scores must match, in the right slots
    ok, v, _ = check_claim("NYM", "CWS", "2026-08-22", 3, 6, rows=rows)   # home matches, away not
    if not ok or v != "NO_ECHO":
        f.append(f"a claim matching only the HOME score was refused as an echo: {v}")
    ok, v, _ = check_claim("NYM", "CWS", "2026-08-22", 4, 5, rows=rows)   # away matches, home not
    if not ok or v != "NO_ECHO":
        f.append(f"a claim matching only the AWAY score was refused as an echo: {v}")

    # a LATER meeting must never be consulted — an echo comes from the past, not the future
    ok, v, d = check_claim("SF", "BOS", "2026-08-22", 4, 6, rows=rows)
    if not ok:
        f.append(f"a claim was refused against a game dated AFTER it ({d}) — the prior lookup is "
                 f"not filtering on date at all")

    # a NON-FINAL prior row is not a graded result and cannot ground an echo refusal
    ok, v, _ = check_claim("LAA", "TEX", "2026-08-22", 3, 5, rows=rows)
    if not ok:
        f.append(f"a claim was refused against a SUSPENDED game — only graded finals count: {v}")

    # a matchup with no prior meeting cannot echo
    ok, v, _ = check_claim("ATL", "MIL", "2026-08-22", 5, 4, rows=rows)
    if not ok or v != "NO_PRIOR_MEETING":
        f.append(f"a first meeting was treated as an echo: {v}")
    # an OLD identical score outside the window is not an echo — series echoes are adjacent
    ok, v, _ = check_claim("NYM", "CWS", "2026-06-05", 4, 6, rows=rows)
    if not ok:
        f.append("a June result was flagged against a June 1 game outside the 3-day window")
    # orientation matters: the reversed matchup is a different game
    ok, v, _ = check_claim("CWS", "NYM", "2026-08-22", 6, 4, rows=rows)
    if not ok or v != "NO_PRIOR_MEETING":
        f.append(f"a REVERSED matchup was matched against the original orientation: {v}")
    # batch screening partitions
    acc, ref = screen([
        {"away": "NYM", "home": "CWS", "date": "2026-08-22", "away_score": 4, "home_score": 6},
        {"away": "TOR", "home": "NYY", "date": "2026-08-22", "away_score": 4, "home_score": 3},
    ], rows=rows)
    if len(acc) != 1 or len(ref) != 1:
        f.append(f"batch screen did not partition: {len(acc)} accepted, {len(ref)} refused")
    if acc and acc[0]["away"] != "TOR":
        f.append("batch screen accepted the wrong claim")

    print("echo_gate selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("echo detection removed", "        if pa == int(away_score) and ph == int(home_score):", "        if False:"),
    ("echo check ignores the away score", "        if pa == int(away_score) and ph == int(home_score):",
     "        if ph == int(home_score):"),
    # NOT A MUTANT, and deliberately so. prior_results' `date < before_date` filter and _within's
    # `0 < days` bound BOTH exclude future dates, so neither is independently necessary and no
    # fixture can isolate one from the other. _within earns its place separately by enforcing the
    # 3-day window (proven by the "window widened" mutant above and the June fixture); the
    # prior_results filter is redundant defence kept on purpose. Lesson 23's corollary applies:
    # overlapping rules are redundancy, not weak fixtures, and where no case can isolate a rule the
    # honest move is to SAY SO rather than invent a mutant that appears to kill.
    ("prior lookup ignores matchup orientation",
     '            if r.get("away") == away and r.get("home") == home',
     '            if {r.get("away"), r.get("home")} == {away, home}'),
    ("window widened so any historical repeat is an echo", "    return 0 < (b - a).days <= days", "    return True"),
    ("non-final rows counted as prior results",
     '            and str(r.get("status", "")).lower() == "final"', "            and True"),
    ("refusal downgraded to a verdict of falsehood",
     "REFUSED PENDING INDEPENDENT CONFIRMATION", "THIS RESULT IS DEFINITELY FALSE"),
    ("batch screen puts refusals in the accepted list", "        (acc if ok else ref).append", "        (acc).append"),
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
