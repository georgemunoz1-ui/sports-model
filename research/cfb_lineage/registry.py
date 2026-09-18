"""Four linked registry tables and event-level eligibility; no auto-activation."""
from __future__ import annotations
import math
from pathlib import Path
from .core import Store, require, GateError, digest, utc, now

PBP_FAMILIES = {'cfbfastR_legacy_pbp', 'espn_cfb_pbp'}
TARGETS = {'home_win_probability':'DECIMAL_0_1', 'home_margin':'POINTS_HOME_MINUS_AWAY', 'game_total':'POINTS_HOME_PLUS_AWAY'}
FORBIDDEN = {'vegas_wp','vegas_wpa','gameSpread','homeTeamSpread','overUnder','moneyline','odds','market_probability','result','winner'}

TABLES = {
 'feature_definitions': ['feature_id','display_name','sport','prediction_mode','entity_grain','target_compatibility','source_family','source_dataset','source_columns','source_endpoint_version','identity_keys','availability_rule','lookback_rule','transform_version','unit','orientation','missingness_policy','eligible_competition','status','owner','definition_hash','definition_json'],
 'feature_observations': ['package_id','event_id','season','week','team_id','opponent_team_id','home_away','feature_id','feature_value_raw','feature_value_model','is_missing','missingness_reason','source_snapshot_id','source_content_hash','source_max_event_time','available_at','forecast_cutoff','as_of_eligible','transform_version','feature_definition_hash','created_at','validation_status','upstream_model_hash','numerator','denominator'],
 'feature_model_paths': ['feature_id','feature_set_id','feature_set_hash','model_id','model_version','model_family','target','input_name','path_status','coefficient','importance_method','importance_value','member_weight','ensemble_id','run_id','path_end_state','model_hash'],
 'feature_evaluations': ['evaluation_id','feature_set_id','candidate_feature_block','comparison_feature_set_id','model_id','train_period','calibration_period','test_period','split_type','target','primary_metric','candidate_metric','baseline_metric','delta','bootstrap_ci_95','operational_availability','decision','decision_reason','evaluation_hash']}
NUMBERS={'feature_value_raw','feature_value_model','coefficient','importance_value','member_weight','candidate_metric','baseline_metric','delta','operational_availability','numerator','denominator'}
BOOLEANS={'is_missing','as_of_eligible'}
INTEGERS={'season','week'}


def seal_definition(definition: dict) -> dict:
    d=dict(definition)
    require(d['sport']=='CFB' and d['feature_id'].startswith('cfb.'),'CROSS_SPORT_FEATURE')
    require(d['status'] in ('REGISTERED','CANDIDATE','QUARANTINED'),'ACTIVE_REQUIRES_EVALUATION')
    require(bool(d['unit']) and bool(d['orientation']),'SEMANTICS_REQUIRED')
    require(not FORBIDDEN.intersection(d['source_columns']),'MARKET_OR_LABEL_FEATURE_REJECTED')
    d.pop('definition_hash',None);d['definition_hash']=digest(d)
    return d


def validate_observation(definition: dict, row: dict, source: dict, cutoff: str, *, upstream_model_required: bool = False) -> None:
    d=dict(definition);h=d.pop('definition_hash')
    require(digest(d)==h and row['feature_definition_hash']==h,'FEATURE_DEFINITION_HASH_MISMATCH')
    require(row['feature_id']==definition['feature_id'],'FEATURE_ID_MISMATCH')
    require(row['transform_version']==definition['transform_version'],'TRANSFORM_VERSION_MISMATCH')
    require(source['source_family']==definition['source_family'],'SOURCE_FAMILY_MISMATCH')
    require(row['source_content_hash']==source['raw_hash'],'SOURCE_HASH_MISMATCH')
    require(row['forecast_cutoff']==cutoff,'CUTOFF_MISMATCH')
    for t in (row['available_at'],source['available_at'],source['retrieved_at']):
        require(utc(t)<=utc(cutoff),'FEATURE_AFTER_CUTOFF')
    require(utc(row['source_max_event_time'])<utc(cutoff),'FEATURE_EVENT_NOT_PRIOR')
    require(row['home_away'] in ('HOME','AWAY') and row['team_id']!=row['opponent_team_id'],'IDENTITY_OR_ORIENTATION')
    if upstream_model_required:
        require(bool(row.get('upstream_model_hash')) and row['upstream_model_hash']==source.get('upstream_model_hash'),'UPSTREAM_MODEL_GENERATION_UNPINNED')
    if row['is_missing']:
        require(bool(row['missingness_reason']) and row['feature_value_raw'] is None,'AMBIGUOUS_MISSINGNESS')
        require(row['feature_value_model'] is None,'IMPUTATION_REQUIRES_FITTED_PREPROCESSOR')
    else:
        require(row['feature_value_raw'] is not None and row['feature_value_model'] is not None,'VALUE_MISSING')
        for key in ('feature_value_raw','feature_value_model'):
            x=row[key];require(type(x) in (float,int) and math.isfinite(x),'FINITE_FEATURE_REQUIRED')
        if definition['unit']=='FRACTION':require(0<=row['feature_value_raw']<=1,'RATE_UNIT_MISMATCH')
        if definition.get('requires_denominator'):
            require(type(row.get('denominator')) in (float,int) and row['denominator']>0,'NONZERO_DENOMINATOR_REQUIRED')
            require(row.get('numerator') is not None and abs(row['feature_value_raw']-row['numerator']/row['denominator'])<1e-10,'RATE_NUMERATOR_DENOMINATOR_MISMATCH')


def feature_set(store: Store, identifier: str, definitions: list[dict], required: list[str]) -> str:
    ids=[d['feature_id'] for d in definitions]
    require(len(ids)==len(set(ids)) and set(required)<=set(ids),'FEATURE_SET_MEMBERSHIP')
    families={d['source_family'] for d in definitions}&PBP_FAMILIES
    require(len(families)<=1,'MIXED_PBP_FAMILIES_REQUIRES_SEPARATE_FEATURE_SET')
    parents={d['feature_id']:store.put('feature_definition',d) for d in definitions}
    h=store.put('feature_set',{'feature_set_id':identifier,'feature_ids':ids,'required_features':required,'status':'REGISTERED_NOT_ACTIVE'},parents)
    store.bind(identifier,h);return h


def snapshot(store: Store, set_hash: str, state_hash: str, event: dict, rows: list[dict], source_hashes: dict[str,str], cutoff: str) -> str:
    fs=store.node(set_hash);state=store.node(state_hash)
    require(utc(state['payload']['created_at'])<=utc(cutoff),'STATE_PUBLISHED_AFTER_CUTOFF')
    require(fs['kind']=='feature_set' and state['kind']=='weekly_state','SNAPSHOT_PARENT_KINDS')
    require(state['payload']['season']==event['season'] and state['payload']['completed_week']<event['week'],'FUTURE_OR_WRONG_SEASON_STATE')
    require(utc(cutoff)<utc(event['kickoff']) and utc(cutoff)<=utc(now()),'NOT_CURRENT_PREGAME_CUTOFF')
    actual={r['feature_id'] for r in rows}
    require(len(actual)==len(rows) and actual<=set(fs['payload']['feature_ids']),'UNREGISTERED_OR_DUPLICATE_FEATURE')
    require(set(fs['payload']['required_features'])<=actual,'REQUIRED_FEATURE_MISSING')
    for r in rows:
        require(r['event_id']==event['event_id'],'OBSERVATION_EVENT_MISMATCH')
        require((r['season'],r['week'])==(event['season'],event['week']),'OBSERVATION_WEEK_MISMATCH')
        home,away=event['home_id'],event['away_id']
        expected=(home,away) if r['home_away']=='HOME' else (away,home)
        require((r['team_id'],r['opponent_team_id'])==expected,'OBSERVATION_TEAM_MISMATCH')
        d=store.node(fs['parents'][r['feature_id']])['payload']
        src=store.node(source_hashes[r['source_snapshot_id']])
        require(src['kind']=='raw_source','RAW_SOURCE_PARENT_REQUIRED')
        validate_observation(d,r,src['payload'],cutoff,upstream_model_required=d.get('upstream_model_required',False))
        if r['feature_id'] in fs['payload']['required_features']:require(not r['is_missing'],'REQUIRED_FEATURE_MISSING')
    return store.put('feature_snapshot',{'event':event,'cutoff':cutoff,'created_at':now(),'rows':rows,'state_hash':state_hash,'feature_set_hash':set_hash,'status':'RESEARCH_ONLY'},
                     {'feature_set':set_hash,'weekly_state':state_hash,**{'source:'+k:v for k,v in source_hashes.items()}})


def check_model_path(path: dict, definition: dict, model: dict, feature_set_hash: str) -> None:
    require(path['feature_id']==definition['feature_id'] and path['feature_set_hash']==feature_set_hash,'MODEL_FEATURE_BINDING')
    require(model['sport']=='CFB' and model['feature_set_hash']==feature_set_hash,'CROSS_SPORT_OR_FEATURE_SET')
    require(path['target'] in definition['target_compatibility'] and path['target']==model['target'],'TARGET_INCOMPATIBLE')
    if path['model_family'] not in ('ridge','linear','logistic','elastic_net'):
        require(path.get('coefficient') is None,'NONLINEAR_COEFFICIENT_UNSUPPORTED')
    w=path.get('member_weight');require(w is None or (math.isfinite(w) and 0<=w<=1),'INVALID_ENSEMBLE_WEIGHT')


def active_eligible(observation: dict, path: dict, evaluation: dict) -> bool:
    """Nonzero weight is necessary for an ensemble path, never sufficient."""
    return (observation.get('validation_status')=='PASS' and observation.get('as_of_eligible') is True
            and not observation.get('is_missing') and path.get('path_status')=='FITTED'
            and path.get('member_weight') is not None and path['member_weight']>0 and evaluation.get('decision')=='PROMOTION_CANDIDATE'
            and evaluation.get('prospective_gate_passed') is True and evaluation.get('integrity_gate_passed') is True)


def matchup_epa_score(home_off: float, away_def_allowed: float, away_off: float, home_def_allowed: float) -> float:
    """Unfitted directional interaction, NOT calibrated expected points or probability.

    Greater opponent EPA allowed is easier, not harder, for the offense.
    Common league centering cancels in this symmetric difference.
    """
    return (home_off+away_def_allowed)-(away_off+home_def_allowed)


def rating_request(provider: str, year: int, week: int | None = None) -> dict:
    endpoints={'srs':'/ratings/srs','srs_expanded':'/ratings/srs/expanded','elo':'/ratings/elo','sp':'/ratings/sp','fpi':'/ratings/fpi','core':'/ratings/core'}
    require(provider in endpoints,'UNKNOWN_RATING_PROVIDER')
    require(week is None or provider=='elo','RATING_ENDPOINT_HAS_NO_WEEK_QUERY')
    q={'year':year}
    if week is not None:q.update(week=week,seasonType='regular')
    return {'endpoint':endpoints[provider],'query':q,'historical_pit_certified':False,'rating_week_not_invented':True}


def freeze_forecast(store: Store, feature_hash: str, model_hash: str, calibration_hash: str, projection: dict, *, mode: str) -> str:
    """Validate already-produced output. This function does not fit or predict.

    Operational promotion is deliberately unsupported until separate approval.
    """
    require(mode in ('RESEARCH','SYNTHETIC_TEST'),'LIVE_DEFAULT_NOT_IMPLEMENTED')
    f,m,c=[store.node(h) for h in (feature_hash,model_hash,calibration_hash)]
    require((f['kind'],m['kind'],c['kind'])==('feature_snapshot','model','calibration'),'FORECAST_PARENT_KINDS')
    if mode!='SYNTHETIC_TEST':
        require(m['payload'].get('fitted') is True and c['payload'].get('fitted') is True,'FITTED_ARTIFACTS_REQUIRED')
    require(m['payload']['feature_set_hash']==f['payload']['feature_set_hash'],'MODEL_FEATURE_SET_MISMATCH')
    require({'training_data','feature_set','code','environment'}<=set(m['parents']),'MODEL_TRAINING_LINEAGE_REQUIRED')
    require({'model','calibration_data'}<=set(c['parents']),'CALIBRATION_LINEAGE_REQUIRED')
    require(m['parents']['feature_set']==f['payload']['feature_set_hash'],'MODEL_FEATURE_SET_MISMATCH')
    require(c['parents'].get('model')==model_hash,'CALIBRATION_MODEL_MISMATCH')
    require(m['payload']['target']==c['payload']['target']=='home_win_probability','TARGET_MISMATCH')
    require(set(projection)=={'home_win_probability_raw','home_win_probability'},'UNSUPPORTED_OUTPUT_FIELDS')
    for target in ('home_win_probability_raw','home_win_probability'):
        x=projection[target];require(type(x) in (float,int) and math.isfinite(x) and 0<=x<=1,'PROBABILITY_UNIT')
    require(utc(now())<utc(f['payload']['event']['kickoff']),'START_CROSSED_BEFORE_WRITE')
    require(utc(m['payload']['available_at'])<=utc(f['payload']['cutoff']) and utc(c['payload']['available_at'])<=utc(f['payload']['cutoff']),'MODEL_OR_CALIBRATION_AFTER_CUTOFF')
    return store.put('forecast',{'event_id':f['payload']['event']['event_id'],'projection':projection,'created_at':now(),'cutoff':f['payload']['cutoff'],
          'mode':mode,'simulation':{'status':'NOT_RUN'},'ensemble':{'status':'NOT_USED'},'action_authority':False,'dose':0.,'promotion':False},
          {'features':feature_hash,'model':model_hash,'calibration':calibration_hash})


def export_tables(directory: Path | str, tables: dict[str,list[dict]]) -> dict:
    import json
    import pyarrow as pa
    import pyarrow.parquet as pq
    out=Path(directory);out.mkdir(parents=True,exist_ok=False);manifest={}
    for name,fields in TABLES.items():
        rows=tables.get(name,[]);schema=pa.schema([(k,pa.float64() if k in NUMBERS else pa.bool_() if k in BOOLEANS else pa.int64() if k in INTEGERS else pa.string()) for k in fields])
        normalized=[]
        for r in rows:
            normalized.append({k:(json.dumps(r[k],sort_keys=True) if isinstance(r.get(k),(dict,list)) else r.get(k)) for k in fields})
        p=out/(name+'.parquet');pq.write_table(pa.Table.from_pylist(normalized,schema=schema),p)
        import hashlib
        manifest[name]={'rows':len(rows),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'columns':fields}
    (out/'manifest.json').write_bytes(__import__('json').dumps(manifest,sort_keys=True,indent=2).encode())
    return manifest
