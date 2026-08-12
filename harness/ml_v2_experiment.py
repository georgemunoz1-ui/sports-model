#!/usr/bin/env python3
"""MLV2 candidate experiment — preregistered in docs/experiments/2026-08-11_MLV2_PREREG.json.

Three candidates vs frozen V13 on identical games:
  C1 v13_platt : walk-forward Platt recalibration of V13's replay probability
  C2 logit7    : ridge logistic, frozen 7 features (8/10 candidate, re-run for ablation parity)
  C3 logit9    : C2 + rest_edge + form10_edge (as-of from results.csv)

All thresholds were frozen before this script was first run. Reuses the tested primitives in
ml_regression.py / ml_diagnostics.py; the only new code is the two as-of features and the Platt loop.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

from ml_regression import (FEATURE_NAMES, build_rows, fit_logistic, predict_logistic,
                           _standardize, metrics)
from ml_diagnostics import roc_auc, brier_decomposition, calibration_fit, date_block_bootstrap, holm

V13_REPLAY = "data/mlb/evaluations/v13_full_30k.jsonl"
BURN_IN = 400
EPS = 1e-6

FULL = {"Arizona Diamondbacks": "AZ", "Atlanta Braves": "ATL", "Baltimore Orioles": "BAL",
        "Boston Red Sox": "BOS", "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
        "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE", "Colorado Rockies": "COL",
        "Detroit Tigers": "DET", "Houston Astros": "HOU", "Kansas City Royals": "KC",
        "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD", "Miami Marlins": "MIA",
        "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN", "New York Mets": "NYM",
        "New York Yankees": "NYY", "Athletics": "ATH", "Philadelphia Phillies": "PHI",
        "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD", "San Francisco Giants": "SF",
        "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TB",
        "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
        "OAK": "ATH", "CHW": "CWS", "ARI": "AZ"}


def _ab(t):
    return FULL.get(t, t)


def team_history():
    """Per-team date-ordered (date, run_diff) from results.csv finals."""
    hist = {}
    for r in csv.DictReader(open("data/backfill/mlb/2026/results.csv")):
        if r["status"] != "final" or r["away_score"] == "" or r["home_score"] == "":
            continue
        a, h = _ab(r["away"]), _ab(r["home"])
        asc, hsc = int(r["away_score"]), int(r["home_score"])
        hist.setdefault(a, []).append((r["date"], asc - hsc))
        hist.setdefault(h, []).append((r["date"], hsc - asc))
    for t in hist:
        hist[t].sort()
    return hist


def rest_form(hist, team, date):
    """(rest_days capped at 5, mean run diff over up to last 10 games) strictly before date."""
    rows = [x for x in hist.get(team, []) if x[0] < date]
    if not rows:
        return 5.0, 0.0
    last = dt.date.fromisoformat(rows[-1][0])
    rest = min((dt.date.fromisoformat(date) - last).days, 5)
    tail = [rd for _, rd in rows[-10:]]
    return float(rest), float(np.mean(tail))


def game_teams():
    """gamePk -> (away_ab, home_ab, date) from features.csv."""
    out = {}
    for r in csv.DictReader(open("data/backfill/mlb/2026/features.csv")):
        out[r["gamePk"]] = (_ab(r["away"]), _ab(r["home"]), r["date"])
    return out


def v13_probs():
    v = {}
    for line in open(V13_REPLAY):
        r = json.loads(line)
        v[r["gamePk"]] = (r["v13"]["p_home"], r["outcome"]["home_win"])
    return v


def run():
    rows = build_rows()
    teams = game_teams()
    hist = team_history()
    v13 = v13_probs()
    # intersect with the frozen replay so every model sees identical games/labels
    rows = [r for r in rows if r["gamePk"] in v13 and r["gamePk"] in teams]
    # append the two as-of features (label consistency asserted against the replay)
    for r in rows:
        a, h, d = teams[r["gamePk"]]
        assert d == r["date"], f"date mismatch {r['gamePk']}"
        assert v13[r["gamePk"]][1] == r["y"], f"label mismatch {r['gamePk']}"
        ra, fa = rest_form(hist, a, r["date"])
        rh, fh = rest_form(hist, h, r["date"])
        r["x9"] = np.concatenate([r["x"], [rh - ra, fh - fa]])
    rows.sort(key=lambda r: (r["date"], r["gamePk"]))

    dates = sorted({r["date"] for r in rows})
    out = {k: {"p": [], "y": [], "d": [], "g": []} for k in ("v13", "platt", "logit7", "logit9")}
    l2_grid = (0.1, 1.0, 10.0, 100.0)
    for d in dates:
        tr = [r for r in rows if r["date"] < d]
        te = [r for r in rows if r["date"] == d]
        if len(tr) < BURN_IN or not te:
            continue
        ytr = np.array([r["y"] for r in tr], float)
        yte = np.array([r["y"] for r in te], float)
        for k in out:
            out[k]["y"] += list(yte)
            out[k]["d"] += [d] * len(te)
            out[k]["g"] += [r["gamePk"] for r in te]
        # V13 reference
        out["v13"]["p"] += [v13[r["gamePk"]][0] for r in te]
        # C1: Platt on V13's PRIOR outputs
        zp_tr = np.log(np.clip([v13[r["gamePk"]][0] for r in tr], EPS, 1 - EPS)
                       / (1 - np.clip([v13[r["gamePk"]][0] for r in tr], EPS, 1 - EPS)))[:, None]
        zp_te = np.log(np.clip([v13[r["gamePk"]][0] for r in te], EPS, 1 - EPS)
                       / (1 - np.clip([v13[r["gamePk"]][0] for r in te], EPS, 1 - EPS)))[:, None]
        b = fit_logistic(zp_tr, ytr, l2=1e-6)
        out["platt"]["p"] += list(predict_logistic(b, zp_te))
        # C2 / C3: ridge with inner-split penalty selection (training window only)
        for key, xf in (("logit7", "x"), ("logit9", "x9")):
            Xtr = np.array([r[xf] for r in tr]); Xte = np.array([r[xf] for r in te])
            Xtr_s, Xte_s = _standardize(Xtr, Xte)
            cut = int(len(tr) * 0.8)
            best, bl2 = None, l2_grid[0]
            if cut > 50 and len(tr) - cut > 20:
                Xi, Xo = _standardize(Xtr[:cut], Xtr[cut:])
                yi, yo = ytr[:cut], ytr[cut:]
                for l2 in l2_grid:
                    m = metrics(predict_logistic(fit_logistic(Xi, yi, l2=l2), Xo), yo)["brier"]
                    if best is None or m < best:
                        best, bl2 = m, l2
            out[key]["p"] += list(predict_logistic(fit_logistic(Xtr_s, ytr, l2=bl2), Xte_s))

    # ---- metrics + preregistered inference ----
    rep = {"n": len(out["v13"]["y"]), "dates": len(set(out["v13"]["d"])), "models": {}}
    y = np.array(out["v13"]["y"], float)
    dts = out["v13"]["d"]
    for k in out:
        p = np.array(out[k]["p"], float)
        cal = calibration_fit(p, y)
        rep["models"][k] = {
            "brier": float(np.mean((p - y) ** 2)),
            "auc": roc_auc(p, y),
            "calibration": cal,
            "decomposition": {kk: vv for kk, vv in brier_decomposition(p, y).items() if kk != "bins"},
        }
    pv = np.array(out["v13"]["p"], float)
    comps = {}
    for name, k in (("C1_platt_vs_v13", "platt"), ("C2_logit7_vs_v13", "logit7"),
                    ("C3_logit9_vs_v13", "logit9")):
        comps[name] = date_block_bootstrap(np.array(out[k]["p"]), pv, y, dts)
    comps["C3_vs_C2_block_ablation"] = date_block_bootstrap(
        np.array(out["logit9"]["p"]), np.array(out["logit7"]["p"]), y, dts)
    rep["comparisons"] = comps
    rep["holm"] = holm({k: v["p"] for k, v in comps.items()})

    # ---- frozen adoption gates ----
    verdicts = {}
    v13_auc = rep["models"]["v13"]["auc"]
    for name, k in (("C1_platt_vs_v13", "platt"), ("C2_logit7_vs_v13", "logit7"),
                    ("C3_logit9_vs_v13", "logit9")):
        m = rep["models"][k]; c = comps[name]; hlm = rep["holm"][name]
        checks = {
            "p_holm_lt_0.05_and_improving": bool(hlm["p_holm"] < 0.05 and c["dBrier"] < 0
                                                 and c["ci95"][1] < 0),
            "cal_slope_in_band": bool(0.85 <= m["calibration"]["slope"] <= 1.15),
            "cal_intercept_in_band": bool(-0.15 <= m["calibration"]["intercept"] <= 0.15),
            "auc_not_worse_than_v13_minus_005": bool(m["auc"] >= v13_auc - 0.005),
        }
        if name == "C3_logit9_vs_v13":
            checks["block_ablation_survives_holm"] = bool(
                rep["holm"]["C3_vs_C2_block_ablation"]["p_holm"] < 0.05
                and comps["C3_vs_C2_block_ablation"]["dBrier"] < 0)
        verdicts[name] = {"checks": checks, "ADOPT": all(checks.values())}
    rep["verdicts"] = verdicts
    rep["prereg"] = "docs/experiments/2026-08-11_MLV2_PREREG.json"
    return rep


if __name__ == "__main__":
    rep = run()
    outp = "data/mlb/ml_asof/2026-08-11_mlv2_experiment.json"
    json.dump(rep, open(outp, "w"), indent=1)
    print(f"n={rep['n']} games over {rep['dates']} dates -> {outp}")
    for k, m in rep["models"].items():
        print(f"  {k:7} brier {m['brier']:.5f}  auc {m['auc']:.4f}  "
              f"slope {m['calibration']['slope']:+.3f}  icpt {m['calibration']['intercept']:+.3f}")
    for name, c in rep["comparisons"].items():
        h = rep["holm"][name]
        print(f"  {name:26} dBrier {c['dBrier']:+.5f}  CI[{c['ci95'][0]:+.5f},{c['ci95'][1]:+.5f}]"
              f"  p_raw {h['p_raw']:.4f}  p_holm {h['p_holm']:.4f}")
    for name, v in rep["verdicts"].items():
        print(f"  {name}: {'ADOPT' if v['ADOPT'] else 'NO_ADOPT'} "
              f"({sum(v['checks'].values())}/{len(v['checks'])} checks)")
