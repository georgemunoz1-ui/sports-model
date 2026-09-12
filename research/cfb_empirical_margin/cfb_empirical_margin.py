"""Offline empirical conditional final-margin challenger; never an action model."""
import hashlib
import numpy as np

MODEL_ID = 'cfb.causal_elo_empirical_margin.v0_1.research'

def distribution(updates, home_elo, away_elo, neutral, home_advantage=55):
    # Match venue class; bandwidth uses features only, never market or test outcomes.
    rows = [r for r in updates if r['neutral_site'] == neutral]
    if len(rows) < 20:
        raise ValueError('INSUFFICIENT_SAME_VENUE_HISTORY')
    x = np.array([r['home_elo_before']-r['away_elo_before'] + (0 if neutral else home_advantage) for r in rows])
    m = np.array([r['home_score']-r['away_score'] for r in rows], dtype=float)
    if not np.isfinite(x).all() or not np.isfinite(m).all() or np.any(m != np.floor(m)) or np.any(m == 0):
        raise ValueError('INVALID_FINAL_MARGIN_HISTORY')
    target = home_elo-away_elo + (0 if neutral else home_advantage)
    if not np.isfinite(target) or target < x.min() or target > x.max():
        raise ValueError('ELO_EXTRAPOLATION_BLOCKED')
    bandwidth = float(np.std(x, ddof=1))
    if bandwidth <= 0:
        raise ValueError('DEGENERATE_HISTORY')
    w = np.exp(-0.5*((x-target)/bandwidth)**2); w /= w.sum()
    ess = float(1/(w@w))
    if ess < 15:
        raise ValueError('INSUFFICIENT_EFFECTIVE_HISTORY')
    return m.astype('<i2'), w, {'n_history':len(rows),'effective_sample_size':ess,'bandwidth_elo':bandwidth}

def simulate(margins, weights, event_id, input_hash, n=100000):
    seed = int.from_bytes(hashlib.sha256(f'{MODEL_ID}:{event_id}:{input_hash}'.encode()).digest()[:8], 'big')
    draws = np.random.default_rng(seed).choice(margins, n, p=weights).astype('<i2')
    return draws, seed

def cover(margins, home_line, weights=None):
    if not np.isfinite(home_line) or home_line*2 != round(home_line*2):
        raise ValueError('ONLY_INTEGER_OR_HALF_POINT_LINES')
    w = np.ones(len(margins))/len(margins) if weights is None else weights
    h=float(w[margins+home_line>0].sum()); a=float(w[margins+home_line<0].sum()); p=float(w[margins+home_line==0].sum())
    return {'home_cover':h,'away_cover':a,'push':p,'home_conditional_no_push':h/(h+a) if h+a else None}
