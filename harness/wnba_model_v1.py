#!/usr/bin/env python3
"""wnba.rs.ff7_logit_ridge.v1_0.shadow — preregistered in docs/experiments/2026-08-12_WNBA_V1_PREREG.json.

Builds the official-plus-one dataset from the staged bytes, walks forward, applies the frozen
gates, and (only if the win-target gates pass) emits a coherence-gated card for a given slate.
Reuses the tested fitting/diagnostic primitives from the MLB harness. SHADOW DIAGNOSTIC ONLY.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow.parquet as pq

ET = ZoneInfo("America/New_York")   # pool/feature dates are ET calendar dates


def et_date(utc_instant):
    """ET (America/New_York) calendar date of a UTC tip instant, YYYY-MM-DD.

    predict_slate previously sliced `tip[:10]` — the UTC date — so a 2026-07-23T00:00Z tip was
    treated as 07-23 for rest/b2b when it is the ET evening of 07-22. Same defect class as the
    wnba_refresh_espn extraction bug; derive, never slice."""
    s = str(utc_instant).strip().replace("Z", "+00:00")
    d = dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(ET).date().isoformat()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

from ml_regression import fit_logistic, predict_logistic, fit_ols, _standardize, metrics


def _ols_raw(beta, X):
    """UNCLIPPED linear prediction. ml_regression.predict_ols clips to [0.001, 0.999] because it
    is an LPM-probability helper; margins and totals are real-valued and must not pass through it —
    the clip silently turned a 160-point total into 0.999 on the first run of this module."""
    import numpy as _np
    return _np.hstack([_np.ones((len(X), 1)), X]) @ beta
from ml_diagnostics import roc_auc, calibration_fit, date_block_bootstrap, holm

STAGE = "data/wnba/source/staging"
MARGIN_SD = 13.97          # frozen: empirical, measured from staged bytes 2026-08-11
SHRINK_G = 10.0            # frozen shrinkage constant (prereg)
BURN_IN = 300
MIN_TEAM_GAMES = 5
XW = {"LA": "LAS", "LV": "LVA", "NY": "NYL", "WSH": "WAS", "CONN": "CON", "SA": "SAN", "GS": "GSV",
      "POR": "PDX"}  # ESPN POR vs official PDX (Portland Fire, 2026) — same class as the PHX swap
EXHIB = {"USA", "WNBASTARS", "WEST", "EAST", "WIL", "DEL", "STE", "PAR", "ALL", "CLA", "COL"}
FEATS = ["net_rtg_edge", "efg_edge", "tov_edge", "orb_edge", "ftr_edge", "rest_edge", "b2b_edge"]
CONT = 6                   # first 6 features standardized; b2b_edge (index 6) never is


def _xw(t, season):
    if t in ("PHX", "PHO"):
        return "PHX" if season >= 2025 else "PHO"
    return XW.get(t, t)


def _official_rows(season):
    p = f"{STAGE}/WNBA_OFFICIAL/wnba_stats/schedules/parquet/wnba_stats_schedule_{season}.parquet"
    d = pq.read_table(p).to_pydict()
    out = []
    for i in range(len(d["game_id"])):
        if d["measure_type"][i] is not None:
            continue
        t = str(d["team_abbreviation"][i])
        if t in EXHIB:
            continue
        out.append({"gid": str(d["game_id"][i]), "date": str(d["game_date"][i])[:10],
                    "team": t, "matchup": str(d["matchup"][i]), "pts": d["pts"][i] or 0,
                    "fgm": d["fgm"][i] or 0, "fga": d["fga"][i] or 0, "fg3m": d["fg3m"][i] or 0,
                    "fta": d["fta"][i] or 0, "oreb": d["oreb"][i] or 0, "tov": d["tov"][i] or 0,
                    "season": season, "stype": str(d["season_type"][i])})
    return out


def _espn_scores(season):
    p = f"{STAGE}/ESPN/wnba/team_box/parquet/team_box_{season}.parquet"
    d = pq.read_table(p).to_pydict()
    g = {}
    for i in range(len(d["game_id"])):
        t = str(d["team_abbreviation"][i])
        if t in EXHIB:
            continue
        g.setdefault(str(d["game_id"][i]), {})[_xw(t, season)] = (
            d["team_score"][i], str(d["game_date"][i])[:10])
    out = set()
    for tm in g.values():
        if len(tm) != 2:
            continue
        ts = sorted(tm)
        out.add((tm[ts[0]][1], ts[0], ts[1], tm[ts[0]][0], tm[ts[1]][0]))
    return out


def build_games():
    """Official-plus-one game rows: [{date, season, home, away, hpts, apts, stats per side}]."""
    games = []
    for season in range(2017, 2027):
        rows = _official_rows(season)
        espn = _espn_scores(season)
        by_gid = {}
        for r in rows:
            by_gid.setdefault(r["gid"], []).append(r)
        for gid, pair in by_gid.items():
            if len(pair) != 2:
                continue
            home = next((r for r in pair if " vs" in r["matchup"]), None)
            away = next((r for r in pair if " @" in r["matchup"]), None)
            if home is None or away is None:
                continue
            key_ts = sorted([home["team"], away["team"]])
            key = (home["date"], key_ts[0], key_ts[1],
                   (home if key_ts[0] == home["team"] else away)["pts"],
                   (home if key_ts[1] == home["team"] else away)["pts"])
            if key not in espn:
                continue  # official-plus-one: unconfirmed rows stay out
            games.append({"date": home["date"], "season": season, "gid": gid,
                          "home": home["team"], "away": away["team"],
                          "hpts": home["pts"], "apts": away["pts"], "H": home, "A": away})
    games.sort(key=lambda g: (g["date"], g["gid"]))
    return games


class TeamState:
    """Season-to-date accumulators; everything read BEFORE the update for the current game."""
    def __init__(self):
        self.s = {}

    def key(self, season, team):
        return (season, team)

    def get(self, season, team):
        return self.s.get(self.key(season, team))

    def feats(self, season, team, date):
        st = self.get(season, team)
        if not st or st["g"] < MIN_TEAM_GAMES:
            return None
        poss = st["fga"] - st["oreb"] + st["tov"] + 0.44 * st["fta"]
        opos = st["ofga"] - st["ooreb"] + st["otov"] + 0.44 * st["ofta"]
        if poss <= 0 or opos <= 0:
            return None
        net = st["pts"] / poss - st["opts"] / opos
        w = st["g"] / (st["g"] + SHRINK_G)
        last = dt.date.fromisoformat(st["last"])
        rest = min((dt.date.fromisoformat(date) - last).days, 5)
        return {"net": net * w, "efg": (st["fgm"] + 0.5 * st["fg3m"]) / st["fga"],
                "tov": st["tov"] / poss, "orb": st["oreb"] / max(st["fga"] - st["fgm"], 1),
                "ftr": st["fta"] / st["fga"], "rest": float(rest), "b2b": 1.0 if rest == 1 else 0.0,
                "pace": poss / st["g"], "g": st["g"]}

    def update(self, g):
        for side, opp in (("H", "A"), ("A", "H")):
            r, o = g[side], g[opp]
            k = self.key(g["season"], r["team"])
            st = self.s.setdefault(k, dict(g=0, pts=0, opts=0, fgm=0, fga=0, fg3m=0, fta=0,
                                           oreb=0, tov=0, ofga=0, ooreb=0, otov=0, ofta=0,
                                           last=g["date"]))
            st["g"] += 1
            st["pts"] += r["pts"]; st["opts"] += o["pts"]
            st["fgm"] += r["fgm"]; st["fga"] += r["fga"]; st["fg3m"] += r["fg3m"]
            st["fta"] += r["fta"]; st["oreb"] += r["oreb"]; st["tov"] += r["tov"]
            st["ofga"] += o["fga"]; st["ooreb"] += o["oreb"]; st["otov"] += o["tov"]
            st["ofta"] += o["fta"]
            st["last"] = g["date"]


def make_rows(games):
    """Feature rows in date order + league running totals for the total target."""
    ts = TeamState()
    rows = []
    lg_tot_sum, lg_tot_n, lg_pace_sum = 0.0, 0, 0.0
    for g in games:
        fh = ts.feats(g["season"], g["home"], g["date"])
        fa = ts.feats(g["season"], g["away"], g["date"])
        if fh and fa and lg_tot_n >= 50:
            x = np.array([fh["net"] - fa["net"], fh["efg"] - fa["efg"], fa["tov"] - fh["tov"],
                          fh["orb"] - fa["orb"], fh["ftr"] - fa["ftr"], fh["rest"] - fa["rest"],
                          fh["b2b"] - fa["b2b"]], float)
            lg_mean_tot = lg_tot_sum / lg_tot_n
            lg_mean_pace = lg_pace_sum / lg_tot_n
            xt = np.array([lg_mean_tot, (fh["pace"] + fa["pace"]) - 2 * lg_mean_pace,
                           fh["net"] + fa["net"]], float)
            rows.append({"date": g["date"], "gid": g["gid"], "x": x, "xt": xt,
                         "y": 1 if g["hpts"] > g["apts"] else 0,
                         "margin": g["hpts"] - g["apts"], "total": g["hpts"] + g["apts"]})
        ts.update(g)
        lg_tot_sum += g["hpts"] + g["apts"]; lg_tot_n += 1
        lg_pace_sum += ((g["H"]["fga"] - g["H"]["oreb"] + g["H"]["tov"] + 0.44 * g["H"]["fta"])
                        + (g["A"]["fga"] - g["A"]["oreb"] + g["A"]["tov"] + 0.44 * g["A"]["fta"])) / 2
    return rows, ts, (lg_tot_sum, lg_tot_n, lg_pace_sum)


def _std_partial(Xtr, Xte, ncont=CONT):
    """Standardize only the first ncont columns (b2b_edge stays raw — v0.3 lesson)."""
    Xtr2, Xte2 = Xtr.copy(), Xte.copy()
    mu = Xtr[:, :ncont].mean(0)
    sd = Xtr[:, :ncont].std(0); sd[sd == 0] = 1.0
    Xtr2[:, :ncont] = (Xtr[:, :ncont] - mu) / sd
    Xte2[:, :ncont] = (Xte[:, :ncont] - mu) / sd
    return Xtr2, Xte2


def walk_forward(rows):
    dates = sorted({r["date"] for r in rows})
    out = {"p": [], "y": [], "d": [], "base": [], "m_pred": [], "m_act": [], "m_base": [],
           "t_pred": [], "t_act": [], "t_base": []}
    l2g = (0.1, 1.0, 10.0, 100.0)
    for d in dates:
        tr = [r for r in rows if r["date"] < d]
        te = [r for r in rows if r["date"] == d]
        if len(tr) < BURN_IN or not te:
            continue
        Xtr = np.array([r["x"] for r in tr]); ytr = np.array([r["y"] for r in tr], float)
        Xte = np.array([r["x"] for r in te])
        Xtr_s, Xte_s = _std_partial(Xtr, Xte)
        cut = int(len(tr) * 0.8)
        best, bl2 = None, 1.0
        if cut > 50 and len(tr) - cut > 20:
            Xi, Xo = _std_partial(Xtr[:cut], Xtr[cut:])
            for l2 in l2g:
                m = metrics(predict_logistic(fit_logistic(Xi, ytr[:cut], l2=l2), Xo), ytr[cut:])["brier"]
                if best is None or m < best:
                    best, bl2 = m, l2
        p = predict_logistic(fit_logistic(Xtr_s, ytr, l2=bl2), Xte_s)
        mtr = np.array([r["margin"] for r in tr], float)
        bm = fit_ols(Xtr_s, mtr, l2=bl2)
        mp = _ols_raw(bm, Xte_s)
        Xt_tr = np.array([r["xt"] for r in tr]); Xt_te = np.array([r["xt"] for r in te])
        ttr = np.array([r["total"] for r in tr], float)
        Xt_trs, Xt_tes = _standardize(Xt_tr, Xt_te)
        tp = _ols_raw(fit_ols(Xt_trs, ttr, l2=1.0), Xt_tes)
        for i, r in enumerate(te):
            out["p"].append(float(p[i])); out["y"].append(r["y"]); out["d"].append(d)
            out["base"].append(ytr.mean())
            out["m_pred"].append(float(mp[i])); out["m_act"].append(r["margin"])
            out["m_base"].append(float(mtr.mean()))
            out["t_pred"].append(float(tp[i])); out["t_act"].append(r["total"])
            out["t_base"].append(float(ttr.mean()))
    return out


def evaluate(out):
    p, y = np.array(out["p"]), np.array(out["y"], float)
    base = np.array(out["base"]); dts = out["d"]
    rep = {"n": len(y), "dates": len(set(dts)),
           "home_win": {"brier": float(np.mean((p - y) ** 2)),
                        "base_brier": float(np.mean((base - y) ** 2)),
                        "auc": roc_auc(p, y), "calibration": calibration_fit(p, y),
                        "accuracy": float(((p >= .5) == (y == 1)).mean())},
           "margin": {"mae": float(np.mean(np.abs(np.array(out["m_pred"]) - np.array(out["m_act"])))),
                      "base_mae": float(np.mean(np.abs(np.array(out["m_base"]) - np.array(out["m_act"]))))},
           "total": {"mae": float(np.mean(np.abs(np.array(out["t_pred"]) - np.array(out["t_act"])))),
                     "base_mae": float(np.mean(np.abs(np.array(out["t_base"]) - np.array(out["t_act"]))))}}
    comps = {"win_vs_base": date_block_bootstrap(p, base, y, dts)}
    # margin / total: paired |err| difference, date-block bootstrap on the same machinery via squared->abs trick
    for key, pr, ac, bs in (("margin_vs_base", "m_pred", "m_act", "m_base"),
                            ("total_vs_base", "t_pred", "t_act", "t_base")):
        a = np.abs(np.array(out[pr]) - np.array(out[ac]))
        b = np.abs(np.array(out[bs]) - np.array(out[ac]))
        rng = np.random.default_rng(11)
        uniq = sorted(set(dts)); idx = {dd: [i for i, x in enumerate(dts) if x == dd] for dd in uniq}
        obs = float(np.mean(a - b)); st = []
        for _ in range(4000):
            pick = rng.choice(uniq, size=len(uniq), replace=True)
            ii = np.concatenate([idx[dd] for dd in pick])
            st.append(np.mean(a[ii] - b[ii]))
        st = np.array(st)
        pv = 2.0 * min((st >= 0).mean(), (st <= 0).mean())
        comps[key] = {"dMAE": obs, "ci95": [float(np.percentile(st, 2.5)), float(np.percentile(st, 97.5))],
                      "p": float(min(1.0, pv)), "n_dates": len(uniq)}
    rep["comparisons"] = comps
    rep["holm"] = holm({k: v["p"] for k, v in comps.items()})
    hw = rep["home_win"]; c = comps["win_vs_base"]; hl = rep["holm"]["win_vs_base"]
    rep["gates"] = {
        "win_p_holm_improving": bool(hl["p_holm"] < 0.05 and c["dBrier"] < 0 and c["ci95"][1] < 0),
        "cal_slope": bool(0.85 <= hw["calibration"]["slope"] <= 1.15),
        "cal_intercept": bool(-0.15 <= hw["calibration"]["intercept"] <= 0.15),
        "auc_above_half": bool(hw["auc"] > 0.5)}
    rep["WIN_TARGET_PASS"] = all(rep["gates"].values())
    rep["target_status"] = {
        "home_win": "VALIDATED_VS_BASELINE" if rep["WIN_TARGET_PASS"] else "FAILED_GATES",
        "margin": ("VALIDATED_VS_BASELINE" if rep["holm"]["margin_vs_base"]["p_holm"] < 0.05
                   and comps["margin_vs_base"]["dMAE"] < 0 else "NOT_BETTER_THAN_BASELINE"),
        "total": ("VALIDATED_VS_BASELINE" if rep["holm"]["total_vs_base"]["p_holm"] < 0.05
                  and comps["total_vs_base"]["dMAE"] < 0 else "NOT_BETTER_THAN_BASELINE")}
    return rep


def fit_full(rows):
    X = np.array([r["x"] for r in rows]); y = np.array([r["y"] for r in rows], float)
    mu = X[:, :CONT].mean(0); sd = X[:, :CONT].std(0); sd[sd == 0] = 1.0
    Xs = X.copy(); Xs[:, :CONT] = (X[:, :CONT] - mu) / sd
    blog = fit_logistic(Xs, y, l2=1.0)
    bmar = fit_ols(Xs, np.array([r["margin"] for r in rows], float), l2=1.0)
    Xt = np.array([r["xt"] for r in rows]); tmu = Xt.mean(0); tsd = Xt.std(0); tsd[tsd == 0] = 1
    btot = fit_ols((Xt - tmu) / tsd, np.array([r["total"] for r in rows], float), l2=1.0)
    return {"mu": mu, "sd": sd, "blog": blog, "bmar": bmar, "tmu": tmu, "tsd": tsd, "btot": btot}


def predict_slate(model, ts, lg, slate, season=2026):
    lg_tot_sum, lg_tot_n, lg_pace_sum = lg
    out = []
    for away, home, tip in slate:
        tip_et = et_date(tip)                # ET date of the tip instant (was tip[:10] UTC slice)
        fh = ts.feats(season, home, tip_et)
        fa = ts.feats(season, away, tip_et)
        if not fh or not fa:
            out.append({"away": away, "home": home, "tip_utc": tip, "et_date": tip_et,
                        "status": "DATA_BLOCKED (insufficient season history)"})
            continue
        x = np.array([fh["net"] - fa["net"], fh["efg"] - fa["efg"], fa["tov"] - fh["tov"],
                      fh["orb"] - fa["orb"], fh["ftr"] - fa["ftr"], fh["rest"] - fa["rest"],
                      fh["b2b"] - fa["b2b"]], float)
        xs = x.copy(); xs[:CONT] = (x[:CONT] - model["mu"]) / model["sd"]
        p = float(predict_logistic(model["blog"], xs[None, :])[0])
        m = float(_ols_raw(model["bmar"], xs[None, :])[0])
        xt = np.array([lg_tot_sum / lg_tot_n,
                       (fh["pace"] + fa["pace"]) - 2 * (lg_pace_sum / lg_tot_n),
                       fh["net"] + fa["net"]], float)
        t = float(_ols_raw(model["btot"], ((xt - model["tmu"]) / model["tsd"])[None, :])[0])
        coher = abs(p - 0.5 * (1 + math.erf((m / MARGIN_SD) / math.sqrt(2))))
        out.append({"away": away, "home": home, "tip_utc": tip, "et_date": tip_et,
                    "date_timezone": "America/New_York", "p_home": round(p, 4),
                    "margin_home": round(m, 2), "total": round(t, 1),
                    "coherence_gap_pp": round(coher * 100, 2), "coherence_pass": bool(coher <= 0.05),
                    "games_used": {"home": fh["g"], "away": fa["g"]}})
    return out


def selftest():
    fails = []
    rng = np.random.default_rng(3)
    n = 2000
    X = rng.normal(size=(n, 7)); X[:, 6] = rng.choice([-1, 0, 1], n)
    z = 1.2 * X[:, 0] + 0.5 * X[:, 1] - 0.4 * X[:, 6]
    y = (1 / (1 + np.exp(-z)) > rng.random(n)).astype(float)
    Xs, _ = _std_partial(X, X)
    if not np.allclose(Xs[:, 6], X[:, 6]):
        fails.append("b2b column was standardized — v0.3 incident class")
    b = fit_logistic(Xs, y, l2=1e-6)
    if not (b[1] > 0.6 and b[7] < -0.1):
        fails.append(f"logistic failed to recover planted signal: {b}")
    ts = TeamState()
    g = {"season": 2026, "date": "2026-06-01", "home": "AAA", "away": "BBB", "hpts": 90, "apts": 80,
         "H": {"team": "AAA", "pts": 90, "fgm": 33, "fga": 70, "fg3m": 9, "fta": 20, "oreb": 8, "tov": 12},
         "A": {"team": "BBB", "pts": 80, "fgm": 30, "fga": 72, "fg3m": 6, "fta": 15, "oreb": 9, "tov": 15}}
    ts.update(g)
    if ts.feats(2026, "AAA", "2026-06-02") is not None:
        fails.append("feats emitted below MIN_TEAM_GAMES — as-of guard broken")
    for i in range(5):
        gg = dict(g); gg["date"] = f"2026-06-0{i+2}"
        ts.update(gg)
    f = ts.feats(2026, "AAA", "2026-06-07")   # last game 6/06 -> next day IS a back-to-back
    if not f or f["b2b"] != 1.0 or f["rest"] != 1.0:
        fails.append("rest/b2b computation wrong on a true next-day game")
    f2 = ts.feats(2026, "AAA", "2026-06-09")  # two days off -> not a b2b
    if not f2 or f2["b2b"] != 0.0 or f2["rest"] != 3.0:
        fails.append("rest/b2b wrongly fires on a non-b2b gap")
    # UTC-tip defect class: a 2026-07-23T00:00Z tip is the ET EVENING of 2026-07-22, so against a
    # last game on ET 2026-07-21 it is a back-to-back (rest=1/b2b=1), NOT rest=2 as tip[:10] gave.
    if et_date("2026-07-23T00:00Z") != "2026-07-22" or et_date("2026-07-23T02:00Z") != "2026-07-22":
        fails.append("et_date does not map a 00:00Z/02:00Z tip to the ET evening before")
    ts2 = TeamState()
    g7 = dict(g); g7["date"] = "2026-07-15"
    ts2.update(g7)
    for i in range(5):
        g8 = dict(g); g8["date"] = f"2026-07-{16+i:02d}"
        ts2.update(g8)                      # last game ET 2026-07-20... then one more:
    g9 = dict(g); g9["date"] = "2026-07-21"
    ts2.update(g9)                          # last game ET 2026-07-21
    f3 = ts2.feats(2026, "AAA", et_date("2026-07-23T00:00Z"))
    if not f3 or f3["rest"] != 1.0 or f3["b2b"] != 1.0:
        fails.append("a 2026-07-23T00:00Z tip vs a 2026-07-21 ET last game must be rest=1/b2b=1 "
                     "(the tip is the ET evening of 07-22)")
    yy = np.array([150.0, 160.0, 170.0, 155.0, 165.0] * 40)
    XX = rng.normal(size=(200, 2))
    if not (120 < _ols_raw(fit_ols(XX, yy, l2=1.0), XX).mean() < 200):
        fails.append("unclipped OLS does not recover a 160-scale target — the clip bug class")
    print("wnba_model_v1 selftest:", "FAIL\n  " + "\n  ".join(fails) if fails else
          "PASS (no-binary-standardization guard, signal recovery, as-of minimum, rest/b2b)")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    games = build_games()
    rows, ts, lg = make_rows(games)
    print(f"official-plus-one games: {len(games)}; feature rows: {len(rows)}; "
          f"latest label date: {max(g['date'] for g in games)}")
    out = walk_forward(rows)
    rep = evaluate(out)
    rep["model_id"] = "wnba.rs.ff7_logit_ridge.v1_0.shadow"
    rep["prereg"] = "docs/experiments/2026-08-12_WNBA_V1_PREREG.json"
    rep["feature_state_as_of"] = max(g["date"] for g in games)
    json.dump(rep, open("data/wnba/model/2026-08-12_v1_walkforward.json", "w"), indent=1)
    hw = rep["home_win"]
    print(f"n={rep['n']} over {rep['dates']} dates")
    print(f"  home_win: brier {hw['brier']:.5f} vs base {hw['base_brier']:.5f}  auc {hw['auc']:.4f}  "
          f"slope {hw['calibration']['slope']:+.3f} icpt {hw['calibration']['intercept']:+.3f}  "
          f"acc {hw['accuracy']:.3f}")
    for k, c in rep["comparisons"].items():
        h = rep["holm"][k]
        key = "dBrier" if "dBrier" in c else "dMAE"
        print(f"  {k:16} {key} {c[key]:+.5f}  CI[{c['ci95'][0]:+.5f},{c['ci95'][1]:+.5f}]  "
              f"p_holm {h['p_holm']:.4f}")
    print(f"  margin MAE {rep['margin']['mae']:.3f} vs base {rep['margin']['base_mae']:.3f}; "
          f"total MAE {rep['total']['mae']:.3f} vs base {rep['total']['base_mae']:.3f}")
    print(f"  gates: {rep['gates']}  -> WIN_TARGET_PASS = {rep['WIN_TARGET_PASS']}")
    print(f"  target_status: {rep['target_status']}")
    if rep["WIN_TARGET_PASS"] and "--card" in sys.argv:
        model = fit_full(rows)
        slate = [("TOR", "DAL", "2026-08-13T00:00Z"), ("MIN", "PDX", "2026-08-13T02:00Z"),
                 ("CHI", "GSV", "2026-08-13T02:00Z")]
        card = predict_slate(model, ts, lg, slate)
        os.makedirs("data/wnba/forecasts", exist_ok=True)
        json.dump({"model_id": rep["model_id"], "slate_date": "2026-08-12",
                   "feature_state_as_of": rep["feature_state_as_of"],
                   "target_status": rep["target_status"], "rows": card},
                  open("data/wnba/forecasts/2026-08-12_card_draft.json", "w"), indent=1)
        for r in card:
            if "p_home" in r:
                print(f"  CARD {r['away']}@{r['home']}: p_home {r['p_home']:.3f} margin "
                      f"{r['margin_home']:+.1f} total {r['total']:.1f} coherence "
                      f"{'PASS' if r['coherence_pass'] else 'FAIL'} ({r['coherence_gap_pp']}pp)")
            else:
                print(f"  CARD {r['away']}@{r['home']}: {r['status']}")
