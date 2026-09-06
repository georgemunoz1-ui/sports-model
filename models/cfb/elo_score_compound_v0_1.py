#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, math
from dataclasses import dataclass
from typing import Dict, Tuple
import numpy as np
from scipy.stats import norm

ENGINE_ID = "cfb.compound_score_mc.v0_1"
FBS_MODEL_ID = "cfb.fbs.causal_elo_score_compound.v0_1.shadow"
FCS_MODEL_ID = "cfb.fcs.causal_elo_score_compound.v0_1.shadow"
WEEK1_MARGIN_SD = 18.3852
ELO_HOME_ADVANTAGE = 55.0
TD_POINT_SHARE = 0.8623008108769842
N_SIMS = 100_000


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def canonical_hash(obj) -> str:
    return sha256_bytes(json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())

def elo_prob(home_elo: float, away_elo: float, neutral: bool, include_hfa: bool=True) -> float:
    diff = home_elo - away_elo + (0.0 if neutral or not include_hfa else ELO_HOME_ADVANTAGE)
    return 1.0 / (1.0 + 10.0 ** (-diff / 400.0))

def poisson_probs(lam: float, tail_tol: float=1e-14):
    probs=[math.exp(-lam)]
    s=probs[0]
    k=0
    while 1.0-s > tail_tol and k < 200:
        k += 1
        probs.append(probs[-1]*lam/k)
        s += probs[-1]
    return probs, max(0.0,1.0-s)

def score_pmf(mean_points: float, td_share: float=TD_POINT_SHARE):
    lam_td = mean_points * td_share / 7.0
    lam_fg = mean_points * (1.0-td_share) / 3.0
    ptd, ttd = poisson_probs(lam_td)
    pfg, tfg = poisson_probs(lam_fg)
    max_score = 7*(len(ptd)-1)+3*(len(pfg)-1)
    pmf=np.zeros(max_score+1, dtype=float)
    for td,p1 in enumerate(ptd):
        for fg,p2 in enumerate(pfg):
            pmf[7*td+3*fg] += p1*p2
    return pmf, min(1.0,ttd+tfg), lam_td, lam_fg

def analytic_distribution(away_mean: float, home_mean: float, p_ot_home: float):
    apmf, atail, atd, afg = score_pmf(away_mean)
    hpmf, htail, htd, hfg = score_pmf(home_mean)
    n=max(len(apmf),len(hpmf))
    a=np.pad(apmf,(0,n-len(apmf)))
    h=np.pad(hpmf,(0,n-len(hpmf)))
    tie=float(np.dot(a,h))
    home_reg=0.0
    for hs,ph in enumerate(h):
        if ph:
            home_reg += ph*float(a[:hs].sum())
    away_reg=max(0.0, float(a.sum()*h.sum())-home_reg-tie)
    home_win=home_reg+tie*p_ot_home
    away_win=away_reg+tie*(1.0-p_ot_home)
    home_final_mean=home_mean+2.0*tie*p_ot_home
    away_final_mean=away_mean+2.0*tie*(1.0-p_ot_home)
    return {
        "home_win_probability": home_win,
        "away_win_probability": away_win,
        "regulation_tie_probability": tie,
        "home_expected_points": home_final_mean,
        "away_expected_points": away_final_mean,
        "expected_home_margin": home_final_mean-away_final_mean,
        "expected_total": home_final_mean+away_final_mean,
        "pmf_tail_bound": atail+htail,
        "home_td_lambda": htd,"home_fg_lambda": hfg,
        "away_td_lambda": atd,"away_fg_lambda": afg,
    }

def monte_carlo(away_mean: float, home_mean: float, p_ot_home: float, seed: int, n: int=N_SIMS):
    rng=np.random.default_rng(seed)
    def draw(mean):
        td=rng.poisson(mean*TD_POINT_SHARE/7.0,n)
        fg=rng.poisson(mean*(1.0-TD_POINT_SHARE)/3.0,n)
        return 7*td+3*fg
    a=draw(away_mean)
    h=draw(home_mean)
    ties=(a==h)
    idx=np.flatnonzero(ties)
    if len(idx):
        home_ot=rng.random(len(idx)) < p_ot_home
        h[idx[home_ot]] += 2
        a[idx[~home_ot]] += 2
    margin=h-a
    total=h+a
    return {
        "simulation_count": n,
        "seed": int(seed),
        "home_win_probability": float((margin>0).mean()),
        "away_win_probability": float((margin<0).mean()),
        "final_tie_probability": float((margin==0).mean()),
        "regulation_tie_frequency": float(ties.mean()),
        "home_expected_points": float(h.mean()),
        "away_expected_points": float(a.mean()),
        "expected_home_margin": float(margin.mean()),
        "expected_total": float(total.mean()),
        "home_points_p10_p90": [float(np.quantile(h,.10)),float(np.quantile(h,.90))],
        "away_points_p10_p90": [float(np.quantile(a,.10)),float(np.quantile(a,.90))],
        "margin_p10_p90": [float(np.quantile(margin,.10)),float(np.quantile(margin,.90))],
        "total_p10_p90": [float(np.quantile(total,.10)),float(np.quantile(total,.90))],
        "margin_sd": float(margin.std(ddof=0)),
    }

def forecast_game(game: dict, teams: Dict[str,dict], cutoff_utc: str, n: int=N_SIMS):
    away=teams[game["away"]]; home=teams[game["home"]]
    p_elo=elo_prob(home["elo"],away["elo"],game["neutral_site"],True)
    p_ot=elo_prob(home["elo"],away["elo"],True,False)
    regulation_margin=float(norm.ppf(p_elo)*WEEK1_MARGIN_SD)
    away_matchup=(away["pf_prior"]+home["pa_prior"])/2.0
    home_matchup=(home["pf_prior"]+away["pa_prior"])/2.0
    regulation_total=away_matchup+home_matchup
    away_mean=max(3.0,(regulation_total-regulation_margin)/2.0)
    home_mean=max(3.0,(regulation_total+regulation_margin)/2.0)
    input_obj={
        "game":game,"away_state":away,"home_state":home,
        "week1_margin_sd":WEEK1_MARGIN_SD,"elo_hfa":ELO_HOME_ADVANTAGE,
        "td_point_share":TD_POINT_SHARE,"regulation_total_method":"offense_defense_arithmetic_matchup_blend",
        "ot_resolution":"NCAA_simplified_two_point_tiebreak_after_regulation_tie",
    }
    input_hash=canonical_hash(input_obj)
    model_id=FCS_MODEL_ID if game["classification"]=="FCS_FCS" else FBS_MODEL_ID
    seed=int.from_bytes(hashlib.sha256(f"{model_id}|{cutoff_utc}|{game['game_id']}|{input_hash}|{n}".encode()).digest()[:8],"big")%(2**32)
    analytic=analytic_distribution(away_mean,home_mean,p_ot)
    sim=monte_carlo(away_mean,home_mean,p_ot,seed,n)
    dp=abs(analytic["home_win_probability"]-sim["home_win_probability"])
    status="ALIGNED" if dp<0.005 else ("WATCH" if dp<0.010 else "DIVERGENT")
    return {
        "game_id":game["game_id"],"away":game["away"],"home":game["home"],
        "venue":game["venue"],"scheduled_start_utc":game["scheduled_start_utc"],
        "scheduled_start_pt":game["scheduled_start_pt"],"neutral_site":game["neutral_site"],
        "classification":game["classification"],"model_id":model_id,"engine_id":ENGINE_ID,
        "forecast_cutoff_utc":cutoff_utc,"input_snapshot_hash":input_hash,
        "source_strength":{
            "away_elo":away["elo"],"home_elo":home["elo"],"elo_home_advantage":0 if game["neutral_site"] else ELO_HOME_ADVANTAGE,
            "elo_prior_home_win_probability":p_elo,"ot_home_probability":p_ot,
        },
        "scoring_inputs":{
            "away_pf_prior":away["pf_prior"],"away_pa_prior":away["pa_prior"],
            "home_pf_prior":home["pf_prior"],"home_pa_prior":home["pa_prior"],
            "regulation_expected_total":regulation_total,"regulation_expected_home_margin":regulation_margin,
            "regulation_away_mean":away_mean,"regulation_home_mean":home_mean,
            "td_point_share":TD_POINT_SHARE,
        },
        "analytic":analytic,"monte_carlo":sim,
        "analytic_mc_abs_diff":dp,"analytic_mc_status":status,
        "support_level":"DIAGNOSTIC_SHADOW" if game["classification"]=="FBS_FBS" else "DIAGNOSTIC_UNVALIDATED_FCS",
        "action_authority":"OFF","market_used_as_predictive_input":False,
    }

if __name__ == "__main__":
    print("model module; use run_cfb_20260906.py")
