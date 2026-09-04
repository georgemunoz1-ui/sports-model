#!/usr/bin/env python3
"""Reproducible MLB V13.1-style diagnostic Monte Carlo engine.

Consumes a frozen JSON input snapshot. No sportsbook price is an input. Missing
starter fields fall back to registered league priors and are recorded explicitly.
"""
from __future__ import annotations
import argparse, hashlib, json, math, subprocess
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
ENGINE_ID="mlb.v13_1.gamma_poisson_monte_carlo.v1"; ENGINE_VERSION="1.0.0"; MIN_SIMS=50_000
LG_RPG=4.45; LG_ERA=4.20; LG_K=22.0; LG_BB=8.5; LG_BIP=1-(LG_K+LG_BB)/100

def canonical(x): return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def sha_obj(x): return "sha256:"+hashlib.sha256(canonical(x)).hexdigest()
def seed_for(e,ih,ch): return int.from_bytes(hashlib.sha256(f"{e}|{ih}|{ch}|{ENGINE_VERSION}".encode()).digest()[:4],"big")
def git_commit():
 try:return subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
 except:return "UNKNOWN"
def val(x,d):
 try:
  y=float(x); return y if math.isfinite(y) else d
 except:return d
def shrunk(e,g):
 w=g/(g+8.0); return w*e+(1-w)*LG_ERA
def starter_ra9(sp):
 e=val(sp.get("era"),LG_ERA); g=val(sp.get("gs"),0); k=val(sp.get("k"),LG_K); bb=val(sp.get("bb"),LG_BB)
 return max(2.2,shrunk(e,g)-((k-bb)-13.5)*0.03)
def bipf(sp): return max(.45,1-(val(sp.get("k"),LG_K)+val(sp.get("bb"),LG_BB))/100)
def normalize_sp(sp,side,adj):
 sp=dict(sp or {}); missing=[]
 for k,d in (("era",LG_ERA),("gs",0),("k",LG_K),("bb",LG_BB)):
  if sp.get(k) is None: sp[k]=d; missing.append(k)
 if missing: adj.append(f"{side}_STARTER_PRIOR_FALLBACK:"+",".join(missing))
 return sp

def run(snapshot,config,n,runline=None,total_line=None):
 if n<MIN_SIMS: raise SystemExit(f"SIMULATION_COUNT_BELOW_MINIMUM:{MIN_SIMS}")
 adj=[]; asp=normalize_sp(snapshot.get("away_sp"),"AWAY",adj); hsp=normalize_sp(snapshot.get("home_sp"),"HOME",adj)
 rf_a=val(snapshot.get("away_rf_pg"),LG_RPG); ra_a=val(snapshot.get("away_ra_pg"),LG_RPG); rf_h=val(snapshot.get("home_rf_pg"),LG_RPG); ra_h=val(snapshot.get("home_ra_pg"),LG_RPG); pf=val(snapshot.get("park_factor"),1.0)
 oa=rf_a/LG_RPG; oh=rf_h/LG_RPG; pena=.55*ra_a+.45*LG_RPG; penh=.55*ra_h+.45*LG_RPG
 rah=starter_ra9(hsp); raa=starter_ra9(asp); pfa=1+(pf-1)*(bipf(hsp)/LG_BIP); pfh=1+(pf-1)*(bipf(asp)/LG_BIP)
 ih=sha_obj(snapshot); ch=sha_obj(config); seed=seed_for(snapshot["event_id"],ih,ch); rng=np.random.default_rng(seed)
 ip_a=np.clip(rng.normal(5.4,1.3,n),2,8); ip_h=np.clip(rng.normal(5.4,1.3,n),2,8)
 mu_a=(rah/9*ip_a+penh/9*(9-ip_a))*oa*pfa; mu_h=(raa/9*ip_h+pena/9*(9-ip_h))*oh*pfh*1.005
 shape_a=np.clip(1.8+(val(hsp.get("k"),LG_K)-LG_K)*.16,1.2,6); shape_h=np.clip(1.8+(val(asp.get("k"),LG_K)-LG_K)*.16,1.2,6)
 away=rng.poisson(rng.gamma(shape_a,np.maximum(mu_a,.3)/shape_a)); home=rng.poisson(rng.gamma(shape_h,np.maximum(mu_h,.3)/shape_h))
 ties=home==away
 # Registered diagnostic extra-inning resolution: fair Bernoulli with a small home-context adjustment inherited from V13.1.
 home_win=(home>away) | (ties & (rng.random(n)<(0.5+0.04*np.sign(pena-penh))))
 margin=home-away; totals=home+away
 q=lambda x: dict(zip(["p10","p25","p50","p75","p90"],map(float,np.quantile(x,[.1,.25,.5,.75,.9]))))
 out={"artifact_type":"mlb_monte_carlo_forecast_bundle_v1","event_id":snapshot["event_id"],"forecast_mode":"DIAGNOSTIC_SHADOW","forecast_tier":"BASELINE_DIAGNOSTIC" if adj else "PRIMARY_SHADOW","forecast_quality":"LOW" if adj else "MEDIUM","generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"simulation_engine":ENGINE_ID,"simulation_engine_version":ENGINE_VERSION,"distribution_specification":{"starter_innings":"Truncated Normal(5.4,1.3;2,8)","latent_run_rate":"Gamma(shape, mean/shape)","team_runs":"Poisson(latent_run_rate)","mixture":"Gamma-Poisson / Negative-Binomial-equivalent"},"simulation_count":int(n),"random_seed":seed,"input_snapshot_hash":ih,"model_state_config_hash":ch,"runtime_commit":git_commit(),"projection":{"home_win_p_sim":float(np.mean(home_win)),"away_win_p_sim":float(1-np.mean(home_win)),"home_runs_mean":float(np.mean(home)),"away_runs_mean":float(np.mean(away)),"total_mean":float(np.mean(totals)),"home_margin_mean":float(np.mean(margin)),"home_runs_quantiles":q(home),"away_runs_quantiles":q(away),"total_quantiles":q(totals),"margin_quantiles":q(margin)},"quality_adjustments":adj,"market_features_used":False,"governance":{"action_authority":False,"action_status":"SHADOW_ONLY"}}
 if runline is not None:
  thr=-float(runline); out["runline_evaluation"]={"home_runline":float(runline),"home_cover_p_sim":float(np.mean(margin>thr)),"away_cover_p_sim":float(np.mean(margin<thr)),"push_p_sim":float(np.mean(margin==thr))}
 if total_line is not None:
  t=float(total_line); out["total_evaluation"]={"total_line":t,"over_p_sim":float(np.mean(totals>t)),"under_p_sim":float(np.mean(totals<t)),"push_p_sim":float(np.mean(totals==t))}
 out["output_hash"]=sha_obj({k:v for k,v in out.items() if k not in ("generated_at_utc","output_hash")}); out["reproduction_command"]="python models/mlb/monte_carlo_v1.py --snapshot <same.json> --config <same.json> --output <out.json> --simulations %d"%n
 return out

def main():
 ap=argparse.ArgumentParser();ap.add_argument("--snapshot",required=True);ap.add_argument("--config",required=True);ap.add_argument("--output",required=True);ap.add_argument("--simulations",type=int,default=100000);ap.add_argument("--home-runline",type=float);ap.add_argument("--total-line",type=float);a=ap.parse_args();snap=json.load(open(a.snapshot));cfg=json.load(open(a.config));out=run(snap,cfg,a.simulations,a.home_runline,a.total_line);Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(out,indent=2,sort_keys=True)+"\n");print(json.dumps({"status":"PASS","event_id":out["event_id"],"seed":out["random_seed"],"output_hash":out["output_hash"],"home_win_p_sim":out["projection"]["home_win_p_sim"]}))
if __name__=="__main__":main()
