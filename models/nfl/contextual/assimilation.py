"""Immutable source assimilation with explicit failures and weekly state semantics."""
from __future__ import annotations
import copy, datetime as dt, hashlib, json
from dataclasses import asdict
from pathlib import Path
import numpy as np
import pandas as pd
from . import base_features as bf
from .recovered_inference import digest, utc, predict

PARSER_VERSION='nfl.pbp.assimilation.v1'
PBP_REQUIRED=['game_id','play_id','home_team','away_team','season','week','qtr',
 'quarter_seconds_remaining','total_home_score','total_away_score','down','play_type',
 'qb_kneel','qb_spike','no_play','wp','posteam','defteam','epa','success','yards_gained',
 'sack','interception','fumble_lost','game_seconds_remaining']

def write_once(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f: json.dump(value,f,indent=2,allow_nan=False)

def ingest_pbp_snapshot(path, receipt, archive):
    raw=Path(path).read_bytes();sha=hashlib.sha256(raw).hexdigest()
    if sha!=receipt['sha256']: raise ValueError('RAW_HASH_MISMATCH')
    utc(receipt['retrieved_at_utc'])
    if not receipt.get('source_url'):raise ValueError('SOURCE_REQUIRED')
    folder=Path(archive)/sha;folder.mkdir(parents=True,exist_ok=True)
    destination=folder/'raw.csv'
    if destination.exists():
        if destination.read_bytes()!=raw: raise ValueError('IMMUTABLE_SNAPSHOT_CONFLICT')
    else:
        with destination.open('xb') as f:f.write(raw)
    meta={**receipt,'snapshot_id':sha,'parser_version':PARSER_VERSION,'local_raw_path':str(destination)}
    receipt_path=folder/(digest(meta)+'.receipt.json')
    if not receipt_path.exists():write_once(receipt_path,meta)
    frame=pd.read_csv(destination,low_memory=False)
    if 'no_play' not in frame and 'play_type' in frame:
        frame['no_play']=frame.play_type.astype('string').str.lower().eq('no_play').fillna(False).astype('int8')
        meta['schema_adapter']="no_play := 1[lower(play_type) == 'no_play']; existing frozen loader convention"
    return frame,meta

def reconcile_game_coverage(pbp, schedule, receipt, cutoff, previous_finals=None):
    """Schedule contains canonical completed AND pending games, never just PBP IDs."""
    missing=sorted(set(PBP_REQUIRED)-set(pbp.columns)); rows=[]
    late=utc(receipt['retrieved_at_utc'])>utc(cutoff)
    for key in ['source_published_at_utc','available_at_utc']:
        if receipt.get(key) and utc(receipt[key])>utc(cutoff):late=True
    for game in schedule.to_dict('records'):
        gid=str(game['game_id']); expected=bool(pd.notna(game['home_score']) and pd.notna(game['away_score']))
        part=pbp[pbp.game_id.astype(str)==gid].copy() if 'game_id' in pbp else pd.DataFrame()
        reasons=[];status='complete';half=None
        if not expected: status='awaiting_finality'; reasons.append('SCHEDULE_NOT_FINAL')
        if expected and part.empty:status='partial';reasons.append('MISSING_COMPLETED_GAME')
        if expected and missing:status='partial';reasons.append('MISSING_COLUMNS:'+','.join(missing))
        if expected and not part.empty and not missing:
            for key in ['home_team','away_team','season','week']:
                values=part[key].dropna().unique()
                if len(values)!=1 or str(values[0])!=str(game[key]):status='invalid_binding';reasons.append('BINDING:'+key)
            ids=pd.to_numeric(part.play_id,errors='coerce')
            if ids.isna().any() or ids.duplicated().any():status='conflicting';reasons.append('DUPLICATE_OR_INVALID_PLAY_ID')
            part=part.assign(play_id=ids)
            if 'order_sequence' in part:
                seq=pd.to_numeric(part.order_sequence,errors='coerce')
                if seq.isna().any() or seq.duplicated().any():status='conflicting';reasons.append('INVALID_ORDER_SEQUENCE')
                part=part.assign(order_sequence=seq).sort_values('order_sequence')
            else:part=part.sort_values('play_id')
            periods=pd.to_numeric(part.qtr,errors='coerce')
            if periods.isna().any() or (periods.diff().dropna()<0).any():status='conflicting';reasons.append('PERIOD_SEQUENCE')
            increases=part.groupby('qtr').quarter_seconds_remaining.diff()>0
            if increases.any():status='conflicting';reasons.append('CLOCK_INCREASE_REQUIRES_REVISION_REVIEW')
            last=part[['total_home_score','total_away_score']].dropna()
            if last.empty or tuple(last.iloc[-1])!=(game['home_score'],game['away_score']):status='conflicting';reasons.append('FINAL_SCORE_MISMATCH')
            q2=part[part.qtr==2][['total_home_score','total_away_score','quarter_seconds_remaining']].dropna()
            if q2.empty or q2.iloc[-1].quarter_seconds_remaining!=0:status='partial' if status=='complete' else status;reasons.append('HALFTIME_BOUNDARY_MISSING')
            else:half={'home':int(q2.iloc[-1].total_home_score),'away':int(q2.iloc[-1].total_away_score)}
            candidates=part[part.play_type.isin(['run','pass']) & part.down.isin([1,2]) & (part.no_play.fillna(0)==0) & (part.qb_kneel.fillna(0)==0) & (part.qb_spike.fillna(0)==0)]
            metric_missing=int(candidates[['epa','wp','success','yards_gained','posteam','defteam']].isna().any(axis=1).sum())
            if metric_missing:status='partial' if status=='complete' else status;reasons.append('CRITICAL_PLAY_METRICS_MISSING:'+str(metric_missing))
            if previous_finals and gid in previous_finals and previous_finals[gid]!=[int(game['home_score']),int(game['away_score'])]:
                status='conflicting';reasons.append('FINAL_SCORE_REVISION; PRIOR_STATE_QUARANTINED_BY_REFERENCE')
        if late:status='stale';reasons.append('SOURCE_AFTER_CUTOFF')
        rows.append({'game_id':gid,'expected_completed':expected,'coverage_status':status,'pregame_eligible':not late,
          'state_update_eligible':status=='complete','reason':reasons,'play_rows':len(part),'halftime_score':half,
          'overtime_observed':bool('qtr' in part and (part.qtr>4).any()),
          'prior_state_quarantine_required':any('REVISION' in r for r in reasons)})
    expected=[r for r in rows if r['expected_completed']]
    complete=bool(expected) and all(r['state_update_eligible'] for r in expected)
    all_week_final=all(r['expected_completed'] for r in rows)
    return {'schema':'nfl.pbp.coverage.v1','cutoff_utc':cutoff,'snapshot_id':receipt['snapshot_id'],
      'expected_completed_games':len(expected),'reconciled_completed_games':sum(r['state_update_eligible'] for r in expected),
      'completed_coverage_complete':complete,'weekly_state_update_eligible':complete and all_week_final,
      'weekly_policy':'batch_after_all_week_features; pending games prevent releasing next-week state',
      'unmatched_source_games':sorted(set(pbp.game_id.astype(str))-set(schedule.game_id.astype(str))) if 'game_id' in pbp else [],
      'rows':rows,'global_missing_columns':missing}

def build_scoring_and_play_attribution(pbp, coverage):
    out=[];scoring=[]
    for row in coverage['rows']:
        if not row['state_update_eligible']:continue
        p=pbp[pbp.game_id==row['game_id']].sort_values('order_sequence' if 'order_sequence' in pbp else 'play_id')
        prior={'home':0,'away':0}
        for play in p.to_dict('records'):
            for side in ['home','away']:
                score=play['total_'+side+'_score']
                if pd.isna(score):continue
                delta=int(score)-prior[side];prior[side]=int(score)
                if delta:
                    team=play[side+'_team'];kind=play.get('play_type')
                    if delta<0: category='score_correction'
                    elif kind in {'extra_point','field_goal'}:category=kind
                    elif kind in {'kickoff','punt'}:category='special_teams_return'
                    elif play.get('posteam')!=team:category='defensive_score'
                    elif kind in {'pass','run'}:category='offensive_score'
                    else:category='unclassified_requires_review'
                    scoring.append({'game_id':row['game_id'],'play_id':int(play['play_id']),'period':int(play['qtr']),
                      'team':team,'points':delta,'category':category,'play_type':kind if pd.notna(kind) else None,
                      'interception':bool(play.get('interception',0)==1),'fumble_lost':bool(play.get('fumble_lost',0)==1)})
        for team in [p.home_team.iloc[0],p.away_team.iloc[0]]:
            for kind in ['pass','run']:
                q=p[(p.posteam==team)&(p.play_type==kind)&(p.no_play.fillna(0)==0)]
                out.append({'game_id':row['game_id'],'team':team,'phase':kind,'plays':len(q),'epa_present':int(q.epa.notna().sum()),
                  'epa_sum':float(q.epa.sum()) if len(q) and q.epa.notna().all() else None,
                  'epa_per_play':float(q.epa.mean()) if len(q) and q.epa.notna().all() else None,
                  'scope':'all non-nullified phase plays; not recap facet attribution and not frozen neutral filter'})
    return {'phase_observations':out,'scoring_events':scoring,'attribution_scope':'scoreboard transitions; no invented EPA allocation to returns'}

def advance_states(states, games, pbp):
    """Reuse the frozen feature implementation, including its opportunity convention."""
    plays,audit=bf._qualifying_plays(pbp)
    next_states=copy.deepcopy(states)
    for team,(obs,n) in bf._weekly_observations(games,plays,states).items():
        next_states.setdefault(team,bf.TeamState()).update(obs,n)
    return next_states,audit

def serialize_states(states):return {team:asdict(state) for team,state in sorted(states.items())}

def trace_feature_effects_into_forecasts(prior, updated, request, params):
    """Technical counterfactual: only the frozen PBP-dependent feature path changes."""
    game=pd.Series(request);home=game.home_team;away=game.away_team
    before=bf._feature_row(game,prior[home],prior[away]);after=bf._feature_row(game,updated[home],updated[away])
    clean=lambda x:{k:(None if pd.isna(x[k]) else float(x[k])) for k in params['feature_names']}
    b=clean(before);a=clean(after);bp=predict(params,b)['prediction'];ap=predict(params,a)['prediction']
    changed={k:{'before':b[k],'after':a[k]} for k in a if b[k]!=a[k]}
    return {'event_id':request['game_id'],'evidence_type':'TECHNICAL_STATE_ASSIMILATION_REPLAY_NOT_PREDICTIVE_VALIDATION',
      'model_id':params.get('model_id'),'parameter_sha256':digest(params),'before_feature_hash':digest(b),'after_feature_hash':digest(a),'changed_features':changed,
      'forecast_before':bp,'forecast_after':ap,'forecast_delta':{k:ap[k]-bp[k] for k in bp},
      'state_before_sha256':digest(serialize_states(prior)),'state_after_sha256':digest(serialize_states(updated))}

def run_nfl_assimilation_check(*,path,receipt,schedule,cutoff,archive,output,prior_states=None,forecast_requests=(),params=None,previous_finals=None):
    """Always persist an audit, including parsing, coverage and assimilation failures."""
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    report={'schema':'nfl.assimilation.audit.v1','parser_version':PARSER_VERSION,'cutoff_utc':cutoff,
      'created_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'status':'failed','reason':[],
      'state_update_applied':False,'forecast_traces':[],'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    try:
        pbp,snapshot=ingest_pbp_snapshot(path,receipt,archive);report['snapshot']=snapshot
        cov=reconcile_game_coverage(pbp,schedule,snapshot,cutoff,previous_finals);report['coverage']=cov
        report['phase_observations']=build_scoring_and_play_attribution(pbp,cov)
        report['status']='reconciled' if cov['completed_coverage_complete'] else 'quarantined'
        prior_hash=digest(serialize_states(prior_states)) if prior_states is not None else None
        quarantine=Path(archive)/'_quarantine'/str(prior_hash)
        revised=[r['game_id'] for r in cov['rows'] if r['prior_state_quarantine_required']]
        if revised:
            record={'prior_state_sha256':prior_hash,'revised_game_ids':revised,'new_snapshot_id':snapshot['snapshot_id'],
              'previous_finals':previous_finals,'reason':'REBUILD_STATE_FROM_CORRECTED_SOURCE_REQUIRED'}
            qpath=quarantine/(digest(record)+'.json')
            if not qpath.exists():write_once(qpath,record)
            report['quarantine_record']=record
        if prior_hash and quarantine.exists():
            report['reason'].append('PRIOR_STATE_QUARANTINED_REBUILD_REQUIRED')
            cov['weekly_state_update_eligible']=False;report['status']='quarantined'
        if cov['weekly_state_update_eligible'] and prior_states is not None:
            updated,qa=advance_states(prior_states,schedule,pbp);report['qualifying_play_audit']=qa
            report['state_before_sha256']=digest(serialize_states(prior_states));report['state_after_sha256']=digest(serialize_states(updated))
            report['state_update_applied']=True
            write_once(out/'team_state.json',serialize_states(updated))
            for request in forecast_requests:
                if (int(request['season']),int(request['week']))<=max(zip(schedule.season.astype(int),schedule.week.astype(int))):
                    report['forecast_traces'].append({'event_id':request['game_id'],'status':'not_updated','reason':'SAME_WEEK_OR_EARLIER_FORECAST'})
                else:report['forecast_traces'].append(trace_feature_effects_into_forecasts(prior_states,updated,request,params))
        else:report['reason'].append('WEEK_NOT_COMPLETE_OR_PRIOR_STATE_NOT_SUPPLIED')
    except Exception as exc:
        report['reason'].append(type(exc).__name__+':'+str(exc))
    write_once(out/'audit.json',report)
    return report
