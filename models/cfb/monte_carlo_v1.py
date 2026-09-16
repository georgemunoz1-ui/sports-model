#!/usr/bin/env python3
"""Reproducible CFB Monte Carlo inference for DIAGNOSTIC_SHADOW.

Forecast inputs are market-independent. A market spread may be supplied only after
margin draws exist, solely to evaluate cover probability.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, subprocess
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

ENGINE_ID = "cfb.monte_carlo_margin.v1"
ENGINE_VERSION = "1.0.0"
MIN_SIMS = 50_000


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

def sha_obj(obj): return "sha256:" + hashlib.sha256(canonical(obj)).hexdigest()
def sha_file(path): return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()
def git_commit():
    try: return subprocess.check_output(["git","rev-parse","HEAD"], text=True).strip()
    except Exception: return "UNKNOWN"
def seed_for(event_id, input_hash, state_hash):
    msg=f"{event_id}|{input_hash}|{state_hash}|{ENGINE_VERSION}".encode()
    return int.from_bytes(hashlib.sha256(msg).digest()[:4], "big", signed=False)
def fnum(x):
    try:
        v=float(x)
        return v if math.isfinite(v) else None
    except Exception: return None

def load_row(schedule_path, event_id):
    with open(schedule_path, newline="") as f:
        for r in csv.DictReader(f):
            if str(r["game_id"]) == str(event_id): return r
    raise SystemExit(f"EVENT_NOT_FOUND:{event_id}")

def build_snapshot(row, elo_state):
    home_sched=fnum(row.get("home_pregame_elo")); away_sched=fnum(row.get("away_pregame_elo"))
    ratings=elo_state.get("team_elo", {})
    home_elo=home_sched if home_sched is not None else fnum(ratings.get(row["home_team"]))
    away_elo=away_sched if away_sched is not None else fnum(ratings.get(row["away_team"]))
    if home_elo is None or away_elo is None:
        raise SystemExit("RATING_FALLBACK_EXHAUSTED")
    home_div=str(row.get("home_division","")).lower(); away_div=str(row.get("away_division","")).lower()
    pop="FBS_VS_FBS" if home_div=="fbs" and away_div=="fbs" else "CROSS_DIVISION"
    return {
      "event_id": str(row["game_id"]), "game_start_utc": row["start_date"],
      "home_team": row["home_team"], "away_team": row["away_team"],
      "home_division": home_div, "away_division": away_div,
      "week": int(float(row["week"])), "neutral_site": str(row.get("neutral_site","")).upper()=="TRUE",
      "conference_game": str(row.get("conference_game","")).upper()=="TRUE",
      "home_elo_pre": home_elo, "away_elo_pre": away_elo,
      "elo_diff_with_home_advantage": home_elo-away_elo,
      "rating_source_home": "schedule_pregame_elo" if home_sched is not None else "causal_elo_fallback",
      "rating_source_away": "schedule_pregame_elo" if away_sched is not None else "causal_elo_fallback",
      "population": pop
    }

def run(snapshot, state, n_sims, home_spread=None):
    if n_sims < MIN_SIMS: raise SystemExit(f"SIMULATION_COUNT_BELOW_MINIMUM:{MIN_SIMS}")
    p=state["parameters"]
    mu=(float(p["intercept"]) + float(p["elo_diff_coefficient"])*snapshot["elo_diff_with_home_advantage"]
        + float(p["neutral_site_coefficient"])*float(snapshot["neutral_site"])
        + float(p["conference_game_coefficient"])*float(snapshot["conference_game"]))
    sigmas=state["residual_model"].get("segment_sigma_by_week", {})
    sigma=float(sigmas.get(str(snapshot["week"]), state["residual_model"]["global_sigma"]))
    tier="PRIMARY_SHADOW"; quality="MEDIUM"; adjustments=[]
    if snapshot["population"] != "FBS_VS_FBS":
        # The fitted margin state is FBS-v-FBS. Cross-division output is an explicit
        # emergency extrapolation using available causal ratings with wider variance.
        sigma *= 1.25; tier="EMERGENCY_DIAGNOSTIC"; quality="MINIMUM"
        adjustments.append("CROSS_DIVISION_SIGMA_MULTIPLIER_1.25")
    input_hash=sha_obj(snapshot); state_hash=sha_obj(state); seed=seed_for(snapshot["event_id"],input_hash,state_hash)
    rng=np.random.default_rng(seed); margins=rng.normal(mu,sigma,int(n_sims))
    q=np.quantile(margins,[.10,.25,.50,.75,.90])
    out={
      "artifact_type":"cfb_monte_carlo_forecast_bundle_v1", "event_id":snapshot["event_id"],
      "forecast_mode":"DIAGNOSTIC_SHADOW", "forecast_tier":tier, "forecast_quality":quality,
      "game_start_utc":snapshot["game_start_utc"], "generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
      "model":{"model_id":state["model_id"],"model_version":state["version"],"model_fit_commit":state["code_commit"],"runtime_commit":git_commit()},
      "input_snapshot":snapshot, "input_snapshot_hash":input_hash, "model_state_config_hash":state_hash,
      "distribution_specification":{"family":"Normal","variable":"home_final_margin","mu":mu,"sigma":sigma},
      "simulation":{"simulation_engine":ENGINE_ID,"simulation_engine_version":ENGINE_VERSION,"rng":"numpy.PCG64","simulation_count":int(n_sims),"random_seed":seed},
      "projection":{"home_margin_mean":mu,"home_margin_sd":sigma,"home_win_p_sim":float(np.mean(margins>0)),"away_win_p_sim":float(np.mean(margins<0)),"margin_quantiles":dict(zip(["p10","p25","p50","p75","p90"],map(float,q)))},
      "quality_adjustments":adjustments,"market_features_used":False,
      "governance":{"action_authority":False,"action_status":"SHADOW_ONLY"}
    }
    if home_spread is not None:
        threshold=-float(home_spread)
        out["market_evaluation"]={"home_spread":float(home_spread),"home_cover_p_sim":float(np.mean(margins>threshold)),"away_cover_p_sim":float(np.mean(margins<threshold)),"push_p_sim":0.0,"note":"market line evaluated after forecast draws; not a model input"}
    out["reproduction"]={"command":f"python models/cfb/monte_carlo_v1.py --event-id {snapshot['event_id']} --simulations {n_sims} --schedule <same-snapshot> --model-state <same-state> --elo-state <same-state>"}
    out["output_hash"]=sha_obj({k:v for k,v in out.items() if k not in ("generated_at_utc","output_hash")})
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--event-id",required=True); ap.add_argument("--schedule",required=True); ap.add_argument("--model-state",required=True); ap.add_argument("--elo-state",required=True); ap.add_argument("--simulations",type=int,default=100000); ap.add_argument("--home-spread",type=float); ap.add_argument("--output",required=True); a=ap.parse_args()
    state=json.load(open(a.model_state)); elo=json.load(open(a.elo_state)); row=load_row(a.schedule,a.event_id); snap=build_snapshot(row,elo); out=run(snap,state,a.simulations,a.home_spread)
    Path(a.output).parent.mkdir(parents=True,exist_ok=True); Path(a.output).write_text(json.dumps(out,indent=2,sort_keys=True)+"\n"); print(json.dumps({"status":"PASS","event_id":a.event_id,"seed":out["simulation"]["random_seed"],"output_hash":out["output_hash"],"home_win_p_sim":out["projection"]["home_win_p_sim"]}))
if __name__=="__main__": main()
