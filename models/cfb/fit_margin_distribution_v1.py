#!/usr/bin/env python3
"""Fit an isolated shadow candidate with disjoint train/calibration/test windows.

Legacy feature tables without source-backed availability timestamps are rejected.
This command never rewrites an existing model or validation artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ALIASES = {
    'target': ['home_margin_final', 'home_margin', 'margin', 'score_margin', 'margin_home'],
    'elo_diff': ['elo_diff_with_home_advantage', 'elo_diff_pre', 'elo_diff'],
    'neutral': ['neutral_site', 'neutral', 'neutral_site_indicator'],
    'conference': ['conference_game', 'is_conference_game'],
    'week': ['week', 'season_week'],
}
TIMESTAMPS = ('kick', 'feature_available_at_utc', 'label_available_at_utc')
SOURCE_REFS = ('kick_source_ref', 'feature_source_ref', 'label_source_ref')
PROTOCOL = 'cfb_margin_train_calibration_test_v1'


def pick(cols, key, required=False):
    for name in ALIASES[key]:
        if name in cols:
            return name
    if required:
        raise ValueError(f'MISSING_COLUMN:{key}')
    return None


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return 'sha256:' + h.hexdigest()


def utc(value, name):
    # utc=True alone silently assigns UTC to naive dates; never do that here.
    if value is None or pd.isna(value) or isinstance(value, (int, float)):
        raise ValueError(f'MISSING_OR_INVALID_TIMESTAMP:{name}')
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'INVALID_TIMESTAMP:{name}') from exc
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError(f'TIMEZONE_REQUIRED:{name}')
    return stamp.tz_convert('UTC')


def window(start, end):
    # Public window dates are inclusive UTC calendar dates.
    lo = pd.Timestamp(date.fromisoformat(start), tz='UTC')
    hi = pd.Timestamp(date.fromisoformat(end), tz='UTC') + pd.Timedelta(days=1)
    if lo >= hi:
        raise ValueError('INVALID_DATE_WINDOW')
    return lo, hi


def verify_provenance(data_path, provenance_path):
    """Bind the input and referenced receipts to retained bytes, not URL claims."""
    root = Path(provenance_path).resolve().parent
    manifest = json.loads(Path(provenance_path).read_text())
    if manifest.get('schema') != 'cfb_margin_pit_provenance_v1':
        raise ValueError('INVALID_PROVENANCE_SCHEMA')
    if manifest.get('dataset_hash') != sha256(data_path):
        raise ValueError('PROVENANCE_DATASET_HASH_MISMATCH')
    sources = {}
    for entry in manifest.get('sources', []):
        identity = entry['id']
        path = (root / entry['path']).resolve()
        if not isinstance(identity, str) or not identity.strip() or identity in sources:
            raise ValueError('INVALID_SOURCE_ID')
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('SOURCE_RECEIPT_UNAVAILABLE')
        if sha256(path) != entry.get('sha256'):
            raise ValueError('SOURCE_RECEIPT_HASH_MISMATCH')
        sources[identity] = entry['sha256']
    if not sources:
        raise ValueError('SOURCE_RECEIPTS_REQUIRED')
    return sources


def prepare_splits(df, *, as_of, windows, source_ids):
    cutoff = utc(as_of, 'as_of')
    if len(windows) != 3 or any(windows[i][1] > windows[i + 1][0] for i in range(2)):
        raise ValueError('TRAIN_CALIBRATION_TEST_WINDOWS_MUST_BE_ORDERED_AND_DISJOINT')
    required = {'game_id', 'season', 'home_division', 'away_division', *TIMESTAMPS, *SOURCE_REFS}
    missing = required - set(df.columns)
    if missing:
        raise ValueError('MISSING_PIT_COLUMNS:' + ','.join(sorted(missing)))
    w = df.copy().reset_index(drop=True)
    if w.game_id.isna().any() or w.game_id.astype(str).str.strip().eq('').any():
        raise ValueError('MISSING_EVENT_ID')
    w['game_id'] = w.game_id.astype(str)
    # One pregame row per event. Multiple snapshots must be resolved upstream.
    if w.game_id.duplicated().any():
        raise ValueError('DUPLICATE_EVENT_ID')
    for name in TIMESTAMPS:
        w[name] = pd.to_datetime([utc(v, name) for v in w[name]], utc=True)
    for name in SOURCE_REFS:
        if not w[name].isin(source_ids).all():
            raise ValueError('UNBOUND_SOURCE_REFERENCE:' + name)
    if (w.feature_available_at_utc >= w.kick).any():
        raise ValueError('FEATURE_NOT_PREGAME')
    if (w.label_available_at_utc <= w.kick).any():
        raise ValueError('LABEL_NOT_POSTGAME')
    cols = set(w.columns)
    for dest, key in [('y', 'target'), ('elo_diff', 'elo_diff'),
                      ('neutral', 'neutral'), ('conference', 'conference'), ('week', 'week')]:
        name = pick(cols, key, required=True)
        w[dest] = pd.to_numeric(w[name], errors='raise')
    w['season'] = pd.to_numeric(w.season, errors='raise')
    numeric = ['y', 'elo_diff', 'neutral', 'conference', 'week', 'season']
    if not np.isfinite(w[numeric].to_numpy(dtype=float)).all():
        raise ValueError('NONFINITE_FIT_INPUT')
    if not w.neutral.isin([0, 1]).all() or not w.conference.isin([0, 1]).all():
        raise ValueError('INVALID_BOOLEAN_FEATURE')
    if (w.week % 1 != 0).any() or (w.season % 1 != 0).any() or (w.week < 0).any():
        raise ValueError('INVALID_SEASON_WEEK')
    w['week'] = w.week.astype(int)
    w['season'] = w.season.astype(int)
    w = w[(w.home_division == 'fbs') & (w.away_division == 'fbs')].copy()
    w['split'] = 'excluded'
    for name, (lo, hi) in zip(('train', 'calibration', 'test'), windows):
        w.loc[(w.kick >= lo) & (w.kick < hi), 'split'] = name
    # Honor the repository's season-week grouping, including boundary straddles.
    if (w.groupby(['season', 'week'])['split'].nunique() > 1).any():
        raise ValueError('SEASON_WEEK_CROSSES_SPLIT_BOUNDARY')
    selected = w[w.split != 'excluded'].copy()
    if (selected.kick >= cutoff).any() or (selected.label_available_at_utc > cutoff).any():
        raise ValueError('ROW_UNAVAILABLE_AS_OF_CUTOFF')
    if len(selected) < 1000:
        raise ValueError(f'INSUFFICIENT_TRAINING_ROWS:{len(selected)}')
    selected = selected.sort_values(['kick', 'game_id'], kind='mergesort')
    splits = tuple(selected[selected.split == name].copy() for name in ('train', 'calibration', 'test'))
    if any(len(frame) < 100 for frame in splits):
        raise ValueError('INSUFFICIENT_SPLIT_ROWS:minimum=100')
    tr, ca, te = splits
    if tr.label_available_at_utc.max() >= ca.kick.min():
        raise ValueError('TRAIN_LABEL_UNAVAILABLE_BEFORE_CALIBRATION')
    if ca.label_available_at_utc.max() >= te.kick.min():
        raise ValueError('CALIBRATION_LABEL_UNAVAILABLE_BEFORE_TEST')
    return splits


def design(frame):
    return np.column_stack([np.ones(len(frame)), frame.elo_diff, frame.neutral, frame.conference])


def fit_parameters(train, calibration):
    # No test argument: neither coefficients nor residual scales can read test y.
    beta, *_ = np.linalg.lstsq(design(train), train.y.to_numpy(), rcond=None)
    residual = calibration.y.to_numpy() - design(calibration) @ beta
    sigma = float(np.sqrt(np.mean(residual ** 2)))
    if not np.isfinite(sigma) or sigma <= 0:
        raise ValueError('INVALID_RESIDUAL_SCALE')
    if abs(float(beta[1])) < 1e-9:
        raise ValueError('PLACEHOLDER_OR_ZERO_ELO_COEFFICIENT')
    weekly = {}
    for week, group in calibration.assign(residual=residual).groupby('week'):
        if len(group) >= 200:
            scale = float(np.sqrt(np.mean(group.residual.to_numpy() ** 2)))
            if not np.isfinite(scale) or scale <= 0:
                raise ValueError('INVALID_WEEKLY_RESIDUAL_SCALE')
            weekly[str(int(week))] = scale
    return beta, sigma, weekly


def evaluate(test, beta, sigma, weekly):
    mu = design(test) @ beta
    residual = test.y.to_numpy() - mu
    # Identical scale-selection rule to monte_carlo_v1.run.
    scales = np.array([weekly.get(str(int(week)), sigma) for week in test.week])
    probability = .5 * (1 + np.vectorize(math.erf)(mu / (scales * np.sqrt(2))))
    return {
        'method': PROTOCOL, 'n_games': len(test),
        'margin_mae': float(np.mean(np.abs(residual))),
        'margin_rmse': float(np.sqrt(np.mean(residual ** 2))),
        'ml_brier_induced_by_margin_sim': float(np.mean((probability - (test.y.to_numpy() > 0)) ** 2)),
        'probability_semantics': 'analytic_normal_cdf_with_runtime_week_scale',
        'test_used_for_fitting': False,
    }


def fit_candidate(df, *, as_of, windows, source_ids):
    splits = prepare_splits(df, as_of=as_of, windows=windows, source_ids=source_ids)
    beta, sigma, weekly = fit_parameters(*splits[:2])
    cohorts = {}
    for name, frame in zip(('train', 'calibration', 'test'), splits):
        ids = frame.game_id.tolist()
        cohorts[name] = {'n_games': len(frame), 'event_ids': ids,
                         'event_ids_sha256': hashlib.sha256(json.dumps(ids).encode()).hexdigest(),
                         'kick_min_utc': frame.kick.min().isoformat(),
                         'kick_max_utc': frame.kick.max().isoformat(),
                         'label_available_max_utc': frame.label_available_at_utc.max().isoformat()}
    return {
        'parameters': dict(zip(('intercept', 'elo_diff_coefficient', 'neutral_site_coefficient',
                                'conference_game_coefficient'), map(float, beta)),
                           home_advantage_embedded_in_elo_diff=True),
        'residual_model': {'distribution': 'normal_margin_v1', 'global_sigma': sigma,
                           'segment_sigma_by_week': weekly, 'fitted_on': 'calibration_only'},
        'validation': evaluate(splits[2], beta, sigma, weekly),
        'evaluation_design': {'protocol': PROTOCOL, 'grouping': 'season_week',
                              'windows_utc_half_open': [[a.isoformat(), b.isoformat()] for a, b in windows],
                              'cohorts': cohorts},
    }


def write_outputs(state, output, validation_output):
    paths = [Path(output), Path(validation_output)]
    if paths[0].resolve() == paths[1].resolve() or any(p.exists() for p in paths):
        raise ValueError('OUTPUT_MUST_BE_NEW_AND_DISTINCT')
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also prevents overwriting under a concurrent writer.
    for path, content in zip(paths, (state, state['validation'])):
        with path.open('x') as stream:
            stream.write(json.dumps(content, indent=2, allow_nan=False) + '\n')


def main(argv=None):
    ap = argparse.ArgumentParser()
    for name in ('train-data', 'provenance', 'output', 'validation-output', 'as-of',
                 'train-start', 'train-end', 'calibration-start', 'calibration-end',
                 'validation-start', 'validation-end'):
        ap.add_argument('--' + name, required=True)
    args = ap.parse_args(argv)
    windows = [window(getattr(args, name + '_start'), getattr(args, name + '_end'))
               for name in ('train', 'calibration', 'validation')]
    p = Path(args.train_data)
    sources = verify_provenance(p, args.provenance)
    state = fit_candidate(pd.read_parquet(p), as_of=args.as_of, windows=windows, source_ids=sources)
    cohorts = state['evaluation_design']['cohorts']
    state.update({
        'artifact_type': 'cfb_margin_model_state_v1', 'model_id': 'cfb.margin_distribution.v1',
        'version': '1.1.0', 'trained_at_utc': datetime.now(timezone.utc).isoformat(),
        'as_of_utc': utc(args.as_of, 'as_of').isoformat(),
        'code_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'training_data': {'dataset_id': p.name, 'dataset_hash': sha256(p),
                          'provenance_hash': sha256(args.provenance),
                          'n_games': sum(x['n_games'] for x in cohorts.values()),
                          'n_train': cohorts['train']['n_games'],
                          'n_calibration': cohorts['calibration']['n_games'],
                          'n_validation': cohorts['test']['n_games'],
                          'population': 'FBS_vs_FBS_only', 'target': 'home_final_margin',
                          'point_in_time_semantics': 'caller_asserted_availability_with_byte_bound_source_refs',
                          'source_authentication_status': 'UNESTABLISHED_REQUIRES_MIGRATION_AUDIT'},
        'feature_schema': {'version': 'cfb_margin_features_v1',
                            'features': ['elo_diff_with_home_advantage', 'neutral_site', 'conference_game']},
        'status': 'SHADOW_CANDIDATE', 'promotion_eligible': False,
    })
    write_outputs(state, args.output, args.validation_output)
    print(json.dumps({'status': 'PASS', **state['validation']}))


if __name__ == '__main__':
    try:
        main()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
