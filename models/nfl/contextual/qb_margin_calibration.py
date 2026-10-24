"""One-parameter, past-only calibration that retains integer NFL margins."""
from __future__ import annotations
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import numpy as np
from . import qb_margin as base
from .recovered_inference import digest, utc

MODEL_ID = 'nfl.qb_margin.integer_blend.v1.research'
DISTRIBUTION = 'QB_CONDITIONAL_INTEGER_MARGIN_CRPS_BLEND_V1'
DATA = base.ROOT/'data/nfl/qb_margin_calibration_v1'


def fit_integer_history(rows, *, before_season):
    # Reuse strict duplicate, finite target, QB-only and chronology validation.
    law = base.fit_residuals(rows, before_season=before_season)
    x, y = [], []
    for r in rows:
        actual = r['home_margin']
        if actual != 0:
            x.append(float(np.sign(actual)*r['pred_margin']))
            y.append(int(abs(actual)))
    return {'winner_oriented_qb_prediction': x, 'winning_integer_margin': y,
            'count': len(rows), 'non_tie_count': len(x), 'max_season': law['max_season'],
            'tie_rate': law['tie_rate'], 'bandwidth_points': 4.0,
            'game_ids': law['game_ids'], 'source_rows_sha256': digest([{k: r[k] for k in ('game_id', 'season', 'arm', 'home_margin', 'pred_margin')} for r in rows])}


def integer_kernel(location, p_home_non_tie, history):
    if not np.isfinite(location) or not np.isfinite(p_home_non_tie) or not 0 <= p_home_non_tie <= 1:
        raise ValueError('INTEGER_KERNEL_PARAMETERS')
    x = np.asarray(history['winner_oriented_qb_prediction'], float)
    y = np.asarray(history['winning_integer_margin'], float)
    h = history['bandwidth_points']; t = history['tie_rate']
    if x.ndim != 1 or len(x) < 100 or y.shape != x.shape or not np.isfinite(x).all() or not np.isfinite(y).all() or (y <= 0).any() or (y != np.rint(y)).any() or h != 4.0 or not 0 <= t < 1:
        raise ValueError('INTEGER_KERNEL_HISTORY')
    if (y > np.iinfo(np.int16).max).any():
        raise ValueError('INTEGER_KERNEL_OVERFLOW')
    magnitudes, inverse = np.unique(y.astype('<i2'), return_inverse=True)
    supports, masses, effective = [np.array([0], dtype='<i2')], [np.array([t])], {}
    for sign, p in [(1, p_home_non_tie), (-1, 1-p_home_non_tie)]:
        log_w = -.5*((x-sign*location)/h)**2
        w = np.exp(log_w-log_w.max()); w /= w.sum()
        effective['home' if sign == 1 else 'away'] = float(1/(w@w))
        supports.append(sign*magnitudes)
        masses.append(np.bincount(inverse, weights=w, minlength=len(magnitudes))*(1-t)*p)
    support, weight = np.concatenate(supports), np.concatenate(masses)
    order = np.argsort(support); support, weight = support[order], weight[order]
    base.validate_measure(support, weight)
    return support, weight, effective


def blend(s0, w0, s1, w1, alpha):
    base.validate_measure(s0, w0); base.validate_measure(s1, w1)
    if isinstance(alpha, bool) or not np.isfinite(alpha) or not 0 <= alpha <= 1:
        raise ValueError('CALIBRATION_ALPHA')
    support = np.union1d(s0, s1).astype('<i2'); weights = np.zeros(len(support))
    np.add.at(weights, np.searchsorted(support, s0), (1-alpha)*np.asarray(w0))
    np.add.at(weights, np.searchsorted(support, s1), alpha*np.asarray(w1))
    base.validate_measure(support, weights)
    return support, weights


def quadratic_terms(s0, w0, s1, w1, actual):
    if not np.isfinite(actual) or actual != round(actual):
        raise ValueError('INTEGER_CALIBRATION_TARGET')
    lower = int(min(min(s0), min(s1), actual)); upper = int(max(max(s0), max(s1), actual))
    grid = np.arange(lower, upper+1)
    def cdf(s, w):
        order = np.argsort(s); s, w = np.asarray(s)[order], np.asarray(w)[order]
        return np.r_[0, np.cumsum(w)][np.searchsorted(s, grid, side='right')]
    f0, f1 = cdf(s0, w0), cdf(s1, w1); delta = f1-f0
    return float(np.sum((f0-(grid >= actual))*delta)), float(delta@delta)


def optimize_alpha(records, *, before_season):
    if not records or any(r['season'] >= before_season for r in records):
        raise ValueError('CALIBRATION_REQUIRES_PRIOR_FOLDS')
    if len({r['game_id'] for r in records}) != len(records):
        raise ValueError('DUPLICATE_CALIBRATION_GAME')
    g = sum(r['gradient_half'] for r in records); h = sum(r['curvature_half'] for r in records)
    if not np.isfinite(g) or not np.isfinite(h) or h < 0:
        raise ValueError('CALIBRATION_QUADRATIC_INVALID')
    return {'alpha': float(np.clip(-g/h, 0, 1)) if h else 0.0,
            'status': 'GLOBAL_BOUNDED_QUADRATIC_MINIMUM' if h else 'UNIDENTIFIABLE_ALPHA_ZERO',
            'gradient_half_sum': g, 'curvature_half_sum': h, 'games': len(records),
            'min_season': min(r['season'] for r in records), 'max_season': max(r['season'] for r in records),
            'before_season': before_season, 'calibration_records_sha256': digest(records)}


def load_registered():
    cfg = json.loads((DATA/'runtime.json').read_text())
    mp, ep = DATA/cfg['model_file'], DATA/cfg['evaluation_file']
    if base.file_sha(mp) != cfg['model_sha256'] or base.file_sha(ep) != cfg['evaluation_sha256']:
        raise ValueError('CALIBRATED_MARGIN_REGISTERED_HASH')
    model, evaluation = json.loads(mp.read_text()), json.loads(ep.read_text())
    if model['model_id'] != MODEL_ID or model['reference_model_id'] != base.MODEL_ID or model['market_input'] or model['action_authority']:
        raise ValueError('CALIBRATED_MARGIN_IDENTITY')
    if model['code_sha256'] != base.file_sha(__file__) or model['design_sha256'] != base.file_sha(DATA/'design.json'):
        raise ValueError('CALIBRATED_MARGIN_CODE_DESIGN_HASH')
    reference, _ = base.load_registered()
    if digest(reference) != model['reference_margin_model_sha256']:
        raise ValueError('CALIBRATED_MARGIN_REFERENCE_HASH')
    return model, evaluation


def build(parent, *, n=100000):
    model, evaluation = load_registered()
    now = dt.datetime.now(dt.timezone.utc)
    if utc(model['fitted_at_utc']) > now or int(parent['event']['event_id'].split('_')[0]) <= model['integer_history']['max_season']:
        raise ValueError('CALIBRATED_MARGIN_CHRONOLOGY')
    reference, _ = base.build(parent, n=n)
    p = parent['prediction']; s1, w1, ess = integer_kernel(p['home_margin'], p['home_win'], model['integer_history'])
    support, weights = blend(reference['margin_support'], reference['margin_weights'], s1, w1, model['calibration']['alpha'])
    identity = digest({'reference_margin_identity': reference['identity'], 'model_sha256': digest(model),
                       'evaluation_sha256': digest(evaluation), 'distribution': DISTRIBUTION})
    if type(n) is not int or n < 1:
        raise ValueError('POSITIVE_INTEGER_SIMULATION_COUNT_REQUIRED')
    seed = int(digest({'identity': identity, 'distribution': DISTRIBUTION, 'n': n})[:16], 16)
    draws = np.random.default_rng(seed).choice(support, size=n, p=weights).astype('<i2')
    f = copy.deepcopy(reference)
    f.update({'schema': 'nfl.qb_margin_calibrated_forecast.v1', 'model_id': MODEL_ID, 'identity': identity,
        'distribution': DISTRIBUTION, 'reference_margin_identity': reference['identity'],
        'calibration_model_sha256': digest(model), 'calibration_evaluation_sha256': digest(evaluation),
        'model_fitted_at_utc': model['fitted_at_utc'], 'margin_support': support.tolist(), 'margin_weights': weights.tolist(),
        'model_summary': base.summarize(support, weights),
        'calibration': {'alpha': model['calibration']['alpha'], 'status': model['calibration']['status'],
                        'bandwidth_points': 4.0, 'conditional_effective_n': ess,
                        'training_max_season': model['integer_history']['max_season']},
        'simulation': {'seed': seed, 'n': n, 'rng': 'numpy.random.default_rng/PCG64', 'distribution': DISTRIBUTION,
                       'dtype': '<i2', 'shape': [n], 'order': 'C', 'raw_sha256': hashlib.sha256(draws.tobytes()).hexdigest(),
                       'summary': base.summarize(draws, np.full(n, 1/n))},
        'retrospective_screen_passed': evaluation['retrospective_screen_passed'],
        'market_comparison_display_enabled': True, 'predictive_market_overlay_enabled': False,
        'research_grading_enabled': True,
        'warnings': ['REUSED_RETROSPECTIVE_HISTORY_NOT_PIT_VALIDATION', 'NEW_CALIBRATION_REQUIRES_PROSPECTIVE_VALIDATION',
                     'RESEARCH_GRADING_ONLY', 'TOTALS_AND_TEAM_SCORES_UNSUPPORTED']})
    f['coherence'] = {'non_tie_winner_head_preserved': abs(f['model_summary']['p_home_non_tie']-p['home_win']) < 1e-12,
                       'mean_minus_ridge_center': f['model_summary']['mean_home_margin']-p['home_margin'],
                       'scope': 'FINAL_MARGIN_ONLY_NOT_JOINT_SCORES'}
    return f, draws


def persist(folder, bundle, draws):
    now = dt.datetime.now(dt.timezone.utc)
    if bundle['model_id'] != MODEL_ID or utc(bundle['information_cutoff_utc']) > now or now >= utc(bundle['event']['start_time_utc']):
        raise ValueError('CALIBRATED_MARGIN_WRITER_CHRONOLOGY')
    if len(draws) != bundle['simulation']['n'] or hashlib.sha256(np.asarray(draws).tobytes()).hexdigest() != bundle['simulation']['raw_sha256']:
        raise ValueError('CALIBRATED_MARGIN_WRITER_DRAW_HASH')
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=False)
    registration = {'type': 'LOCAL_RESEARCH_CALIBRATED_MARGIN_ARTIFACT', 'created_at_utc': now.isoformat(),
        'model_id': MODEL_ID, 'forecast_identity': bundle['identity'], 'information_cutoff_utc': bundle['information_cutoff_utc'],
        'canonical_prospective_eligible': False, 'research_grading_enabled': True, 'action_authority': False}
    registration['record_hash'] = digest(registration)
    (folder/'registration.jsonl').write_text(json.dumps(registration)+'\n')
    (folder/'forecast.json').write_text(json.dumps(bundle, indent=2, allow_nan=False)+'\n')
    np.save(folder/'margin_draws.npy', draws, allow_pickle=False)
    (folder/'manifest.json').write_text(json.dumps({p.name: base.file_sha(p) for p in folder.iterdir() if p.is_file()}, indent=2)+'\n')
