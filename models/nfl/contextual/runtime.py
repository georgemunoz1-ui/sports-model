"""One research inference path for recovered weather and fitted current context."""
from __future__ import annotations
import copy,datetime as dt,hashlib,json
from pathlib import Path
from .features import qb_features,availability_features,travel_features,canonical
from .model import simulate_joint
from .operating import select,coverage,RESEARCH_MODE
from .recovered_inference import bind_context,predict,digest,bernoulli_simulation,utc

def live_features(artifact,recovered,base,context,event,cutoff):
    if base['game_id']!=event['event_id']:raise ValueError('BASE_EVENT_ID')
    if (base['home_team'],base['away_team'])!=(event['home_team'],event['away_team']):raise ValueError('HOME_AWAY_BINDING')
    bound=bind_context(recovered,base,context,cutoff,event['start_time_utc'])
    ratings=copy.deepcopy(artifact['state']['qb_ratings'])
    years=int(base['season'])-int(artifact['state'].get('season',max(artifact['arms']['combined']['training_seasons'])))
    if years<0:raise ValueError('FUTURE_FEATURE_STATE')
    for v in ratings.values():v['sum']*=.55**years;v['n']*=.55**years
    r={**base,'gameday':event['gameday'],'gametime':event['gametime'],'location':event.get('location','Home')}
    personnel=context.get('personnel',{}).get('state',{});reports={};report_audit=[]
    for side in ('home','away'):
        team=event[side+'_team'];q=personnel.get('quarterbacks',{}).get(team,{})
        r[side+'_qb_id']=q.get('id')
        if q.get('game_status')=='OUT':raise ValueError('EXPECTED_QB_REPORTED_OUT:'+team)
    for obs in personnel.get('injury_observations',[]):
        team=canonical(obs['team'])
        if team not in (event['home_team'],event['away_team']):raise ValueError('PERSONNEL_TEAM_MISMATCH')
        reports.setdefault(team,[]).append({'full_name':obs['player'],'gsis_id':obs.get('player_id'),'position':obs['position'],'report_status':obs['game_status'],'practice_status':obs['practice']})
    # Explicit verified reserve status can enter the absence proxy, with its
    # out-of-report support difference preserved rather than claiming calibration.
    for absence in personnel.get('reserve_absences',[]):
        team=canonical(absence['team'])
        if team not in (event['home_team'],event['away_team']):raise ValueError('RESERVE_TEAM_MISMATCH')
        if absence['status'] not in {'COMMISSIONER_EXEMPT','SUSPENDED','INJURED_RESERVE'}:raise ValueError('UNVERIFIED_RESERVE_STATE')
        reports.setdefault(team,[]).append({'full_name':absence['player'],'position':absence['position'],'report_status':'OUT','practice_status':None})
        report_audit.append(absence['status']+'_MAPPED_TO_OUT_PROXY; HISTORICAL_RESERVE_COVERAGE_UNVERIFIED')
    av,role_audit=availability_features(r,reports,artifact['state']['roles'])
    x={**bound['features'],**qb_features(r,ratings,artifact['state']['last_qb']),**av,**travel_features(r,artifact['airports'])}
    return x,{'recovered_model':bound,'personnel_absence_roles':role_audit,'availability_mapping_notes':report_audit,'workload':'PRIOR_SNAP_ROLE_PROXY; CURRENT_EXPECTED_WORKLOAD_UNKNOWN','travel':'HOME_AIRPORT_ROUTE_PROXY; ACTUAL_ITINERARY_UNKNOWN','final_inactives':personnel.get('final_inactives','UNKNOWN')}

def run(artifact,recovered,base,context,event,cutoff,n=100000,*,model_id=None,mode=RESEARCH_MODE,mode_artifact=None,market=None,live_state=None):
    if mode in {'enhanced_pregame','live'}:
        from ..modes.runtime import enhanced,live
        if mode_artifact is None:raise ValueError('FITTED_MODE_ARTIFACT_REQUIRED')
        if utc(mode_artifact['deployment_packaged_at_utc'])>utc(cutoff):raise ValueError('MODE_ARTIFACT_AFTER_CUTOFF')
        if model_id is not None and model_id!=mode_artifact['model_id']:raise ValueError('EXACT_MODEL_ID_REQUIRED_NO_FALLBACK')
        expected_schema='nfl.market_ensemble.v1' if mode=='enhanced_pregame' else 'nfl.live_state_hgb.v1'
        if mode_artifact['schema']!=expected_schema:raise ValueError('MODE_ARTIFACT_SCHEMA')
        if mode=='live':return live(mode_artifact,market,live_state,event,cutoff,n)
        if live_state is not None:raise ValueError('LIVE_INPUT_IN_PREGAME')
        football,_,_=run(artifact,recovered,base,context,event,cutoff,n,model_id=mode_artifact['football_model_id'])
        return enhanced(football,mode_artifact,market,event,cutoff,n)
    if market is not None or live_state is not None:raise ValueError('MARKET_OR_LIVE_INPUT_IN_FOOTBALL_ONLY')
    # Legacy callers keep the documented combined default; selectors never fallback.
    if model_id is None:model_id=artifact['arms']['combined']['model_id']
    selected=select(artifact,model_id,mode)
    if utc(cutoff)>=utc(event['start_time_utc']):raise ValueError('NOT_PREGAME')
    x,audit=live_features(artifact,recovered,base,context,event,cutoff)
    arms={}
    for arm,params in artifact['arms'].items():
        feature={name:x[name] for name in params['feature_names']}
        arms[arm]=predict(params,feature)
    from .capabilities import describe_run_capabilities
    capability_report=describe_run_capabilities(artifact['arms'][selected],x,context,base,cutoff,event,digest(artifact),arms[selected]['contribution_trace'])
    code_hashes={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in ('runtime.py','model.py','features.py','recovered_inference.py','operating.py','capabilities.py','settlement.py','forecast_stream.py')}
    identity=digest({'event':event,'features':x,'artifact':artifact,'context':context,'runtime':'nfl.integrated_context.v1','model_id':model_id,'mode':mode,'code_hashes':code_hashes})
    p=arms[selected]['prediction'];winner,win_info=bernoulli_simulation(p['home_win'],identity,n)
    scores=None;score_info={'status':'UNAVAILABLE_FOR_SELECTED_ARM','reason':'FROZEN_JOINT_RESIDUAL_POOL_IS_COMBINED_SPECIFIC'}
    if selected=='combined':scores,score_info=simulate_joint(p['home_margin'],p['total_points'],p['home_win'],artifact['final_score_residuals'],artifact['simulation_v2']['tie_rate'],identity,n)
    feature_contributions={t:arms[selected]['contribution_trace'][t]['features'] for t in p}
    means={'home':(p['total_points']+p['home_margin'])/2,'away':(p['total_points']-p['home_margin'])/2}
    result={'schema':'nfl.integrated_context_forecast.v1','model_id':model_id,'event':event,'cutoff_utc':cutoff,'identity':identity,'model_artifact_sha256':digest(artifact),'features':x,'audit':audit,'arms':arms,'prediction':p,'score_centers':means,'winner_simulation':win_info,'score_simulation':score_info,'contribution_trace':feature_contributions,'current_context_numerically_applied':['QB_PRIOR_AND_CHANGE','INJURY_POSITION_GROUPS','PRACTICE','PRIOR_SNAP_WORKLOAD','AIRPORT_TRAVEL_PROXY','WEATHER','REST'],'coverage_label':'FITTED_RESEARCH_FEATURES_WITH_UNRESOLVED_CURRENT_STATE','research_only':True,'canonical_prospective_eligible':False,'market_input':False,'action_authority':False,'warnings':['NEW_FIT_NOT_PROSPECTIVELY_VALIDATED','HISTORICAL_REPORT_AND_STARTER_PIT_LIMITATIONS','FINAL_INACTIVES_PENDING','PRIOR_SNAP_SHARE_IS_NOT_PROMISED_WORKLOAD','TRAVEL_IS_AIRPORT_PROXY','EMPIRICAL_SCORE_SETTLEMENT_UNVALIDATED']}
    result['code_hashes']=code_hashes
    result['capability_report']=capability_report
    result['mode']=mode
    result['selected_arm']=selected
    result['feature_coverage']=coverage(artifact['arms'][selected],x,audit)
    result['current_context_numerically_applied']={'base':['WEATHER','REST'], 'qb':['WEATHER','REST','QB_PRIOR_AND_CHANGE'], 'availability':['WEATHER','REST','INJURY_POSITION_GROUPS','PRACTICE','PRIOR_SNAP_WORKLOAD'], 'travel':['WEATHER','REST','AIRPORT_TRAVEL_PROXY'], 'combined':result['current_context_numerically_applied']}[selected]
    return result,winner,scores

def persist_run(folder,bundle,winner,scores,design):
    import numpy as np
    now=dt.datetime.now(dt.timezone.utc)
    if utc(bundle['cutoff_utc'])>now:raise ValueError('FUTURE_INFORMATION_CUTOFF_AT_WRITE')
    folder=Path(folder)
    from .capabilities import validate_report
    if bundle.get('mode')!='live': validate_report(bundle['capability_report'])
    if bundle.get('mode')!='live' and dt.datetime.now(dt.timezone.utc)>=utc(bundle['event']['start_time_utc']):raise ValueError('START_CROSSED_BEFORE_PERSISTENCE')
    folder.mkdir(parents=True,exist_ok=False)
    # Exact UTC registration timestamps are actual writes, never invented history.
    registration={'created_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'type':'LOCAL_RESEARCH_ARTIFACT','mode':bundle.get('mode','research_pregame'), 'information_cutoff_utc':bundle['cutoff_utc'],'forecast_identity':bundle['identity'],'design_sha256':digest(design),'previous_hash':None,'canonical_prospective_eligible':False}
    registration['reporter_sha256']=bundle.get('capability_report',{}).get('reporter_sha256')
    registration['capability_report_sha256']=digest(bundle['capability_report']) if 'capability_report' in bundle else None
    registration['record_hash']=digest(registration)
    (folder/'registration.jsonl').write_text(json.dumps(registration)+'\n')
    np.save(folder/'winner_draws.npy',winner,allow_pickle=False)
    if 'capability_report' in bundle:(folder/'capabilities.json').write_text(json.dumps(bundle['capability_report'],indent=2,allow_nan=False))
    if scores is not None:np.save(folder/'score_draws.npy',scores,allow_pickle=False)
    (folder/'forecast.json').write_text(json.dumps(bundle,indent=2,allow_nan=False))
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2))
    from .forecast_stream import append_forecast_record
    append_forecast_record(folder.parent/'forecast_stream.jsonl',bundle,digest(manifest))
