#!/usr/bin/env python3
"""Prove selected-model state consumption, without waiving the wider CFB gate."""
import argparse, copy, datetime as dt, hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
from models.current.cfb import feature_row
from models.current.linear import predict
from models.current.common import save
from models.nfl.contextual.recovered_inference import digest
from scripts.verify_nfl_weekly_sources import manifest


def verify(source,package,output):
    from harness import cfb_v1_port as C
    manifest(source,'manifest.json');p=json.loads(package.read_text())
    report=json.loads((source/'report.json').read_text())
    receipts=[r for r in report['binary_sources']if 'current'in r['name']]
    if len(receipts)!=1:raise ValueError('CURRENT_SOURCE_RECEIPT_REQUIRED')
    h=pd.concat([pd.read_parquet(f)for f in sorted((source/'binary/schedules/parquet').glob('*.parquet'))],ignore_index=True)
    h=h[h.completed & h.home_points.notna() & h.away_points.notna()].copy()
    c=pd.read_parquet(source/'binary/cfb_current.parquet');c['kick']=pd.to_datetime(c.start_date,utc=True,format='mixed')
    cutoff=pd.Timestamp(p['training_cutoff_utc']);pending=c[(~c.completed)&(c.kick>cutoff)&(c.kick<cutoff+pd.Timedelta(days=7))]
    if pending.empty:raise ValueError('FREEZE_WEEK_UNRESOLVED')
    wk=int(pending.week.min());finals=c[c.completed&c.home_points.notna()&c.away_points.notna()&(c.week<wk)].copy()
    if not (finals.kick<cutoff).all():raise ValueError('FUTURE_FINAL')
    rows=pd.concat([h,finals],ignore_index=True);rows['kick']=pd.to_datetime(rows.start_date,utc=True,format='mixed');rows=rows.sort_values(['kick','game_id'],kind='stable')
    if rows.game_id.duplicated().any():raise ValueError('DUPLICATE_RESULT')
    if rows.game_id.astype(str).tolist()!=p['consumed_game_ids']:raise ValueError('CONSUMED_RESULT_SET_MISMATCH')
    def state(data):
        captured={};old=sys.getprofile()
        def capture(frame,event,arg):
            if frame.f_code is C.build_state.__code__ and event=='return':
                for k in ('elo','ewpf','ewpa','ewm','last','last_season'):captured[k]=copy.deepcopy(frame.f_locals[k])
        try:sys.setprofile(capture);C.build_state(data,**p['parameters'])
        finally:sys.setprofile(old)
        captured['last']={k:v.isoformat()for k,v in captured['last'].items()};return captured
    after=state(rows);before=state(rows[rows.season<2026])
    if digest(after)!=digest(p['team_state']):raise ValueError('STATE_REPLAY_MISMATCH')
    if digest({'model':p['fitted_model'],'state':after,'parameters':p['parameters']})!=p['model_sha256']:raise ValueError('MODEL_STATE_HASH_MISMATCH')
    changes=[]
    for e in p['events']:
        new=feature_row(after,e,p['parameters']);old=feature_row(before,e,p['parameters'])
        vals=[new[k]for k in p['feature_names']];prior=[old[k]for k in p['feature_names']]
        actual=predict(p['fitted_model']['winner'],vals);control=predict(p['fitted_model']['winner'],prior)
        changes.append({'event_id':e['event_id'],'loaded_feature_values':new,'feature_sha256':digest(new),'consumed_state_sha256':p['model_sha256'],'changed_features':[k for k in new if new[k]!=old[k]],'current_state_p_home':actual,'historical_only_state_same_head_p_home':control,'p_delta':actual-control})
    result={'scope':'SELECTED_STATE_RESULT_SET_REPLAY_AND_NUMERICAL_INPUT_BINDING','status':'PASS','created_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'source_manifest_sha256':hashlib.sha256((source/'manifest.json').read_bytes()).hexdigest(),'package_sha256':hashlib.sha256(package.read_bytes()).hexdigest(),'parent_team_state_sha256':digest(before),'successor_team_state_sha256':digest(after),'eligible_current_finals':len(finals),'excluded_current_week':wk,'eligible_current_ids':finals.game_id.astype(str).tolist(),'event_traces':changes,'broader_assimilation_acceptance':'HOLD_ROSTER_TRANSFER_DEPTH_IDENTITY_AND_PROVIDER_SCHEDULE_LINEAGE','historical_source_publication_time':'UNPROVEN','official_release_eligible':False,'action_authority':False}
    save(output,result);return result


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--source',type=Path,required=True);a.add_argument('--package',type=Path,required=True);a.add_argument('--output',type=Path,required=True);p=a.parse_args();r=verify(p.source,p.package,p.output);print(json.dumps({k:v for k,v in r.items()if k not in ['event_traces','eligible_current_ids']},indent=2))
