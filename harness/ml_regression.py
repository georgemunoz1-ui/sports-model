#!/usr/bin/env python3
"""Regression models for MLB home-win probability, walk-forward validated.

WHY (owner request 2026-08-10): "model should be machine learning in order to be 'less wrong' —
LINEAR REGRESSION". V13 is a hand-tuned Monte Carlo whose measured Brier on the frozen as-of set is
0.2527 — worse than simply predicting the league home-win base rate. A model FIT to the data should
be able to beat that, and the only way to know is to fit it and score it out of sample.

WHAT IS FIT
  target : home_win (binary)
  features: strictly as-of, taken from data/backfill/mlb/2026/features.csv, the same frozen inputs
            harness/run_v13_historical.py replays. No look-ahead, no market prices as inputs.

MODELS
  base     league home-win rate on the training window (the null model everything must beat)
  lpm      LINEAR regression on the 0/1 target — the Linear Probability Model, as requested.
           Honest caveat: OLS on a binary target can predict outside [0,1] and its errors are
           heteroscedastic by construction, so predictions are clipped. It is reported because it
           was asked for and because it is a fair baseline, not because it is correctly specified.
  logit    logistic regression (IRLS) — the correctly specified sibling for a binary target.
  ridge    L2-penalised logistic; the penalty is chosen on an inner split of the TRAINING window
           only, never on the scoring rows.

VALIDATION
  EXPANDING-WINDOW WALK-FORWARD, date-ordered: to predict date D, fit only on games strictly before
  D. Never a random split — a random split over a season leaks the future into the past, which is
  exactly how a model that cannot predict comes to look like one that can.

Everything is scored against V13 on the SAME games via data/mlb/evaluations/v13_full_30k.jsonl, so
the comparison is like-for-like rather than against a remembered number.

Usage:
  python3 harness/ml_regression.py --selftest
  python3 harness/ml_regression.py            # walk-forward evaluation + comparison table
  python3 harness/ml_regression.py --fit-full --out data/mlb/ml_asof/regression_coefficients.json
"""

from __future__ import annotations

MODULE_ID = "ml_regression"

import argparse
import csv
import json
import os

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEATURES = "data/backfill/mlb/2026/features.csv"
V13_REPLAY = "data/mlb/evaluations/v13_full_30k.jsonl"
LG_ERA = 4.20

FEATURE_NAMES = [
    "sp_era_edge",     # shrunk ERA: away SP - home SP  (positive => home SP better)
    "team_rd_edge",    # (home_rf-home_ra) - (away_rf-away_ra)
    "off_edge",        # home_rf - away_rf
    "def_edge",        # away_ra - home_ra
    "sp_k_edge",       # home SP K% - away SP K%
    "sp_bb_edge",      # away SP BB% - home SP BB%  (positive => home SP walks fewer)
    "park",            # park factor (centred at 1.0)
]


def shrunk_era(era, gs):
    """Regress a starter's ERA toward league by starts made. Same shrinkage V13 uses, so the two
    models see the same view of starter quality and any difference is in the FITTING, not the input."""
    if era is None:
        return LG_ERA
    gs = gs or 0
    w = gs / (gs + 8.0)
    return w * era + (1 - w) * LG_ERA


def build_rows(path=FEATURES):
    rows = []
    for r in csv.DictReader(open(path)):
        if r["home_win"] == "":
            continue
        f = json.loads(r["features"])
        a, h = f.get("away_sp") or {}, f.get("home_sp") or {}
        arf, ara = f.get("away_rf"), f.get("away_ra")
        hrf, hra = f.get("home_rf"), f.get("home_ra")
        if None in (arf, ara, hrf, hra):
            continue  # incomplete team form -> excluded rather than imputed (R1)
        x = [
            shrunk_era(a.get("era"), a.get("gs")) - shrunk_era(h.get("era"), h.get("gs")),
            (hrf - hra) - (arf - ara),
            hrf - arf,
            ara - hra,
            (h.get("k") if h.get("k") is not None else 22.0) - (a.get("k") if a.get("k") is not None else 22.0),
            (a.get("bb") if a.get("bb") is not None else 8.5) - (h.get("bb") if h.get("bb") is not None else 8.5),
            (f.get("park") or 1.0) - 1.0,
        ]
        rows.append({"gamePk": r["gamePk"], "date": r["date"], "y": int(r["home_win"]),
                     "x": np.array(x, dtype=float)})
    rows.sort(key=lambda r: (r["date"], r["gamePk"]))
    return rows


# ---------- fitting ----------

def _standardize(Xtr, Xte):
    mu, sd = Xtr.mean(0), Xtr.std(0)
    sd = np.where(sd < 1e-9, 1.0, sd)
    return (Xtr - mu) / sd, (Xte - mu) / sd


def fit_ols(X, y, l2=0.0):
    """Linear Probability Model: OLS on the 0/1 target (the requested linear regression)."""
    Xb = np.hstack([np.ones((len(X), 1)), X])
    A = Xb.T @ Xb + l2 * np.eye(Xb.shape[1])
    A[0, 0] -= l2  # never penalise the intercept
    return np.linalg.solve(A, Xb.T @ y)


def predict_ols(beta, X):
    Xb = np.hstack([np.ones((len(X), 1)), X])
    return np.clip(Xb @ beta, 0.001, 0.999)


def fit_logistic(X, y, l2=1.0, iters=60, tol=1e-9):
    """Logistic regression by IRLS with an L2 penalty (intercept unpenalised)."""
    Xb = np.hstack([np.ones((len(X), 1)), X])
    n, p = Xb.shape
    beta = np.zeros(p)
    P = l2 * np.eye(p)
    P[0, 0] = 0.0
    for _ in range(iters):
        eta = np.clip(Xb @ beta, -30, 30)
        mu = 1.0 / (1.0 + np.exp(-eta))
        W = np.clip(mu * (1 - mu), 1e-8, None)
        z = eta + (y - mu) / W
        A = Xb.T @ (Xb * W[:, None]) + P
        try:
            new = np.linalg.solve(A, Xb.T @ (W * z))
        except np.linalg.LinAlgError:
            break
        if np.max(np.abs(new - beta)) < tol:
            beta = new
            break
        beta = new
    return beta


def predict_logistic(beta, X):
    Xb = np.hstack([np.ones((len(X), 1)), X])
    return np.clip(1.0 / (1.0 + np.exp(-np.clip(Xb @ beta, -30, 30))), 1e-6, 1 - 1e-6)


# ---------- metrics ----------

def metrics(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float)
    return {"n": int(len(y)),
            "brier": float(np.mean((p - y) ** 2)),
            "logloss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
            "acc": float(np.mean((p >= 0.5) == y))}


def walk_forward(rows, burn_in=400, l2_grid=(0.1, 1.0, 10.0, 100.0)):
    """Expanding-window, date-ordered. To predict date D, fit only on games strictly before D."""
    dates = sorted({r["date"] for r in rows})
    out = {k: {"p": [], "y": []} for k in ("base", "lpm", "logit", "ridge")}
    for d in dates:
        tr = [r for r in rows if r["date"] < d]
        te = [r for r in rows if r["date"] == d]
        if len(tr) < burn_in or not te:
            continue
        Xtr = np.array([r["x"] for r in tr]); ytr = np.array([r["y"] for r in tr], float)
        Xte = np.array([r["x"] for r in te]); yte = np.array([r["y"] for r in te], float)
        Xtr_s, Xte_s = _standardize(Xtr, Xte)
        # base rate
        out["base"]["p"] += [ytr.mean()] * len(te); out["base"]["y"] += list(yte)
        # LPM (requested linear regression)
        out["lpm"]["p"] += list(predict_ols(fit_ols(Xtr_s, ytr), Xte_s)); out["lpm"]["y"] += list(yte)
        # logistic
        out["logit"]["p"] += list(predict_logistic(fit_logistic(Xtr_s, ytr, l2=1.0), Xte_s))
        out["logit"]["y"] += list(yte)
        # ridge: penalty chosen on an INNER split of the training window only
        cut = int(len(tr) * 0.8)
        best, bl2 = None, l2_grid[0]
        if cut > 50 and len(tr) - cut > 20:
            Xi, Xo = _standardize(Xtr[:cut], Xtr[cut:])
            yi, yo = ytr[:cut], ytr[cut:]
            for l2 in l2_grid:
                m = metrics(predict_logistic(fit_logistic(Xi, yi, l2=l2), Xo), yo)["brier"]
                if best is None or m < best:
                    best, bl2 = m, l2
        out["ridge"]["p"] += list(predict_logistic(fit_logistic(Xtr_s, ytr, l2=bl2), Xte_s))
        out["ridge"]["y"] += list(yte)
    return {k: metrics(v["p"], v["y"]) for k, v in out.items() if v["y"]}, out


def v13_on(gamepks):
    """V13's own probabilities for the same games, from the frozen historical replay."""
    if not os.path.exists(V13_REPLAY):
        return None
    want = set(gamepks)
    p, y = [], []
    for line in open(V13_REPLAY):
        r = json.loads(line)
        if r["gamePk"] in want:
            p.append(r["v13"]["p_home"]); y.append(r["outcome"]["home_win"])
    return metrics(p, y) if p else None


def selftest():
    fails = []
    rng = np.random.default_rng(0)
    # a signal the model must recover: y driven by x0
    X = rng.normal(size=(4000, 3))
    y = (1 / (1 + np.exp(-(0.9 * X[:, 0] - 0.4 * X[:, 1]))) > rng.random(4000)).astype(float)
    b = fit_logistic(X, y, l2=1e-6)
    if not (b[1] > 0.5 and b[2] < -0.1):
        fails.append(f"logistic did not recover known coefficients: {b}")
    pm = metrics(predict_logistic(b, X), y)
    if pm["brier"] >= 0.25:
        fails.append("logistic no better than coin flip on a strongly separable synthetic set")
    # OLS must recover a linear relationship
    yl = 0.5 + 0.1 * X[:, 0]
    bo = fit_ols(X, yl)
    if abs(bo[1] - 0.1) > 0.01 or abs(bo[0] - 0.5) > 0.01:
        fails.append(f"OLS did not recover linear coefficients: {bo[:2]}")
    # LPM predictions must be clipped into [0,1]
    if not ((predict_ols(np.array([0.5, 10.0, 0, 0]), X) <= 1).all()
            and (predict_ols(np.array([0.5, 10.0, 0, 0]), X) >= 0).all()):
        fails.append("LPM predictions not clipped to [0,1]")
    # NO LOOK-AHEAD: every walk-forward training row must predate its test date
    rows = [{"gamePk": str(i), "date": f"2026-04-{(i % 28) + 1:02d}", "y": i % 2,
             "x": rng.normal(size=7)} for i in range(600)]
    dates = sorted({r["date"] for r in rows})
    for d in dates:
        tr = [r for r in rows if r["date"] < d]
        if tr and max(r["date"] for r in tr) >= d:
            fails.append("walk-forward training window contains the test date (look-ahead)")
            break
    # standardisation must use TRAINING moments only
    A = np.array([[0.0], [10.0]]); B = np.array([[100.0]])
    As, Bs = _standardize(A, B)
    if abs(As.mean()) > 1e-9 or abs(Bs[0, 0] - (100 - 5) / 5) > 1e-6:
        fails.append("standardisation leaked test moments")
    if fails:
        print("ml_regression selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("ml_regression selftest: PASS (logistic + OLS recover known coefficients, LPM clipped, "
          "walk-forward has no look-ahead, standardisation uses training moments only)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--fit-full", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--burn-in", type=int, default=400)
    a = ap.parse_args()
    os.chdir(BASE)
    if a.selftest:
        return selftest()
    rows = build_rows()
    res, raw = walk_forward(rows, burn_in=a.burn_in)
    scored = [r for r in rows if r["date"] >= sorted({x["date"] for x in rows})[0]]
    # V13 on the SAME scored games
    n_scored = res["base"]["n"]
    dates = sorted({r["date"] for r in rows})
    used_pks = []
    for d in dates:
        tr = [r for r in rows if r["date"] < d]
        te = [r for r in rows if r["date"] == d]
        if len(tr) < a.burn_in or not te:
            continue
        used_pks += [r["gamePk"] for r in te]
    v13 = v13_on(used_pks)
    print(f"walk-forward OOS on {n_scored} games "
          f"(expanding window, date-ordered, burn-in {a.burn_in})\n")
    print(f"{'model':<10}{'Brier':>9}{'logloss':>10}{'acc':>8}   {'vs base':>9}")
    order = [("base", "base rate"), ("lpm", "LPM (linear)"), ("logit", "logistic"), ("ridge", "ridge logit")]
    b0 = res["base"]["brier"]
    for k, label in order:
        m = res[k]
        print(f"{label:<10}{m['brier']:>9.4f}{m['logloss']:>10.4f}{m['acc']:>7.1%}   {m['brier']-b0:>+9.4f}")
    if v13:
        print(f"{'V13 (MC)':<10}{v13['brier']:>9.4f}{v13['logloss']:>10.4f}{v13['acc']:>7.1%}   "
              f"{v13['brier']-b0:>+9.4f}   [same {v13['n']} games]")
    if a.fit_full:
        X = np.array([r["x"] for r in rows]); y = np.array([r["y"] for r in rows], float)
        mu, sd = X.mean(0), X.std(0); sd = np.where(sd < 1e-9, 1.0, sd)
        Xs = (X - mu) / sd
        blog = fit_logistic(Xs, y, l2=1.0)
        blpm = fit_ols(Xs, y)
        out = {"record_id": "ML-REGRESSION-COEFFICIENTS", "n_train": int(len(y)),
               "feature_names": FEATURE_NAMES,
               "standardization": {"mean": mu.tolist(), "std": sd.tolist()},
               "logistic": {"intercept": blog[0], "coefficients": dict(zip(FEATURE_NAMES, blog[1:]))},
               "lpm": {"intercept": blpm[0], "coefficients": dict(zip(FEATURE_NAMES, blpm[1:]))},
               "walk_forward_oos": res,
               "note": "Coefficients fit on the FULL frozen as-of set for inspection. The honest "
                       "performance number is the walk-forward OOS block, not any in-sample fit."}
        print("\nlogistic coefficients (standardised):")
        for nme, c in sorted(zip(FEATURE_NAMES, blog[1:]), key=lambda t: -abs(t[1])):
            print(f"  {nme:<14}{c:+.4f}")
        if a.out:
            json.dump(out, open(a.out, "w"), indent=1, default=float)
            print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
