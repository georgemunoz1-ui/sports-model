#!/usr/bin/env python3
"""NEVER-ADAPT AUDIT — a do-not-change list is worth nothing unless something checks it.

OWNER SPECIFICATION 2026-08-23 names ten things that must never adapt automatically. Declaring them
is the easy half. This module asserts that each one is bound to a module that actually RUNS in the
healthcheck, and FAILS when any of them is only a promise.

IT FOUND ONE ON ITS FIRST RUN. `same_book_devig_requirement` — the 2026-08-03 ruling that cross-book
best-odds de-vig is INVALID for market probability — was on the list with no enforcing module in the
healthcheck loop. The guard existed in freshness_gates.py, complete with a passing selftest for the
cross-book bases, and had simply never been wired. For that entire period the rule was documented,
implemented, and unexecuted.

The failure mode this exists for is not a missing rule. It is a rule that is present, correct, and
never run — which reads exactly like a rule that works.
"""
from __future__ import annotations

MODULE_ID = "never_adapt_audit"

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adaptive_layers as AL

# Each never-adapt quantity and the module(s) whose EXECUTION enforces it.
ENFORCERS = {
    "evidence_tier_definitions": ["tier_discipline.py", "tier1_board_gate.py"],
    "temporal_leakage_rules": ["settlement_contract.py", "pregame_preflight.py"],
    # added to the never-adapt list with the owner's 2026-08-23 reassignment. This audit FAILED on
    # both the moment they were added, which is the audit doing exactly its job.
    "timing_gates": ["settlement_contract.py", "pregame_preflight.py", "adaptive_layers.py"],
    "immutable_identities": ["artifact_immutability.py", "forecast_registry.py"],
    "source_provenance_requirements": ["result_provenance.py", "acquisition_ledger.py"],
    "same_book_devig_requirement": ["freshness_gates.py"],
    "ats_deadbands": ["ats_ledgers.py"],
    "market_prices_as_predictive_features": ["test_ml_firewall.py", "baseline_offset.py"],
    "registered_forecast_bytes": ["artifact_immutability.py"],
    "grading_definitions": ["grade_ledger.py", "settlement_contract.py"],
    "wager_authority": ["policy_gate.py", "decision_card.py"],
    "promotion_standards": ["policy_gate.py", "paired_eval.py"],
}
HEALTHCHECK = os.path.join(BASE, "harness/healthcheck.py")


def audit(healthcheck_text=None, harness_dir=None):
    """(ok, failures, rows). A quantity passes only when a named enforcer both EXISTS on disk and
    APPEARS in the healthcheck, because a module that is never invoked enforces nothing."""
    hc = healthcheck_text if healthcheck_text is not None else open(HEALTHCHECK).read()
    hd = harness_dir or os.path.join(BASE, "harness")
    fails, rows = [], []
    for q in AL.LAYERS[AL.NEVER]["quantities"]:
        mods = ENFORCERS.get(q)
        if not mods:
            fails.append(f"{q}: on the never-adapt list with NO enforcing module named")
            rows.append({"quantity": q, "enforcers": [], "wired": [], "ok": False})
            continue
        present = [m for m in mods if os.path.exists(os.path.join(hd, m))]
        wired = [m for m in present if m[:-3] in hc]
        ok = bool(wired)
        if not ok:
            fails.append(f"{q}: enforcer(s) {mods} present={present} but NONE runs in the "
                         f"healthcheck — the rule is documented and never executed")
        rows.append({"quantity": q, "enforcers": mods, "present": present, "wired": wired, "ok": ok})
    return (not fails), fails, rows


def selftest():
    f = []
    ok, ff, rows = audit()
    if not ok:
        f.append(f"live audit failed: {ff}")
    if len(rows) != len(AL.LAYERS[AL.NEVER]["quantities"]):
        f.append("the audit did not cover every never-adapt quantity")
    # the audit must FAIL when an enforcer is not wired, and it must not be satisfied by mere
    # existence on disk
    ok2, ff2, _ = audit(healthcheck_text="nothing is wired here")
    if ok2:
        f.append("the audit PASSED against a healthcheck that runs nothing")
    if len(ff2) != len(AL.LAYERS[AL.NEVER]["quantities"]):
        f.append(f"an empty healthcheck produced {len(ff2)} failures, expected one per quantity")
    # ...and when an enforcer is named but absent from disk
    ok3, ff3, _ = audit(harness_dir="/nonexistent")
    if ok3:
        f.append("the audit passed with no enforcing module present on disk")
    # a quantity with no enforcer named at all is a failure, not a skip
    saved = ENFORCERS.pop("ats_deadbands")
    try:
        ok4, ff4, _ = audit()
        if ok4 or not any("NO enforcing module named" in x for x in ff4):
            f.append("a never-adapt quantity with no named enforcer was skipped instead of failed")
    finally:
        ENFORCERS["ats_deadbands"] = saved
    print("never_adapt_audit selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    ok, ff, rows = audit()
    print(f"never-adapt audit: {'PASS' if ok else f'FAIL ({len(ff)})'}")
    for r in rows:
        print(f"  {'OK ' if r['ok'] else 'GAP'}  {r['quantity']:40s} {', '.join(r.get('wired') or []) or '(unenforced)'}")
    for x in ff:
        print("  ! " + x)
    sys.exit(0 if ok else 1)
