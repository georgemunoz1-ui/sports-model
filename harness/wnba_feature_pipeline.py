#!/usr/bin/env python3
"""WNBA FEATURE PIPELINE — staleness is a job, and an exhausted job is a SYSTEM FAILURE.

Owner correction, 2026-08-25: the WNBA feature state aged from 33 to 34 days while the page kept
describing what someone should eventually do — a blocker-REPORTING loop where a blocker-RESOLUTION
pipeline belongs. Three rules make that structurally impossible:

1. PENDING_FEATURE_REFRESH is not a terminal game disposition. A game ends BET, PASS, a named
   exception, or SYSTEM_FAILURE — "we should refresh" ends nothing.
2. Stale features LAUNCH a recovery job covering all five components below, before the slate.
   Prose does not discharge the obligation; a registered job with measurable units does.
3. When every authorized route is exhausted and nothing bound, the board publishes
   SYSTEM_FAILURE_WNBA_FEATURE_PIPELINE — never a normal-looking board with blocked rows.

Search snippets identify and never bind (standing rule: snippets are not canonical evidence).
A unit binds only from a retrieved artifact with a source, a timestamp and a content hash.
"""
from __future__ import annotations

import sys

MODULE_ID = "wnba_feature_pipeline"

COMPONENTS = (
    "SCHEDULE_AND_CANONICAL_GAME_IDS",
    "ROSTERS_AND_TRANSACTIONS",
    "OFFICIAL_INJURY_AVAILABILITY",
    "RESULTS_AND_STATS_THROUGH_ASOF",
    "MARKET_PRICES_VIA_SEPARATE_OVERLAY",
)

#: registered policy v1: features older than this at board-build time REQUIRE an active job
STALENESS_THRESHOLD_DAYS = 2

SYSTEM_FAILURE = "SYSTEM_FAILURE_WNBA_FEATURE_PIPELINE"

OK = "FEATURE_PIPELINE_OK"
REFUSED = "FEATURE_PIPELINE_REFUSED"

STALE_WITHOUT_ACTIVE_JOB = "STALE_FEATURES_WITHOUT_ACTIVE_REFRESH_JOB"
JOB_MISSING_COMPONENT = "REFRESH_JOB_MISSING_COMPONENT"
TERMINAL_PENDING = "PENDING_FEATURE_REFRESH_AS_TERMINAL_DISPOSITION"
SNIPPET_NOT_CANONICAL = "SNIPPET_SOURCE_CANNOT_BIND_A_UNIT"
ROUTES_NOT_EXHAUSTED = "AUTHORIZED_ROUTES_REMAIN_UNTRIED"
FAILURE_WITHOUT_EXHAUSTION = "SYSTEM_FAILURE_DECLARED_BEFORE_EXHAUSTION"

#: every authorized rung for this pipeline; owner relay is always last and always authorized
AUTHORIZED_ROUTES = ("OFFICIAL_API", "OFFICIAL_SITE", "NAMED_AGGREGATOR_FETCH",
                     "SEARCH_IDENTIFICATION", "OWNER_RELAY")


def staleness_gate(feature_age_days, jobs):
    """Features older than the threshold require an ACTIVE job covering all five components.
    jobs: iterable of {"components": [...], "status": ...}; terminal/complete jobs don't count."""
    if feature_age_days <= STALENESS_THRESHOLD_DAYS:
        return {"status": OK, "problems": []}
    problems = []
    active = [j for j in (jobs or [])
              if j.get("status") not in ("COMPLETE", "FAILED_TERMINAL")]
    if not active:
        problems.append({"code": STALE_WITHOUT_ACTIVE_JOB,
                         "age_days": feature_age_days,
                         "threshold": STALENESS_THRESHOLD_DAYS})
    else:
        covered = set()
        for j in active:
            covered |= set(j.get("components") or [])
        missing = [c for c in COMPONENTS if c not in covered]
        if missing:
            problems.append({"code": JOB_MISSING_COMPONENT, "missing": missing})
    return {"status": OK if not problems else REFUSED, "problems": problems}


def disposition_gate(disposition):
    """PENDING_FEATURE_REFRESH may appear only as a work-queue condition, never as what a game
    row ends with."""
    if "PENDING_FEATURE_REFRESH" in str(disposition):
        return {"status": REFUSED, "problems": [{"code": TERMINAL_PENDING,
                                                 "disposition": disposition}]}
    return {"status": OK, "problems": []}


def bind_unit(source_route, artifact_hash, retrieved_utc):
    """A unit binds from a retrieved artifact only. Search snippets identify; they never bind."""
    if source_route == "SEARCH_IDENTIFICATION":
        return None, SNIPPET_NOT_CANONICAL
    if not (artifact_hash and retrieved_utc):
        return None, "UNIT_WITHOUT_ARTIFACT_HASH_OR_TIMESTAMP"
    return {"route": source_route, "artifact_hash": artifact_hash,
            "retrieved_utc": retrieved_utc}, None


def exhaustion(attempts):
    """attempts: {route: outcome}. SYSTEM_FAILURE publication becomes REQUIRED when every
    authorized route was attempted and none bound; it is FORBIDDEN while any route is untried.
    SEARCH_IDENTIFICATION succeeding changes nothing — identification is not binding."""
    untried = [r for r in AUTHORIZED_ROUTES if r not in (attempts or {})]
    if untried:
        return {"publication_required": False, "publication_allowed": False,
                "problems": [{"code": ROUTES_NOT_EXHAUSTED, "untried": untried}]}
    bound = [r for r, o in attempts.items()
             if o == "BOUND" and r != "SEARCH_IDENTIFICATION"]
    if bound:
        return {"publication_required": False, "publication_allowed": False,
                "problems": [], "bound_routes": bound}
    return {"publication_required": True, "publication_allowed": True,
            "publication": SYSTEM_FAILURE, "problems": []}


# =================================================================================================
def selftest():
    f = []
    if len(COMPONENTS) != 5:
        f.append("the pipeline has exactly five components")

    fresh = staleness_gate(1, [])
    if fresh["status"] != OK:
        f.append("fresh features need no job")
    stale_nojob = staleness_gate(34, [])
    if stale_nojob["status"] != REFUSED or stale_nojob["problems"][0]["code"] != STALE_WITHOUT_ACTIVE_JOB:
        f.append(f"34-day features with no job must refuse, got {stale_nojob}")
    stale_closed = staleness_gate(34, [{"components": list(COMPONENTS), "status": "FAILED_TERMINAL"}])
    if stale_closed["status"] != REFUSED:
        f.append("a terminally-closed job does not discharge the staleness obligation")
    stale_partial = staleness_gate(34, [{"components": ["OFFICIAL_INJURY_AVAILABILITY"],
                                         "status": "BLOCKED_EXTERNAL"}])
    if stale_partial["status"] != REFUSED or stale_partial["problems"][0]["code"] != JOB_MISSING_COMPONENT:
        f.append(f"an injuries-only job must be refused as missing components, got {stale_partial}")
    stale_full = staleness_gate(34, [{"components": list(COMPONENTS), "status": "BLOCKED_EXTERNAL"}])
    if stale_full["status"] != OK:
        f.append(f"an active five-component job satisfies the launch rule, got {stale_full}")

    d = disposition_gate("PENDING_FEATURE_REFRESH")
    if d["status"] != REFUSED or d["problems"][0]["code"] != TERMINAL_PENDING:
        f.append("PENDING_FEATURE_REFRESH must be refused as a game disposition")
    if disposition_gate(SYSTEM_FAILURE)["status"] != OK:
        f.append("a published system failure IS a valid way for a game row to end")

    u, err = bind_unit("SEARCH_IDENTIFICATION", "abc123", "2026-08-25T22:00:00Z")
    if u is not None or err != SNIPPET_NOT_CANONICAL:
        f.append("a search snippet must never bind a unit")
    u, err = bind_unit("OFFICIAL_SITE", None, "2026-08-25T22:00:00Z")
    if u is not None:
        f.append("a unit without an artifact hash must not bind")
    u, err = bind_unit("OFFICIAL_SITE", "abc123", "2026-08-25T22:00:00Z")
    if err or u["artifact_hash"] != "abc123":
        f.append("an official artifact with hash and timestamp binds")

    partial = exhaustion({"OFFICIAL_SITE": "EGRESS_BLOCKED"})
    if partial["publication_allowed"] or partial["problems"][0]["code"] != ROUTES_NOT_EXHAUSTED:
        f.append("SYSTEM_FAILURE is forbidden while authorized routes are untried")
    full = exhaustion({"OFFICIAL_API": "EGRESS_BLOCKED", "OFFICIAL_SITE": "EGRESS_BLOCKED",
                       "NAMED_AGGREGATOR_FETCH": "EGRESS_BLOCKED",
                       "SEARCH_IDENTIFICATION": "IDENTIFIED_ONLY",
                       "OWNER_RELAY": "NOTHING_RELAYED"})
    if not full["publication_required"] or full.get("publication") != SYSTEM_FAILURE:
        f.append(f"full exhaustion REQUIRES the system-failure publication, got {full}")
    snips = exhaustion({"OFFICIAL_API": "EGRESS_BLOCKED", "OFFICIAL_SITE": "EGRESS_BLOCKED",
                        "NAMED_AGGREGATOR_FETCH": "EGRESS_BLOCKED",
                        "SEARCH_IDENTIFICATION": "BOUND",
                        "OWNER_RELAY": "NOTHING_RELAYED"})
    if not snips["publication_required"]:
        f.append("a 'BOUND' search snippet is still not a binding — exhaustion stands")
    relayed = exhaustion({"OFFICIAL_API": "EGRESS_BLOCKED", "OFFICIAL_SITE": "EGRESS_BLOCKED",
                          "NAMED_AGGREGATOR_FETCH": "EGRESS_BLOCKED",
                          "SEARCH_IDENTIFICATION": "IDENTIFIED_ONLY",
                          "OWNER_RELAY": "BOUND"})
    if relayed["publication_required"] or not relayed.get("bound_routes"):
        f.append("an owner-relayed binding averts the system failure")

    print("wnba_feature_pipeline selftest:", "OK" if not f else "FAIL")
    for x in f:
        print("   -", x)
    return not f


MUTANTS = [
    ("stale features stop requiring a job",
     "    if feature_age_days <= STALENESS_THRESHOLD_DAYS:",
     "    if True:"),
    ("the staleness threshold grows until 34 days is fresh",
     "STALENESS_THRESHOLD_DAYS = 2",
     "STALENESS_THRESHOLD_DAYS = 60"),
    ("a closed job satisfies the launch rule forever",
     '              if j.get("status") not in ("COMPLETE", "FAILED_TERMINAL")]',
     "              ]"),
    ("an injuries-only job counts as full coverage",
     "        missing = [c for c in COMPONENTS if c not in covered]",
     "        missing = []"),
    ("PENDING_FEATURE_REFRESH becomes a legal game ending",
     '    if "PENDING_FEATURE_REFRESH" in str(disposition):',
     "    if False:"),
    ("search snippets start binding units",
     '    if source_route == "SEARCH_IDENTIFICATION":',
     "    if False:"),
    ("SYSTEM_FAILURE publishes before routes are exhausted",
     "    if untried:",
     "    if False:"),
    ("a snippet 'binding' averts the system failure",
     '             if o == "BOUND" and r != "SEARCH_IDENTIFICATION"]',
     '             if o == "BOUND"]'),
]


def mutation_suite():
    src = open(__file__).read()
    import io as _io, contextlib as _cl
    _b = _io.StringIO()
    with _cl.redirect_stdout(_b):
        _base = selftest()
    if not _base:
        print("  BASELINE_FAILING  the unmutated selftest does not pass")
        print(_b.getvalue().strip())
        return False
    body = src[:src.index("MUTANTS = [")]
    killed = 0
    for name, old, new in MUTANTS:
        if old not in src:
            print("  UNAPPLIED ", name + ": pattern not found")
            continue
        if old not in body:
            print("  SELF_TARGETED ", name + ": pattern occurs only inside the MUTANTS list")
            continue
        ns = {"__file__": __file__, "__name__": "mutant"}
        try:
            exec(compile(src.replace(old, new, 1), "<mutant>", "exec"), ns)
            ok = ns["selftest"]()
        except Exception:
            ok = False
        print(("  KILLED    " if not ok else "  SURVIVED  ") + name)
        killed += not ok
    print(f"mutation suite: {killed}/{len(MUTANTS)} killed"
          + ("" if killed == len(MUTANTS) else "  — SURVIVORS MEAN DECORATIVE FIXTURES"))
    return killed == len(MUTANTS)


if __name__ == "__main__":
    if "--mutants" in sys.argv:
        sys.exit(0 if mutation_suite() else 1)
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    print(__doc__)
