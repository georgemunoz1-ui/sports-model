#!/usr/bin/env python3
"""Complete official season census, D-1 team form and prior-date pitcher inputs."""
import argparse,collections,datetime as dt,hashlib,json,sys
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from models.current.common import save
from models.nfl.contextual.recovered_inference import digest,utc
from scripts.verify_nfl_weekly_sources import manifest
from harness.mlb_form_state import normalize_team
from pipelines.cards.selection import select


def innings_outs(value):
    whole,part=str(value).split('.') if '.' in str(value) else (str(value),'0')
    if part not in ('0','1','2') or int(whole)<0:raise ValueError('INVALID_BASEBALL_INNINGS')
    return 3*int(whole)+int(part)


def pitcher(j,pid,day,final_ids):
    rows=[r for x in j['stats'] if x['group']['displayName']=='pitching' and x['type']['displayName']=='gameLog' for r in x['splits']]
    seen=set();tot=collections.Counter()
    for r in rows:
        if str(r['player']['id'])!=str(pid):raise ValueError('PITCHER_IDENTITY')
        if r['gameType']!='R' or r['date']>=day:continue
        gid=str(r['game']['gamePk'])
        if gid in seen or gid not in final_ids:raise ValueError('PITCHER_GAME_CENSUS_OR_DUPLICATE:'+gid)
        seen.add(gid);s=r['stat'];outs=innings_outs(s['inningsPitched'])
        if outs!=s['outs']:raise ValueError('PITCHER_OUTS_MISMATCH')
        for key,value in {'outs':outs,'er':s['earnedRuns'],'k':s['strikeOuts'],'bb':s['baseOnBalls'],'tbf':s['battersFaced'],'gs':s['gamesStarted']}.items():
            if not isinstance(value,int) or value<0:raise ValueError('INVALID_PITCHER_STAT')
            tot[key]+=value
    if tot['tbf']<10 or tot['outs']<3:raise ValueError('INSUFFICIENT_OBSERVED_PITCHER_PROFILE')
    return {'era':round(tot['er']*27/tot['outs'],3),'gs':tot['gs'],'k':round(tot['k']/tot['tbf']*100,2),'bb':round(tot['bb']/tot['tbf']*100,2),'observed_game_ids':sorted(seen),'innings_outs':tot['outs']}


def prepare(source,output):
    manifest(source,'manifest.json');now=dt.datetime.now(dt.timezone.utc);day=now.astimezone(ZoneInfo('America/New_York')).date().isoformat();report=json.loads((source/'report.json').read_text());receipts=[r for r in report['sources'] if r['league']=='mlb']
    if any(r['status']!='CAPTURED' for r in receipts):raise ValueError('OFFICIAL_CAPTURE_FAILURE')
    rec=next(r for r in receipts if r['kind']=='official_season');season=json.loads((source/rec['raw_path']).read_text());finals={};stats=collections.defaultdict(collections.Counter)
    for d in season['dates']:
        if d['totalGames']!=len(d['games']):raise ValueError('DAILY_SCHEDULE_CENSUS')
        for g in d['games']:
            if g['gameType']!='R' or g['officialDate']>=day:continue
            if g['status']['detailedState'] in ('Postponed','Cancelled','Suspended'):continue
            if g['status']['abstractGameState']!='Final':
                if g['status']['detailedState'] not in ('Postponed','Cancelled','Suspended'):raise ValueError('PAST_GAME_UNRESOLVED:'+str(g['gamePk']))
                continue
            if utc(g['gameDate'])>=now:raise ValueError('FUTURE_FINAL')
            gid=str(g['gamePk']);teams=g['teams'];h=normalize_team(teams['home']['team']['name']);a=normalize_team(teams['away']['team']['name']);hs=teams['home']['score'];ass=teams['away']['score']
            if h==a or hs==ass or min(hs,ass)<0:raise ValueError('INVALID_FINAL_IDENTITY')
            row={'home':h,'away':a,'home_score':hs,'away_score':ass,'date':g['officialDate']}
            if gid in finals:
                if finals[gid]!=row:raise ValueError('DUPLICATE_FINAL_REVISION:'+gid)
                continue  # Suspended/resumed game can appear on both calendar dates.
            finals[gid]=row
            for t,rf,ra in [(h,hs,ass),(a,ass,hs)]:stats[t].update(rf=rf,ra=ra,games=1)
    if season['totalGames']!=sum(len(d['games']) for d in season['dates']) or len(stats)!=30:raise ValueError('SEASON_CENSUS')
    daily=[]
    for rec in receipts:
        if rec['kind']!='official_schedule':continue
        for d in json.loads((source/rec['raw_path']).read_text())['dates']:
            for g in d['games']:
                if g['gameType']!='R':continue
                if d['date']==day and g['status']['abstractGameState']=='Preview' and utc(g['gameDate'])>now:daily.append(g)
                if d['date']<day and g['status']['abstractGameState']=='Final' and g['status']['detailedState'] not in ('Postponed','Cancelled','Suspended'):
                    prior=finals.get(str(g['gamePk']));t=g['teams']
                    expected={'home':normalize_team(t['home']['team']['name']),'away':normalize_team(t['away']['team']['name']),'home_score':t['home']['score'],'away_score':t['away']['score'],'date':g['officialDate']}
                    if prior!=expected:raise ValueError('DAILY_SEASON_RECONCILIATION')
    form={t:{'rf':s['rf']/s['games'],'ra':s['ra']/s['games'],'games':s['games']} for t,s in stats.items()};starters={}
    for rec in receipts:
        if rec['kind']=='starter_game_logs':
            pid=rec['url'].split('/people/')[1].split('/')[0];starters[pid]=pitcher(json.loads((source/rec['raw_path']).read_text()),pid,day,finals)
    sys.path.insert(0,str(ROOT/'harness'));import mlb_daily_coordinator as C
    parks=json.loads((ROOT/'data/backfill/mlb/2026/park_factors.json').read_text());events=[]
    for g in daily:
        e={'event_id':'MLB:'+str(g['gamePk']),'start_time_utc':g['gameDate'],'slate_date':utc(g['gameDate']).astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat()}
        for side in ('home','away'):
            t=g['teams'][side];pid=t.get('probablePitcher',{}).get('id')
            if pid is None:
                pid='unknown:'+str(g['gamePk'])+':'+side
                starters[pid]={'era':None,'gs':0,'k':None,'bb':None,'observed_game_ids':[],'treatment':'FROZEN_V13_LEAGUE_PRIOR_UNKNOWN_STARTER'}
            elif str(pid) not in starters:raise ValueError('PROBABLE_PITCHER_PROFILE_MISSING')
            e[side+'_team']=normalize_team(t['team']['name']);e[side+'_pitcher_id']=pid;e[side+'_starter']=t.get('probablePitcher',{}).get('fullName')
        e['park_factor']=C.park_factor(parks,e['home_team']);events.append(e)
    if len({e['event_id'] for e in events})!=len(events):raise ValueError('DUPLICATE_SCHEDULE')
    names=['harness/run_v13_historical.py','harness/mlb_form_state.py','harness/mlb_daily_coordinator.py','engine/hfa.py','data/backfill/mlb/2026/park_factors.json','data/mlb/ml_asof/p3_candidate_config.json','models/current/common.py','models/current/mlb.py','pipelines/cards/adapters/mlb.py']
    pins={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names};pkg={'schema':'sports.current_research_package.v1','league':'mlb','model_id':select('mlb')['default_model_id'],'captured_at_utc':now.isoformat(),'training_cutoff_utc':now.isoformat(),'ttl_hours':6,'covered_dates':[day],'events':events,'team_state':form,'starter_state':starters,'consumed_game_ids':sorted(finals),'model_sha256':digest({'pins':pins,'teams':form,'starters':starters}),'data_grade':'OFFICIAL_SEASON_CENSUS_AND_CURRENT_PITCHER_LOGS','model_lineage':{'frozen_engine':'harness/run_v13_historical.py','official_finals':len(finals),'current_pitcher_profiles':len(starters),'team_count':len(form),'form_through':max(r['date'] for r in finals.values()),'game_log_cutoff':'STRICTLY_BEFORE_OFFICIAL_SLATE_DATE','source_census_reconciled':True},'source_fetches':[{'source':r['url'],'sha256':r['raw_sha256'],'fetched_at_utc':r['retrieved_at_utc']} for r in receipts],'limitations':['PROBABLE_STARTERS_NOT_CONFIRMED','NO_LINEUP_OR_INJURY_EFFECT_TRANSFORM','V13_TIE_PROXY_NOT_FULL_EXTRA_INNINGS','TOTAL_RUNLINE_SETTLEMENT_NOT_VALIDATED','NO_WAGERING_AUTHORITY'],'action_authority':False,'code_pins':pins}
    save(output/'mlb/package.json',pkg);print(json.dumps(pkg['model_lineage']));return pkg

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();prepare(a.source,a.output)
