#!/usr/bin/env python3
"""RJ-002 — the date-blocked out-of-fold uncertainty replay over the evidence-bound pool.

WHAT THIS COMPUTES. The registered estimand (harness/uncertainty_estimand.py): the SD across date
blocks of the block-mean signed calibration residual r_b = mean_i(y_i - p_i), ddof=1, where p_i is
the FROZEN champion's probability computed from strictly-as-of features and y_i is a canonical
outcome. Blocks are slate dates because forecasts on one day share a feature vintage and model
state.

ADMISSIBILITY (all four required per row, refused otherwise, refusals enumerated):
  1. the as-of dataset carries the row (features strictly before the slate date — the leakage rule
     is build_ml_asof's, not re-derived here);
  2. the results row is canonical: status=final, result_status=FINAL, source_tier=1;
  3. the results row is EVIDENCE-BOUND (non-empty evidence_sha256) — RJ-001's product, and the
     reason this replay could not run before provenance bound;
  4. the game key is a real integer gamePk so the deployed seed policy (seed = 722 + gamePk,
     30,000 draws) reproduces byte-for-byte.
Owner-relayed or provisional outcomes NEVER enter: they are descriptive-only by standing rule, and
an uncertainty estimator fed unverified outcomes would launder them into decisions.

WHAT THIS IS NOT (the four impostors are refused by construction — the estimand module names
them): Bernoulli outcome SD, cross-game dispersion, Monte Carlo error, prior-parameter SD.

COVERAGE VALIDATION is out-of-fold too: for each block b, an interval mean_{-b} +/- 1.96*s_{-b} is
formed WITHOUT b, and we record whether r_b lands inside. In-sample coverage of the fitting set
would validate nothing.

KNOWN LIMITATIONS (reported, not hidden):
  - V13's design freeze (2026-08-10) used the early season for model selection; pre-freeze blocks
    test the frozen arithmetic out-of-fold in features and outcomes but not out-of-fold in DESIGN.
    The post-freeze subset is reported separately so the reader can see both.
  - Replay rows use only retained as-of starter records; deployed boards also carried
    search-identified starters. Replay dose <= deployed dose on stale-window dates.

Usage: python3 harness/rj002_oof_replay.py [--selftest]
Writes data/audit/2026-08-27_rj002_oof_replay.json (content-addressed, wall clock only in
created_utc).
"""
from __future__ import annotations

MODULE_ID = "rj002_oof_replay"

import csv
import hashlib
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import run_v13_historical as V13
import uncertainty_estimand as UE

DATASET = "data/mlb/ml_asof/dataset.jsonl"
RESULTS = "data/backfill/mlb/2026/results.csv"
OUT = "data/audit/2026-08-27_rj002_oof_replay.json"
SEED_BASE = 722          # the registered replay seed policy: seed = SEED_BASE + gamePk
SIMS = 30000
FREEZE_DATE = "2026-08-10"   # V13 design freeze (V13-FREEZE-2026-08-10)
Z = 1.96


def canonical_results():
    out = {}
    for r in csv.DictReader(open(RESULTS)):
        key = r["game_id"].rsplit(":", 1)[1]
        out[key] = r
    return out


def replay():
    res = canonical_results()
    blocks, refusals = {}, {"NOT_CANONICAL_FINAL": 0, "NOT_EVIDENCE_BOUND": 0,
                            "NONINT_PK_SEED_POLICY": 0, "NO_RESULT_ROW": 0}
    per_row = []
    for ln in open(DATASET):
        d = json.loads(ln)
        pk = str(d["gamePk"])
        r = res.get(pk)
        if r is None:
            refusals["NO_RESULT_ROW"] += 1
            continue
        if not (r["status"] == "final" and r["result_status"] == "FINAL"
                and r["source_tier"] == "1"):
            refusals["NOT_CANONICAL_FINAL"] += 1
            continue
        if not r["evidence_sha256"]:
            refusals["NOT_EVIDENCE_BOUND"] += 1
            continue
        if not pk.isdigit():
            refusals["NONINT_PK_SEED_POLICY"] += 1
            continue
        spa = V13._sp(d["sp"]["away"] and {
            "era": d["sp"]["away"]["era"], "gs": d["sp"]["away"]["gs"],
            "k": d["sp"]["away"]["k_pct"], "bb": d["sp"]["away"]["bb_pct"]} or {})
        sph = V13._sp(d["sp"]["home"] and {
            "era": d["sp"]["home"]["era"], "gs": d["sp"]["home"]["gs"],
            "k": d["sp"]["home"]["k_pct"], "bb": d["sp"]["home"]["bb_pct"]} or {})
        t = d["team"]
        sim = V13.v13_sim(spa, sph,
                          t["away"] and t["away"]["rf_pg"], t["away"] and t["away"]["ra_pg"],
                          t["home"] and t["home"]["rf_pg"], t["home"] and t["home"]["ra_pg"],
                          d["park_factor"], SEED_BASE + int(pk), SIMS)
        y = int(r["home_win"])
        blocks.setdefault(d["slate_date"], []).append((sim["p_home"], y))
        per_row.append({"gamePk": int(pk), "date": d["slate_date"], "p": sim["p_home"], "y": y})
    return blocks, refusals, per_row


def block_stats(blocks):
    rb = {}
    for date, pairs in sorted(blocks.items()):
        r, err = UE.block_residual(pairs)
        assert err is None, (date, err)
        rb[date] = r
    return rb


def noise_floor(blocks):
    """The shrunk-Bernoulli component of SD(r_b): sqrt(mean_b sum_i p_i(1-p_i) / n_b^2).

    This is a DIAGNOSTIC, not a re-definition. The registered estimand is SD(r_b) as frozen; at
    the pool's block sizes the outcome-noise floor does not fully shrink away, so SD(r_b) sits
    above the purely epistemic component. The excess variance (SD(r_b)^2 - floor^2), floored at
    zero, is reported so the reader can see the split; consuming it in decisions would need its
    own registration."""
    vs = []
    for _, pairs in sorted(blocks.items()):
        n = len(pairs)
        vs.append(sum(p * (1 - p) for p, _ in pairs) / (n * n))
    return math.sqrt(sum(vs) / len(vs))


def oof_coverage(rb):
    """For each block, interval from ALL OTHER blocks; count containment. Genuine out-of-fold."""
    items = sorted(rb.items())
    hits = 0
    for i, (date, r) in enumerate(items):
        others = [v for j, (_, v) in enumerate(items) if j != i]
        m = sum(others) / len(others)
        s = math.sqrt(sum((v - m) ** 2 for v in others) / (len(others) - 1))
        if abs(r - m) <= Z * s:
            hits += 1
    return 100.0 * hits / len(items)


def run():
    blocks, refusals, per_row = replay()
    rb = block_stats(blocks)
    sizes = [len(v) for _, v in sorted(blocks.items())]
    est = UE.estimate({d: v for d, v in blocks.items()})
    cov = oof_coverage(rb)
    grd = UE.grade(len(rb), cluster_sizes=sizes, block_residuals=rb, coverage=cov)
    post = {d: v for d, v in rb.items() if d > FREEZE_DATE}
    post_est = UE.estimate({d: blocks[d] for d in post}) if len(post) >= 2 else None
    rec = {
        "record_id": "RJ-002-OOF-REPLAY-2026-08-27",
        "schema": "ops.rj002_replay.v1",
        "created_utc": None,  # stamped by caller
        "estimand": UE.ESTIMAND, "formula": UE.FORMULA, "block_unit": UE.BLOCK_UNIT,
        "ddof": UE.DDOF,
        "model_identity": "mlb.winner.CHAMPION_V13 (frozen 2026-08-10; arithmetic unchanged)",
        "seed_policy": f"seed = {SEED_BASE} + gamePk, {SIMS} draws (registered replay policy)",
        "inputs": {
            "dataset": DATASET, "dataset_sha256": _sha(DATASET),
            "results": RESULTS, "results_sha256": _sha(RESULTS),
        },
        "pool": {"graded_rows": sum(sizes), "date_blocks": len(rb),
                 "block_size_min": min(sizes), "block_size_max": max(sizes),
                 "refusals": refusals,
                 "eligibility_note": "canonical FINAL tier-1 evidence-bound only; provisional, "
                                     "relayed and descriptive outcomes excluded by rule"},
        "estimate": est,
        "grade": grd,
        "oof_coverage_pct": cov,
        "noise_floor_decomposition": _decomp(est, blocks),
        "post_freeze_subset": {
            "dates": sorted(post), "k": len(post),
            "estimate": post_est,
            "why_separate": "V13's design freeze used the early season for model selection; this "
                            "subset is out-of-fold in design as well as features"},
        "impostors_refused": UE.NOT_THE_ESTIMAND,
        "limitations": [
            "pre-freeze blocks are out-of-fold in features/outcomes but not in design selection",
            "replay starter dose <= deployed dose where starter records were never retained",
            "coverage is validated at the block level (n=k), not per game — the estimand is a "
            "block-level quantity",
        ],
    }
    return rec, per_row


def _decomp(est, blocks):
    s = est.get("sigma_epistemic_pp")
    if s is None:
        return None
    fl = 100.0 * noise_floor(blocks)
    excess_var = max(0.0, (s / 100.0) ** 2 - (fl / 100.0) ** 2)
    return {
        "registered_estimand_sd_pp": s,
        "shrunk_bernoulli_floor_pp": fl,
        "epistemic_excess_sd_pp": 100.0 * math.sqrt(excess_var),
        "reading": "SD(r_b) at these block sizes is dominated by the outcome-noise floor; the "
                   "excess over the floor is the epistemic component. The registered estimand "
                   "stays SD(r_b) (frozen); any decision use of the excess needs its own "
                   "registration — flagged as the RJ-002 finding for owner review.",
    }


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def selftest():
    f = []
    # the coverage check is genuinely out-of-fold: a wildly outlying block must NOT be covered
    rb = {f"d{i}": 0.0 for i in range(10)}; rb["d9"] = 9.9
    if oof_coverage(rb) > 95:
        f.append("outlier block reported as covered")
    # containment: identical residuals cover trivially except degenerate s=0 handling
    rb2 = {f"d{i}": 0.01 * (i % 3) for i in range(12)}
    c = oof_coverage(rb2)
    if not (0 <= c <= 100):
        f.append("coverage out of range")
    # block_residual sign: y=1,p=0.4 -> +0.6
    r, err = UE.block_residual([(0.4, 1)])
    if err or abs(r - 0.6) > 1e-12:
        f.append("block residual sign wrong")
    print("rj002_oof_replay selftest:", "FAIL" if f else "PASS", f or "")
    return 1 if f else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    import datetime as dt
    rec, per_row = run()
    rec["created_utc"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {k: v for k, v in rec.items() if k != "record_sha256"}
    rec["record_sha256"] = hashlib.sha256(
        json.dumps(body, sort_keys=True).encode()).hexdigest()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(rec, open(OUT, "w"), indent=1, sort_keys=True)
    e, g = rec["estimate"], rec["grade"]
    print("RJ-002 REPLAY", rec["record_sha256"][:8])
    print(f"  pool: {rec['pool']['graded_rows']} rows / {rec['pool']['date_blocks']} blocks; "
          f"refusals {rec['pool']['refusals']}")
    print(f"  sigma_epistemic: {e.get('sigma_epistemic_pp')}pp  status {e.get('status')}")
    print(f"  k_eff {g['k_effective']:.1f}  grade {g['grade']}  "
          f"blockers {[b['code'] for b in g['blockers']]}")
    print(f"  OOF coverage {rec['oof_coverage_pct']:.1f}% (nominal 95%)")
    if rec["post_freeze_subset"]["estimate"]:
        pf = rec["post_freeze_subset"]["estimate"]
        print(f"  post-freeze subset k={rec['post_freeze_subset']['k']}: "
              f"sigma {pf.get('sigma_epistemic_pp')}pp status {pf.get('status')}")
