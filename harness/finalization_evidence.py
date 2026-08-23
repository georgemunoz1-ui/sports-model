#!/usr/bin/env python3
"""FINALIZATION EVIDENCE — an observed timestamp, a derived bound, and the gap between them.

OWNER AMENDMENT 9 (2026-08-23): "Strengthen chronology proof. start time + 7 hours is a
conservative inference, not an observed finalization timestamp. Prefer official_finalized_utc <
training_cutoff_utc; exclude the result when finalization ordering cannot be proven."

WHAT THE BOUND IS AND IS NOT. `finalization_upper_bound` establishes an inequality: if the latest
instant a game could possibly have ended is still before the cutoff, the ordering holds however long
the game actually took. That is a proof — but a proof CONDITIONAL ON THE MAXIMUM. And the maximum is
an assumption, not a measured quantity: MAX_GAME_DURATION_HOURS["mlb"] = 7.0 is exceeded in reality
by extra-inning games, long rain delays and suspended-and-resumed games, any of which can push a
finalization past a seven-hour envelope. So a clearing bound is not the same evidence as a
timestamp, it can be WRONG in a way a timestamp cannot, and this module refuses to let the two share
a status.

THREE GRADES, AND THEY ARE NOT INTERCHANGEABLE:

  OBSERVED_TIER1     a finalization instant from a tier-1 source. The only unconditional evidence.
  OBSERVED_UNSOURCED a finalization instant with no source recorded. It is still a measurement and
                     still better than a bound, but it cannot populate a canonical result, because
                     an unsourced timestamp is exactly what tier discipline exists to keep out.
  DERIVED_UPPER_BOUND  start + registered maximum. Conditional on the maximum holding.

AND THE MARGIN IS REPORTED, ALWAYS. A bound that clears the cutoff by nineteen hours and one that
clears it by ninety seconds are both "OK by upper bound" and are not remotely the same claim. The
margin in hours travels with the verdict so a reader can see which one they have. A bound clearing
by less than the amount by which the assumption could be wrong is not reassuring.

EXCLUSION IS THE DEFAULT FOR THE UNPROVEN. Under the registered policy a result whose finalization
ordering cannot be established does not get to sit quietly in the prior pool contributing to p — it
is EXCLUDED, with a reason, and counted. The prior is then recomputed on the survivors and the
excluded count is reported beside it, because a prior silently built on 1808 games of which some
unknown number leak is not a prior anyone can check.

TWO POLICIES ARE REGISTERED, and the choice between them is the owner's, not this module's:
  PREFER_OBSERVED_EXCLUDE_UNPROVEN  observed included; a CLEARING bound included and flagged;
                                    anything else excluded.   (default)
  STRICT_OBSERVED_ONLY              only observed timestamps are admissible; every bound excluded.

API
  grade(finalized_at_utc, source, upper_bound_utc)  -> the evidence grade for one result
  ordering_proven(ev, cutoff_utc, policy)           -> (admissible, status, reason, margin_hours)
  partition_pool(rows, cutoff_utc, policy)          -> included / excluded, with reasons and counts
  bound_assumption_report()                         -> what the bound assumes and how it can fail
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

OBSERVED_TIER1 = "OBSERVED_TIER1"
OBSERVED_UNSOURCED = "OBSERVED_UNSOURCED"
DERIVED_BOUND = "DERIVED_UPPER_BOUND"
NO_EVIDENCE = "NO_FINALIZATION_EVIDENCE"

PROVEN_OBSERVED = "ORDERING_PROVEN_BY_OBSERVATION"
PROVEN_BY_BOUND = "ORDERING_PROVEN_CONDITIONAL_ON_DURATION_ASSUMPTION"
UNPROVEN = "ORDERING_UNPROVEN_EXCLUDE_RESULT"
REFUTED = "ORDERING_REFUTED_RESULT_NOT_FINAL_BEFORE_CUTOFF"

PREFER_OBSERVED = "PREFER_OBSERVED_EXCLUDE_UNPROVEN"
STRICT_OBSERVED = "STRICT_OBSERVED_ONLY"
POLICIES = (PREFER_OBSERVED, STRICT_OBSERVED)

# Sources that may carry a canonical finalization instant. Same list discipline as tier 1 evidence.
TIER1_FINALIZATION_SOURCES = ("MLB_STATSAPI_GAME_FINAL", "SAVANT_BOX_FINAL",
                              "WNBA_OFFICIAL_BOX_FINAL", "NFL_OFFICIAL_BOX_FINAL")

# The assumption the derived bound rests on, and the ways it is known to break.
BOUND_ASSUMPTION = {
    "assumption": "a game finishes within MAX_GAME_DURATION_HOURS of its scheduled start",
    "known_failure_modes": [
        "extra innings — a 15+ inning MLB game can exceed 7 hours of elapsed time",
        "rain or weather delay — suspends the clock without suspending the calendar",
        "suspended and resumed on a later date — finalization can post more than a day after start",
        "a start that was itself pushed back, so the recorded start instant is not the real one",
    ],
    "consequence": "a bound can be WRONG in a direction a timestamp cannot; it is never reported "
                   "under the same status as an observation",
}


def _parse(t):
    if not t or "T" not in str(t):
        return None
    try:
        return dt.datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def grade(finalized_at_utc=None, source=None, upper_bound_utc=None):
    """The evidence grade for ONE result's finalization instant."""
    if finalized_at_utc and _parse(finalized_at_utc) is not None:
        g = OBSERVED_TIER1 if source in TIER1_FINALIZATION_SOURCES else OBSERVED_UNSOURCED
        return {"grade": g, "instant": finalized_at_utc, "source": source,
                "conditional": False}
    if finalized_at_utc:
        return {"grade": NO_EVIDENCE, "instant": None, "source": source, "conditional": None,
                "reason": f"unparseable or calendar-only finalization value {finalized_at_utc!r}"}
    if upper_bound_utc and _parse(upper_bound_utc) is not None:
        return {"grade": DERIVED_BOUND, "instant": upper_bound_utc, "source": "DERIVED",
                "conditional": True, "assumption": BOUND_ASSUMPTION["assumption"]}
    return {"grade": NO_EVIDENCE, "instant": None, "source": source, "conditional": None,
            "reason": "no finalization instant and no derivable bound"}


def ordering_proven(ev, cutoff_utc, policy=PREFER_OBSERVED):
    """Is `instant < cutoff` PROVEN, under the named policy? Margin always reported."""
    if policy not in POLICIES:
        raise ValueError(f"unregistered policy {policy!r}")
    cut = _parse(cutoff_utc)
    if cut is None:
        return {"admissible": False, "status": UNPROVEN, "margin_hours": None,
                "reason": f"cutoff {cutoff_utc!r} is not an instant"}
    inst = _parse(ev.get("instant"))
    if inst is None:
        return {"admissible": False, "status": UNPROVEN, "margin_hours": None,
                "reason": ev.get("reason") or "no finalization instant"}
    margin = (cut - inst).total_seconds() / 3600.0
    if not (inst < cut):
        return {"admissible": False, "status": REFUTED, "margin_hours": margin,
                "reason": f"{ev['grade']} {ev['instant']} is at or after cutoff {cutoff_utc}"}
    if ev["grade"] == DERIVED_BOUND:
        if policy == STRICT_OBSERVED:
            return {"admissible": False, "status": UNPROVEN, "margin_hours": margin,
                    "reason": "policy STRICT_OBSERVED_ONLY admits no derived bound"}
        return {"admissible": True, "status": PROVEN_BY_BOUND, "margin_hours": margin,
                "conditional_on": BOUND_ASSUMPTION["assumption"]}
    return {"admissible": True, "status": PROVEN_OBSERVED, "margin_hours": margin,
            "evidence_grade": ev["grade"]}


def partition_pool(rows, cutoff_utc, policy=PREFER_OBSERVED):
    """Split a prior pool into what may contribute and what is excluded, with reasons and counts.

    row: {"game_id", "finalized_at_utc"?, "finalization_source"?, "finalized_upper_bound_utc"?, ...}
    """
    included, excluded = [], []
    by_status = {}
    for r in rows:
        ev = grade(r.get("finalized_at_utc"), r.get("finalization_source"),
                   r.get("finalized_upper_bound_utc"))
        ver = ordering_proven(ev, cutoff_utc, policy)
        by_status[ver["status"]] = by_status.get(ver["status"], 0) + 1
        rec = dict(r, finalization_evidence=ev["grade"], ordering_status=ver["status"],
                   margin_hours=ver["margin_hours"], reason=ver.get("reason"))
        (included if ver["admissible"] else excluded).append(rec)
    bounds = [r for r in included if r["finalization_evidence"] == DERIVED_BOUND]
    margins = [r["margin_hours"] for r in bounds if r["margin_hours"] is not None]
    return {
        "policy": policy,
        "cutoff_utc": cutoff_utc,
        "n_in": len(rows),
        "n_included": len(included),
        "n_excluded": len(excluded),
        "by_status": by_status,
        "n_included_on_a_derived_bound": len(bounds),
        "smallest_bound_margin_hours": min(margins) if margins else None,
        "included": included,
        "excluded": excluded,
        "note": "a prior whose pool was filtered must report the excluded count beside p and n; a "
                "count that is not reported cannot be checked",
    }


def bound_assumption_report():
    return dict(BOUND_ASSUMPTION, tier1_sources=list(TIER1_FINALIZATION_SOURCES),
                policies=list(POLICIES), default_policy=PREFER_OBSERVED)


# =================================================================================================
def selftest():
    f = []
    CUT = "2026-08-23T00:00:00Z"

    # --- grading ----------------------------------------------------------------------------------
    g1 = grade("2026-08-22T02:41:00Z", "MLB_STATSAPI_GAME_FINAL")
    if g1["grade"] != OBSERVED_TIER1 or g1["conditional"]:
        f.append("a tier-1 sourced timestamp is unconditional observed evidence")
    g2 = grade("2026-08-22T02:41:00Z", None)
    if g2["grade"] != OBSERVED_UNSOURCED:
        f.append("an unsourced timestamp is observed but not tier 1")
    g3 = grade(None, None, "2026-08-22T09:10:00Z")
    if g3["grade"] != DERIVED_BOUND or not g3["conditional"]:
        f.append("a bound must be graded as derived and marked conditional")
    if grade(None, None, None)["grade"] != NO_EVIDENCE:
        f.append("nothing at all is no evidence")
    # a calendar date is not an instant — the defect this whole rule exists for
    if grade("2026-08-22", "MLB_STATSAPI_GAME_FINAL")["grade"] != NO_EVIDENCE:
        f.append("a calendar date must not be accepted as a finalization instant")
    if grade(None, None, "2026-08-22")["grade"] != NO_EVIDENCE:
        f.append("a calendar-date bound is not a bound")

    # --- the preference the amendment asks for ----------------------------------------------------
    o = ordering_proven(g1, CUT)
    if o["status"] != PROVEN_OBSERVED or not o["admissible"]:
        f.append("an observed timestamp before the cutoff proves the ordering")
    b = ordering_proven(g3, CUT)
    if b["status"] != PROVEN_BY_BOUND or not b["admissible"]:
        f.append("a clearing bound proves the ordering, conditionally")
    if b["status"] == o["status"]:
        f.append("a bound and an observation must NOT share a status")
    if "conditional_on" not in b:
        f.append("the bound verdict must name the assumption it rests on")
    # the margin distinguishes a comfortable bound from a hairline one
    if abs(o["margin_hours"] - 21.3167) > 1e-3:
        f.append(f"margin must be reported in hours, got {o['margin_hours']}")
    hair = ordering_proven(grade(None, None, "2026-08-22T23:58:30Z"), CUT)
    if abs(hair["margin_hours"] - 0.025) > 1e-6:
        f.append(f"a hairline bound must report its tiny margin, got {hair['margin_hours']}")
    if hair["margin_hours"] >= b["margin_hours"]:
        f.append("fixture is wrong: the hairline bound should have the smaller margin")

    # --- exclusion --------------------------------------------------------------------------------
    late = ordering_proven(grade("2026-08-23T01:00:00Z", "MLB_STATSAPI_GAME_FINAL"), CUT)
    if late["admissible"] or late["status"] != REFUTED:
        f.append("a result finalized after the cutoff must be refuted and excluded")
    none_ev = ordering_proven(grade(None, None, None), CUT)
    if none_ev["admissible"] or none_ev["status"] != UNPROVEN:
        f.append("no evidence must exclude the result")
    if ordering_proven(g1, "2026-08-23")["admissible"]:
        f.append("a calendar-date cutoff proves nothing")
    # exactly AT the cutoff is not before it: the ordering the rule needs is strict
    tie = ordering_proven(grade(CUT, "MLB_STATSAPI_GAME_FINAL"), CUT)
    if tie["admissible"] or tie["status"] != REFUTED:
        f.append("a result finalized exactly at the cutoff must be refuted, not admitted")

    # --- policy -----------------------------------------------------------------------------------
    strict = ordering_proven(g3, CUT, STRICT_OBSERVED)
    if strict["admissible"] or strict["status"] != UNPROVEN:
        f.append("STRICT_OBSERVED_ONLY must exclude a derived bound")
    if not ordering_proven(g1, CUT, STRICT_OBSERVED)["admissible"]:
        f.append("STRICT_OBSERVED_ONLY still admits an observed timestamp")
    try:
        ordering_proven(g1, CUT, "WHATEVER_I_LIKE")
        f.append("an unregistered policy must raise")
    except ValueError:
        pass

    # --- the pool ---------------------------------------------------------------------------------
    rows = [
        {"game_id": "A", "finalized_at_utc": "2026-08-22T02:41:00Z",
         "finalization_source": "MLB_STATSAPI_GAME_FINAL"},
        {"game_id": "B", "finalized_upper_bound_utc": "2026-08-22T09:10:00Z"},
        {"game_id": "C", "finalized_upper_bound_utc": "2026-08-22T23:58:30Z"},
        {"game_id": "D"},
        {"game_id": "E", "finalized_at_utc": "2026-08-23T01:00:00Z",
         "finalization_source": "MLB_STATSAPI_GAME_FINAL"},
    ]
    p = partition_pool(rows, CUT)
    if p["n_included"] != 3 or p["n_excluded"] != 2:
        f.append(f"three admissible and two excluded, got {p['n_included']}/{p['n_excluded']}")
    if p["n_included_on_a_derived_bound"] != 2:
        f.append("the count leaning on a bound must be reported separately")
    if abs(p["smallest_bound_margin_hours"] - 0.025) > 1e-6:
        f.append("the tightest bound margin must be surfaced")
    if {r["game_id"] for r in p["excluded"]} != {"D", "E"}:
        f.append("the excluded rows must be the unproven and the refuted ones")
    if not all(r.get("reason") for r in p["excluded"]):
        f.append("every excluded row must carry a reason")
    ps = partition_pool(rows, CUT, STRICT_OBSERVED)
    if ps["n_included"] != 1 or ps["n_excluded"] != 4:
        f.append(f"under STRICT only the observed row survives, got {ps['n_included']}")
    if ps["n_included"] >= p["n_included"]:
        f.append("the strict policy must admit strictly fewer rows here")

    # --- the assumption is stated, not buried -----------------------------------------------------
    r = bound_assumption_report()
    if len(r["known_failure_modes"]) < 3 or r["default_policy"] != PREFER_OBSERVED:
        f.append("the bound's failure modes and default policy must be reported")
    modes = " ".join(r["known_failure_modes"]).lower()
    for must in ("extra inning", "delay", "suspend"):
        if must not in modes:
            f.append(f"the bound's failure modes must still name {must!r}")

    for x in f:
        print("FAIL:", x)
    if not f:
        print("finalization_evidence selftest: OK")
    return f


MUTANTS = [
    ("a derived bound is reported under the observed status",
     '        return {"admissible": True, "status": PROVEN_BY_BOUND, "margin_hours": margin,\n                "conditional_on": BOUND_ASSUMPTION["assumption"]}',
     '        return {"admissible": True, "status": PROVEN_OBSERVED, "margin_hours": margin,\n                "conditional_on": BOUND_ASSUMPTION["assumption"]}'),
    ("the bound stops naming the assumption it rests on",
     '                "conditional_on": BOUND_ASSUMPTION["assumption"]}', '                }'),
    ("an unsourced timestamp is promoted to tier 1",
     "        g = OBSERVED_TIER1 if source in TIER1_FINALIZATION_SOURCES else OBSERVED_UNSOURCED",
     "        g = OBSERVED_TIER1"),
    ("a calendar date is accepted as a finalization instant",
     '    if not t or "T" not in str(t):\n        return None', "    if not t:\n        return None"),
    ("a result finalized after the cutoff is admitted",
     "    if not (inst < cut):", "    if False:"),
    ("the ordering test becomes non-strict, so a tie at the cutoff passes",
     "    if not (inst < cut):", "    if not (inst <= cut):"),
    ("a result with no evidence is admitted",
     '        return {"admissible": False, "status": UNPROVEN, "margin_hours": None,\n                "reason": ev.get("reason") or "no finalization instant"}',
     '        return {"admissible": True, "status": UNPROVEN, "margin_hours": None,\n                "reason": ev.get("reason") or "no finalization instant"}'),
    ("the margin stops being reported",
     "    margin = (cut - inst).total_seconds() / 3600.0", "    margin = None"),
    ("the tightest bound margin is hidden",
     '        "smallest_bound_margin_hours": min(margins) if margins else None,',
     '        "smallest_bound_margin_hours": None,'),
    ("the count leaning on a bound is folded into the total",
     '        "n_included_on_a_derived_bound": len(bounds),', '        "n_included_on_a_derived_bound": 0,'),
    ("the strict policy stops excluding bounds",
     "        if policy == STRICT_OBSERVED:", "        if False:"),
    ("an unregistered policy is accepted",
     "    if policy not in POLICIES:", "    if False:"),
    ("excluded rows lose their reasons",
     '        rec = dict(r, finalization_evidence=ev["grade"], ordering_status=ver["status"],\n                   margin_hours=ver["margin_hours"], reason=ver.get("reason"))',
     '        rec = dict(r, finalization_evidence=ev["grade"], ordering_status=ver["status"],\n                   margin_hours=ver["margin_hours"], reason=None)'),
    ("a calendar-date cutoff is accepted",
     '    cut = _parse(cutoff_utc)\n    if cut is None:', "    cut = _parse(cutoff_utc)\n    if False:"),
    ("the bound's failure modes are emptied",
     '    "known_failure_modes": [\n        "extra innings — a 15+ inning MLB game can exceed 7 hours of elapsed time",',
     '    "known_failure_modes": [\n        "none known",'),
    ("everything is included regardless of the verdict",
     '        (included if ver["admissible"] else excluded).append(rec)', "        included.append(rec)"),
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
