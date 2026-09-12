"""Empirical first-half total baseline. No full-game division or market features."""
import hashlib
import numpy as np
MODEL_ID='cfb.first_half_empirical_total.v0_1.research'
def half_score(team):
 q=team.get('linescores',[])
 if len(q)<4: raise ValueError('MISSING_REGULATION_QUARTERS')
 values=[float(x.get('value',x.get('displayValue','nan'))) for x in q]
 if any(not np.isfinite(x) or x<0 or x!=int(x) for x in values):raise ValueError('INVALID_QUARTER_SCORE')
 if sum(values)!=float(team['score']):raise ValueError('QUARTERS_FINAL_CONFLICT')
 return int(values[0]+values[1])
def forecast(totals,event_id,snapshot_hash,n=100000):
 x=np.asarray(totals,dtype=float)
 if len(x)<30 or not np.isfinite(x).all() or np.any(x<0) or np.any(x!=np.floor(x)):raise ValueError('INVALID_OR_INSUFFICIENT_HISTORY')
 seed=int.from_bytes(hashlib.sha256(f'{MODEL_ID}:{event_id}:{snapshot_hash}:{n}'.encode()).digest()[:8],'big')
 draws=np.random.default_rng(seed).choice(x.astype('<i2'),size=n).astype('<i2')
 return {'mean':float(x.mean()),'quantiles':dict(zip(['p10','p25','p50','p75','p90'],map(float,np.quantile(x,[.1,.25,.5,.75,.9],method='inverted_cdf')))),'n_history':len(x),'seed':seed,'n_sims':n,'sim_mean':float(draws.mean()),'draws_sha256':hashlib.sha256(draws.tobytes()).hexdigest()},draws

def probabilities(totals,line):
 x=np.asarray(totals)
 if not np.isfinite(line) or line*2!=int(line*2):raise ValueError('UNSUPPORTED_LINE')
 return {'under':float(np.mean(x<line)),'over':float(np.mean(x>line)),'push':float(np.mean(x==line))}
