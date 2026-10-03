#!/usr/bin/env python3
"""Acquire event-bound context separately; capture never implies fitted use."""
import argparse,datetime as dt,hashlib,json,sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.recovery_capture import capture,save_json


def extract(event,receipt,payload):
    if receipt['status']!='CAPTURED':return {'event_id':event['event_id'],'state':'ACQUIRE_REQUIRED','receipt':receipt,'consumed':False}
    header=payload.get('header',{})
    if str(header.get('id'))!=event['event_id'].split(':')[1]:raise ValueError('CONTEXT_EVENT_MISMATCH')
    weather=payload.get('gameInfo',{}).get('weather')
    injuries=payload.get('injuries')
    retrieved=dt.datetime.fromisoformat(receipt['retrieved_at_utc'].replace('Z','+00:00'))
    start=dt.datetime.fromisoformat(event['start_time_utc'].replace('Z','+00:00'))
    return {'event_id':event['event_id'],'source_sha256':receipt['raw_sha256'],'source_url':receipt['url'],
            'retrieved_at_utc':receipt['retrieved_at_utc'],'source_effective_at':None,
            'timing_policy':'RETRIEVAL_BOUND_CURRENT_CONTEXT_ONLY','pre_start_capture':retrieved<start,
            'weather':{'state':'PARSED_NOT_ACTIVE'if weather else'ACQUIRE_REQUIRED','provider_fields':weather,'units':'PROVIDER_UNITS_UNVERIFIED','consumed':False},
            'player_availability':{'state':'COLLECTED_NOT_ACTIVE'if injuries is not None else'ACQUIRE_REQUIRED','records':injuries,'consumed':False},
            'numeric_context_gate':'HOLD_MISSING_HISTORICAL_PIT_TRAINING_FRAME_AND_FITTED_TRANSFORM',
            'warning':'Absent injury key is unknown availability, never proof all players are available.'}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--package',type=Path,required=True);ap.add_argument('--date',required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    a.output.mkdir(parents=True,exist_ok=False);p=json.loads(a.package.read_text());now=dt.datetime.now(dt.timezone.utc)
    events=[e for e in p['events']if e['slate_date']==a.date and dt.datetime.fromisoformat(e['start_time_utc'].replace('Z','+00:00'))>now]
    def get(e):
        url='https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event='+e['event_id'].split(':')[1]
        r,j=capture(a.output/'sources',('cfb',e['event_id'],url,1));return extract(e,r,j)
    with ThreadPoolExecutor(max_workers=4)as ex:rows=list(ex.map(get,events))
    save_json(a.output/'context-review.json',{'schema':'cfb.context_capture_review.v1','created_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'package_sha256':hashlib.sha256(a.package.read_bytes()).hexdigest(),'rows':rows,'source_tier':'PROVIDER_CONTEXT_NOT_OFFICIAL_AVAILABILITY_CERTIFICATION','action_authority':False})
    save_json(a.output/'manifest.json',{str(f.relative_to(a.output)):hashlib.sha256(f.read_bytes()).hexdigest()for f in a.output.rglob('*')if f.is_file()})
    print(json.dumps({'events':len(rows),'weather_captured':sum(r.get('weather',{}).get('state')=='PARSED_NOT_ACTIVE'for r in rows),'availability_captured':sum(r.get('player_availability',{}).get('state')=='COLLECTED_NOT_ACTIVE'for r in rows),'numerically_consumed':0}))


if __name__=='__main__':main()
