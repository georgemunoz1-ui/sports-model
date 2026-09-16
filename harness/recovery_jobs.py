"""Executable recovery jobs. A job has an id, a next run, progress, a deadline and a disposition.

WHY THIS IS NOT PROSE. "Scheduled maintenance" in a journal entry is a sentence. It has no id, so
nothing can reference it; no next-run time, so nothing fires it; no progress, so nobody can tell
whether it moved; no deadline, so it can never be late; and no terminal disposition, so it can never
end. A blocker described that way survives indefinitely by being unfalsifiable.

A job here is a record with all five, and it can FAIL. `advance()` refuses a progress figure that
goes backwards, refuses completion while units remain, and marks a job OVERDUE the moment its
deadline passes with work outstanding — which is the property that makes the deadline real.

THE THIRD JOB IS THE INTERESTING ONE. If as-of historical features cannot be reconstructed without
leakage, the answer is not to wait: it is to register a CONSERVATIVE FALLBACK ARM built only from
inputs that CAN be reconstructed as-of, carrying its own validated uncertainty. That arm is worse
than the one we wanted, and it is honest, and a worse honest arm beats an indefinite outage.
"""

from __future__ import annotations

MODULE_ID = "recovery_jobs"

import json
import os
import sys

JOBS_PATH = "data/registry/recovery_jobs.json"

PENDING = "PENDING"
RUNNING = "RUNNING"
BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
COMPLETE = "COMPLETE"
FAILED_TERMINAL = "FAILED_TERMINAL"
CLOSED_CONDITION_NOT_FIRED = "CLOSED_CONDITION_NOT_FIRED"
TERMINAL_STATUSES = (COMPLETE, FAILED_TERMINAL, CLOSED_CONDITION_NOT_FIRED)
OVERDUE = "OVERDUE"
STATUSES = (PENDING, RUNNING, BLOCKED_EXTERNAL, *TERMINAL_STATUSES)

#: a terminal disposition is required to close a job, and "we stopped looking" is not one
TERMINAL_DISPOSITIONS = ("RESTORED", "RECONSTRUCTED", "FALLBACK_ARM_REGISTERED",
                         "UNRESOLVABLE_WITH_STATED_REASON", "SUPERSEDED_BY_WIDER_JOB",
                         "CONDITION_NOT_FIRED")

REQUIRED_FIELDS = ("job_id", "title", "owner_subsystem", "next_run_utc", "deadline_utc",
                   "units_total", "units_done", "status", "blocks")

BACKWARDS = "REFUSED_PROGRESS_WENT_BACKWARDS"
INCOMPLETE_CLOSE = "REFUSED_COMPLETE_WITH_UNITS_OUTSTANDING"
NO_DISPOSITION = "REFUSED_TERMINAL_WITHOUT_A_DISPOSITION"
UNKNOWN_DISPOSITION = "REFUSED_UNKNOWN_TERMINAL_DISPOSITION"


def _job(job_id, title, owner, next_run, deadline, units_total, blocks, notes=None,
         depends_on=None):
    return {"job_id": job_id, "title": title, "owner_subsystem": owner, "next_run_utc": next_run,
            "deadline_utc": deadline, "units_total": units_total, "units_done": 0,
            "status": PENDING, "blocks": list(blocks), "depends_on": list(depends_on or []),
            "terminal_disposition": None, "notes": notes, "history": []}


def default_jobs():
    """The two open problems, converted. Ids are stable so later records can reference them."""
    return {j["job_id"]: j for j in (
        _job("RJ-001-PROVENANCE",
             "Restore Tier-1 provenance for the 123 provisional rows and the 1,620 with no "
             "evidence path",
             "acquisition", "2026-08-25T06:00:00Z", "2026-09-01T00:00:00Z", 123,
             blocks=["PRIOR_INPUT_POOL_PROVISIONAL", "UNCERTAINTY_PIPELINE_DEFECT"],
             notes="a unit is one canonical row bound to a retrieved artifact with a game id, a "
                   "retrieval timestamp and a content hash. Currently blocked on egress; the job "
                   "records BLOCKED_EXTERNAL rather than silently not running."),
        _job("RJ-002-OOF-REPLAY",
             "Build a leakage-free date-blocked historical replay for uncertainty estimation",
             "modelling", "2026-08-25T06:30:00Z", "2026-09-08T00:00:00Z", 20,
             blocks=["UNCERTAINTY_PIPELINE_DEFECT", "INSUFFICIENT_EFFECTIVE_CLUSTERS"],
             depends_on=["RJ-001-PROVENANCE"],
             notes="a unit is one admissible date block: features reconstructed strictly as-of, "
                   "graded out of fold. Target is 20 EFFECTIVE clusters, not 20 nominal dates, and "
                   "not the computable floor of 6."),
        _job("RJ-003-FALLBACK-ARM",
             "Register a conservative fallback arm on reconstructible-as-of inputs, with its own "
             "validated uncertainty",
             "modelling", "2026-08-25T07:00:00Z", "2026-09-08T00:00:00Z", 4,
             blocks=["UNCERTAINTY_PIPELINE_DEFECT"],
             notes="fires if RJ-002 finds that rich historical features cannot be reconstructed "
                   "as-of without leakage. Units: define the reconstructible input set; fit the "
                   "arm; validate its interval coverage; register the identity. A worse honest arm "
                   "beats an indefinite outage — but it must be a REGISTERED identity with its own "
                   "coverage validation, never the primary arm with wider error bars."),
    )}


def load(path=JOBS_PATH):
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        return json.load(fh).get("jobs", {})


def save(jobs, path=JOBS_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump({"schema": "ops.recovery_jobs.v1", "jobs": jobs}, fh, indent=1, sort_keys=True)


def advance(job, now_utc, units_done=None, status=None, disposition=None, note=None,
            next_run_utc=None):
    """Move a job forward. Refuses the three ways a job can lie about its own progress."""
    j = dict(job)
    missing = [k for k in REQUIRED_FIELDS if k not in j]
    if missing:
        return None, f"INCOMPLETE_JOB_RECORD: {missing}"
    if units_done is not None:
        if units_done < j["units_done"]:
            return None, (f"{BACKWARDS}: {j['units_done']} -> {units_done}. A job that can "
                          f"un-progress can report anything.")
        if units_done > j["units_total"]:
            return None, f"REFUSED_PROGRESS_EXCEEDS_TOTAL: {units_done} > {j['units_total']}"
        j["units_done"] = units_done
    if status is not None:
        if status not in STATUSES:
            return None, f"UNKNOWN_STATUS: {status}"
        if status == COMPLETE and j["units_done"] < j["units_total"]:
            return None, (f"{INCOMPLETE_CLOSE}: {j['units_done']}/{j['units_total']}")
        if status in TERMINAL_STATUSES:
            if not disposition:
                return None, NO_DISPOSITION
            if disposition not in TERMINAL_DISPOSITIONS:
                return None, f"{UNKNOWN_DISPOSITION}: {disposition}"
            if status == CLOSED_CONDITION_NOT_FIRED and disposition != "CONDITION_NOT_FIRED":
                return None, "REFUSED_CONDITIONAL_CLOSE_WITHOUT_MATCHING_DISPOSITION"
            j["terminal_disposition"] = disposition
        j["status"] = status
    if next_run_utc is not None:
        j["next_run_utc"] = next_run_utc
    j["history"] = list(j.get("history") or []) + [
        {"utc": now_utc, "units_done": j["units_done"], "status": j["status"], "note": note}]
    return j, None


def status_report(jobs, now_utc):
    """What is late, what is blocked, and which defects are still held open by which job."""
    rows, open_blocks, integrity_problems = [], {}, []
    for jid in sorted(jobs or {}):
        j = jobs[jid]
        terminal = j["status"] in TERMINAL_STATUSES
        if j["status"] not in STATUSES:
            integrity_problems.append(f"{jid}:UNKNOWN_STATUS:{j['status']}")
        if terminal and j.get("terminal_disposition") not in TERMINAL_DISPOSITIONS:
            integrity_problems.append(f"{jid}:TERMINAL_DISPOSITION_MISSING_OR_INVALID")
        if j["status"] == CLOSED_CONDITION_NOT_FIRED and j.get("terminal_disposition") != "CONDITION_NOT_FIRED":
            integrity_problems.append(f"{jid}:CONDITIONAL_DISPOSITION_MISMATCH")
        overdue = (not terminal) and str(now_utc) >= str(j["deadline_utc"])
        pct = (100.0 * j["units_done"] / j["units_total"]) if j["units_total"] else 0.0
        rows.append({"job_id": jid, "title": j["title"], "owner": j["owner_subsystem"],
                     "status": OVERDUE if overdue else j["status"],
                     "progress": f"{j['units_done']}/{j['units_total']}",
                     "percent": round(pct, 1), "next_run_utc": j["next_run_utc"],
                     "deadline_utc": j["deadline_utc"], "overdue": overdue,
                     "terminal_disposition": j.get("terminal_disposition"),
                     "blocks": j["blocks"], "depends_on": j.get("depends_on") or [],
                     "phases": j.get("phases", {})})
        if not terminal:
            for b in j["blocks"]:
                open_blocks.setdefault(b, []).append(jid)
    return {"now_utc": now_utc, "n_jobs": len(rows),
            "n_overdue": sum(1 for r in rows if r["overdue"]),
            "n_terminal": sum(j["status"] in TERMINAL_STATUSES for j in jobs.values()),
            "integrity_problems": integrity_problems,
            "jobs": rows, "open_blockers": open_blocks,
            "note": "every defect above is held open by a NAMED job with a deadline. A blocker with "
                    "no job is a blocker nobody owns."}


# =================================================================================================
def selftest():
    f = []
    J = default_jobs()
    if len(J) != 3:
        f.append("three recovery jobs are registered")
    for jid in ("RJ-001-PROVENANCE", "RJ-002-OOF-REPLAY", "RJ-003-FALLBACK-ARM"):
        if jid not in J:
            f.append(f"{jid} must exist")
    for jid, j in J.items():
        for k in REQUIRED_FIELDS:
            if k not in j:
                f.append(f"{jid} missing {k}")
        if not j["blocks"]:
            f.append(f"{jid} must name the defect it holds open")
    if "RJ-001-PROVENANCE" not in J["RJ-002-OOF-REPLAY"]["depends_on"]:
        f.append("the OOF replay depends on provenance restoration")

    now = "2026-08-25T03:00:00Z"
    j1 = J["RJ-001-PROVENANCE"]

    # progress moves forward, is recorded, and cannot go backwards
    a, e = advance(j1, now, units_done=40, status=RUNNING, note="40 rows bound")
    if e or a["units_done"] != 40 or a["status"] != RUNNING:
        f.append(f"a job must advance: {e}")
    if not a["history"] or a["history"][-1]["units_done"] != 40:
        f.append("every advance must be recorded in history")
    # history must ACCUMULATE. Checking only the last entry cannot tell an append from a reset,
    # and a job whose history resets on every step has no history at all.
    a2, _ = advance(a, "2026-08-25T04:00:00Z", units_done=55, note="55 rows")
    a3, _ = advance(a2, "2026-08-25T05:00:00Z", units_done=70, note="70 rows")
    if len(a3["history"]) != 3:
        f.append(f"three advances must leave three history entries, got {len(a3['history'])}")
    if [h["units_done"] for h in a3["history"]] != [40, 55, 70]:
        f.append(f"history must preserve the whole trajectory, got "
                 f"{[h['units_done'] for h in a3['history']]}")
    _, e2 = advance(a, now, units_done=10)
    if not e2 or BACKWARDS not in e2:
        f.append("progress must not go backwards")
    _, e3 = advance(a, now, units_done=9999)
    if not e3:
        f.append("progress beyond the total must be refused")

    # a job cannot close with work outstanding
    _, e4 = advance(a, now, status=COMPLETE, disposition="RESTORED")
    if not e4 or INCOMPLETE_CLOSE not in e4:
        f.append("closing with units outstanding must be refused")
    done, e5 = advance(a, now, units_done=123, status=COMPLETE, disposition="RESTORED")
    if e5 or done["terminal_disposition"] != "RESTORED":
        f.append(f"a finished job closes with a disposition: {e5}")

    # a terminal status needs a disposition, and only a recognised one
    _, e6 = advance(a, now, units_done=123, status=COMPLETE)
    if not e6 or NO_DISPOSITION not in e6:
        f.append("a terminal status without a disposition must be refused")
    _, e7 = advance(a, now, units_done=123, status=COMPLETE, disposition="WE_STOPPED_LOOKING")
    if not e7 or UNKNOWN_DISPOSITION not in e7:
        f.append("'we stopped looking' is not a terminal disposition")
    for d in TERMINAL_DISPOSITIONS:
        _, ed = advance(a, now, units_done=123, status=COMPLETE, disposition=d)
        if ed:
            f.append(f"{d} must be an acceptable disposition")
    _, e8 = advance(a, now, status="INVENTED")
    if not e8:
        f.append("an unknown status must be refused")

    # a deadline that has passed with work outstanding makes the job OVERDUE — that is what makes
    # a deadline real rather than decorative
    late = status_report(J, "2026-09-02T00:00:00Z")
    if late["n_overdue"] < 1:
        f.append("a passed deadline with work outstanding must be OVERDUE")
    if not any(r["job_id"] == "RJ-001-PROVENANCE" and r["overdue"] for r in late["jobs"]):
        f.append("the provenance job must be overdue after its deadline")
    early = status_report(J, "2026-08-25T03:00:00Z")
    if early["n_overdue"] != 0:
        f.append("nothing is overdue before its deadline")
    # ...and a CLOSED job is never overdue, however old
    closed = dict(J); closed["RJ-001-PROVENANCE"] = done
    if any(r["job_id"] == "RJ-001-PROVENANCE" and r["overdue"]
           for r in status_report(closed, "2027-01-01T00:00:00Z")["jobs"]):
        f.append("a completed job cannot be overdue")

    # every open defect must be attributable to a named job
    rep = status_report(J, now)
    for b in ("PRIOR_INPUT_POOL_PROVISIONAL", "UNCERTAINTY_PIPELINE_DEFECT"):
        if b not in rep["open_blockers"]:
            f.append(f"{b} must be held open by a named job")
    if "RJ-001-PROVENANCE" not in rep["open_blockers"]["PRIOR_INPUT_POOL_PROVISIONAL"]:
        f.append("the provenance defect must name its owning job")
    # ...and closing every job empties the blocker list, which is the point of tracking it
    allclosed = {}
    for jid, j in J.items():
        d, _ = advance(j, now, units_done=j["units_total"], status=COMPLETE,
                       disposition="RESTORED")
        allclosed[jid] = d
    if status_report(allclosed, now)["open_blockers"]:
        f.append("a fully closed job set holds no blocker open")

    print("recovery_jobs selftest:", "OK" if not f else "FAIL")
    for x in f:
        print("   -", x)
    return not f


MUTANTS = [
    ("progress may go backwards",
     '        if units_done < j["units_done"]:', "        if False:"),
    ("a job may close with work outstanding",
     '        if status == COMPLETE and j["units_done"] < j["units_total"]:', "        if False:"),
    ("a terminal status needs no disposition",
     "            if not disposition:\n                return None, NO_DISPOSITION",
     "            if False:\n                return None, NO_DISPOSITION"),
    ("any string is a terminal disposition",
     "            if disposition not in TERMINAL_DISPOSITIONS:", "            if False:"),
    ("a deadline never expires",
     '        overdue = (not terminal) and str(now_utc) >= str(j["deadline_utc"])',
     "        overdue = False"),
    ("a completed job is still reported overdue",
     "        terminal = j[\"status\"] in TERMINAL_STATUSES",
     "        terminal = False"),
    ("open blockers stop being attributed to a job",
     "        if not terminal:\n            for b in j[\"blocks\"]:", "        if False:\n            for b in j[\"blocks\"]:"),
    ("progress stops being recorded",
     '    j["history"] = list(j.get("history") or []) + [', "    j[\"history\"] = [] + ["),
    ("the fallback arm job is dropped",
     '        _job("RJ-003-FALLBACK-ARM",', '        _job("RJ-003-DROPPED",'),
    ("the OOF replay stops depending on provenance",
     'depends_on=["RJ-001-PROVENANCE"],', "depends_on=[],"),
    ("progress may exceed the total",
     '        if units_done > j["units_total"]:', "        if False:"),
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
    if "--report" in sys.argv:
        jobs = load() or default_jobs()
        print(json.dumps(status_report(jobs, sys.argv[-1] if "T" in sys.argv[-1]
                                       else "2026-08-25T03:00:00Z"), indent=1))
    else:
        print(__doc__)
