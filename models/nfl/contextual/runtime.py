"""One research inference path for recovered weather and fitted current context."""
from __future__ import annotations
import copy,datetime as dt,hashlib,json
from pathlib import Path
from .features import qb_features,availability_features,travel_features,canonical
from .model import simulate_joint
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

def run(artifact,recovered,base,context,event,cutoff,n=100000):
    if utc(cutoff)>=utc(event['start_time_utc']):raise ValueError('NOT_PREGAME')
    x,audit=live_features(artifact,recovered,base,context,event,cutoff)
    arms={}
    for arm,params in artifact['arms'].items():
        feature={name:x[name] for name in params['feature_names']}
        arms[arm]=predict(params,feature)
    code_hashes={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in ('runtime.py','model.py','features.py','recovered_inference.py')}
    identity=digest({'event':event,'features':x,'artifact':artifact,'context':context,'runtime':'nfl.integrated_context.v1','code_hashes':code_hashes})
    p=arms['combined']['prediction'];winner,win_info=bernoulli_simulation(p['home_win'],identity,n)
    scores,score_info=simulate_joint(p['home_margin'],p['total_points'],p['home_win'],artifact['final_score_residuals'],artifact['simulation_v2']['tie_rate'],identity,n)
    feature_contributions={t:arms['combined']['contribution_trace'][t]['features'] for t in p}
    means={'home':(p['total_points']+p['home_margin'])/2,'away':(p['total_points']-p['home_margin'])/2}
    result={'schema':'nfl.integrated_context_forecast.v1','model_id':artifact['arms']['combined']['model_id'],'event':event,'cutoff_utc':cutoff,'identity':identity,'model_artifact_sha256':digest(artifact),'features':x,'audit':audit,'arms':arms,'prediction':p,'score_centers':means,'winner_simulation':win_info,'score_simulation':score_info,'contribution_trace':feature_contributions,'current_context_numerically_applied':['QB_PRIOR_AND_CHANGE','INJURY_POSITION_GROUPS','PRACTICE','PRIOR_SNAP_WORKLOAD','AIRPORT_TRAVEL_PROXY','WEATHER','REST'],'coverage_label':'BASELINE_WITH_UNRESOLVED_INPUTS','research_only':True,'canonical_prospective_eligible':False,'market_input':False,'action_authority':False,'warnings':['NEW_FIT_NOT_PROSPECTIVELY_VALIDATED','HISTORICAL_REPORT_AND_STARTER_PIT_LIMITATIONS','FINAL_INACTIVES_PENDING','PRIOR_SNAP_SHARE_IS_NOT_PROMISED_WORKLOAD','TRAVEL_IS_AIRPORT_PROXY','EMPIRICAL_SCORE_SETTLEMENT_UNVALIDATED']}
    result['code_hashes']=code_hashes
    return result,winner,scores

def persist_run(folder,bundle,winner,scores,design):
    import numpy as np
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    if dt.datetime.now(dt.timezone.utc)>=utc(bundle['event']['start_time_utc']):raise ValueError('START_CROSSED_BEFORE_PERSISTENCE')
    # Exact UTC registration timestamps are actual writes, never invented history.
    registration={'created_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'type':'LOCAL_RESEARCH_ARTIFACT','forecast_identity':bundle['identity'],'design_sha256':digest(design),'previous_hash':None,'canonical_prospective_eligible':False}
    registration['record_hash']=digest(registration)
    (folder/'registration.jsonl').write_text(json.dumps(registration)+'\n')
    np.save(folder/'winner_draws.npy',winner,allow_pickle=False);np.save(folder/'score_draws.npy',scores,allow_pickle=False)
    (folder/'forecast.json').write_text(json.dumps(bundle,indent=2,allow_nan=False))
    manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2))
