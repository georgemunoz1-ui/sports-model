#!/usr/bin/env python3
"""Acquire current seven-league evidence and NFL weekly sources; never infer readiness."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs, urlsplit
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.recovery_capture import ROUTES, capture, save_json


def context_summary_specs(events, today, leagues):
    """Opt-in current-day context, separate from completed history acquisition."""
    specs = {}
    for league in leagues:
        for event_id, wrapper in events[league].items():
            event = wrapper['event']
            stamp = dt.datetime.fromisoformat(event['date'].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('CONTEXT_EVENT_TIMEZONE_REQUIRED')
            if stamp.astimezone(ZoneInfo('America/Los_Angeles')).date() != today:
                continue
            url = f'https://site.api.espn.com/apis/site/v2/sports/{ROUTES[league]}/summary?event={event_id}'
            specs[url] = (league, 'event_context', url, 2)
    return specs


def context_inventory(results):
    rows = []
    for receipt, payload in results:
        if receipt['kind'] != 'event_context':
            continue
        requested_id = parse_qs(urlsplit(receipt['url']).query)['event'][0]
        row = {'league': receipt['league'], 'event_id': requested_id,
               'receipt': receipt, 'numerically_consumed': False,
               'expected_minutes': None, 'goalie_confirmation': 'UNKNOWN',
               'provider_authenticity': 'NOT_ASSESSED'}
        if receipt['status'] != 'CAPTURED':
            row['state'] = 'ACQUIRE_REQUIRED'
        elif str((payload or {}).get('header', {}).get('id')) != requested_id:
            row['state'] = 'QUARANTINED_EVENT_ID_MISMATCH'
        else:
            row.update(state='COLLECTED_NOT_ACTIVE',
                       availability_state='UNKNOWN' if payload.get('injuries') is None else 'PROVIDER_RECORDS_CAPTURED',
                       provider_injuries=payload.get('injuries'),
                       provider_odds=payload.get('pickcenter'),
                       exact_contract_status='UNVERIFIED',
                       personnel_transform='NOT_APPLIED')
        rows.append(row)
    return rows


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--context-league', action='append', choices=['nba','cfb','nhl'], default=[],
                   help='Capture current Pacific-day event context; no numerical adjustment')
    a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    today=dt.datetime.now(ZoneInfo('America/Los_Angeles')).date()
    specs=[]
    for offset in range(-7,8):
        day=today+dt.timedelta(days=offset)
        for league,route in ROUTES.items():
            specs.append((league,'schedule',f'https://site.api.espn.com/apis/site/v2/sports/{route}/scoreboard?dates={day:%Y%m%d}&limit=1000',2))
        specs.append(('mlb','official_schedule',f'https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={day}&hydrate=probablePitcher,linescore,venue',1))
    # Fill the numeric WNBA extension gap after the retained August 29 state.
    day=dt.date(today.year,8,30)
    while day < today-dt.timedelta(days=7):
        specs.append(('wnba','schedule',f'https://site.api.espn.com/apis/site/v2/sports/{ROUTES["wnba"]}/scoreboard?dates={day:%Y%m%d}&limit=1000',2))
        day+=dt.timedelta(days=1)
    with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(lambda s:capture(a.output,s),specs))
    events={k:{} for k in ROUTES};details={}
    for rec,payload in results:
        if not payload or rec['kind']!='schedule':continue
        for e in payload.get('events',[]):
            events[rec['league']][e['id']]={'event':e,'source_sha256':rec['raw_sha256'],'retrieved_at_utc':rec['retrieved_at_utc']}
            if rec['league'] in {'wnba','mlb','nfl'}:
                u=f"https://site.api.espn.com/apis/site/v2/sports/{ROUTES[rec['league']]}/summary?event={e['id']}"
                details[u]=(rec['league'],'event_summary',u,2)
    details.update(context_summary_specs(events, today, set(a.context_league)))
    with ThreadPoolExecutor(max_workers=6) as pool:results.extend(pool.map(lambda s:capture(a.output,s),details.values()))
    nfl=[]
    urls={'games.csv':'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv',f'play_by_play_{today.year}.csv':f'https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{today.year}.csv'}
    folder=a.output/'nfl';folder.mkdir()
    for name,url in urls.items():
        rec={'filename':name,'source_url':url,'requested_at_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
        try:
            with urllib.request.urlopen(url,timeout=60) as response:
                raw=response.read(80_000_001);headers=dict(response.headers)
            rec['retrieved_at_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
            if len(raw)>80_000_000:raise ValueError('SOURCE_SIZE_LIMIT')
            (folder/name).write_bytes(raw);rec.update(status='captured',sha256=hashlib.sha256(raw).hexdigest(),headers=headers)
        except Exception as e:rec.update(status='failed',error=str(e),retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        nfl.append(rec)
    save_json(folder/'receipt.json',nfl)
    save_json(a.output/'events.json',events)
    if a.context_league:
        save_json(a.output/'context_inventory.json', {'schema':'sports.operational_context_capture.v1',
                  'rows':context_inventory(results), 'source_capture_only':True,
                  'action_authority':False, 'model_input_usage_proven':False})
    save_json(a.output/'report.json',{'date':str(today),'timezone':'America/Los_Angeles','created_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'sources':[r for r,_ in results],'nfl_sources':nfl,'event_counts':{k:len(v) for k,v in events.items()},'source_capture_only':True,'action_authority':False})
    save_json(a.output/'manifest.json',{str(p.relative_to(a.output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in a.output.rglob('*') if p.is_file()})
    print(json.dumps({'events':{k:len(v) for k,v in events.items()},'failed_sources':sum(r['status']=='FAILED' for r,_ in results)+sum(r['status']=='failed' for r in nfl)}))

if __name__=='__main__':main()
