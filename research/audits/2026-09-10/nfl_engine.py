"""NFL Elo-based margin/total diagnostic Monte Carlo baseline.
This is a new SHADOW baseline, not a validated production model. Market inputs forbidden.
"""
from __future__ import annotations
import hashlib,json,math
import numpy as np
ENGINE_ID="nfl.elo_margin_monte_carlo.v1";ENGINE_VERSION="1.0.0";MIN_SIMS=50000

def _c(x):return json.dumps(x,sort_keys=True,separators=(",",":"),allow_nan=False)
def _h(x):return "sha256:"+hashlib.sha256(_c(x).encode()).hexdigest()
def _seed(e,i,s):return int.from_bytes(hashlib.sha256(f"{e}|{i}|{s}|{ENGINE_VERSION}".encode()).digest()[:4],"big")
def run(snapshot,config,n_sims=100000):
    if n_sims<MIN_SIMS:raise ValueError("SIMULATION_COUNT_BELOW_MINIMUM")
    for k in ("event_id","home_team","away_team","home_elo","away_elo"):
        if snapshot.get(k) is None:raise ValueError(f"INPUTS_INCOMPLETE:{k}")
    ih=_h(snapshot);sh=_h(config);seed=_seed(snapshot["event_id"],ih,sh);rng=np.random.default_rng(seed)
    diff=float(snapshot["home_elo"])-float(snapshot["away_elo"]); hfa=0 if snapshot.get("neutral_site") else float(config.get("home_field_points",1.8))
    mu=hfa+diff*float(config.get("points_per_elo",.036))+float(snapshot.get("home_adjustment_points",0))-float(snapshot.get("away_adjustment_points",0))
    total_mu=float(snapshot.get("total_prior",config.get("league_total_prior",44.0)))+float(snapshot.get("total_adjustment",0))
    # Correlated team scores via margin and total draws; enforce nonnegative football scores.
    margin=rng.normal(mu,float(config.get("margin_sd",13.5)),n_sims);total=rng.normal(total_mu,float(config.get("total_sd",10.5)),n_sims)
    hp=np.maximum(0,np.rint((total+margin)/2));ap=np.maximum(0,np.rint((total-margin)/2));m=hp-ap;t=hp+ap
    tie=m==0; # diagnostic OT resolver for winner probability only
    win=(m>0).astype(float);win[tie]=rng.binomial(1,.5,tie.sum());sim_p=float(win.mean())
    model_p=1/(1+math.exp(-mu/float(config.get("margin_logistic_scale",8.0))))
    return {"model_id":ENGINE_ID,"model_version":ENGINE_VERSION,"model_p":model_p,"sim_p":sim_p,"projected_margin":float(m.mean()),"projected_total":float(t.mean()),"home_score_mean":float(hp.mean()),"away_score_mean":float(ap.mean()),"input_snapshot_hash":ih,"model_state_config_hash":sh,"simulation":{"engine":ENGINE_ID,"version":ENGINE_VERSION,"rng":"numpy.random.Generator(PCG64)","count":n_sims,"seed":seed,"margin_quantiles":{str(q):float(np.quantile(m,q)) for q in (.1,.25,.5,.75,.9)},"total_quantiles":{str(q):float(np.quantile(t,q)) for q in (.1,.25,.5,.75,.9)}}}
