#!/usr/bin/env python3
"""Execute the frozen retrospective study; never register historical forecasts.

Provider scores are authentic retained observations. Historical timestamps below
are explicit simulation assumptions, not claims of original pregame capture.
"""
import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from models.common import discrete_research as D, discrete_calibration as C
from models.current.linear import pack, predict as point_predict
from research.evaluate_discrete_products import evaluate
from scripts import prepare_initial_baselines as B

SETTLEMENT = {'cfb': 'FULL_GAME_OT', 'nba': 'FULL_GAME_OT',
              'nhl': 'FULL_GAME_OT_SO_PLUS_ONE', 'mls': 'REGULATION_90_STOPPAGE'}
CFB_FEATURES = ['elo_diff_with_home_advantage', 'home_ewma_points_for',
                'home_ewma_points_against', 'away_ewma_points_for',
                'away_ewma_points_against', 'home_ewma_margin', 'away_ewma_margin',
                'rest_days_diff', 'neutral_site', 'conference_game']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as f:
        json.dump(value, f, sort_keys=True, indent=2, allow_nan=False)
        f.write('\n')


def compressed(path, value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    with path.open('xb') as f:
        f.write(gzip.compress(raw, mtime=0))


def eligibility(game):
    start = D.stamp(game['start_time_utc'])
    return (start - dt.timedelta(hours=1)).isoformat(), (start + dt.timedelta(hours=48)).isoformat()


def ordered_splits(rows, split):
    groups = {name: [r for r in rows if r[0]['season'] == split[name + '_season']]
              for name in ('residual', 'calibration', 'evaluation')}
    parent = [r for r in rows if r[0]['season'] <= split['parent_train_max_season']]
    if any(not g for g in [parent, *groups.values()]):
        raise ValueError('EMPTY_TEMPORAL_SPLIT')
    all_ids = [r[0]['event_id'] for r in parent + sum(list(groups.values()), [])]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError('DUPLICATE_STUDY_GAME')
    seq = [parent, *groups.values()]
    for before, after in zip(seq, seq[1:]):
        if max(D.stamp(eligibility(r[0])[1]) for r in before) >= min(D.stamp(eligibility(r[0])[0]) for r in after):
            raise ValueError('TEMPORAL_SPLIT_OVERLAP')
    return parent, groups


def source_rows(league, history, cfb, design):
    split = design['splits'][league]
    if league == 'cfb':
        if sha(cfb) != design['source_pins']['cfb_features_sha256']:
            raise ValueError('CFB_SOURCE_DRIFT')
        frame = pd.read_parquet(cfb)
        frame = frame[(frame.home_division == 'fbs') & (frame.away_division == 'fbs')]
        rows = []
        for r in frame.to_dict('records'):
            game = {'event_id': 'CFB:' + str(r['game_id']), 'season': int(r['season']),
                    'week': int(r['week']), 'start_time_utc': pd.Timestamp(r['kick']).isoformat(),
                    'observed_margin': int(r['home_margin'])}
            rows.append((game, [r[k] for k in CFB_FEATURES]))
        parent, groups = ordered_splits(rows, split)
        X = np.asarray([x for _, x in parent]); y = np.asarray([r['observed_margin'] for r, _ in parent])
        fitted = {'margin': pack(make_pipeline(SimpleImputer(strategy='median'), StandardScaler(),
                                               Ridge(alpha=1)).fit(X, y), 'linear')}
        # The selected Week 2+ profile is the experiment population. Parent recipe
        # itself uses all FBS training weeks, exactly as prepare_cfb_current does.
        groups = {k: [r for r in v if r[0]['week'] >= 2] for k, v in groups.items()}
        provenance = {'feature_file_sha256': sha(cfb), 'features': CFB_FEATURES,
                      'parent_train_n': len(parent), 'source': 'repository CFB pinned feature replay',
                      'total': 'POINT_HEAD_UNAVAILABLE'}
    else:
        if sha(history / 'manifest.json') != design['source_pins']['history_manifest_sha256']:
            raise ValueError('HISTORY_SOURCE_DRIFT')
        B.manifest(history, 'manifest.json')
        games, receipts, copies = B.histories(history, league)
        training = [r for r in games if r['season'] <= split['parent_train_max_season']]
        prior = float(np.mean([r[s + '_score'] for r in training for s in ('home', 'away')]))
        rows, _, _ = B.causal_rows(games, prior, D.writer_clock())
        parent, groups = ordered_splits(rows, split)
        fitted = B.fit(parent, league)
        provenance = {'history_manifest_sha256': sha(history / 'manifest.json'),
                      'prior': prior, 'parent_train_n': len(parent), 'provider_copy_counts': copies,
                      'source_receipts': [{k: r[k] for k in ('url', 'raw_sha256', 'retrieved_at_utc')} for r in receipts]}
    return fitted, groups, provenance


def point(fitted, x, league, product):
    if league == 'mls':
        h, a = point_predict(fitted['home_goals'], x), point_predict(fitted['away_goals'], x)
        return h - a if product == 'margin' else h + a
    return point_predict(fitted[product], x)


def observation(game, product):
    if 'observed_margin' in game:
        return game['observed_margin']
    return game['home_score'] - game['away_score'] if product == 'margin' else game['home_score'] + game['away_score']


def train_rows(rows, fitted, parent_id, league, product, source_digest, parent_fit):
    result = []
    for game, x in rows:
        cutoff, available = eligibility(game)
        mean = point(fitted, x, league, product)
        result.append({'event_id': game['event_id'], 'league': league, 'product': product,
                       'settlement': SETTLEMENT[league], 'parent_model_id': parent_id,
                       'information_set': 'RECONSTRUCTED_PROVIDER_FINALS_FIXED_PARENT', 'market_input': False,
                       'prediction_kind': 'CHRONOLOGICAL_OUT_OF_TIME', 'parent_fit_cutoff': parent_fit,
                       'forecast_cutoff': cutoff, 'start_time_utc': game['start_time_utc'],
                       'result_available_at': available, 'predicted_mean': mean, 'observed': observation(game, product),
                       'forecast_sha256': D.digest({'game': game['event_id'], 'features': [None if not np.isfinite(v) else float(v) for v in x],
                                                  'parent': fitted, 'predicted_mean': mean}),
                       'result_source_sha256': source_digest,
                       'scale_features': {'absolute_parent_margin': abs(point(fitted, x, league, 'margin'))},
                       'historical_availability_proven': False,
                       'timestamp_basis': 'SIMULATED_START_MINUS_1H_AND_START_PLUS_48H_NOT_CAPTURE',
                       'source_capture_kind': 'RETROSPECTIVE_RECONSTRUCTION'})
    return result


def distributions(model, rows):
    return [{'distribution': D.predict(model, mean=r['predicted_mean'], event_id=r['event_id'],
                                      cutoff=r['forecast_cutoff'], parent_model_id=r['parent_model_id'],
                                      information_set=r['information_set'], parent_forecast_sha256=r['forecast_sha256'],
                                      scale_features=r['scale_features']),
             **{k: r[k] for k in ('start_time_utc', 'result_available_at', 'observed', 'result_source_sha256')},
             'block_id': D.stamp(r['start_time_utc']).strftime('%G-%V')}
            for r in rows]


def contracts(rows, product):
    result = []
    for r in rows:
        mean = r['distribution']['provenance']['mean_input']
        lines = [-7, -3.5, -3, 0, 3, 3.5, 7] if product == 'margin' else [math.floor(mean * 2) / 2]
        for line in lines:
            result.append({**r, 'contract': {'kind': 'HYPOTHETICAL', 'line': line,
                                             'side': 'HOME' if product == 'margin' else 'OVER'}})
    return result


def diagnostics(rows):
    scores = [D.score(r['distribution'], r['observed']) for r in rows]
    covered, widths = [], []
    for r in rows:
        x, p = D.validate(r['distribution']); cdf = np.cumsum(p)
        lo, hi = x[min(np.searchsorted(cdf, .05), len(x)-1)], x[min(np.searchsorted(cdf, .95), len(x)-1)]
        covered.append(lo <= r['observed'] <= hi); widths.append(hi - lo)
    return {'games': len(rows), 'crps': float(np.mean([r['crps'] for r in scores])),
            'zero_probability_outcomes': sum(r['log_loss'] is None for r in scores),
            'central_90_interval_coverage': float(np.mean(covered)),
            'central_90_interval_mean_width': float(np.mean(widths))}


def execute(design_path, history, cfb, output):
    design = json.loads(design_path.read_text())
    for p, h in design['code_pins'].items():
        if sha(ROOT / p) != h:
            raise ValueError('DESIGN_CODE_DRIFT:' + p)
    output.mkdir(parents=True, exist_ok=False)
    summary = {'schema': 'sports.distribution_study.results.v1', 'created_at_utc': D.writer_clock(),
               'design_sha256': sha(design_path), 'runner_sha256': sha(__file__), 'results': {},
               'unavailable': design['unavailable_source_adapters'], 'action_authority': False,
               'historical_availability_proven': False, 'market_evaluation': 'NOT_RUN_NO_TIMESTAMPED_QUOTES',
               'availability_effects': 'NOT_FITTED_NO_HISTORICAL_STATUS_AND_PARTICIPATION_PANEL',
               'prospective_validation': 'NOT_RUN_FUTURE_OUTCOMES_REQUIRED', 'default_promotion': False}
    for league in design['executed_source_adapters']:
        fitted, groups, provenance = source_rows(league, history, cfb, design)
        folder = output / league; folder.mkdir()
        parent_id = league + '.fixed_parent.' + D.digest(fitted)[:16] + '.research'
        write(folder / 'parent.json', {'model_id': parent_id, 'fitted': fitted, 'source': provenance,
                                     'created_at_utc': D.writer_clock(), 'current_default': False})
        parent_fit = min(eligibility(r[0])[0] for r in groups['residual'])
        residual_fit = min(eligibility(r[0])[0] for r in groups['calibration'])
        calibration_fit = min(eligibility(r[0])[0] for r in groups['evaluation'])
        result = {}
        for product in (['margin'] if league == 'cfb' else ['margin', 'total']):
            rows = {k: train_rows(v, fitted, parent_id, league, product, D.digest(provenance), parent_fit)
                    for k, v in groups.items()}
            compressed(folder / (product + '_cohort.json.gz'), rows)
            options = dict(league=league, product=product, settlement=SETTLEMENT[league], parent_model_id=parent_id,
                           fitted_at=residual_fit, information_set='RECONSTRUCTED_PROVIDER_FINALS_FIXED_PARENT')
            raw = D.fit_residuals(rows['residual'], **options)
            scaled = D.fit_residuals(rows['residual'], **options, method='conditional_scale',
                                     scale_features=['absolute_parent_margin'])
            write(folder / (product + '_empirical.json'), raw)
            write(folder / (product + '_conditional_scale.json'), scaled)
            # Fit calibration before test predictions/metrics. A missing supported
            # score aborts this arm; no observation is silently dropped.
            calibrator = None; calibration_status = None
            try:
                calibrator = C.fit(distributions(raw, rows['calibration']), fitted_at=calibration_fit)
                write(folder / (product + '_cdf.json'), calibrator)
                calibration_status = 'FITTED'
            except ValueError as exc:
                calibration_status = str(exc)
            baseline = distributions(raw, rows['evaluation'])
            candidate = distributions(scaled, rows['evaluation'])
            report = evaluate(contracts(baseline + candidate, product), baseline_id=raw['model_id'],
                              challenger_id=scaled['model_id'], bootstrap=2000, seed=7)
            write(folder / (product + '_scale_evaluation.json'), report)
            product_result = {'residual_n': len(rows['residual']), 'calibration_n': len(rows['calibration']),
                              'evaluation_n': len(rows['evaluation']), 'baseline': diagnostics(baseline),
                              'conditional_scale': diagnostics(candidate),
                              'scale_paired': report['paired_challenger_minus_baseline'],
                              'calibration_status': calibration_status}
            if calibrator:
                calibrated = [{**r, 'distribution': C.apply(r['distribution'], calibrator)} for r in baseline]
                creport = evaluate(contracts(baseline + calibrated, product), baseline_id=raw['model_id'],
                                   challenger_id=calibrator['model_id'], bootstrap=2000, seed=7)
                write(folder / (product + '_cdf_evaluation.json'), creport)
                product_result.update(calibrated=diagnostics(calibrated), cdf_paired=creport['paired_challenger_minus_baseline'])
            # One authentic held-out event per product: actual 100K draws with
            # exact byte replay. This verifies sampling, not predictive accuracy.
            draws, receipt = D.simulate(baseline[0]['distribution'], draws=100000)
            repeat, replay = D.simulate(baseline[0]['distribution'], draws=100000)
            if not np.array_equal(draws, repeat) or receipt != replay:
                raise ValueError('SIMULATION_REPLAY_FAILED')
            buffer = io.BytesIO(); np.save(buffer, draws, allow_pickle=False)
            (folder / (product + '_draws.npy.gz')).write_bytes(gzip.compress(buffer.getvalue(), mtime=0))
            write(folder / (product + '_simulation_receipt.json'), receipt)
            compressed(folder / (product + '_prediction_hashes.json.gz'),
                       {r['distribution']['model_id'] + ':' + r['distribution']['provenance']['event_id']:
                        r['distribution']['distribution_sha256'] for r in baseline + candidate})
            result[product] = product_result
        if league == 'cfb': result['total'] = {'status': 'POINT_HEAD_UNAVAILABLE_IN_SELECTED_PARENT'}
        summary['results'][league] = result
        write(folder / 'summary.json', result)
        print(json.dumps({'league': league, 'completed': list(result)}), flush=True)
    write(output / 'summary.json', summary)
    write(output / 'manifest.json', {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob('*')) if p.is_file()})
    return summary


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--design', type=Path, required=True)
    ap.add_argument('--history', type=Path, required=True)
    ap.add_argument('--cfb-features', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    execute(a.design, a.history, a.cfb_features, a.output)
