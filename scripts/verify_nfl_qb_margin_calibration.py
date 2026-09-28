#!/usr/bin/env python3
"""Independent CDF reconstruction, optimizer replay and saved-draw audit."""
import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from models.nfl.contextual import qb_margin as base, qb_margin_calibration as cal
from models.nfl.contextual.recovered_inference import digest, utc
from models.nfl.contextual.research_grading import status, records


def independent_integer(history, location, probability):
    x = np.asarray(history['winner_oriented_qb_prediction']); magnitudes = np.asarray(history['winning_integer_margin'])
    atoms = {0: history['tie_rate']}
    for sign, mass in [(1, probability), (-1, 1-probability)]:
        weights = np.exp(-((x-sign*location)**2)/(2*4.0**2)); weights /= weights.sum()
        for y, w in zip(magnitudes, weights):
            k = int(sign*y); atoms[k] = atoms.get(k, 0)+float(w*(1-history['tie_rate'])*mass)
    return atoms


def main():
    p = argparse.ArgumentParser(); p.add_argument('--source-dir', type=Path, required=True); p.add_argument('--run-root', type=Path, required=True)
    p.add_argument('--grading-store', type=Path, required=True); p.add_argument('--output', type=Path, required=True); a = p.parse_args()
    model, evaluation = cal.load_registered(); config = json.loads((cal.DATA/'runtime.json').read_text())
    source = a.source_dir/'oof_predictions.csv'; assert base.file_sha(source) == model['source_oof_sha256']
    q = pd.read_csv(source); q = q[q.arm == 'qb'].sort_values(['season', 'week', 'game_id']); non_ties = q[q.home_margin != 0]
    h = model['integer_history']; np.testing.assert_array_equal(np.sign(non_ties.home_margin)*non_ties.pred_margin, h['winner_oriented_qb_prediction'])
    np.testing.assert_array_equal(np.abs(non_ties.home_margin), h['winning_integer_margin']); assert q.game_id.tolist() == h['game_ids']
    terms = json.loads((cal.DATA/'fit_01/calibration_terms.json').read_text()); recomputed = []
    for year in range(2020, 2026):
        prior = q[q.season < year].to_dict('records'); law = base.fit_residuals(prior, before_season=year)
        hist = cal.fit_integer_history(prior, before_season=year)
        for row in q[q.season == year].to_dict('records'):
            s0, w0 = base.kernel(row['pred_margin'], row['p_home'], law); integer = independent_integer(hist, row['pred_margin'], row['p_home'])
            grid = np.arange(min(min(s0), min(integer), row['home_margin']), max(max(s0), max(integer), row['home_margin'])+1)
            f0 = np.array([sum(w for s, w in zip(s0, w0) if s <= threshold) for threshold in grid])
            f1 = np.array([sum(w for s, w in integer.items() if s <= threshold) for threshold in grid])
            delta = f1-f0; g = float(np.sum((f0-(grid >= row['home_margin']))*delta)); curvature = float(delta@delta)
            recomputed.append({'game_id': row['game_id'], 'season': year, 'gradient_half': g, 'curvature_half': curvature})
    assert [r['game_id'] for r in recomputed] == [r['game_id'] for r in terms]
    np.testing.assert_allclose([[r['gradient_half'], r['curvature_half']] for r in recomputed], [[r['gradient_half'], r['curvature_half']] for r in terms], atol=1e-12, rtol=0)
    for year in [2022, 2023, 2024, 2025, 2026]:
        past = [r for r in recomputed if r['season'] < year]
        alpha = np.clip(-sum(r['gradient_half'] for r in past)/sum(r['curvature_half'] for r in past), 0, 1)
        fitted = model['calibration'] if year == 2026 else evaluation['outer_calibrations'][str(year)]
        assert abs(alpha-fitted['alpha']) < 1e-12 and fitted['max_season'] < year
    reports = []
    registry = records(a.grading_store)
    for path in sorted(a.run_root.glob('*/2026_*/qb_margin_calibrated/forecast.json')):
        folder = path.parent; parent = json.loads((folder.parent/'forecast.json').read_text()); f = json.loads(path.read_text())
        for directory in [folder, folder.parent]:
            for name, expected in json.loads((directory/'manifest.json').read_text()).items(): assert base.file_sha(directory/name) == expected
        law, _ = base.load_registered(); s0, w0 = base.kernel(parent['prediction']['home_margin'], parent['prediction']['home_win'], law['law'])
        integer = independent_integer(h, parent['prediction']['home_margin'], parent['prediction']['home_win'])
        alpha = model['calibration']['alpha']; atoms = {int(s): float((1-alpha)*w) for s, w in zip(s0, w0)}
        for s, w in integer.items(): atoms[s] = atoms.get(s, 0)+alpha*w
        support = np.array(sorted(atoms), dtype='<i2'); weight = np.array([atoms[int(s)] for s in support])
        np.testing.assert_array_equal(support, f['margin_support']); np.testing.assert_allclose(weight, f['margin_weights'], atol=1e-15, rtol=0)
        seed = int(digest({'identity': f['identity'], 'distribution': f['distribution'], 'n': 100000})[:16], 16)
        cdf = np.cumsum(weight); cdf /= cdf[-1]; independent_draws = support[np.searchsorted(cdf, np.random.Generator(np.random.PCG64(seed)).random(100000), side='right')]
        draws = np.load(folder/'margin_draws.npy', allow_pickle=False); np.testing.assert_array_equal(independent_draws, draws)
        assert seed == f['simulation']['seed'] and hashlib.sha256(draws.tobytes()).hexdigest() == f['simulation']['raw_sha256']
        board = json.loads((folder.parent/'board.json').read_text()); assert board['margin_forecast_sha256'] == digest(f)
        assert board['market_overlay']['display_enabled'] and not board['market_overlay']['predictive_input_enabled']
        for r in board['spread_rows']:
            sign = 1 if r['side'] == 'HOME' else -1
            exact = float(weight[sign*support+r['handicap'] > 0].sum()); mc = float(np.mean(sign*draws.astype(float)+r['handicap'] > 0))
            assert abs(exact-r['model_cover_probability']) < 1e-14 and abs(mc-r['sim_cover_probability']) < 1e-14
            assert abs(exact-mc) < 6*np.sqrt(exact*(1-exact)/len(draws))
        registration = next(r for r in registry if r['kind'] == 'REGISTER' and r['forecast_identity'] == f['identity'])
        assert digest(registration['payload']['forecast']) == digest(f)
        assert utc(parent['cutoff_utc']) <= utc(f['information_cutoff_utc']) <= utc(registration['written_at_utc']) < utc(f['event']['start_time_utc'])
        assert parent['assimilation']['completed_week'] == 2 and len(parent['assimilation']['consumed_game_ids']) == 32
        reports.append({'scenario': folder.parent.parent.name, 'identity': f['identity'], 'seed': seed, 'simulations': len(draws),
            'parent_cutoff_utc': parent['cutoff_utc'], 'margin_cutoff_utc': f['information_cutoff_utc'], 'registered_at_utc': registration['written_at_utc'],
            'model_file_sha256': config['model_sha256'], 'forecast_sha256': base.file_sha(path), 'raw_draw_sha256': f['simulation']['raw_sha256'],
            'state_id': parent['assimilation']['state_id'], 'input_flags': ['CHICAGO_STARTER_CONDITIONAL', 'FINAL_INACTIVES_PENDING', 'WEATHER_FITTED_IMPUTATION', 'NON_QB_AVAILABILITY_NOT_NUMERICALLY_CONSUMED', 'WEEK2_STATE_LATEST_VALID_FOR_WEEK3'],
            'rows': board['spread_rows'], 'independent_distribution_and_inverse_cdf_replay': 'PASS',
            'market_comparison_display_enabled': True, 'market_input': False, 'action_authority': False})
    assert len(reports) == 2
    result = {'schema': 'nfl.qb_margin_calibration_verification.v1', 'verified_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'preregistration_commit': model['preregistration_commit'], 'model_id': cal.MODEL_ID,
        'history_rows': len(q), 'independently_replayed_calibration_games': len(recomputed), 'calibration_alpha': model['calibration']['alpha'],
        'screen_passed': evaluation['retrospective_screen_passed'], 'screen_metrics': evaluation['metrics'],
        'paired_crps_95_ci': evaluation['paired_crps_season_bootstrap_95_ci'], 'current_runs': reports, 'grading': status(a.grading_store),
        'prospective_predictive_validation': 'PENDING', 'canonical_promotion': False, 'action_authority': False}
    with a.output.open('x') as f: json.dump(result, f, indent=2, allow_nan=False); f.write('\n')
    print(json.dumps({'verified_runs': len(reports), 'calibration_replay_games': len(recomputed), 'screen_passed': result['screen_passed'], 'grading': result['grading']}, indent=2))


if __name__ == '__main__': main()
