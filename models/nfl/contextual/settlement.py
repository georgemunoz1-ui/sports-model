"""Shared settlement signs for explicitly scoped integer score outcomes."""
from decimal import Decimal
import numpy as np

def settlement_values(scores,market_type,side,line=None,*,period='FULL_GAME',score_period='FULL_GAME',tie_policy=None):
    if period not in {'FULL_GAME','FIRST_HALF','REGULATION'} or period!=score_period:raise ValueError('PERIOD_UNSUPPORTED_OR_MISMATCH')
    s=np.asarray(scores)
    if s.ndim!=2 or s.shape[1]!=2 or not len(s) or not np.isfinite(s).all() or (s<0).any() or not np.equal(s,np.floor(s)).all():raise ValueError('INVALID_INTEGER_SCORES')
    h,a=s[:,0],s[:,1]
    if market_type=='MONEYLINE':
        if side not in {'HOME','AWAY'} or tie_policy not in {'REFUND','LOSS'}:raise ValueError('MONEYLINE_TIE_CONTRACT_REQUIRED')
        v=h-a if side=='HOME' else a-h
        return np.where((v==0)&(tie_policy=='LOSS'),-1,np.sign(v))
    if line is None or not Decimal(str(line)).is_finite():raise ValueError('LINE_REQUIRED')
    if market_type=='SPREAD':
        if side not in {'HOME','AWAY'}:raise ValueError('SIDE')
        return np.sign((h-a if side=='HOME' else a-h)+float(line))
    if market_type=='TOTAL':
        if side not in {'OVER','UNDER'}:raise ValueError('SIDE')
        return np.sign((h+a-float(line))*(1 if side=='OVER' else -1))
    raise ValueError('MARKET_TYPE')

def settle_contract(*,home_score,away_score,market_type,side,line=None,period='FULL_GAME',score_period='FULL_GAME',tie_policy=None,decimal_price=None,fee_per_unit=None,void=False):
    if void:return {'result':'VOID','net_return_per_unit':0.0,'reason':'DECLARED_VOID'}
    v=settlement_values([[home_score,away_score]],market_type,side,line,period=period,score_period=score_period,tie_policy=tie_policy)[0]
    result='WIN' if v>0 else 'LOSS' if v<0 else 'PUSH'
    net=None
    if decimal_price is not None:
        d=Decimal(str(decimal_price))
        if not d.is_finite() or d<=1:raise ValueError('INVALID_PRICE')
        if fee_per_unit is not None:
            fee=Decimal(str(fee_per_unit))
            if not fee.is_finite() or fee<0:raise ValueError('INVALID_FEE')
            net=float((d-1 if v>0 else Decimal(-1) if v<0 else Decimal(0))-fee)
    return {'result':result,'period':period,'net_return_per_unit':net,'reason':'SETTLED' if net is not None else 'PRICE_OR_FEE_UNSPECIFIED'}
