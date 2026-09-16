"""Explicit V13 + frozen d_logistic_2f research adapter; not Phase 1.1."""
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch
import numpy as np
from pipelines.mlb.current import instant, digest

ROOT=Path(__file__).resolve().parents[3]
MODEL_ID='mlb.v13_and_d_logistic_2f.research.v1'

def _load():
    rp=ROOT/'data/mlb/current_v1/runtime.json'
    config=json.loads(rp.read_text())
    pp=ROOT/config['package_path']
    if digest(pp)!=config['package_sha256']:raise ValueError('PACKAGE_HASH_MISMATCH')
    p=json.loads(pp.read_text())
    for name,h in p['pins'].items():
        if digest(ROOT/name)!=h:raise ValueError('INPUT_OR_CODE_PIN_MISMATCH:'+name)
    return p

def load_schedule(card_date,as_of):
    p=_load()
    if card_date!=p['slate_date']:raise ValueError('SLATE_NOT_ACQUIRED')
    if instant(p['captured_at'])>instant(as_of):raise ValueError('PACKAGE_AFTER_CUTOFF')
    if (instant(as_of)-instant(p['captured_at'])).total_seconds()>p['ttl_hours']*3600:raise ValueError('PACKAGE_EXPIRED')
    return p['events']

def build_context(events,as_of,*args):
    if args and len(args)>1 and args[1]:raise ValueError('MANUAL_OVERRIDES_UNSUPPORTED')
    p=_load()
    if events!=p['events']:raise ValueError('EVENT_PACKAGE_MISMATCH')
    form=json.loads((ROOT/p['form_path']).read_text())
    if instant(form['built_at'])>instant(as_of):raise ValueError('FORM_AFTER_CUTOFF')
    if form['through_date']!=(dt.date.fromisoformat(p['slate_date'])-dt.timedelta(days=1)).isoformat():raise ValueError('D1_FORM_MISSING')
    return {'package':p,'form':form,'cutoff':as_of,'pit_provenance':{'pit_mode':'CURRENT_RESEARCH_STAGED_ASSIMILATION','pit_reconstruction_supported':False,'adapter_source':__name__,'data_vintage_basis':'MIXED_CANONICAL_AND_STAGED_RESULTS; CAPPED_STALE_STARTERS','source_fetches':p['source_fetches']}}

def capture_sim(engine,*args):
    """Retain arrays at the pinned function return without changing its bytes/RNG."""
    captured={};previous=sys.getprofile()
    def record(frame,event,arg):
        if frame.f_code is engine.v13_sim.__code__ and event=='return':
            for name in ('ra','rh','hw'):captured[name]=frame.f_locals[name].copy()
    try:
        sys.setprofile(record)
        result=engine.v13_sim(*args)
    finally:sys.setprofile(previous)
    return result,captured

def forecast_event(event,context,simulations=100000):
    if simulations<1:raise ValueError('INVALID_SIMULATION_COUNT')
    p=context['package'];form=context['form'];cutoff=context['cutoff']
    if instant(event['start_time_utc'])<=instant(cutoff):raise ValueError('POST_START')
    sys.path.insert(0,str(ROOT/'harness'))
    import build_board_0825 as B
    import run_v13_historical as V
    import mlb_daily_coordinator as C
    pid=B.name_to_pid()
    # The legacy builder hardcodes August 25. Bind the declared run date only for
    # this synchronous resolution and restore it even if the resolver raises.
    with patch.object(B,'SLATE_DATE',p['slate_date']):
        sa,ast,_,ad=B.starter(pid,event['away_starter'],now=instant(cutoff))
        sh,hst,_,hd=B.starter(pid,event['home_starter'],now=instant(cutoff))
    a=form['teams'][event['away_team']];h=form['teams'][event['home_team']]
    pf=C.park_factor(json.loads((ROOT/B.PARKS).read_text()),event['home_team'])
    inputs={'sp_away':sa,'sp_home':sh,'away_form':a,'home_form':h,'park_factor':pf,'event_id':event['event_id'],'cutoff':cutoff,'model_id':MODEL_ID,'n':simulations}
    ih=hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest();seed=int(ih[:16],16)
    sim,draws=capture_sim(V,sa,sh,a['rf'],a['ra'],h['rf'],h['ra'],pf,seed,simulations)
    analytic=V.candidate_p(a['rf'],a['ra'],h['rf'],h['ra'],sa['era'],sa['gs'],sh['era'],sh['gs'],V.load_candidate_beta())
    before_a=form['before_teams'][event['away_team']];before_h=form['before_teams'][event['home_team']]
    before_p=V.candidate_p(before_a['rf'],before_a['ra'],before_h['rf'],before_h['ra'],sa['era'],sa['gs'],sh['era'],sh['gs'],V.load_candidate_beta())
    home=analytic>=.5;win=event['home_team'] if home else event['away_team']
    cap=sum(x['disposition']!='FRESH' for x in (ad,hd))
    diagnostics={'analytic_model_id':'d_logistic_2f','simulation_model_id':'mlb.winner.CHAMPION_V13','comparison':'DIFFERENT_MODELS_NOT_ANALYTIC_MC_CONVERGENCE','analytic_home_win':analytic,'analytic_before_assimilation_home':before_p,'assimilation_probability_change_pp':100*(analytic-before_p),'sim_home_win':sim['p_home'],'seed':seed,'simulations':simulations,'starter_dispositions':{'away':ad,'home':hd},'starter_status':{'away':ast,'home':hst},'capped_starter_slots':cap,'form_through':form['through_date'],'assimilated_results':form['assimilated_rows'],'form_before':{t:form['before_teams'][t] for t in (event['away_team'],event['home_team'])},'form_used':{t:form['teams'][t] for t in (event['away_team'],event['home_team'])},'canonical_prospective_eligible':False}
    output=os.environ.get('MLB_DRAW_OUTPUT')
    if not output:raise ValueError('MLB_DRAW_OUTPUT_REQUIRED_FOR_DURABLE_SIMULATION')
    out=Path(output)/event['event_id'].replace(':','_');out.mkdir(parents=True,exist_ok=False)
    for name,data in draws.items():np.save(out/(name+'.npy'),data,allow_pickle=False)
    (out/'inputs.json').write_text(json.dumps(inputs,indent=2)+'\n')
    (out/'diagnostics.json').write_text(json.dumps(diagnostics,indent=2)+'\n')
    (out/'manifest.json').write_text(json.dumps({f.name:digest(f) for f in out.iterdir()},indent=2)+'\n')
    return {'model_id':MODEL_ID,'model_winner':win,'model_p':analytic if home else 1-analytic,'sim_p':sim['p_home'] if home else 1-sim['p_home'],'forecast_tier':'REDUCED','data_quality':'CURRENT_TEAM_FORM_PARTIAL_STARTERS','dose':0.0,'projected_home_runs':sim['proj_home'],'projected_away_runs':sim['proj_away'],'projected_total':'UNSUPPORTED_SETTLEMENT','spread_or_runline':'UNSUPPORTED_SETTLEMENT','total_market':'UNSUPPORTED_SETTLEMENT','warnings':['RESEARCH_ONLY_GLOBAL_HEALTH_RED','DIFFERENT_MODELS_NOT_CONVERGENCE','STARTER_CAPS:'+str(cap),'LINEUP_AND_INJURY_EFFECTS_UNVERIFIED','V13_TIE_PROXY_NOT_FULL_EXTRA_INNINGS','STAGED_RESULTS_NOT_PROMOTED_TO_TIER1'],'input_snapshot_hash':ih,'model_state_config_hash':hashlib.sha256(json.dumps(p['pins'],sort_keys=True).encode()).hexdigest(),'model_input_snapshot':inputs,'diagnostics':diagnostics,'simulation':{'count':simulations,'seed':seed,'draw_directory':str(out),'home_win_probability':sim['p_home']},'coverage_label':'CURRENT_FORM_RESEARCH; NOT_PHASE1_1','provenance':{'source_fetches':p['source_fetches']},'action_authority':False}
