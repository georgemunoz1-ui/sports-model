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


def provenance(prior_record, pool, target_slate_date, target_game_id=None,
               generated_at_utc=None, game_start_utc=None,
               prior_last_game_finalized_at_utc=None):
    """The required fields plus BOTH audits, for attachment to an evaluation row."""
    status, f = audit_pool(pool, target_slate_date, target_game_id)
    cut = prior_record.get("prior_cutoff_utc", f"{target_slate_date}T00:00:00Z")
    cstatus, cf = audit_chronology(prior_last_game_finalized_at_utc, cut,
                                   generated_at_utc, game_start_utc)
    return {
        "chronology_status": cstatus,
        "chronology_failures": cf,
        "prior_last_game_finalized_at_utc": prior_last_game_finalized_at_utc,
        "generated_at_utc": generated_at_utc,
        "game_start_utc": game_start_utc,
        "prior_n": prior_record.get("prior_games_n"),
        "prior_p": prior_record.get("p_home_prior"),
        "prior_cutoff_utc": prior_record.get("prior_cutoff_utc",
                                             f"{target_slate_date}T00:00:00Z"),
        "prior_source_hash": prior_record.get("prior_source_hash"),
        "prior_last_game_date": prior_record.get("prior_last_game_date"),
        "prequential_status": status,
        "prequential_failures": f,
    }


# ---------------------------------------------------------------------------------------------
# CHRONOLOGY — TIMESTAMPS, NOT CALENDAR DATES.
#
# OWNER RULING 2026-08-23: prior_last_game_date=2026-08-18 does NOT prove safety against a cutoff of
# 2026-08-19T00:00:00Z. That cutoff is 17:00 Pacific on August 18, and MLB games dated August 18 on
# the West Coast were still in progress. A calendar date says which SLATE a game belongs to; it says
# nothing about when the result became knowable. The required orderings are:
#
#     prior_last_game_finalized_at_utc  <  prior_cutoff_utc
#     prior_cutoff_utc                 <=  generated_at_utc  <  game_start_utc
#
# The middle ordering matters as much as the first: a cutoff LATER than the moment the forecast was
# generated would mean the prior absorbed results the forecast could not have used, and a forecast
# generated at or after first pitch is not a forecast.
# ---------------------------------------------------------------------------------------------
CHRONOLOGY_OK = "CHRONOLOGY_OK"
FINALIZATION_AFTER_CUTOFF = "PRIOR_GAME_FINALIZED_AT_OR_AFTER_CUTOFF"
CUTOFF_AFTER_GENERATION = "CUTOFF_AFTER_GENERATION"
GENERATED_AFTER_START = "GENERATED_AT_OR_AFTER_FIRST_PITCH"
NO_FINALIZATION_TIMESTAMP = "NO_FINALIZATION_TIMESTAMP_AVAILABLE"


def audit_chronology(prior_last_game_finalized_at_utc, prior_cutoff_utc, generated_at_utc,
                     game_start_utc):
    """(status, failures). All four instants are required; a missing one is refused, not assumed."""
    f = []
    fin, cut, gen, start = (prior_last_game_finalized_at_utc, prior_cutoff_utc,
                            generated_at_utc, game_start_utc)
    if fin is None:
        return NO_FINALIZATION_TIMESTAMP, [
            f"{NO_FINALIZATION_TIMESTAMP}: the prior's last pooled game carries no finalization "
            f"timestamp. A CALENDAR DATE IS NOT SUFFICIENT — a game dated the day before a midnight "
            f"UTC cutoff may still have been in progress at that cutoff."]
    for name, v in (("prior_cutoff_utc", cut), ("generated_at_utc", gen),
                    ("game_start_utc", start)):
        if v is None:
            f.append(f"{name} is absent; chronology cannot be established")
    if f:
        return "CHRONOLOGY_UNESTABLISHED", f
    if not (fin < cut):
        f.append(f"{FINALIZATION_AFTER_CUTOFF}: the last pooled result finalized at {fin}, at or "
                 f"after the prior cutoff {cut}")
    if not (cut <= gen):
        f.append(f"{CUTOFF_AFTER_GENERATION}: the prior cutoff {cut} is AFTER the forecast was "
                 f"generated at {gen}, so the prior absorbed results the forecast could not use")
    if not (gen < start):
        f.append(f"{GENERATED_AFTER_START}: the forecast was generated at {gen}, at or after first "
                 f"pitch {start}")
    return (CHRONOLOGY_OK if not f else f[0].split(":")[0]), f


REQUIRED_ROW_FIELDS = ("prior_n", "prior_p", "prior_cutoff_utc", "prequential_status",
                       "chronology_status")


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
        cs = r.get("chronology_status")
        if cs is not None and cs != CHRONOLOGY_OK:
            f.append(f"{gid}: chronology status {cs}")
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

    # --- CHRONOLOGY: timestamps, not calendar dates ------------------------------------------
    FIN, CUT, GEN, START = ("2026-08-18T23:12:00Z", "2026-08-19T00:00:00Z",
                            "2026-08-19T09:35:00Z", "2026-08-19T23:05:00Z")
    st, ff = audit_chronology(FIN, CUT, GEN, START)
    if st != CHRONOLOGY_OK or ff:
        f.append(f"a clean chronology was flagged: {st} {ff}")
    # THE OWNER'S EXACT CASE: a West Coast game dated 08-18 that finished AFTER a midnight-UTC
    # cutoff. A calendar date of 2026-08-18 looks safe; the timestamp is not.
    st, ff = audit_chronology("2026-08-19T02:40:00Z", CUT, GEN, START)
    if st != FINALIZATION_AFTER_CUTOFF:
        f.append(f"a game finalized at 02:40Z on the 19th passed a midnight-19th cutoff: {st}")
    # boundary: finalization EXACTLY at the cutoff is not before it
    if audit_chronology(CUT, CUT, GEN, START)[0] != FINALIZATION_AFTER_CUTOFF:
        f.append("a result finalized exactly at the cutoff was accepted")
    # cutoff AFTER generation
    if audit_chronology(FIN, "2026-08-19T10:00:00Z", GEN, START)[0] != CUTOFF_AFTER_GENERATION:
        f.append("a prior cutoff later than the forecast's own generation time was accepted")
    # cutoff EXACTLY at generation is permitted
    if audit_chronology(FIN, GEN, GEN, START)[0] != CHRONOLOGY_OK:
        f.append("a cutoff exactly at generation was refused; the rule is cutoff <= generated")
    # generated at or after first pitch
    for g in (START, "2026-08-19T23:30:00Z"):
        if audit_chronology(FIN, CUT, g, START)[0] != GENERATED_AFTER_START:
            f.append(f"a forecast generated at {g} against a {START} first pitch was accepted")
    # A CALENDAR DATE ALONE IS REFUSED
    st, ff = audit_chronology(None, CUT, GEN, START)
    if st != NO_FINALIZATION_TIMESTAMP:
        f.append("a missing finalization timestamp was not refused")
    if "CALENDAR DATE IS NOT SUFFICIENT" not in " ".join(ff):
        f.append("the refusal does not say a calendar date is insufficient")
    for missing in ("cut", "gen", "start"):
        args = {"prior_last_game_finalized_at_utc": FIN, "prior_cutoff_utc": CUT,
                "generated_at_utc": GEN, "game_start_utc": START}
        args[{"cut": "prior_cutoff_utc", "gen": "generated_at_utc",
              "start": "game_start_utc"}[missing]] = None
        if audit_chronology(**args)[0] == CHRONOLOGY_OK:
            f.append(f"chronology passed with {missing} absent")

    # --- row audit -------------------------------------------------------------------------------
    rows = [{"game_id": "g1", "slate_date": "2026-08-21", "prior_n": 100, "prior_p": 0.527,
             "prior_cutoff_utc": "2026-08-21T00:00:00Z", "prequential_status": CLEAN,
             "chronology_status": CHRONOLOGY_OK}]
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
    for bad in (FINALIZATION_AFTER_CUTOFF, CUTOFF_AFTER_GENERATION, GENERATED_AFTER_START,
                NO_FINALIZATION_TIMESTAMP):
        if audit_rows([dict(rows[0], chronology_status=bad)])[0]:
            f.append(f"a row with chronology status {bad} passed the cohort audit")
    # provenance carries the chronology verdict through
    pr19 = dict(pr, prior_cutoff_utc=CUT)     # a prior record whose cutoff matches this chronology
    pv = provenance(pr19, POOL, "2026-08-21", generated_at_utc=GEN, game_start_utc=START,
                    prior_last_game_finalized_at_utc=FIN)
    if pv["chronology_status"] != CHRONOLOGY_OK:
        f.append(f"provenance mis-graded a clean chronology: {pv['chronology_status']}")
    pv2 = provenance(pr19, POOL, "2026-08-21")
    if pv2["chronology_status"] != NO_FINALIZATION_TIMESTAMP:
        f.append("provenance with no finalization timestamp was not refused")
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
    ("a calendar date is accepted in place of a finalization timestamp",
     "    if fin is None:", "    if False:"),
    ("finalization at or after the cutoff is accepted",
     "    if not (fin < cut):", "    if not (fin <= cut):"),
    ("the finalization ordering is dropped entirely",
     "    if not (fin < cut):", "    if False:"),
    ("a prior cutoff later than the forecast generation is accepted",
     "    if not (cut <= gen):", "    if False:"),
    ("the cutoff/generation boundary becomes strict, refusing a legitimate equality",
     "    if not (cut <= gen):", "    if not (cut < gen):"),
    ("a forecast generated at or after first pitch is accepted",
     "    if not (gen < start):", "    if False:"),
    ("a missing chronology instant is assumed safe",
     "        if v is None:\n            f.append(f\"{name} is absent; chronology cannot be established\")",
     "        if False:\n            f.append(f\"{name} is absent; chronology cannot be established\")"),
    ("a bad chronology status no longer fails the cohort",
     "        if cs is not None and cs != CHRONOLOGY_OK:", "        if False:"),
    ("the calendar-date refusal stops explaining itself",
     'f"timestamp. A CALENDAR DATE IS NOT SUFFICIENT — a game dated the day before a midnight "',
     'f"timestamp. "'),
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
