"""Inference boundaries for explicitly market-aware pregame and live modes."""
from __future__ import annotations
import copy,hashlib,math,re
from pathlib import Path
from .core import devig,ensemble,state_features,predict_live,categorical_simulation,CLASSES
from ..contextual.recovered_inference import digest,utc,bernoulli_simulation
from ..contextual.model import simulate_joint

def receipt(packet,event,cutoff,*,pregame):
    if not isinstance(packet,dict):raise ValueError('MODE_INPUT_PACKET_REQUIRED')
    for k in ['event_id','home_team','away_team']:
        expected=event[k]
        if packet.get(k)!=expected:raise ValueError('MODE_EVENT_BINDING:'+k)
    if not packet.get('source') or not re.fullmatch('[0-9a-f]{64}',str(packet.get('source_sha256',''))):raise ValueError('MODE_SOURCE_RECEIPT_REQUIRED')
    observed=utc(packet['observed_at_utc']);retrieved=utc(packet['retrieved_at_utc']);cut=utc(cutoff)
    if observed>retrieved or retrieved>cut:raise ValueError('MODE_POST_CUTOFF_RECEIPT')
    if pregame and observed>=utc(event['start_time_utc']):raise ValueError('PREGAME_MARKET_AFTER_START')
    return (cut-observed).total_seconds()

def market_values(packet,event,cutoff):
    age=receipt(packet,event,cutoff,pregame=True)
    if packet.get('period')!='FULL_GAME' or packet.get('odds_format')!='AMERICAN' or packet.get('state')!='PREGAME':raise ValueError('MARKET_PRODUCT_SCHEMA')
    fields=packet['quotes']
    if set(fields)!={'home_moneyline','away_moneyline','home_spread','total_line'}:raise ValueError('EXACT_MARKET_QUOTE_SCHEMA')
    if not math.isfinite(float(fields['home_spread'])) or not math.isfinite(float(fields['total_line'])) or float(fields['total_line'])<=0:raise ValueError('MARKET_POINT_LINE')
    values={'home_win':devig(fields['home_moneyline'],fields['away_moneyline']),'home_margin':-float(fields['home_spread']),'total_points':float(fields['total_line'])}
    return values,{'packet_sha256':digest(packet),'source_sha256':packet['source_sha256'],'observed_at_utc':packet['observed_at_utc'],'age_seconds':age,'quote_age_warning':age>3600,'devig':'PROPORTIONAL','historical_fit_quote_time':'UNARCHIVED_PREGAME; TIMESTAMPED_NEW_INPUT_DOES_NOT_REPAIR_HISTORICAL_PIT','wager_contract_validated':False}

def code_hashes():
    folder=Path(__file__).parent
    return {name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in ['core.py','runtime.py']}

def enhanced(football,model,market,event,cutoff,n):
    if utc(cutoff)>=utc(event['start_time_utc']):raise ValueError('NOT_PREGAME')
    if football['model_id']!=model['football_model_id'] or football['model_artifact_sha256']!=model['football_artifact_sha256']:raise ValueError('ENSEMBLE_FOOTBALL_ARTIFACT_MISMATCH')
    if football['cutoff_utc']!=cutoff or football['event']!=event:raise ValueError('ENSEMBLE_FOOTBALL_CUTOFF_MISMATCH')
    mv,audit=market_values(market,event,cutoff);p=ensemble(model,football['prediction'],mv);ch=code_hashes();identity=digest({'model':model,'football_identity':football['identity'],'market':market,'event':event,'cutoff':cutoff,'code_hashes':ch})
    if 'original_quote_observed_at_utc' in market and market['original_quote_observed_at_utc'] is None:
        audit.update(original_quote_time_unknown=True,quote_age_warning=True,executable_now_verified=False)
    draws,wi=bernoulli_simulation(p['home_win'],identity,n);scores,si=simulate_joint(p['home_margin'],p['total_points'],p['home_win'],model['final_score_residuals'],model['tie_rate'],identity,n)
    b=copy.deepcopy(football);b.update({'schema':'nfl.enhanced_pregame_forecast.v1','mode':'enhanced_pregame','model_id':model['model_id'],'model_artifact_sha256':digest(model),'identity':identity,'selected_arm':'market_ensemble','prediction':p,'score_centers':{'home':(p['total_points']+p['home_margin'])/2,'away':(p['total_points']-p['home_margin'])/2},'winner_simulation':wi,'score_simulation':si,'market_input':True,'market_snapshot':market,'market_benchmark':mv,'market_audit':audit,'football_reference':{'model_id':football['model_id'],'identity':football['identity'],'model_artifact_sha256':football['model_artifact_sha256'],'prediction':football['prediction'],'contribution_trace':football['contribution_trace']},'contribution_trace':{k:{'football_weight':model['weights'][k],'football_term':model['weights'][k]*football['prediction'][k],'market_term':(1-model['weights'][k])*mv[k]} for k in p},'mode_code_hashes':ch,'full_game_settlement_validated':False})
    b['feature_coverage']['market_columns']=3;b['feature_coverage']['football_weights_by_target']=model['weights'];b['warnings']+=['MARKET_AWARE_MODEL_EXPLICIT','REUSED_RETROSPECTIVE_FIT_NOT_PROSPECTIVE_VALIDATION']
    from ..contextual.capabilities import describe_ensemble
    b['capability_report']=describe_ensemble(football['capability_report'],model,football['prediction'],mv,event,cutoff)
    # This comparison belongs to the football-only parent, not the market blend.
    if 'flip_diagnostics' in b:
        b['football_reference']['flip_diagnostics']=b.pop('flip_diagnostics')
    return b,draws,scores

def live(model,market,snapshot,event,cutoff,n):
    if int(event['event_id'].split('_')[0])<=max(model['training_seasons']):raise ValueError('LIVE_MODEL_TRAINING_OVERLAPS_EVENT_SEASON')
    if utc(cutoff)<utc(event['start_time_utc']):raise ValueError('GAME_NOT_STARTED_FOR_LIVE')
    mv,ma=market_values(market,event,cutoff);age=receipt(snapshot,event,cutoff,pregame=False)
    if utc(snapshot['observed_at_utc'])<utc(event['start_time_utc']):raise ValueError('LIVE_STATE_BEFORE_KICKOFF')
    if age>model['max_input_age_seconds']:raise ValueError('STALE_LIVE_STATE')
    if snapshot.get('state_boundary')!='PRE_PLAY' or snapshot.get('game_status')!='IN_PROGRESS':raise ValueError('LIVE_STATE_BOUNDARY')
    effective=utc(snapshot['effective_at_utc'])
    if effective>utc(snapshot['observed_at_utc']) or effective<utc(event['start_time_utc']) or (utc(cutoff)-effective).total_seconds()>model['max_input_age_seconds']:raise ValueError('LIVE_EFFECTIVE_TIME')
    x=state_features(snapshot['features'],mv['home_win']);p=predict_live(model['model'],x)[0];ch=code_hashes();identity=digest({'model':model,'market':market,'snapshot':snapshot,'event':event,'cutoff':cutoff,'code_hashes':ch});draws,sim=categorical_simulation(p,identity,n)
    b={'schema':'nfl.live_forecast.v1','mode':'live','model_id':model['model_id'],'model_artifact_sha256':digest(model),'event':event,'cutoff_utc':cutoff,'identity':identity,'prediction_target':model['prediction_target'],'prediction':dict(zip(CLASSES,map(float,p))),'winner_simulation':sim,'score_simulation':{'status':'UNSUPPORTED_WINNER_ONLY_MODEL'},'features':dict(zip(model['model']['feature_names'],map(float,x))),'market_input':True,'market_role':'PREGAME_MARKET_PRIOR_NOT_LIVE_ODDS','market_snapshot':market,'market_audit':ma,'live_snapshot':snapshot,'live_input_age_seconds':age,'mode_code_hashes':ch,'research_only':True,'canonical_prospective_eligible':False,'action_authority':False,'full_game_settlement_validated':False,'warnings':model['limitations']}
    return b,draws,None
