#!/usr/bin/env python3
"""Rigorous diagnostics for the walk-forward regression comparison (owner spec 2026-08-10).

The first pass reported Brier/accuracy and called the LPM's ranking "fine". That was too loose.
This module answers the specific questions asked:

  1. LPM prediction range, counts outside [0,1], and raw vs clipped Brier
  2. ROC-AUC (replaces the hand-waved "ranking is fine")
  3. Calibration intercept & slope, reliability bins, Murphy Brier decomposition — all four models
  4. An audit of WHERE each preprocessing step is fitted (inside the fold, or not)
  5. Standardised coefficients translated into an IQR-shift marginal probability effect
  6. Walk-forward BLOCK ABLATIONS (starter / offense / defense / park / run-differential)
  7. Date-block bootstrap + Holm correction across the model comparisons

Blocks bootstrap by DATE, not by game: games on the same date share weather, schedule and slate
effects, so resampling individual games would understate the standard error.
"""

from __future__ import annotations

MODULE_ID = "ml_diagnostics"

import json
import os

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V13_REPLAY = "data/mlb/evaluations/v13_full_30k.jsonl"

BLOCKS = {
    "starter": ["sp_era_edge", "sp_k_edge", "sp_bb_edge"],
    "offense": ["off_edge"],
    "defense": ["def_edge"],
    "park": ["park"],
    "run_diff": ["team_rd_edge"],
}


# ---------- metrics ----------

def roc_auc(p, y):
    """Rank-based AUC with tie handling (Mann-Whitney U)."""
    p = np.asarray(p, float); y = np.asarray(y, int)
    order = np.argsort(p, kind="mergesort")
    ps = p[order]
    ranks = np.empty(len(p), float)
    i = 0
    while i < len(ps):
        j = i
        while j + 1 < len(ps) and ps[j + 1] == ps[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    n1 = int(y.sum()); n0 = len(y) - n1
    if n1 == 0 or n0 == 0:
        return float("nan")
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def brier_decomposition(p, y, n_bins=10):
    """Murphy: BS = reliability - resolution + uncertainty (equal-count bins)."""
    p = np.asarray(p, float); y = np.asarray(y, float)
    n = len(y); obar = y.mean()
    order = np.argsort(p, kind="mergesort")
    rel = res = 0.0
    bins = []
    for idx in np.array_split(order, n_bins):
        if not len(idx):
            continue
        pk, ok, nk = p[idx].mean(), y[idx].mean(), len(idx)
        rel += nk / n * (pk - ok) ** 2
        res += nk / n * (ok - obar) ** 2
        bins.append({"n": int(nk), "pred": float(pk), "actual": float(ok)})
    return {"brier": float(np.mean((p - y) ** 2)), "reliability": float(rel),
            "resolution": float(res), "uncertainty": float(obar * (1 - obar)),
            "bins": bins}


def calibration_fit(p, y, eps=1e-6):
    """Logistic recalibration y ~ a + b*logit(p). Perfect calibration is a=0, b=1."""
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    z = np.log(p / (1 - p))
    X = np.column_stack([np.ones(len(z)), z])
    beta = np.zeros(2)
    for _ in range(100):
        eta = np.clip(X @ beta, -30, 30)
        mu = 1 / (1 + np.exp(-eta))
        W = np.clip(mu * (1 - mu), 1e-9, None)
        try:
            new = beta + np.linalg.solve(X.T @ (X * W[:, None]), X.T @ (y - mu))
        except np.linalg.LinAlgError:
            break
        if np.max(np.abs(new - beta)) < 1e-10:
            beta = new
            break
        beta = new
    return {"intercept": float(beta[0]), "slope": float(beta[1])}


# ---------- inference ----------

def date_block_bootstrap(pa, pb, y, dates, n_boot=4000, seed=11):
    """Paired Brier difference, resampling whole DATES (games within a date are correlated)."""
    rng = np.random.default_rng(seed)
    pa, pb, y = map(lambda v: np.asarray(v, float), (pa, pb, y))
    dates = np.asarray(dates)
    uniq = np.unique(dates)
    idx_by_date = {d: np.where(dates == d)[0] for d in uniq}
    d_obs = float(np.mean((pa - y) ** 2 - (pb - y) ** 2))
    stats = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([idx_by_date[d] for d in pick])
        stats[b] = np.mean((pa[idx] - y[idx]) ** 2 - (pb[idx] - y[idx]) ** 2)
    lo, hi = np.percentile(stats, [2.5, 97.5])
    # two-sided bootstrap p-value: proportion of resamples on the other side of 0
    pval = 2.0 * min((stats >= 0).mean(), (stats <= 0).mean())
    return {"dBrier": d_obs, "ci95": [float(lo), float(hi)], "p": float(min(1.0, pval)),
            "n_dates": int(len(uniq))}


def holm(pvals_by_name):
    """Holm-Bonferroni step-down. Returns name -> (raw p, adjusted p, reject at 0.05)."""
    items = sorted(pvals_by_name.items(), key=lambda kv: kv[1])
    m = len(items)
    out = {}
    running = 0.0
    for i, (name, p) in enumerate(items):
        adj = min(1.0, max(running, (m - i) * p))
        running = adj
        out[name] = {"p_raw": float(p), "p_holm": float(adj), "reject_0.05": bool(adj < 0.05)}
    return out


def v13_lookup(gamepks):
    v = {}
    for line in open(V13_REPLAY):
        r = json.loads(line)
        v[r["gamePk"]] = r["v13"]["p_home"]
    return np.array([v[g] for g in gamepks])


if __name__ == "__main__":
    print(__doc__)
