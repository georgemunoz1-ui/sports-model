"""Shared card selection, preserving frozen engine code and challenger identities."""
import copy,hashlib,json
from .selection import select,require_default

def apply_default(league,event,raw):
    league=league.lower();result=copy.deepcopy(raw)
    if league=='nfl':
        selection=require_default(league,raw['model_id'])
    elif league=='mlb':
        selection=select(league)
        d=result['diagnostics']
        if d.get('simulation_model_id')!='mlb.winner.CHAMPION_V13':raise ValueError('SELECTED_V13_OUTPUT_UNAVAILABLE')
        p=d['sim_home_win']
        if not 0<=p<=1:raise ValueError('INVALID_SELECTED_PROBABILITY')
        home=p>=.5;selected_p=p if home else 1-p
        d['challengers']=[{'model_id':'d_logistic_2f','home_win_probability':d['analytic_home_win'],'role':'CHALLENGER_ONLY'}]
        d['producer_bundle_model_id']=raw['model_id']
        d['comparison']='MONTE_CARLO_ESTIMATE_NO_INDEPENDENT_ANALYTIC_VALUE'
        result.update(model_id=selection['default_model_id'],model_winner=event['home_team'] if home else event['away_team'],model_p=selected_p,sim_p=selected_p,analytic_p=None,stochastic_sim_p=selected_p,probability_estimator='MONTE_CARLO_ONLY')
        result['warnings']=[w for w in result.get('warnings',[]) if w!='DIFFERENT_MODELS_NOT_CONVERGENCE']+['TESTED_INCUMBENT_NOT_ESTABLISHED_BETTING_EDGE','D_LOGISTIC_2F_CHALLENGER_ONLY']
    else:
        selection=require_default(league,raw.get('model_id'),week=event.get('week'),division=event.get('division_scope'))
    result.setdefault('diagnostics',{})['default_selection']=selection
    result['selection_hash']=selection['policy_sha256']
    result['action_authority']=False;result['dose']=0.0
    return result

def wnba_predict(model,team_state,league_state,slate,season=2026):
    """Selected path to the existing pinned WNBA fitter; preserves all data gates."""
    selection=select('wnba')
    from harness.wnba_model_v1 import predict_slate
    rows=predict_slate(model,team_state,league_state,slate,season)
    return {'model_id':selection['default_model_id'],'selection':selection,'games':rows,'action_authority':False}
