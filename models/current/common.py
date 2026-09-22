"""Shared immutable package and retained simulation contract."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import numpy as np
from models.nfl.contextual.recovered_inference import digest, utc, bernoulli_simulation
ROOT=Path(__file__).resolve().parents[2]


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:json.dump(value,f,sort_keys=True,indent=2,allow_nan=False)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(league):
    path=Path(os.environ.get('SPORTS_RESEARCH_PACKAGE_DIR',ROOT/'data/current_models'))/league/'package.json'
    raw=path.read_bytes();p=json.loads(raw)
    if p['league']!=league or p['schema']!='sports.current_research_package.v1':raise ValueError('PACKAGE_IDENTITY')
    if p.get('action_authority') is not False:raise ValueError('RESEARCH_ONLY_PACKAGE_REQUIRED')
    for name,h in p['code_pins'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=h:raise ValueError('RUNTIME_CODE_DRIFT:'+name)
    if league=='mlb':material={'pins':p['code_pins'],'teams':p['team_state'],'starters':p['starter_state']}
    elif league=='wnba':material={'model':p['fitted_model'],'state':p['team_state'],'league':p['league_state']}
    elif league=='cfb':material={'model':p['fitted_model'],'state':p['team_state'],'parameters':p['parameters']}
    else:material={'model':p['fitted_model'],'state':p['team_state'],'prior':p['prior']}
    if digest(material)!=p['model_sha256']:raise ValueError('MODEL_STATE_DIGEST_MISMATCH')
    return p,hashlib.sha256(raw).hexdigest()


def current(p,asof):
    cutoff=utc(asof)
    if not p['source_fetches']:raise ValueError('SOURCE_RECEIPTS_REQUIRED')
    for stamp in [p['captured_at_utc']]+[r['fetched_at_utc'] for r in p['source_fetches']]:
        if not 0 <= (cutoff-utc(stamp)).total_seconds() <= p.get('ttl_hours',6)*3600:raise ValueError('PACKAGE_NOT_CURRENT')
    if utc(p['training_cutoff_utc'])>cutoff:raise ValueError('FUTURE_FITTED_STATE')


def schedule(league,card_date,asof):
    p,_=load(league)
    if card_date not in p['covered_dates']:raise ValueError('DATE_NOT_ACQUIRED:'+card_date)
    current(p,asof)
    return [e for e in p['events'] if e['slate_date']==card_date]


def context(league,events,asof):
    p,h=load(league)
    current(p,asof)
    if any(e not in p['events'] for e in events):raise ValueError('EVENT_PACKAGE_MISMATCH')
    if utc(p['training_cutoff_utc'])>utc(asof):raise ValueError('FUTURE_FITTED_STATE')
    return {'package':p,'package_sha256':h,'cutoff':asof,'pit_provenance':{'pit_mode':'CURRENT_SOURCE_BOUND_RESEARCH','pit_reconstruction_supported':False,'data_vintage_basis':'RETAINED_SOURCES_AND_FROZEN_TRANSFORM','source_fetches':p['source_fetches']}}


def emit(event,ctx,features,p_home,margin,total,n,*,model_id=None,limitations=()):
    if event not in ctx['package']['events']:raise ValueError('EVENT_PACKAGE_MISMATCH')
    current(ctx['package'],ctx['cutoff'])
    if utc(event['start_time_utc'])<=utc(ctx['cutoff']):raise ValueError('NOT_PREGAME')
    if not 1<=n<=1000000:raise ValueError('DRAW_COUNT_RANGE')
    package=ctx['package'];mid=model_id or package['model_id']
    identity=digest({'event':event,'features':features,'model':package['model_sha256'],'package':ctx['package_sha256'],'cutoff':ctx['cutoff'],'model_id':mid,'n':n})
    draws,sim=bernoulli_simulation(float(p_home),identity,n)
    output=os.environ.get('SPORTS_RESEARCH_DRAW_OUTPUT')
    if not output:raise ValueError('SPORTS_RESEARCH_DRAW_OUTPUT_REQUIRED')
    out=Path(output)/event['event_id'].replace(':','_');out.mkdir(parents=True,exist_ok=False)
    np.save(out/'winner_draws.npy',draws,allow_pickle=False)
    save(out/'inputs.json',{'identity':identity,'features':features,'source_fetches':package['source_fetches'],'model_sha256':package['model_sha256']})
    save(out/'manifest.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()})
    home=p_home>=.5
    return {'model_id':mid,'model_winner':event['home_team'] if home else event['away_team'],
        'model_p':float(p_home if home else 1-p_home),'sim_p':sim['home_win_probability'] if home else 1-sim['home_win_probability'],
        'analytic_p':float(p_home if home else 1-p_home),'stochastic_sim_p':sim['home_win_probability'] if home else 1-sim['home_win_probability'],
        'projected_margin':(float(margin) if home else -float(margin)) if margin is not None else None,
        'projected_total':float(total) if total is not None else None,'forecast_tier':'REDUCED','dose':0.,
        'data_quality':package['data_grade'],'coverage_label':'CURRENT_RESEARCH; INDEPENDENT_MARGIN_TOTAL_HEADS_NOT_JOINT_SCORE_EXPECTATIONS',
        'model_state_config_hash':package['model_sha256'],'input_snapshot_hash':digest(features),'model_input_snapshot':features,
        'simulation':{'binary':sim,'draw_directory':str(out),'joint_scores':None},'warnings':list(limitations)+package.get('limitations',[]),
        'diagnostics':{'home_win':float(p_home),'home_margin':margin,'total':total,'package_sha256':ctx['package_sha256'],'model_lineage':package['model_lineage']},
        'provenance':{'source_fetches':package['source_fetches']},'action_authority':False}
