"""Capture evidence for seven sports; never manufactures features or registers forecasts."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import urllib.request

ROUTES = {'mlb':'baseball/mlb','nfl':'football/nfl','cfb':'football/college-football',
          'nba':'basketball/nba','wnba':'basketball/wnba','nhl':'hockey/nhl','mls':'soccer/usa.1'}
REQUIRED = {
 'mlb':['authoritative_schedule','both_starters','starter_quality','offense_baselines','input_PIT'],
 'nfl':['authoritative_schedule','fitted_team_ratings','quarterback_status','input_PIT','card_adapter'],
 'cfb':['authoritative_schedule','fitted_team_ratings','division_bridge','input_PIT'],
 'nba':['authoritative_schedule','fitted_efficiency_state','PIT_feature_snapshots'],
 'wnba':['authoritative_schedule','fitted_efficiency_state','PIT_feature_snapshots','card_adapter'],
 'nhl':['authoritative_schedule','goalie_status','fitted_model','card_adapter','input_PIT'],
 'mls':['authoritative_schedule','fitted_score_state','card_adapter','input_PIT']}
def utc(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def digest(data): return hashlib.sha256(data).hexdigest()
def write_once(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as f: f.write(data)
    except FileExistsError:
        if path.read_bytes() != data: raise RuntimeError('IMMUTABLE_CONTENT_CONFLICT')
def save_json(path, data): write_once(path, (json.dumps(data,sort_keys=True,indent=2)+'\n').encode())
def capture(root, spec):
    league, kind, url, tier = spec
    record={'league':league,'kind':kind,'url':url,'evidence_tier':tier,'requested_at_utc':utc(),
            'provider_observed_at_utc':None,'historical_pregame_eligibility':False}
    try:
        request=urllib.request.Request(url,headers={'User-Agent':'sports-model-evidence-capture/1.0','Accept':'application/json'})
        with urllib.request.urlopen(request, timeout=25) as response:
            body=response.read(20_000_001)
            record.update(http_status=response.status, headers=dict(response.headers.items()), final_url=response.url)
        record['retrieved_at_utc']=utc()
        if len(body)>20_000_000: raise ValueError('RESPONSE_LIMIT_EXCEEDED')
        sha=digest(body); write_once(root/'raw'/f'{sha}.json',body)
        record.update(raw_sha256=sha,raw_path=f'raw/{sha}.json',status='CAPTURED')
        data=json.loads(body)
        record['parse_status']='JSON_PARSED'
    except Exception as exc:
        record.update(status='FAILED',error_type=type(exc).__name__,error=str(exc)[:500],retrieved_at_utc=utc())
        data=None
    return record,data

def main():
    p=argparse.ArgumentParser();p.add_argument('--date',default=datetime.now(timezone.utc).date().isoformat())
    p.add_argument('--days',type=int,default=7);p.add_argument('--output',default='output/recovery');args=p.parse_args()
    if not 1<=args.days<=7: p.error('days must be 1..7')
    day=datetime.fromisoformat(args.date).date()
    if day>datetime.now(timezone.utc).date(): p.error('future capture date forbidden')
    root=Path(args.output)/('capture-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    root.mkdir(parents=True,exist_ok=False)
    specs=[]
    for offset in range(args.days):
        d=day-timedelta(days=offset)
        for league,route in ROUTES.items():
            specs.append((league,'scoreboard_discovery',f'https://site.api.espn.com/apis/site/v2/sports/{route}/scoreboard?dates={d:%Y%m%d}&limit=1000',2))
        specs.append(('mlb','official_schedule',f'https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d}&hydrate=probablePitcher,linescore,venue',1))
    with ThreadPoolExecutor(max_workers=8) as pool: fetched=list(pool.map(lambda s:capture(root,s),specs))
    details={}; events={league:set() for league in ROUTES}; today_events={league:set() for league in ROUTES}
    for record,data in fetched:
        if data is None: continue
        league=record['league']
        if record['kind']=='scoreboard_discovery':
            for event in data.get('events',[]):
                eid=str(event['id']);events[league].add(eid)
                if event.get('date','')[:10]==str(day):
                    today_events[league].add(eid)
                    url=f'https://site.api.espn.com/apis/site/v2/sports/{ROUTES[league]}/summary?event={eid}'
                    details[url]=(league,'event_detail_discovery',url,2)
        else:
            for date in data.get('dates',[]):
                for game in date.get('games',[]):
                    if date['date']!=str(day): continue
                    gid=game['gamePk'];url=f'https://statsapi.mlb.com/api/v1/game/{gid}/boxscore'
                    details[url]=('mlb','official_boxscore',url,1)
                    for side in ('home','away'):
                        pid=game['teams'][side].get('probablePitcher',{}).get('id')
                        if pid:
                            url=f'https://statsapi.mlb.com/api/v1/people/{pid}/stats?stats=gameLog&group=pitching&season={day.year}'
                            details[url]=('mlb','starter_game_logs',url,1)
    # Bound acquisition; never silently truncate a slate and declare it complete.
    pending=list(details.values()); cap=200
    with ThreadPoolExecutor(max_workers=8) as pool: fetched.extend(pool.map(lambda s:capture(root,s),pending[:cap]))
    records=[record for record,_ in fetched]
    code=Path(__file__).read_bytes()
    report={'schema':'all_sports_recovery_capture_v1','capture_completed_at_utc':utc(),'requested_date':str(day),
      'days':args.days,'code_commit':os.environ.get('GITHUB_SHA'),'collector_sha256':digest(code),
      'role':'SOURCE_EVIDENCE_ONLY','market_overlay':'OFF','action_authority':'OFF',
      'registrations_created':0,'forecasts_generated':0,'detail_requests_deferred':max(0,len(pending)-cap),
      'sources':records,'sports':{}}
    for league in ROUTES:
        rows=[r for r in records if r['league']==league]
        report['sports'][league]={'discovery_events_in_window':len(events[league]),'events_with_UTC_date':len(today_events[league]),
          'responses_captured':sum(r['status']=='CAPTURED' for r in rows),'requests_failed':sum(r['status']=='FAILED' for r in rows),
          'model_readiness':'BLOCKED_PENDING_FEATURE_AND_PROVENANCE_VALIDATION','required_unverified':REQUIRED[league]}
    save_json(root/'report.json',report)
    save_json(root/'manifest.json',{'files':{str(f.relative_to(root)):digest(f.read_bytes()) for f in sorted(root.rglob('*')) if f.is_file()},'created_at_utc':utc()})
    print(json.dumps({'output':str(root),'sports':report['sports']},indent=2))
    if any(r['status']=='FAILED' for r in records) or report['detail_requests_deferred']: raise SystemExit(2)
if __name__=='__main__': main()
