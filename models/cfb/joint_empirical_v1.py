"""FBS-only joint final-score challenger; never an incumbent/default replacement.

Uniform nearest-neighbour mass on observed score pairs provides an exact discrete
distribution. No Gaussian rounding, tie reassignment, or made-up OT continuation.
Historical source availability remains a separate, unproven PIT requirement.
"""
import hashlib
import json
import math
import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

MODEL_ID = 'cfb.joint_final_score.knn256.v1.research'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def fit(frame, features, cutoff, neighbours=256):
    import pandas as pd
    if len(set(frame.game_id.astype(str))) != len(frame):
        raise ValueError('DUPLICATE_EVENT')
    if not ((frame.home_division == 'fbs') & (frame.away_division == 'fbs')).all():
        raise ValueError('FBS_ONLY')
    cutoff_time = pd.Timestamp(cutoff)
    if cutoff_time.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    if not (pd.to_datetime(frame.kick, utc=True) < cutoff_time).all():
        raise ValueError('FUTURE_TRAINING_ROW')
    scores = frame[['home_points', 'away_points']].to_numpy(float)
    if not np.isfinite(scores).all() or (scores < 0).any() or (scores != np.floor(scores)).any():
        raise ValueError('INVALID_FINAL_SCORE')
    if (scores[:, 0] == scores[:, 1]).any():
        raise ValueError('TIED_FINAL_NOT_SUPPORTED')
    if isinstance(neighbours, bool) or not 2 <= neighbours <= len(frame):
        raise ValueError('NEIGHBOUR_COUNT')
    forbidden = ['market', 'odds', 'spread', 'home_win', 'home_margin', 'home_points', 'away_points', 'pregame_elo']
    if any(any(t in f for t in forbidden) for f in features):
        raise ValueError('FEATURE_FIREWALL')
    imp = SimpleImputer(strategy='median', keep_empty_features=True)
    x = imp.fit_transform(frame[features])
    if not np.isfinite(x).all():
        raise ValueError('NONFINITE_FEATURE')
    scaler = StandardScaler().fit(x)
    z = scaler.transform(x)
    state = {'model_id': MODEL_ID, 'features': features, 'impute': imp.statistics_.tolist(),
             'mean': scaler.mean_.tolist(), 'scale': scaler.scale_.tolist(),
             'z': z.tolist(), 'scores': scores.astype(int).tolist(),
             'event_ids': frame.game_id.astype(str).tolist(), 'training_cutoff': cutoff,
             'neighbours': neighbours, 'population': 'FBS_VS_FBS',
             'settlement': 'EMPIRICAL_REPORTED_FINAL_SCORE_INCLUDING_OT',
             'limitations': ['UNVALIDATED_PRODUCT_CALIBRATION', 'HISTORICAL_SOURCE_AVAILABILITY_UNPROVEN',
                             'NO_PLAYER_OR_WEATHER_TRANSFORM', 'NO_ACTION_AUTHORITY']}
    state['state_sha256'] = digest(state)
    return state


def distribution(state, values):
    check = {k: v for k, v in state.items() if k != 'state_sha256'}
    if digest(check) != state['state_sha256']:
        raise ValueError('STATE_HASH_MISMATCH')
    x = np.asarray([np.nan if v is None else v for v in values], float)
    if len(x) != len(state['features']) or np.isinf(x).any():
        raise ValueError('FEATURE_SCHEMA')
    x = np.where(np.isnan(x), state['impute'], x)
    z = (x - state['mean']) / state['scale']
    # Stable distance ordering makes equal-distance selection replayable.
    distances = np.sum((np.asarray(state['z']) - z) ** 2, axis=1)
    ix = np.argsort(distances, kind='stable')[:state['neighbours']]
    scores = np.asarray(state['scores'], dtype='<i4')[ix]
    return scores, {'neighbour_event_ids': [state['event_ids'][i] for i in ix],
                    'furthest_standardized_distance': float(np.sqrt(distances[ix[-1]])),
                    'distribution_sha256': hashlib.sha256(scores.tobytes()).hexdigest()}


def summarize(scores, home_handicap=None, total_line=None):
    scores = np.asarray(scores)
    if scores.ndim != 2 or scores.shape[1] != 2 or not len(scores):
        raise ValueError('SCORE_SHAPE')
    if not np.isfinite(scores).all() or (scores < 0).any() or (scores != np.floor(scores)).any():
        raise ValueError('INVALID_SCORES')
    margin = scores[:, 0] - scores[:, 1]
    total = scores.sum(axis=1)
    result = {'home_win': float(np.mean(margin > 0)), 'away_win': float(np.mean(margin < 0)),
              'tie': float(np.mean(margin == 0)), 'home_margin': float(margin.mean()),
              'total': float(total.mean()), 'home_score': float(scores[:, 0].mean()),
              'away_score': float(scores[:, 1].mean()),
              'margin_quantiles': np.quantile(margin, [.1, .25, .5, .75, .9]).tolist(),
              'total_quantiles': np.quantile(total, [.1, .25, .5, .75, .9]).tolist()}
    for line in [home_handicap, total_line]:
        if line is not None and (isinstance(line, bool) or not math.isfinite(line) or line * 2 != round(line * 2)):
            raise ValueError('HALF_OR_INTEGER_LINE_REQUIRED')
    if home_handicap is not None:
        s = margin + home_handicap
        result['home_cover'] = {'win': float(np.mean(s > 0)), 'push': float(np.mean(s == 0)), 'loss': float(np.mean(s < 0))}
    if total_line is not None:
        s = total - total_line
        result['over'] = {'win': float(np.mean(s > 0)), 'push': float(np.mean(s == 0)), 'loss': float(np.mean(s < 0))}
    return result


def simulate(scores, identity, n=100000):
    if isinstance(n, bool) or not 1 <= n <= 1000000:
        raise ValueError('DRAW_COUNT')
    seed = int(digest({'identity': identity, 'kind': MODEL_ID, 'n': n})[:16], 16)
    draws = np.asarray(scores, dtype='<i4')[np.random.default_rng(seed).integers(len(scores), size=n)]
    return draws, {'seed': seed, 'rng': 'numpy.PCG64', 'draw_count': n,
                   'encoding': 'int32_little_endian_C_order_home_away',
                   'draw_sha256': hashlib.sha256(draws.tobytes()).hexdigest()}
