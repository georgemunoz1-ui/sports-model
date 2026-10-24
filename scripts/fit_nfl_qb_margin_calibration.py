#!/usr/bin/env python3
"""Nested chronological, globally optimized one-weight QB margin calibration."""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from models.nfl.contextual import qb_margin as base, qb_margin_calibration as cal
from models.nfl.contextual.recovered_inference import digest
from scripts.fit_nfl_qb_margin import crps, normal_measure, metrics


def evaluate(cached, alpha, lines):
    row = cached['row']; s, w = cal.blend(cached['s0'], cached['w0'], cached['s1'], cached['w1'], alpha)
    summary = base.summarize(s, w); ns, nw = normal_measure(row['pred_margin'], cached['sigma'])
    output = {'game_id': row['game_id'], 'season': int(row['season']), 'week': int(row['week']),
        'alpha': alpha, 'max_history_season': cached['max_history_season'],
        'candidate_crps': crps(s, w, row['home_margin']), 'reference_crps': crps(cached['s0'], cached['w0'], row['home_margin']),
        'normal_crps': crps(ns, nw, row['home_margin']), 'mean_error': summary['mean_home_margin']-row['home_margin'],
        'interval_90_covered': summary['quantiles_05_10_50_90_95'][0] <= row['home_margin'] <= summary['quantiles_05_10_50_90_95'][-1],
        'interval_90_width': summary['quantiles_05_10_50_90_95'][-1]-summary['quantiles_05_10_50_90_95'][0],
        'p_tie': summary['p_tie'], 'actual_tie': row['home_margin'] == 0,
        'conditional_effective_n': cached['effective_n'], 'contracts': []}
    for line in lines:
        p = base.price(s, w, line); q = base.price(cached['s0'], cached['w0'], line)
        actual = np.array([row['home_margin']+line > 0, row['home_margin']+line == 0, row['home_margin']+line < 0], float)
        pv, qv = np.array(list(p.values())), np.array(list(q.values()))
        output['contracts'].append({'home_handicap': line, 'candidate': p, 'reference': q, 'actual': actual.tolist(),
            'candidate_brier': float(np.sum((pv-actual)**2)), 'reference_brier': float(np.sum((qv-actual)**2)),
            'candidate_log_loss_clipped': float(-np.log(np.clip(pv[actual.astype(bool)][0], 1e-12, 1))),
            'reference_log_loss_clipped': float(-np.log(np.clip(qv[actual.astype(bool)][0], 1e-12, 1))),
            'candidate_zero_mass_observation': bool(pv[actual.astype(bool)][0] == 0)})
    return output


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--source-dir', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True); ap.add_argument('--prereg-commit', required=True)
    a = ap.parse_args(); design = json.loads((cal.DATA/'design.json').read_text())
    if a.output.exists(): raise ValueError('CALIBRATION_FIT_OUTPUT_EXISTS')
    path = a.source_dir/'oof_predictions.csv'
    if base.file_sha(path) != design['source_oof_sha256']: raise ValueError('CALIBRATION_SOURCE_HASH')
    source = pd.read_csv(path); q = source[source.arm == 'qb'].sort_values(['season', 'week', 'game_id'])
    features = pd.read_csv(a.source_dir/'features.csv').set_index('game_id')
    if base.file_sha(a.source_dir/'features.csv') != json.loads((base.DATA/'design.json').read_text())['input_sha256']['features.csv']:
        raise ValueError('CALIBRATION_FEATURE_SOURCE_HASH')
    cache, terms = [], []
    for year in range(2020, 2026):
        prior = q[q.season < year].to_dict('records')
        law = base.fit_residuals(prior, before_season=year); history = cal.fit_integer_history(prior, before_season=year)
        for row in q[q.season == year].to_dict('records'):
            s0, w0 = base.kernel(row['pred_margin'], row['p_home'], law)
            s1, w1, effective = cal.integer_kernel(row['pred_margin'], row['p_home'], history)
            g, h = cal.quadratic_terms(s0, w0, s1, w1, row['home_margin'])
            terms.append({'game_id': row['game_id'], 'season': int(row['season']), 'gradient_half': g,
                          'curvature_half': h, 'max_history_season': year-1})
            cache.append({'row': row, 's0': s0, 'w0': w0, 's1': s1, 'w1': w1, 'effective_n': effective,
                          'max_history_season': law['max_season'], 'sigma': law['residual_sigma_points']})
        print('Inner prior-only distribution fold', year, len(prior), flush=True)
    rows, fits = [], {}
    for year in design['calibration']['outer_evaluation_years']:
        fitted = cal.optimize_alpha([r for r in terms if r['season'] < year], before_season=year); fits[str(year)] = fitted
        for c in cache:
            if c['row']['season'] != year: continue
            result = evaluate(c, fitted['alpha'], design['screen']['fixed_home_handicaps'])
            result['calibration_max_season'] = fitted['max_season']
            result['neutral_site'] = bool(features.loc[result['game_id'], 'neutral_site'])
            result['report_missing_count'] = int(features.loc[result['game_id'], 'report_missing_count'])
            rows.append(result)
        print('Outer evaluation', year, 'alpha', fitted['alpha'], 'calibration rows', fitted['games'], flush=True)
    m = metrics(rows); m['normal_reference_crps'] = float(np.mean([r['normal_crps'] for r in rows]))
    m['reference_key_number_push'] = {}
    for key in [3, 7]:
        contracts = [c for r in rows for c in r['contracts'] if abs(c['home_handicap']) == key]
        m['reference_key_number_push'][str(key)] = {'predicted': float(np.mean([c['reference']['push'] for c in contracts])),
                                                  'observed': float(np.mean([c['actual'][1] for c in contracts]))}
    years = design['calibration']['outer_evaluation_years']; rng = np.random.default_rng(design['screen']['bootstrap_seed'])
    sums = np.array([sum(r['candidate_crps']-r['reference_crps'] for r in rows if r['season'] == year) for year in years])
    counts = np.array([sum(r['season'] == year for r in rows) for year in years])
    idx = rng.integers(len(years), size=(design['screen']['bootstrap_replicates'], len(years)))
    ci = np.quantile(sums[idx].sum(axis=1)/counts[idx].sum(axis=1), [.025, .975]).tolist()
    bounds = design['screen']['interval_90_coverage_bounds']; screen = design['screen']
    criteria = {'crps_mean_vs_v1': m['candidate_crps']-m['reference_crps'] <= screen['mean_crps_delta_max'],
        'crps_season_ci': ci[1] <= screen['season_bootstrap_95_ci_upper_max'],
        'crps_mean_vs_normal': m['candidate_crps']-m['normal_reference_crps'] <= screen['normal_reference_crps_delta_max'],
        'cover_brier': m['candidate_brier']-m['reference_brier'] <= screen['cover_three_way_brier_delta_max'],
        'interval_90': bounds[0] <= m['interval_90_coverage'] <= bounds[1]}
    for key in ['3', '7']:
        v, b = m['key_number_push'][key], m['reference_key_number_push'][key]
        criteria['key_'+key+'_push'] = abs(v['predicted']-v['observed']) <= abs(b['predicted']-b['observed'])
    reliability = []
    contracts = [c for r in rows for c in r['contracts']]
    for k in range(10):
        group = [c for c in contracts if min(9, int(c['candidate']['cover']*10)) == k]
        reliability.append({'bin': [k/10, (k+1)/10], 'n': len(group),
            'predicted': float(np.mean([c['candidate']['cover'] for c in group])) if group else None,
            'observed': float(np.mean([c['actual'][0] for c in group])) if group else None})
    report = {'model_id': cal.MODEL_ID, 'design_sha256': base.file_sha(cal.DATA/'design.json'),
        'preregistration_commit': a.prereg_commit, 'retrospective_screen_passed': all(criteria.values()), 'criteria': criteria,
        'metrics': m, 'paired_crps_season_bootstrap_95_ci': ci, 'outer_calibrations': fits,
        'by_season': {str(y): metrics([r for r in rows if r['season'] == y]) for y in years},
        'weeks_1_to_4': metrics([r for r in rows if r['week'] <= 4]),
        'neutral_venue': metrics([r for r in rows if r['neutral_site']]),
        'missingness_cohorts': {str(k): metrics([r for r in rows if r['report_missing_count'] == k]) for k in [0, 1, 2]},
        'reliability_bins': reliability, 'lowest_conditional_effective_n': min(min(r['conditional_effective_n'].values()) for r in rows),
        'population': 'All paired 2022-2025 QB REG OOF games; no outcome exclusions',
        'evidence': 'REUSED_RETROSPECTIVE_NESTED_CHRONOLOGICAL_NOT_UNTOUCHED_HOLDOUT',
        'predictive_validation': 'HOLD', 'production_promotion': False, 'research_grading_enabled': True,
        'market_comparison_display_enabled': True, 'market_input': False, 'action_authority': False}
    reference, _ = base.load_registered()
    model = {'schema': 'nfl.qb_margin_calibration_model.v1', 'model_id': cal.MODEL_ID,
        'reference_model_id': base.MODEL_ID, 'reference_margin_model_sha256': digest(reference),
        'fitted_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'preregistration_commit': a.prereg_commit,
        'source_oof_sha256': design['source_oof_sha256'], 'design_sha256': base.file_sha(cal.DATA/'design.json'),
        'code_sha256': base.file_sha(cal.__file__), 'fit_code_sha256': base.file_sha(__file__),
        'integer_history': cal.fit_integer_history(q.to_dict('records'), before_season=2026),
        'calibration': cal.optimize_alpha(terms, before_season=2026),
        'market_input': False, 'predictive_market_overlay_enabled': False, 'action_authority': False, 'production_promotion': False}
    a.output.mkdir(parents=True, exist_ok=False)
    for name, value in [('model.json', model), ('evaluation.json', report), ('evaluation_rows.json', rows), ('calibration_terms.json', terms)]:
        (a.output/name).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'passed': report['retrospective_screen_passed'], 'criteria': criteria, 'metrics': m,
                      'crps_ci': ci, 'deployment_calibration': model['calibration']}, indent=2))


if __name__ == '__main__': main()
