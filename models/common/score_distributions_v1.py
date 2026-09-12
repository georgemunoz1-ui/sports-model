"""Diagnostic score distributions; no market/action authority.

Repricing returns empirical frequencies, not exact population probabilities.
Conditioning on no push removes push mass, not bookmaker vig. Raw ordered
score pairs are retained losslessly with full SHA-256 and explicit byte format.
"""
import base64
import hashlib
import math
import zlib
import numpy as np

PERIODS = {'MLB_NINE_INNING_PROXY', 'MLS_REGULATION_GRID'}
QUANTILES = [.05, .10, .25, .50, .75, .90, .95]

def _scores(x):
    a = np.asarray(x)
    if a.ndim != 1 or not len(a) or a.dtype.kind not in 'iuf':
        raise ValueError('NONEMPTY_NUMERIC_SCORE_VECTOR_REQUIRED')
    if not np.isfinite(a).all() or (a < 0).any() or (a > 2147483647).any() or (a != np.floor(a)).any():
        raise ValueError('NONNEGATIVE_INT32_SCORES_REQUIRED')
    return a.astype(np.int64)  # Never subtract uint8 score arrays.

def _summary(a):
    values, counts = np.unique(a, return_counts=True)
    return dict(mean=float(a.mean()), std=float(a.std(ddof=0)),
        quantile_method='inverted_cdf',
        quantiles={f'p{round(q*100):02d}':int(v) for q,v in zip(QUANTILES,np.quantile(a,QUANTILES,method='inverted_cdf'))},
        pmf=[dict(value=int(v),count=int(c)) for v,c in zip(values,counts)])

def extract(home_scores, away_scores, *, score_period):
    if score_period not in PERIODS: raise ValueError('UNKNOWN_SCORE_PERIOD')
    h,a=_scores(home_scores),_scores(away_scores)
    if len(h)!=len(a): raise ValueError('UNPAIRED_SCORE_DRAWS')
    margin,total=h-a,h+a
    pairs=np.column_stack((h,a)).astype('<i4')
    raw=pairs.tobytes(order='C')
    corr=None if margin.std()==0 or total.std()==0 else float(np.corrcoef(margin,total)[0,1])
    return dict(schema='score_distribution.v1',score_period=score_period,n_sims=len(h),
        margin_convention='HOME_MINUS_AWAY',margin=_summary(margin),total=_summary(total),
        home_points=_summary(h),away_points=_summary(a),margin_total_correlation=corr,
        correlation_status='UNDEFINED_CONSTANT_VECTOR' if corr is None else 'DEFINED',
        score_draws=dict(encoding='base64_zlib',dtype='<i4',shape=[len(h),2],
            columns=['home','away'],order='C',sha256=hashlib.sha256(raw).hexdigest(),
            data=base64.b64encode(zlib.compress(raw,9)).decode('ascii')),
        capability=dict(distribution='DIAGNOSTIC_AVAILABLE',repricing='MATCHING_PERIOD_DIAGNOSTIC_ONLY',
            full_game_mlb_settlement='UNSUPPORTED',action_authority=False))

def decode(artifact):
    s=artifact['score_draws'];n=artifact['n_sims']
    if not isinstance(n,int) or n<=0 or s['shape']!=[n,2] or s['dtype']!='<i4':
        raise ValueError('DRAW_SCHEMA_INVALID')
    if s['encoding']!='base64_zlib' or s['columns']!=['home','away'] or s['order']!='C':
        raise ValueError('DRAW_ENCODING_INVALID')
    raw=zlib.decompress(base64.b64decode(s['data'],validate=True))
    if len(raw)!=n*8 or hashlib.sha256(raw).hexdigest()!=s['sha256']:
        raise ValueError('DRAW_HASH_OR_LENGTH_MISMATCH')
    d=np.frombuffer(raw,dtype='<i4').reshape(n,2).astype(np.int64)
    _scores(d[:,0]);_scores(d[:,1])
    return d[:,0],d[:,1]

def reprice(artifact, line, *, kind, score_period):
    if score_period not in PERIODS or score_period!=artifact['score_period']:
        raise ValueError('SETTLEMENT_PERIOD_UNSUPPORTED_OR_MISMATCH')
    if isinstance(line,bool) or not math.isfinite(float(line)) or float(line)*2!=int(float(line)*2):
        raise ValueError('ONLY_INTEGER_OR_HALF_LINES_SUPPORTED')
    h,a=decode(artifact)
    if kind=='spread':values=h-a+float(line);labels=('home_cover','away_cover')
    elif kind=='total':values=h+a-float(line);labels=('over','under')
    else:raise ValueError('UNKNOWN_REPRICE_KIND')
    win,lose,push=[int(np.sum(f(values))) for f in (lambda v:v>0,lambda v:v<0,lambda v:v==0)]
    n=len(values);nonpush=win+lose
    return dict(line=float(line),kind=kind,score_period=score_period,
        probabilities={labels[0]:win/n,labels[1]:lose/n,'push':push/n},
        conditional_on_no_push={labels[0]:win/nonpush if nonpush else None,labels[1]:lose/nonpush if nonpush else None},
        conditional_status='DEFINED' if nonpush else 'UNDEFINED_ALL_PUSH',
        n_sims=n,method='EMPIRICAL_DRAW_FREQUENCIES',action_authority=False)
