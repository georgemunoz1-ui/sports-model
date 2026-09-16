from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.news_information.benchmark import score_event_extraction, score_ensemble
from research.news_information.contracts import digest, write_immutable_json


def load_jsonl(path: Path):
    rows=[]
    for n,line in enumerate(path.read_text(encoding="utf-8").splitlines(),1):
        if not line.strip(): continue
        value=json.loads(line)
        if not isinstance(value,dict): raise ValueError(f"JSONL line {n} must be object")
        rows.append(value)
    return rows


def evaluate(gold_path: Path, prediction_paths: list[Path]):
    gold=load_jsonl(gold_path)
    components={}
    all_ensemble=[]
    for path in prediction_paths:
        pred=load_jsonl(path)
        name=path.stem
        components[name]=score_event_extraction(gold,pred)
        all_ensemble.extend(x for x in pred if x.get("cross_model_state"))
    core={
        "schema_version":"sports_information_benchmark_report.v1",
        "gold_sha256":digest(gold),
        "prediction_sets":sorted(components),
        "component_reports":components,
        "ensemble_state_report":score_ensemble(all_ensemble),
        "decision_authority":False,
        "forecast_adjustment_authority":False,
        "market_input":False,
        "action_authority":"OFF",
    }
    return {**core,"report_sha256":digest(core)}


def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--gold",type=Path,required=True); p.add_argument("--pred",type=Path,action="append",required=True); p.add_argument("--output-dir",type=Path,required=True)
    a=p.parse_args(argv); report=evaluate(a.gold,a.pred); dest=a.output_dir/report["gold_sha256"]/report["report_sha256"]/"benchmark_report.json"; write_immutable_json(dest,report)
    print(json.dumps({"status":"PASS","report_sha256":report["report_sha256"],"path":str(dest)},sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
