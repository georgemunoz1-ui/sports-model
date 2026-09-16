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

def build_context(schedule,as_of_utc,allow_stale=True,overrides_path=None,*,mode='research_pregame'):
    if overrides_path:raise ValueError('USE_VERSIONED_EVENT_PACKAGE_NOT_UNTYPED_OVERRIDES')
    package=_package();base=_path().parent
    if mode=='live':return {'model':None,'recovered':None,'package':package,'cutoff':as_of_utc}
    model_path=base/package['model_path'];model=load_artifact(model_path)
    if digest(model)!=package['model_digest']:raise ValueError('MODEL_PACKAGE_HASH_MISMATCH')
    if model['schema']!='nfl.integrated_context.v1':raise ValueError('NFL_MODEL_SCHEMA')
    recovered=json.loads((base/package['recovered_parameters_path']).read_text())
    return {'model':model,'recovered':recovered,'package':package,'cutoff':as_of_utc,'pit_provenance':{'pit_mode':'FROZEN_EVENT_PACKAGE','pit_reconstruction_supported':True,'adapter_source':__name__,'data_vintage_basis':'SOURCE_RECEIPTS_PLUS_REUSED_HISTORICAL_FIT','source_fetches':package['source_fetches']}}

def mode_artifact(mode):
    if mode=='research_pregame':return None
    config_path=ROOT/'data/nfl/modes_v1/runtime.json'
    config=json.loads(config_path.read_text())
    if mode not in config['models']:raise ValueError('MODE_UNAVAILABLE:'+mode)
    entry=config['models'][mode];model=load_artifact(config_path.parent/entry['file'])
    if digest(model)!=entry['model_digest']:raise ValueError('MODE_ARTIFACT_HASH_MISMATCH')
    return model

def forecast_event(event,context,simulations=100000,*,model_id=None,mode='research_pregame',market=None,live_state=None):
    packet={'base':None,'context':None} if mode=='live' else context['package']['event_inputs'][event['event_id']]
    fitted=mode_artifact(mode) if mode!='research_pregame' else None
    from models.nfl.contextual.week2 import applies,policy
    default_id=fitted['model_id'] if fitted is not None else (policy()['default_reference_model'] if applies(packet['base'],event) else json.loads((DATA/'runtime.json').read_text())['default_research_model'])
    result,winner,scores=run(context['model'],context['recovered'],packet['base'],packet['context'],event,context['cutoff'],simulations,model_id=default_id if model_id is None else model_id,mode=mode,mode_artifact=fitted,market=market,live_state=live_state)
    if mode=='live':return result
    p=result['prediction'];home=p['home_win']>=.5;winner_name=event['home_team'] if home else event['away_team']
    analytic=p['home_win'] if home else 1-p['home_win'];mc=result['winner_simulation']['home_win_probability'];mc=mc if home else 1-mc
    joint=result.get('joint_distribution')
    # Only the joint object supplies score expectations. Independent Ridge heads stay diagnostic.
    margin=joint['mean_margin'] if joint else None
    total=joint['mean_total'] if joint else None
    points={'home':joint['mean_home_score'],'away':joint['mean_away_score']} if joint else {'home':None,'away':None}
    return {'model_id':result['model_id'],'model_winner':winner_name,'model_p':analytic,'sim_p':mc,'analytic_p':analytic,'stochastic_sim_p':mc,'projected_margin':(margin if home else -margin) if margin is not None else None,'projected_total':total,'projected_home_points':points['home'],'projected_away_points':points['away'],'forecast_tier':'REDUCED','data_quality':'PARTIAL_CURRENT_CONTEXT_APPLIED','dose':0.0,'coverage_label':result['coverage_label'],'model_state_config_hash':result['model_artifact_sha256'],'input_snapshot_hash':digest(result['features']),'model_input_snapshot':result['features'],'diagnostics':result,'simulation':{'binary':result['winner_simulation'],'joint_scores':result['score_simulation']},'warnings':result['warnings'],'provenance':{'source_fetches':context['package']['source_fetches'],'model_id':result['model_id']},'action_authority':False}


def calibrate_spreads(frozen_forecast,score_draws,home_handicaps,*,n=100000):
    """Downstream calibrated spread output; never changes generation inputs."""
    from models.nfl.contextual.spread_runtime import build_overlay
    return build_overlay(frozen_forecast,score_draws,home_handicaps,n=n)
