#!/usr/bin/env python3
"""Machine-readable latest-capability ledger.

A schema declaration never counts as execution, and execution never counts as validation.
This audit is intentionally conservative: unknown evidence is FAIL/PARTIAL plus an obligation.
"""
import datetime, hashlib, json, pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
STD=json.loads((ROOT/"governance/ALL_MODEL_CAPABILITY_STANDARD.json").read_text())
DEFAULTS=json.loads((ROOT/"data/model_selection/defaults_v1.json").read_text())
SPORTS=STD["sports"]
KNOWN={
 "nfl":{"context":["data/nfl/contextual_v1/runtime.json"],"dist":["data/nfl/modes_v1/runtime.json"],"priority":"Certified state/personnel path plus coherent joint margin/total distribution"},
 "cfb":{"context":["data/cfb/model/CFB_V2_PREREG.json"],"dist":["data/cfb/model/cfb_margin_sd_schedule.json"],"priority":"Contextual margin/total build with chronological OOF fitting"},
 "mlb":{"context":["data/mlb/ml_asof/V13_FREEZE.json"],"dist":[],"priority":"Joint run distribution and lineup/bullpen availability path"},
 "wnba":{"context":["data/wnba/model/2026-08-12_v1_walkforward.json"],"dist":["data/wnba/model/wnba_margin_sd_measurement.json","data/wnba/model/wnba_total_sd_measurement.json"],"priority":"Separate postseason/current-availability challenger"},
 "nhl":{"context":[],"dist":[],"priority":"Goalie/workload contextual increment to joint-score challenger"},
 "mls":{"context":[],"dist":[],"priority":"Correlated goal model plus lineup/availability source path"},
 "nba":{"context":[],"dist":[],"priority":"Establish reproducible baseline before expanding feature set"}
}
def present(paths): return bool(paths) and all((ROOT/p).exists() for p in paths)
def tri(declared=False, executed=False, validated=False):
 return {"DECLARED":bool(declared),"EXECUTED":bool(executed),"VALIDATED":bool(validated),"status":"PASS" if validated else ("PARTIAL" if executed or declared else "FAIL")}
def obligation(s, code, target, evidence):
 return {"id":f"{s.upper()}-{code}","target":target,"required_evidence":evidence,"status":"OPEN"}
def main():
 out={"schema":"sports.latest_capability_ledger.v2","evaluated_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"standard_sha256":hashlib.sha256((ROOT/"governance/ALL_MODEL_CAPABILITY_STANDARD.json").read_bytes()).hexdigest(),"sports":{}}
 for s in SPORTS:
  k=KNOWN[s]; prof=DEFAULTS.get("profiles",{}).get(f"{s}:winner",{}); selected=prof.get("default_model_id")
  control=bool(selected); ctx=present(k["context"]); dist=present(k["dist"]); obs=[]
  if not control: obs.append(obligation(s,"BASELINE-001","winner_probability","reproducible selected baseline plus chronological target evaluation"))
  if not ctx: obs.append(obligation(s,"CTX-001","current_context","source-bound PIT starter/personnel/rest/travel/weather acquisition and replay"))
  if not dist: obs.append(obligation(s,"DIST-001","joint_distribution","replayable coherent score/margin/total distribution with settlement semantics"))
  winner={"analytic":tri(control,control,control),"calibrated":tri(control,control,control),"simulated":tri(control,control,False),"current_context":tri(True,ctx,False),"chronological_oof_comparison":tri(control,control,control),"prospective_shadow":tri(True,False,False)}
  margin={"point_estimate":tri(control,control,control),"predictive_distribution":tri(True,dist,False),"cover_probability":tri(True,False,False),"push_probability":tri(True,False,False)}
  total={"point_estimate":tri(True,False,False),"predictive_distribution":tri(True,dist,False),"over_under_probability":tri(True,False,False),"push_probability":tri(True,False,False)}
  complete=all(x["VALIDATED"] for grp in (winner,margin,total) for x in grp.values())
  out["sports"][s]={
   "incumbent":{"model_id":selected,"selection_status":prof.get("selection_status"),"status":"CONTROL_VALID" if control else "RESEARCH_ONLY"},
   "targets":{"winner_probability":winner,"margin":margin,"total":total},
   "blocking_obligations":obs,
   "first_upgrade_target":k["priority"],
   "overall":{"latest_capability_status":"GREEN" if complete else "RED","CONTROL_VALID":control,"BEST_VALIDATED":control,"CAPABILITY_COMPLETE":complete,"RESEARCH_ONLY":not control,"SHADOW_VALIDATED":False,"PROMOTION_ELIGIBLE":False,"DEFAULT":control,"QUARANTINED":False,"incumbent_is_capability_ceiling":False,"action_authority":"OFF"}
  }
 out["release"]={"LATEST_CAPABILITY_AUDIT":"IMPLEMENTED","INITIAL_RESULTS":"RED_EXPECTED","MODEL_DEFAULTS":"UNCHANGED","ACTION_AUTHORITY":"OFF","MARKET_OVERLAY":"BENCHMARK_ONLY","NEW_CHALLENGERS":"RESEARCH_SHADOW_ONLY"}
 out["all_models_capability_complete"]=all(v["overall"]["CAPABILITY_COMPLETE"] for v in out["sports"].values())
 p=ROOT/"evidence/latest_capability_audit.json";p.parent.mkdir(exist_ok=True);p.write_text(json.dumps(out,indent=2)+"\n")
 print(json.dumps(out,indent=2)); return 0 if out["all_models_capability_complete"] else 2
if __name__=="__main__": raise SystemExit(main())
