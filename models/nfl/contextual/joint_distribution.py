"""Exact weighted measure underlying the frozen V2 sampler, not a new fitted arm."""
import numpy as np
from .recovered_inference import digest
from .settlement import settlement_values

def kernel(margin,total,p_home_non_tie,residual_pairs,tie_rate):
    pool=np.asarray(residual_pairs,float)
    centers=np.array([(total+margin)/2,(total-margin)/2])
    if pool.ndim!=2 or pool.shape[1]!=2 or len(pool)<100 or not np.isfinite(pool).all():raise ValueError('RESIDUAL_POOL_INVALID')
    if not np.isfinite(centers).all() or (centers<0).any() or not 0<=p_home_non_tie<=1 or not 0<=tie_rate<1:raise ValueError('JOINT_PARAMETERS_INVALID')
    support=np.rint(np.maximum(0,centers+pool-pool.mean(axis=0))).astype('<i2')
    weights=np.zeros(len(support),float);signs=np.sign(support[:,0]-support[:,1])
    for sign,mass in [(1,(1-tie_rate)*p_home_non_tie),(-1,(1-tie_rate)*(1-p_home_non_tie)),(0,tie_rate)]:
        mask=signs==sign
        if mass>0 and not mask.any():raise ValueError('JOINT_SCORE_SUPPORT_MISSING')
        if mask.any():weights[mask]=mass/mask.sum()
    return support,weights

def summary(support,weights):
    s=np.asarray(support);w=np.asarray(weights)
    if s.ndim!=2 or s.shape[1]!=2 or w.shape!=(len(s),) or not np.isfinite(w).all() or (w<0).any() or not np.isclose(w.sum(),1):raise ValueError('JOINT_MEASURE_INVALID')
    m=s[:,0]-s[:,1];t=s.sum(axis=1);h=float(w[m>0].sum());a=float(w[m<0].sum())
    return {'distribution':'OUTCOME_ALIGNED_FINAL_SCORE_KERNEL_V2','measure_sha256':digest({'support':s.tolist(),'weights':w.tolist()}),
            'p_home_win':h,'p_away_win':a,'p_tie':float(w[m==0].sum()),'p_home_win_conditional_non_tie':h/(h+a) if h+a else None,
            'mean_home_score':float(w@s[:,0]),'mean_away_score':float(w@s[:,1]),'mean_margin':float(w@m),'mean_total':float(w@t),
            'source':'EXACT_WEIGHTED_SUPPORT_NOT_MONTE_CARLO','calibration_established':False}

def contract(support,weights,market_type,side,line=None,tie_policy=None):
    summary(support,weights) # validate measure
    v=settlement_values(support,market_type,side,line,tie_policy=tie_policy)
    w=np.asarray(weights)
    return {'win':float(w[v>0].sum()),'push_or_refund':float(w[v==0].sum()),'loss':float(w[v<0].sum()),'scope':'UNVALIDATED_EXACT_KERNEL_SETTLEMENT'}
