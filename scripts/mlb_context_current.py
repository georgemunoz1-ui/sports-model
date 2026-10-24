#!/usr/bin/env python3
"""Collect complete current context independently; no forecasts or auto-review."""
import argparse,datetime as dt,json,sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import mlb_postseason_workflow as W
from scripts.recovery_capture import capture,save_json,utc

def collect(root,day):
    root=Path(root).resolve();W.collect(root,day)
    p=W.load(root/'package.json');report=W.load(root/'sources/report.json');src={r['kind']:W.load(root/'sources'/r['raw_path']) for r in report['sources']}
    out=root/'context';out.mkdir();sources=[]
    def batch(specs):
        with ThreadPoolExecutor(max_workers=6) as ex: rows=list(ex.map(lambda s:capture(out,s),specs))
        sources.extend(r for r,d in rows)
        save_json(out/f'capture-{len(sources):04d}.json',{'sources':sources,'package_sha256':W.sha(root/'package.json'),'created_at_utc':utc()})
        if any(d is None for r,d in rows): raise ValueError('CONTEXT_CAPTURE_FAILED')
        return {r['kind']:d for r,d in rows}
    teams={src['gamefeed_'+e['event_id'].split(':')[1]]['gameData']['teams'][s]['id'] for e in p['events'] for s in ('home','away')}
    prior=(dt.date.fromisoformat(day)-dt.timedelta(days=10)).isoformat()
    specs=[('mlb',f'roster_{t}',f'https://statsapi.mlb.com/api/v1/teams/{t}/roster?rosterType=active&date={day}',1) for t in sorted(teams)]
    specs += [('mlb',f'transactions_{t}',f'https://statsapi.mlb.com/api/v1/transactions?teamId={t}&startDate={prior}&endDate={day}',1) for t in sorted(teams)]
    data=batch(specs);people=sorted({r['person']['id'] for k,j in data.items() if k.startswith('roster_') for r in j['roster']})
    specs=[]
    for offset in range(0,len(people),12):
        ids=','.join(map(str,people[offset:offset+12]))
        for typ in ('R','F','D','L','W'):
            specs.append(('mlb',f'people_{offset}_{typ}',f'https://statsapi.mlb.com/api/v1/people?personIds={ids}&hydrate=stats(group=[hitting,pitching],type=[gameLog],season={day[:4]},gameType={typ})',1))
    batch(specs)
    save_json(out/'report.json',{'sources':sources,'package_sha256':W.sha(root/'package.json'),'created_at_utc':utc(),'player_count':len(people),'injury_completeness':'TRANSACTIONS_AND_ROSTER_ONLY_NOT_FULL_INJURY_SEVERITY','series_roster_certification':False})
    print(json.dumps({'root':str(root),'players':len(people),'sources':len(sources)}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--date',required=True);a=p.parse_args();collect(a.root,a.date)
