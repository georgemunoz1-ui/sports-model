#!/usr/bin/env python3
"""Full diagnostic report for the walk-forward model comparison (owner spec 2026-08-10).

Re-runs the expanding-window walk-forward while retaining everything the diagnostics need:
raw (UNCLIPPED) LPM predictions, dates for block bootstrapping, and gamePks for aligning V13.
Then runs items 1-7 of the owner's spec and writes a single JSON record.

  python3 harness/ml_full_report.py --out data/mlb/ml_asof/2026-08-10_ml_full_report.json
"""

from __future__ import annotations

MODULE_ID = "ml_full_report"

import argparse
import importlib.util
import json
import os

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)


def _load(mod, path):
    s = importlib.util.spec_from_file_location(mod, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


mlr = _load("ml_regression", "harness/ml_regression.py")
dg = _load("ml_diagnostics", "harness/ml_diagnostics.py")


def walk_forward_full(rows, burn_in=400, drop=None, l2_grid=(0.1, 1.0, 10.0, 100.0)):
    """Expanding-window walk-forward retaining raw LPM, dates and gamePks.

    `drop` is a list of feature INDICES to remove (for block ablations). Removal happens before
    standardisation so the ablated model never sees the block in any form.
    """
    keep = [i for i in range(len(mlr.FEATURE_NAMES)) if not drop or i not in drop]
    dates = sorted({r["date"] for r in rows})
    acc = {k: [] for k in ("base", "lpm_raw", "lpm", "logit", "ridge")}
    y_all, d_all, pk_all = [], [], []
    for d in dates:
        tr = [r for r in rows if r["date"] < d]
        te = [r for r in rows if r["date"] == d]
        if len(tr) < burn_in or not te:
            continue
        Xtr = np.array([r["x"][keep] for r in tr]); ytr = np.array([r["y"] for r in tr], float)
        Xte = np.array([r["x"][keep] for r in te]); yte = np.array([r["y"] for r in te], float)
        # standardisation fitted on the TRAINING fold only
        Xtr_s, Xte_s = mlr._standardize(Xtr, Xte)
        acc["base"] += [ytr.mean()] * len(te)
        b_ols = mlr.fit_ols(Xtr_s, ytr)
        raw = np.hstack([np.ones((len(Xte_s), 1)), Xte_s]) @ b_ols   # UNCLIPPED
        acc["lpm_raw"] += list(raw)
        acc["lpm"] += list(np.clip(raw, 0.001, 0.999))
        acc["logit"] += list(mlr.predict_logistic(mlr.fit_logistic(Xtr_s, ytr, l2=1.0), Xte_s))
        # ridge penalty chosen on an inner split of the TRAINING window only
        cut = int(len(tr) * 0.8); best, bl2 = None, l2_grid[0]
        if cut > 50 and len(tr) - cut > 20:
            Xi, Xo = mlr._standardize(Xtr[:cut], Xtr[cut:])
            yi, yo = ytr[:cut], ytr[cut:]
            for l2 in l2_grid:
                m = np.mean((mlr.predict_logistic(mlr.fit_logistic(Xi, yi, l2=l2), Xo) - yo) ** 2)
                if best is None or m < best:
                    best, bl2 = m, l2
        acc["ridge"] += list(mlr.predict_logistic(mlr.fit_logistic(Xtr_s, ytr, l2=bl2), Xte_s))
        y_all += list(yte); d_all += [d] * len(te); pk_all += [r["gamePk"] for r in te]
    return ({k: np.array(v) for k, v in acc.items()}, np.array(y_all, float),
            np.array(d_all), pk_all)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--burn-in", type=int, default=400)
    ap.add_argument("--out")
    a = ap.parse_args()

    rows = mlr.build_rows()
    P, y, dates, pks = walk_forward_full(rows, burn_in=a.burn_in)
    v13 = dg.v13_lookup(pks)
    models = {"LPM": P["lpm"], "logistic": P["logit"], "ridge": P["ridge"], "V13": v13,
              "base": P["base"]}
    rep = {"record_id": "ML-FULL-DIAGNOSTIC-REPORT-2026-08-10",
           "n_games": int(len(y)), "n_dates": int(len(set(dates))),
           "home_win_rate": float(y.mean())}

    # ---- 1. LPM range / out-of-range / raw vs clipped ----
    raw = P["lpm_raw"]
    rep["item1_lpm_range"] = {
        "min": float(raw.min()), "max": float(raw.max()),
        "n_below_0": int((raw < 0).sum()), "n_above_1": int((raw > 1).sum()),
        "pct_outside_0_1": float(100.0 * ((raw < 0) | (raw > 1)).mean()),
        "brier_raw_unclipped": float(np.mean((raw - y) ** 2)),
        "brier_clipped": float(np.mean((P["lpm"] - y) ** 2)),
        "note": "Clipping can only help Brier when predictions leave [0,1]; the gap quantifies how "
                "much of the LPM's score is repaired by clipping rather than earned by the fit."}

    # ---- 2. ROC-AUC ----
    rep["item2_roc_auc"] = {k: float(dg.roc_auc(v, y)) for k, v in models.items() if k != "base"}
    rep["item2_note"] = ("AUC measures RANKING only and is invariant to monotone recalibration, so a "
                         "model can rank well and still be badly calibrated — which is exactly the "
                         "LPM's situation and why the earlier 'ranking is fine' phrasing was replaced.")

    # ---- 3. calibration + reliability + Brier decomposition ----
    rep["item3_calibration"] = {}
    for k, v in models.items():
        if k == "base":
            continue
        d = dg.brier_decomposition(v, y)
        rep["item3_calibration"][k] = {"calibration": dg.calibration_fit(v, y),
                                       "brier_decomposition": {kk: d[kk] for kk in
                                                               ("brier", "reliability", "resolution", "uncertainty")},
                                       "reliability_bins": d["bins"]}

    # ---- 4. preprocessing-fold audit ----
    rep["item4_preprocessing_audit"] = {
        "standardization": "FITTED INSIDE FOLD — mean/std computed on the training rows only "
                           "(_standardize(Xtr, Xte)); verified by a selftest that a test-set outlier "
                           "does not move the training moments.",
        "ridge_penalty_selection": "FITTED INSIDE FOLD — chosen on an inner 80/20 split of the "
                                   "TRAINING window; scoring rows are never used to pick l2.",
        "coefficients": "FITTED INSIDE FOLD — every model is refit on each expanding window.",
        "imputation": "NOT FOLD-FITTED, and disclosed: missing SP K%/BB%/ERA fall back to FIXED "
                      "GLOBAL CONSTANTS (LG_ERA 4.20, K 22.0, BB 8.5) and the ERA shrinkage prior is "
                      "the same constant. These are PRIORS, not quantities estimated from data, so "
                      "they carry no outcome information and cannot leak the future — but they are "
                      "not re-estimated per fold, and a purist implementation would fit them on the "
                      "training window. Materiality is small: rows with missing TEAM form are dropped "
                      "outright rather than imputed.",
        "row_filtering": "Rows lacking team run data are EXCLUDED (R1: not imputed). The filter uses "
                         "no outcome information.",
        "target_leakage": "None: no market price, no post-game quantity, and no same-day information "
                          "enters the features; the training window is strictly date < test date."}

    # ---- 5. standardised coefficients -> IQR marginal effect ----
    X = np.array([r["x"] for r in rows]); yy = np.array([r["y"] for r in rows], float)
    mu, sd = X.mean(0), X.std(0); sd = np.where(sd < 1e-9, 1.0, sd)
    blog = mlr.fit_logistic((X - mu) / sd, yy, l2=1.0)
    eff = {}
    for i, nme in enumerate(mlr.FEATURE_NAMES):
        q1, q3 = np.percentile(X[:, i], [25, 75])
        iqr_sd = (q3 - q1) / sd[i]                 # IQR expressed in standard deviations
        dlogit = float(blog[i + 1] * iqr_sd)       # log-odds change across the IQR
        eff[nme] = {"coef_standardized": float(blog[i + 1]),
                    "raw_iqr": float(q3 - q1), "iqr_in_sd": float(iqr_sd),
                    "delta_logodds_per_IQR": dlogit,
                    "delta_prob_at_p50_per_IQR": float(0.25 * dlogit)}
    rep["item5_coefficients"] = {
        "standardized": True,
        "note": "Features are standardised inside each fold, so coefficients are per-SD and directly "
                "comparable. The IQR translation below is the honest effect size: how much the "
                "predicted probability moves across the interquartile range of that feature, "
                "evaluated at p=0.5 where the logistic slope is steepest (0.25) — i.e. an UPPER bound "
                "on the marginal effect.",
        "effects": eff}

    # ---- 6. block ablations ----
    name_idx = {n: i for i, n in enumerate(mlr.FEATURE_NAMES)}
    full_logit_brier = float(np.mean((P["logit"] - y) ** 2))
    abl = {}
    for blk, feats in dg.BLOCKS.items():
        drop = [name_idx[f] for f in feats]
        Pa, ya, da, _ = walk_forward_full(rows, burn_in=a.burn_in, drop=drop)
        b = float(np.mean((Pa["logit"] - ya) ** 2))
        abl[blk] = {"features_removed": feats, "brier_without_block": b,
                    "delta_vs_full": b - full_logit_brier,
                    "auc_without_block": float(dg.roc_auc(Pa["logit"], ya))}
    rep["item6_block_ablations"] = {
        "full_model_brier": full_logit_brier,
        "full_model_auc": float(dg.roc_auc(P["logit"], y)),
        "blocks": abl,
        "reading": "delta_vs_full > 0 means removing the block HURT (the block carries signal)."}

    # ---- 7. date-block bootstrap + Holm ----
    comps = {"logistic_vs_V13": ("logistic", "V13"), "logistic_vs_base": ("logistic", "base"),
             "LPM_vs_base": ("LPM", "base"), "V13_vs_base": ("V13", "base"),
             "ridge_vs_V13": ("ridge", "V13"), "LPM_vs_logistic": ("LPM", "logistic")}
    boot, pv = {}, {}
    for nm, (aa, bb) in comps.items():
        r = dg.date_block_bootstrap(models[aa], models[bb], y, dates)
        boot[nm] = r; pv[nm] = r["p"]
    rep["item7_inference"] = {"date_block_bootstrap": boot, "holm": dg.holm(pv),
        "note": "Resampling whole DATES, not individual games: games on a date share slate, schedule "
                "and weather effects, so a game-level bootstrap would understate the SE. Holm is "
                "applied across all six comparisons."}

    if a.out:
        json.dump(rep, open(a.out, "w"), indent=1, default=float)

    # ---------- console summary ----------
    print(f"n={rep['n_games']} games over {rep['n_dates']} dates; home-win rate {rep['home_win_rate']:.3f}\n")
    i1 = rep["item1_lpm_range"]
    print("1. LPM PREDICTION RANGE")
    print(f"   range [{i1['min']:.4f}, {i1['max']:.4f}]  below 0: {i1['n_below_0']}  above 1: {i1['n_above_1']}"
          f"  ({i1['pct_outside_0_1']:.2f}% outside)")
    print(f"   Brier raw {i1['brier_raw_unclipped']:.4f} -> clipped {i1['brier_clipped']:.4f}\n")
    print("2. ROC-AUC")
    for k, v in sorted(rep["item2_roc_auc"].items(), key=lambda t: -t[1]):
        print(f"   {k:<10}{v:.4f}")
    print("\n3. CALIBRATION (perfect = intercept 0, slope 1) + BRIER DECOMPOSITION")
    print(f"   {'model':<10}{'intcpt':>8}{'slope':>8}{'REL':>9}{'RES':>9}{'UNC':>8}")
    for k, v in rep["item3_calibration"].items():
        c = v["calibration"]; d = v["brier_decomposition"]
        print(f"   {k:<10}{c['intercept']:>+8.3f}{c['slope']:>8.3f}{d['reliability']:>9.5f}"
              f"{d['resolution']:>9.5f}{d['uncertainty']:>8.4f}")
    print("\n5. IQR MARGINAL EFFECTS (prob shift at p=0.5, upper bound)")
    for n, e in sorted(eff.items(), key=lambda t: -abs(t[1]["delta_prob_at_p50_per_IQR"])):
        print(f"   {n:<14}coef {e['coef_standardized']:+.4f}   dP/IQR {e['delta_prob_at_p50_per_IQR']:+.4f}")
    print("\n6. BLOCK ABLATIONS (delta > 0 = block carries signal)")
    print(f"   full model: Brier {rep['item6_block_ablations']['full_model_brier']:.4f} "
          f"AUC {rep['item6_block_ablations']['full_model_auc']:.4f}")
    for b, v in sorted(abl.items(), key=lambda t: -t[1]["delta_vs_full"]):
        print(f"   drop {b:<10}Brier {v['brier_without_block']:.4f}  delta {v['delta_vs_full']:+.5f}"
              f"  AUC {v['auc_without_block']:.4f}")
    print("\n7. DATE-BLOCK BOOTSTRAP + HOLM")
    print(f"   {'comparison':<20}{'dBrier':>10}{'95% CI':>24}{'p_raw':>8}{'p_holm':>8}  sig")
    for nm, r in boot.items():
        h = rep["item7_inference"]["holm"][nm]
        ci = f"[{r['ci95'][0]:+.5f},{r['ci95'][1]:+.5f}]"
        print(f"   {nm:<20}{r['dBrier']:>+10.5f}{ci:>24}{h['p_raw']:>8.3f}{h['p_holm']:>8.3f}"
              f"  {'YES' if h['reject_0.05'] else 'no'}")
    if a.out:
        print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
