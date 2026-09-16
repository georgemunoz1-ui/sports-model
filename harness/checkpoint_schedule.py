"""The v1.0 mandatory acquisition schedule and its escalation ladder.

WHY A SCHEDULE AT ALL. The failure this replaces is not "we could not get the data". It is
"we discovered at decision time that we did not have it". A checkpoint schedule turns a missing
field from a surprise into a work item with a deadline and an owner, and it is the difference
between an acquisition incident and a slate of blocked rows.

Every checkpoint is a DEADLINE, not a suggestion. A checkpoint that has passed with its work
undone is OVERDUE, and an OVERDUE checkpoint at T-5 is a SYSTEM_FAILURE, not a PASS.

The escalation ladder in section 10 is deliberately front-loaded: alternate-source search starts at
T-90, not at T-5. By the time the board freezes, every automatic remedy has already been tried.
"""

MODULE_ID = "checkpoint_schedule"

import sys

#: (name, minutes before first pitch, work, escalation that fires AT this checkpoint)
CHECKPOINTS = (
    ("T_MINUS_24H", 1440, "schedule, official game IDs, start times, venues, cohort population",
     None),
    ("T_MINUS_6H", 360, "starters, roster status, injuries, expected lineups, weather, initial "
                        "market board", None),
    ("T_MINUS_90M", 90, "refresh all material inputs; identify unresolved statuses",
     "ALTERNATE_SOURCE_SEARCH_BEGINS"),
    ("T_MINUS_45M", 45, "official/team injury reports, active rosters, lineup announcements",
     "RECHECK_TEAM_PAGES_STATUS_POSTS_LEAGUE_FEEDS"),
    ("T_MINUS_20M", 20, "generate replacement forecasts from newly confirmed information",
     "ACTIVATE_REGISTERED_FALLBACK_OR_REPLACEMENT"),
    ("T_MINUS_10M", 10, "refresh same-book moneyline, spread and total; validate market phase",
     "OPEN_ACQUISITION_INCIDENT_FOR_ANY_UNRESOLVED_FIELD"),
    ("T_MINUS_5M", 5, "freeze the final decision board; remotely anchor model, input and cohort "
                      "hashes", "MUST_EMIT_BET_PASS_OR_SYSTEM_FAILURE"),
    ("PRE_EXECUTION", 0, "fresh quote from the selected book; verify max/min playable price", None),
)
NAMES = tuple(c for c, _, _, _ in CHECKPOINTS)
OFFSETS = {c: m for c, m, _, _ in CHECKPOINTS}
ESCALATIONS = {c: e for c, _, _, e in CHECKPOINTS if e}

#: the final post-lineup refresh is mandatory in every sport, whatever else a league's calendar
#: forces us to move. Section 3's one non-negotiable.
MANDATORY_ALWAYS = "T_MINUS_45M"

PENDING = "PENDING"
DONE = "DONE"
OVERDUE = "OVERDUE"
SYSTEM_FAILURE = "SYSTEM_FAILURE"
READY = "CHECKPOINTS_SATISFIED"

#: the internal work-queue conditions from section 1. None of these may be a FINAL decision.
WORK_QUEUE_CONDITIONS = (
    "BLOCKED_INFORMATION_UNAVAILABLE", "PERSONNEL_UNVERIFIED", "PRICE_MISSING",
    "STARTER_UNCONFIRMED", "UNCERTAINTY_PIPELINE_DEFECT", "LINEUP_UNAVAILABLE",
    "SLATE_UNAVAILABLE", "SOURCE_ARTIFACT_NOT_RETAINED", "PRICE_STALE",
)


def is_work_queue(condition):
    """True when a condition is an internal work item rather than a fact about the game."""
    return str(condition) in WORK_QUEUE_CONDITIONS


def adjust(sport_overrides=None):
    """A sport may shift its checkpoints; it may never drop the final post-lineup refresh."""
    out = dict(OFFSETS)
    for k, v in (sport_overrides or {}).items():
        if k not in OFFSETS:
            return None, f"UNKNOWN_CHECKPOINT: {k}"
        if v is None:
            if k == MANDATORY_ALWAYS:
                return None, (f"REFUSED_CANNOT_DROP_{MANDATORY_ALWAYS}: the final post-lineup "
                              f"refresh is mandatory in every sport")
            return None, f"REFUSED_CANNOT_DROP_CHECKPOINT: {k}"
        out[k] = int(v)
    if MANDATORY_ALWAYS not in out:
        return None, f"REFUSED_CANNOT_DROP_{MANDATORY_ALWAYS}"
    return out, None


def status(minutes_to_start, completed, offsets=None):
    """Grade the schedule at a moment. `completed`: set of checkpoint names already done."""
    offsets = offsets or OFFSETS
    completed = set(completed or ())
    rows, overdue = [], []
    for name in NAMES:
        due = offsets.get(name, OFFSETS[name])
        if name in completed:
            st = DONE
        elif minutes_to_start <= due:
            st = OVERDUE
            overdue.append(name)
        else:
            st = PENDING
        rows.append({"checkpoint": name, "due_minutes_before_start": due, "status": st,
                     "escalation": ESCALATIONS.get(name)})
    fired = [ESCALATIONS[n] for n in NAMES
             if n in ESCALATIONS and minutes_to_start <= offsets.get(n, OFFSETS[n])]
    past_freeze = minutes_to_start <= offsets.get("T_MINUS_5M", 5)
    return {
        "minutes_to_start": minutes_to_start,
        "checkpoints": rows,
        "overdue": overdue,
        "escalations_fired": fired,
        "past_freeze": past_freeze,
        "status": (SYSTEM_FAILURE if (past_freeze and overdue) else
                   READY if not overdue else OVERDUE),
        "note": ("a checkpoint overdue at the freeze is a SYSTEM_FAILURE, which is an incident with "
                 "a named responsible subsystem — never a PASS, and never model conservatism"
                 if past_freeze and overdue else None),
    }


def incident(missing_field, routes_attempted, errors, last_successful_artifact, subsystem,
             remediation):
    """The section 10 SYSTEM_FAILURE record. Every field is required; none defaults to None."""
    rec = {"kind": SYSTEM_FAILURE, "missing_field": missing_field,
           "routes_attempted": list(routes_attempted or []), "errors": list(errors or []),
           "last_successful_artifact": last_successful_artifact,
           "responsible_subsystem": subsystem,
           "remediation_required_before_next_slate": remediation,
           "not_an_acceptable_normal_result": True}
    missing = [k for k in ("missing_field", "routes_attempted", "errors", "responsible_subsystem",
                           "remediation_required_before_next_slate") if not rec[k]]
    if missing:
        return None, f"INCOMPLETE_INCIDENT_RECORD: {missing}"
    return rec, None


# =================================================================================================
def selftest():
    f = []
    if len(CHECKPOINTS) != 8:
        f.append("v1.0 defines eight checkpoints")
    for n in ("T_MINUS_24H", "T_MINUS_6H", "T_MINUS_90M", "T_MINUS_45M", "T_MINUS_20M",
              "T_MINUS_10M", "T_MINUS_5M", "PRE_EXECUTION"):
        if n not in NAMES:
            f.append(f"{n} must be a checkpoint")
    if list(OFFSETS[n] for n in NAMES) != sorted((OFFSETS[n] for n in NAMES), reverse=True):
        f.append("checkpoints must be ordered from earliest to latest")

    # the escalation ladder fires in order, and starts long before the freeze
    for mins, expect in ((120, []), (90, ["ALTERNATE_SOURCE_SEARCH_BEGINS"]),
                         (45, ["ALTERNATE_SOURCE_SEARCH_BEGINS",
                               "RECHECK_TEAM_PAGES_STATUS_POSTS_LEAGUE_FEEDS"])):
        got = status(mins, set())["escalations_fired"]
        if got != expect:
            f.append(f"at T-{mins} escalations must be {expect}, got {got}")
    at5 = status(5, set())["escalations_fired"]
    for e in ("ALTERNATE_SOURCE_SEARCH_BEGINS", "RECHECK_TEAM_PAGES_STATUS_POSTS_LEAGUE_FEEDS",
              "ACTIVATE_REGISTERED_FALLBACK_OR_REPLACEMENT",
              "OPEN_ACQUISITION_INCIDENT_FOR_ANY_UNRESOLVED_FIELD",
              "MUST_EMIT_BET_PASS_OR_SYSTEM_FAILURE"):
        if e not in at5:
            f.append(f"{e} must have fired by the freeze")

    # everything done on time is READY
    allc = set(NAMES)
    if status(5, allc)["status"] != READY:
        f.append("a fully completed schedule is READY")
    # ...and an overdue checkpoint AT the freeze is a SYSTEM_FAILURE, not a pass
    late = status(4, allc - {"T_MINUS_45M"})
    if late["status"] != SYSTEM_FAILURE:
        f.append(f"an overdue checkpoint past the freeze must be SYSTEM_FAILURE, got {late['status']}")
    if "T_MINUS_45M" not in late["overdue"]:
        f.append("the overdue checkpoint must be named")
    if "never a PASS" not in (late["note"] or ""):
        f.append("the failure note must say it is not a PASS")
    # before the freeze the same gap is merely OVERDUE — recoverable, not terminal
    early = status(30, allc - {"T_MINUS_45M"})
    if early["status"] != OVERDUE:
        f.append(f"an overdue checkpoint before the freeze is OVERDUE, got {early['status']}")
    if early["status"] == late["status"]:
        f.append("recoverable and terminal lateness must be distinguishable")

    # THE SECTION 1 RULE: work-queue conditions are not decisions
    for c in ("BLOCKED_INFORMATION_UNAVAILABLE", "PERSONNEL_UNVERIFIED", "PRICE_MISSING",
              "STARTER_UNCONFIRMED", "UNCERTAINTY_PIPELINE_DEFECT"):
        if not is_work_queue(c):
            f.append(f"{c} must be classified as an internal work queue, not a decision")
    for c in ("BET", "PASS", "GAME_ALREADY_LIVE"):
        if is_work_queue(c):
            f.append(f"{c} must NOT be a work-queue condition")

    # a sport may move a checkpoint but never drop the post-lineup refresh
    moved, err = adjust({"T_MINUS_6H": 300})
    if err or moved["T_MINUS_6H"] != 300:
        f.append(f"a sport must be able to move a checkpoint, got {err}")
    dropped, err2 = adjust({"T_MINUS_45M": None})
    if dropped is not None:
        f.append("the final post-lineup refresh may never be dropped")
    # ...and it must refuse with its OWN code. A generic "cannot drop a checkpoint" would also
    # refuse here, which would let the mandatory-always guard be deleted without any fixture
    # noticing — the guard would be decorative and the message would cover for it.
    elif f"REFUSED_CANNOT_DROP_{MANDATORY_ALWAYS}" not in (err2 or ""):
        f.append(f"dropping {MANDATORY_ALWAYS} must fire its own guard, got {err2}")
    other, err2b = adjust({"T_MINUS_6H": None})
    if other is not None or "REFUSED_CANNOT_DROP_CHECKPOINT" not in (err2b or ""):
        f.append("dropping any other checkpoint refuses under the generic code")
    if err2 == err2b:
        f.append("the mandatory refusal and the generic refusal must be distinguishable")
    _, err3 = adjust({"NOT_A_CHECKPOINT": 5})
    if not err3:
        f.append("an unknown checkpoint must be refused")

    # an incident record must be complete
    ok, e = incident("starter", ["OFFICIAL_API"], ["EGRESS_BLOCKED"], "sha:abc", "acquisition",
                     "restore egress or register a relay")
    if e or not ok:
        f.append(f"a complete incident must be accepted, got {e}")
    for kw in ({"missing_field": ""}, {"routes_attempted": []}, {"errors": []},
               {"subsystem": None}, {"remediation": None}):
        args = dict(missing_field="starter", routes_attempted=["OFFICIAL_API"],
                    errors=["EGRESS_BLOCKED"], last_successful_artifact="sha:abc",
                    subsystem="acquisition", remediation="restore egress")
        args.update(kw)
        bad, e2 = incident(**args)
        if bad is not None or not e2:
            f.append(f"an incomplete incident must be refused: {kw}")

    print("checkpoint_schedule selftest:", "OK" if not f else "FAIL")
    for x in f:
        print("   -", x)
    return not f


MUTANTS = [
    ("an overdue checkpoint past the freeze becomes an ordinary result",
     '        "status": (SYSTEM_FAILURE if (past_freeze and overdue) else',
     '        "status": (READY if (past_freeze and overdue) else'),
    ("alternate-source search is delayed until the freeze",
     '    ("T_MINUS_90M", 90, "refresh all material inputs; identify unresolved statuses",\n     "ALTERNATE_SOURCE_SEARCH_BEGINS"),',
     '    ("T_MINUS_90M", 90, "refresh all material inputs; identify unresolved statuses",\n     None),'),
    ("the fallback escalation never fires",
     '"ACTIVATE_REGISTERED_FALLBACK_OR_REPLACEMENT"', 'None'),
    ("the mandatory post-lineup refresh becomes droppable",
     '            if k == MANDATORY_ALWAYS:', "            if False:"),
    ("the uncertainty defect stops being an internal work queue",
     '"STARTER_UNCONFIRMED", "UNCERTAINTY_PIPELINE_DEFECT", "LINEUP_UNAVAILABLE",',
     '"STARTER_UNCONFIRMED", "LINEUP_UNAVAILABLE",'),
    ("a missing price stops being an internal work queue",
     '"BLOCKED_INFORMATION_UNAVAILABLE", "PERSONNEL_UNVERIFIED", "PRICE_MISSING",',
     '"BLOCKED_INFORMATION_UNAVAILABLE", "PERSONNEL_UNVERIFIED",'),
    ("an incomplete incident record is accepted",
     '    if missing:\n        return None, f"INCOMPLETE_INCIDENT_RECORD: {missing}"', "    pass"),
    ("recoverable lateness and terminal lateness collapse",
     'OVERDUE = "OVERDUE"', 'OVERDUE = "SYSTEM_FAILURE"'),
    ("the failure note stops saying it is not a PASS",
     '"a checkpoint overdue at the freeze is a SYSTEM_FAILURE, which is an incident with "\n                 "a named responsible subsystem — never a PASS, and never model conservatism"',
     '"late"'),
    ("a checkpoint stops being overdue when its deadline passes",
     "        elif minutes_to_start <= due:", "        elif False:"),
]


def mutation_suite():
    src = open(__file__).read()
    # BASELINE FIRST. A failing selftest makes every mutant look killed, so a broken fixture reports
    # a perfect score. Caught 2026-08-25 when module_manifest printed 11/11 while its own selftest
    # was failing.
    import io as _io, contextlib as _cl
    _b = _io.StringIO()
    with _cl.redirect_stdout(_b):
        _base = selftest()
    if not _base:
        print("  BASELINE_FAILING  the unmutated selftest does not pass; every 'kill' below is "
              "meaningless until it does")
        print(_b.getvalue().strip())
        return False
    # a mutant whose pattern occurs only inside the MUTANTS literal edits its OWN definition,
    # applies cleanly, changes no behaviour and reports SURVIVED. Caught 2026-08-25 after a rename.
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
