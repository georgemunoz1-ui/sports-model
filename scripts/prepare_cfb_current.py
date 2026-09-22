#!/usr/bin/env python3
"""Reproduce the incumbent historical features, then assimilate captured 2026 finals."""
import argparse,copy,datetime as dt,hashlib,json,sys
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression,Ridge
from models.current.common import save
from models.current.linear import pack,predict
from models.current.cfb import feature_row
from models.nfl.contextual.recovered_inference import digest,utc
from scripts.verify_nfl_weekly_sources import manifest
from pipelines.cards.selection import select


def prepare(source,output):
    from harness import cfb_v1_port as C
    manifest(source,'manifest.json');now=dt.datetime.now(dt.timezone.utc)
    frames=[pd.read_parquet(p) for p in sorted((source/'binary/schedules/parquet').glob('*.parquet'))]
    hist=pd.concat(frames,ignore_index=True);hist=hist[hist.completed&hist.home_points.notna()&hist.away_points.notna()].copy()
    hist['kick']=pd.to_datetime(hist.start_date,utc=True,format='mixed');hist=hist.sort_values(['kick','game_id'],kind='mergesort').reset_index(drop=True)
    params={'k':28.,'hfa':55.,'regress':.75,'alpha':.4}
    recovered=C.build_state(hist,**params);frozen=pd.read_parquet(ROOT/'data/cfb/model/cfb_v1_features.parquet')
    if recovered.game_id.tolist()!=frozen.game_id.tolist() or not np.allclose(recovered[C.FEATURES],frozen[C.FEATURES],equal_nan=True,rtol=0,atol=1e-10):
        raise ValueError('FROZEN_CFB_FEATURE_REPLAY_MISMATCH')
    current=pd.read_parquet(source/'binary/cfb_current.parquet');current['kick']=pd.to_datetime(current.start_date,utc=True,format='mixed')
    finals=current[current.completed&current.home_points.notna()&current.away_points.notna()].copy()
    if (finals.kick>=now).any():raise ValueError('FUTURE_FINAL')
    pending=current[(~current.completed)&(current.kick>now)&(current.kick<now+dt.timedelta(days=7))]
    if len(pending):
        first_week=int(pending.week.min())
        finals=finals[finals.week<first_week].copy()  # Freeze before the forecast week, including midweek refreshes.
    allgames=pd.concat([hist,finals],ignore_index=True).sort_values(['kick','game_id'],kind='mergesort').reset_index(drop=True)
    if allgames.game_id.duplicated().any():raise ValueError('DUPLICATE_CFB_ID')
    captured={};previous=sys.getprofile()
    def capture(frame,event,arg):
        if frame.f_code is C.build_state.__code__ and event=='return':
            for k in ('elo','ewpf','ewpa','ewm','last','last_season'):captured[k]=copy.deepcopy(frame.f_locals[k])
    try:
        sys.setprofile(capture);features=C.build_state(allgames,**params)
    finally:sys.setprofile(previous)
    captured['last']={k:v.isoformat() for k,v in captured['last'].items()}
    cohort=features[(features.home_division=='fbs')&(features.away_division=='fbs')]
    clf=make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),LogisticRegression(C=1,max_iter=2000)).fit(cohort[C.FEATURES],cohort.home_win)
    reg=make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),Ridge(alpha=1)).fit(cohort[C.FEATURES],cohort.home_margin)
    fitted={'winner':pack(clf,'logistic'),'margin':pack(reg,'linear')}
    events=[]
    upcoming=current[(~current.completed)&(current.kick>now)&(current.kick<now+dt.timedelta(days=7))&(current.home_division=='fbs')&(current.away_division=='fbs')]
    for row in upcoming.to_dict('records'):
        e={'event_id':'CFB:'+str(row['game_id']),'home_team':row['home_team'],'away_team':row['away_team'],'start_time_utc':row['kick'].isoformat(),
            'slate_date':row['kick'].astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat(),'season':int(row['season']),'week':int(row['week']),
            'division_scope':'FBS_VS_FBS','neutral_site':bool(row['neutral_site']),'conference_game':bool(row['conference_game'])}
        # Validate the portable state against the untouched original transform.
        test=dict(row,home_points=0,away_points=0);probe=C.build_state(pd.concat([allgames,pd.DataFrame([test])],ignore_index=True),**params).iloc[-1]
        x=feature_row(captured,e,params)
        if not np.allclose([np.nan if x[k] is None else x[k] for k in C.FEATURES],probe[C.FEATURES].astype(float),equal_nan=True,rtol=0,atol=1e-10):raise ValueError('CURRENT_FEATURE_REPLAY_MISMATCH')
        events.append(e)
    if any(e['week']==1 for e in events):raise ValueError('USE_REGISTERED_WEEK1_SELECTED_ARM')
    report=json.loads((source/'report.json').read_text());receipts=[r for r in report['binary_sources'] if 'cfb' in r['name'] and r['status']=='CAPTURED']
    pkg={'schema':'sports.current_research_package.v1','league':'cfb','model_id':select('cfb',week=2,division='FBS_VS_FBS')['default_model_id'],'captured_at_utc':now.isoformat(),'training_cutoff_utc':now.isoformat(),'ttl_hours':6,'covered_dates':[(now.astimezone(ZoneInfo('America/Los_Angeles')).date()+dt.timedelta(days=i)).isoformat() for i in range(7)],'events':events,'parameters':params,'fitted_model':fitted,'team_state':captured,'feature_names':C.FEATURES,'consumed_game_ids':allgames.game_id.astype(str).tolist(),'model_sha256':digest({'model':fitted,'state':captured,'parameters':params}),'data_grade':'PINNED_HISTORY_PLUS_CURRENT_FBS_SCHEDULE_FINALS','model_lineage':{'historical_feature_rows_replayed':len(recovered),'exact_historical_replay':True,'current_finals_assimilated':len(finals),'training_rows':len(cohort),'current_feature_replay_events':len(events)},'source_fetches':[{'source':r['url'],'sha256':r['sha256'],'fetched_at_utc':r['retrieved_at_utc']} for r in receipts],'limitations':['FBS_VS_FBS_ONLY','NO_CURRENT_QB_OR_PERSONNEL_TRANSFORM_IN_SELECTED_ARM','NO_WAGERING_AUTHORITY'],'action_authority':False,'code_pins':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['harness/cfb_v1_port.py','models/current/common.py','models/current/linear.py','models/current/cfb.py','pipelines/cards/adapters/cfb.py']}}
    save(output/'cfb/package.json',pkg);print(json.dumps(pkg['model_lineage']));return pkg

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();prepare(a.source,a.output)
