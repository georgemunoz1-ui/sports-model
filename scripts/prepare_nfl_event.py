#!/usr/bin/env python3
"""Package explicit event, source-bound current context, and fitted model."""
import argparse,datetime as dt,json,sys,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from models.nfl.contextual.runtime import live_features
from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.recovered_inference import digest

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',type=Path,required=True);p.add_argument('--base',type=Path,required=True);p.add_argument('--context',type=Path,required=True);p.add_argument('--event',type=Path,required=True);p.add_argument('--recovered-parameters',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    model=load_artifact(a.model);raw=json.loads(a.base.read_text());base=raw[0] if isinstance(raw,list) else raw
    context=json.loads(a.context.read_text());event=json.loads(a.event.read_text());recovered=json.loads(a.recovered_parameters.read_text());stamp=dt.datetime.now(dt.timezone.utc).isoformat()
    live_features(model,recovered,base,context,event,stamp)
    package={'schema':'nfl.event_package.v1','captured_at_utc':stamp,'scope':'REQUESTED_EVENTS_NOT_AUTOMATIC_LEAGUE_COMPLETENESS','covered_dates':[event['gameday']],'events':[event],'model_path':os.path.relpath(a.model,a.output.parent),'model_digest':digest(model),'recovered_parameters_path':os.path.relpath(a.recovered_parameters,a.output.parent),'event_inputs':{event['event_id']:{'base':base,'context':context}},'source_fetches':[{'source':v['source'],'sha256':v['source_sha256'],'fetched_at_utc':v['retrieved_at_utc']} for v in context.values()]}
    with a.output.open('x') as f:json.dump(package,f,indent=2,allow_nan=False)
    print(a.output)
if __name__=='__main__':main()
