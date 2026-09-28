"""QB-only, market-blind final-margin research distribution.

The unchanged QB heads supply the location and non-tie winner mass. Only QB
out-of-fold errors supply the margin shape. This is not a joint score model.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np

from .recovered_inference import digest, predict, utc

MODEL_ID = 'nfl.qb_margin.residual_alignment.v1.research'
REFERENCE_ID = 'nfl.integrated_context.qb.v1.research'
DISTRIBUTION = 'QB_OOF_CENTERED_INTEGER_MARGIN_OUTCOME_ALIGNED_V1'
ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / 'data/nfl/qb_margin_v1'


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fit_residuals(rows, *, before_season):
    """Every calibration residual must precede the season being forecast."""
    if not rows or len(rows) < 200:
        raise ValueError('QB_RESIDUAL_HISTORY_INSUFFICIENT')
    ids = [r['game_id'] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError('DUPLICATE_RESIDUAL_GAME')
    if any(r['arm'] != 'qb' for r in rows):
        raise ValueError('QB_RESIDUAL_ARM_REQUIRED')
    if any(int(r['season']) >= before_season for r in rows):
        raise ValueError('FUTURE_RESIDUAL_SEASON')
    actual = np.asarray([r['home_margin'] for r in rows], dtype=float)
    predicted = np.asarray([r['pred_margin'] for r in rows], dtype=float)
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all() or (actual != np.rint(actual)).any():
        raise ValueError('INVALID_RESIDUAL_TARGET')
    residuals = actual - predicted
    sigma = float(residuals.std(ddof=0))
    if sigma <= 0:
        raise ValueError('DEGENERATE_RESIDUAL_LAW')
    return {'residuals': residuals.tolist(), 'residual_mean_removed': float(residuals.mean()),
            'residual_sigma_points': sigma, 'sigma_definition': 'POPULATION_SD_OF_QB_OOF_MARGIN_ERRORS',
            'count': len(rows), 'game_ids': ids, 'seasons': [int(r['season']) for r in rows],
            'max_season': max(int(r['season']) for r in rows),
            'tie_count': int((actual == 0).sum()), 'tie_rate': float(((actual == 0).sum() + .5) / (len(rows) + 1)),
            'before_season': int(before_season), 'residual_sha256': digest(residuals.tolist())}


def kernel(location, p_home_non_tie, law):
    residuals = np.asarray(law['residuals'], dtype=float)
    tie_rate = law['tie_rate']
    if residuals.ndim != 1 or len(residuals) < 200 or not np.isfinite(residuals).all():
        raise ValueError('QB_RESIDUAL_LAW_INVALID')
    if not np.isfinite(location) or not np.isfinite(p_home_non_tie) or not 0 <= p_home_non_tie <= 1 or not 0 <= tie_rate < 1:
        raise ValueError('QB_MARGIN_PARAMETERS_INVALID')
    values = np.rint(location + residuals - residuals.mean())
    if (abs(values) > np.iinfo(np.int16).max).any():
        raise ValueError('MARGIN_ENCODING_OVERFLOW')
    support, counts = np.unique(values.astype('<i2'), return_counts=True)
    weights = np.zeros(len(support), dtype=float)
    for sign, mass in [(1, (1-tie_rate)*p_home_non_tie), (-1, (1-tie_rate)*(1-p_home_non_tie)), (0, tie_rate)]:
        mask = np.sign(support) == sign
        if mass > 0 and not mask.any():
            raise ValueError('QB_MARGIN_OUTCOME_SUPPORT_MISSING')
        if mask.any():
            weights[mask] = counts[mask] / counts[mask].sum() * mass
    validate_measure(support, weights)
    return support, weights


def validate_measure(support, weights):
    s, w = np.asarray(support), np.asarray(weights)
    if s.ndim != 1 or not len(s) or w.shape != s.shape or not np.isfinite(s).all() or not np.isfinite(w).all() or (s != np.rint(s)).any() or (w < 0).any() or not np.isclose(w.sum(), 1, atol=1e-12, rtol=0):
        raise ValueError('MARGIN_MEASURE_INVALID')


def summarize(support, weights):
    validate_measure(support, weights)
    s, w = np.asarray(support, dtype=float), np.asarray(weights)
    mean = float(w @ s)
    order = np.argsort(s); cdf = np.cumsum(w[order])
    quantiles = s[order][np.minimum(np.searchsorted(cdf, [.05, .1, .5, .9, .95]), len(s)-1)]
    home, away, tie = (float(w[np.sign(s) == sign].sum()) for sign in [1, -1, 0])
    return {'mean_home_margin': mean, 'margin_sd_points': float(np.sqrt(w @ ((s-mean)**2))),
            'quantiles_05_10_50_90_95': quantiles.tolist(), 'p_home_win': home,
            'p_away_win': away, 'p_tie': tie, 'p_home_non_tie': home/(home+away),
            'measure_sha256': digest({'support': s.tolist(), 'weights': w.tolist()})}


def price(support, weights, home_handicap, *, side='HOME', period='FULL_GAME'):
    validate_measure(support, weights)
    if period != 'FULL_GAME' or side not in {'HOME', 'AWAY'}:
        raise ValueError('QB_MARGIN_PRODUCT_UNSUPPORTED')
    if isinstance(home_handicap, bool) or not np.isfinite(home_handicap) or 2*home_handicap != round(2*home_handicap):
        raise ValueError('INTEGER_OR_HALF_HANDICAP_REQUIRED')
    result = (np.asarray(support, dtype=float) + home_handicap) * (1 if side == 'HOME' else -1)
    w = np.asarray(weights)
    return {'cover': float(w[result > 0].sum()), 'push': float(w[result == 0].sum()), 'loss': float(w[result < 0].sum())}


def simulate(support, weights, identity, n=100000):
    validate_measure(support, weights)
    if type(n) is not int or n < 1:
        raise ValueError('POSITIVE_INTEGER_SIMULATION_COUNT_REQUIRED')
    seed = int(digest({'identity': identity, 'distribution': DISTRIBUTION, 'n': n})[:16], 16)
    draws = np.random.default_rng(seed).choice(np.asarray(support, dtype='<i2'), size=n, p=weights).astype('<i2')
    return draws, {'seed': seed, 'n': n, 'rng': 'numpy.random.default_rng/PCG64',
                   'distribution': DISTRIBUTION, 'dtype': '<i2', 'shape': [n], 'order': 'C',
                   'raw_sha256': hashlib.sha256(draws.tobytes()).hexdigest(),
                   'summary': summarize(draws, np.full(n, 1/n))}


def load_registered():
    config = json.loads((DATA/'runtime.json').read_text())
    model_path, evaluation_path = DATA/config['model_file'], DATA/config['evaluation_file']
    if file_sha(model_path) != config['model_sha256'] or file_sha(evaluation_path) != config['evaluation_sha256']:
        raise ValueError('QB_MARGIN_REGISTERED_ARTIFACT_HASH')
    model, evaluation = json.loads(model_path.read_text()), json.loads(evaluation_path.read_text())
    if model['model_id'] != MODEL_ID or model['reference_model_id'] != REFERENCE_ID or model['market_input'] or model['action_authority']:
        raise ValueError('QB_MARGIN_MODEL_CONTRACT')
    if model['design_sha256'] != file_sha(DATA/'design.json') or model['code_sha256'] != file_sha(__file__):
        raise ValueError('QB_MARGIN_DESIGN_OR_CODE_HASH')
    return model, evaluation


def build(forecast, *, n=100000):
    """Build from a new or preserved QB forecast without mutating it."""
    model, evaluation = load_registered()
    now = dt.datetime.now(dt.timezone.utc)
    if forecast['model_id'] != REFERENCE_ID or forecast.get('selected_arm') != 'qb' or forecast.get('mode') != 'research_pregame':
        raise ValueError('QB_MARGIN_REFERENCE_REQUIRED')
    if forecast.get('market_input') is not False or forecast.get('action_authority') is not False:
        raise ValueError('QB_MARGIN_MARKET_AUTHORITY_FIREWALL')
    if utc(forecast['cutoff_utc']) > now or utc(model['fitted_at_utc']) > now or now >= utc(forecast['event']['start_time_utc']):
        raise ValueError('QB_MARGIN_PREGAME_CHRONOLOGY')
    if int(forecast['event']['event_id'].split('_')[0]) <= model['law']['max_season']:
        raise ValueError('QB_MARGIN_TRAINING_AFTER_EVENT')
    from .model import load_artifact
    reference_path = ROOT/'data/nfl/contextual_v1/model_packed.json'
    reference = load_artifact(reference_path)
    if file_sha(reference_path) != model['reference_packed_sha256'] or digest(reference) != forecast['model_artifact_sha256']:
        raise ValueError('QB_MARGIN_REFERENCE_HASH')
    qb = reference['arms']['qb']
    if digest(qb) != model['reference_qb_coefficients_sha256']:
        raise ValueError('QB_MARGIN_COEFFICIENT_HASH')
    features = {name: forecast['features'][name] for name in qb['feature_names']}
    actual = predict(qb, features)
    if actual['prediction'] != forecast['prediction']:
        raise ValueError('QB_MARGIN_HEAD_REPLAY_MISMATCH')
    p = actual['prediction']; support, weights = kernel(p['home_margin'], p['home_win'], model['law'])
    binding = {'reference_forecast_identity': forecast['identity'], 'reference_forecast_digest': digest(forecast),
               'model_sha256': digest(model), 'evaluation_sha256': digest(evaluation),
               'feature_sha256': digest(features), 'code_sha256': file_sha(__file__)}
    identity = digest(binding); draws, simulation = simulate(support, weights, identity, n)
    summary = summarize(support, weights)
    bundle = {'schema': 'nfl.qb_margin_forecast.v1', 'model_id': MODEL_ID, 'identity': identity,
              'reference_model_id': REFERENCE_ID, 'event': forecast['event'], 'created_at_utc': now.isoformat(),
              'information_cutoff_utc': now.isoformat(), 'reference_source_cutoff_utc': forecast['cutoff_utc'],
              'binding': binding, 'distribution': DISTRIBUTION, 'model_fitted_at_utc': model['fitted_at_utc'],
              'source_state': forecast.get('assimilation'), 'consumed_features': features,
              'head_predictions': p, 'head_contribution_trace': actual['contribution_trace'],
              'margin_support': support.tolist(), 'margin_weights': weights.tolist(),
              'model_summary': summary, 'simulation': simulation,
              'residual_law': {k: v for k, v in model['law'].items() if k not in {'residuals', 'game_ids', 'seasons'}},
              'coherence': {'non_tie_winner_head_preserved': abs(summary['p_home_non_tie']-p['home_win']) < 1e-12,
                            'mean_minus_ridge_center': summary['mean_home_margin']-p['home_margin'],
                            'scope': 'FINAL_MARGIN_ONLY_NOT_JOINT_SCORES'},
              'execution_status': 'COMPLETED', 'predictive_validation': 'HOLD',
              'retrospective_screen_passed': evaluation['retrospective_screen_passed'],
              'publication_eligibility': 'INELIGIBLE', 'canonical_prospective_eligible': False,
              'market_input': False, 'market_overlay_enabled': False, 'action_authority': False,
              'warnings': ['REUSED_RETROSPECTIVE_HISTORY_NOT_PIT_VALIDATION', 'NEW_DISTRIBUTION_NOT_PROSPECTIVELY_VALIDATED',
                           'INTEGER_KEY_NUMBER_CALIBRATION_UNESTABLISHED', 'TOTALS_AND_TEAM_SCORES_UNSUPPORTED']}
    return bundle, draws


def persist(folder, bundle, draws):
    """Actual-clock, exclusive writer. Never revises a parent forecast."""
    now = dt.datetime.now(dt.timezone.utc)
    if utc(bundle['information_cutoff_utc']) > now or now >= utc(bundle['event']['start_time_utc']):
        raise ValueError('QB_MARGIN_WRITER_CHRONOLOGY')
    if hashlib.sha256(np.asarray(draws).tobytes()).hexdigest() != bundle['simulation']['raw_sha256'] or len(draws) != bundle['simulation']['n']:
        raise ValueError('QB_MARGIN_DRAW_HASH')
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=False)
    registration = {'type': 'LOCAL_RESEARCH_MARGIN_ARTIFACT', 'created_at_utc': now.isoformat(),
                    'forecast_identity': bundle['identity'], 'model_id': MODEL_ID,
                    'information_cutoff_utc': bundle['information_cutoff_utc'],
                    'canonical_prospective_eligible': False, 'action_authority': False}
    registration['record_hash'] = digest(registration)
    (folder/'registration.jsonl').write_text(json.dumps(registration)+'\n')
    (folder/'forecast.json').write_text(json.dumps(bundle, indent=2, allow_nan=False)+'\n')
    np.save(folder/'margin_draws.npy', draws, allow_pickle=False)
    (folder/'manifest.json').write_text(json.dumps({p.name: file_sha(p) for p in folder.iterdir() if p.is_file()}, indent=2)+'\n')


def compare(bundle, draws, home_handicaps):
    """Settlement only, after generation; lines cannot enter the sampler."""
    if bundle['model_id'] != MODEL_ID or hashlib.sha256(np.asarray(draws).tobytes()).hexdigest() != bundle['simulation']['raw_sha256']:
        raise ValueError('QB_MARGIN_COMPARISON_BINDING')
    rows = []
    for line in home_handicaps:
        for side in ['HOME', 'AWAY']:
            exact = price(bundle['margin_support'], bundle['margin_weights'], line, side=side)
            mc = price(draws, np.full(len(draws), 1/len(draws)), line, side=side)
            rows.append({'team': bundle['event'][side.lower()+'_team'], 'side': side,
                         'handicap': float(line if side == 'HOME' else -line),
                         'model_cover_probability': exact['cover'], 'sim_cover_probability': mc['cover'],
                         'model': exact, 'simulation': mc})
    return {'schema': 'nfl.qb_margin_comparison.v1', 'model_id': MODEL_ID,
            'forecast_identity': bundle['identity'], 'forecast_digest': digest(bundle),
            'draw_sha256': bundle['simulation']['raw_sha256'], 'rows': rows,
            'market_overlay_enabled': False, 'action_authority': False}
