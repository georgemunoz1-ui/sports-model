"""Validate qualified QB OOF rows against retained source bytes before fitting."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
from .features import canonical
from .model import load_artifact, predict_frame
from .recovered_inference import digest

PARENT = 'nfl.integrated_context.qb.v1.research'
INFO = 'RECONSTRUCTED_QB_OOF_PRIOR_SEASON_FITS'


def require(ok, code):
    if not ok:
        raise ValueError(code)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def _safe(value):
    return None if pd.isna(value) else float(value)


def validate_cohort(cohort, cohort_path=None, *, repository_root=None):
    """Recheck row identity and raw-source binding; no predictive evaluation.

    The evidence remains retrospective. Strong internal binding is not proof of
    original historical source publication or forecast registration.
    """
    try:
        return _validate(cohort, Path(cohort_path) if cohort_path else None,
                         Path(repository_root) if repository_root else Path(__file__).resolve().parents[3])
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError, OSError) as exc:
        raise ValueError('QB_COHORT_STRUCTURE_OR_SOURCE_INVALID') from exc


def _validate(c, path, repo):
    require(c['schema'] == 'nfl.qb_margin_qualified_cohort.v1', 'QB_COHORT_SCHEMA')
    require(path is not None, 'QB_COHORT_PATH_REQUIRED')
    require(c['summary']['parent_model_id'] == PARENT and c['summary']['information_set'] == INFO, 'QB_COHORT_PARENT')
    require(c['summary']['historical_availability_proven'] is False and c['summary']['market_input'] is False and c['summary']['action_authority'] is False, 'QB_COHORT_AUTHORITY')
    require(c['source_sha256'], 'QB_COHORT_SOURCES_REQUIRED')
    for name, expected in c['source_sha256'].items():
        require(sha(name) == expected, 'QB_COHORT_SOURCE_HASH')
    for name, expected in c['code_sha256'].items():
        target = (repo / name).resolve()
        require(target.is_relative_to(repo.resolve()) and sha(target) == expected, 'QB_COHORT_CODE_HASH')
    def one_suffix(suffix):
        found = [name for name in c['source_sha256'] if name.endswith(suffix)]
        require(len(found) == 1, 'QB_COHORT_SOURCE_SCOPE')
        return Path(found[0])
    artifact = load_artifact(one_suffix('/model_packed.json'))
    audit = load(one_suffix('/evaluation/data_audit.json'))
    require(digest(artifact) == c['summary']['parent_decoded_sha256'] and digest(artifact['arms']['qb']) == c['summary']['parent_qb_head_sha256'], 'QB_COHORT_PARENT_ARTIFACT')
    require(digest(audit) == artifact['source_audit_sha256'] == c['summary']['parent_source_audit_sha256'], 'QB_COHORT_PARENT_AUDIT')
    oof_hash = sha(one_suffix('/evaluation/oof_predictions.csv'))
    raw_oof = pd.read_csv(one_suffix('/evaluation/oof_predictions.csv'))
    raw_qb = raw_oof[raw_oof.arm == 'qb']
    require(not raw_qb.game_id.duplicated().any(), 'QB_COHORT_SOURCE_DUPLICATE')
    raw_qb = raw_qb.set_index('game_id')
    raw_features = pd.read_csv(one_suffix('/evaluation/features.csv')).set_index('game_id')
    require(not raw_features.index.duplicated().any(), 'QB_COHORT_SOURCE_DUPLICATE')
    schedule_info = c['source_files']['schedule']
    require(schedule_info['sha256'] == sha(schedule_info['path']), 'QB_COHORT_SOURCE_HASH')
    raw_schedule = pd.read_csv(schedule_info['path']).set_index('game_id')
    require(not raw_schedule.index.duplicated().any(), 'QB_COHORT_SOURCE_DUPLICATE')
    rows = c['rows']
    require(rows and len({r['event_id'] for r in rows}) == len(rows), 'QB_COHORT_EVENT_DUPLICATE')
    require({r['event_id'] for r in rows} == set(raw_qb.index), 'QB_COHORT_POPULATION')
    require(rows == sorted(rows, key=lambda r: (r['forecast_cutoff'], r['event_id'])), 'QB_COHORT_ORDER')
    folds = {f['held_out_season']: f for f in c['folds']}
    require(len(folds) == len(c['folds']), 'QB_COHORT_FOLD_DUPLICATE')
    for year, f in folds.items():
        params = load(path.parent / 'folds' / f'qb-{year}.json')
        require(digest(params) == f['fitted_parent_sha256'] and params['model_id'] == PARENT and params['training_seasons'] == f['training_seasons'], 'QB_COHORT_FOLD_HASH')
        require(f['training_seasons'] and max(f['training_seasons']) < year and f['replay_passed'] is True, 'QB_COHORT_FOLD_CHRONOLOGY')
        require(params['feature_names'] == artifact['arms']['qb']['feature_names'], 'QB_COHORT_FOLD_FEATURES')
        expected = raw_qb[raw_qb.season == year]
        prediction = predict_frame(params, raw_features.loc[expected.index])['home_margin'].to_numpy()
        require(np.isfinite(prediction).all() and np.allclose(prediction, expected.pred_margin.to_numpy(), rtol=0, atol=1e-10), 'QB_COHORT_FOLD_PREDICTION_MISMATCH')
        require(f['prediction_rows'] == len(expected), 'QB_COHORT_FOLD_COUNT')
    for r in rows:
        require(r['league'] == 'nfl' and r['product'] == 'margin' and r['settlement'] == 'FULL_GAME_OT_REGULAR' and r['parent_model_id'] == PARENT and r['information_set'] == INFO, 'QB_COHORT_ROW_SCOPE')
        require(r['prediction_kind'] == 'CHRONOLOGICAL_OUT_OF_TIME' and r['label_in_sample'] is False and r['oof'] is True and r['market_input'] is False and r['historical_availability_proven'] is False, 'QB_COHORT_ROW_PROVENANCE')
        require(type(r['season']) is int and type(r['week']) is int, 'QB_COHORT_TYPED_CHRONOLOGY')
        require(type(r['predicted_mean']) in (int, float) and np.isfinite(r['predicted_mean']) and type(r['observed']) is int, 'QB_COHORT_NONFINITE_OR_NONINTEGER')
        q, f, s = raw_qb.loc[r['event_id']], raw_features.loc[r['event_id']], raw_schedule.loc[r['event_id']]
        require(s.game_type == 'REG', 'QB_COHORT_REGULAR_SEASON_ONLY')
        require(int(q.season) == int(s.season) == r['season'] and int(q.week) == int(s.week) == r['week'], 'QB_COHORT_DATE_SCOPE')
        require(s.gameday == f.gameday == r['gameday'], 'QB_COHORT_DATE_SCOPE')
        require(canonical(s.home_team) == canonical(f.home_team) == canonical(r['home_team']) and canonical(s.away_team) == canonical(f.away_team) == canonical(r['away_team']), 'QB_COHORT_ORIENTATION')
        require(float(q.pred_margin) == r['predicted_mean'] and float(q.home_margin) == r['observed'] == int(s.home_score - s.away_score), 'QB_COHORT_SOURCE_VALUE_MISMATCH')
        start = dt.datetime.fromisoformat(str(s.gameday) + 'T' + str(s.gametime)).replace(tzinfo=ZoneInfo('America/New_York')).astimezone(dt.timezone.utc)
        expected_times = {'parent_fit_cutoff': dt.datetime(r['season'], 7, 1, tzinfo=dt.timezone.utc), 'forecast_cutoff': start - dt.timedelta(hours=1), 'start_time_utc': start, 'result_available_at': start + dt.timedelta(hours=24)}
        require(all(dt.datetime.fromisoformat(r[k].replace('Z', '+00:00')) == v for k, v in expected_times.items()), 'QB_COHORT_TIMESTAMP_BASIS')
        require(r['parent_fold_sha256'] == folds[r['season']]['fitted_parent_sha256'] and r['parent_training_seasons'] == folds[r['season']]['training_seasons'], 'QB_COHORT_FOLD_BINDING')
        fe, re = r['forecast_evidence'], r['result_evidence']
        require(digest(fe) == r['forecast_sha256'] and digest(re) == r['result_row_sha256'], 'QB_COHORT_EVIDENCE_HASH')
        expected_features = {k: _safe(f[k]) for k in artifact['arms']['qb']['feature_names']}
        require(fe['features'] == expected_features and fe['predicted_mean'] == r['predicted_mean'] and fe['event_id'] == r['event_id'] and fe['parent_model_id'] == PARENT and fe['fold_sha256'] == r['parent_fold_sha256'], 'QB_COHORT_FORECAST_BINDING')
        require(fe['oof_source_sha256'] == oof_hash and fe['feature_source_sha256'] == audit['feature_sha256'], 'QB_COHORT_FORECAST_SOURCE_BINDING')
        require(re['event_id'] == r['event_id'] and re['home_score'] == int(s.home_score) and re['away_score'] == int(s.away_score) and re['home'] == str(s.home_team) and re['away'] == str(s.away_team) and re['source_sha256'] == r['result_source_sha256'] == schedule_info['sha256'], 'QB_COHORT_RESULT_BINDING')
        require(r['scale_features'] == {'absolute_parent_margin': abs(r['predicted_mean'])}, 'QB_COHORT_SCALE_FEATURE')
    require(c['residual'] == [r for r in rows if 2019 <= r['season'] <= 2022] and c['evaluation'] == [r for r in rows if 2023 <= r['season'] <= 2025] and c['deployment'] == rows, 'QB_COHORT_SPLIT_BINDING')
    require(c['summary']['oof_rows'] == len(rows) and c['summary']['fit_rows_2019_2022'] == len(c['residual']) and c['summary']['evaluation_rows_2023_2025'] == len(c['evaluation']), 'QB_COHORT_COUNT_BINDING')
    require(c['summary']['deployment_rows_2019_2025'] == len(rows) and c['summary']['ties_retained'] == sum(r['observed'] == 0 for r in rows), 'QB_COHORT_COUNT_BINDING')
    require(c['summary']['counts_by_season'] == {str(y): sum(r['season'] == y for r in rows) for y in sorted(folds)}, 'QB_COHORT_COUNT_BINDING')
    return {'status': 'PASS', 'rows': len(rows), 'raw_source_binding': True, 'fold_binding': True, 'historical_availability_proven': False}
