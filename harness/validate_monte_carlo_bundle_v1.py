#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
REQUIRED=("event_id","generated_at_utc","input_snapshot_hash","model_state_config_hash","output_hash")
def validate(x):
 v=[]
 for k in REQUIRED:
  if not x.get(k):v.append("MISSING_"+k.upper())
 sim=x.get("simulation",x)
 for k in ("simulation_engine","simulation_engine_version","simulation_count","random_seed"):
  if sim.get(k) is None:v.append("MISSING_"+k.upper())
 if int(sim.get("simulation_count",0))<50000:v.append("SIMULATION_COUNT_BELOW_MINIMUM")
 if not str(x.get("input_snapshot_hash","")).startswith("sha256:"):v.append("BAD_INPUT_SNAPSHOT_HASH")
 if not str(x.get("model_state_config_hash","")).startswith("sha256:"):v.append("BAD_MODEL_STATE_CONFIG_HASH")
 if not str(x.get("output_hash","")).startswith("sha256:"):v.append("BAD_OUTPUT_HASH")
 if x.get("market_features_used") is not False:v.append("MARKET_INPUT_LEAKAGE_OR_UNDECLARED")
 g=x.get("governance",{})
 if g.get("action_authority") is not False:v.append("DIAGNOSTIC_ACTION_AUTHORITY_NOT_OFF")
 p=x.get("projection",{})
 for k in ("home_win_p_sim","away_win_p_sim"):
  if k in p and not (0<=float(p[k])<=1):v.append("INVALID_"+k.upper())
 return v
def main():
 ap=argparse.ArgumentParser();ap.add_argument("path");a=ap.parse_args();x=json.load(open(a.path));v=validate(x)
 if v:raise SystemExit("MONTE_CARLO_BUNDLE_INVALID:"+",".join(v))
 print("monte carlo bundle: PASS")
if __name__=="__main__":main()
