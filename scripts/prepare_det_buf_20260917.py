#!/usr/bin/env python3
"""One-event, source-pinned research package; no fitting and no simulations.

Inputs are immutable Actions archives from this run, not moving web URLs.
The narrow extraction assertions are intentional: changed source text must be reviewed.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, re, shutil, sys, os
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from bs4 import BeautifulSoup
from models.nfl.contextual import base_features as bf
from models.nfl.contextual.assimilation import run_nfl_assimilation_check,serialize_states,write_once
from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.recovered_inference import digest,utc
from models.nfl.contextual.qb_assimilation import build as qb_build,verified as qb_verified
from models.nfl.contextual.week2 import require_assimilation
EVENT='2026_02_DET_BUF'
HISTORY_STATE_SHA='3bab9194f7fac20d3790d8f691744a342c16f3bd7f2b0b2693d042741d8430d7'
CAPTURE_ARCHIVE_SHA='808220e192d9ffbad1ed38bc9d70645f4b38d8b67efd21afbf3086c095cb6078'
HISTORY_ARCHIVE_SHA='5149d68ad402ecb4c40ff39bc9de79b062c9e137879b888a6952c27dc3d1a3d1'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def require(condition,reason):
    if not condition:raise ValueError(reason)
def article(path):
    soup=BeautifulSoup(Path(path).read_text(),'html.parser')
    body=soup.select_one('.nfl-c-article__body') or soup.find('article') or soup
    return body.get_text(' ',strip=True)
def main():
    p=argparse.ArgumentParser();p.add_argument('--capture',type=Path,required=True);p.add_argument('--history',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output;out.mkdir(parents=True,exist_ok=False)
    receipts=json.loads((a.capture/'sources/receipt.json').read_text());rr={x['filename']:x for x in receipts}
    for name,expected in json.loads((a.capture/'capture_manifest.json').read_text()).items():require(sha(a.capture/name)==expected,'CAPTURE_MANIFEST_MISMATCH:'+name)
    src=a.capture/'sources'
    for r in receipts:
        if r['status']=='captured':require(sha(src/r['filename'])==r['sha256'],'SOURCE_RAW_HASH:'+r['filename'])
    shutil.copytree(src,out/'sources');src=out/'sources'
    history=json.loads((a.history/'historical_state.json').read_text())
    require(digest(history['states'])==history['state_sha256']==HISTORY_STATE_SHA,'HISTORY_STATE_CHANGED')
    require(history['base_feature_code_sha256']==sha(Path(bf.__file__)),'HISTORICAL_TRANSFORM_CHANGED')
    require((history['season'],history['week'])==(2026,1),'WRONG_STARTING_WEEK')
    write_once(out/'historical_state.json',history)
    write_once(out/'upstream_archives.json',{'capture':{'run_id':35288221132,'artifact_id':10525425662,'zip_sha256':CAPTURE_ARCHIVE_SHA},'history':{'run_id':35030382886,'artifact_id':10421286992,'zip_sha256':HISTORY_ARCHIVE_SHA},'raw_capture_manifest_sha256':sha(a.capture/'capture_manifest.json'),'historical_state_file_sha256':sha(a.history/'historical_state.json'),'artifact_provenance':'GITHUB_ACTIONS_DOWNLOADS; HASH_VERIFIED_LOCAL_DOWNLOADS; NOT_OFFICIAL_GAMEBOOK_CLEARANCE'})
    games=pd.read_csv(src/'games.csv',low_memory=False)
    current=games[games.game_id==EVENT];require(len(current)==1,'EVENT_NOT_UNIQUE')
    g=current.iloc[0]
    require((g.home_team,g.away_team,int(g.season),int(g.week),g.gameday,g.gametime)==('BUF','DET',2026,2,'2026-09-17','20:15'),'SCHEDULE_BINDING')
    require(pd.isna(g.home_score) and pd.isna(g.away_score),'TARGET_ALREADY_RECORDED')
    start=dt.datetime.fromisoformat(g.gameday+'T'+g.gametime).replace(tzinfo=ZoneInfo('America/New_York')).astimezone(dt.timezone.utc).isoformat()
    require(utc(now())<utc(start),'NOT_PREGAME')
    # Both official schedules must actually contain the event day and kickoff text.
    for name in ('det_schedule.html','buf_schedule.html'):
        text=article(src/name)
        require('09/17' in text and ('8:15 PM' in text or '8:15PM' in text),'OFFICIAL_SCHEDULE_NOT_MATCHED:'+name)
    event={'event_id':EVENT,'home_team':'BUF','away_team':'DET','gameday':g.gameday,'gametime':g.gametime,'start_time_utc':start,'location':'Home','venue':'Highmark Stadium, Orchard Park','source':rr['buf_schedule.html']['source_url'],'source_sha256':rr['buf_schedule.html']['sha256'],'supporting_schedule_receipts':[rr[n] for n in ('buf_schedule.html','det_schedule.html','games.csv')],'event_scope':'REQUESTED_EVENT_ONLY_NOT_FULL_WEEK2_SLATE','venue_limitation':'Provider stadium alias retained; no new-field-specific adjustment fitted'}
    # Restore historical state once, then reconcile ALL 16 completed W1 games.
    week=games[(games.season==2026)&(games.week==1)&(games.game_type=='REG')].copy()
    require(len(week)==16 and week[['home_score','away_score']].notna().all().all(),'WEEK1_REQUIRES_16_FINALS')
    prior={k:bf.TeamState(**v) for k,v in history['states'].items()}
    cutoff=now()
    audit=run_nfl_assimilation_check(path=src/'play_by_play_2026.csv',receipt=rr['play_by_play_2026.csv'],schedule=week,cutoff=cutoff,archive=out/'snapshots',output=out/'assimilation',prior_states=prior)
    require(audit['status']=='reconciled' and audit['state_update_applied'],'ASSIMILATION_FAILED')
    after=json.loads((out/'assimilation/team_state.json').read_text())
    model=load_artifact(ROOT/'data/nfl/contextual_v1/model_packed.json')
    pbp=pd.read_csv(src/'play_by_play_2026.csv',low_memory=False)
    evidence={'audit':audit,'state_before':serialize_states(prior),'state_after':after,'base_feature_code_sha256':sha(Path(bf.__file__)),'schedule_receipt':rr['games.csv'],'qb_update':qb_build(model,pbp,week,rr['play_by_play_2026.csv']['sha256'])}
    qb_verified(model,evidence)
    def meta(name):
        r=rr[name]
        return {'event_id':EVENT,'source':r['source_url'],'source_sha256':r['sha256'],'retrieved_at_utc':r['retrieved_at_utc'],'available_by_utc':r['retrieved_at_utc'],'published_at_utc':None}
    # Retain only football context, no scores or market columns from provider row.
    fields=['game_id','season','week','gameday','gametime','home_team','away_team','location','roof','home_rest','away_rest']
    request={k:g[k] for k in fields};request.update(home_score=None,away_score=None,temp=None,wind=None)
    row=bf._feature_row(pd.Series(request),bf.TeamState(**after['BUF']),bf.TeamState(**after['DET']))
    base={k:(None if pd.isna(v) else v) for k,v in row.items()};base.update({k:request[k] for k in ['gametime','location','roof']});base.update({k:int(request[k]) for k in ['home_rest','away_rest']})
    # Exact NWS hour for the captured stadium-area point, not a city daily low.
    weather=json.loads((src/'nws_hourly.json').read_text())['properties']
    periods=[v for v in weather['periods'] if utc(v['startTime'])<=utc(start)<utc(v['endTime'])];require(len(periods)==1,'WEATHER_HOUR_NOT_UNIQUE')
    period=periods[0];require(period['temperatureUnit']=='F','WEATHER_UNIT')
    match=re.fullmatch(r'(\d+(?:\.\d+)?) mph',period['windSpeed']);require(match is not None,'UNSUPPORTED_WIND_RANGE')
    wx={**meta('nws_hourly.json'),'published_at_utc':weather.get('updateTime'),'valid_from_utc':period['startTime'],'valid_to_utc':period['endTime'],'temperature_kind':'HOURLY_FORECAST','temperature_f':period['temperature'],'wind_kind':'SUSTAINED','wind_mph':float(match[1]),'spatial_scope':'NWS_STADIUM_AREA_GRID_PROXY_42.7748_-78.7870; NOT_FIELD_OBSERVATION','period':period,'point_source_receipt':rr['nws_points.json']}
    # Verify rest against completed W1 dates, not only the provider rest field.
    rest={}
    for side in ('home','away'):
        team=g[side+'_team'];last=week[(week.home_team==team)|(week.away_team==team)].sort_values('gameday').iloc[-1]
        days=(dt.date.fromisoformat(g.gameday)-dt.date.fromisoformat(last.gameday)).days
        require(days==int(g[side+'_rest']),'REST_CONFLICT');rest[side+'_rest']=days
    rest={**meta('games.csv'),**rest,'definition':'Calendar days between completed Week1 game date and this game; both independently recalculated as 4'}
    texts={name:article(src/name) for name in ('det_inactives.html','buf_inactives.html','det_injuries.html','buf_injuries.html','det_depth.html','buf_depth.html')}
    inactive={
      'DET':[('Blake Miller','T'),('Christian Mahogany','OL'),('Keith Abney II','CB'),('Ennis Rakestraw Jr.','CB'),('Jimmy Rolder','LB'),('Mekhi Wingo','DL'),('Ahmed Hassanein','DE')],
      'BUF':[('Skyler Bell','WR'),('Ty Johnson','RB'),('Jalon Kilgore','S'),('Armaj Reed-Adams','G'),('Jude Bowry','T'),('Ed Oliver','DL'),('T.J. Sanders','DL')]}
    teams={}
    for team,players in inactive.items():
        name=team.lower()+'_inactives.html';text=texts[name]
        # Apostrophe spelling is preserved in raw; normalized spelling is explicit.
        normalize=lambda x:re.sub(r'[^a-z0-9]','',x.lower())
        for player,pos in players:require(normalize(player) in normalize(text),'INACTIVE_NOT_IN_SOURCE:'+player)
        teams[team]={'source':rr[name]['source_url'],'source_sha256':rr[name]['sha256'],'complete':True,'players':[{'player':player,'position':pos,'inactive_reason':'NOT_ASSUMED_FROM_INACTIVE_LIST'} for player,pos in players]}
    final={'event_id':EVENT,'retrieved_at_utc':max(rr[n]['retrieved_at_utc'] for n in ('det_inactives.html','buf_inactives.html')),'teams':teams,'rows_sha256':digest(teams)}
    quarterbacks={}
    for side,expected in [('home','Josh Allen'),('away','Jared Goff')]:
        team=g[side+'_team'];name=team.lower()+'_depth.html'
        soup=BeautifulSoup((src/name).read_text(),'html.parser');rows=[[' '.join(c.stripped_strings) for c in tr.find_all(['th','td'])] for tr in soup.find_all('tr')]
        qb_rows=[r for r in rows if r and r[0]=='QB'];require(len(qb_rows)==1 and expected in qb_rows[0][1],'OFFICIAL_EXPECTED_QB_CONFLICT')
        require(g[side+'_qb_name']==expected,'QB_ID_NAME_CONFLICT')
        quarterbacks[team]={'name':expected,'id':g[side+'_qb_id'],'depth':'QB1','game_status':'NOT_REPORTED_OUT','final_inactive_status':'NOT_ON_COMPLETE_INACTIVE_LIST','workload':'UNKNOWN','source_receipt':rr[name],'id_source_receipt':rr['games.csv']}
    # Preserve final practice/report labels. Final availability is a separate fact;
    # active does not erase a questionnaire/practice feature's historical semantics.
    injury=[]
    soup=BeautifulSoup((src/'det_injuries.html').read_text(),'html.parser')
    for tr in soup.find_all('tr'):
        cols=[' '.join(td.stripped_strings) for td in tr.find_all('td')]
        if not cols:continue
        require(len(cols)==7,'DET_INJURY_SCHEMA')
        name,pos,issue,mon,tue,wed,status=cols
        injury.append({'team':'DET','player':name,'position':pos,'issue':issue,'practice':{'NP':'DNP','LP':'LIMITED','FP':'FULL'}.get(wed,wed or None),'game_status':status.upper() or 'NO_DESIGNATION','effective_date':'2026-09-16','source':rr['det_injuries.html']['source_url'],'source_sha256':rr['det_injuries.html']['sha256'],'final_status':'INACTIVE' if name in [v[0] for v in inactive['DET']] else 'NOT_ON_COMPLETE_INACTIVE_LIST'})
    require(len(injury)==5,'DET_INJURY_COVERAGE')
    text=texts['buf_injuries.html']
    for name,pos,issue,status in [('Cole Bishop','S','Knee/Groin','QUESTIONABLE'),('Ty Johnson','RB','Hamstring','QUESTIONABLE'),('T.J. Sanders','DL','Knee/Illness','QUESTIONABLE'),('Terrel Bernard','ILB','calf','NO_DESIGNATION')]:
        require(name in text and 'limited' in text.lower(),'BUF_INJURY_NOT_SUPPORTED:'+name)
        injury.append({'team':'BUF','player':name,'position':pos,'issue':issue,'practice':'LIMITED','game_status':status,'effective_date':'2026-09-16','source':rr['buf_injuries.html']['source_url'],'source_sha256':rr['buf_injuries.html']['sha256'],'final_status':'INACTIVE' if name in [v[0] for v in inactive['BUF']] else 'NOT_ON_COMPLETE_INACTIVE_LIST'})
    # Oliver's newly reported warmup injury has no earlier practice assumption.
    require('hip' in texts['buf_inactives.html'].lower() and 'warmup' in texts['buf_inactives.html'].lower().replace('-',''),'OLIVER_LATE_INJURY_NOT_SUPPORTED')
    injury.append({'team':'BUF','player':'Ed Oliver','position':'DL','issue':'hip during warmups','practice':None,'game_status':'OUT','effective_date':'2026-09-17','source':rr['buf_inactives.html']['source_url'],'source_sha256':rr['buf_inactives.html']['sha256'],'final_status':'INACTIVE','mapping_note':'EXPLICIT_NEW_INJURY_OUT; NO_MANUAL_POINT_WEIGHT'})
    personnel={'quarterbacks':quarterbacks,'injury_observations':injury,'final_inactive_report':final,'expected_workloads':'UNKNOWN','reserve_absences':[],'reserve_status_coverage':'NOT_EXHAUSTIVELY_CAPTURED; EMPTY_IS_NOT_NONE_EXIST','role_resolutions':{},'final_active_confirmations':{'DET':['D.J. Reed','Christian Izien','Levi Onwuzurike'],'BUF':['Cole Bishop']},'final_injury_policy':'Final list retained separately. Historical QUESTIONABLE/practice features retained; no invented healthy-scratch effect. Oliver explicit new injury maps to existing OUT proxy.'}
    for player in personnel['final_active_confirmations']['DET']:require(player in texts['det_inactives.html'],'ACTIVE_SOURCE_MISSING:'+player)
    require('Cole Bishop' in texts['buf_inactives.html'],'BISHOP_SOURCE_MISSING')
    parent_names=['det_inactives.html','buf_inactives.html','det_injuries.html','buf_injuries.html','det_depth.html','buf_depth.html','games.csv']
    derived={'state':personnel,'parent_source_receipts':[rr[n] for n in parent_names],'extraction':'SOURCE_TEXT_ASSERTED_HUMAN_REVIEWED_FIELDS; NO_INVENTED_IMPACT_COEFFICIENTS'}
    write_once(out/'personnel_derived.json',derived)
    stamp=max(rr[n]['retrieved_at_utc'] for n in parent_names)
    pers={'event_id':EVENT,'source':'derived:personnel_derived.json; parents are retained official bytes','source_sha256':sha(out/'personnel_derived.json'),'retrieved_at_utc':stamp,'available_by_utc':stamp,'published_at_utc':None,**derived}
    travel={**meta('games.csv'),'state':{'home_team':'BUF','away_team':'DET','actual_itinerary':None,'departure':None,'arrival':None,'scope':'FITTED_HOME_AIRPORT_PROXY_ONLY; NO_VERIFIED_TRAVEL_ITINERARY'}}
    context={'weather':wx,'rest':rest,'personnel':pers,'travel':travel,'assimilation':{**meta('play_by_play_2026.csv'),**evidence}}
    state_check=require_assimilation(base,context,event,now())
    write_once(out/'event.json',event);write_once(out/'base.json',base);write_once(out/'context.json',context);write_once(out/'state_validation.json',state_check)
    # Captured provider market columns stay outside the football-only package.
    cols=['away_moneyline','home_moneyline','spread_line','away_spread_odds','home_spread_odds','total_line','under_odds','over_odds']
    market={'event_id':EVENT,'source_receipt':rr['games.csv'],'values':{c:None if pd.isna(g[c]) else float(g[c]) for c in cols},'scope':'PROVIDER_SCHEDULE_METADATA_ONLY; BOOK_AND_QUOTE_TIME_UNKNOWN','model_input':False,'action_authority':False}
    write_once(out/'market_quarantined.json',market)
    write_once(out/'preparation.json',{'created_at_utc':now(),'event_id':EVENT,'week1_finals':len(week),'qb_aggregates':len(evidence['qb_update']['aggregates']),'source_failures':[r for r in receipts if r['status']!='captured'],'model_artifact_sha256':digest(model),'current_data_status':'SOURCE_BOUND_RESEARCH_PACKAGE_COMPONENTS_READY','official_release_eligible':False,'action_authority':False,'dose':0.0})
    print(json.dumps({'status':'PREPARED_NOT_FORECASTED','event':event,'assimilation':state_check,'qb_update_aggregate_count':len(evidence['qb_update']['aggregates'])},indent=2))
if __name__=='__main__':main()
