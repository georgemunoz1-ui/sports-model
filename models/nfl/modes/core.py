from __future__ import annotations
import hashlib, math
import numpy as np
from ..contextual.recovered_inference import digest

LIVE_FEATURES=['home_score','away_score','margin','seconds_remaining','quarter_seconds_remaining','quarter','possession_home','yardline_100','down','yards_to_go','home_timeouts','away_timeouts','pregame_logit','margin_time_scaled','possession_field_position']
CLASSES=['AWAY_WIN','HOME_WIN','TIE']

def implied(odds):
    x=float(odds)
    if not math.isfinite(x) or abs(x)<100:raise ValueError('INVALID_AMERICAN_ODDS')
    return -x/(100-x) if x<0 else 100/(100+x)

def devig(home,away):
    h,a=implied(home),implied(away)
    return h/(h+a)

def ensemble(model,football,market):
    if set(football)!={'home_win','home_margin','total_points'}:raise ValueError('FOOTBALL_SCHEMA')
    if set(market)!={'home_win','home_margin','total_points'}:raise ValueError('MARKET_SCHEMA')
    return {k:model['weights'][k]*float(football[k])+(1-model['weights'][k])*float(market[k]) for k in football}

def state_features(state,pregame_home_p):
    required={'home_score','away_score','seconds_remaining','quarter_seconds_remaining','quarter','possession','yardline_100','down','yards_to_go','home_timeouts','away_timeouts'}
    if set(state)!=required:raise ValueError('EXACT_LIVE_STATE_SCHEMA_REQUIRED')
    s=state
    numeric=[s[k] for k in required-{'possession'}]
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in numeric):raise ValueError('LIVE_FINITE_NUMERIC_STATE')
    for k in ['home_score','away_score','quarter','down','home_timeouts','away_timeouts']:
        if int(s[k])!=s[k]:raise ValueError('LIVE_INTEGER_STATE:'+k)
    if s['possession'] not in {'HOME','AWAY'}:raise ValueError('LIVE_POSSESSION')
    if not 0<=s['home_score']<=100 or not 0<=s['away_score']<=100:raise ValueError('LIVE_SCORE_RANGE')
    if s['quarter'] not in range(1,6) or not 1<=s['down']<=4 or not 0<=s['yardline_100']<=100 or not 0<=s['yards_to_go']<=100:raise ValueError('LIVE_SCRIMMAGE_STATE_RANGE')
    if not 0<=s['home_timeouts']<=3 or not 0<=s['away_timeouts']<=3:raise ValueError('LIVE_TIMEOUT_RANGE')
    q=s['quarter'];qr=s['quarter_seconds_remaining'];sec=s['seconds_remaining']
    if not 0<=qr<=900 or not 0<=sec<=3600:raise ValueError('LIVE_CLOCK_RANGE')
    if q<=4 and abs(sec-((4-q)*900+qr))>1:raise ValueError('LIVE_CLOCK_INCONSISTENT')
    if q==5 and sec!=0:raise ValueError('LIVE_OVERTIME_CLOCK')
    if not 0<pregame_home_p<1:raise ValueError('LIVE_PREGAME_PRIOR')
    margin=s['home_score']-s['away_score'];ph=float(s['possession']=='HOME')
    return [s['home_score'],s['away_score'],margin,sec,qr,q,ph,s['yardline_100'],s['down'],s['yards_to_go'],s['home_timeouts'],s['away_timeouts'],math.log(pregame_home_p/(1-pregame_home_p)),margin/math.sqrt(sec/60+1),(2*ph-1)*(100-s['yardline_100'])/100]

def export_hgb(estimator,temperature):
    # Portable numeric trees; no executable pickle in the deployment artifact.
    if list(estimator.classes_)!=[0,1,2]:raise ValueError('LIVE_CLASS_MAPPING')
    trees=[]
    for iteration in estimator._predictors:
        group=[]
        for tree in iteration:
            if np.any(tree.nodes['is_categorical']):raise ValueError('CATEGORICAL_TREE_UNSUPPORTED')
            group.append([[float(n['value']),int(n['feature_idx']),float(n['num_threshold']),int(n['missing_go_to_left']),int(n['left']),int(n['right']),int(n['is_leaf'])] for n in tree.nodes])
        trees.append(group)
    return {'feature_names':LIVE_FEATURES,'classes':CLASSES,'initial_logits':np.ravel(estimator._baseline_prediction).tolist(),'trees':trees,'temperature':float(temperature)}

def predict_live(export,frame):
    x=np.asarray(frame,float)
    if x.ndim==1:x=x[None,:]
    if x.shape[1]!=len(LIVE_FEATURES) or not np.isfinite(x).all():raise ValueError('LIVE_MATRIX')
    logits=np.tile(export['initial_logits'],(len(x),1))
    for group in export['trees']:
        for c,nodes in enumerate(group):
            tree=np.asarray(nodes,float);at=np.zeros(len(x),dtype=int);active=np.ones(len(x),dtype=bool)
            while active.any():
                rows=np.flatnonzero(active);n=tree[at[rows]];leaf=n[:,6].astype(bool)
                logits[rows[leaf],c]+=n[leaf,0];active[rows[leaf]]=False
                rows=rows[~leaf];n=n[~leaf]
                if len(rows):
                    value=x[rows,n[:,1].astype(int)];left=np.where(np.isnan(value),n[:,3].astype(bool),value<=n[:,2]);at[rows]=np.where(left,n[:,4],n[:,5]).astype(int)
    logits/=export['temperature'];logits-=logits.max(axis=1,keepdims=True);p=np.exp(logits);return p/p.sum(axis=1,keepdims=True)

def categorical_simulation(probabilities,identity,n=100000):
    p=np.asarray(probabilities,float)
    if p.shape!=(3,) or not np.isfinite(p).all() or (p<0).any() or not np.isclose(p.sum(),1,atol=1e-12) or not isinstance(n,int) or n<1:raise ValueError('LIVE_SIMULATION_PARAMETERS')
    seed=int(digest({'identity':identity,'distribution':'FITTED_THREE_WAY_OUTCOME','n':n})[:16],16)
    draws=np.random.default_rng(seed).choice(3,size=n,p=p).astype('u1')
    return draws,{'seed':seed,'n':n,'classes':CLASSES,'probabilities':dict(zip(CLASSES,np.bincount(draws,minlength=3)/n)),'sha256':hashlib.sha256(draws.tobytes()).hexdigest(),'target':'FINAL_OUTCOME_INCLUDING_OVERTIME','simulation_type':'CATEGORICAL_OUTCOME_DRAWS_NOT_DRIVE_OR_SCORE_SIMULATION'}

def state_from_nflverse(row,event):
    if row['game_id']!=event['event_id'] or row['home_team']!=event['home_team'] or row['away_team']!=event['away_team']:raise ValueError('PBP_EVENT_BINDING')
    ph=row['posteam']==event['home_team']
    if row['posteam'] not in {event['home_team'],event['away_team']}:raise ValueError('PBP_POSSESSION_REQUIRED')
    q=float(row['qtr']);qr=float(row['quarter_seconds_remaining']);raw_sec=float(row['game_seconds_remaining'])
    if q==5 and abs(raw_sec-qr)>1:raise ValueError('PBP_OVERTIME_CLOCK')
    state={'home_score':float(row['posteam_score'] if ph else row['defteam_score']),'away_score':float(row['defteam_score'] if ph else row['posteam_score']),'seconds_remaining':0.0 if q==5 else raw_sec,'quarter_seconds_remaining':qr,'quarter':q,'possession':'HOME' if ph else 'AWAY','yardline_100':float(row['yardline_100']),'down':float(row['down']),'yards_to_go':float(row['ydstogo']),'home_timeouts':float(row['home_timeouts_remaining']),'away_timeouts':float(row['away_timeouts_remaining'])}
    state_features(state,.5)
    return state
