"""NBA possession/efficiency Monte Carlo diagnostic engine.
Market-free. Inputs must be frozen pregame team ratings; optional player availability
adjustments are supplied as net points/100 possessions from an upstream PIT snapshot.
"""
from __future__ import annotations
import hashlib, json, math
import numpy as np
ENGINE_ID="nba.efficiency_monte_carlo.v1"; ENGINE_VERSION="1.0.0"; MIN_SIMS=50000

def _canon(x): return json.dumps(x,sort_keys=True,separators=(",",":"),allow_nan=False)
def _hash(x): return "sha256:"+hashlib.sha256(_canon(x).encode()).hexdigest()
def _seed(event_id,input_hash,state_hash): return int.from_bytes(hashlib.sha256(f"{event_id}|{input_hash}|{state_hash}|{ENGINE_VERSION}".encode()).digest()[:4],"big")
def _logistic(x): return 1/(1+math.exp(-x))
def run(snapshot, config, n_sims=100000):
    if n_sims<MIN_SIMS: raise ValueError("SIMULATION_COUNT_BELOW_MINIMUM")
    for k in ("event_id","home_team","away_team","home_adj_ortg","home_adj_drtg","away_adj_ortg","away_adj_drtg","home_pace","away_pace"):
        if snapshot.get(k) is None: raise ValueError(f"INPUTS_INCOMPLETE:{k}")
    ih=_hash(snapshot); sh=_hash(config); seed=_seed(snapshot["event_id"],ih,sh); rng=np.random.default_rng(seed)
    lg=float(config.get("league_ortg",114.5)); hca=float(config.get("home_court_points_per100",2.2))
    pace=2/(1/max(float(snapshot["home_pace"]),1)+1/max(float(snapshot["away_pace"]),1))
    pace=max(85,min(110,pace))
    ha=float(snapshot.get("home_availability_epm_per100",0)); aa=float(snapshot.get("away_availability_epm_per100",0))
    home_eff=lg+(float(snapshot["home_adj_ortg"])-lg)+(lg-float(snapshot["away_adj_drtg"]))+hca+ha
    away_eff=lg+(float(snapshot["away_adj_ortg"])-lg)+(lg-float(snapshot["home_adj_drtg"]))+aa
    poss=np.clip(rng.normal(pace,float(config.get("pace_sd",3.2)),n_sims),80,120)
    shared=rng.normal(0,float(config.get("shared_eff_sd",4.0)),n_sims)
    he=home_eff+shared+rng.normal(0,float(config.get("team_eff_sd",9.5)),n_sims)
    ae=away_eff+shared+rng.normal(0,float(config.get("team_eff_sd",9.5)),n_sims)
    hp=np.maximum(0,np.rint(poss*he/100)); ap=np.maximum(0,np.rint(poss*ae/100)); tie=hp==ap
    hp[tie]+=rng.binomial(1,.5,tie.sum()); ap[tie]+=(hp[tie]==ap[tie])
    margin=hp-ap; total=hp+ap; sim_p=float(np.mean(margin>0)); mu=float(np.mean(margin)); tot=float(np.mean(total))
    # independent point estimate from expected efficiencies, distinct from simulation fraction
    model_p=_logistic((pace*(home_eff-away_eff)/100)/float(config.get("margin_logistic_scale",10.5)))
    return {"model_id":ENGINE_ID,"model_version":ENGINE_VERSION,"model_p":model_p,"sim_p":sim_p,"projected_margin":mu,"projected_total":tot,"home_score_mean":float(hp.mean()),"away_score_mean":float(ap.mean()),"input_snapshot_hash":ih,"model_state_config_hash":sh,"simulation":{"engine":ENGINE_ID,"version":ENGINE_VERSION,"rng":"numpy.random.Generator(PCG64)","count":n_sims,"seed":seed,"margin_quantiles":{str(q):float(np.quantile(margin,q)) for q in (.1,.25,.5,.75,.9)},"total_quantiles":{str(q):float(np.quantile(total,q)) for q in (.1,.25,.5,.75,.9)}}}
