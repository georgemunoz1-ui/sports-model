"""Prepare an isolated official-source postseason research package."""
import argparse
import collections
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from research.mlb_postseason_v1 import MODEL_ID,POSTSEASON_TYPES,sha,stamp,save_once,instant,validate_inputs
from scripts.prepare_mlb_official_current import pitcher
from harness.mlb_form_state import normalize_team
from harness.mlb_daily_coordinator import park_factor


def prepare(root,day):
    root=Path(root); source=root/'sources'
    receipts=json.loads((source/'report.json').read_text())['sources']
    by={r['kind']:r for r in receipts}
    def get(kind):
        r=by[kind]
        if r['status']!='CAPTURED' or sha(source/r['raw_path'])!=r['raw_sha256']:
            raise ValueError('INVALID_SOURCE:'+kind)
        return json.loads((source/r['raw_path']).read_text())
    season=get('season'); today=get('today'); finals={}; stats=collections.defaultdict(collections.Counter)
    if season['totalGames']!=sum(len(d['games']) for d in season['dates']):
        raise ValueError('SEASON_CENSUS_COUNT')
    for d in season['dates']:
        if d['totalGames']!=len(d['games']):raise ValueError('DAILY_CENSUS_COUNT')
        for g in d['games']:
            if g['gameType'] not in POSTSEASON_TYPES|{'R'} or g['officialDate']>=day:continue
            if g['status']['detailedState'] in ('Postponed','Cancelled','Suspended'):continue
            if g['status']['abstractGameState']!='Final':raise ValueError('PRIOR_GAME_UNRESOLVED')
            teams=g['teams'];a=normalize_team(teams['away']['team']['name']);h=normalize_team(teams['home']['team']['name'])
            ar=teams['away']['score'];hr=teams['home']['score'];gid=str(g['gamePk'])
            if a==h or not all(type(v)is int and v>=0 for v in (ar,hr)) or ar==hr:raise ValueError('INVALID_FINAL')
            row={'date':g['officialDate'],'home':h,'away':a,'home_score':hr,'away_score':ar,'game_type':g['gameType']}
            if gid in finals:
                if finals[gid]!=row:raise ValueError('CONFLICTING_FINAL')
                continue
            finals[gid]=row
            stats[a].update(rf=ar,ra=hr,games=1);stats[h].update(rf=hr,ra=ar,games=1)
    if len(stats)!=30 or max(r['date']for r in finals.values())!=(dt.date.fromisoformat(day)-dt.timedelta(days=1)).isoformat():
        raise ValueError('THIRTY_TEAM_OR_D1_CENSUS')
    forms={t:{'rf':s['rf']/s['games'],'ra':s['ra']/s['games'],'games':s['games']}for t,s in stats.items()}
    regular_ids={gid for gid,r in finals.items() if r['game_type']=='R'}
    profiles={k.split('_')[1]:pitcher(get(k),k.split('_')[1],day,regular_ids)for k in by if k.startswith('pitcher_')}
    parks=json.loads((ROOT/'data/backfill/mlb/2026/park_factors.json').read_text())
    events=[];context=[]
    for d in today['dates']:
        if d['totalGames']!=len(d['games']):raise ValueError('TODAY_CENSUS')
        for g in d['games']:
            if instant(g['gameDate']).astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat()!=day:continue
            if g['gameType']not in POSTSEASON_TYPES:raise ValueError('NON_POSTSEASON_EVENT')
            feed=get('gamefeed_'+str(g['gamePk']));gd=feed['gameData']
            if feed['gamePk']!=g['gamePk']:raise ValueError('FEED_IDENTITY')
            x={'event_id':'MLB:'+str(g['gamePk']),'start_time_utc':g['gameDate'],'slate_date':day,'through_date':max(r['date']for r in finals.values()),'game_type':g['gameType'],'captured_status':g['status']['abstractGameState']}
            c={'event_id':x['event_id'],'retrieved_at_utc':by['gamefeed_'+str(g['gamePk'])]['retrieved_at_utc'],'weather':gd.get('weather'),'lineups':{},'used_as_model_input':False}
            for side in ('away','home'):
                t=g['teams'][side];name=normalize_team(t['team']['name']);p=t.get('probablePitcher');fp=gd.get('probablePitchers',{}).get(side)
                if not p or not fp or p['id']!=fp['id'] or name!=normalize_team(gd['teams'][side]['name']):raise ValueError('STARTER_OR_TEAM_IDENTITY')
                x[side+'_team']=name;x[side+'_form']=forms[name];x['sp_'+side]=profiles[str(p['id'])];x[side+'_starter']=p['fullName'];x[side+'_pitcher_id']=p['id']
                c['lineups'][side]=feed['liveData']['boxscore']['teams'][side].get('battingOrder',[])
            x['park_factor']=park_factor(parks,x['home_team']);validate_inputs(x);events.append(x);context.append(c)
    if not events or len({e['event_id']for e in events})!=len(events):raise ValueError('EVENT_CENSUS')
    pkg={'schema':'mlb.postseason.research_package.v1','model_id':MODEL_ID,'created_at_utc':stamp(),'slate_date':day,'events':events,'team_state':forms,'consumed_finals':finals,'source_receipts':receipts,'context_available_not_used':context,'same_day_results_used':False,'starter_features':'REGULAR_SEASON_LOGS_STRICTLY_BEFORE_SLATE_DATE','action_authority':False}
    save_once(root/'package.json',pkg)
    print(json.dumps({'events':[(x['event_id'],x['away_team'],x['home_team'],x['captured_status'])for x in events],'consumed_finals':len(finals),'postseason_finals':sum(r['game_type']!='R'for r in finals.values()),'pitcher_profiles':len(profiles),'context':context},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--date',required=True);a=p.parse_args();prepare(a.root.resolve(),a.date)
