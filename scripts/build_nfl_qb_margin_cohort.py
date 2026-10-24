#!/usr/bin/env python3
"""Qualify retained QB-parent OOF margins for retrospective distribution research.

This replays every annual QB fit against authentic saved features and outputs.
Schedule times are retained provider values. Fit, forecast, and result-availability
times are explicitly reconstructed bounds, never original publication receipts.
No performance scores, fitted margin law, or new prospective forecasts are made.
"""
from __future__ import annotations
import argparse
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from models.nfl.contextual.model import load_artifact, fit, predict_frame
from models.nfl.contextual.recovered_inference import digest
from models.nfl.contextual.features import canonical

PARENT = 'nfl.integrated_context.qb.v1.research'
INFORMATION_SET = 'RECONSTRUCTED_QB_OOF_PRIOR_SEASON_FITS'
TOLERANCE = 1e-10


def require(ok, code):
    if not ok:
        raise ValueError(code)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def dump(path, obj):
    with Path(path).open('x') as f:
        json.dump(obj, f, indent=2, sort_keys=True, allow_nan=False)
        f.write('\n')


def safe(value):
    return None if pd.isna(value) else float(value)


def build(source, schedule, schedule_receipt, parent_model, output):
    source, schedule, schedule_receipt, parent_model, output = map(Path, (source, schedule, schedule_receipt, parent_model, output))
    require(not output.exists(), 'OUTPUT_EXISTS')
    manifest = load(source / 'manifest.json')
    verified = []
    for name, record in manifest.items():
        if not isinstance(record, dict) or 'sha256' not in record:
            continue
        path = (source / name).resolve()
        require(path.is_relative_to(source.resolve()), 'SOURCE_PATH_ESCAPE')
        require(path.is_file() and path.stat().st_size == record['bytes'] and sha(path) == record['sha256'], 'SOURCE_MANIFEST_MISMATCH:' + name)
        verified.append({'path': name, 'sha256': record['sha256'], 'bytes': record['bytes']})
    artifact = load_artifact(parent_model)
    source_hashes = {str(p.resolve()): sha(p) for p in [source / 'evaluation/features.csv', source / 'evaluation/oof_predictions.csv', source / 'evaluation/data_audit.json', schedule, schedule_receipt, parent_model]}
    schedule_hash = source_hashes[str(schedule.resolve())]
    oof_hash = source_hashes[str((source / 'evaluation/oof_predictions.csv').resolve())]
    saved = artifact['arms']['qb']
    require(saved['model_id'] == PARENT, 'EXACT_QB_PARENT_REQUIRED')
    audit = load(source / 'evaluation/data_audit.json')
    require(digest(audit) == artifact['source_audit_sha256'], 'PARENT_SOURCE_AUDIT_MISMATCH')
    require(audit['feature_sha256'] == sha(source / 'evaluation/features.csv'), 'FEATURE_SOURCE_MISMATCH')
    require(audit['design_sha256'] == digest(artifact['design']), 'PARENT_DESIGN_MISMATCH')
    receipt = load(schedule_receipt)
    found = [r for r in receipt['sources'] if r.get('kind') == 'schedule' and r.get('sha256') == sha(schedule)]
    require(len(found) == 1 and found[0]['status'] == 'CAPTURED', 'SCHEDULE_RECEIPT_MISMATCH')
    features = pd.read_csv(source / 'evaluation/features.csv')
    full_oof = pd.read_csv(source / 'evaluation/oof_predictions.csv')
    oof = full_oof[full_oof.arm == 'qb'].copy()
    require(len(oof) > 0 and not oof.game_id.duplicated().any(), 'QB_OOF_ROWS_REQUIRED')
    require(not features.game_id.duplicated().any(), 'FEATURE_ID_DUPLICATE')
    schedule_frame = pd.read_csv(schedule)
    # Keep only the source fields needed for scope, timing and final labels.
    # Captured market columns never leave this acquisition boundary.
    schedule_frame = schedule_frame[['game_id', 'season', 'week', 'game_type', 'gameday', 'gametime', 'home_team', 'away_team', 'home_score', 'away_score']]
    require(not schedule_frame.game_id.duplicated().any(), 'SCHEDULE_ID_DUPLICATE')
    schedule_index = schedule_frame.set_index('game_id')
    feature_index = features.set_index('game_id')
    require(set(oof.game_id).issubset(schedule_index.index), 'SCHEDULE_EVENT_MISSING')
    require(set(oof.game_id).issubset(feature_index.index), 'FEATURE_EVENT_MISSING')
    matching = schedule_index.loc[oof.game_id]
    require((matching.game_type == 'REG').all(), 'REGULAR_SEASON_ONLY')
    require(not matching[['gameday', 'gametime', 'home_score', 'away_score']].isna().any().any(), 'SCHEDULE_FIELD_MISSING')
    require(np.array_equal(feature_index.loc[oof.game_id].gameday.to_numpy(), matching.gameday.to_numpy()), 'SCHEDULE_DATE_CONFLICT')
    require(np.array_equal(oof.home_margin.to_numpy(), (matching.home_score - matching.away_score).to_numpy()), 'FINAL_MARGIN_CONFLICT')
    require(np.array_equal(oof.total_points.to_numpy(), (matching.home_score + matching.away_score).to_numpy()), 'FINAL_TOTAL_CONFLICT')
    require(np.isfinite(oof[['home_margin', 'pred_margin']].to_numpy()).all(), 'NONFINITE_MARGIN')
    require(np.equal(oof.home_margin, np.round(oof.home_margin)).all(), 'INTEGER_MARGIN_REQUIRED')

    folds, parameters = [], {}
    for season in sorted(oof.season.unique()):
        train = features[features.season < season]
        test = features[(features.season == season) & features.home_margin.notna()]
        require(not train.empty and int(train.season.max()) < int(season), 'CHRONOLOGICAL_FOLD_REQUIRED')
        params = fit(train, 'qb', artifact['design'])
        predicted = predict_frame(params, test)
        expected = oof[oof.season == season].set_index('game_id')
        require(set(test.game_id) == set(expected.index), 'FOLD_POPULATION_MISMATCH')
        expected = expected.loc[test.game_id]
        errors = {k: float(np.max(np.abs(predicted[k].to_numpy() - expected[v].to_numpy()))) for k, v in [('home_win', 'p_home'), ('home_margin', 'pred_margin'), ('total_points', 'pred_total')]}
        require(max(errors.values()) <= TOLERANCE, 'OOF_REPLAY_MISMATCH')
        fold = {'held_out_season': int(season), 'training_seasons': params['training_seasons'], 'training_rows': params['training_rows'], 'prediction_rows': len(test), 'train_gameday_max': str(train.gameday.max()), 'test_gameday_min': str(test.gameday.min()), 'test_gameday_max': str(test.gameday.max()), 'fitted_parent_sha256': digest(params), 'max_abs_prediction_error': errors, 'replay_passed': True}
        folds.append(fold)
        parameters[int(season)] = params
    final = fit(features, 'qb', artifact['design'])
    require(final['feature_names'] == saved['feature_names'] and final['training_rows'] == saved['training_rows'] and final['training_seasons'] == saved['training_seasons'], 'PARENT_TRAINING_SCOPE_MISMATCH')
    final_errors = {target: {k: float(np.max(np.abs(np.asarray(v) - np.asarray(saved['heads'][target][k])))) for k, v in head.items()} for target, head in final['heads'].items()}
    require(max(e for h in final_errors.values() for e in h.values()) <= TOLERANCE, 'PARENT_COEFFICIENT_MISMATCH')
    rows = []
    for r in oof.itertuples(index=False):
        season = int(r.season)
        scheduled = schedule_index.loc[r.game_id]
        feature = feature_index.loc[r.game_id]
        require(int(scheduled.season) == season and int(scheduled.week) == int(r.week), 'SEASON_WEEK_CONFLICT')
        require(canonical(scheduled.home_team) == canonical(feature.home_team) and canonical(scheduled.away_team) == canonical(feature.away_team), 'TEAM_ORIENTATION_CONFLICT')
        start = dt.datetime.fromisoformat(str(scheduled.gameday) + 'T' + str(scheduled.gametime)).replace(tzinfo=ZoneInfo('America/New_York')).astimezone(dt.timezone.utc)
        parent_cutoff = dt.datetime(season, 7, 1, tzinfo=dt.timezone.utc)
        cutoff = start - dt.timedelta(hours=1)
        available = start + dt.timedelta(hours=24)
        require(parent_cutoff <= cutoff < start <= available, 'RECONSTRUCTED_CHRONOLOGY_INVALID')
        vals = {k: safe(feature[k]) for k in saved['feature_names']}
        forecast_evidence = {'event_id': r.game_id, 'parent_model_id': PARENT, 'held_out_season': season, 'fold_sha256': digest(parameters[season]), 'features': vals, 'predicted_mean': float(r.pred_margin), 'oof_source_sha256': oof_hash, 'feature_source_sha256': audit['feature_sha256']}
        result_evidence = {'event_id': r.game_id, 'home': str(scheduled.home_team), 'away': str(scheduled.away_team), 'home_score': int(scheduled.home_score), 'away_score': int(scheduled.away_score), 'source_sha256': schedule_hash}
        rows.append({'event_id': r.game_id, 'league': 'nfl', 'product': 'margin', 'settlement': 'FULL_GAME_OT_REGULAR', 'parent_model_id': PARENT, 'information_set': INFORMATION_SET, 'market_input': False, 'prediction_kind': 'CHRONOLOGICAL_OUT_OF_TIME', 'label_in_sample': False, 'oof': True, 'season': season, 'week': int(r.week), 'home_team': str(scheduled.home_team), 'away_team': str(scheduled.away_team), 'gameday': str(scheduled.gameday), 'parent_fit_cutoff': parent_cutoff.isoformat(), 'forecast_cutoff': cutoff.isoformat(), 'start_time_utc': start.isoformat(), 'result_available_at': available.isoformat(), 'forecast_sha256': digest(forecast_evidence), 'result_source_sha256': sha(schedule), 'result_row_sha256': digest(result_evidence), 'predicted_mean': float(r.pred_margin), 'observed': int(r.home_margin), 'scale_features': {'absolute_parent_margin': abs(float(r.pred_margin))}, 'block_id': f'{season}-W{int(r.week):02d}', 'parent_fold_sha256': digest(parameters[season]), 'parent_training_seasons': parameters[season]['training_seasons'], 'source_capture_kind': 'RETAINED_RESEARCH_ARCHIVE_AND_LATER_PROVIDER_FINALS', 'timestamp_basis': 'RECONSTRUCTED_PARENT_JULY1_FORECAST_START_MINUS_1H_RESULT_START_PLUS_24H; SCHEDULE_START_FROM_PROVIDER_EASTERN', 'historical_availability_proven': False, 'source_retrieved_at_utc': found[0]['retrieved_at_utc'], 'original_forecast_created_at_utc': None, 'original_result_observed_at_utc': None, 'forecast_evidence': forecast_evidence, 'result_evidence': result_evidence})
    rows.sort(key=lambda r: (r['forecast_cutoff'], r['event_id']))
    require(len(rows) == len({r['event_id'] for r in rows}), 'EVENT_DUPLICATE')
    residual = [r for r in rows if 2019 <= r['season'] <= 2022]
    evaluation = [r for r in rows if 2023 <= r['season'] <= 2025]
    require(len(residual) + len(evaluation) == len(rows), 'UNDECLARED_SEASON')
    require(set(r['event_id'] for r in residual).isdisjoint(r['event_id'] for r in evaluation), 'SPLIT_OVERLAP')
    summary = {'parent_model_id': PARENT, 'parent_packed_sha256': sha(parent_model), 'parent_decoded_sha256': digest(artifact), 'parent_qb_head_sha256': digest(saved), 'parent_source_audit_sha256': digest(audit), 'information_set': INFORMATION_SET, 'settlement': 'FULL_GAME_OT_REGULAR', 'feature_rows': len(features), 'oof_rows': len(rows), 'fit_rows_2019_2022': len(residual), 'evaluation_rows_2023_2025': len(evaluation), 'deployment_rows_2019_2025': len(rows), 'ties_retained': sum(r['observed'] == 0 for r in rows), 'counts_by_season': {str(y): sum(r['season'] == y for r in rows) for y in sorted(set(r['season'] for r in rows))}, 'same_parent_verified': True, 'source_manifest_verified_files': len(verified), 'historical_availability_proven': False, 'original_historical_forecasts_registered': False, 'outcome_metrics_computed': False, 'new_2026_outcomes_used': False, 'market_input': False, 'action_authority': False}
    cohort = {'schema': 'nfl.qb_margin_qualified_cohort.v1', 'created_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'summary': summary, 'folds': folds, 'final_coefficient_max_abs_errors': final_errors, 'source_files': {'features': {'path': str(source / 'evaluation/features.csv'), 'sha256': audit['feature_sha256']}, 'oof': {'path': str(source / 'evaluation/oof_predictions.csv'), 'sha256': sha(source / 'evaluation/oof_predictions.csv')}, 'schedule': {'path': str(schedule), 'sha256': sha(schedule), 'receipt': found[0]}, 'archive_manifest': {'path': str(source / 'manifest.json'), 'sha256': sha(source / 'manifest.json')}}, 'source_manifest_checks': verified, 'rows': rows, 'residual': residual, 'evaluation': evaluation, 'deployment': rows, 'qualification_limitations': ['Historical source publication and starter identities were not archived as of each kickoff.', 'Fit, forecast and result-availability timestamps are explicit reconstructed study bounds; they are not observed publication times.', 'Same model family is established by exact annual fitting rules and coefficient replay; each historical fold uses prior seasons only.', 'Final frozen QB heads exclude ties from fitting under the original parent contract; all six held-out final ties remain in this margin cohort.', 'This study reuses historical research rows and is not an untouched or prospective validation cohort.'], 'code_sha256': {str(p.relative_to(ROOT)): sha(p) for p in [Path(__file__), ROOT / 'scripts/build_nfl_context.py', ROOT / 'models/nfl/contextual/model.py', ROOT / 'models/nfl/contextual/features.py', ROOT / 'models/nfl/contextual/recovered_inference.py']}}
    cohort['source_sha256'] = source_hashes
    cohort['team_alias_policy'] = 'Existing NFL contextual canonical() mapping; source team labels and game IDs retained.'
    output.mkdir(parents=True)
    (output / 'folds').mkdir()
    for year, params in parameters.items():
        dump(output / 'folds' / f'qb-{year}.json', params)
    dump(output / 'qb_margin_cohort.json', cohort)
    dump(output / 'qualification.json', {k: v for k, v in cohort.items() if k not in {'rows', 'residual', 'evaluation', 'deployment'}})
    dump(output / 'manifest.json', {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob('*')) if p.is_file()})
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'schedule', 'schedule-receipt', 'parent-model', 'output'):
        ap.add_argument('--' + name, type=Path, required=True)
    a = ap.parse_args()
    print(json.dumps(build(a.source, a.schedule, a.schedule_receipt, a.parent_model, a.output), indent=2))


if __name__ == '__main__':
    main()
