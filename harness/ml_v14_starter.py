#!/usr/bin/env python3
"""V14 starter shadow: the ONE-SHOT walk-forward fit specified by the frozen preregistration.

PREREG: docs/experiments/2026-08-18_V14_STARTER_PREREG.json, sha256 9cb65230ab704aa4...,
committed 8855503 BEFORE this file existed. This module implements that document and nothing else.
The feature list is closed, the estimator is fixed, the comparators are fixed, and the fit runs
ONCE — re-runs are for byte-identical reproduction only. Any variation is a NEW prereg.

Deliberately NOT here: any code path that produces a card, a forecast file, a price, or a wager.
The registered role is SHADOW_EXPERIMENT; forward registration is a separate, later step under
FORWARD_ONLY_PENDING and its own tooling.

Usage: python3 harness/ml_v14_starter.py [--selftest] [--run]
"""
from __future__ import annotations
import datetime as dt, hashlib, json, os, sys

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
DATASET = "data/mlb/ml_asof/dataset.jsonl"
V13FILE = "data/mlb/evaluations/v13_full_30k.jsonl"
LOGS = "data/backfill/mlb/2026/pitcher_logs"
OUT = "data/mlb/ml_asof/2026-08-18_v14_result.json"
PREREG = "docs/experiments/2026-08-18_V14_STARTER_PREREG.json"
PREREG_SHA = "9cb65230ab704aa477acb2d91a33172416f64ee8c46e2bb5ce914ac1f67c5725"

LG_ERA, LG_KBB, PRIOR_IP = 4.20, 13.5, 5.4
MIN_TRAIN_DATES, REST_CAP = 30, 15
LAMBDAS = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0]
EPS = 1e-12


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _log_rows(pid):
    """(date, ip, gs) from a pitcher log, all widths."""
    p = f"{LOGS}/{pid}.txt"
    if not os.path.exists(p):
        return []
    out = []
    for ln in open(p):
        f = ln.strip().split("|")
        if len(f) == 10:
            out.append((f[0], float(f[4]), f[9] == "1"))
        elif len(f) == 8:
            out.append((f[0], float(f[2]), f[7] == "1"))
        elif len(f) == 7:
            out.append((f[0], float(f[1]), f[6] == "1"))
    return sorted(out)


def sp_feats(sp, slate_date):
    """The five starter features for one side, or None if any is uncomputable. STRICT prior:
    only log rows dated < slate_date are visible."""
    if not sp or sp.get("era") is None or sp.get("k_pct") is None or not sp.get("last_start_date"):
        return None
    gs = sp.get("gs") or 0
    w = gs / (gs + 8)
    shrunk_era = w * sp["era"] + (1 - w) * LG_ERA
    kbb = (sp["k_pct"] - sp["bb_pct"])
    shrunk_kbb = w * kbb + (1 - w) * LG_KBB
    d0 = dt.date.fromisoformat(slate_date)
    rest = min((d0 - dt.date.fromisoformat(sp["last_start_date"])).days, REST_CAP)
    if rest < 0:
        return None  # future-dated last start: leakage, refuse the row
    rows = [(d, ip, g) for d, ip, g in _log_rows(sp["pid"]) if d < slate_date]
    lo30 = (d0 - dt.timedelta(days=30)).isoformat()
    ip30 = sum(ip for d, ip, _g in rows if d >= lo30)
    starts = [ip for d, ip, g in rows if g][-5:]
    n = len(starts)
    exp_ip = (n / (n + 3)) * (sum(starts) / n if n else PRIOR_IP) + (3 / (n + 3)) * PRIOR_IP
    return [shrunk_era, shrunk_kbb, float(rest), ip30, exp_ip]


def build_rows():
    v13 = {}
    for l in open(V13FILE):
        r = json.loads(l)
        v13[r["gamePk"]] = r["v13"]["p_home"]
    rows, excl = [], {"not_eligible": 0, "sp_block_missing": 0, "sp_feature_uncomputable": 0,
                      "no_v13_join": 0, "label_missing": 0}
    for l in open(DATASET):
        r = json.loads(l)
        if not r.get("eligible_for_evaluation"):
            excl["not_eligible"] += 1
            continue
        if r.get("label_home_win") is None:
            excl["label_missing"] += 1
            continue
        if not (r["sp"]["away"] and r["sp"]["home"]):
            excl["sp_block_missing"] += 1
            continue
        fa = sp_feats(r["sp"]["away"], r["slate_date"])
        fh = sp_feats(r["sp"]["home"], r["slate_date"])
        if fa is None or fh is None:
            excl["sp_feature_uncomputable"] += 1
            continue
        if r["gamePk"] not in v13:
            excl["no_v13_join"] += 1
            continue
        # edges home minus away; ERA edge negated so that POSITIVE always favours home
        x = [fa[0] - fh[0],            # era: away-minus-home (higher away ERA -> home good)
             fh[1] - fa[1],            # kbb: home minus away
             fh[2] - fa[2],            # rest
             fh[3] - fa[3],            # ip30 workload
             fh[4] - fa[4],            # expected ip
             r["park_factor"] or 1.0]
        rows.append({"gamePk": r["gamePk"], "date": r["slate_date"], "y": int(r["label_home_win"]),
                     "x": x, "p_v13": v13[r["gamePk"]]})
    rows.sort(key=lambda r: (r["date"], r["gamePk"]))
    return rows, excl


# ---------- estimator ----------
def _fit_ridge_logit(X, y, lam, iters=60):
    """Newton-IRLS ridge logistic on already-standardized X; intercept unpenalized."""
    Xb = np.hstack([np.ones((len(X), 1)), X])
    b = np.zeros(Xb.shape[1])
    R = np.eye(Xb.shape[1]) * lam
    R[0, 0] = 0.0
    for _ in range(iters):
        z = Xb @ b
        p = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
        W = p * (1 - p) + 1e-9
        g = Xb.T @ (y - p) - R @ b
        H = (Xb * W[:, None]).T @ Xb + R
        step = np.linalg.solve(H, g)
        b = b + step
        if np.max(np.abs(step)) < 1e-9:
            break
    return b


def _predict(b, X):
    z = np.hstack([np.ones((len(X), 1)), X]) @ b
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def _standardize(Xtr, Xte):
    mu, sd = Xtr.mean(0), Xtr.std(0)
    sd[sd == 0] = 1.0
    return (Xtr - mu) / sd, (Xte - mu) / sd


def _fit_fold(Xtr, ytr, tr_dates, Xte):
    """Full fold discipline: inner date-split lambda selection, train-only standardization."""
    uniq = sorted(set(tr_dates))
    cut = uniq[int(len(uniq) * 0.8)]
    inner_tr = np.array([d < cut for d in tr_dates])
    inner_va = ~inner_tr
    best, best_ll = None, np.inf
    Zi_tr, Zi_va = _standardize(Xtr[inner_tr], Xtr[inner_va])
    for lam in LAMBDAS:
        b = _fit_ridge_logit(Zi_tr, ytr[inner_tr], lam)
        p = np.clip(_predict(b, Zi_va), EPS, 1 - EPS)
        ll = -np.mean(ytr[inner_va] * np.log(p) + (1 - ytr[inner_va]) * np.log(1 - p))
        if ll < best_ll:
            best_ll, best = ll, lam
    Ztr, Zte = _standardize(Xtr, Xte)
    return _predict(_fit_ridge_logit(Ztr, ytr, best), Zte), best


def _platt(p_tr, y_tr, p_te):
    lg = np.log(np.clip(p_tr, EPS, 1 - EPS) / np.clip(1 - p_tr, EPS, 1 - EPS)).reshape(-1, 1)
    b = _fit_ridge_logit(lg, y_tr, 0.0)
    lt = np.log(np.clip(p_te, EPS, 1 - EPS) / np.clip(1 - p_te, EPS, 1 - EPS)).reshape(-1, 1)
    return _predict(b, lt)


# ---------- metrics ----------
def auc(p, y):
    order = np.argsort(p)
    r = np.empty(len(p))
    r[order] = np.arange(1, len(p) + 1)
    # average ranks over ties
    for v in np.unique(p):
        m = p == v
        r[m] = r[m].mean()
    n1, n0 = y.sum(), (1 - y).sum()
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else float("nan")


def calib(p, y):
    lg = np.log(np.clip(p, EPS, 1 - EPS) / np.clip(1 - p, EPS, 1 - EPS)).reshape(-1, 1)
    b = _fit_ridge_logit(lg, y, 0.0)
    return float(b[0]), float(b[1])


def murphy(p, y, bins=10):
    q = np.quantile(p, np.linspace(0, 1, bins + 1))
    q[0], q[-1] = -1, 2
    idx = np.digitize(p, q[1:-1])
    ybar = y.mean()
    rel = res = 0.0
    table = []
    for k in range(bins):
        m = idx == k
        if not m.any():
            continue
        pk, ok, nk = p[m].mean(), y[m].mean(), int(m.sum())
        rel += nk * (pk - ok) ** 2
        res += nk * (ok - ybar) ** 2
        table.append({"n": nk, "p_mean": round(float(pk), 4), "obs_rate": round(float(ok), 4)})
    n = len(p)
    return {"reliability": round(rel / n, 6), "resolution": round(res / n, 6),
            "uncertainty": round(float(ybar * (1 - ybar)), 6), "bins": table}


def score(p, y):
    p = np.clip(p, EPS, 1 - EPS)
    return {"brier": round(float(np.mean((p - y) ** 2)), 6),
            "logloss": round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 6),
            "auc": round(auc(p, y), 4),
            "p_sd_pp": round(float(p.std()) * 100, 2)}


def block_boot_holm(preds, y, dates, draws=10000, seed=20260818):
    """Paired date-block bootstrap of V14 minus each comparator on Brier and logloss; Holm over 8."""
    rng = np.random.default_rng(seed)
    uniq = sorted(set(dates))
    di = {d: i for i, d in enumerate(uniq)}
    idx_by_date = [[] for _ in uniq]
    for i, d in enumerate(dates):
        idx_by_date[di[d]].append(i)
    k = len(uniq)
    draws_idx = rng.integers(0, k, size=(draws, k))
    def per_game(p, metric):
        p = np.clip(p, EPS, 1 - EPS)
        return (p - y) ** 2 if metric == "brier" else -(y * np.log(p) + (1 - y) * np.log(1 - p))
    tests = []
    for name, pc in preds.items():
        if name == "v14":
            continue
        for metric in ("brier", "logloss"):
            diff = per_game(preds["v14"], metric) - per_game(pc, metric)
            sums = np.array([diff[ix].sum() for ix in idx_by_date])
            cnts = np.array([len(ix) for ix in idx_by_date])
            b = sums[draws_idx].sum(1) / cnts[draws_idx].sum(1)
            p_ge = float((b >= 0).mean())
            tests.append({"test": f"v14_vs_{name}::{metric}", "mean_diff": round(float(diff.mean()), 6),
                          "ci95": [round(float(np.percentile(b, 2.5)), 6), round(float(np.percentile(b, 97.5)), 6)],
                          "p_raw": float(min(1.0, 2 * min(p_ge, 1 - p_ge))),
                          "favors_v14": bool(diff.mean() < 0)})
    order = sorted(range(len(tests)), key=lambda i: tests[i]["p_raw"])
    run = 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, tests[i]["p_raw"] * (len(tests) - rank)))
        tests[i]["p_holm"] = round(run, 4)
        tests[i]["significant_05"] = bool(run < 0.05)
    return tests


def run_once():
    if os.path.exists(OUT):
        raise SystemExit(f"REFUSED: {OUT} exists. The prereg is ONE-SHOT; delete requires owner authority.")
    if _sha(PREREG) != PREREG_SHA:
        raise SystemExit("REFUSED: prereg bytes do not match the frozen sha — fit will not run against a drifted spec")
    rows, excl = build_rows()
    dates = [r["date"] for r in rows]
    uniq = sorted(set(dates))
    X = np.array([r["x"] for r in rows])
    y = np.array([r["y"] for r in rows], float)
    pv13 = np.array([r["p_v13"] for r in rows])

    p14 = np.full(len(rows), np.nan)
    pabl = np.full(len(rows), np.nan)
    pcal = np.full(len(rows), np.nan)
    pbase = np.full(len(rows), np.nan)
    lam_used = []
    darr = np.array(dates)
    for d in uniq[MIN_TRAIN_DATES:]:
        tr = darr < d
        te = darr == d
        if not te.any():
            continue
        p14[te], lam = _fit_fold(X[tr], y[tr], list(darr[tr]), X[te])
        lam_used.append(lam)
        pabl[te], _ = _fit_fold(X[tr][:, 5:6], y[tr], list(darr[tr]), X[te][:, 5:6])
        pcal[te] = _platt(pv13[tr], y[tr], pv13[te])
        pbase[te] = y[tr].mean()
    scored = ~np.isnan(p14)
    y_s, d_s = y[scored], darr[scored]
    preds = {"v14": p14[scored], "raw_v13": pv13[scored], "calibrated_v13": pcal[scored],
             "expanding_home_rate": pbase[scored], "no_starter_ablation": pabl[scored]}

    rep = {"record_id": "V14-STARTER-ONESHOT-2026-08-18",
           "built_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "model_id": "ml.v14_starter.rlog.shadow",
           "prereg": PREREG, "prereg_sha256": PREREG_SHA, "prereg_verified_before_fit": True,
           "dataset_sha256": _sha(DATASET), "v13_replay_sha256": _sha(V13FILE),
           "rows_scored": int(scored.sum()), "dates_scored": len(set(d_s)),
           "burn_in_dates": MIN_TRAIN_DATES, "exclusions": excl,
           "reconciliation": {"dataset_rows": sum(1 for _ in open(DATASET)),
                              "eligible_rows_entering": len(rows),
                              "scored": int(scored.sum()),
                              "burn_in_unscored": int(len(rows) - scored.sum())},
           "lambda_distribution": {str(l): lam_used.count(l) for l in sorted(set(lam_used))},
           "scores": {k: score(v, y_s) for k, v in preds.items()},
           "calibration": {k: dict(zip(("intercept", "slope"), calib(v, y_s))) for k, v in preds.items()},
           "murphy": {k: murphy(v, y_s) for k, v in preds.items()},
           "inference": block_boot_holm(preds, y_s, list(d_s)),
           "resolution_caveat": "resolution/spread reported DIAGNOSTICALLY; widening alone is never "
                                "success (V19 lesson). Judge Brier+logloss+AUC+calibration together.",
           "identity_leakage_disclosure": "historical starter identity is RESOLVED_POST_HOC per the "
                                          "frozen prereg; the promotion test runs only on prospective "
                                          "pregame-confirmed games.",
           "status": "FORWARD_ONLY_PENDING — this result changes no card, no gate, no authority."}
    json.dump(rep, open(OUT, "w"), indent=1)
    return rep


def selftest():
    fails = []
    rng = np.random.default_rng(7)
    n = 2000
    dates = [f"2026-{4+i//200:02d}-{1+(i//10)%20:02d}" for i in range(n)]
    x_sig = rng.normal(0, 1, n)
    x_noise = rng.normal(0, 1, n)
    y = (rng.random(n) < 1 / (1 + np.exp(-(0.8 * x_sig)))).astype(float)
    X = np.column_stack([x_sig, x_noise])
    darr = np.array(sorted(dates))
    # power: an informative feature must beat the noise-only ablation
    p_full = np.full(n, np.nan)
    p_abl = np.full(n, np.nan)
    for d in sorted(set(dates))[10:]:
        tr, te = darr < d, darr == d
        p_full[te], _ = _fit_fold(X[tr], y[tr], list(darr[tr]), X[te])
        p_abl[te], _ = _fit_fold(X[tr][:, 1:2], y[tr], list(darr[tr]), X[te][:, 1:2])
    m = ~np.isnan(p_full)
    if not (score(p_full[m], y[m])["brier"] < score(p_abl[m], y[m])["brier"] - 0.01):
        fails.append("informative feature did not beat the noise ablation — no power")
    if not (score(p_full[m], y[m])["auc"] > 0.6 > score(p_abl[m], y[m])["auc"]):
        fails.append("AUC did not separate signal from noise")
    # false-positive control: pure-noise features vs base rate must NOT be Holm-significant
    Xn = rng.normal(0, 1, (n, 2))
    pn = np.full(n, np.nan)
    pb = np.full(n, np.nan)
    for d in sorted(set(dates))[10:]:
        tr, te = darr < d, darr == d
        pn[te], _ = _fit_fold(Xn[tr], y[tr] * 0 + (rng.random(tr.sum()) < 0.52), list(darr[tr]), Xn[te])
        pb[te] = 0.52
    yn = (rng.random(n) < 0.52).astype(float)
    tests = block_boot_holm({"v14": pn[m], "base": pb[m]}, yn[m], list(darr[m]), draws=2000)
    if any(t["significant_05"] and t["favors_v14"] for t in tests):
        fails.append("pure noise reported as a Holm-significant improvement")
    # leakage guards
    if sp_feats({"era": 4.0, "k_pct": 20, "bb_pct": 8, "gs": 10, "pid": "0",
                 "last_start_date": "2026-09-01"}, "2026-08-01") is not None:
        fails.append("a FUTURE-dated last start produced features instead of refusing")
    mu_probe = np.array([[100.0], [0.0]])
    Ztr, Zte = _standardize(np.array([[1.0], [2.0], [3.0]]), mu_probe)
    if abs(Zte[0, 0]) < 5:
        fails.append("standardization appears to use test rows")
    # calibration: on data GENERATED from its own probabilities the recal slope must be ~1 and the
    # intercept ~0. (A perfectly-separated fixture is the wrong test — separation legitimately sends
    # the logistic slope unbounded, which the first version of this test got wrong.)
    pc = np.clip(rng.random(4000) * .6 + .2, EPS, 1 - EPS)
    yc = (rng.random(4000) < pc).astype(float)
    i, sl = calib(pc, yc)
    if not (0.8 < sl < 1.2 and abs(i) < 0.15):
        fails.append(f"recal slope/intercept off on self-generated data ({i:.3f},{sl:.3f})")
    # and a systematically overconfident forecaster must show slope < 1
    po = np.clip(0.5 + (pc - 0.5) * 1.8, EPS, 1 - EPS)
    _i2, sl2 = calib(po, yc)
    if not (sl2 < sl - 0.2):
        fails.append(f"overconfident forecaster not detected (slope {sl2:.3f} vs {sl:.3f})")
    if abs(auc(np.array([.1, .4, .35, .8]), np.array([0, 0, 1, 1], float)) - 0.75) > 1e-9:
        fails.append("AUC wrong on hand-checked fixture")
    if os.path.exists(OUT):
        r = json.load(open(OUT))
        if r.get("prereg_sha256") != PREREG_SHA:
            fails.append("existing result was not fit against the frozen prereg")
    if fails:
        print("ml_v14_starter selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("ml_v14_starter selftest: PASS (informative feature beats noise ablation with AUC "
          "separation; pure noise never Holm-significant; future-dated start refused; "
          "standardization train-only; AUC and calibration verified on fixtures)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    if "--run" not in sys.argv:
        print("pass --run to execute the ONE-SHOT fit (prereg sha verified first), or --selftest")
        raise SystemExit(0)
    r = run_once()
    print(f'V14 one-shot complete: {r["rows_scored"]} games over {r["dates_scored"]} dates '
          f'(+{r["burn_in_dates"]} burn-in). exclusions: {r["exclusions"]}')
    print(f'\n{"model":<22}{"Brier":>9}{"logloss":>9}{"AUC":>7}{"p SD":>7}{"slope":>7}{"icpt":>7}{"rel":>8}{"resol":>8}')
    for k in ("v14", "no_starter_ablation", "raw_v13", "calibrated_v13", "expanding_home_rate"):
        s, c, mu = r["scores"][k], r["calibration"][k], r["murphy"][k]
        print(f'{k:<22}{s["brier"]:>9.5f}{s["logloss"]:>9.5f}{s["auc"]:>7.4f}{s["p_sd_pp"]:>6.2f}%'
              f'{c["slope"]:>7.3f}{c["intercept"]:>+7.3f}{mu["reliability"]:>8.5f}{mu["resolution"]:>8.5f}')
    print("\ninference (date-block bootstrap + Holm, negative mean_diff favors V14):")
    for t in r["inference"]:
        print(f'  {t["test"]:<38} d={t["mean_diff"]:+.6f} CI[{t["ci95"][0]:+.6f},{t["ci95"][1]:+.6f}] '
              f'p_holm={t["p_holm"]:.4f} {"SIG" if t["significant_05"] else "ns"}')
    print(f'\nwrote {OUT}')
