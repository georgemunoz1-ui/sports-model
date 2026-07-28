#!/usr/bin/env python3
"""ML-P2 baseline evaluation + ML-P3 ablation runner, per docs/experiments/ML-P2P3_prereg.md.

Everything here follows the pre-registration committed BEFORE any run. The sealed holdout
(2026-06-29..2026-07-19) is structurally excluded: rows in that range are never loaded into the
evaluation frame, so no code path in this file can score them.

    python3 harness/ml_p2_baselines.py            # P2: (a)(b)(c)(d) on the 8 dev weeks
    python3 harness/ml_p2_baselines.py --a1       # P3-A1: paired HFA 1.03 vs 1.005
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

PREREG = "docs/experiments/ML-P2P3_prereg.md"
DATASET = "data/mlb/ml_asof/dataset.jsonl"
VINTAGE = "431e689cf629e3952354f417de4825caee4907f5ca490a376a940a75ae40d203"
OUT = "data/mlb/ml_asof"

DEV_WEEKS = ["2026-05-04", "2026-05-11", "2026-05-18", "2026-05-25",
             "2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22"]
HOLDOUT_START, HOLDOUT_END = "2026-06-29", "2026-07-19"   # SEALED — never loaded

LG_RPG = 4.45; LG_ERA = 4.20; LG_K = 22.0; LG_BB = 8.5; LG_BIP = 1 - (LG_K + LG_BB) / 100


def wk_end(mon):
    import datetime as dt
    d = dt.date.fromisoformat(mon)
    return (d + dt.timedelta(days=6)).isoformat()


def load_rows():
    rows = []
    for ln in open(DATASET):
        r = json.loads(ln)
        if not r["eligible_for_evaluation"]:
            continue
        if HOLDOUT_START <= r["slate_date"] <= HOLDOUT_END:
            continue  # SEALED holdout: structurally excluded
        rows.append(r)
    rows.sort(key=lambda r: (r["slate_date"], r["gamePk"]))
    for i, r in enumerate(rows):
        r["_gidx"] = i  # global row index -> split-independent RNG stream
    return rows


def shrunk(e, g):
    e = LG_ERA if e is None else e
    g = g or 0
    w = g / (g + 8)
    return w * e + (1 - w) * LG_ERA


def rs(era, gs, k, bb):
    k = LG_K if k is None else k
    bb = LG_BB if bb is None else bb
    return max(2.2, shrunk(era, gs) - ((k - bb) - 13.5) * 0.03)


def bipf(k, bb):
    k = LG_K if k is None else k
    bb = LG_BB if bb is None else bb
    return max(0.45, 1 - (k + bb) / 100)


def v13_row(r, hfa, n=4000):
    """The verdict scorer's arithmetic, HFA parameterized, per-row RNG reset (registered policy)."""
    rng = np.random.default_rng(7_000_000 + r["_gidx"])
    t = r["team"]; sp = r["sp"]
    oa = (t["away"]["rf_pg"] or LG_RPG) / LG_RPG; oh = (t["home"]["rf_pg"] or LG_RPG) / LG_RPG
    pena = 0.55 * (t["away"]["ra_pg"] or LG_RPG) + 0.45 * LG_RPG
    penh = 0.55 * (t["home"]["ra_pg"] or LG_RPG) + 0.45 * LG_RPG
    a, h = sp["away"], sp["home"]
    rah = rs(h["era"], h["gs"], h["k_pct"], h["bb_pct"])
    raa = rs(a["era"], a["gs"], a["k_pct"], a["bb_pct"])
    pf = r["park_factor"] or 1.0
    pfa = 1 + (pf - 1) * (bipf(h["k_pct"], h["bb_pct"]) / LG_BIP)
    pfh = 1 + (pf - 1) * (bipf(a["k_pct"], a["bb_pct"]) / LG_BIP)
    ip = np.clip(rng.normal(5.4, 1.3, n), 2, 8); ip2 = np.clip(rng.normal(5.4, 1.3, n), 2, 8)
    ma = (rah / 9 * ip + penh / 9 * (9 - ip)) * oa * pfa
    mh = (raa / 9 * ip2 + pena / 9 * (9 - ip2)) * oh * pfh * hfa
    ka = h["k_pct"] if h["k_pct"] is not None else LG_K
    kh = a["k_pct"] if a["k_pct"] is not None else LG_K
    sa = np.clip(1.8 + (ka - LG_K) * 0.16, 1.2, 6); sh = np.clip(1.8 + (kh - LG_K) * 0.16, 1.2, 6)
    ra_ = rng.poisson(rng.gamma(sa, np.maximum(ma, 0.3) / sa))
    rh_ = rng.poisson(rng.gamma(sh, np.maximum(mh, 0.3) / sh))
    tie = ra_ == rh_
    hx = rng.random(n) < (0.5 + 0.04 * np.sign(pena - penh))
    return float(np.where(tie, hx, rh_ > ra_).mean())


def feats_2f(r):
    t = r["team"]; sp = r["sp"]
    x1 = ((t["home"]["rf_pg"] or LG_RPG) - (t["home"]["ra_pg"] or LG_RPG)) \
       - ((t["away"]["rf_pg"] or LG_RPG) - (t["away"]["ra_pg"] or LG_RPG))
    x2 = shrunk(sp["away"]["era"], sp["away"]["gs"]) - shrunk(sp["home"]["era"], sp["home"]["gs"])
    return np.array([1.0, x1, x2])


def fit_logistic(X, y, iters=60):
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ b))
        W = p * (1 - p) + 1e-9
        g = X.T @ (y - p)
        Hm = (X * W[:, None]).T @ X + 1e-6 * np.eye(X.shape[1])
        b = b + np.linalg.solve(Hm, g)
    return b


def metrics(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6); y = np.asarray(y, float)
    brier = float(np.mean((p - y) ** 2))
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    acc = float(np.mean((p >= 0.5) == y))
    return brier, ll, acc


def calib(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    X = np.column_stack([np.ones(len(p)), np.log(p / (1 - p))])
    b = fit_logistic(X, np.asarray(y, float))
    return float(b[0]), float(b[1])


def reliability(p, y, bins=10):
    p = np.asarray(p, float); y = np.asarray(y, float)
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        m = (p >= lo) & (p < hi) if i < bins - 1 else (p >= lo) & (p <= hi)
        if m.sum():
            out.append(dict(bin=f"{lo:.1f}-{hi:.1f}", n=int(m.sum()),
                            mean_p=round(float(p[m].mean()), 3), obs=round(float(y[m].mean()), 3)))
    return out


def run_p2():
    rows = load_rows()
    y_all = {r["_gidx"]: r["label_home_win"] for r in rows}
    print(f"eligible dev rows loaded: {len(rows)} (holdout {HOLDOUT_START}..{HOLDOUT_END} SEALED, never loaded)")
    va = {r["_gidx"]: v13_row(r, 1.005) for r in rows if any(w <= r["slate_date"] <= wk_end(w) for w in DEV_WEEKS)}
    res = {m: {"p": [], "y": [], "weeks": []} for m in ("a_v13", "b_const", "c_baserate", "d_logistic")}
    per_week = []
    for w in DEV_WEEKS:
        we = wk_end(w)
        tr = [r for r in rows if r["slate_date"] < w]
        te = [r for r in rows if w <= r["slate_date"] <= we]
        if not te:
            continue
        yte = [r["label_home_win"] for r in te]
        base = float(np.mean([r["label_home_win"] for r in tr]))
        Xtr = np.vstack([feats_2f(r) for r in tr]); ytr = np.array([r["label_home_win"] for r in tr], float)
        beta = fit_logistic(Xtr, ytr)
        pd_ = [float(1 / (1 + np.exp(-feats_2f(r) @ beta))) for r in te]
        pa = [va[r["_gidx"]] for r in te]
        wk = dict(week=w, n=len(te), train_n=len(tr), base_rate=round(base, 4),
                  beta=[round(float(x), 4) for x in beta])
        for mid, pv in (("a_v13", pa), ("b_const", [0.5] * len(te)),
                        ("c_baserate", [base] * len(te)), ("d_logistic", pd_)):
            b_, l_, ac = metrics(pv, yte)
            wk[mid] = dict(brier=round(b_, 4), logloss=round(l_, 4), acc=round(ac, 4))
            res[mid]["p"] += pv; res[mid]["y"] += yte
        per_week.append(wk)
    pooled = {}
    for mid, d in res.items():
        b_, l_, ac = metrics(d["p"], d["y"])
        c0, c1 = calib(d["p"], d["y"]) if mid != "b_const" else (None, None)
        pooled[mid] = dict(n=len(d["y"]), brier=round(b_, 4), logloss=round(l_, 4), acc=round(ac, 4),
                           calib_intercept=(round(c0, 3) if c0 is not None else None),
                           calib_slope=(round(c1, 3) if c1 is not None else None),
                           reliability=reliability(d["p"], d["y"]))
    art = dict(record_id="ML-P2-BASELINES", prereg=PREREG,
               prereg_sha256=hashlib.sha256(open(PREREG, "rb").read()).hexdigest(),
               dataset_vintage=VINTAGE, model_identity="ml.v13_1.p2eval.hfa_param.n4000.per_row_reset",
               hfa_param=1.005, dev_weeks=DEV_WEEKS,
               holdout_sealed=f"{HOLDOUT_START}..{HOLDOUT_END} (never loaded)",
               market_benchmark="UNAVAILABLE on this population (stored ML openings are 7/24-25 only; SP resolution ends 7/19). Not approximated.",
               per_week=per_week, pooled=pooled)
    json.dump(art, open(f"{OUT}/p2_baselines.json", "w"), indent=1)
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "reliability"} for k, v in pooled.items()}, indent=1))
    print(f"wrote {OUT}/p2_baselines.json")


def run_a1():
    rows = load_rows()
    te = [r for r in rows if any(w <= r["slate_date"] <= wk_end(w) for w in DEV_WEEKS)]
    y = [r["label_home_win"] for r in te]
    p1005 = [v13_row(r, 1.005) for r in te]
    p103 = [v13_row(r, 1.03) for r in te]   # SAME per-row RNG stream -> paired, multiplier-only delta
    b1, l1, a1_ = metrics(p1005, y); b2, l2, a2_ = metrics(p103, y)
    d = np.array([(pa - yv) ** 2 - (pb - yv) ** 2 for pa, pb, yv in zip(p103, p1005, y)])
    se = float(d.std(ddof=1) / np.sqrt(len(d)))
    art = dict(record_id="ML-P3-A1-HFA", prereg=PREREG, dataset_vintage=VINTAGE,
               model_identity="ml.v13_1.p2eval.hfa_param.n4000.per_row_reset",
               paired=True, n=len(te),
               hfa_1005=dict(brier=round(b1, 4), logloss=round(l1, 4), acc=round(a1_, 4),
                             calib=calib(p1005, y)),
               hfa_103=dict(brier=round(b2, 4), logloss=round(l2, 4), acc=round(a2_, 4),
                            calib=calib(p103, y)),
               delta_brier_103_minus_1005=round(float(d.mean()), 6),
               paired_se=round(se, 6),
               note="negative delta favours 1.03; |delta| < ~2*SE is noise")
    json.dump(art, open(f"{OUT}/p3_a1_hfa.json", "w"), indent=1)
    print(json.dumps({k: v for k, v in art.items() if k not in ("prereg",)}, indent=1, default=str)[:1200])
    print(f"wrote {OUT}/p3_a1_hfa.json")


if __name__ == "__main__":
    if "--a1" in sys.argv:
        run_a1()
    else:
        run_p2()
