"""Versioned JSON Schema definitions; semantic checks remain in core/registry."""
from .core import require

S={'type':'string','minLength':1};H={'type':'string','pattern':'^[a-f0-9]{64}$'}
I={'type':'integer','minimum':0};N={'type':'number'};B={'type':'boolean'}
TIME={'type':'string','format':'date-time'}
BASE={'sport':{'const':'CFB'},'schema_version':{'const':1}}
FIELDS={
 'cfb_schedule_contract_v1':{'registry_id':S,'season':I,'week':I,'scope':{'enum':['FBS_VS_FBS','FULL_PROVIDER_WEEK']},'game_ids':{'type':'array','items':S,'uniqueItems':True,'minItems':1},'dataset_hash':H},
 'cfb_pbp_contract_v1':{'event_id':S,'play_id':S,'season':I,'week':I,'posteam':S,'defteam':S,'source_family':{'enum':['cfbfastR_legacy_pbp','espn_cfb_pbp']},'source_hash':H,'adapter_version':S,'available_at':TIME},
 'cfb_team_stats_contract_v1':{'event_id':S,'team_id':S,'source_hash':H,'numerator':N,'denominator':{'type':'number','exclusiveMinimum':0},'unit':S,'orientation':S},
 'cfb_player_identity_contract_v1':{'provider':S,'source_player_id':S,'player_id':S,'team_id':S,'valid_from':TIME,'source_hash':H},
 'cfb_roster_availability_contract_v1':{'event_id':S,'player_id':S,'status':{'enum':['CANDIDATE','CONFIRMED','UNKNOWN','OUT']},'source_role':{'enum':['ROSTER','DEPTH_CHART','OFFICIAL_GAME_AVAILABILITY']},'available_at':TIME,'source_hash':H},
 'cfb_weather_contract_v1':{'venue_id':S,'kind':{'enum':['FORECAST','OBSERVED']},'roof':{'enum':['OPEN','CLOSED','UNKNOWN']},'valid_from':TIME,'valid_to':TIME,'available_at':TIME,'wind_mph':{'type':['number','null'],'minimum':0},'temperature_f':{'type':['number','null']},'source_hash':H},
 'cfb_market_contract_v1':{'event_id':S,'book':S,'captured_at':TIME,'market_type':S,'period':S,'side':S,'odds_format':{'enum':['AMERICAN','DECIMAL','FRACTIONAL']},'price':N,'source_hash':H,'predictive_feature':{'const':False}},
 'cfb_feature_registry_v1':{'feature_id':S,'feature_set_hash':H,'definition_hash':H,'source_family':S,'unit':S,'orientation':S,'transform_version':S,'status':{'enum':['REGISTERED','AVAILABLE_FOR_MODEL','FITTED','CONNECTED','ACTIVE_SHADOW','ACTIVE_DEFAULT','QUARANTINED','REJECTED_BY_ABLATION','BLOCKED_MISSING_SOURCE','BLOCKED_STALE','BLOCKED_LEAKAGE_RISK']}},
 'cfb_state_transition_contract_v1':{'transition_id':H,'parent_state_hash':H,'child_state_hash':H,'schedule_hash':H,'pbp_hash':H,'updater_version':S,'state_published':B},
 'cfb_forecast_artifact_contract_v1':{'forecast_hash':H,'event_id':S,'feature_snapshot_hash':H,'model_hash':H,'calibration_hash':H,'forecast_cutoff':TIME,'generated_at':TIME,'home_win_probability':{'type':'number','minimum':0,'maximum':1},'action_authority':{'const':False},'dose':{'const':0.0}},
}
SCHEMAS={name:{'$schema':'https://json-schema.org/draft/2020-12/schema','$id':name,'type':'object','required':list(BASE)+list(fields),'properties':{**BASE,**fields},'additionalProperties':False} for name,fields in FIELDS.items()}

def validate(name,record):
    from jsonschema import Draft202012Validator,FormatChecker
    require(name in SCHEMAS,'UNKNOWN_CONTRACT')
    Draft202012Validator(SCHEMAS[name],format_checker=FormatChecker()).validate(record)
