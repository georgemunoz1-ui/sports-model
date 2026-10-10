#!/usr/bin/env python3
"""Capture complete team-season schedules; overlaps reconcile by provider ID."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.recovery_capture import ROUTES,capture,save_json

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--league',choices=('nba','nhl','mls'),action='append');p.add_argument('--season-scope',type=Path);p.add_argument('--resume',action='store_true');a=p.parse_args()
    if a.season_scope is not None:
        if a.league!=['nhl']:raise ValueError('SEASON_SCOPE_EXPLICIT_NHL_REQUIRED')
        from scripts.nhl_atomic_capture import collect_history
        report=collect_history(a.output,a.season_scope,resume=a.resume)
        print(json.dumps({'sources':len(report['sources']),'status':report['status'],'pending_requests':report['pending_requests']}))
        if report['pending_requests']:raise SystemExit(2)
        return
    if a.resume:raise ValueError('RESUME_REQUIRES_EXPLICIT_NHL_SCOPE')
    a.output.mkdir(parents=True,exist_ok=False);results=[];specs=[]
    for league in (a.league or ('nba','nhl','mls')):
        u=f'https://site.api.espn.com/apis/site/v2/sports/{ROUTES[league]}/teams?limit=1000'
        rec,j=capture(a.output,(league,'team_directory',u,2));results.append((rec,j))
        if not j:continue
        teams=j['sports'][0]['leagues'][0]['teams']
        for entry in teams:
            tid=entry['team']['id']
            for year in range(2021,dt.date.today().year+1):
                u=f'https://site.api.espn.com/apis/site/v2/sports/{ROUTES[league]}/teams/{tid}/schedule?season={year}'
                if league in ('nba','nhl'):u+='&seasontype=2'
                specs.append((league,'team_season_schedule',u,2))
    with ThreadPoolExecutor(max_workers=6) as pool:results.extend(pool.map(lambda s:capture(a.output,s),specs))
    save_json(a.output/'report.json',{'sources':[r for r,_ in results],'created_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'action_authority':False})
    save_json(a.output/'manifest.json',{str(p.relative_to(a.output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in a.output.rglob('*') if p.is_file()})
    print(json.dumps({'sources':len(results),'failed':sum(r['status']=='FAILED' for r,_ in results),'event_records':sum(len(j.get('events',[])) for _,j in results if j)}))

if __name__=='__main__':main()
