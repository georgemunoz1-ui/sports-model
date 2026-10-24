#!/usr/bin/env python3
"""Independent reconstruction and inverse-CDF replay of a QB margin run."""
import argparse
import collections
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.recovered_inference import digest, utc


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reconstruct(model, parent, reference):
    params = reference['arms']['qb']; values = parent['features']; heads = {}
    for target in ['home_win', 'home_margin']:
        h = params['heads'][target]
        raw = np.array([np.nan if values[name] is None else values[name] for name in params['feature_names']])
        used = np.where(np.isnan(raw), h['impute'], raw)
        terms = (used-np.asarray(h['center']))/np.asarray(h['scale'])*np.asarray(h['coefficient'])
        linear = float(terms.sum()+h['intercept'])
        heads[target] = 1/(1+np.exp(-linear)) if target == 'home_win' else linear
    errors = np.asarray(model['law']['residuals'])
    shifted = np.rint(heads['home_margin']+errors-errors.mean()).astype('<i2')
    counts = collections.Counter(map(int, shifted)); support = np.array(sorted(counts), dtype='<i2')
    totals = {sign: sum(n for margin, n in counts.items() if np.sign(margin) == sign) for sign in [-1, 0, 1]}
    t = model['law']['tie_rate']; masses = {-1: (1-t)*(1-heads['home_win']), 0: t, 1: (1-t)*heads['home_win']}
    weights = np.array([counts[int(m)]/totals[np.sign(m)]*masses[np.sign(m)] for m in support])
    return support, weights, heads


def main():
    p = argparse.ArgumentParser(); p.add_argument('--run-root', type=Path, required=True)
    p.add_argument('--source-dir', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    cfg = json.loads((ROOT/'data/nfl/qb_margin_v1/runtime.json').read_text())
    model_path = ROOT/'data/nfl/qb_margin_v1'/cfg['model_file']
    assert sha(model_path) == cfg['model_sha256']
    model = json.loads(model_path.read_text())
    reference = load_artifact(ROOT/'data/nfl/contextual_v1/model_packed.json')
    assert digest(reference['arms']['qb']) == model['reference_qb_coefficients_sha256']
    source = a.source_dir/'oof_predictions.csv'
    assert sha(source) == model['source_sha256']['oof_predictions.csv']
    q = pd.read_csv(source); q = q[q.arm == 'qb'].sort_values(['season', 'week', 'game_id'])
    assert q.game_id.tolist() == model['law']['game_ids']
    residuals = (q.home_margin-q.pred_margin).to_numpy()
    np.testing.assert_array_equal(residuals, model['law']['residuals'])
    assert float(residuals.std(ddof=0)) == model['law']['residual_sigma_points']
    assert q.season.max() == 2025 and len(q) == 1871
    reports = []
    paths = sorted(a.run_root.glob('*/2026_*/qb_margin/forecast.json'))
    if not paths:
        raise ValueError('NO_MARGIN_FORECASTS')
    for path in paths:
        folder = path.parent; event_dir = folder.parent
        for directory in [folder, event_dir]:
            for filename, expected in json.loads((directory/'manifest.json').read_text()).items():
                assert sha(directory/filename) == expected
        f = json.loads(path.read_text()); parent = json.loads((event_dir/'forecast.json').read_text())
        before = {str(v): sha(v) for v in event_dir.rglob('*') if v.is_file()}
        registration = json.loads((folder/'registration.jsonl').read_text())
        record_hash = registration.pop('record_hash'); assert digest(registration) == record_hash
        assert utc(model['fitted_at_utc']) <= utc(f['information_cutoff_utc']) <= utc(registration['created_at_utc']) < utc(f['event']['start_time_utc'])
        assert utc(parent['cutoff_utc']) <= utc(f['information_cutoff_utc'])
        assert digest(parent) == f['binding']['reference_forecast_digest']
        assert parent['assimilation']['completed_week'] == 2 and len(parent['assimilation']['consumed_game_ids']) == 32
        assert f['source_state'] == parent['assimilation']
        assert all(parent['features'][k] == v for k, v in parent['assimilation']['state_feature_values'].items())
        support, weights, heads = reconstruct(model, parent, reference)
        np.testing.assert_array_equal(support, f['margin_support'])
        np.testing.assert_allclose(weights, f['margin_weights'], atol=1e-15, rtol=0)
        assert abs(heads['home_win']-parent['prediction']['home_win']) < 1e-15
        assert abs(heads['home_margin']-parent['prediction']['home_margin']) < 1e-12
        seed = int(digest({'identity': f['identity'], 'distribution': f['distribution'], 'n': 100000})[:16], 16)
        assert seed == f['simulation']['seed']
        cdf = np.cumsum(weights); cdf /= cdf[-1]
        independently_sampled = support[np.searchsorted(cdf, np.random.Generator(np.random.PCG64(seed)).random(100000), side='right')]
        saved = np.load(folder/'margin_draws.npy', allow_pickle=False)
        np.testing.assert_array_equal(independently_sampled, saved)
        assert saved.dtype == np.dtype('<i2') and saved.shape == (100000,)
        assert hashlib.sha256(saved.tobytes()).hexdigest() == f['simulation']['raw_sha256']
        comparison = json.loads((event_dir/'qb_margin_comparison.json').read_text())
        assert comparison['forecast_digest'] == digest(f) and comparison['draw_sha256'] == f['simulation']['raw_sha256']
        for row in comparison['rows']:
            sign = 1 if row['side'] == 'HOME' else -1
            exact = float(weights[sign*support+row['handicap'] > 0].sum())
            mc = float(np.mean(sign*saved.astype(np.int64)+row['handicap'] > 0))
            assert abs(exact-row['model_cover_probability']) < 1e-14
            assert abs(mc-row['sim_cover_probability']) < 1e-14
            assert abs(exact-mc) <= 6*np.sqrt(exact*(1-exact)/len(saved))
        # A synthetic perturbation is a sensitivity proof, never a second real forecast.
        changed = json.loads(json.dumps(parent)); changed['features']['qb_quality_diff'] += .01
        xs, xw, _ = reconstruct(model, changed, reference)
        before_cover = float(weights[support+3.5 > 0].sum())
        after_cover = float(xw[xs+3.5 > 0].sum())
        assert abs(after_cover-before_cover) > 1e-8
        unused = json.loads(json.dumps(parent)); unused['features']['report_missing_count'] = 0.0
        us, uw, uh = reconstruct(model, unused, reference)
        np.testing.assert_array_equal(us, support); np.testing.assert_array_equal(uw, weights)
        assert 'report_missing_count' not in f['consumed_features']
        assert all(sha(Path(v)) == h for v, h in before.items())
        reports.append({'scenario': event_dir.parent.name, 'forecast_identity': f['identity'],
            'forecast_sha256': sha(path), 'parent_forecast_sha256': sha(event_dir/'forecast.json'),
            'margin_npy_sha256': sha(folder/'margin_draws.npy'), 'raw_draw_sha256': f['simulation']['raw_sha256'],
            'seed': seed, 'draws': 100000, 'source_cutoff_utc': parent['cutoff_utc'],
            'distribution_cutoff_utc': f['information_cutoff_utc'], 'registered_at_utc': registration['created_at_utc'],
            'state_id': parent['assimilation']['state_id'],
            'eight_bindings': {'model_code_coefficients': 'PASS', 'sources_parent_state': 'PASS', 'consumed_features': 'PASS',
                'heads_orientation': 'PASS', 'qb_noise_law_sigma': 'PASS', 'sampler_seed_draw_hash': 'EXACT_INVERSE_CDF_REPLAY',
                'settlement_coherence': 'PASS', 'independent_replay_effect': 'PASS'},
            'sensitivity_probe': {'synthetic_not_forecast': True, 'qb_quality_diff_delta': .01,
                'home_cover_probability_delta': after_cover-before_cover, 'report_missing_count_effect': 0.0},
            'availability_missingness_orientation': {'home_indicator': 'CHI_DESIGNATED_HOME_NON_NEUTRAL',
                'home_missing_report': True, 'away_missing_report': True, 'combined_report_missing_count': 2,
                'qb_model_status': 'NOT_USED', 'combined_model_status': 'QUARANTINED_NOT_CONSUMED'},
            'input_flags': ['CHICAGO_STARTER_UNRESOLVED', 'FINAL_INACTIVES_PENDING', 'WEATHER_FITTED_IMPUTATION',
                            'NON_QB_AVAILABILITY_NOT_NUMERICALLY_USED', 'OFFICIAL_GAMEBOOK_CLEARANCE_FALSE'],
            'original_freeze_unchanged': True, 'market_overlay_enabled': False, 'action_authority': False})
    protected = json.loads((a.run_root/'protected_parent_manifest.json').read_text())
    assert all(sha(ROOT/name) == h for name, h in protected.items())
    result = {'schema': 'nfl.qb_margin_verification.v1', 'verified_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'model_id': model['model_id'], 'model_file_sha256': sha(model_path), 'rows': reports,
              'historical_residual_rows_verified': len(q), 'old_protected_files_verified': len(protected),
              'execution_status': 'COMPLETED', 'predictive_validation': 'HOLD',
              'publication_eligibility': 'INELIGIBLE', 'action_authority': False}
    with a.output.open('x') as handle:
        json.dump(result, handle, indent=2, allow_nan=False); handle.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
