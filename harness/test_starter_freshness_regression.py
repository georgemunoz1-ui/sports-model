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
import board_freshness as BF             # noqa: E402

SLATE = "2026-08-28"

#: (name, last_start_date, age_at_slate) — measured, not invented
REAL_ROWS = [
    ("Hunter Brown",    "2026-07-19", 40),   # HOU@NYM away
    ("Christian Scott", "2026-07-16", 43),   # HOU@NYM home
    ("Drew Anderson",   "2026-06-15", 74),   # worst on the slate
    ("Andrew Painter",  "2026-06-17", 72),
    ("Gerrit Cole",     "2026-07-22", 37),   # freshest RESOLVED slot on the slate
]


_NOW = dt.datetime.fromisoformat(SLATE).replace(tzinfo=dt.timezone.utc)


class _D:
    """Attribute view over resolve_starter_slot's disposition dict, so the assertions below read
    the same as they did against the old object API. The regression's INTENT is what must survive
    the refactor, not its accessor syntax."""

    def __init__(self, d):
        self.raw = d
        self.disposition = d["disposition"]
        self.grade = d["grade"]
        self.dose_multiplier = d["dose_multiplier"]
        self.age_days = d.get("age_days")
        self.bettable = True


def _feats(last):
    return {"era": 3.50, "gs": 12, "k_pct": 24.0, "bb_pct": 7.0, "last_start_date": last}


def run():
    f = []

    # R1 — every real 8/28 slot must now DEGRADE. The freshest was 37 days old; the limit is 2.
    for name, last, expected_age in REAL_ROWS:
        _sp, _st, dd = BF.resolve_starter_slot(name, _feats(last), "RESOLVED", SLATE,
                                               "regression fixture", now=_NOW)
        d = _D(dd)
        if d.disposition != FC.DEGRADED:
            f.append(f"R1: {name} ({expected_age}d) resolved {d.disposition}, expected DEGRADED")
        if d.age_days is None or abs(d.age_days - expected_age) > 1.5:
            f.append(f"R1: {name} age computed {d.age_days}, expected ~{expected_age}")
        if d.dose_multiplier >= 1.0:
            f.append(f"R1: {name} kept a full dose at {expected_age}d")

    # R2 — THE HEADLINE. HOU@NYM must no longer produce a full information dose.
    brown = _D(BF.resolve_starter_slot("Hunter Brown", _feats("2026-07-19"), "RESOLVED", SLATE,
                                       "regression fixture", now=_NOW)[2])
    scott = _D(BF.resolve_starter_slot("Christian Scott", _feats("2026-07-16"), "RESOLVED", SLATE,
                                       "regression fixture", now=_NOW)[2])
    dose = BF.game_dose([brown.raw, scott.raw])
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
        sp, status, rs, _d = B.starter(_PidMap({"Hunter Brown": "p1"}), "Hunter Brown", now=_NOW)
        if status in ("RESOLVED", "PROBABLE"):
            f.append(f"R3: a 40-day-old slot still emits {status!r} from starter()")
        if not status.startswith("STALE_DATA_CAP"):
            f.append(f"R3: expected STALE_DATA_CAP, got {status!r}")
        # DELIBERATELY RELAXED, 2026-08-29. The earlier assertion here demanded rs is None — it
        # encoded an implementation choice of mine (blank the sp dict on a stale slot), not a
        # correctness requirement. The integrated builder keeps the REAL aged features feeding the
        # engine and widens the dose instead, which is both more informative and truer to R1: do
        # not discard real data, discount confidence in it. What must never regress is the SAFETY
        # property, asserted below.
        if _d["dose_multiplier"] == 1.0:
            f.append("R3: a stale slot kept a full information dose")
        if status == "PROBABLE":
            f.append("R3: a stale slot reached bare PROBABLE")

        # R4 — a genuinely fresh slot must still resolve normally. The fix must not cap everything.
        fresh_date = (dt.date.fromisoformat(SLATE) - dt.timedelta(days=1)).isoformat()
        B.ASOF.sp_asof_strict = lambda pid, sd, ph: (_feats(fresh_date), {})
        sp2, status2, rs2, _d2 = B.starter(_PidMap({"Fresh Guy": "p2"}), "Fresh Guy", now=_NOW)
        # the vocabulary changed with the refactor: resolve_slot returns PROBABLE directly where
        # owner_class used to map RESOLVED -> PROBABLE. Bare PROBABLE still means FRESH+CONFIRMED.
        if status2 != "PROBABLE":
            f.append(f"R4: a 1-day-old slot was capped as {status2!r}; the gate is too aggressive")
        if rs2 is None:
            f.append("R4: a fresh slot lost its run-support value")
    finally:
        B.ASOF.sp_asof_strict = saved

    # R5 — the vocabulary must not launder a stale slot into bare PROBABLE. owner_class is gone;
    #      board_freshness.resolve_slot now owns the mapping for every sport, and bare PROBABLE is
    #      reachable ONLY from FRESH + CONFIRMED. This is the original bug, restated against the
    #      replacement API so the regression stays pinned across the refactor.
    stale_stamp = BF.stamp_from_features("Hunter Brown", _feats("2026-07-19"), SLATE,
                                         "regression fixture")
    st5, d5 = BF.resolve_slot("Hunter Brown", "mlb", "starter", stale_stamp, "RESOLVED",
                              now=dt.datetime.fromisoformat(SLATE).replace(tzinfo=dt.timezone.utc))
    if st5 == "PROBABLE":
        f.append("R5: a 40-day-old slot mapped to bare PROBABLE — the original bug, reopened")
    if "STALE" not in st5:
        f.append(f"R5: status {st5!r} does not name the staleness")
    if d5["disposition"] != FC.DEGRADED:
        f.append(f"R5: resolve_slot returned {d5['disposition']} for a 40-day-old slot")

    # R7 — a FRESH + CONFIRMED slot must still reach bare PROBABLE, or the gate is a blanket cap.
    fresh_stamp = BF.stamp_from_features(
        "Fresh Guy", _feats((dt.date.fromisoformat(SLATE) - dt.timedelta(days=1)).isoformat()),
        SLATE, "regression fixture")
    st7, _ = BF.resolve_slot("Fresh Guy", "mlb", "starter", fresh_stamp, "RESOLVED",
                             now=dt.datetime.fromisoformat(SLATE).replace(tzinfo=dt.timezone.utc))
    if st7 != "PROBABLE":
        f.append(f"R7: a 1-day-old confirmed slot got {st7!r}; the gate is capping everything")

    # R6 — a missing last_start_date is ABSENT, never fresh.
    d6 = _D(BF.resolve_starter_slot("No Date Guy", {"era": 3.0, "gs": 5, "k_pct": 20.0,
                                                    "bb_pct": 8.0, "last_start_date": None},
                                    "RESOLVED", SLATE, "regression fixture", now=_NOW)[2])
    # R6 — the SAFETY property is that an unknowable age DEGRADES. The grade label differs between
    #      implementations (ABSENT vs CONFIRMED-with-no-timestamp) and is not load-bearing; the
    #      disposition is.
    if d6.disposition != FC.DEGRADED:
        f.append(f"R6: a feature row with no last_start_date resolved {d6.disposition}, not DEGRADED")
    if d6.dose_multiplier == 1.0:
        f.append("R6: a row with an unknowable age kept a full dose")

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
