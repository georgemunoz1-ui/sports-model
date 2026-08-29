"""Regression test: the 2026-08-28 stale-starter bypass must never reopen.

Replays the real rows from the frozen 2026-08-28 board through the PATCHED production path and
asserts the outcome is now different. These are not synthetic fixtures — the last_start_date
values are the ones sp_asof_strict actually returns for those pitchers against that slate.

The frozen board is NOT rebuilt and NOT modified. R3 holds. This test reads it to source truth and
exercises the code path that would produce tomorrow's board.
"""
from __future__ import annotations

MODULE_ID = "test_starter_freshness_regression"

import datetime as dt
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "harness"))

import freshness_contract as FC          # noqa: E402
import build_board_0825 as B             # noqa: E402

SLATE = "2026-08-28"

#: (name, last_start_date, age_at_slate) — measured, not invented
REAL_ROWS = [
    ("Hunter Brown",    "2026-07-19", 40),   # HOU@NYM away
    ("Christian Scott", "2026-07-16", 43),   # HOU@NYM home
    ("Drew Anderson",   "2026-06-15", 74),   # worst on the slate
    ("Andrew Painter",  "2026-06-17", 72),
    ("Gerrit Cole",     "2026-07-22", 37),   # freshest RESOLVED slot on the slate
]


def _feats(last):
    return {"era": 3.50, "gs": 12, "k_pct": 24.0, "bb_pct": 7.0, "last_start_date": last}


def run():
    f = []

    # R1 — every real 8/28 slot must now DEGRADE. The freshest was 37 days old; the limit is 2.
    for name, last, expected_age in REAL_ROWS:
        d = B.starter_freshness(name, _feats(last), slate_date=SLATE)
        if d.disposition != FC.DEGRADED:
            f.append(f"R1: {name} ({expected_age}d) resolved {d.disposition}, expected DEGRADED")
        if d.age_days is None or abs(d.age_days - expected_age) > 1.5:
            f.append(f"R1: {name} age computed {d.age_days}, expected ~{expected_age}")
        if d.dose_multiplier >= 1.0:
            f.append(f"R1: {name} kept a full dose at {expected_age}d")

    # R2 — THE HEADLINE. HOU@NYM must no longer produce a full information dose.
    brown = B.starter_freshness("Hunter Brown", _feats("2026-07-19"), slate_date=SLATE)
    scott = B.starter_freshness("Christian Scott", _feats("2026-07-16"), slate_date=SLATE)
    dose = FC.cohort_dose([brown, scott])
    if dose >= 1.0:
        f.append(f"R2: HOU@NYM still produces dose {dose}; the published board said 1.0")
    if not (brown.bettable and scott.bettable):
        f.append("R2: the fix made HOU@NYM unbettable; terminal behaviour must be degrade, not block")

    # R3 — the status string the builder emits must NOT be RESOLVED, because owner_class maps
    #      RESOLVED -> PROBABLE and PROBABLE is what the dose formula reads as full information.
    class _PidMap(dict):
        pass
    saved = B.ASOF.sp_asof_strict
    try:
        B.ASOF.sp_asof_strict = lambda pid, sd, ph: (_feats("2026-07-19"), {})
        sp, status, rs = B.starter(_PidMap({"Hunter Brown": "p1"}), "Hunter Brown")
        if status == "RESOLVED":
            f.append("R3: a 40-day-old slot still emits RESOLVED from starter()")
        if not status.startswith("STALE_DATA_CAP"):
            f.append(f"R3: expected STALE_DATA_CAP, got {status!r}")
        if rs is not None:
            f.append("R3: a stale slot still returned a run-support value")

        # R4 — a genuinely fresh slot must still resolve normally. The fix must not cap everything.
        fresh_date = (dt.date.fromisoformat(SLATE) - dt.timedelta(days=1)).isoformat()
        B.ASOF.sp_asof_strict = lambda pid, sd, ph: (_feats(fresh_date), {})
        sp2, status2, rs2 = B.starter(_PidMap({"Fresh Guy": "p2"}), "Fresh Guy")
        if status2 != "RESOLVED":
            f.append(f"R4: a 1-day-old slot was capped as {status2!r}; the gate is too aggressive")
        if rs2 is None:
            f.append("R4: a fresh slot lost its run-support value")
    finally:
        B.ASOF.sp_asof_strict = saved

    # R5 — owner_class must not launder the new status into PROBABLE.
    import build_board_0828 as B28
    cls = B28.owner_class("STALE_DATA_CAP(last_start=2026-07-19,age=40d,limit=2d)")
    if cls == "PROBABLE":
        f.append("R5: owner_class laundered STALE_DATA_CAP into PROBABLE — the original bug")
    if "STALE" not in cls:
        f.append(f"R5: owner_class returned {cls!r}, which does not name the staleness")

    # R6 — a missing last_start_date is ABSENT, never fresh.
    d6 = B.starter_freshness("No Date Guy", {"era": 3.0, "gs": 5, "k_pct": 20.0,
                                             "bb_pct": 8.0, "last_start_date": None},
                             slate_date=SLATE)
    if d6.disposition != FC.DEGRADED or d6.grade != FC.ABSENT:
        f.append(f"R6: a feature row with no last_start_date resolved {d6.disposition}/{d6.grade}")

    print(f"{MODULE_ID} selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("  !", x)
    if not f:
        print(f"    HOU@NYM cohort dose: 1.0 (published)  ->  {dose}  (after the fix)")
        print(f"    Hunter Brown    40d -> {brown.disposition} dose {brown.dose_multiplier}")
        print(f"    Christian Scott 43d -> {scott.disposition} dose {scott.dose_multiplier}")
    return 0 if not f else 1


def gate():
    return run()


if __name__ == "__main__":
    sys.exit(run())
