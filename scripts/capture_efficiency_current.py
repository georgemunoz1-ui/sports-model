#!/usr/bin/env python3
"""Capture current CFB/NBA schedules and completed-game summaries for research."""
from __future__ import annotations
import argparse,concurrent.futures,hashlib,json,pathlib
from acquire_efficiency_history import capture,utc

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--date',action='append',required=True,help='YYYYMMDD');p.add_argument('--league',action='append',choices=['nba','cfb']);p.add_argument('--include-final-summaries',action='store_true');a=p.parse_args()
    for date in a.date:
        if len(date)!=8 or not date.isdigit():raise ValueError('date must be YYYYMMDD')
    a.output.mkdir(parents=True,exist_ok=False);specs=[]
    routes={'nba':'basketball/nba','cfb':'football/college-football'}
    for league in a.league or ['nba','cfb']:
        for date in sorted(set(a.date)):
            specs.append({'league':league,'dataset':'scoreboard','date':date,'path':f'{league}/scoreboard_{date}.json','url':f'https://site.api.espn.com/apis/site/v2/sports/{routes[league]}/scoreboard?dates={date}&limit=1000'+('&groups=80' if league=='cfb' else '')})
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:records=list(pool.map(lambda s:capture(a.output,s),specs))
    more={}
    if a.include_final_summaries:
        for r in records:
            if r['status']!='CAPTURED':continue
            j=json.loads((a.output/r['path']).read_text())
            for event in j.get('events',[]):
                if not event['status']['type'].get('completed'):continue
                league=r['league'];eid=str(event['id'])
                more[(league,eid)]={'league':league,'dataset':'summary','event_id':eid,'path':f'{league}/summary_{eid}.json','url':f'https://site.api.espn.com/apis/site/v2/sports/{routes[league]}/summary?event={eid}'}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:records.extend(pool.map(lambda s:capture(a.output,s),more.values()))
    (a.output/'report.json').write_text(json.dumps({'schema':'efficiency-current-capture-v1','sources':records,'created_at_utc':utc(),'action_authority':False},indent=2))
    (a.output/'manifest.json').write_text(json.dumps({str(p.relative_to(a.output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in a.output.rglob('*') if p.is_file()},indent=2))
    print(json.dumps({'sources':len(records),'captured':sum(r['status']=='CAPTURED' for r in records),'failed':sum(r['status']!='CAPTURED' for r in records)}))
    if any(r['status']!='CAPTURED' for r in records):raise SystemExit(2)
if __name__=='__main__':main()
