#!/usr/bin/env python3
"""Settlement contract gate: estimands are structured, separate, and never graded from hindsight.

WHY (owner ruling 2026-08-19): the 8/18 WNBA settlement graded the registered win-probability head
correctly but LABELLED it generically as "sides" while the pregame table displayed spread reads —
two estimands under one word. The follow-up then graded a 3-1 ATS overlay that was never registered
as a gradeable output, which, entered as a record, would have been a ghost grade. Both failures are
naming/contract failures, so the fix is a contract, machine-enforced:

  - future settlement records carry an explicit `estimand`: WINNER | MARGIN | TOTAL | ATS
  - the generic label "side" is REJECTED in post-cutoff records
  - a graded ATS record requires a PRE-TIP ats_selection_id resolving to a registered selection
    whose capture timestamp precedes tip — a selection derived after the outcome cannot grade
  - one estimand per record: WINNER, MARGIN and ATS results are never combined
  - reports use three separate headings (WINNER / ATS / TOTAL)

Records graded BEFORE the cutoff are grandfathered as-written (append-only: they are historical
fact, and the winner ledger 9/13 / Brier .1648 stands). The contract binds everything after.

Usage: python3 harness/settlement_contract.py [--gate] [--selftest]
"""
from __future__ import annotations
import datetime as dt, json, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
CUTOFF = "2026-08-19T05:00:00Z"
ESTIMANDS = {"WINNER", "MARGIN", "TOTAL", "ATS"}
WNBA_GRADES = "data/wnba/forecasts/grades.jsonl"
ATS_SELECTIONS = "data/wnba/forecasts/ats_selections.jsonl"
WNBA_REGS = "data/wnba/forecasts/registrations.jsonl"


def _rows(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def check(grades=None, selections=None, regs=None):
    grades = grades if grades is not None else _rows(WNBA_GRADES)
    selections = selections if selections is not None else _rows(ATS_SELECTIONS)
    regs = regs if regs is not None else _rows(WNBA_REGS)
    sel_by_id = {s["ats_selection_id"]: s for s in selections}
    tip_by_ref = {r["forecast_id"]: r.get("tip_utc") for r in regs}
    fails = []
    for g in grades:
        if (g.get("graded_at_utc") or "") < CUTOFF:
            continue  # grandfathered historical record
        gid = g.get("grade_id", "?")
        est = g.get("estimand")
        if est not in ESTIMANDS:
            fails.append(f"{gid}: missing/invalid estimand {est!r} — WINNER|MARGIN|TOTAL|ATS required")
        # generic 'side' language rejected in post-cutoff records
        for k in g:
            if k == "side" or (k.startswith("side") and k != "side_note"):
                fails.append(f"{gid}: generic label {k!r} — name the estimand instead")
        # one estimand per record: a WINNER grade may not also carry margin/total/ats results
        packed = [f for f in ("margin_result", "total_result", "ats_result", "cover_result")
                  if f in g and est != {"margin_result": "MARGIN", "total_result": "TOTAL",
                                        "ats_result": "ATS", "cover_result": "ATS"}[f]]
        if packed:
            fails.append(f"{gid}: combines estimands — carries {packed} on a {est} record")
        if est == "ATS":
            sid = g.get("ats_selection_id")
            if not sid:
                fails.append(f"{gid}: ATS grade without ats_selection_id — a post-outcome derived "
                             f"selection cannot grade")
                continue
            s = sel_by_id.get(sid)
            if s is None:
                fails.append(f"{gid}: ats_selection_id {sid} resolves to no registered selection")
                continue
            cap, tip = s.get("captured_at_utc"), s.get("tip_utc") or tip_by_ref.get(s.get("forecast_ref", ""))
            if not cap or not tip or not (cap < tip):
                fails.append(f"{gid}: selection {sid} capture {cap} is not strictly pre-tip {tip}")
            for req in ("line", "selected_team", "home_margin_pred", "home_cover_delta", "rule_id"):
                if s.get(req) in (None, ""):
                    fails.append(f"{gid}: selection {sid} missing bound field {req}")
    # selections must never be graded twice
    graded_sids = [g.get("ats_selection_id") for g in grades if g.get("estimand") == "ATS"]
    dupes = {x for x in graded_sids if x and graded_sids.count(x) > 1}
    for d in dupes:
        fails.append(f"selection {d} graded more than once")
    return fails


def selftest():
    f = []
    ok_sel = {"ats_selection_id": "S1", "captured_at_utc": "2026-08-20T10:00:00Z",
              "tip_utc": "2026-08-20T23:00:00Z", "line": 1.5, "juice": -110, "source": "b",
              "selected_team": "CON", "home_margin_pred": 0.9, "home_cover_delta": 2.4,
              "rule_id": "WNBA-ATS-PREREG-2026-08-19"}
    base = {"grade_id": "G1", "graded_at_utc": "2026-08-21T04:00:00Z", "estimand": "ATS",
            "ats_selection_id": "S1", "ats_result": "WIN"}
    if check([base], [ok_sel], []):
        f.append("a fully compliant ATS grade was rejected: " + str(check([base], [ok_sel], [])))
    # 1. generic 'side' label must fail post-cutoff
    if not check([{"grade_id": "G", "graded_at_utc": "2026-08-21T00:00:00Z", "estimand": "WINNER",
                   "side": "CON"}], [], []):
        f.append("generic 'side' label accepted")
    # 2. ATS grade without a selection id must fail (post-outcome derivation)
    if not check([{"grade_id": "G", "graded_at_utc": "2026-08-21T00:00:00Z", "estimand": "ATS",
                   "ats_result": "WIN"}], [], []):
        f.append("ATS grade without pre-tip selection accepted — ghost grade possible")
    # 3. capture AFTER tip must fail
    late = dict(ok_sel, captured_at_utc="2026-08-21T02:00:00Z")
    if not check([base], [late], []):
        f.append("post-tip selection capture accepted")
    # 4. combined estimands must fail
    if not check([{"grade_id": "G", "graded_at_utc": "2026-08-21T00:00:00Z", "estimand": "WINNER",
                   "home_win": 1, "ats_result": "WIN"}], [ok_sel], []):
        f.append("combined WINNER+ATS record accepted")
    # 5. missing estimand must fail
    if not check([{"grade_id": "G", "graded_at_utc": "2026-08-21T00:00:00Z", "home_win": 1}], [], []):
        f.append("missing estimand accepted")
    # 6. pre-cutoff records are grandfathered — the live ledger must pass unchanged
    live = check()
    if live:
        f.append(f"live ledger violates the contract: {live[:3]}")
    # 7. duplicate grading of one selection must fail
    if not check([base, dict(base, grade_id="G2")], [ok_sel], []):
        f.append("double-graded selection accepted")
    if f:
        print("settlement_contract selftest: FAIL")
        for x in f:
            print("  " + x)
        return 1
    print("settlement_contract selftest: PASS (generic 'side', ghost ATS, post-tip capture, combined "
          "estimands, missing estimand and double-grading all rejected; compliant records and the "
          "grandfathered pre-cutoff ledger pass)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    fails = check()
    print(f"settlement contract: {'PASS' if not fails else 'FAIL'} "
          f"(cutoff {CUTOFF}; pre-cutoff records grandfathered)")
    for x in fails[:10]:
        print("  ! " + x)
    raise SystemExit(1 if (fails and "--gate" in sys.argv) else 0)
