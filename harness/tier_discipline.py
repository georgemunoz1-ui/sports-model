#!/usr/bin/env python3
"""Canonical-tier discipline: one shared predicate, and a gate that locks today's exposure.

WHY (2026-08-16 audit): a 14-agent repository sweep found that NOT ONE outcome-label consumer of
data/backfill/mlb/2026/results.csv enforces the owner's tier-1-only rule. Every consumer selects
`status == "final" and total != ""`, which admits all 126 legacy tier-2/3 provisional rows plus 10
tier-1 rows whose result_status is still PROVISIONAL (winner proven by standings arithmetic, score
not officially captured). The tier column is then DROPPED at the feature-write boundary, so
provenance dies there and cannot be recovered downstream.

Why this module gates rather than patches:
  Applying the predicate inside harness/daily_card.py, harness/build_p4_slate.py,
  sports/enrich_mlb.py and harness/build_ml_asof.py would change the as-of team form that the
  FROZEN V13 identity (ml.v13_1.hfa1005.card.s722n30000) consumes. Measured impact: 30 of 62 team
  labels on the 2026-08-14 slate move (BOS 5.391/3.696 over 23 games -> 4.312/4.375 over 16).
  Silently changing a frozen model's inputs is an R3 violation and would put a discontinuity in the
  middle of a live prospective record. That flip is an OWNER decision, not a repair.

  So this module does the part that is unambiguously correct: it measures the exposure exactly,
  writes it to a baseline artifact, and FAILS the healthcheck if the exposure GROWS. Today's
  contamination is thereby frozen and enumerated; tomorrow's cannot arrive unnoticed.

Usage: python3 harness/tier_discipline.py [--gate] [--rebaseline] [--selftest]
"""
from __future__ import annotations
import csv, json, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
RESULTS = "data/backfill/mlb/2026/results.csv"
BASELINE = "data/audit/tier_exposure_baseline.json"

# The consumers the sweep found reading outcome labels with a tier-blind predicate. Each entry is
# (file:line, what it feeds). Kept as data so the report names them rather than hand-waving.
TIER_BLIND_LABEL_CONSUMERS = [
    ("harness/build_ml_asof.py:126", "ML training/eval dataset labels", "CRITICAL"),
    ("harness/build_p4_slate.py:72", "live slate as-of team form (production forecast path)", "CRITICAL"),
    ("sports/enrich_mlb.py:81", "features.csv labels", "CRITICAL"),
    ("sports/enrich_mlb.py:15", "features.csv as-of rf/ra accumulator", "HIGH"),
    ("harness/daily_card.py:30", "daily card team_rf/team_ra — direct V13 card inputs", "HIGH"),
    ("harness/ml_v2_experiment.py:54", "MLV2 rest_edge / form10_edge features", "HIGH"),
    ("harness/build_p4_slate.py:121", "slate completeness/contiguity reconciler", "MEDIUM"),
    ("harness/healthcheck.py:33", "finals>=1505 threshold counts provisional rows", "MEDIUM"),
    ("sports/schema.py:72", "operator-facing 'N finals' confirmation line", "MEDIUM"),
    ("harness/result_content_checks.py:41", "_finals() helper (defensible for echo detection)", "LOW"),
]


def is_canonical_final(row) -> bool:
    """The predicate every outcome-label consumer SHOULD use. Owner ruling 2026-08-16."""
    return (row.get("status") == "final"
            and row.get("source_tier") == "1"
            and row.get("result_status") == "FINAL"
            and row.get("total") not in ("", None))


def naive_final(row) -> bool:
    """The predicate every outcome-label consumer ACTUALLY uses today."""
    return row.get("status") == "final" and row.get("total") not in ("", None)


def exposure(rows=None):
    rows = rows if rows is not None else list(csv.DictReader(open(RESULTS)))
    naive = [r for r in rows if naive_final(r)]
    canon = [r for r in rows if is_canonical_final(r)]
    leaked = [r for r in naive if not is_canonical_final(r)]
    by_tier, by_date = {}, {}
    for r in leaked:
        k = f'tier{r.get("source_tier") or "blank"}/{r.get("result_status") or "blank"}'
        by_tier[k] = by_tier.get(k, 0) + 1
        by_date[r["date"]] = by_date.get(r["date"], 0) + 1
    return {"rows": len(rows), "naive_finals": len(naive), "canonical_finals": len(canon),
            "leaked_into_naive_predicate": len(leaked),
            "leaked_by_class": dict(sorted(by_tier.items())),
            "leaked_by_date": dict(sorted(by_date.items()))}


def run(gate=False, rebaseline=False):
    e = exposure()
    os.makedirs("data/audit", exist_ok=True)
    if rebaseline or not os.path.exists(BASELINE):
        json.dump({"note": "Frozen exposure baseline. A RISE means new non-tier-1 rows became visible "
                           "to tier-blind consumers — that is a gate failure, not a warning. A FALL is "
                           "fine (contamination was removed). Rebaseline only on an owner decision.",
                   "consumers": TIER_BLIND_LABEL_CONSUMERS, "exposure": e},
                  open(BASELINE, "w"), indent=1)
        print(f"tier exposure baseline written: {e['leaked_into_naive_predicate']} leaked rows")
        return 0
    base = json.load(open(BASELINE))["exposure"]
    grew = e["leaked_into_naive_predicate"] > base["leaked_into_naive_predicate"]
    print(f"tier exposure: {e['leaked_into_naive_predicate']} rows admitted by the tier-blind predicate "
          f"but not canonical (baseline {base['leaked_into_naive_predicate']}); "
          f"canonical finals {e['canonical_finals']} of {e['naive_finals']} naive")
    if grew:
        print(f"  ! EXPOSURE GREW by {e['leaked_into_naive_predicate'] - base['leaked_into_naive_predicate']}")
        for k, v in e["leaked_by_class"].items():
            print(f"    {k}: {v}")
    return 1 if (gate and grew) else 0


def selftest():
    fails = []
    rows = list(csv.DictReader(open(RESULTS)))
    e = exposure(rows)
    if e["canonical_finals"] >= e["naive_finals"]:
        fails.append("canonical finals should be a strict subset of naive finals while legacy rows exist")
    # falsification: a synthetic tier-3 row must be counted as leaked, a tier-1 FINAL must not
    t3 = {"status": "final", "total": "9", "source_tier": "3", "result_status": "PROVISIONAL", "date": "2026-01-01"}
    t1 = {"status": "final", "total": "9", "source_tier": "1", "result_status": "FINAL", "date": "2026-01-01"}
    t1p = {"status": "final", "total": "9", "source_tier": "1", "result_status": "PROVISIONAL", "date": "2026-01-01"}
    if is_canonical_final(t3):
        fails.append("tier-3 row wrongly accepted as canonical")
    if not is_canonical_final(t1):
        fails.append("tier-1 FINAL row wrongly rejected")
    if is_canonical_final(t1p):
        fails.append("tier-1 PROVISIONAL row wrongly accepted (the 10-row winner-proof class)")
    if exposure([t3, t1, t1p])["leaked_into_naive_predicate"] != 2:
        fails.append("exposure count wrong on the synthetic fixture")
    if os.path.exists(BASELINE):
        base = json.load(open(BASELINE))["exposure"]
        if e["leaked_into_naive_predicate"] > base["leaked_into_naive_predicate"]:
            fails.append(f"live exposure {e['leaked_into_naive_predicate']} exceeds frozen baseline "
                         f"{base['leaked_into_naive_predicate']}")
    if fails:
        print("tier_discipline selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print(f"tier_discipline selftest: PASS (canonical predicate rejects tier-3 and tier-1-PROVISIONAL, "
          f"accepts tier-1 FINAL; live exposure {e['leaked_into_naive_predicate']} rows at or below baseline)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    raise SystemExit(run(gate="--gate" in sys.argv, rebaseline="--rebaseline" in sys.argv))
