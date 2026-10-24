#!/usr/bin/env python3
"""Official historical acquisition. Captured-now evidence is NOT pregame evidence."""
import argparse, json, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.recovery_capture import capture,save_json,utc
POST={'F','D','L','W'}

def acquire(root, years, resume=False):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=resume)
    if (root/'report.json').exists(): raise ValueError('ALREADY_COMPLETE')
    checkpoints=sorted(list(root.glob('report-*.json'))+list(root.glob('checkpoint-*.json')),key=lambda p:p.stat().st_mtime_ns)
    sources=json.loads(checkpoints[-1].read_text())['sources'] if resume and checkpoints else []
    def batch(specs):
        cached={r['kind']:r for r in sources if r['status']=='CAPTURED'}
        rows=[];pending=[]
        for spec in specs:
            old=cached.get(spec[1]);path=root/old['raw_path'] if old else None
            if old and old['url']==spec[2] and path.is_file() and __import__('hashlib').sha256(path.read_bytes()).hexdigest()==old['raw_sha256']:
                rows.append((old,json.loads(path.read_text())))
            else: pending.append(spec)
        with ThreadPoolExecutor(max_workers=6) as p: fresh=list(p.map(lambda s:capture(root,s),pending))
        rows+=fresh
        new={r['kind']:r for r in sources};new.update({r['kind']:r for r,d in fresh});sources[:]=new.values()
        save_json(root/('checkpoint-'+utc().replace(':','')+'.json'),{'created_at_utc':utc(),'sources':sources,'historical_pregame_eligibility':False})
        failures=[r for r,d in rows if d is None]
        if failures: raise RuntimeError('ACQUISITION_FAILURE:'+str([(r['kind'],r.get('error')) for r in failures]))
        return {r['kind']:d for r,d in rows}
    census=[]
    for year in years:
        schedules=batch([('mlb',f'season_{year}',f'https://statsapi.mlb.com/api/v1/schedule?sportId=1&startDate={year}-03-01&endDate={year}-12-01&hydrate=probablePitcher,linescore',1)])
        schedule=schedules[f'season_{year}'];games={str(g['gamePk']):g for d in schedule['dates'] for g in d['games'] if g['gameType'] in POST and g['status']['abstractGameState']=='Final'}
        print(year,'postseason',len(games),flush=True)
        specs=[]
        for gid,g in games.items():
            specs.append(('mlb',f'box_{year}_{gid}',f'https://statsapi.mlb.com/api/v1/game/{gid}/boxscore',1))
        team_dates=sorted({(g['teams'][s]['team']['id'],g['officialDate']) for g in games.values() for s in ('away','home')})
        specs.extend(('mlb',f'roster_{year}_{t}_{d}',f'https://statsapi.mlb.com/api/v1/teams/{t}/roster?rosterType=active&date={d}',1) for t,d in team_dates)
        data=batch(specs); people=set()
        for k,j in data.items():
            if k.startswith('roster_'): people.update(r['person']['id'] for r in j['roster'])
            else:
                for s in ('away','home'):
                    people.update(p['person']['id'] for p in j['teams'][s]['players'].values() if p.get('battingOrder') or p.get('stats',{}).get('pitching',{}).get('gamesStarted')==1)
        ids=sorted(people);specs=[]
        for offset in range(0,len(ids),12):
            chunk=','.join(map(str,ids[offset:offset+12]))
            for typ in ('R','F','D','L','W'):
                specs.append(('mlb',f'people_{year}_{offset}_{typ}',f'https://statsapi.mlb.com/api/v1/people?personIds={chunk}&hydrate=stats(group=[hitting,pitching],type=[gameLog],season={year},gameType={typ})',1))
        print(year,'player ids',len(ids),'log requests',len(specs),flush=True)
        batch(specs); census.append({'year':year,'games':len(games),'players':len(ids),'rosters':len(team_dates)})
    save_json(root/'report.json',{'created_at_utc':utc(),'sources':sources,'census':census,'historical_pregame_eligibility':False})
    print(json.dumps(census),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--years',nargs='+',type=int,required=True);p.add_argument('--resume',action='store_true');a=p.parse_args();acquire(a.root,a.years,a.resume)
