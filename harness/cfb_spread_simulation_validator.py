#!/usr/bin/env python3
"""Fail-closed validation for CFB margin/ATS forecast artifacts."""
from __future__ import annotations
from datetime import datetime

MODULE_ID = "cfb_spread_simulation_validator"
MIN_SIMS = 50_000


def _dt(x):
    return datetime.fromisoformat(str(x).replace("Z", "+00:00"))


def validate(a):
    v=[]
    required=("event_id","generated_at_utc","frozen_at_utc","game_start_utc","model","input_snapshot","projection","simulation","governance")
    for k in required:
        if a.get(k) in (None,""): v.append(f"MISSING_{k.upper()}")
    if v: return v
    if _dt(a["generated_at_utc"]) >= _dt(a["game_start_utc"]): v.append("POST_START_FORECAST")
    if _dt(a["frozen_at_utc"]) >= _dt(a["game_start_utc"]): v.append("POST_START_FREEZE")
    m=a["model"]; s=a["simulation"]; p=a["projection"]; g=a["governance"]
    for k in ("margin_model_id","margin_model_version","elo_model_id","git_commit"):
        if not m.get(k): v.append(f"MODEL_MISSING_{k.upper()}")
    snap=a["input_snapshot"]
    for k in ("snapshot_id","feature_schema_version","data_health"):
        if not snap.get(k): v.append(f"INPUT_MISSING_{k.upper()}")
    if s.get("run_count",0) < MIN_SIMS: v.append("SIM_COUNT_BELOW_MINIMUM")
    if s.get("seed") is None: v.append("SIM_SEED_MISSING")
    if float(p.get("home_margin_sd",0)) <= 0: v.append("NONPOSITIVE_MARGIN_SD")
    for k in ("home_win_p_model","home_win_p_sim"):
        x=p.get(k)
        if x is None or not 0 <= float(x) <= 1: v.append(f"INVALID_{k.upper()}")
    mp=a.get("market_pricing")
    if mp:
        if mp.get("home_spread") is None: v.append("ATS_PROBABILITY_WITHOUT_SPREAD")
        probs=[mp.get("home_cover_p_sim"),mp.get("push_p_sim"),mp.get("away_cover_p_sim")]
        if any(x is None or not 0 <= float(x) <= 1 for x in probs): v.append("INVALID_ATS_PROBABILITY")
        elif abs(sum(map(float,probs))-1.0)>1e-6: v.append("ATS_PROBABILITIES_DO_NOT_SUM_TO_ONE")
    if g.get("forecast_registered") is not True: v.append("FORECAST_NOT_REGISTERED")
    if g.get("action_status")=="PLAY" and g.get("authority_mode")!="PRODUCTION": v.append("PLAY_WITHOUT_PRODUCTION_AUTHORITY")
    if a.get("population") != "FBS_VS_FBS": v.append("OUTSIDE_DECLARED_FBS_POPULATION")
    if a.get("market_features_used"): v.append("MARKET_INPUT_LEAKAGE")
    return v


def selftest():
    a={"event_id":"E1","generated_at_utc":"2026-09-03T19:00:00Z","frozen_at_utc":"2026-09-03T19:01:00Z","game_start_utc":"2026-09-03T23:00:00Z","population":"FBS_VS_FBS","market_features_used":False,
       "model":{"margin_model_id":"cfb.margin_distribution.v1","margin_model_version":"1.0.0","elo_model_id":"elo","git_commit":"abc"},
       "input_snapshot":{"snapshot_id":"sha256:x","feature_schema_version":"v1","data_health":"GREEN"},
       "projection":{"home_margin_sd":14.0,"home_win_p_model":.6,"home_win_p_sim":.59},
       "simulation":{"run_count":100000,"seed":1},"market_pricing":{"home_spread":-6.5,"home_cover_p_sim":.45,"push_p_sim":0,"away_cover_p_sim":.55},
       "governance":{"forecast_registered":True,"authority_mode":"SHADOW_ONLY","action_status":"BLOCKED"}}
    assert validate(a)==[], validate(a)
    print("cfb_spread_simulation_validator selftest: PASS")

if __name__=="__main__": selftest()
