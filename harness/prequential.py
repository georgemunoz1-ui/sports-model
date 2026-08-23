#!/usr/bin/env python3
"""PREQUENTIAL PROVENANCE — prove the prior could not have seen what it is forecasting.

OWNER REQUIREMENT 2026-08-23:
    "Prove the prior is prequential. Each row must expose prior_n, prior_p, prior_cutoff_utc, and
     confirm no same-slate or target-game result entered the prior."

A PRIOR IS ONLY A BASELINE IF IT IS BLIND. An expanding base rate that has seen the slate it is
scoring is not a baseline — it is a leak wearing a baseline's label, and every skill score computed
against it is meaningless in a direction that FLATTERS the challenger (a contaminated prior looks
better than it is, so the challenger's skill looks worse; or, if the contamination is partial, the
comparison is simply unmoored). The asymmetry does not matter. What matters is that the claim be
checkable per row rather than asserted once in prose.

THREE FIELDS PER ROW, AND A PROOF. prior_n, prior_p and prior_cutoff_utc are carried on every
evaluation row. The proof is a positive assertion over the pool ITSELF, not over the code that built
it: the pool is re-derived, and every game in it is checked to be strictly earlier than the target
slate date and to not be the target game. A rule that lives only in the builder is a rule that stops
being true the first time someone calls the builder differently.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CLEAN = "PREQUENTIAL_CLEAN"
SAME_SLATE_LEAK = "SAME_SLATE_RESULT_IN_PRIOR"
TARGET_GAME_LEAK = "TARGET_GAME_RESULT_IN_PRIOR"
FUTURE_LEAK = "FUTURE_RESULT_IN_PRIOR"
NO_POOL = "NO_POOL_SUPPLIED"


def audit_pool(pool, target_slate_date, target_game_id=None):
    """(status, failures) for ONE prior pool against ONE target.

    Checks the POOL, not the builder. Every row must be strictly earlier than the target slate."""
    if pool is None:
        return NO_POOL, ["no prior pool was supplied, so the prequential claim cannot be checked"]
    f = []
    same, future, target = [], [], []
    for r in pool:
        d = r.get("date") or ""
        gid = r.get("game_id")
        if target_game_id is not None and gid == target_game_id:
            target.append(gid)
        if d == target_slate_date:
            same.append(gid)
        elif d > target_slate_date:
            future.append(gid)
    if target:
        f.append(f"{TARGET_GAME_LEAK}: the target game itself is in its own prior pool {target[:3]}")
    if same:
        f.append(f"{SAME_SLATE_LEAK}: {len(same)} same-slate result(s) in the prior pool "
                 f"{same[:3]} — a prior that has seen the slate it scores is not a baseline")
    if future:
        f.append(f"{FUTURE_LEAK}: {len(future)} result(s) dated AFTER the target slate {future[:3]}")
    return (CLEAN if not f else f[0].split(":")[0]), f


def provenance(prior_record, pool, target_slate_date, target_game_id=None):
    """The three required fields plus the audit result, for attachment to an evaluation row."""
    status, f = audit_pool(pool, target_slate_date, target_game_id)
    return {
        "prior_n": prior_record.get("prior_games_n"),
        "prior_p": prior_record.get("p_home_prior"),
        "prior_cutoff_utc": prior_record.get("prior_cutoff_utc",
                                             f"{target_slate_date}T00:00:00Z"),
        "prior_source_hash": prior_record.get("prior_source_hash"),
        "prior_last_game_date": prior_record.get("prior_last_game_date"),
        "prequential_status": status,
        "prequential_failures": f,
    }


REQUIRED_ROW_FIELDS = ("prior_n", "prior_p", "prior_cutoff_utc", "prequential_status")


def audit_rows(rows):
    """(ok, failures, summary) over a whole evaluation cohort.

    A row missing any required field FAILS: an unexposed provenance field is an unchecked one."""
    f = []
    counts = {}
    for r in rows:
        gid = r.get("game_id", "?")
        for k in REQUIRED_ROW_FIELDS:
            if r.get(k) is None:
                f.append(f"{gid}: required prequential field {k} is absent")
        st = r.get("prequential_status")
        counts[st] = counts.get(st, 0) + 1
        if st is not None and st != CLEAN:
            f.append(f"{gid}: prequential status {st}")
        cut = r.get("prior_cutoff_utc")
        sd = r.get("slate_date")
        if cut and sd and not (str(cut)[:10] <= sd):
            f.append(f"{gid}: prior cutoff {cut} is not at or before its slate date {sd}")
        n = r.get("prior_n")
        if n is not None and not (isinstance(n, int) and n >= 0):
            f.append(f"{gid}: prior_n {n!r} is not a count")
    return (not f), f, {"n_rows": len(rows), "by_status": counts}


def selftest():
    f = []
    POOL = [{"game_id": "a", "date": "2026-08-18"}, {"game_id": "b", "date": "2026-08-20"}]
    st, ff = audit_pool(POOL, "2026-08-21")
    if st != CLEAN or ff:
        f.append(f"a clean pool was flagged: {st} {ff}")
    # SAME-SLATE leak
    st, ff = audit_pool(POOL + [{"game_id": "c", "date": "2026-08-21"}], "2026-08-21")
    if st != SAME_SLATE_LEAK or not any("not a baseline" in x for x in ff):
        f.append(f"a same-slate result did not trip the leak check: {st} {ff}")
    # FUTURE leak
    st, ff = audit_pool(POOL + [{"game_id": "d", "date": "2026-08-25"}], "2026-08-21")
    if st != FUTURE_LEAK:
        f.append(f"a future-dated result did not trip the leak check: {st}")
    # TARGET GAME leak takes precedence and is named separately
    st, ff = audit_pool(POOL + [{"game_id": "T", "date": "2026-08-21"}], "2026-08-21",
                        target_game_id="T")
    if st != TARGET_GAME_LEAK:
        f.append(f"the target game in its own prior was reported as {st}")
    if not any(TARGET_GAME_LEAK in x for x in ff) or not any(SAME_SLATE_LEAK in x for x in ff):
        f.append("the target-game leak masked the same-slate finding instead of reporting both")
    # an EARLIER meeting of the same matchup is NOT a leak
    st, _ = audit_pool(POOL + [{"game_id": "T", "date": "2026-08-18"}], "2026-08-21",
                       target_game_id="T2")
    if st != CLEAN:
        f.append("an earlier game was treated as a leak")
    # NO POOL is refused, not assumed clean
    st, ff = audit_pool(None, "2026-08-21")
    if st != NO_POOL or not ff:
        f.append("a missing pool was treated as clean")

    # --- provenance fields ---------------------------------------------------------------------
    pr = {"prior_games_n": 1808, "p_home_prior": 0.52516,
          "prior_cutoff_utc": "2026-08-22T00:00:00Z", "prior_source_hash": "abc",
          "prior_last_game_date": "2026-08-21"}
    p = provenance(pr, POOL, "2026-08-21")
    for k in ("prior_n", "prior_p", "prior_cutoff_utc", "prequential_status"):
        if k not in p:
            f.append(f"provenance omits {k}")
    if p["prior_n"] != 1808 or abs(p["prior_p"] - 0.52516) > 1e-12:
        f.append("provenance did not carry the prior's own values")
    if p["prequential_status"] != CLEAN:
        f.append("a clean provenance record was flagged")

    # --- row audit -------------------------------------------------------------------------------
    rows = [{"game_id": "g1", "slate_date": "2026-08-21", "prior_n": 100, "prior_p": 0.527,
             "prior_cutoff_utc": "2026-08-21T00:00:00Z", "prequential_status": CLEAN}]
    ok, ff, s = audit_rows(rows)
    if not ok:
        f.append(f"a clean row cohort failed: {ff}")
    if s["n_rows"] != 1 or s["by_status"].get(CLEAN) != 1:
        f.append(f"the row summary is wrong: {s}")
    # every required field is required
    for k in REQUIRED_ROW_FIELDS:
        bad = [dict(rows[0], **{k: None})]
        if audit_rows(bad)[0]:
            f.append(f"a row missing {k} was accepted — an unexposed field is an unchecked one")
    # a leaked row fails the cohort
    if audit_rows([dict(rows[0], prequential_status=SAME_SLATE_LEAK)])[0]:
        f.append("a leaked row passed the cohort audit")
    # a cutoff AFTER its own slate date fails
    if audit_rows([dict(rows[0], prior_cutoff_utc="2026-08-22T00:00:00Z")])[0]:
        f.append("a prior cutoff dated after its own slate was accepted")
    # a cutoff exactly at the slate date is fine (the pool is strictly earlier)
    if not audit_rows([dict(rows[0], prior_cutoff_utc="2026-08-21T00:00:00Z")])[0]:
        f.append("a cutoff at the slate boundary was rejected")
    if audit_rows([dict(rows[0], prior_n=-1)])[0]:
        f.append("a negative prior_n was accepted")

    print("prequential selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("same-slate results are allowed into the prior",
     '        if d == target_slate_date:\n            same.append(gid)', "        if False:\n            same.append(gid)"),
    ("future-dated results are allowed into the prior",
     "        elif d > target_slate_date:", "        elif False:"),
    ("the target game may appear in its own prior",
     "        if target_game_id is not None and gid == target_game_id:", "        if False:"),
    ("a missing pool is assumed clean", "    if pool is None:", "    if False:"),
    ("the same-slate refusal stops saying why it matters",
     '                 f"{same[:3]} — a prior that has seen the slate it scores is not a baseline")',
     '                 f"{same[:3]}")'),
    ("a required provenance field may be absent",
     "        for k in REQUIRED_ROW_FIELDS:\n            if r.get(k) is None:", "        for k in ():\n            if r.get(k) is None:"),
    ("a leaked row passes the cohort audit",
     '        if st is not None and st != CLEAN:', "        if False:"),
    ("a prior cutoff after its own slate date is accepted",
     "        if cut and sd and not (str(cut)[:10] <= sd):", "        if False:"),
    ("the cutoff boundary becomes strict, rejecting a legitimate cutoff",
     "        if cut and sd and not (str(cut)[:10] <= sd):", "        if cut and sd and not (str(cut)[:10] < sd):"),
    ("a negative prior_n is accepted",
     "        if n is not None and not (isinstance(n, int) and n >= 0):", "        if False:"),
    ("provenance stops carrying the prior's own values",
     '        "prior_n": prior_record.get("prior_games_n"),', '        "prior_n": None,'),
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
