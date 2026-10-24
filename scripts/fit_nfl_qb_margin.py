#!/usr/bin/env python3
"""Fit the preregistered QB-only residual law; evaluate past-season-only pools."""
import argparse
import datetime as dt
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import scipy
import sklearn
from scipy.special import ndtr
from models.nfl.contextual import qb_margin as qm
from models.nfl.contextual.model import fit, load_artifact, predict_frame
from models.nfl.contextual.recovered_inference import digest


def crps(support, weights, actual):
    order = np.argsort(support); s, w = np.asarray(support)[order], np.asarray(weights)[order]
    return float(w @ abs(s-actual) - np.sum(w*s*(2*np.cumsum(w)-w-1)))


def normal_measure(location, sigma):
    # Rounded-normal reference: omitted tail below double-precision tolerance.
    s = np.arange(int(np.floor(location-12*sigma))-1, int(np.ceil(location+12*sigma))+2)
    w = ndtr((s+.5-location)/sigma)-ndtr((s-.5-location)/sigma)
    if not np.isclose(w.sum(), 1, atol=1e-14, rtol=0):
        raise ValueError('NORMAL_REFERENCE_TAIL_MASS')
    return s, w


def evaluate_row(row, law, lines):
    support, weights = qm.kernel(row.pred_margin, row.p_home, law)
    ns, nw = normal_measure(row.pred_margin, law['residual_sigma_points'])
    summary = qm.summarize(support, weights)
    out = {'game_id': row.game_id, 'season': int(row.season), 'week': int(row.week),
           'max_residual_season': law['max_season'], 'residual_count': law['count'],
           'candidate_crps': crps(support, weights, row.home_margin), 'reference_crps': crps(ns, nw, row.home_margin),
           'mean_error': summary['mean_home_margin']-row.home_margin,
           'interval_90_covered': summary['quantiles_05_10_50_90_95'][0] <= row.home_margin <= summary['quantiles_05_10_50_90_95'][-1],
           'interval_90_width': summary['quantiles_05_10_50_90_95'][-1]-summary['quantiles_05_10_50_90_95'][0],
           'p_tie': summary['p_tie'], 'actual_tie': row.home_margin == 0, 'contracts': []}
    for line in lines:
        a, b = qm.price(support, weights, line), qm.price(ns, nw, line)
        truth = np.array([row.home_margin+line > 0, row.home_margin+line == 0, row.home_margin+line < 0], dtype=float)
        p, q = np.array(list(a.values())), np.array(list(b.values()))
        out['contracts'].append({'home_handicap': line, 'candidate': a, 'reference': b,
            'actual': truth.tolist(), 'candidate_brier': float(np.sum((p-truth)**2)),
            'reference_brier': float(np.sum((q-truth)**2)),
            'candidate_log_loss_clipped': float(-np.log(np.clip(p[truth.astype(bool)][0], 1e-12, 1))),
            'reference_log_loss_clipped': float(-np.log(np.clip(q[truth.astype(bool)][0], 1e-12, 1))),
            'candidate_zero_mass_observation': bool(p[truth.astype(bool)][0] == 0)})
    return out


def metrics(rows):
    if not rows:
        return {'games': 0}
    contracts = [c for r in rows for c in r['contracts']]
    m = {'games': len(rows), 'contracts': len(contracts),
         'candidate_crps': float(np.mean([r['candidate_crps'] for r in rows])),
         'reference_crps': float(np.mean([r['reference_crps'] for r in rows])),
         'margin_mean_mae': float(np.mean([abs(r['mean_error']) for r in rows])),
         'margin_mean_rmse': float(np.sqrt(np.mean([r['mean_error']**2 for r in rows]))),
         'interval_90_coverage': float(np.mean([r['interval_90_covered'] for r in rows])),
         'interval_90_width': float(np.mean([r['interval_90_width'] for r in rows])),
         'predicted_tie_rate': float(np.mean([r['p_tie'] for r in rows])),
         'observed_tie_rate': float(np.mean([r['actual_tie'] for r in rows]))}
    for k in ['candidate_brier', 'reference_brier', 'candidate_log_loss_clipped', 'reference_log_loss_clipped']:
        m[k] = float(np.mean([c[k] for c in contracts]))
    m['candidate_zero_mass_observations'] = sum(c['candidate_zero_mass_observation'] for c in contracts)
    m['key_number_push'] = {}
    for key in [3, 7]:
        subset = [c for c in contracts if abs(c['home_handicap']) == key]
        m['key_number_push'][str(key)] = {'contracts': len(subset),
            'predicted': float(np.mean([c['candidate']['push'] for c in subset])),
            'observed': float(np.mean([c['actual'][1] for c in subset]))}
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-dir', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--prereg-commit', required=True)
    a = ap.parse_args()
    design_path = qm.DATA/'design.json'; design = json.loads(design_path.read_text())
    if a.output.exists():
        raise ValueError('FIT_OUTPUT_EXISTS')
    for name, expected in design['input_sha256'].items():
        if qm.file_sha(a.source_dir/name) != expected:
            raise ValueError('FIT_SOURCE_HASH:'+name)
    oof = pd.read_csv(a.source_dir/'oof_predictions.csv')
    features = pd.read_csv(a.source_dir/'features.csv')
    if features.game_id.duplicated().any() or oof.duplicated(['arm', 'game_id']).any():
        raise ValueError('FIT_SOURCE_DUPLICATE')
    q = oof[oof.arm == 'qb'].sort_values(['season', 'week', 'game_id']).copy()
    if set(q.season) != set(range(2019, 2026)):
        raise ValueError('QB_OOF_SEASON_COVERAGE')
    reference = load_artifact(ROOT/'data/nfl/contextual_v1/model_packed.json')
    if qm.file_sha(ROOT/'data/nfl/contextual_v1/model_packed.json') != design['reference_model_packed_sha256']:
        raise ValueError('FIT_REFERENCE_HASH')
    checks, fold_models = [], {}
    # Refit only historical heads for independent OOF provenance checks.
    # Live inference continues to use the byte-identical registered QB heads.
    for season in range(2019, 2026):
        training = features[features.season < season]
        saved = q[q.season == season].set_index('game_id')
        test = features.set_index('game_id').loc[saved.index]
        params = fit(training, 'qb', reference['design'])
        if max(params['training_seasons']) >= season:
            raise ValueError('HEAD_FOLD_LEAKAGE')
        predicted = predict_frame(params, test)
        diffs = {target: float(np.max(abs(predicted[target].to_numpy()-saved[column].to_numpy())))
                 for target, column in [('home_win', 'p_home'), ('home_margin', 'pred_margin'), ('total_points', 'pred_total')]}
        if diffs['home_win'] > 1e-5 or max(diffs['home_margin'], diffs['total_points']) > 1e-8:
            raise ValueError('ARCHIVED_QB_OOF_REPLAY:'+json.dumps(diffs))
        if not np.array_equal(test.home_margin.to_numpy(), saved.home_margin.to_numpy()):
            raise ValueError('QB_OOF_OUTCOME_BINDING')
        checks.append({'season': season, 'training_max_season': max(params['training_seasons']),
                       'training_rows': params['training_rows'], 'oof_games': len(saved),
                       'max_absolute_replay_difference': diffs, 'parameter_sha256': digest(params)})
        fold_models[str(season)] = params
        print('QB chronological head replay', season, len(saved), diffs, flush=True)
    rows = []
    by_game = features.set_index('game_id')
    for season in design['history']['distribution_evaluation_seasons']:
        law = qm.fit_residuals(q[q.season < season].to_dict('records'), before_season=season)
        for row in q[q.season == season].itertuples(index=False):
            r = evaluate_row(row, law, design['evaluation']['fixed_home_handicaps'])
            r['neutral_site'] = bool(by_game.loc[row.game_id, 'neutral_site'])
            r['report_missing_count'] = int(by_game.loc[row.game_id, 'report_missing_count'])
            rows.append(r)
        print('Margin fold', season, 'prior-only residuals', law['count'], flush=True)
    all_metrics = metrics(rows)
    rng = np.random.default_rng(design['evaluation']['bootstrap']['seed'])
    years = design['history']['distribution_evaluation_seasons']
    sums = np.array([sum(r['candidate_crps']-r['reference_crps'] for r in rows if r['season'] == y) for y in years])
    counts = np.array([sum(r['season'] == y for r in rows) for y in years])
    idx = rng.integers(len(years), size=(10000, len(years)))
    ci = np.quantile(sums[idx].sum(axis=1)/counts[idx].sum(axis=1), [.025, .975]).tolist()
    gate = design['evaluation']['screen']
    criteria = {'crps_mean': all_metrics['candidate_crps']-all_metrics['reference_crps'] <= gate['mean_delta_max'],
                'crps_season_ci': ci[1] <= gate['season_bootstrap_ci_upper_max'],
                'cover_brier': all_metrics['candidate_brier']-all_metrics['reference_brier'] <= gate['cover_brier_delta_max'],
                'interval_90': gate['interval_90_coverage_min'] <= all_metrics['interval_90_coverage'] <= gate['interval_90_coverage_max']}
    report = {'model_id': qm.MODEL_ID, 'design_sha256': qm.file_sha(design_path),
              'preregistration_commit': a.prereg_commit, 'retrospective_screen_passed': all(criteria.values()),
              'criteria': criteria, 'metrics': all_metrics, 'paired_crps_season_bootstrap_95_ci': ci,
              'by_season': {str(y): metrics([r for r in rows if r['season'] == y]) for y in years},
              'weeks_1_to_4': metrics([r for r in rows if r['week'] <= 4]),
              'neutral_venue': metrics([r for r in rows if r['neutral_site']]),
              'missingness_cohorts': {str(k): metrics([r for r in rows if r['report_missing_count'] == k]) for k in [0, 1, 2]},
              'head_replay': checks, 'population': 'All 2020-2025 saved QB REG OOF games including ties; no outcome-based exclusions',
              'evidence': 'REUSED_RETROSPECTIVE_HISTORY_NOT_ORIGINAL_PIT_OR_UNTOUCHED_HOLDOUT',
              'market_line_evaluation': False, 'predictive_validation': 'HOLD', 'promotion': False,
              'publication_eligibility': 'INELIGIBLE', 'action_authority': False}
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    model = {'schema': 'nfl.qb_margin_model.v1', 'model_id': qm.MODEL_ID, 'reference_model_id': qm.REFERENCE_ID,
             'distribution': qm.DISTRIBUTION, 'fitted_at_utc': now, 'preregistration_commit': a.prereg_commit,
             'reference_packed_sha256': design['reference_model_packed_sha256'],
             'reference_qb_coefficients_sha256': digest(reference['arms']['qb']),
             'source_sha256': design['input_sha256'], 'design_sha256': qm.file_sha(design_path),
             'code_sha256': qm.file_sha(qm.__file__), 'fit_code_sha256': qm.file_sha(__file__),
             'law': qm.fit_residuals(q.to_dict('records'), before_season=2026),
             'environment': {'python': platform.python_version(), 'numpy': np.__version__, 'pandas': pd.__version__,
                             'scipy': scipy.__version__, 'sklearn': sklearn.__version__},
             'market_input': False, 'market_overlay_enabled': False, 'action_authority': False, 'promotion': False}
    a.output.mkdir(parents=True, exist_ok=False)
    for name, obj in [('model.json', model), ('evaluation.json', report), ('evaluation_rows.json', rows), ('fold_models.json', fold_models)]:
        (a.output/name).write_text(json.dumps(obj, indent=2, allow_nan=False)+'\n')
    q.to_csv(a.output/'qb_oof_predictions.csv', index=False)
    print(json.dumps({'retrospective_screen_passed': report['retrospective_screen_passed'], 'criteria': criteria,
                      'metrics': all_metrics, 'crps_ci': ci, 'deployment_sigma': model['law']['residual_sigma_points']}, indent=2))


if __name__ == '__main__':
    main()
