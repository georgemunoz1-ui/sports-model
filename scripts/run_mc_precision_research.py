#!/usr/bin/env python3
"""Explicit opt-in MC precision research; never replaces a registered forecast."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.discrete_mc_v1 import select_distribution, run, write_run
from research.mc_precision_v1 import PrecisionPlan


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--distribution', required=True, help='Canonical discrete law or shared-card distribution_report.json')
    ap.add_argument('--comparison-distribution', help='Optional distinct same-event/cutoff/product/settlement law')
    ap.add_argument('--event-id');ap.add_argument('--model-id');ap.add_argument('--comparison-model-id')
    ap.add_argument('--product',choices=['margin','total'])
    ap.add_argument('--line',required=True,type=float);ap.add_argument('--side',required=True,choices=['HOME','AWAY','OVER','UNDER'])
    ap.add_argument('--experiment-id',required=True);ap.add_argument('--seed',required=True,type=int)
    ap.add_argument('--replicate',type=int,default=0)
    ap.add_argument('--checkpoints',default='100000',help='Predeclared comma-separated looks; default fixed100k, minimum100k, maximum1m')
    ap.add_argument('--alpha',type=float,default=.05);ap.add_argument('--tolerance',type=float,default=.005)
    ap.add_argument('--output',required=True,help='A new research-only output directory')
    args=ap.parse_args(argv)
    try:
        plan=PrecisionPlan(tuple(int(n) for n in args.checkpoints.split(',')),args.alpha,args.tolerance)
        source_paths=[args.distribution]+([args.comparison_distribution] if args.comparison_distribution else [])
        selected=[];source_receipts=[]
        for i,path in enumerate(source_paths):
            raw=Path(path).read_bytes()
            selected.append(select_distribution(json.loads(raw),event_id=args.event_id,
                model_id=args.model_id if i==0 else args.comparison_model_id,product=args.product))
            source_receipts.append({'file_name':Path(path).name,'file_sha256':hashlib.sha256(raw).hexdigest()})
        paths,report=run(selected,line=args.line,side=args.side,experiment_id=args.experiment_id,
                         root_seed=args.seed,replicate=args.replicate,plan=plan)
        report['source_files']=source_receipts
        result=write_run(args.output,paths,report)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        ap.exit(2,'MC_RESEARCH_REFUSED: '+str(exc)+'\n')
    print(json.dumps({'status':result['looks'][-1]['status'],'actual_draws':result['actual_draws'],
                      'report':str(Path(args.output)/'report.json'),'action_authority':False}))
    return 0

if __name__=='__main__':raise SystemExit(main())
