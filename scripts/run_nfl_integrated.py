#!/usr/bin/env python3
"""One command: canonical adapter, all model arms, binary and score simulations."""
import argparse,datetime as dt,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pipelines.cards.adapters import nfl
from models.nfl.contextual.runtime import run,persist_run

def main():
    p=argparse.ArgumentParser();p.add_argument('--date',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--simulations',type=int,default=100000);p.add_argument('--model-id');p.add_argument('--mode',default='research_pregame');a=p.parse_args()
    cutoff=dt.datetime.now(dt.timezone.utc).isoformat();events=nfl.load_schedule(a.date,cutoff);context=nfl.build_context(events,cutoff)
    for e in events:
        packet=context['package']['event_inputs'][e['event_id']]
        result,win,scores=run(context['model'],context['recovered'],packet['base'],packet['context'],e,cutoff,a.simulations,model_id=json.loads((nfl.DATA/'runtime.json').read_text())['default_research_model'] if a.model_id is None else a.model_id,mode=a.mode)
        persist_run(a.output/e['event_id'],result,win,scores,context['model']['design'])
        print(json.dumps({'event':e['event_id'],'prediction':result['prediction'],'binary':result['winner_simulation'],'scores':result['score_simulation']},indent=2))
if __name__=='__main__':main()
