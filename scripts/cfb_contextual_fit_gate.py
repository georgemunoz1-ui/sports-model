#!/usr/bin/env python3
"""CFB contextual-v3 fit gate: causal QB/personnel/weather only; no market features.

This runner intentionally refuses a fitted forecast until historical pregame artifacts exist
for every enabled contextual block. It prevents current-only injury/weather knowledge from
being assigned discretionary coefficients.
"""
import json, pathlib, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
PREREG=ROOT/"data/cfb/model/CFB_V2_PREREG.json"
OUT=ROOT/"data/cfb/contextual_v3"
REQUIRED={
 "qb": OUT/"historical_pregame_qb.parquet",
 "personnel": OUT/"historical_pregame_availability.parquet",
 "weather": OUT/"historical_pregame_weather.parquet",
}
def main():
    spec=json.loads(PREREG.read_text())
    missing=[k for k,p in REQUIRED.items() if not p.exists()]
    report={
      "schema":"cfb.contextual_fit_gate.v1",
      "base_model":spec["model_id"],
      "target_date":"2026-10-02",
      "feature_blocks":["qb","personnel","weather"],
      "market_features":"FORBIDDEN",
      "fit_method":"expanding season-week OOF; coefficients/estimators trained only on prior blocks",
      "targets":["home_win","home_margin"],
      "required_historical_pregame_artifacts":{k:str(p.relative_to(ROOT)) for k,p in REQUIRED.items()},
      "missing_blocks":missing,
      "forecast_allowed":not missing,
      "current_only_context_may_be_fitted":False,
      "reason":None if not missing else "Historical PIT contextual training artifacts are absent; fitting current-only context would invent coefficients and violate the registered causal personnel rule."
    }
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"fit_gate_2026-10-02.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))
    if missing: return 2
    # Deliberately require a separate reviewed fitter once source-bound PIT artifacts exist.
    return 3
if __name__=="__main__": sys.exit(main())
