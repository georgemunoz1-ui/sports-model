#!/usr/bin/env python3
"""Audit/fit an explicitly supplied research dataset; never imports card runners."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.nba_forecast_combination import audit, digest, event_key, fit, predict
from pipelines.cards.missingness import seal_audit, verify_audit


def bound(row):
    return dict(league="nba", event_id=row["event_id"], model_id=row["requested_model"],
                products=["home_margin_points"],forecast={k:v for k,v in row.items() if k!="missingness_audit"})


def predictions(rows,root,state,protocol):
    rows=[r if isinstance(r,dict) else {} for r in rows]
    ids=Counter(r.get("event_id") for r in rows if isinstance(r.get("event_id"),str))
    keys=Counter(digest(event_key(r)) for r in rows)
    out=[]
    stage=state["stage"]
    required=["B0","B1"]+(["databallr"] if stage=="C2" else [])
    for ix,r in enumerate(rows):
        eid=r.get("event_id")
        details={"status":"RESEARCH_HOLD","stage":stage,"historical_support":"UNMEASURED",
                 "required_sources":required,"thresholds":"UNREVIEWED","perturbations":{}}
        try:
            if not isinstance(eid,str) or not eid.strip() or ids[eid]!=1 or keys[digest(event_key(r))]!=1:
                raise ValueError("UNRESOLVED_OR_DUPLICATE_EVENT_IDENTITY")
            current=predict(r,root,state,protocol)
            for source in required:
                subset={k:v for k,v in r["sources"].items() if k!=source}
                probe=predict({**r,"sources":subset},root,state,protocol)
                if probe["challenger_emitted"]:
                    raise ValueError("SOURCE_FAILURE_EMITTED_CHALLENGER:"+source)
                details["perturbations"][source]={"emitted_stage":probe["emitted_stage"],
                    "home_margin":probe["home_margin"],"reasons":probe["reasons"],
                    "change_from_requested_margin":(probe["home_margin"]-current["home_margin"]
                         if current["challenger_emitted"] and probe["home_margin"] is not None else None)}
            details["method"]="Withhold each required source in the native predictor. B0 fallback is a distinct model comparison."
        except (OSError,ValueError,TypeError,KeyError) as exc:
            current={"event_id":eid if isinstance(eid,str) and eid.strip() else f"UNRESOLVED_ROW_{ix}",
                     "requested_stage":stage,"emitted_stage":None,"home_margin":None,"challenger_emitted":False,
                     "probabilities":None,"action_authority":False,"reasons":[str(exc)]}
        current["requested_model"]="nba.forecast_combination."+stage
        current["requested_state_sha256"]=state.get("state_hash")
        current["protocol_sha256"]=digest(protocol)
        current["pregame_sources_sha256"]=digest(r.get("sources",{}))
        current["feature_cutoff"]=r.get("feature_cutoff")
        current["missingness_audit"]=seal_audit(**bound(current),details=details)
        out.append(current)
    n=sum(r["challenger_emitted"] for r in out)
    return {"predictions":out,"emitted_count":n,"status":"BLOCKED" if not n else "COMPLETED" if n==len(rows) else "PARTIAL"}



def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("audit", "fit", "predict"))
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--stage", choices=("C1", "C2"), default="C1")
    p.add_argument("--train-before")
    p.add_argument("--state", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    rows = json.loads(a.dataset.read_text())["rows"]
    protocol = json.loads(a.protocol.read_text())
    root = a.dataset.parent
    if a.command == "audit":
        result = audit(rows, root, a.stage, a.train_before)
    elif a.command == "fit":
        if not a.train_before:
            p.error("fit requires --train-before")
        result = fit(rows, root, protocol, a.train_before, a.stage)
    else:
        if not a.state:
            p.error("predict requires --state")
        state = json.loads(a.state.read_text())
        if state.get("stage") != a.stage:
            p.error("state stage differs from --stage")
        result = predictions(rows,root,state,protocol)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    # A rerun cannot overwrite a prior fitted state or audit.
    with a.output.open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write("\n")
    if a.command=="predict":
        stored=json.loads(a.output.read_bytes())
        if stored!=result or any(not verify_audit(r.get("missingness_audit"),**bound(r)) for r in stored["predictions"]):
            raise ValueError("NBA_COMBINATION_MISSINGNESS_READBACK")
    print(json.dumps({"output": str(a.output), "status": result.get("status", "COMPLETED"),
                      "fitted": result.get("fitted", False)}))
    return 2 if result.get("status", "").startswith("BLOCKED") or result.get("status")=="PARTIAL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
