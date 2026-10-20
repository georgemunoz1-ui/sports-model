"""Source-bound rejection probes for the QB margin cohort consumer."""
import copy
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import tempfile
import unittest
from models.nfl.contextual.qb_margin_cohort import INFO, PARENT, sha, validate_cohort
from models.nfl.contextual.recovered_inference import digest


def fixture(tmp_path):
    """Small independent linear law makes forged coefficients detectable."""
    ev = tmp_path / 'evaluation'
    ev.mkdir()
    folds_dir = tmp_path / 'folds'
    folds_dir.mkdir()
    head = {'impute': [0.], 'center': [0.], 'scale': [1.], 'coefficient': [1.], 'intercept': 0.}
    features = [{'game_id': 'a', 'season': 2019, 'week': 1, 'gameday': '2019-09-08', 'home_team': 'KC', 'away_team': 'BAL', 'x': 2.}, {'game_id': 'b', 'season': 2023, 'week': 1, 'gameday': '2023-09-10', 'home_team': 'SF', 'away_team': 'NYG', 'x': -3.}]
    outcomes = [7, 0]
    pd.DataFrame(features).to_csv(ev / 'features.csv', index=False)
    oof = [{**{k: r[k] for k in ('game_id', 'season', 'week')}, 'arm': 'qb', 'pred_margin': r['x'], 'home_margin': y} for r, y in zip(features, outcomes)]
    pd.DataFrame(oof).to_csv(ev / 'oof_predictions.csv', index=False)
    schedule = [{**{k: r[k] for k in ('game_id', 'season', 'week', 'gameday', 'home_team', 'away_team')}, 'game_type': 'REG', 'gametime': '13:00', 'home_score': 20+y, 'away_score': 20} for r, y in zip(features, outcomes)]
    pd.DataFrame(schedule).to_csv(tmp_path / 'schedule.csv', index=False)
    audit = {'feature_sha256': sha(ev / 'features.csv')}
    (ev / 'data_audit.json').write_text(json.dumps(audit))
    artifact = {'source_audit_sha256': digest(audit), 'arms': {'qb': {'model_id': PARENT, 'feature_names': ['x'], 'heads': {'home_margin': head}}}}
    (tmp_path / 'model_packed.json').write_text(json.dumps(artifact))
    (tmp_path / 'builder.py').write_text('# retained builder bytes\n')
    rows, folds = [], []
    for f, s, y in zip(features, schedule, outcomes):
        year = f['season']
        params = {'model_id': PARENT, 'feature_names': ['x'], 'training_seasons': [year-1], 'heads': {'home_margin': head}}
        (folds_dir / f'qb-{year}.json').write_text(json.dumps(params))
        folds.append({'held_out_season': year, 'fitted_parent_sha256': digest(params), 'training_seasons': [year-1], 'prediction_rows': 1, 'replay_passed': True})
        start = dt.datetime.fromisoformat(s['gameday']+'T13:00').replace(tzinfo=ZoneInfo('America/New_York')).astimezone(dt.timezone.utc)
        fe = {'event_id': f['game_id'], 'parent_model_id': PARENT, 'fold_sha256': digest(params), 'features': {'x': f['x']}, 'predicted_mean': f['x'], 'oof_source_sha256': sha(ev / 'oof_predictions.csv'), 'feature_source_sha256': audit['feature_sha256']}
        re = {'event_id': f['game_id'], 'home': s['home_team'], 'away': s['away_team'], 'home_score': s['home_score'], 'away_score': s['away_score'], 'source_sha256': sha(tmp_path / 'schedule.csv')}
        rows.append({'event_id': f['game_id'], 'league': 'nfl', 'product': 'margin', 'settlement': 'FULL_GAME_OT_REGULAR', 'parent_model_id': PARENT, 'information_set': INFO, 'prediction_kind': 'CHRONOLOGICAL_OUT_OF_TIME', 'label_in_sample': False, 'oof': True, 'market_input': False, 'historical_availability_proven': False, 'season': year, 'week': 1, 'home_team': f['home_team'], 'away_team': f['away_team'], 'gameday': f['gameday'], 'predicted_mean': f['x'], 'observed': y, 'forecast_cutoff': (start-dt.timedelta(hours=1)).isoformat(), 'start_time_utc': start.isoformat(), 'result_available_at': (start+dt.timedelta(hours=24)).isoformat(), 'parent_fit_cutoff': dt.datetime(year, 7, 1, tzinfo=dt.timezone.utc).isoformat(), 'parent_fold_sha256': digest(params), 'parent_training_seasons': [year-1], 'forecast_evidence': fe, 'forecast_sha256': digest(fe), 'result_evidence': re, 'result_row_sha256': digest(re), 'result_source_sha256': re['source_sha256'], 'scale_features': {'absolute_parent_margin': abs(f['x'])}})
    paths = [ev/'features.csv', ev/'oof_predictions.csv', ev/'data_audit.json', tmp_path/'schedule.csv', tmp_path/'model_packed.json']
    cohort = {'schema': 'nfl.qb_margin_qualified_cohort.v1', 'summary': {'parent_model_id': PARENT, 'information_set': INFO, 'historical_availability_proven': False, 'market_input': False, 'action_authority': False, 'parent_decoded_sha256': digest(artifact), 'parent_qb_head_sha256': digest(artifact['arms']['qb']), 'parent_source_audit_sha256': digest(audit), 'oof_rows': 2, 'fit_rows_2019_2022': 1, 'evaluation_rows_2023_2025': 1, 'deployment_rows_2019_2025': 2, 'ties_retained': 1, 'counts_by_season': {'2019': 1, '2023': 1}}, 'source_sha256': {str(p): sha(p) for p in paths}, 'code_sha256': {'builder.py': sha(tmp_path/'builder.py')}, 'source_files': {'schedule': {'path': str(tmp_path/'schedule.csv'), 'sha256': sha(tmp_path/'schedule.csv')}}, 'folds': folds, 'rows': rows, 'residual': rows[:1], 'evaluation': rows[1:], 'deployment': rows}
    return cohort, tmp_path/'cohort.json'


def check(c, path):
    return validate_cohort(c, path, repository_root=path.parent)


class QBMarginCohortTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.c, self.p = fixture(self.tmp_path)

    def test_valid_source_bound_cohort_retains_tie(self):
        self.assertEqual(check(self.c, self.p)['rows'], 2)
        self.assertEqual(self.c['rows'][1]['observed'], 0)

    def test_invalid_cohort_evidence_rejected(self):
        mutations = [
            (lambda c: c['rows'][0].update(parent_model_id='nfl.integrated_context.combined.v1.research'), 'ROW_SCOPE'),
            (lambda c: c['rows'][0].update(predicted_mean=float('nan')), 'NONFINITE'),
            (lambda c: c['rows'].append(copy.deepcopy(c['rows'][0])), 'EVENT_DUPLICATE'),
            (lambda c: c['rows'][0].update(forecast_cutoff=c['rows'][0]['start_time_utc']), 'TIMESTAMP_BASIS'),
            (lambda c: c['rows'][0].update(label_in_sample=True), 'ROW_PROVENANCE'),
            (lambda c: c['rows'][0].update(settlement='FULL_GAME_OT_POSTSEASON'), 'ROW_SCOPE'),
            (lambda c: c['rows'][0].update(season='2019'), 'TYPED_CHRONOLOGY'),
            (lambda c: c['summary'].update(ties_retained=0), 'COUNT_BINDING'),
            (lambda c: c['evaluation'].clear(), 'SPLIT_BINDING'),
        ]
        for mutation, code in mutations:
            with self.subTest(code=code):
                c = copy.deepcopy(self.c)
                mutation(c)
                with self.assertRaisesRegex(ValueError, code):
                    check(c, self.p)

    def test_resealed_changed_prediction_rejected_against_raw_oof(self):
        r = self.c['rows'][0]
        r['predicted_mean'] += 1
        r['forecast_evidence']['predicted_mean'] = r['predicted_mean']
        r['forecast_sha256'] = digest(r['forecast_evidence'])
        with self.assertRaisesRegex(ValueError, 'SOURCE_VALUE_MISMATCH'):
            check(self.c, self.p)

    def test_resealed_changed_observation_rejected_against_raw_final(self):
        r = self.c['rows'][0]
        r['observed'] += 1
        r['result_evidence']['home_score'] += 1
        r['result_row_sha256'] = digest(r['result_evidence'])
        with self.assertRaisesRegex(ValueError, 'SOURCE_VALUE_MISMATCH'):
            check(self.c, self.p)

    def test_changed_raw_source_rejected(self):
        (self.tmp_path/'evaluation/oof_predictions.csv').write_text('modified\n')
        with self.assertRaisesRegex(ValueError, 'SOURCE_HASH'):
            check(self.c, self.p)

    def test_different_fit_code_rejected(self):
        (self.tmp_path/'builder.py').write_text('# altered fit rule\n')
        with self.assertRaisesRegex(ValueError, 'CODE_HASH'):
            check(self.c, self.p)

    def test_resealed_fold_coefficient_requires_numerical_replay(self):
        fold_path = self.tmp_path/'folds/qb-2019.json'
        params = json.loads(fold_path.read_text())
        params['heads']['home_margin']['coefficient'] = [2.]
        fold_path.write_text(json.dumps(params))
        changed = digest(params)
        self.c['folds'][0]['fitted_parent_sha256'] = changed
        r = self.c['rows'][0]
        r['parent_fold_sha256'] = changed
        r['forecast_evidence']['fold_sha256'] = changed
        r['forecast_sha256'] = digest(r['forecast_evidence'])
        with self.assertRaisesRegex(ValueError, 'FOLD_PREDICTION_MISMATCH'):
            check(self.c, self.p)


if __name__ == '__main__':
    unittest.main()
