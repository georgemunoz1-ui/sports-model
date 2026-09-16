"""WNBA pace/efficiency Monte Carlo diagnostic engine with explicit availability dose."""
from __future__ import annotations
import hashlib,json,math
import numpy as np
ENGINE_ID="wnba.efficiency_monte_carlo.v1_1.defense_direction_fix.shadow"; ENGINE_VERSION="1.1.0"; MIN_SIMS=50000

def _c(x):return json.dumps(x,sort_keys=True,separators=(",",":"),allow_nan=False)
def _h(x):return "sha256:"+hashlib.sha256(_c(x).encode()).hexdigest()
def _seed(e,i,s):return int.from_bytes(hashlib.sha256(f"{e}|{i}|{s}|{ENGINE_VERSION}".encode()).digest()[:4],"big")
def run(snapshot,config,n_sims=100000):
    if n_sims<MIN_SIMS:raise ValueError("SIMULATION_COUNT_BELOW_MINIMUM")
    req=("event_id","home_team","away_team","home_ortg","home_drtg","away_ortg","away_drtg","home_pace","away_pace")
    for k in req:
        if snapshot.get(k) is None:raise ValueError(f"INPUTS_INCOMPLETE:{k}")
    ih=_h(snapshot);sh=_h(config);seed=_seed(snapshot["event_id"],ih,sh);rng=np.random.default_rng(seed)
    lg=float(config.get("league_ortg",103.0));hca=float(config.get("home_court_points_per100",2.0));pace=2/(1/float(snapshot["home_pace"])+1/float(snapshot["away_pace"]))
    he=lg+(float(snapshot["home_ortg"])-lg)+(float(snapshot["away_drtg"])-lg)+hca+float(snapshot.get("home_availability_per100",0))
    ae=lg+(float(snapshot["away_ortg"])-lg)+(float(snapshot["home_drtg"])-lg)+float(snapshot.get("away_availability_per100",0))
    poss=np.clip(rng.normal(pace,float(config.get("pace_sd",3.0)),n_sims),70,105); shared=rng.normal(0,float(config.get("shared_eff_sd",4.5)),n_sims)
    hp=np.maximum(0,np.rint(poss*(he+shared+rng.normal(0,float(config.get("team_eff_sd",10.5)),n_sims))/100));ap=np.maximum(0,np.rint(poss*(ae+shared+rng.normal(0,float(config.get("team_eff_sd",10.5)),n_sims))/100))
    tie=hp==ap; hp[tie]+=rng.binomial(1,.5,tie.sum());ap[tie]+=(hp[tie]==ap[tie]);m=hp-ap;t=hp+ap
    mu=pace*(he-ae)/100;model_p=1/(1+math.exp(-mu/float(config.get("margin_logistic_scale",9.0))))
    return {"model_id":ENGINE_ID,"model_version":ENGINE_VERSION,"model_p":model_p,"sim_p":float(np.mean(m>0)),"projected_margin":mu,"projected_total":float(np.mean(t)),"home_score_mean":float(hp.mean()),"away_score_mean":float(ap.mean()),"input_snapshot_hash":ih,"model_state_config_hash":sh,"analytic_margin":mu,"artifact_role":"MODEL_CORRECTION_DIAGNOSTIC","action_authority":False,"simulation":{"engine":ENGINE_ID,"version":ENGINE_VERSION,"rng":"numpy.random.Generator(PCG64)","count":n_sims,"seed":seed,"margin_quantiles":{str(q):float(np.quantile(m,q)) for q in (.1,.25,.5,.75,.9)},"total_quantiles":{str(q):float(np.quantile(t,q)) for q in (.1,.25,.5,.75,.9)}}}

