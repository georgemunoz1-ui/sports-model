#!/usr/bin/env python3
"""Date-safe V13 Monte Carlo historical replay + deterministic candidate + same-book market.

WHY THIS EXISTS (owner spec 2026-08-04): the correct "full sims on all data" is a date-safe
HISTORICAL REPLAY over the frozen as-of features -- NOT looping harness/daily_card.py over
historical dates. daily_card reads every final currently on disk with no historical date filter,
which is look-ahead leakage. This runner reads ONLY data/backfill/mlb/2026/features.csv, whose
rows are the strict as-of inputs captured for each game.

Fixes vs engine/score_and_calibrate.py:
  - sims/game configurable (--sims-per-game, default 30000; score_and_calibrate hardcoded 4000)
  - PER-GAME seed = global_seed + int(gamePk): each game's result is independent of row order and
    of parallelism (score_and_calibrate uses one sequential stream, so order changes per-row probs)
  - DATE-ORDERED expanding-window (rolling) calibration, never a random split on the scoring rows
  - full simulated run arrays -> ML win prob, run-line cover probs, totals O/push/U at a captured
    line, projected score+total, and Monte Carlo standard error (score_and_calibrate emits ML only)
  - the Phase-4 candidate d_logistic_2f is computed ONCE per row, deterministic (never simulated)

Model treatment (owner):
  V13            -> Monte Carlo replay (per-game gamePk seed)
  d_logistic_2f  -> one deterministic closed-form calculation per game
  Market         -> same-book two-sided de-vig (only where a same-book close exists; else null)
  Evaluation     -> rolling, date-ordered; no random tuning on the scoring rows

Usage:
  python3 harness/run_v13_historical.py --sims-per-game 30000 --seed 722 \
      --output data/mlb/evaluations/v13_full_30k.jsonl
  python3 harness/run_v13_historical.py --sims-per-game 100000   # final precision check
  python3 harness/run_v13_historical.py --selftest               # determinism + wiring (fast)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import sys

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "engine"))
from hfa import CURRENT as HFA  # HFA-SPLIT single source of truth (engine/hfa.py); no stray literal

FEATURES = "data/backfill/mlb/2026/features.csv"
RESULTS = "data/backfill/mlb/2026/results.csv"
CAND_CFG = "data/mlb/ml_asof/p3_candidate_config.json"
CAND_CANONICAL_SHA = "132523ac86695b851fd8e4c88815da0416a79421e76ba0cce1c9bce24dfe096b"
CAND_FILE_SHA = "eede422d0659e485ecdfefb40938aaab5d705bd1aa873720460977cd7a573f47"

LG_RPG = 4.45; LG_ERA = 4.20; LG_K = 22.0; LG_BB = 8.5; LG_BIP = 1 - (LG_K + LG_BB) / 100
# HFA imported from engine/hfa.py above (CURRENT == 1.005); stamped per output row.


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def shrunk(e, g):
    e = LG_ERA if e is None else e
    g = g or 0
    w = g / (g + 8)
    return w * e + (1 - w) * LG_ERA


def rs(era, gs, k, bb):
    era = LG_ERA if era is None else era
    gs = gs or 0
    k = LG_K if k is None else k
    bb = LG_BB if bb is None else bb
    return max(2.2, shrunk(era, gs) - ((k - bb) - 13.5) * 0.03)


def bipf(k, bb):
    k = LG_K if k is None else k
    bb = LG_BB if bb is None else bb
    return max(0.45, 1 - (k + bb) / 100)


def load_candidate_beta():
    """Load + double-hash-verify the frozen candidate config (refuse on drift)."""
    raw = open(CAND_CFG, "rb").read()
    if hashlib.sha256(raw).hexdigest() != CAND_FILE_SHA:
        raise RuntimeError("candidate config file-bytes hash drift -- refusing")
    cfg = json.loads(raw)
    if hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest() != CAND_CANONICAL_SHA:
        raise RuntimeError("candidate config canonical hash drift -- refusing")
    return cfg["beta"]


def candidate_p(rf_a, ra_a, rf_h, ra_h, era_a, gs_a, era_h, gs_h, beta):
    """Deterministic closed-form d_logistic_2f, computed ONCE. None if team form incomplete."""
    if None in (rf_a, ra_a, rf_h, ra_h):
        return None
    x1 = (rf_h - ra_h) - (rf_a - ra_a)
    x2 = shrunk(era_a, gs_a) - shrunk(era_h, gs_h)
    z = beta[0] + beta[1] * x1 + beta[2] * x2
    return float(1.0 / (1.0 + np.exp(-z)))


def v13_sim(sp_a, sp_h, rf_a, ra_a, rf_h, ra_h, pf, seed, n, total_line=None):
    """V13 Monte Carlo, PER-GAME seeded. Keeps run arrays -> full ML/RL/totals distributions."""
    rng = np.random.default_rng(seed)
    oa = (rf_a or LG_RPG) / LG_RPG; oh = (rf_h or LG_RPG) / LG_RPG
    pena = 0.55 * (ra_a or LG_RPG) + 0.45 * LG_RPG
    penh = 0.55 * (ra_h or LG_RPG) + 0.45 * LG_RPG
    rah = rs(sp_h["era"], sp_h["gs"], sp_h["k"], sp_h["bb"])
    raa = rs(sp_a["era"], sp_a["gs"], sp_a["k"], sp_a["bb"])
    pf = pf or 1.0
    pfa = 1 + (pf - 1) * (bipf(sp_h["k"], sp_h["bb"]) / LG_BIP)
    pfh = 1 + (pf - 1) * (bipf(sp_a["k"], sp_a["bb"]) / LG_BIP)
    ip = np.clip(rng.normal(5.4, 1.3, n), 2, 8); ip2 = np.clip(rng.normal(5.4, 1.3, n), 2, 8)
    ma = (rah / 9 * ip + penh / 9 * (9 - ip)) * oa * pfa
    mh = (raa / 9 * ip2 + pena / 9 * (9 - ip2)) * oh * pfh * HFA
    ka = sp_h["k"] if sp_h["k"] is not None else LG_K
    kh = sp_a["k"] if sp_a["k"] is not None else LG_K
    sa = np.clip(1.8 + (ka - LG_K) * 0.16, 1.2, 6); sh = np.clip(1.8 + (kh - LG_K) * 0.16, 1.2, 6)
    ra = rng.poisson(rng.gamma(sa, np.maximum(ma, 0.3) / sa))
    rh = rng.poisson(rng.gamma(sh, np.maximum(mh, 0.3) / sh))
    tie = ra == rh
    hx = rng.random(n) < (0.5 + 0.04 * np.sign(pena - penh))
    hw = np.where(tie, hx, rh > ra)
    tot = ra + rh + tie * rng.poisson(1.0, n)
    p = float(hw.mean())
    out = {
        "p_home": p,
        "mc_se": float(np.sqrt(p * (1 - p) / n)),
        "proj_away": round(float(ra.mean()), 3),
        "proj_home": round(float(rh.mean()), 3),
        "proj_total": round(float(tot.mean()), 3),
        "rl_home_cover_1_5": float(np.mean((rh - ra) >= 2)),
        "rl_away_cover_1_5": float(np.mean((ra - rh) >= 2)),
    }
    if total_line is not None:
        # No market total line lives in the frozen features, so we score the simulated total
        # distribution AT THE REALIZED TOTAL. This is a PIT-style calibration check of the totals
        # distribution, NOT a market over/under settlement -- named so it can't be mistaken for one.
        out["scored_at_realized_total"] = total_line
        out["p_sim_over_realized"] = float(np.mean(tot > total_line))
        out["p_sim_eq_realized"] = float(np.mean(tot == total_line))
        out["p_sim_under_realized"] = float(np.mean(tot < total_line))
    return out


def american_devig(a, h):
    def imp(m):
        return 100 / (m + 100) if m > 0 else (-m) / ((-m) + 100)
    ia, ih = imp(a), imp(h)
    return ih / (ia + ih)  # p_home, proportional


def load_market_by_gamepk():
    """Same-book two-sided close ML by gamePk, where present. HONEST: the 2026 close_* columns are
    sparse (~30 rows) and flagged as OPENINGS/contaminated -- so market is null for ~99% of games."""
    m = {}
    for r in csv.DictReader(open(RESULTS)):
        gid = r["game_id"].split(":")[-1]
        a, h = r.get("close_ml_away"), r.get("close_ml_home")
        if a and h:
            try:
                m[gid] = round(american_devig(float(a), float(h)), 4)
            except ValueError:
                pass
    return m


def load_rows():
    rows = []
    for r in csv.DictReader(open(FEATURES)):
        if r["home_win"] == "":
            continue  # no outcome -> ineligible
        f = json.loads(r["features"])
        rows.append({
            "gamePk": r["gamePk"], "date": r["date"], "away": r["away"], "home": r["home"],
            "home_win": int(r["home_win"]),
            "actual_total": (int(r["total"]) if r["total"] not in ("", None) else None),
            "actual_margin": (int(r["margin"]) if r["margin"] not in ("", None) else None),
            "f": f, "inputs_hash": hashlib.sha256(r["features"].encode()).hexdigest(),
        })
    rows.sort(key=lambda r: (r["date"], r["gamePk"]))
    return rows


def _sp(d):
    d = d or {}
    return {"era": d.get("era"), "gs": d.get("gs") or 0, "k": d.get("k"), "bb": d.get("bb")}


def run(sims, seed, out_path):
    beta = load_candidate_beta()
    market = load_market_by_gamepk()
    rows = load_rows()
    model_hash = _sha(__file__)
    feat_hash = _sha(FEATURES)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    built = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n_written = n_sp = 0
    with open(out_path, "w") as fh:
        for r in rows:
            f = r["f"]; spa = _sp(f["away_sp"]); sph = _sp(f["home_sp"])
            has_sp = spa["era"] is not None and sph["era"] is not None
            g_seed = seed + int(r["gamePk"])
            v = v13_sim(spa, sph, f.get("away_rf"), f.get("away_ra"), f.get("home_rf"),
                        f.get("home_ra"), f.get("park"), g_seed, sims,
                        total_line=r["actual_total"])  # PIT check: totals dist vs the realized total
            cand = candidate_p(f.get("away_rf"), f.get("away_ra"), f.get("home_rf"), f.get("home_ra"),
                               spa["era"], spa["gs"], sph["era"], sph["gs"], beta)
            rec = {
                "gamePk": r["gamePk"], "date": r["date"], "away": r["away"], "home": r["home"],
                "built_utc": built, "inputs_hash": r["inputs_hash"], "model_hash": model_hash,
                "features_file_sha256": feat_hash, "seed_base": seed, "game_seed": g_seed,
                "sims_per_game": sims, "hfa": HFA, "sp_mature": has_sp,
                "v13": v,
                "candidate_p_home": (round(cand, 6) if cand is not None else None),
                "candidate_model": "ml.d_logistic_2f.p4.cfg132523ac (deterministic_closed_form)",
                "market_p_home_samebook": market.get(r["gamePk"]),
                "market_note": ("same-book close de-vig" if r["gamePk"] in market
                                else "no same-book close on file (2026 close_* sparse/contaminated)"),
                "outcome": {"home_win": r["home_win"], "actual_total": r["actual_total"],
                            "actual_margin": r["actual_margin"]},
            }
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
            n_written += 1
            n_sp += int(has_sp)
    print(f"wrote {n_written} rows -> {out_path} ({n_sp} with both SP records; sims/game={sims}; "
          f"per-game seed={seed}+gamePk)")
    evaluate(out_path)


def _metrics(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6); y = np.asarray(y, float)
    return (float(np.mean((p - y) ** 2)),
            float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
            float(np.mean((p >= 0.5) == y)))


def _fit_T(p, y):
    """Temperature that minimizes log loss on (p,y). Grid 0.50..2.00."""
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6); y = np.asarray(y, float)
    lg = np.log(p / (1 - p))
    best, bT = 1e9, 1.0
    for T in np.arange(0.50, 2.01, 0.01):
        pc = np.clip(1 / (1 + np.exp(-lg / T)), 1e-6, 1 - 1e-6)
        ll = -np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))
        if ll < best:
            best, bT = ll, T
    return float(bT)


def evaluate(out_path):
    recs = [json.loads(l) for l in open(out_path)]
    recs.sort(key=lambda r: (r["date"], r["gamePk"]))
    p = np.array([r["v13"]["p_home"] for r in recs]); y = np.array([r["outcome"]["home_win"] for r in recs])
    print("\n=== V13 historical replay — evaluation ===")
    b, l, a = _metrics(p, y)
    print(f"  ALL eligible n={len(recs)}: Brier {b:.4f}  logloss {l:.4f}  acc {a:.1%}  home base {y.mean():.3f}")
    sp = [r for r in recs if r["sp_mature"]]
    if sp:
        ps = np.array([r["v13"]["p_home"] for r in sp]); ysp = np.array([r["outcome"]["home_win"] for r in sp])
        b2, l2, a2 = _metrics(ps, ysp)
        print(f"  both-SP subset n={len(sp)}: Brier {b2:.4f}  logloss {l2:.4f}  acc {a2:.1%}")
    # ROLLING date-ordered OOS calibration: expanding weekly window, T fit on strictly-prior weeks
    def wk(d): return dt.date.fromisoformat(d).isocalendar()[:2]
    weeks = sorted({wk(r["date"]) for r in recs})
    oos_p, oos_y, oos_raw = [], [], []
    for i, w in enumerate(weeks):
        if i < 3:  # burn-in: need prior weeks to fit T
            continue
        prior = [r for r in recs if wk(r["date"]) < w]
        cur = [r for r in recs if wk(r["date"]) == w]
        if len(prior) < 50 or not cur:
            continue
        T = _fit_T([r["v13"]["p_home"] for r in prior], [r["outcome"]["home_win"] for r in prior])
        for r in cur:
            pp = np.clip(r["v13"]["p_home"], 1e-6, 1 - 1e-6)
            lg = np.log(pp / (1 - pp))
            oos_p.append(float(1 / (1 + np.exp(-lg / T)))); oos_y.append(r["outcome"]["home_win"])
            oos_raw.append(r["v13"]["p_home"])
    if oos_p:
        bo, lo, ao = _metrics(oos_p, oos_y)
        # raw (uncalibrated) V13 on exactly the same OOS rows, for an apples-to-apples comparison
        br, lr, ar = _metrics(oos_raw, oos_y)
        print(f"  ROLLING OOS (expanding weekly calibration, n={len(oos_p)}):")
        print(f"      raw V13      Brier {br:.4f}  logloss {lr:.4f}  acc {ar:.1%}")
        print(f"      calibrated   Brier {bo:.4f}  logloss {lo:.4f}  acc {ao:.1%}")
    # paired vs same-book market (honest: essentially unavailable)
    mk = [r for r in recs if r["market_p_home_samebook"] is not None]
    print(f"  same-book market benchmark available on {len(mk)}/{len(recs)} games "
          f"({'no clean paired comparison possible' if len(mk) < 50 else 'paired below'})")
    if len(mk) >= 50:
        pv = np.array([r["v13"]["p_home"] for r in mk]); pm = np.array([r["market_p_home_samebook"] for r in mk])
        ym = np.array([r["outcome"]["home_win"] for r in mk])
        d = (pv - ym) ** 2 - (pm - ym) ** 2
        print(f"  paired dBrier V13-market: {d.mean():+.5f} +/- {d.std(ddof=1)/np.sqrt(len(d)):.5f} SE (n={len(mk)})")
    print("  candidate d_logistic_2f is deterministic (one calc/row); scored separately, never simulated.")


def selftest():
    """Fast wiring + determinism proof (no full run)."""
    fails = []
    beta = load_candidate_beta()
    if len(beta) != 3:
        fails.append("candidate beta load")
    spa = {"era": 4.0, "gs": 15, "k": 22.0, "bb": 8.0}
    sph = {"era": 3.2, "gs": 18, "k": 26.0, "bb": 6.0}
    a1 = v13_sim(spa, sph, 4.5, 4.2, 4.9, 4.1, 1.0, 722 + 823244, 4000, total_line=8)
    a2 = v13_sim(spa, sph, 4.5, 4.2, 4.9, 4.1, 1.0, 722 + 823244, 4000, total_line=8)
    if a1 != a2:
        fails.append("per-game seed NOT deterministic on repeat")
    a3 = v13_sim(spa, sph, 4.5, 4.2, 4.9, 4.1, 1.0, 722 + 999999, 4000, total_line=8)
    if a3["p_home"] == a1["p_home"]:
        fails.append("different gamePk seed gave identical p (suspicious)")
    if not (0 <= a1["p_home"] <= 1 and a1["mc_se"] > 0):
        fails.append("p_home/se sanity")
    if not abs((a1["p_sim_over_realized"] + a1["p_sim_eq_realized"]
                + a1["p_sim_under_realized"]) - 1.0) < 1e-9:
        fails.append("totals dist does not sum to 1")
    c = candidate_p(4.5, 4.2, 4.9, 4.1, 4.0, 15, 3.2, 18, beta)
    if not (0 < c < 1):
        fails.append("candidate deterministic calc")
    if candidate_p(None, 4.2, 4.9, 4.1, 4.0, 15, 3.2, 18, beta) is not None:
        fails.append("candidate should be null on missing team form")
    # order-invariance: seed depends only on gamePk, not iteration order
    if v13_sim(spa, sph, 4.5, 4.2, 4.9, 4.1, 1.0, 722 + 823244, 4000)["p_home"] != a1["p_home"]:
        fails.append("order-invariance (same seed same result)")
    if fails:
        print("run_v13_historical selftest: FAIL")
        for x in fails:
            print("  " + x)
        return 1
    print("run_v13_historical selftest: PASS (per-game-seed determinism, order-invariance, "
          "totals dist sums to 1, deterministic candidate + null guard)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default=FEATURES)
    ap.add_argument("--sims-per-game", type=int, default=30000)
    ap.add_argument("--seed", type=int, default=722)
    ap.add_argument("--split", default="rolling", choices=["rolling"])
    ap.add_argument("--output", default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        raise SystemExit(selftest())
    out = args.output or f"data/mlb/evaluations/v13_full_{args.sims_per_game // 1000}k.jsonl"
    raise SystemExit(run(args.sims_per_game, args.seed, out))
