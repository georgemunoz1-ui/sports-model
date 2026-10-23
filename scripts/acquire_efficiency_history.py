#!/usr/bin/env python3
"""Capture SportsDataverse efficiency sources without asserting historical PIT truth."""
from __future__ import annotations
import argparse, concurrent.futures, datetime as dt, hashlib, json, pathlib, urllib.request

def utc(): return dt.datetime.now(dt.timezone.utc).isoformat()

def capture(output, spec):
    rec={**spec, 'requested_at_utc':utc(), 'provider_observed_at_utc':None,
         'historical_pregame_eligibility':False,'evidence_scope':'RETROSPECTIVE_RECONSTRUCTION'}
    try:
        req=urllib.request.Request(spec['url'],headers={'User-Agent':'sports-model-research/1.0'})
        with urllib.request.urlopen(req,timeout=120) as response:
            raw=response.read();rec.update(http_status=response.status,final_url=response.url,headers=dict(response.headers))
        p=output/spec['path'];p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('xb') as f:f.write(raw)
        rec.update(status='CAPTURED',sha256=hashlib.sha256(raw).hexdigest(),byte_count=len(raw))
    except Exception as e:rec.update(status='FAILED',error=str(e))
    rec['retrieved_at_utc']=utc()
    return rec

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--cfb-seasons',nargs='*',type=int,default=[]);p.add_argument('--nba-seasons',nargs='*',type=int,default=[]);p.add_argument('--player-box',action='store_true');a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    specs=[]
    for y in a.cfb_seasons:
        specs.append({'league':'cfb','dataset':'classic_epa_pbp','season':y,'path':f'cfb/play_by_play_{y}.parquet','url':f'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/cfbfastR_cfb_pbp/play_by_play_{y}.parquet'})
    for y in a.nba_seasons:
        for dataset,tag,stem in [('team_box','espn_nba_team_boxscores','team_box'),('schedule','espn_nba_schedules','nba_schedule')]+([('player_box','espn_nba_player_boxscores','player_box')] if a.player_box else []):
            specs.append({'league':'nba','dataset':dataset,'season':y,'path':f'nba/{stem}_{y}.parquet','url':f'https://github.com/sportsdataverse/sportsdataverse-data/releases/download/{tag}/{stem}_{y}.parquet'})
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        records=[]
        for r in pool.map(lambda s:capture(a.output,s),specs):
            records.append(r); print(json.dumps({k:r.get(k) for k in ('league','dataset','season','status','byte_count','error')}),flush=True)
            (a.output/'capture-progress.json').write_text(json.dumps(records,indent=2))
    report={'schema':'efficiency-source-capture-v1','created_at_utc':utc(),'action_authority':False,'sources':records,'historical_original_availability_verified':False}
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    (a.output/'manifest.json').write_text(json.dumps({str(f.relative_to(a.output)):hashlib.sha256(f.read_bytes()).hexdigest() for f in a.output.rglob('*') if f.is_file()},indent=2))
    if any(r['status']!='CAPTURED' for r in records):raise SystemExit(2)
if __name__=='__main__':main()
