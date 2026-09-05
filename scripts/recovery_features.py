"""Materialize hash-bound diagnostic inputs from recovery source bytes; no model execution."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

def sha(data):return hashlib.sha256(data).hexdigest()
def materialize(root):
    root=Path(root);report=json.loads((root/'report.json').read_text());manifest=json.loads((root/'manifest.json').read_text())
    for name,expected in manifest['files'].items():
        target=(root/name).resolve()
        if not target.is_relative_to(root.resolve()): raise ValueError('MANIFEST_PATH_ESCAPE')
        if sha(target.read_bytes())!=expected:raise ValueError('SOURCE_MANIFEST_HASH_MISMATCH')
    sources=[]
    for r in report['sources']:
        if r['status']!='CAPTURED':continue
        body=(root/r['raw_path']).read_bytes()
        if sha(body)!=r['raw_sha256']:raise ValueError('RAW_SOURCE_HASH_MISMATCH')
        sources.append((r,json.loads(body)))
    day=report['requested_date'];logs={};boxes={};standings={};games=[]
    for r,data in sources:
        if r['kind']=='starter_game_logs':logs[int(re.search(r'/people/(\d+)',r['url'])[1])]=(r,data)
        if r['kind']=='official_boxscore':boxes[int(re.search(r'/game/(\d+)',r['url'])[1])]=(r,data)
        if r['kind']=='official_standings':
            for group in data.get('records',[]):
                for team in group.get('teamRecords',[]):standings[team['team']['id']]=(r,team)
        if r['kind']=='official_schedule' and f'date={day}' in r['url']:
            for d in data.get('dates',[]):
                if d['date']==day:games.extend((r,g) for g in d.get('games',[]))
    def reference(r):return dict(raw_sha256=r['raw_sha256'],retrieved_at_utc=r['retrieved_at_utc'],source_observed_at_utc=None,observation_time_policy='RETRIEVAL_BOUND_ONLY',source_url=r['url'])
    rows=[]
    for schedule,g in games:
        row={'league':'MLB','event_id':str(g['gamePk']),'scheduled_start_utc':g['gameDate'],
             'artifact_role':'RECOVERED_DIAGNOSTIC_INPUT','prospective_eligibility':False,'market_overlay':'OFF','action_authority':'OFF',
             'schedule_provenance':reference(schedule),'missing_required':[],
             'captured_after_start':schedule['retrieved_at_utc']>=g['gameDate']}
        box=boxes.get(g['gamePk'])
        for side in ('home','away'):
            t=g['teams'][side];pid=t.get('probablePitcher',{}).get('id')
            out={'team_id':t['team']['id'],'team_name':t['team']['name'],'starter_id':pid,'starter_quality':None,'team_baseline':None,
                 'lineup_state':'MISSING','bullpen_availability':'UNKNOWN','weather_state':'MISSING'}
            if not pid:row['missing_required'].append(side+':starter')
            if pid in logs:
                r,data=logs[pid];splits=[s for group in data.get('stats',[]) for s in group.get('splits',[]) if s.get('date','9999')<day]
                stats=[s['stat'] for s in splits]
                mandatory=('outs','earnedRuns','battersFaced','strikeOuts','baseOnBalls','gamesStarted')
                if any(any(key not in st or st[key] is None for key in mandatory) for st in stats):
                    stats=[]
                outs=sum(int(s.get('outs',0)) for s in stats);er=sum(int(s.get('earnedRuns',0)) for s in stats);bf=sum(int(s.get('battersFaced',0)) for s in stats)
                if outs and bf:
                    out['starter_quality']={'era':27*er/outs,'gs':sum(int(s.get('gamesStarted',0)) for s in stats),
                      'k_pct':100*sum(int(s.get('strikeOuts',0)) for s in stats)/bf,'bb_pct':100*sum(int(s.get('baseOnBalls',0)) for s in stats)/bf,
                      'outs':outs,'sample_games':len(stats),'games_before_date':day,'provenance':reference(r)}
            if out['starter_quality'] is None:row['missing_required'].append(side+':starter_quality')
            if t['team']['id'] in standings:
                r,st=standings[t['team']['id']];gp=st.get('gamesPlayed',0)
                if gp and st.get('runsScored') is not None and st.get('runsAllowed') is not None:
                    out['team_baseline']={'games_played':gp,'rf_pg':st['runsScored']/gp,'ra_pg':st['runsAllowed']/gp,'provenance':reference(r),'vintage':'LIVE_AT_RETRIEVAL_NOT_HISTORICAL'}
            if out['team_baseline'] is None:row['missing_required'].append(side+':team_baseline')
            if box:
                r,b=box;team=b.get('teams',{}).get(side,{});order=team.get('battingOrder',[])
                out.update(batting_order_ids=order,lineup_state='ORDER_OBSERVED' if len(order)==9 else 'PARTIAL_OR_MISSING',
                    bullpen_roster_ids=team.get('bullpen',[]),lineup_provenance=reference(r))
            row[side]=out
        rows.append(row)
    # No result scores or market fields enter these normalized event identities.
    discovery=[]
    for r,data in sources:
        if r['kind']!='scoreboard_discovery':continue
        for e in data.get('events',[]):
            comps=e.get('competitions',[])
            for c in comps:
                participants={x.get('homeAway'):x.get('team',{}) for x in c.get('competitors',[])}
                discovery.append({'league':r['league'],'event_id':'espn:'+str(e['id']),'start_utc':e.get('date'),
                    'home_team':participants.get('home',{}).get('displayName'),'away_team':participants.get('away',{}).get('displayName'),
                    'evidence_tier':2,'authoritative_identity_verified':False,'source':reference(r)})
    result={'role':'RECOVERED_DIAGNOSTIC_INPUTS','source_manifest_sha256':sha((root/'manifest.json').read_bytes()),
      'created_at_utc':datetime.now(timezone.utc).isoformat(),'mlb':rows,'discovery_events':discovery,
      'summary':{'mlb_games':len(rows),'mlb_complete_numeric_baselines':sum(not r['missing_required'] for r in rows),
      'mlb_starters_with_quality':sum(r[s]['starter_quality'] is not None for r in rows for s in ('home','away')),
      'mlb_observed_nine_player_orders':sum(r[s]['lineup_state']=='ORDER_OBSERVED' for r in rows for s in ('home','away')),
      'prospectively_eligible_forecasts':0,'action_authority':'OFF'}}
    payload=(json.dumps(result,sort_keys=True,indent=2)+'\n').encode();path=root/f'diagnostic_inputs_{sha(payload)}.json'
    with path.open('xb') as f:f.write(payload)
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('capture_root');a=p.parse_args();print(json.dumps(materialize(a.capture_root)['summary'],indent=2))
