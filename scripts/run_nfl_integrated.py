#!/usr/bin/env python3
"""One command: canonical adapter, all model arms, binary and score simulations."""
import argparse,datetime as dt,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from pipelines.cards.adapters import nfl
from models.nfl.contextual.runtime import run,persist_run

def main():
    p=argparse.ArgumentParser();p.add_argument('--date',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--simulations',type=int,default=100000);p.add_argument('--model-id');p.add_argument('--mode',default='research_pregame');p.add_argument('--market-packet',type=Path);p.add_argument('--live-packet',type=Path);p.add_argument('--event-id');a=p.parse_args()
    fitted=nfl.mode_artifact(a.mode) if a.mode!='research_pregame' else None
    market=json.loads(a.market_packet.read_text()) if a.market_packet else None
    live=json.loads(a.live_packet.read_text()) if a.live_packet else None
    default_id=fitted['model_id'] if fitted is not None else json.loads((nfl.DATA/'runtime.json').read_text())['default_research_model']
    cutoff=dt.datetime.now(dt.timezone.utc).isoformat();events=nfl.load_schedule(a.date,cutoff)
    if a.event_id:
        events=[e for e in events if e['event_id']==a.event_id]
        if not events:raise ValueError('EVENT_NOT_IN_CAPTURED_SCHEDULE')
    context=nfl.build_context(events,cutoff,mode=a.mode)
    for e in events:
        packet={'base':None,'context':None} if a.mode=='live' else context['package']['event_inputs'][e['event_id']]
        market_for_event=market.get('event_packets',{}).get(e['event_id']) if market and 'event_packets' in market else market
        live_for_event=live.get('event_packets',{}).get(e['event_id']) if live and 'event_packets' in live else live
        result,win,scores=run(context['model'],context['recovered'],packet['base'],packet['context'],e,cutoff,a.simulations,model_id=default_id if a.model_id is None else a.model_id,mode=a.mode,mode_artifact=fitted,market=market_for_event,live_state=live_for_event)
        persist_run(a.output/e['event_id'],result,win,scores,json.loads((nfl.ROOT/'data/nfl/modes_v1/design.json').read_text()) if fitted is not None else context['model']['design'])
        print(json.dumps({'event':e['event_id'],'prediction':result['prediction'],'binary':result['winner_simulation'],'scores':result['score_simulation']},indent=2))
if __name__=='__main__':main()
