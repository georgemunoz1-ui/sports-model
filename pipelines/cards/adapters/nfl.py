"""Canonical NFL card adapter: integrated context first, explicit baseline arm.

No import-time network or hidden SRS fallback. An absent fitted package is an
installation error, not evidence that the NFL only supports an SRS engine.
"""
from __future__ import annotations
import datetime as dt,json,os
from pathlib import Path
from models.nfl.contextual.runtime import run
from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.recovered_inference import utc,digest

ROOT=Path(__file__).resolve().parents[3]
DATA=ROOT/'data/nfl/contextual_v1'

def _path():
    if os.environ.get('NFL_CONTEXT_PACKAGE'):return Path(os.environ['NFL_CONTEXT_PACKAGE'])
    config=json.loads((DATA/'runtime.json').read_text())
    return DATA/config['event_package']
def _package():
    path=_path()
    if not path.is_file():raise ValueError('NFL_CONTEXT_PACKAGE_MISSING: run scripts/prepare_nfl_event.py; no silent SRS fallback')
    return json.loads(path.read_text())

def load_schedule(card_date,as_of_utc):
    package=_package()
    if card_date not in package['covered_dates']:raise ValueError('NFL_DATE_NOT_CAPTURED:'+card_date)
    if utc(package['captured_at_utc'])>utc(as_of_utc):raise ValueError('SCHEDULE_AFTER_CUTOFF')
    return [e for e in package['events'] if e['gameday']==card_date]

def build_context(schedule,as_of_utc,allow_stale=True,overrides_path=None):
    if overrides_path:raise ValueError('USE_VERSIONED_EVENT_PACKAGE_NOT_UNTYPED_OVERRIDES')
    package=_package();base=_path().parent
    model_path=base/package['model_path'];model=load_artifact(model_path)
    if digest(model)!=package['model_digest']:raise ValueError('MODEL_PACKAGE_HASH_MISMATCH')
    if model['schema']!='nfl.integrated_context.v1':raise ValueError('NFL_MODEL_SCHEMA')
    recovered=json.loads((base/package['recovered_parameters_path']).read_text())
    return {'model':model,'recovered':recovered,'package':package,'cutoff':as_of_utc,'pit_provenance':{'pit_mode':'FROZEN_EVENT_PACKAGE','pit_reconstruction_supported':True,'adapter_source':__name__,'data_vintage_basis':'SOURCE_RECEIPTS_PLUS_REUSED_HISTORICAL_FIT','source_fetches':package['source_fetches']}}

def forecast_event(event,context,simulations=100000,*,model_id=None,mode='research_pregame'):
    packet=context['package']['event_inputs'][event['event_id']]
    result,winner,scores=run(context['model'],context['recovered'],packet['base'],packet['context'],event,context['cutoff'],simulations,model_id=json.loads((DATA/'runtime.json').read_text())['default_research_model'] if model_id is None else model_id,mode=mode)
    p=result['prediction'];home=p['home_win']>=.5;winner_name=event['home_team'] if home else event['away_team']
    analytic=p['home_win'] if home else 1-p['home_win'];mc=result['winner_simulation']['home_win_probability'];mc=mc if home else 1-mc
    return {'model_id':result['model_id'],'model_winner':winner_name,'model_p':analytic,'sim_p':mc,'analytic_p':analytic,'stochastic_sim_p':mc,'projected_margin':p['home_margin'] if home else -p['home_margin'],'projected_total':p['total_points'],'projected_home_points':result['score_centers']['home'],'projected_away_points':result['score_centers']['away'],'forecast_tier':'REDUCED','data_quality':'PARTIAL_CURRENT_CONTEXT_APPLIED','dose':0.0,'coverage_label':result['coverage_label'],'model_state_config_hash':result['model_artifact_sha256'],'input_snapshot_hash':digest(result['features']),'model_input_snapshot':result['features'],'diagnostics':result,'simulation':{'binary':result['winner_simulation'],'joint_scores':result['score_simulation']},'warnings':result['warnings'],'provenance':{'source_fetches':context['package']['source_fetches'],'model_id':result['model_id']},'action_authority':False}
