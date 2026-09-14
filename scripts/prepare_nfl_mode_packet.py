#!/usr/bin/env python3
"""Bind an acquired market observation or nflverse pre-play row to an event."""
import argparse,datetime as dt,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from models.nfl.modes.core import state_from_nflverse
from models.nfl.modes.runtime import market_values
from models.nfl.contextual.recovered_inference import utc

def main():
 p=argparse.ArgumentParser();p.add_argument('--kind',choices=['market','live'],required=True);p.add_argument('--raw',type=Path,required=True);p.add_argument('--event',type=Path,required=True);p.add_argument('--source',required=True);p.add_argument('--observed-at',required=True);p.add_argument('--effective-at');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 raw=a.raw.read_bytes();data=json.loads(raw);e=json.loads(a.event.read_text());now=dt.datetime.now(dt.timezone.utc).isoformat()
 if utc(a.observed_at)>utc(now):raise ValueError('OBSERVATION_IN_FUTURE')
 packet={k:e[k] for k in ['event_id','home_team','away_team']};packet.update({'source':a.source,'source_sha256':hashlib.sha256(raw).hexdigest(),'observed_at_utc':a.observed_at,'retrieved_at_utc':now,'parser_version':'nfl_mode_packet.v1','raw_file':str(a.raw)})
 if a.kind=='market':
  if any(data.get(k)!=e[k] for k in ['event_id','home_team','away_team']):raise ValueError('MARKET_RAW_EVENT_BINDING')
  packet.update({'period':'FULL_GAME','odds_format':'AMERICAN','state':'PREGAME','quotes':data['quotes']});market_values(packet,e,now)
 else:
  if not a.effective_at:raise ValueError('LIVE_EFFECTIVE_TIMESTAMP_REQUIRED')
  if utc(a.effective_at)>utc(a.observed_at):raise ValueError('EFFECTIVE_AFTER_OBSERVATION')
  packet.update({'state_boundary':'PRE_PLAY','game_status':'IN_PROGRESS','effective_at_utc':a.effective_at,'play_id':data['play_id'],'features':state_from_nflverse(data,e)})
 with a.output.open('x') as f:json.dump(packet,f,indent=2,allow_nan=False)
if __name__=='__main__':main()
