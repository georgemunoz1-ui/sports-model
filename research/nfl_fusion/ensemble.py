"""Target-separated, chronological constrained stacking. No live-default mutation."""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit,logit
from .contracts import digest,validate_prediction_packet,TARGETS

CONTEXT = ['CONTEXT_'+x for x in ('BASE','QB','AVAILABILITY','TRAVEL','COMBINED')]
CANDIDATE_MAP = {'ridge_base':'PR36_SCORING_RIDGE','ridge_coaching':'PR36_COACHING_RIDGE','xgb_base':'PR36_SCORING_XGBOOST'}
CANDIDATES=list(CANDIDATE_MAP.values())


def align(context,candidates,schedule):
    """Never combine margin units with probability or duplicate one game as two rows."""
    c=context.copy();q=candidates.copy()
    for data in (c,q):
        if data.duplicated(['game_id','arm']).any():raise ValueError('DUPLICATE_ARM_GAME')
        if not data.season.between(2019,2024).all():raise ValueError('EXCLUDED_SEASON')
    if set(c.arm)!=set(CONTEXT):raise ValueError('CONTEXT_ARM_SET_MISMATCH')
    if set(q.arm)!=set(CANDIDATE_MAP):raise ValueError('CANDIDATE_ARM_SET_MISMATCH')
    if not (c.trained_through_season<c.season).all():raise ValueError('IN_SAMPLE_BASE_PREDICTION')
    q['arm']=q.arm.map(CANDIDATE_MAP)
    populations={arm:set(g.game_id) for arm,g in pd.concat([c[['arm','game_id']],q[['arm','game_id']]]).groupby('arm')}
    common=set.intersection(*populations.values());union=set.union(*populations.values())
    if common!=union:raise ValueError('ENSEMBLE_COHORT_MISMATCH')
    g=schedule[schedule.game_id.isin(common)].copy().set_index('game_id',verify_integrity=True).sort_index()
    if set(g.index)!=common:raise ValueError('SCHEDULE_ID_MISSING')
    g['home_margin']=g.home_score-g.away_score;g['total_points']=g.home_score+g.away_score
    g['home_win']=np.where(g.home_margin==0,np.nan,(g.home_margin>0).astype(float))
    if len(g)!=len(common):raise ValueError('COHORT_ID_MISMATCH')
    for arm,r in c.groupby('arm'):
        r=r.set_index('game_id').loc[g.index]
        if not np.array_equal(r.season,g.season):raise ValueError('SEASON_BINDING_MISMATCH')
        for target in ('home_win','home_margin','total_points'):
            if not np.allclose(r[target],g[target],equal_nan=True):raise ValueError('TARGET_RECONCILIATION:'+target)
        for name,col in [('p','p_home'),('m','pred_margin'),('t','pred_total')]:g[name+'__'+arm]=r[col].to_numpy(float)
    for arm,r in q.groupby('arm'):
        r=r.set_index('game_id').loc[g.index]
        if not np.array_equal(r.season,g.season):raise ValueError('SEASON_BINDING_MISMATCH')
        if not np.allclose(r.target_margin,g.home_margin):raise ValueError('CANDIDATE_MARGIN_ORIENTATION_MISMATCH')
        g['p__'+arm]=r.p_home_calibrated.to_numpy(float);g['m__'+arm]=r.predicted_margin.to_numpy(float)
    for prefix in ('p__','m__','t__'):
        values=g[[col for col in g if col.startswith(prefix)]].to_numpy(float)
        if not np.isfinite(values).all():raise ValueError('NONFINITE_ARM_PREDICTION')
        if prefix=='p__' and ((values<0)|(values>1)).any():raise ValueError('PROBABILITY_UNITS')
    return g.reset_index()


def weights(X,y,anchor=1,penalty=.001):
    X,y=np.asarray(X,float),np.asarray(y,float)
    if X.ndim!=2 or len(X)!=len(y) or len(y)<20 or not np.isfinite(X).all() or not np.isfinite(y).all():raise ValueError('INVALID_WEIGHT_FIT')
    a=np.zeros(X.shape[1]);a[anchor]=1
    def objective(w):return np.mean((X@w-y)**2)+penalty*np.sum((w-a)**2)
    def gradient(w):return 2*X.T@(X@w-y)/len(y)+2*penalty*(w-a)
    result=minimize(objective,a,jac=gradient,method='SLSQP',bounds=[(0,1)]*len(a),constraints={'type':'eq','fun':lambda w:w.sum()-1,'jac':lambda w:np.ones_like(w)},options={'ftol':1e-12,'maxiter':2000})
    if not result.success:raise ValueError('WEIGHT_OPTIMIZATION_FAILED:'+result.message)
    w=np.maximum(result.x,0);w/=w.sum()
    return w


def fit_calibration(p,y):
    z=logit(np.clip(np.asarray(p,float),1e-9,1-1e-9));y=np.asarray(y,float)
    def loss(v):
        s=z*v[0]+v[1]
        return np.mean(np.logaddexp(0,s)-y*s)+.001*((v[0]-1)**2+v[1]**2)
    res=minimize(loss,[1.,0.],method='L-BFGS-B',bounds=[(0,20),(-20,20)],options={'ftol':1e-14})
    if not res.success:raise ValueError('CALIBRATION_FAILED')
    return {'slope':float(res.x[0]),'intercept':float(res.x[1])}


def fit(frame,protocol):
    if not frame.season.between(2019,2022).all():raise ValueError('TEST_DATA_IN_FIT')
    tr=frame[frame.season.between(*protocol['weight_fit_years'])];cal=frame[frame.season.between(*protocol['calibration_years'])]
    if tr.empty or cal.empty or tr.season.max()>=cal.season.min():raise ValueError('CHRONOLOGICAL_SPLIT_REQUIRED')
    model={'schema':'nfl.target_aligned_ensemble.v1','protocol_sha256':digest(protocol),'heads':{},'research_only':True,'action_authority':False,'market_input':False,'official_release_eligible':False,
           'fit_game_ids':sorted(tr.game_id.tolist()),'calibration_game_ids':sorted(cal.game_id.tolist()),'trained_through_season':2022}
    for target,prefix,arms in [('home_win','p',CONTEXT+CANDIDATES),('home_margin','m',CONTEXT+CANDIDATES),('total_points','t',CONTEXT)]:
        rows=tr[tr[target].notna()];cols=[prefix+'__'+a for a in arms]
        w=weights(rows[cols],rows[target],anchor=arms.index('CONTEXT_QB'),penalty=protocol['weight_penalty'])
        head={'target':TARGETS[target],'arms':arms,'weights':w.tolist(),'weight_sum':float(w.sum()),'fit_n':len(rows)}
        if target=='home_win':
            rows=cal[cal.home_win.notna()];head['calibration']=fit_calibration(rows[cols].to_numpy(float)@w,rows.home_win)
        model['heads'][target]=head
    return model


def predict_frame(model,frame):
    out={}
    for target,prefix in [('home_win','p'),('home_margin','m'),('total_points','t')]:
        h=model['heads'][target];X=frame[[prefix+'__'+a for a in h['arms']]].to_numpy(float)
        raw=X@np.asarray(h['weights']);out[target+'_raw']=raw
        if target=='home_win':
            c=h['calibration'];out[target]=expit(c['slope']*logit(np.clip(raw,1e-9,1-1e-9))+c['intercept'])
        else:out[target]=raw
    return pd.DataFrame(out,index=frame.index)


def predict_packets(model,packets,event_id,cutoff,target):
    head=model['heads'][target]
    if set(packets)!=set(head['arms']):raise ValueError('REQUIRED_ARMS_MISSING_OR_EXTRA')
    values=np.array([validate_prediction_packet(packets[a],event_id,cutoff,target) for a in head['arms']])
    weighted=values*np.array(head['weights']);raw=float(weighted.sum());value=raw
    if target=='home_win':
        c=head['calibration'];value=float(expit(c['slope']*logit(np.clip(raw,1e-9,1-1e-9))+c['intercept']))
    return {'event_id':event_id,'target':head['target'],'value':value,'raw_blend':raw,'weighted_components':dict(zip(head['arms'],map(float,weighted))),
            'calibration_delta':value-raw,'model_sha256':digest(model),'input_packet_sha256':digest(packets),'market_input':False,'action_authority':False,'official_release_eligible':False}


def binary_score(y,p):
    y,p=np.asarray(y,float),np.asarray(p,float)
    if not np.isfinite(y).all() or not np.isfinite(p).all() or not set(y).issubset({0.,1.}) or ((p<0)|(p>1)).any():raise ValueError('INVALID_BINARY_SCORE')
    s=np.clip(p,1e-12,1-1e-12)
    return {'n':len(y),'correct':int(((p>.5)==y).sum()),'accuracy':float(np.mean((p>.5)==y)),'brier':float(np.mean((p-y)**2)),
            'log_loss':float(np.mean(-y*np.log(s)-(1-y)*np.log1p(-s)))}


def reliability(y,p):
    y,p=np.asarray(y,float),np.asarray(p,float);bins=np.minimum((p*10).astype(int),9);rows=[]
    for k in range(10):
        mask=bins==k;n=int(mask.sum())
        rows.append({'low':k/10,'high':(k+1)/10,'n':n,'mean_probability':float(p[mask].mean()) if n else None,'observed_rate':float(y[mask].mean()) if n else None})
    return rows


def paired_interval(frame,loss_difference,seed=20260918):
    x=pd.DataFrame({'cluster':frame.season.astype(str)+'_'+frame.week.astype(str),'loss':loss_difference})
    a=x.groupby('cluster').loss.agg(['sum','count']);rng=np.random.default_rng(seed)
    i=rng.integers(len(a),size=(10000,len(a)));d=a['sum'].to_numpy()[i].sum(axis=1)/a['count'].to_numpy()[i].sum(axis=1)
    return {'cluster_count':len(a),'mean_delta':float(x.loss.mean()),'ci95':np.quantile(d,[.025,.975]).tolist(),'scope':'WEEK_CLUSTER_BOOTSTRAP_NOT_PROSPECTIVE_OR_SERIAL_DEPENDENCE_CERTIFICATION'}


def simulate_binary(p,identity,n=100000):
    if not 0<=p<=1 or n!=100000:raise ValueError('SIMULATION_CONTRACT')
    seed=int(digest({'identity':identity,'p':p,'n':n})[:16],16)
    draws=(np.random.default_rng(seed).random(n)<p)
    return draws,{'seed':seed,'n':n,'p_home':float(draws.mean()),'mc_standard_error':float(math.sqrt(p*(1-p)/n)),
                  'draws_sha256':__import__('hashlib').sha256(draws.tobytes()).hexdigest(),'scope':'BINARY_NON_TIE; NOT_SCORE_OR_DRIVE_SIMULATOR'}
