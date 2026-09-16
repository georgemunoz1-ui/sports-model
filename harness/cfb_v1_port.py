"""Clean port of the registered CFB incumbent: cfb.fbs.elo_form_logit_ridge.v1_0.shadow.

WHY THIS AND NOT V2. The v2 preregistration's own week_one_policy decides it. v2 needs talent,
returning production, quarterback and coach continuity for a Week 1 forecast; the acquisition is
schedules-only, so those blocks are genuinely absent. The policy's instruction for exactly that
situation is explicit: "If the clean v1 port is present and passes its own healthcheck, publish v1
baseline forecasts with V2_INPUT_BLOCKED." v1 was recorded as ABSENT_AT_PREREGISTRATION and
PENDING_CLEAN_PORT. This is that port. Building v2 on inputs it does not have would be worse than
useless — it would be a v2-branded model that is secretly v1 plus noise.

CAUSAL DISCIPLINE. Games are processed in strict kickoff order and every feature for a game is read
off team state BEFORE that game updates it. For an evaluation season-week, training uses only games
whose kickoff is strictly before the EARLIEST kickoff in that week, so no game in a week can learn
from any other game in the same week. This is the preregistration's weekly_block rule.

HYPERPARAMETERS ARE FROZEN ON AN EARLY WINDOW AND NEVER RE-TOUCHED. The Elo and EWMA constants are
selected once on 2001-2010 and then held fixed for the whole 2011-2025 evaluation. Tuning them
inside the evaluation window would make every reported number optimistic by an unknown amount; a
half-done tuning that is not declared is worse than a crude constant that is.

WHAT IS NOT A FEATURE. No score, no market price, no ESPN Elo. ESPN's pregame Elo ships in the same
files and is retained ONLY as an external diagnostic the preregistration permits for evaluation and
forbids as an internally controlled baseline. The market firewall is structural: prices were never
acquired.
"""
from __future__ import annotations

MODULE_ID = "cfb_v1_port"

import datetime as dt
import hashlib
import json
import math
import os

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

MANIFEST = "data/cfb/model/CFB_V2_ACQUISITION_MANIFEST.json"
MODEL_ID = "cfb.fbs.elo_form_logit_ridge.v1_0.shadow"

FREEZE_SEASONS = (2001, 2010)     # hyperparameter selection window; never evaluated
EVAL_SEASONS = (2011, 2025)       # walk-forward evaluation window
MIN_HISTORY_SEASONS = 5           # preregistered

FEATURES = [
    "elo_diff_with_home_advantage",
    "home_ewma_points_for", "home_ewma_points_against",
    "away_ewma_points_for", "away_ewma_points_against",
    "home_ewma_margin", "away_ewma_margin",
    "rest_days_diff", "neutral_site", "conference_game",
]
#: The contract's own token set, imported rather than restated. My first attempt hand-rolled a
#: cruder list containing the bare substring "point", which then rejected home_ewma_points_for —
#: a feature the preregistration itself lists in v1_state. The lesson is that a firewall written
#: beside the thing it guards will drift from it; the contract is the single source of truth.
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cfb_v2_contract as CONTRACT
FORBIDDEN_IN_FEATURE_NAMES = tuple(sorted(CONTRACT.FORBIDDEN_TOKENS))


def _load():
    man = json.load(open(MANIFEST))
    frames = []
    for f in man["files"]:
        frames.append(pd.read_parquet(os.path.join(man["source"]["retained_locally_at"], f["path"])))
    d = pd.concat(frames, ignore_index=True)
    d = d[(d["completed"] == True) & d["home_points"].notna() & d["away_points"].notna()]  # noqa
    d = d.copy()
    d["kick"] = pd.to_datetime(d["start_date"], utc=True, format="mixed")
    d = d.sort_values(["kick", "game_id"], kind="mergesort").reset_index(drop=True)
    return man, d


def build_state(d, k, hfa, regress, alpha):
    """One causal pass. Features are read BEFORE the game updates the state it read from."""
    elo, ewpf, ewpa, ewm, last, last_season = {}, {}, {}, {}, {}, {}
    rows = []
    for r in d.itertuples(index=False):
        h, a, s = r.home_team, r.away_team, r.season
        for t in (h, a):
            if last_season.get(t) is not None and last_season[t] != s:
                # between seasons, regress toward the mean; roster turnover is real
                elo[t] = 1500.0 + (elo.get(t, 1500.0) - 1500.0) * regress
            last_season[t] = s
        eh, ea = elo.get(h, 1500.0), elo.get(a, 1500.0)
        adv = 0.0 if bool(r.neutral_site) else hfa
        rest_h = (r.kick - last[h]).days if h in last else np.nan
        rest_a = (r.kick - last[a]).days if a in last else np.nan
        rows.append({
            "game_id": r.game_id, "season": s, "week": r.week, "kick": r.kick,
            "home_team": h, "away_team": a,
            "home_division": r.home_division, "away_division": r.away_division,
            "elo_diff_with_home_advantage": (eh + adv) - ea,
            "home_ewma_points_for": ewpf.get(h, np.nan),
            "home_ewma_points_against": ewpa.get(h, np.nan),
            "away_ewma_points_for": ewpf.get(a, np.nan),
            "away_ewma_points_against": ewpa.get(a, np.nan),
            "home_ewma_margin": ewm.get(h, np.nan),
            "away_ewma_margin": ewm.get(a, np.nan),
            "rest_days_diff": (rest_h - rest_a) if not (np.isnan(rest_h) or np.isnan(rest_a))
                              else np.nan,
            "neutral_site": float(bool(r.neutral_site)),
            "conference_game": float(bool(r.conference_game)),
            "home_win": 1 if r.home_points > r.away_points else 0,
            "home_margin": float(r.home_points - r.away_points),
            "espn_home_pregame_elo": r.home_pregame_elo,
            "espn_away_pregame_elo": r.away_pregame_elo,
        })
        # ---- update AFTER reading
        exp_h = 1.0 / (1.0 + 10 ** (-((eh + adv) - ea) / 400.0))
        res_h = 1.0 if r.home_points > r.away_points else (0.5 if r.home_points == r.away_points
                                                           else 0.0)
        mv = math.log1p(abs(r.home_points - r.away_points))       # margin-of-victory damping
        elo[h] = eh + k * mv * (res_h - exp_h)
        elo[a] = ea + k * mv * ((1 - res_h) - (1 - exp_h))
        for t, pf, pa in ((h, r.home_points, r.away_points), (a, r.away_points, r.home_points)):
            ewpf[t] = pf if t not in ewpf else alpha * pf + (1 - alpha) * ewpf[t]
            ewpa[t] = pa if t not in ewpa else alpha * pa + (1 - alpha) * ewpa[t]
            m = pf - pa
            ewm[t] = m if t not in ewm else alpha * m + (1 - alpha) * ewm[t]
            last[t] = r.kick
    return pd.DataFrame(rows)


def _brier(y, p):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def select_hyperparameters(d):
    """Grid on the FREEZE window only. Selected once, then never touched again."""
    best, trials = None, []
    for k in (12.0, 20.0, 28.0):
        for hfa in (55.0, 65.0, 75.0):
            for regress in (0.60, 0.75):
                for alpha in (0.25, 0.40):
                    f = build_state(d[d.season.between(*FREEZE_SEASONS)], k, hfa, regress, alpha)
                    m = f[(f.season >= FREEZE_SEASONS[0] + 5)
                          & (f.home_division == "fbs") & (f.away_division == "fbs")]
                    p = 1.0 / (1.0 + 10 ** (-m["elo_diff_with_home_advantage"] / 400.0))
                    b = _brier(m["home_win"], p)
                    trials.append({"k": k, "hfa": hfa, "regress": regress, "alpha": alpha,
                                   "brier": round(b, 6), "n": int(len(m))})
                    if best is None or b < best["brier"]:
                        best = trials[-1]
    return best, trials


def walk_forward(feat, params):
    """Expanding-window OOF prediction, one refit per evaluation season-week."""
    from sklearn.linear_model import LogisticRegression, Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.impute import SimpleImputer

    coh = feat[(feat.home_division == "fbs") & (feat.away_division == "fbs")].copy()
    out = []
    for season in range(EVAL_SEASONS[0], EVAL_SEASONS[1] + 1):
        for week in sorted(coh[coh.season == season]["week"].unique()):
            blk = coh[(coh.season == season) & (coh.week == week)]
            cutoff = blk["kick"].min()
            tr = feat[(feat.kick < cutoff) & (feat.home_division == "fbs")
                      & (feat.away_division == "fbs")]
            if tr["season"].nunique() < MIN_HISTORY_SEASONS or len(tr) < 500:
                continue
            Xtr, Xte = tr[FEATURES], blk[FEATURES]
            clf = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                LogisticRegression(C=1.0, max_iter=2000))
            clf.fit(Xtr, tr["home_win"])
            reg = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                Ridge(alpha=1.0))
            reg.fit(Xtr, tr["home_margin"])
            p = clf.predict_proba(Xte)[:, 1]
            mg = reg.predict(Xte)
            # baselines, both trained on exactly the same rows
            base_rate = float(tr["home_win"].mean())
            elo_clf = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                    LogisticRegression(C=1.0, max_iter=2000))
            elo_clf.fit(Xtr[["elo_diff_with_home_advantage"]], tr["home_win"])
            p_elo = elo_clf.predict_proba(Xte[["elo_diff_with_home_advantage"]])[:, 1]
            for i, row in enumerate(blk.itertuples(index=False)):
                out.append({"season": season, "week": int(week), "game_id": row.game_id,
                            "home_team": row.home_team, "away_team": row.away_team,
                            "y": int(row.home_win), "margin": float(row.home_margin),
                            "p_model": float(p[i]), "pred_margin": float(mg[i]),
                            "p_base_rate": base_rate, "p_elo": float(p_elo[i]),
                            "espn_h": row.espn_home_pregame_elo,
                            "espn_a": row.espn_away_pregame_elo})
    return pd.DataFrame(out)


def evaluate(oof, seed=20260828):
    from sklearn.linear_model import LogisticRegression
    y = oof["y"].values

    def metrics(p):
        p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
        ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
        lg = np.log(p / (1 - p)).reshape(-1, 1)
        cal = LogisticRegression(C=1e6, max_iter=2000).fit(lg, y)
        bins = np.clip((p * 10).astype(int), 0, 9)
        ece = float(sum(abs(p[bins == b].mean() - y[bins == b].mean()) * (bins == b).sum()
                        for b in range(10) if (bins == b).any()) / len(p))
        order = np.argsort(p)
        yy = y[order]
        n1, n0 = yy.sum(), len(yy) - yy.sum()
        auc = float((np.sum(np.arange(1, len(yy) + 1)[yy == 1]) - n1 * (n1 + 1) / 2) / (n1 * n0)) \
            if n1 and n0 else float("nan")
        return {"brier": round(_brier(y, p), 6), "logloss": round(ll, 6),
                "calibration_slope": round(float(cal.coef_[0][0]), 4),
                "calibration_intercept": round(float(cal.intercept_[0]), 4),
                "ece": round(ece, 6), "auc": round(auc, 6)}

    res = {"model": metrics(oof["p_model"]),
           "baseline_expanding_home_rate": metrics(oof["p_base_rate"]),
           "baseline_causal_elo": metrics(oof["p_elo"])}

    esp = oof.dropna(subset=["espn_h", "espn_a"])
    if len(esp) > 100:
        pe = 1.0 / (1.0 + 10 ** (-((esp["espn_h"] - esp["espn_a"]) / 400.0)))
        ye = esp["y"].values
        res["external_diagnostic_espn_elo"] = {
            "brier": round(float(np.mean((pe - ye) ** 2)), 6), "n": int(len(esp)),
            "role": "EVALUATION-ONLY. The preregistration forbids treating this as an internally "
                    "controlled baseline; it is not used in any promotion decision."}

    # paired season-week bootstrap versus the strongest internal baseline
    strongest = min(("baseline_expanding_home_rate", "baseline_causal_elo"),
                    key=lambda kk: res[kk]["brier"])
    col = "p_base_rate" if strongest == "baseline_expanding_home_rate" else "p_elo"
    blocks = [g for _, g in oof.groupby(["season", "week"])]
    diffs = np.array([_brier(g["y"], g["p_model"]) - _brier(g["y"], g[col]) for g in blocks])
    rng = np.random.default_rng(seed)
    boots = np.array([diffs[rng.integers(0, len(diffs), len(diffs))].mean()
                      for _ in range(20000)])
    lo, hi = np.percentile(boots, [2.5, 97.5])
    res["paired_vs_strongest_baseline"] = {
        "baseline": strongest, "n_blocks": len(blocks),
        "mean_brier_diff": round(float(diffs.mean()), 6),
        "ci95": [round(float(lo), 6), round(float(hi), 6)],
        "improves": bool(hi < 0), "bootstrap_reps": 20000, "seed": seed,
        "reading": "negative is better (model Brier below baseline Brier)"}

    per_season = {}
    for s, g in oof.groupby("season"):
        per_season[int(s)] = {"n": int(len(g)),
                              "brier_model": round(_brier(g["y"], g["p_model"]), 6),
                              "brier_base": round(_brier(g["y"], g[col]), 6)}
    gains = {s: v["brier_base"] - v["brier_model"] for s, v in per_season.items()}
    tot = sum(x for x in gains.values() if x > 0)
    res["per_season"] = per_season
    res["max_single_season_share_of_gain"] = (
        round(max(gains.values()) / tot, 4) if tot > 0 else None)
    res["margin"] = {"mae_model": round(float(np.mean(np.abs(oof["pred_margin"] - oof["margin"]))), 4),
                     "mae_naive_zero": round(float(np.mean(np.abs(oof["margin"]))), 4)}
    return res


def run():
    man, d = _load()
    best, trials = select_hyperparameters(d)
    feat = build_state(d, best["k"], best["hfa"], best["regress"], best["alpha"])
    # 1. the port must use the PREREGISTERED v1_state block exactly — same members, same order.
    prereg = json.load(open("data/cfb/model/CFB_V2_PREREG.json"))
    registered = prereg["ordered_feature_blocks"]["v1_state"]
    if FEATURES != registered:
        raise SystemExit("FEATURE DRIFT: the port's feature list is not the preregistered "
                         f"v1_state block.\n  port:       {FEATURES}\n  registered: {registered}")
    # 2. and none of them may carry a market or outcome token, by the contract's own definition.
    for f in FEATURES:
        low = f.lower()
        hits = sorted(t for t in FORBIDDEN_IN_FEATURE_NAMES if t in low)
        if hits:
            raise SystemExit(f"FEATURE FIREWALL: '{f}' contains forbidden token(s) {hits}")
    oof = walk_forward(feat, best)
    res = evaluate(oof)
    return man, best, trials, feat, oof, res


if __name__ == "__main__":
    man, best, trials, feat, oof, res = run()
    os.makedirs("data/cfb/model", exist_ok=True)
    feat.to_parquet("data/cfb/model/cfb_v1_features.parquet")
    oof.to_parquet("data/cfb/model/cfb_v1_oof.parquet")
    print("HYPERPARAMETERS frozen on", FREEZE_SEASONS, "->", best)
    print("OOF rows", len(oof), "| seasons", oof.season.min(), "-", oof.season.max(),
          "| blocks", oof.groupby(['season','week']).ngroups)
    print()
    for k in ("model", "baseline_expanding_home_rate", "baseline_causal_elo"):
        m = res[k]
        print(f"  {k:<32} brier {m['brier']:.5f}  logloss {m['logloss']:.5f}  "
              f"slope {m['calibration_slope']:.3f}  int {m['calibration_intercept']:+.3f}  "
              f"ece {m['ece']:.4f}  auc {m['auc']:.4f}")
    if "external_diagnostic_espn_elo" in res:
        e = res["external_diagnostic_espn_elo"]
        print(f"  {'[diagnostic] espn pregame elo':<32} brier {e['brier']:.5f}  (n={e['n']})")
    p = res["paired_vs_strongest_baseline"]
    print()
    print(f"  paired vs {p['baseline']}: mean {p['mean_brier_diff']:+.5f} "
          f"CI95 [{p['ci95'][0]:+.5f}, {p['ci95'][1]:+.5f}] improves={p['improves']} "
          f"({p['n_blocks']} blocks)")
    print(f"  max single-season share of gain: {res['max_single_season_share_of_gain']}")
    print(f"  margin MAE {res['margin']['mae_model']} vs naive-zero {res['margin']['mae_naive_zero']}")
    json.dump(res, open("data/cfb/model/CFB_V1_OOF_EVALUATION.json", "w"), indent=1, sort_keys=True)
