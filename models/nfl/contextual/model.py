"""Jointly fitted NFL context heads and final-score residual simulation."""
from __future__ import annotations
import hashlib
import json
import gzip,base64
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression,Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from .base_features import MODEL_FEATURES
from .features import QB_FEATURES,AVAIL_FEATURES,TRAVEL_FEATURES
from .recovered_inference import predict,digest

FAMILIES={'base':[],'qb':QB_FEATURES,'availability':AVAIL_FEATURES,'travel':TRAVEL_FEATURES,'combined':QB_FEATURES+AVAIL_FEATURES+TRAVEL_FEATURES}
TARGETS=('home_win','home_margin','total_points')

def load_artifact(path):
    with open(path) as f:obj=json.load(f)
    if obj.get('encoding')=='GZIP_BASE64':
        raw=gzip.decompress(base64.b64decode(obj['payload']))
        if hashlib.sha256(raw).hexdigest()!=obj['sha256']:raise ValueError('PACKED_MODEL_HASH')
        obj=json.loads(raw)
    return obj

def fit(frame,arm,design):
    names=list(MODEL_FEATURES)+FAMILIES[arm]
    complete=frame.dropna(subset=list(TARGETS))
    if complete.empty or not set(complete.home_win.unique())=={0.,1.}:raise ValueError('BINARY_TRAINING_POPULATION_REQUIRED')
    heads={}
    for target in TARGETS:
        est=LogisticRegression(C=design['fit_rule']['logistic_C'],max_iter=2000) if target=='home_win' else Ridge(alpha=design['fit_rule']['ridge_alpha'])
        pipe=make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),StandardScaler(),est)
        pipe.fit(complete[names],complete[target]);imp,scale,model=pipe.steps[0][1],pipe.steps[1][1],pipe.steps[2][1]
        heads[target]={'impute':imp.statistics_.tolist(),'center':scale.mean_.tolist(),'scale':scale.scale_.tolist(),'coefficient':np.ravel(model.coef_).tolist(),'intercept':float(np.ravel(model.intercept_)[0])}
    return {'model_id':f'nfl.integrated_context.{arm}.v1.research','feature_names':names,'heads':heads,'training_rows':len(complete),'training_seasons':sorted(map(int,complete.season.unique())),'design_sha256':digest(design),'market_input':False}

def predict_frame(params,frame):
    x=frame[params['feature_names']].to_numpy(float);out={}
    for t,head in params['heads'].items():
        z=(np.where(np.isnan(x),head['impute'],x)-head['center'])/head['scale']
        linear=z@np.array(head['coefficient'])+head['intercept']
        out[t]=1/(1+np.exp(-linear)) if t=='home_win' else linear
    return pd.DataFrame(out,index=frame.index)

def score(frame):
    binary=frame[frame.home_win.notna()];p=np.clip(binary.p_home,1e-12,1-1e-12);y=binary.home_win
    return {'games':len(frame),'binary_games':len(binary),'ties_excluded_from_binary':len(frame)-len(binary),'brier':float(np.mean((p-y)**2)),'log_loss':float(np.mean(-y*np.log(p)-(1-y)*np.log1p(-p))),'winner_accuracy':float(np.mean((p>.5)==y)),'margin_mae':float(np.mean(abs(frame.pred_margin-frame.home_margin))),'margin_rmse':float(np.sqrt(np.mean((frame.pred_margin-frame.home_margin)**2))),'total_mae':float(np.mean(abs(frame.pred_total-frame.total_points)))}

def simulate_scores(margin,total,residual_pairs,identity,n=100000):
    """Empirical joint final-score residuals: overtime is already in the target.

    No extra overtime is appended and no tied score is converted to a winner.
    Rounding and nonnegative clipping are explicit and may shift sampled means.
    This is an uncalibrated empirical score distribution, not a drive model.
    """
    pool=np.asarray(residual_pairs,float)
    if pool.ndim!=2 or pool.shape[1]!=2 or len(pool)<100 or not np.isfinite(pool).all():raise ValueError('RESIDUAL_POOL_INVALID')
    means=np.array([(total+margin)/2,(total-margin)/2])
    if (means<0).any():raise ValueError('NEGATIVE_SCORE_CENTER')
    seed=int(digest({'identity':identity,'distribution':'JOINT_FINAL_SCORE_OOF_RESIDUAL_V1','n':n})[:16],16)
    rng=np.random.default_rng(seed);center=pool.mean(axis=0)
    scores=np.rint(np.maximum(0,means+pool[rng.integers(len(pool),size=n)]-center)).astype('<i2')
    m=scores[:,0]-scores[:,1];t=scores.sum(axis=1);h=float(np.mean(m>0));a=float(np.mean(m<0));tie=float(np.mean(m==0))
    summary={'seed':seed,'n':n,'p_home_win':h,'p_away_win':a,'p_tie':tie,'p_home_win_conditional_non_tie':h/(h+a),'mean_home_score':float(scores[:,0].mean()),'mean_away_score':float(scores[:,1].mean()),'mean_margin':float(m.mean()),'mean_total':float(t.mean()),'margin_quantiles':np.quantile(m,[.05,.1,.25,.5,.75,.9,.95]).tolist(),'total_quantiles':np.quantile(t,[.05,.1,.25,.5,.75,.9,.95]).tolist(),'residual_count':len(pool),'residual_center_removed':center.tolist(),'sha256':hashlib.sha256(scores.tobytes()).hexdigest(),'target':'FINAL_SCORE_INCLUDING_OVERTIME','settlement_validation':'NOT_ESTABLISHED','discrete_key_number_calibration':'NOT_ESTABLISHED'}
    return scores,summary

def simulate_joint(margin,total,p_home_non_tie,residual_pairs,tie_rate,identity,n=100000):
    """Probability-aligned final-score kernel, a separately declared v2 sampler.

    Fit the tie mass from observed historical final ties. The binary fitted head
    controls the non-tie outcome mass. Residual-score support supplies conditional
    score shapes. No coin flip changes a tied score; no extra OT is appended.
    The means of this joint model can differ from the separate Ridge centers.
    """
    pool=np.asarray(residual_pairs,float);centers=np.array([(total+margin)/2,(total-margin)/2])
    if pool.ndim!=2 or pool.shape[1]!=2 or not np.isfinite(pool).all() or len(pool)<100:raise ValueError('RESIDUAL_POOL_INVALID')
    if (centers<0).any() or not 0<=p_home_non_tie<=1 or not 0<=tie_rate<1:raise ValueError('JOINT_PARAMETERS_INVALID')
    support=np.rint(np.maximum(0,centers+pool-pool.mean(axis=0))).astype('<i2')
    signs=np.sign(support[:,0]-support[:,1]);strata=[support[signs==s] for s in [1,-1,0]]
    weights=np.array([(1-tie_rate)*p_home_non_tie,(1-tie_rate)*(1-p_home_non_tie),tie_rate])
    if any(len(v)==0 and w>0 for v,w in zip(strata,weights)):raise ValueError('JOINT_SCORE_SUPPORT_MISSING')
    seed=int(digest({'identity':identity,'distribution':'OUTCOME_ALIGNED_FINAL_SCORE_KERNEL_V2','n':n})[:16],16)
    rng=np.random.default_rng(seed);categories=rng.choice(3,size=n,p=weights);scores=np.empty((n,2),dtype='<i2')
    for k,v in enumerate(strata):
        mask=categories==k
        if mask.any():scores[mask]=v[rng.integers(len(v),size=int(mask.sum()))]
    m=scores[:,0]-scores[:,1];t=scores.sum(axis=1);h=float(np.mean(m>0));a=float(np.mean(m<0));tie=float(np.mean(m==0))
    return scores,{'seed':seed,'n':n,'distribution':'OUTCOME_ALIGNED_FINAL_SCORE_KERNEL_V2','target':'FINAL_SCORE_INCLUDING_OVERTIME','p_home_win':h,'p_away_win':a,'p_tie':tie,'p_home_win_conditional_non_tie':h/(h+a),'model_home_win_unconditional':float(weights[0]),'model_away_win_unconditional':float(weights[1]),'model_tie':float(tie_rate),'tie_model':'JEFFREYS_BETA_RATE_FROM_TRAINING_FINALS; UNCONDITIONAL','mean_home_score':float(scores[:,0].mean()),'mean_away_score':float(scores[:,1].mean()),'mean_margin':float(m.mean()),'mean_total':float(t.mean()),'margin_quantiles':np.quantile(m,[.05,.1,.25,.5,.75,.9,.95]).tolist(),'total_quantiles':np.quantile(t,[.05,.1,.25,.5,.75,.9,.95]).tolist(),'conditional_score_support_counts':list(map(len,strata)),'sha256':hashlib.sha256(scores.tobytes()).hexdigest(),'settlement_validation':'NOT_ESTABLISHED','discrete_key_number_calibration':'NOT_ESTABLISHED','conditional_score_means_differ_from_ridge_centers':True}

def price_contract(scores,market_type,side,line=None,period='FULL_GAME',tie_policy=None):
    """Downstream-only empirical settlement; fees/prices never enter generation."""
    if period!='FULL_GAME':raise ValueError('PERIOD_UNSUPPORTED')
    h,a=scores[:,0],scores[:,1]
    if market_type=='SPREAD':
        if side not in {'HOME','AWAY'}:raise ValueError('SIDE')
        v=(h-a if side=='HOME' else a-h)+float(line)
    elif market_type=='TOTAL':
        if side not in {'OVER','UNDER'}:raise ValueError('SIDE')
        v=(h+a-float(line))*(1 if side=='OVER' else -1)
    elif market_type=='MONEYLINE':
        if side not in {'HOME','AWAY'} or tie_policy not in {'REFUND','LOSS'}:raise ValueError('MONEYLINE_TIE_CONTRACT_REQUIRED')
        v=h-a if side=='HOME' else a-h
    else:raise ValueError('MARKET_TYPE')
    w=float(np.mean(v>0));p=float(np.mean(v==0));l=float(np.mean(v<0))
    if market_type=='MONEYLINE' and tie_policy=='LOSS':l+=p;p=0.
    return {'win':w,'push_or_refund':p,'loss':l,'scope':'UNVALIDATED_EMPIRICAL_SETTLEMENT_DIAGNOSTIC','fees_included':False}
