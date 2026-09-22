#!/usr/bin/env python3
"""Acquire replayable historical/current inputs for seven-league research recovery."""
import argparse
import calendar
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.recovery_capture import ROUTES,capture,save_json


def binary(root, spec):
    name,url,pin=spec
    rec={'name':name,'url':url,'retrieved_at_utc':None,'expected_sha256':pin}
    try:
        with urllib.request.urlopen(url,timeout=60) as response: raw=response.read(80_000_001)
        rec['retrieved_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
        if len(raw)>80_000_000:raise ValueError('SOURCE_SIZE_LIMIT')
        h=hashlib.sha256(raw).hexdigest()
        if pin and h!=pin:raise ValueError('PIN_MISMATCH')
        path=root/'binary'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        rec.update(status='CAPTURED',sha256=h,path=str(path.relative_to(root)))
    except Exception as e:rec.update(status='FAILED',error=str(e))
    return rec


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False);today=dt.datetime.now(dt.timezone.utc).date()
    specs=[]
    for offset in range(-22,8):
        day=today+dt.timedelta(days=offset)
        specs.append(('mlb','official_schedule',f'https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={day}&hydrate=probablePitcher,linescore,venue',1))
    specs.append(('wnba','official_schedule','https://cdn.wnba.com/static/json/staticData/scheduleLeagueV2.json',1))
    with ThreadPoolExecutor(max_workers=6) as pool: results=list(pool.map(lambda s:capture(a.output,s),specs))
    details={}
    for r,j in results:
        if not j or r['kind']!='official_schedule':continue
        if r['league']=='wnba':
            for day in j['leagueSchedule']['gameDates']:
                for game in day['games']:
                    gid=str(game['gameId'])
                    if gid.startswith('102') and game['gameStatus']==3 and game['gameDateTimeUTC'][:10]>'2026-08-30':
                        u=f'https://cdn.wnba.com/static/json/liveData/boxscore/boxscore_{gid}.json'
                        details[u]=('wnba','official_boxscore',u,1)
            continue
        if r['league']!='mlb':continue
        for day in j.get('dates',[]):
            if day['date']!=str(today):continue
            for game in day['games']:
                for side in ('home','away'):
                    pid=game['teams'][side].get('probablePitcher',{}).get('id')
                    if pid:
                        u=f'https://statsapi.mlb.com/api/v1/people/{pid}/stats?stats=gameLog&group=pitching&season={today.year}'
                        details[u]=('mlb','starter_game_logs',u,1)
    with ThreadPoolExecutor(max_workers=6) as pool: results.extend(pool.map(lambda s:capture(a.output,s),details.values()))
    manifest=json.loads((ROOT/'data/cfb/model/CFB_V2_ACQUISITION_MANIFEST.json').read_text())
    c=manifest['source']['commit'];binaries=[]
    for f in manifest['files']:
        binaries.append((f['path'],f'https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/{c}/'+f['path'],f['sha256']))
    binaries.append(('cfb_current.parquet',f'https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/schedules/parquet/cfb_schedules_{today.year}.parquet',None))
    binaries.extend([
        ('nba_schedule_master.parquet','https://raw.githubusercontent.com/sportsdataverse/hoopR-data/main/nba_schedule_master.parquet',None),
        ('nhl_schedule_master.parquet','https://raw.githubusercontent.com/sportsdataverse/fastRhockey-data/main/nhl_schedule_master.parquet',None),
        ('mls_scores.csv','https://www.football-data.co.uk/new/USA.csv',None)])
    wm=json.loads((ROOT/'data/wnba/source/STAGING_MANIFEST_2026-08-11.json').read_text())
    for family,meta in wm['families'].items():
        for f in meta['files']:
            if f['season']=='2025' and f['role'] in {'results_long','team_box'}:
                rel=f['relative_path'].replace('2025',str(today.year))
                binaries.append((f'wnba_{family}_{f["role"]}.parquet',f'https://raw.githubusercontent.com/{meta["repository"]}/master/{rel}',None))
    with ThreadPoolExecutor(max_workers=6) as pool: binary_results=list(pool.map(lambda s:binary(a.output,s),binaries))
    report={'created_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'source_capture_only':True,'sources':[r for r,_ in results],'binary_sources':binary_results,'action_authority':False}
    save_json(a.output/'report.json',report)
    save_json(a.output/'manifest.json',{str(p.relative_to(a.output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in a.output.rglob('*') if p.is_file()})
    print(json.dumps({'json_sources':len(results),'json_failures':sum(r['status']=='FAILED' for r,_ in results),'binary_sources':len(binary_results),'binary_failures':[r for r in binary_results if r['status']=='FAILED']}))


if __name__=='__main__':main()
