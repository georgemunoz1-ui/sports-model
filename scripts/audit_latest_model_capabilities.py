#!/usr/bin/env python3
"""Audit whether each sport is actually running its latest validated capability set."""
import json, pathlib, hashlib, datetime
ROOT=pathlib.Path(__file__).resolve().parents[1]
STD=json.loads((ROOT/"governance/ALL_MODEL_CAPABILITY_STANDARD.json").read_text())
DEFAULTS=json.loads((ROOT/"data/model_selection/defaults_v1.json").read_text())
SPORTS=STD["sports"]
# Concrete repository evidence; absence is a development obligation, not silently "unsupported".
EVIDENCE={
 "nfl":{"context":["data/nfl/contextual_v1/runtime.json"],"distribution":["data/nfl/modes_v1/runtime.json"],"notes":"QB/context integrated; verify current personnel/weather and calibrated margin distribution on each card."},
 "cfb":{"context":["data/cfb/model/CFB_V2_PREREG.json"],"distribution":["data/cfb/model/cfb_margin_sd_schedule.json"],"notes":"Incumbent lacks fitted current QB/personnel/weather; contextual historical PIT acquisition remains required."},
 "mlb":{"context":["data/mlb/ml_asof/V13_FREEZE.json"],"distribution":[],"notes":"Starter-bound V13 exists; joint run-line/total settlement distribution must be independently validated."},
 "nba":{"context":[],"distribution":[],"notes":"No verified selected default on main; build/evaluate current contextual and joint-score capability."},
 "wnba":{"context":["data/wnba/model/2026-08-12_v1_walkforward.json"],"distribution":["data/wnba/model/wnba_margin_sd_measurement.json","data/wnba/model/wnba_total_sd_measurement.json"],"notes":"Selected regular-season model exists; postseason/current availability and joint distributions remain obligations."},
 "nhl":{"context":[],"distribution":[],"notes":"Initial research exists outside automatic default; current goalie/personnel plus joint-score distribution required."},
 "mls":{"context":[],"distribution":[],"notes":"Initial Poisson research exists outside automatic default; current XI/personnel/weather and calibrated dependence required."}
}
def exists(p): return (ROOT/p).exists()
def main():
 out={"schema":"sports.latest_capability_audit.v1","generated_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"standard_sha256":hashlib.sha256((ROOT/"governance/ALL_MODEL_CAPABILITY_STANDARD.json").read_bytes()).hexdigest(),"sports":{}}
 for s in SPORTS:
  prof=DEFAULTS.get("profiles",{}).get(f"{s}:winner",{})
  ev=EVIDENCE[s]
  ctx={p:exists(p) for p in ev["context"]}; dist={p:exists(p) for p in ev["distribution"]}
  selected=prof.get("default_model_id")
  obligations=[]
  if not selected: obligations.append("NO_VERIFIED_SELECTED_WINNER_DEFAULT")
  if not ctx or not all(ctx.values()): obligations.append("CONTEXT_CAPABILITY_INCOMPLETE")
  if not dist or not all(dist.values()): obligations.append("DISTRIBUTIONAL_COVER_TOTAL_CAPABILITY_INCOMPLETE")
  out["sports"][s]={"selected_winner_model":selected,"selection_status":prof.get("selection_status"),"context_evidence":ctx,"distribution_evidence":dist,"latest_capability_validated":not obligations,"development_obligations":obligations,"notes":ev["notes"]}
 out["all_models_latest_capability_validated"]=all(v["latest_capability_validated"] for v in out["sports"].values())
 p=ROOT/"evidence/latest_capability_audit.json"; p.parent.mkdir(exist_ok=True); p.write_text(json.dumps(out,indent=2)+"\n")
 print(json.dumps(out,indent=2))
 return 0 if out["all_models_latest_capability_validated"] else 2
if __name__=="__main__": raise SystemExit(main())
