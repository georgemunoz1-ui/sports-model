"""Coherent monotone CDF recalibration of final home-margin distributions.

This module prices full-game spread thresholds only. It does not modify a frozen
football forecast, calibrate totals, or manufacture halftime outcomes.
"""
from __future__ import annotations
import hashlib
import numpy as np
from scipy.special import expit, logit

MODEL_ID = 'nfl.spread_cdf_calibration.v1.research'
REFERENCE_ID = 'nfl.integrated_context.combined.v1.research'
CLASSES = ['HOME_COVER', 'PUSH', 'HOME_FAIL']

def transform_cdf(probability, intercept=0.0, slope=1.0):
    f = np.asarray(probability, dtype=float)
    if not np.isfinite(f).all() or (f < 0).any() or (f > 1).any():
        raise ValueError('CDF_RANGE')
    if not np.isfinite([intercept, slope]).all() or slope <= 0:
        raise ValueError('CALIBRATION_PARAMETERS')
    # Preserve the identity exactly, including finite-support endpoints.
    if intercept == 0 and slope == 1:
        return f.copy()
    q = expit(intercept + slope * logit(np.clip(f, 1e-15, 1-1e-15)))
    return np.where(f == 0, 0., np.where(f == 1, 1., q))

def margin_distribution(margins, weights=None):
    m = np.asarray(margins, dtype=float)
    if m.ndim != 1 or not len(m) or not np.isfinite(m).all() or not np.equal(m, np.rint(m)).all():
        raise ValueError('INTEGER_MARGIN_ARRAY_REQUIRED')
    w = np.ones(len(m), float) if weights is None else np.asarray(weights, float)
    if w.shape != m.shape or not np.isfinite(w).all() or (w < 0).any() or w.sum() <= 0:
        raise ValueError('MARGIN_WEIGHT_INVALID')
    support, inv = np.unique(m.astype(np.int64), return_inverse=True)
    masses = np.bincount(inv, weights=w, minlength=len(support)); masses /= masses.sum()
    return support, masses

def exact_kernel_margin(margin, total, p_home_non_tie, residual_pairs, tie_rate):
    """Exact marginal of simulate_joint V2, with no Monte Carlo fit noise."""
    pool = np.asarray(residual_pairs, float)
    centers = np.array([(total+margin)/2, (total-margin)/2])
    if pool.ndim != 2 or pool.shape[1] != 2 or len(pool) < 100 or not np.isfinite(pool).all():
        raise ValueError('RESIDUAL_POOL_INVALID')
    if not np.isfinite(centers).all() or (centers < 0).any() or not 0 <= p_home_non_tie <= 1 or not 0 <= tie_rate < 1:
        raise ValueError('JOINT_PARAMETERS_INVALID')
    scores = np.rint(np.maximum(0, centers + pool - pool.mean(axis=0))).astype(np.int64)
    m = scores[:, 0] - scores[:, 1]
    weights = np.zeros(len(m), float)
    for sign, mass in zip([1,-1,0], [(1-tie_rate)*p_home_non_tie, (1-tie_rate)*(1-p_home_non_tie), tie_rate]):
        mask = np.sign(m) == sign
        if mass > 0 and not mask.any():
            raise ValueError('CONDITIONAL_SCORE_SUPPORT_MISSING')
        if mask.any():weights[mask] = mass / mask.sum()
    return margin_distribution(m, weights)

def cdf_bounds(support, masses, home_handicap):
    """P(M < -handicap), P(M <= -handicap); their gap is push mass."""
    if not np.isfinite(home_handicap) or float(home_handicap)*2 != round(float(home_handicap)*2):
        raise ValueError('HALF_POINT_INCREMENT_REQUIRED')
    m,w = margin_distribution(support, masses)
    threshold = -float(home_handicap)
    lo = float(w[m < threshold].sum()); hi = float(w[m <= threshold].sum())
    return np.clip([lo,hi],0,1)

def probabilities_from_bounds(bounds, intercept=0., slope=1.):
    bounds = np.asarray(bounds, float)
    if bounds.shape[-1:] != (2,) or (bounds[...,0] > bounds[...,1]).any():
        raise ValueError('ORDERED_CDF_BOUNDS_REQUIRED')
    q = transform_cdf(bounds, intercept, slope)
    return np.stack([1-q[...,1], q[...,1]-q[...,0], q[...,0]], axis=-1)

def price_spread(support, masses, home_handicap, *, side='HOME', intercept=0., slope=1., period='FULL_GAME'):
    if period != 'FULL_GAME':raise ValueError('PERIOD_UNSUPPORTED')
    if side not in {'HOME','AWAY'}:raise ValueError('SIDE')
    p = probabilities_from_bounds(cdf_bounds(support,masses,home_handicap),intercept,slope)
    if side == 'AWAY':p = p[::-1]
    return dict(zip(['win','push','loss'],map(float,p)))

def calibrated_distribution(support, masses, intercept, slope):
    m,w = margin_distribution(support,masses);cdf=np.cumsum(w);cdf[-1]=1.
    calibrated = np.diff(np.r_[0.,transform_cdf(cdf,intercept,slope)])
    if (calibrated < -1e-12).any():raise ValueError('NEGATIVE_CALIBRATED_MASS')
    calibrated=np.maximum(0,calibrated);calibrated/=calibrated.sum()
    return m,calibrated

def simulate_margins(support,masses,seed,n=100000):
    if not isinstance(n,int) or n<=0:raise ValueError('SIMULATION_COUNT')
    m,w=margin_distribution(support,masses)
    draws=np.random.default_rng(seed).choice(m,size=n,p=w).astype('<i8')
    return draws,{'n':n,'seed':seed,'sha256':hashlib.sha256(draws.tobytes()).hexdigest(),
                  'target':'FINAL_HOME_MARGIN_INCLUDING_OVERTIME','score_or_drive_simulation':False}
