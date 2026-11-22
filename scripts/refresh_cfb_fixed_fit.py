#!/usr/bin/env python3
"""Refresh CFB team state with retained fitted heads, then use the native card runner.

No fit or market calculation is performed. The parent package and captured source
tree remain immutable. Output is an independently identified research package.
"""
from __future__ import annotations
import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def refresh(repository, source, parent_path, output, slate_date):
    import numpy as np
    import pandas as pd
    repository=Path(repository).resolve()
    source=Path(source).resolve()
    parent_path=Path(parent_path).resolve()
    output=Path(output).resolve()
    sys.path.insert(0,str(repository))
    from harness import cfb_v1_port as C
    from models.current.cfb import feature_row
    from models.current.common import save
    from models.nfl.contextual.recovered_inference import digest,utc
    from scripts.verify_nfl_weekly_sources import manifest
    from pipelines.cards.selection import select

    output.mkdir(parents=True,exist_ok=False)
    now=dt.datetime.now(dt.timezone.utc)
    execution={'schema':'cfb.fixed_fit_state_refresh.execution.v1',
        'started_at_utc':now.isoformat(),'slate_date':slate_date,
        'repository':str(repository),'source':str(source),'parent_package':str(parent_path),
        'refresh_code_sha256':sha(__file__),'fit_executed':False,'action_authority':False}
    try:
        date=dt.date.fromisoformat(slate_date)
        today=now.astimezone(ZoneInfo('America/Los_Angeles')).date()
        if not 0 <= (date-today).days < 7:
            raise ValueError('TARGET_OUTSIDE_CURRENT_SEVEN_DAY_WINDOW')
        parent=json.loads(parent_path.read_text())
        if parent.get('schema')!='sports.current_research_package.v1' or parent.get('league')!='cfb' or parent.get('action_authority') is not False:
            raise ValueError('RETAINED_CFB_RESEARCH_PACKAGE_REQUIRED')
        if parent['model_id']!=select('cfb',week=2,division='FBS_VS_FBS')['default_model_id']:
            raise ValueError('CURRENT_SELECTED_PARENT_REQUIRED')
        if utc(parent['training_cutoff_utc'])>now:
            raise ValueError('FUTURE_FITTED_PARENT')
        expected=digest({'model':parent['fitted_model'],'state':parent['team_state'],'parameters':parent['parameters']})
        if parent['model_sha256']!=expected:
            raise ValueError('PARENT_STATE_DIGEST_MISMATCH')
        for name,pin in parent['code_pins'].items():
            if sha(repository/name)!=pin:
                raise ValueError('PARENT_PROCEDURE_DRIFT:'+name)
        manifest(source,'manifest.json')
        source_manifest=json.loads((source/'manifest.json').read_text())
        historical_paths=sorted((source/'binary/schedules/parquet').glob('*.parquet'))
        if not historical_paths:
            raise ValueError('PINNED_HISTORICAL_SCHEDULES_REQUIRED')
        consumed_sources=[source/'report.json',source/'binary/cfb_current.parquet',*historical_paths]
        missing=[str(path.relative_to(source)) for path in consumed_sources
                 if str(path.relative_to(source)) not in source_manifest]
        if missing:
            raise ValueError('CONSUMED_SOURCE_MISSING_FROM_MANIFEST:'+','.join(missing))
        records=json.loads((source/'report.json').read_text())['binary_sources']
        current_records=[r for r in records if r.get('name')=='cfb_current.parquet' and r.get('status')=='CAPTURED']
        if len(current_records)!=1:
            raise ValueError('UNIQUE_CURRENT_CFB_SOURCE_REQUIRED')
        current_record=current_records[0]
        current_path=source/'binary/cfb_current.parquet'
        if sha(current_path)!=current_record['sha256']:
            raise ValueError('CURRENT_CFB_SOURCE_HASH')
        if not 0 <= (now-utc(current_record['retrieved_at_utc'])).total_seconds() <= 6*3600:
            raise ValueError('CURRENT_CFB_SOURCE_STALE_OR_FUTURE')
        parameters=copy.deepcopy(parent['parameters'])
        historical=pd.concat([pd.read_parquet(p) for p in historical_paths],ignore_index=True)
        historical=historical[historical.completed&historical.home_points.notna()&historical.away_points.notna()].copy()
        historical['kick']=pd.to_datetime(historical.start_date,utc=True,format='mixed')
        historical=historical.sort_values(['kick','game_id'],kind='mergesort').reset_index(drop=True)
        recovered=C.build_state(historical,**parameters)
        frozen=pd.read_parquet(repository/'data/cfb/model/cfb_v1_features.parquet')
        if recovered.game_id.tolist()!=frozen.game_id.tolist() or not np.allclose(recovered[C.FEATURES],frozen[C.FEATURES],equal_nan=True,rtol=0,atol=1e-10):
            raise ValueError('FROZEN_HISTORICAL_FEATURE_REPLAY_MISMATCH')
        current=pd.read_parquet(current_path)
        current['kick']=pd.to_datetime(current.start_date,utc=True,format='mixed')
        current['slate_date']=current.kick.dt.tz_convert('America/Los_Angeles').dt.date.astype(str)
        target=current[(current.slate_date==slate_date)&(~current.completed)&(current.kick>now)&
            (current.home_division=='fbs')&(current.away_division=='fbs')].copy()
        if target.empty:
            raise ValueError('NO_ELIGIBLE_PRESTART_FBS_EVENTS_ON_REQUESTED_DATE')
        if (target.week<2).any():
            raise ValueError('REGISTERED_WEEK1_ARM_REQUIRED')
        freeze_week=int(target.week.min())
        finals=current[current.completed&current.home_points.notna()&current.away_points.notna()&(current.week<freeze_week)].copy()
        if (finals.kick>=now).any():
            raise ValueError('FUTURE_FINAL')
        allgames=pd.concat([historical,finals],ignore_index=True).sort_values(['kick','game_id'],kind='mergesort').reset_index(drop=True)
        if allgames.game_id.duplicated().any():
            raise ValueError('DUPLICATE_CFB_ID')
        old_ids=set(parent['consumed_game_ids']);new_ids=set(allgames.game_id.astype(str))
        if old_ids-new_ids:
            raise ValueError('PARENT_CONSUMED_GAME_LOST_OR_TARGET_PRECEDES_PARENT')
        state={};previous=sys.getprofile()
        def capture(frame,event,arg):
            if frame.f_code is C.build_state.__code__ and event=='return':
                for key in ('elo','ewpf','ewpa','ewm','last','last_season'):
                    state[key]=copy.deepcopy(frame.f_locals[key])
        try:
            sys.setprofile(capture)
            C.build_state(allgames,**parameters)
        finally:
            sys.setprofile(previous)
        state['last']={k:v.isoformat() for k,v in state['last'].items()}
        events=[]
        for row in target.to_dict('records'):
            event={'event_id':'CFB:'+str(row['game_id']),'home_team':row['home_team'],
                'away_team':row['away_team'],'start_time_utc':row['kick'].isoformat(),
                'slate_date':slate_date,'season':int(row['season']),'week':int(row['week']),
                'division_scope':'FBS_VS_FBS','neutral_site':bool(row['neutral_site']),
                'conference_game':bool(row['conference_game'])}
            probe=C.build_state(pd.concat([allgames,pd.DataFrame([{**row,'home_points':0,'away_points':0}])],ignore_index=True),**parameters).iloc[-1]
            features=feature_row(state,event,parameters)
            if not np.allclose([np.nan if features[k] is None else features[k] for k in C.FEATURES],probe[C.FEATURES].astype(float),equal_nan=True,rtol=0,atol=1e-10):
                raise ValueError('CURRENT_FEATURE_REPLAY_MISMATCH')
            events.append(event)
        fitted=copy.deepcopy(parent['fitted_model'])
        receipt={**execution,'schema':'cfb.fixed_fit_state_refresh.v1','parent_package_sha256':sha(parent_path),
            'parent_fit_sha256':digest(parent['fitted_model']),'current_fit_sha256':digest(fitted),
            'fitted_heads_unchanged':digest(parent['fitted_model'])==digest(fitted),
            'parent_training_cutoff_utc':parent['training_cutoff_utc'],
            'parent_training_rows':parent['model_lineage'].get('training_rows'),
            'historical_rows_replayed':len(recovered),'current_finals_assimilated':len(finals),
            'state_freeze_before_week':freeze_week,'newly_consumed_game_ids':sorted(new_ids-old_ids),
            'target_events':len(events),'state_sha256':digest(state)}
        package={**parent,'captured_at_utc':now.isoformat(),'covered_dates':[slate_date],
            'events':events,'team_state':state,'fitted_model':fitted,'parameters':parameters,
            'consumed_game_ids':allgames.game_id.astype(str).tolist(),
            'model_sha256':digest({'model':fitted,'state':state,'parameters':parameters}),
            'model_lineage':{**parent['model_lineage'],'current_finals_assimilated':len(finals),
                'current_feature_replay_events':len(events),'fit_reused_without_refit':True,
                'parent_package_sha256':sha(parent_path),'fit_sha256':digest(fitted),
                'state_refresh_receipt_sha256':digest(receipt)},
            'source_fetches':[{'source':r['url'],'sha256':r['sha256'],'fetched_at_utc':r['retrieved_at_utc']}
                for r in records if r.get('status')=='CAPTURED' and 'cfb' in r.get('name','')],
            'limitations':parent['limitations']+['RETAINED_FITTED_HEADS_WITH_CURRENT_STATE_REFRESH'],
            'fixed_fit_state_refresh':receipt}
        save(output/'cfb/package.json',package)
        save(output/'state_refresh_receipt.json',receipt)
        execution.update(status='COMPLETED',events=len(events),model_id=package['model_id'],
            package_sha256=sha(output/'cfb/package.json'),parent_fit_sha256=digest(fitted),
            state_sha256=digest(state),finished_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        save(output/'execution_receipt.json',execution)
        return execution
    except Exception as exc:
        execution.update(status='BLOCKED',error_type=type(exc).__name__,reason=str(exc),
            finished_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        save(output/'failure.json',execution)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository',required=True,type=Path)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--parent-package',required=True,type=Path)
    parser.add_argument('--date',required=True)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(refresh(args.repository,args.source,args.parent_package,args.output,args.date),indent=2))


if __name__=='__main__':main()

