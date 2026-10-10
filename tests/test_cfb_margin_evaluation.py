import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from models.cfb import fit_margin_distribution_v1 as fit


WINDOWS = [fit.window('2001-01-01', '2001-12-31'),
           fit.window('2002-01-01', '2002-12-31'),
           fit.window('2003-01-01', '2003-12-31')]


def fixture():
    rows = []
    rng = np.random.default_rng(132)
    # 400 train, 400 calibration and 400 test; weekly segment meets n >= 200.
    for year in (2001, 2002, 2003):
        for index in range(400):
            kick = pd.Timestamp(f'{year}-09-01T12:00:00Z') + pd.Timedelta(hours=index)
            elo = rng.normal(0, 200)
            rows.append(dict(game_id=f'{year}:{index}', season=year, week=1,
                             kick=kick, feature_available_at_utc=kick-pd.Timedelta(days=1),
                             label_available_at_utc=kick+pd.Timedelta(hours=4),
                             kick_source_ref='schedule', feature_source_ref='features',
                             label_source_ref='results', home_division='fbs', away_division='fbs',
                             elo_diff_with_home_advantage=elo, neutral_site=index % 2,
                             conference_game=(index // 2) % 2,
                             home_margin=.035*elo + 2 + rng.normal(0, 14)))
    return pd.DataFrame(rows)


class EvaluationTest(unittest.TestCase):
    def setUp(self):
        self.df = fixture()
        self.kw = dict(as_of='2004-01-01T00:00:00Z', windows=WINDOWS,
                       source_ids={'schedule', 'features', 'results'})

    def test_test_outcomes_never_influence_any_fitted_parameter(self):
        a = fit.fit_candidate(self.df, **self.kw)
        changed = self.df.copy()
        changed.loc[changed.season == 2003, 'home_margin'] += 500
        b = fit.fit_candidate(changed, **self.kw)
        self.assertEqual(a['parameters'], b['parameters'])
        self.assertEqual(a['residual_model'], b['residual_model'])
        self.assertNotEqual(a['validation'], b['validation'])
        self.assertIn('1', a['residual_model']['segment_sigma_by_week'])

    def test_calibration_outcomes_change_only_scales(self):
        a = fit.fit_candidate(self.df, **self.kw)
        changed = self.df.copy()
        changed.loc[changed.season == 2002, 'home_margin'] += 20
        b = fit.fit_candidate(changed, **self.kw)
        self.assertEqual(a['parameters'], b['parameters'])
        self.assertNotEqual(a['residual_model'], b['residual_model'])

    def test_shuffle_is_exactly_stable(self):
        a = fit.fit_candidate(self.df, **self.kw)
        b = fit.fit_candidate(self.df.sample(frac=1, random_state=53), **self.kw)
        self.assertEqual(a, b)

    def test_unique_event_cohorts_and_group_disjointness(self):
        candidate = fit.fit_candidate(self.df, **self.kw)
        ids = [set(x['event_ids']) for x in candidate['evaluation_design']['cohorts'].values()]
        self.assertEqual(len(set.union(*ids)), 1200)
        self.assertTrue(all(not ids[i] & ids[j] for i in range(3) for j in range(i)))
        duplicate = pd.concat([self.df, self.df.iloc[:1]])
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_EVENT_ID'):
            fit.fit_candidate(duplicate, **self.kw)

    def test_same_season_week_cannot_straddle_window(self):
        bad = self.df.copy()
        bad.loc[bad.season == 2002, 'season'] = 2001
        with self.assertRaisesRegex(ValueError, 'SEASON_WEEK_CROSSES'):
            fit.fit_candidate(bad, **self.kw)

    def test_partial_season_week_exclusion_rejected(self):
        kw = dict(self.kw, windows=[fit.window('2001-09-02', '2001-12-31'), *WINDOWS[1:]])
        with self.assertRaisesRegex(ValueError, 'SEASON_WEEK_CROSSES'):
            fit.fit_candidate(self.df, **kw)

    def test_missing_original_timestamps_rejected(self):
        for name in fit.TIMESTAMPS:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'MISSING_PIT_COLUMNS'):
                fit.fit_candidate(self.df.drop(columns=name), **self.kw)

    def test_naive_and_missing_timestamps_rejected(self):
        for value in ('2001-09-01T12:00:00', None, 1000000000):
            bad = self.df.copy()
            bad['kick'] = bad.kick.astype(object)
            bad.loc[0, 'kick'] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'TIMESTAMP|TIMEZONE'):
                fit.fit_candidate(bad, **self.kw)
        with self.assertRaisesRegex(ValueError, 'TIMEZONE_REQUIRED'):
            fit.fit_candidate(self.df, **dict(self.kw, as_of='2004-01-01'))

    def test_timezone_offsets_are_normalized(self):
        other = self.df.copy()
        for name in fit.TIMESTAMPS:
            other[name] = other[name].dt.tz_convert('America/New_York')
        self.assertEqual(fit.fit_candidate(self.df, **self.kw), fit.fit_candidate(other, **self.kw))

    def test_as_of_enforced_for_event_and_label(self):
        with self.assertRaisesRegex(ValueError, 'ROW_UNAVAILABLE_AS_OF'):
            fit.fit_candidate(self.df, **dict(self.kw, as_of='2003-09-01T00:00:00Z'))
        bad = self.df.copy()
        bad.loc[1199, 'label_available_at_utc'] = pd.Timestamp('2004-02-01T00:00:00Z')
        with self.assertRaisesRegex(ValueError, 'ROW_UNAVAILABLE_AS_OF'):
            fit.fit_candidate(bad, **self.kw)

    def test_temporal_label_and_feature_rules(self):
        for column, value, error in [
            ('feature_available_at_utc', self.df.loc[0, 'kick'], 'FEATURE_NOT_PREGAME'),
            ('label_available_at_utc', self.df.loc[0, 'kick'], 'LABEL_NOT_POSTGAME'),
            ('label_available_at_utc', pd.Timestamp('2002-10-01T00:00:00Z'), 'TRAIN_LABEL_UNAVAILABLE')]:
            bad = self.df.copy()
            bad.loc[0, column] = value
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                fit.fit_candidate(bad, **self.kw)
        bad = self.df.copy()
        bad.loc[400, 'label_available_at_utc'] = pd.Timestamp('2003-10-01T00:00:00Z')
        with self.assertRaisesRegex(ValueError, 'CALIBRATION_LABEL_UNAVAILABLE'):
            fit.fit_candidate(bad, **self.kw)

    def test_overlapping_or_reversed_windows_rejected(self):
        for windows in ([WINDOWS[0], WINDOWS[0], WINDOWS[2]], WINDOWS[::-1]):
            with self.assertRaisesRegex(ValueError, 'ORDERED_AND_DISJOINT'):
                fit.fit_candidate(self.df, **dict(self.kw, windows=windows))
        with self.assertRaisesRegex(ValueError, 'INVALID_DATE_WINDOW'):
            fit.window('2004-01-01', '2003-01-01')

    def test_unbound_provenance_rejected(self):
        bad = self.df.copy()
        bad.loc[0, 'feature_source_ref'] = 'unretained'
        with self.assertRaisesRegex(ValueError, 'UNBOUND_SOURCE_REFERENCE'):
            fit.fit_candidate(bad, **self.kw)

    def test_fbs_population_is_enforced(self):
        baseline = fit.fit_candidate(self.df, **self.kw)
        extra = self.df.iloc[:1].copy()
        extra['game_id'] = 'fcs-game'
        extra['away_division'] = 'fcs'
        extra['home_margin'] = 10000
        self.assertEqual(baseline, fit.fit_candidate(pd.concat([self.df, extra]), **self.kw))

    def test_nonfinite_inputs_rejected_not_silently_dropped(self):
        bad = self.df.copy()
        bad.loc[0, 'home_margin'] = np.inf
        with self.assertRaisesRegex(ValueError, 'NONFINITE_FIT_INPUT'):
            fit.fit_candidate(bad, **self.kw)

    def test_brier_uses_runtime_weekly_scale_with_global_fallback(self):
        te = fit.prepare_splits(self.df, **self.kw)[2]
        beta = np.array([5, .01, 0, 0])
        result = fit.evaluate(te, beta, 1, {'1': 50})
        mu = fit.design(te) @ beta
        p = np.array([.5*(1+math.erf(x/(50*math.sqrt(2)))) for x in mu])
        self.assertEqual(result['ml_brier_induced_by_margin_sim'], float(np.mean((p-(te.y.to_numpy()>0))**2)))
        self.assertNotEqual(result, fit.evaluate(te, beta, 1, {}))
        self.assertEqual(fit.evaluate(te, beta, 50, {}), result)

    def test_provenance_binds_dataset_and_receipt_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root/'features.parquet'; data.write_bytes(b'fixture only')
            source = root/'source.json'; source.write_text('{}')
            manifest = {'schema':'cfb_margin_pit_provenance_v1', 'dataset_hash':fit.sha256(data),
                        'sources':[{'id':'s','path':'source.json','sha256':fit.sha256(source)}]}
            path = root/'provenance.json'; path.write_text(json.dumps(manifest))
            self.assertEqual(set(fit.verify_provenance(data, path)), {'s'})
            source.write_text('{"tamper":true}')
            with self.assertRaisesRegex(ValueError, 'SOURCE_RECEIPT_HASH_MISMATCH'):
                fit.verify_provenance(data, path)
            data.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'PROVENANCE_DATASET_HASH_MISMATCH'):
                fit.verify_provenance(data, path)

    def test_old_files_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            old = Path(directory)/'old.json'; old.write_bytes(b'frozen candidate')
            new = Path(directory)/'new.json'
            for first, second in ((old, new), (new, old), (new, new)):
                with self.assertRaisesRegex(ValueError, 'OUTPUT_MUST_BE_NEW'):
                    fit.write_outputs({'validation':{}}, first, second)
                self.assertEqual(old.read_bytes(), b'frozen candidate')
                self.assertFalse(new.exists())

    def test_cli_passes_every_window_to_fitter(self):
        args = ['--train-data','fixture.parquet','--provenance','receipt.json',
                '--output','new.json','--validation-output','validation.json',
                '--as-of','2004-01-01T00:00:00Z']
        for phase, year in [('train',2001),('calibration',2002),('validation',2003)]:
            args += [f'--{phase}-start',f'{year}-01-01',f'--{phase}-end',f'{year}-12-31']
        with patch.object(fit, 'verify_provenance', return_value=self.kw['source_ids']), \
             patch.object(fit.pd, 'read_parquet', return_value=self.df), \
             patch.object(fit, 'sha256', return_value='sha256:fixture'), \
             patch.object(fit.subprocess, 'check_output', return_value='commit'), \
             patch.object(fit, 'write_outputs') as write:
            fit.main(args)
            output = write.call_args.args[0]
        self.assertEqual(output['evaluation_design']['windows_utc_half_open'],
                         [[a.isoformat(),b.isoformat()] for a,b in WINDOWS])
        self.assertEqual(output['training_data']['n_calibration'], 400)
        self.assertEqual(output['training_data']['source_authentication_status'],
                         'UNESTABLISHED_REQUIRES_MIGRATION_AUDIT')
        self.assertFalse(output['promotion_eligible'])

    def test_both_workflows_pass_all_bounds_and_provenance(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('cfb-fit-margin-model.yml','cfb-fit-forecast.yml'):
            text = (root/'.github/workflows'/name).read_text()
            for phase in ('train','calibration','validation'):
                for bound in ('start','end'):
                    self.assertIn(f'--{phase}-{bound} "${phase.upper()}_{bound.upper()}"', text)
                    self.assertIn(f'${{{{ inputs.{phase}_{bound} }}}}', text)
            self.assertIn('--provenance data/cfb/model/cfb_margin_pit_features_v1.provenance.json', text)
            self.assertNotIn('VALIDATION_AFTER_TRAIN_END', text)
            self.assertIn('cfb_margin_pit_features_v1.parquet', text)


if __name__ == '__main__':
    unittest.main()
