#!/usr/bin/env python3
"""Refresh the selected WNBA state from independently confirmed official boxes."""
import argparse,datetime as dt,hashlib,json,os,sys,tempfile
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from models.current.common import save
from models.nfl.contextual.recovered_inference import digest,utc
from scripts.verify_nfl_weekly_sources import manifest
from scripts.refresh_all_sports import wnba_box
from pipelines.cards.selection import select


def prepare(source,current,output):
    from harness import wnba_model_v1 as W
    from harness.wnba_refresh_espn import duplicate_content_violations
    manifest(source,'manifest.json');manifest(current,'manifest.json')
    report=json.loads((source/'report.json').read_text());now=dt.datetime.now(dt.timezone.utc)
    receipts=[r for r in report['sources'] if r['league']=='wnba' and r['status']=='CAPTURED']
    binary_receipts=[{'source':r['url'],'sha256':r['sha256'],'fetched_at_utc':r['retrieved_at_utc']} for r in report['binary_sources'] if r['name'].startswith('wnba_') and r['status']=='CAPTURED']
    # Supply current 2026 files to frozen readers; all historical source bytes stay untouched.
    with tempfile.TemporaryDirectory() as tmp:
        stage=Path(tmp)
        original=ROOT/W.STAGE
        for f in original.rglob('*.parquet'):
            target=stage/f.relative_to(original);target.parent.mkdir(parents=True,exist_ok=True);target.symlink_to(f)
        for rel,src in [('WNBA_OFFICIAL/wnba_stats/schedules/parquet/wnba_stats_schedule_2026.parquet','wnba_WNBA_OFFICIAL_results_long.parquet'),('ESPN/wnba/team_box/parquet/team_box_2026.parquet','wnba_ESPN_team_box.parquet')]:
            target=stage/rel;target.unlink();target.symlink_to((source/'binary'/src).resolve())
        with patch.object(W,'STAGE',str(stage)):games=W.build_games()
    # Current ESPN observations serve as the independent score/box confirmation.
    espn={}
    cr=json.loads((current/'report.json').read_text())
    for r in cr['sources']:
        if r['league']=='wnba' and r['kind']=='event_summary' and r['status']=='CAPTURED':
            try:g=wnba_box(current/r['raw_path'],{'retrieved_at':r['retrieved_at_utc'],'sha256':r['raw_sha256'],'source_available_at':None})
            except ValueError as e:
                if str(e) in {'WNBA_NOT_FINAL','WNBA_NON_REGULAR_SEASON'}:continue
                raise
            espn[(g['date'],g['home'],g['away'],g['hpts'],g['apts'])]=g
    existing={g['gid'] for g in games};added=[]
    mapping={'fgm':'fieldGoalsMade','fga':'fieldGoalsAttempted','fg3m':'threePointersMade','fta':'freeThrowsAttempted','oreb':'reboundsOffensive','tov':'turnoversTotal'}
    for r in receipts:
        if r['kind']!='official_boxscore':continue
        g=json.loads((source/r['raw_path']).read_text())['game'];gid=g['gameId']
        if not gid.startswith('10226') or g['gameStatus']!=3:raise ValueError('OFFICIAL_REGULAR_FINAL_REQUIRED')
        if utc(g['gameTimeUTC'])>=utc(r['retrieved_at_utc']):raise ValueError('FUTURE_FINAL')
        date=utc(g['gameTimeUTC']).astimezone(ZoneInfo('America/New_York')).date().isoformat()
        row={'gid':gid,'season':2026,'date':date,'utc_instant':g['gameTimeUTC'],'source_sha256':r['raw_sha256']}
        for side,slot in [('home','H'),('away','A')]:
            tm=g[side+'Team'];team=W._xw(tm['teamTricode'],2026);stats=tm['statistics'];score=int(tm['score'])
            row[side]=team;row['hpts' if side=='home' else 'apts']=score
            row[slot]={'team':team,'pts':score,**{k:int(stats[v]) for k,v in mapping.items()}}
            if 2*int(stats['fieldGoalsMade'])+int(stats['threePointersMade'])+int(stats['freeThrowsMade'])!=score:raise ValueError('OFFICIAL_BOX_SCORE_MISMATCH')
        key=(date,row['home'],row['away'],row['hpts'],row['apts'])
        if key not in espn:raise ValueError('INDEPENDENT_FINAL_CONFIRMATION_MISSING:'+gid)
        e=espn[key]
        for slot in ('H','A'):
            for k in mapping:
                if row[slot][k]!=e[slot][k]:raise ValueError('INDEPENDENT_BOX_CONFLICT:'+gid+':'+slot+':'+k)
        if gid in existing:
            old=next(x for x in games if x['gid']==gid)
            if any(old[k]!=row[k] for k in ('date','home','away','hpts','apts')) or any(old[slot][k]!=row[slot][k] for slot in ('H','A') for k in mapping):
                raise ValueError('EXISTING_OFFICIAL_GAME_REVISION:'+gid)
            continue  # Same ET-date game independently reconfirmed, never applied twice.
        existing.add(gid);added.append(row)
    games+=added;games.sort(key=lambda g:(g['date'],g['gid']))
    if duplicate_content_violations(games):raise ValueError('DUPLICATE_GAME_CONTENT')
    today=now.astimezone(ZoneInfo('America/New_York')).date().isoformat()
    if any(g['date']>=today for g in games):raise ValueError('SAME_DAY_OUTCOME_REQUIRES_SEPARATE_CUTOFF')
    official_rec=next(r for r in receipts if r['kind']=='official_schedule')
    official=json.loads((source/official_rec['raw_path']).read_text())['leagueSchedule']
    finals={str(g['gameId']) for d in official['gameDates'] for g in d['games'] if str(g['gameId']).startswith('10226') and g['gameStatus']==3}
    covered={g['gid'] for g in games if g['season']==2026}
    if covered!=finals:raise ValueError('SEASON_FINAL_CENSUS_MISMATCH:'+str(sorted(finals-covered)))
    rows,ts,lg=W.make_rows(games);model=W.fit_full(rows)
    if str(official['seasonYear'])!='2026':raise ValueError('OFFICIAL_SCHEDULE_SEASON')
    events=[];dates={(now.astimezone(ZoneInfo('America/Los_Angeles')).date()+dt.timedelta(days=n)).isoformat() for n in range(8)}
    for d in official['gameDates']:
        for g in d['games']:
            if not str(g['gameId']).startswith('10226'):continue
            start=utc(g['gameDateTimeUTC']);day=start.astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat()
            if not now<=start<=now+dt.timedelta(days=7):continue
            dates.add(day)
            events.append({'event_id':'WNBA:'+str(g['gameId']),'home_team':W._xw(g['homeTeam']['teamTricode'],2026),'away_team':W._xw(g['awayTeam']['teamTricode'],2026),'start_time_utc':start.isoformat(),'slate_date':day,'season':2026,'season_type':2})
    fitted={k:v.tolist() for k,v in model.items()};state=[{'season':s,'team':t,'values':v} for (s,t),v in sorted(ts.s.items())]
    pkg={'schema':'sports.current_research_package.v1','league':'wnba','model_id':select('wnba')['default_model_id'],'captured_at_utc':now.isoformat(),'training_cutoff_utc':now.isoformat(),'ttl_hours':6,'covered_dates':sorted(dates),'events':events,'fitted_model':fitted,'team_state':state,'league_state':list(lg),'consumed_game_ids':sorted(g['gid'] for g in games),'model_sha256':digest({'model':fitted,'state':state,'league':list(lg)}),'data_grade':'OFFICIAL_PLUS_ESPN_BOX_CONFIRMATION','model_lineage':{'frozen_fitter':'harness/wnba_model_v1.py','training_rows':len(rows),'historical_games':len(games),'current_season_games':len(covered),'current_final_census_verified':True,'new_official_boxes':len(added)},'source_fetches':binary_receipts+[{'source':r.get('url'),'sha256':r.get('raw_sha256'),'fetched_at_utc':r['retrieved_at_utc']} for r in receipts]+[{'source':'retained current ESPN raw evidence','sha256':hashlib.sha256((current/'manifest.json').read_bytes()).hexdigest(),'fetched_at_utc':cr['created_at_utc']}],'limitations':['NO_PLAYER_AVAILABILITY_TRANSFORM_IN_SELECTED_MODEL','NO_WAGERING_AUTHORITY'],'action_authority':False,'code_pins':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['harness/wnba_model_v1.py','models/current/common.py','models/current/wnba.py','pipelines/cards/adapters/wnba.py']}}
    save(output/'wnba/package.json',pkg);print(json.dumps(pkg['model_lineage']));return pkg

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--current',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();prepare(a.source,a.current,a.output)
