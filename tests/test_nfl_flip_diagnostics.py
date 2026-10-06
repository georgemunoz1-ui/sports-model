"""Synthetic cases assert diagnostics semantics, never refit or alter forecasts."""
import copy
import datetime as dt
import json
import math
from pathlib import Path
import tempfile
import unittest

from models.nfl.contextual.flip_diagnostics import (
    QB_FEATURES, _digest, append_flip_diagnostic, build_flip_diagnostics,
)


def fixture(base=.521, qb=.4678):
    return {'schema': 'nfl.integrated_context_forecast.v1',
            'identity': 'frozen-forecast-identity', 'model_artifact_sha256': 'artifact-sha',
            'model_id': 'qb-model', 'selected_arm': 'qb', 'mode': 'research_pregame', 'market_input': False,
            'event': {'event_id': '2026_04_ATL_NO', 'home_team': 'NO', 'away_team': 'ATL',
                      'start_time_utc': '2026-10-06T00:15:00Z'},
            'cutoff_utc': '2026-10-05T15:00:00Z',
            'arms': {'base': {'model_id': 'base-model', 'prediction': {'home_win': base}},
                     'qb': {'model_id': 'qb-model', 'prediction': {'home_win': qb}}},
            'tags': ['SEA_STALE_STARTER', 'CHI_UNRESOLVED_STARTER'],
            'warnings': ['RESEARCH_ONLY', 'FINAL_INACTIVES_PENDING'],
            'prediction': {'home_win': qb}, 'winner_simulation': {'count': 100000, 'seed': 817}}


def with_traces(bundle):
    for name, extra in (('base', {}), ('qb', dict.fromkeys(QB_FEATURES, 0.))):
        p = bundle['arms'][name]['prediction']['home_win']
        logit = math.log(p / (1 - p))
        # QB terms deliberately offset each other; signed sum differs from
        # absolute share, which must exclude intercept and avoid cancellation.
        if name == 'qb':
            extra.update(qb_quality_diff=.3, qb_quality_sum=-.1)
        features = {'team_strength': .1 if name == 'base' else -.1, **extra}
        intercept = logit - sum(features.values())
        bundle['arms'][name]['contribution_trace'] = {'home_win': {
            'features': features, 'intercept': intercept, 'linear_value': logit, 'units': 'LOG_ODDS'}}
    return bundle


class FlipDiagnosticTests(unittest.TestCase):
    def test_atl_flip_below_gap_threshold(self):
        d = build_flip_diagnostics(fixture(), {'base': 'base-model', 'qb': 'qb-model'})
        self.assertEqual(d['status'], 'COMPARABLE')
        self.assertTrue(d['pick_flip'])
        self.assertEqual(d['base']['pick'], 'NO')
        self.assertEqual(d['qb']['pick'], 'ATL')
        self.assertAlmostEqual(d['delta_pp'], -5.32)
        self.assertIn('PICK_FLIP', d['flags'])
        self.assertNotIn('LARGE_PROBABILITY_GAP', d['flags'])
        self.assertEqual(d['source']['arm_model_ids']['qb'], 'qb-model')

    def test_large_same_side_is_gap_not_flip(self):
        d = build_flip_diagnostics(fixture(.6, .8))
        self.assertFalse(d['pick_flip'])
        self.assertIn('LARGE_PROBABILITY_GAP', d['flags'])
        self.assertNotIn('PICK_FLIP', d['flags'])

    def test_unrounded_crossing_and_exact_neutral(self):
        d = build_flip_diagnostics(fixture(.500000001, .499999999))
        self.assertTrue(d['pick_flip'])
        self.assertEqual(round(d['base']['home_win_probability'], 2), .5)
        for b, q in ((.5, .6), (.4, .5), (.5, .5)):
            with self.subTest(base=b, qb=q):
                d = build_flip_diagnostics(fixture(b, q))
                self.assertFalse(d['pick_flip'])
                self.assertIn('NEUTRAL_PROBABILITY', d['flags'])
                self.assertIsNone(d['base']['pick'] if b == .5 else d['qb']['pick'])

    def test_home_away_swap_symmetry(self):
        original = fixture(.6, .4)
        swapped = fixture(.4, .6)
        swapped['event']['home_team'], swapped['event']['away_team'] = 'ATL', 'NO'
        left, right = map(build_flip_diagnostics, (original, swapped))
        self.assertEqual(left['base']['pick'], right['base']['pick'])
        self.assertEqual(left['qb']['pick'], right['qb']['pick'])
        self.assertEqual(left['pick_flip'], right['pick_flip'])
        self.assertAlmostEqual(left['delta_pp'], -right['delta_pp'])
        self.assertAlmostEqual(left['delta_logit'], -right['delta_logit'])

    def test_missing_and_invalid_arm_are_fail_visible(self):
        broken = fixture()
        del broken['arms']['qb']
        d = build_flip_diagnostics(broken)
        self.assertEqual(d['status'], 'NOT_COMPARABLE')
        self.assertIsNone(d['pick_flip'])
        self.assertIn('MISSING_ARM:qb', d['flags'])
        for p in (None, True, False, '0.6', -0.01, 1.01, float('nan'), float('inf'), -float('inf')):
            with self.subTest(p=p):
                d = build_flip_diagnostics(fixture(.6, p))
                self.assertIsNone(d['pick_flip'])
                self.assertIsNone(d['delta_pp'])
                self.assertIn('INVALID_PROBABILITY:qb', d['flags'])
                json.dumps(d, allow_nan=False)
        broken = fixture()
        broken['arms']['qb']['prediction'] = None
        self.assertIsNone(build_flip_diagnostics(broken)['pick_flip'])

    def test_contradictory_arm_identity_fails_visible(self):
        changes = ({'event_id': 'OTHER'}, {'home_team': 'ATL'}, {'away_team': 'NO'},
                   {'cutoff_utc': '2026-10-05T16:00:00Z'}, {'identity': 'other'},
                   {'model_artifact_sha256': 'other'}, {'event': {'home_team': 'ATL'}},
                   {'model_id': 'wrong-model'})
        for change in changes:
            with self.subTest(change=change):
                bundle = fixture()
                bundle['arms']['qb'].update(change)
                d = build_flip_diagnostics(bundle, {'base': 'base-model', 'qb': 'qb-model'})
                self.assertEqual(d['status'], 'NOT_COMPARABLE')
                self.assertIsNone(d['pick_flip'])
                self.assertTrue(any(v.startswith('ARM_IDENTITY_MISMATCH:') for v in d['flags']))

    def test_missing_source_identity_and_identical_teams(self):
        for key in ('identity', 'model_artifact_sha256', 'cutoff_utc'):
            b = fixture()
            del b[key]
            self.assertEqual(build_flip_diagnostics(b)['status'], 'NOT_COMPARABLE')
        b = fixture()
        b['event']['home_team'] = b['event']['away_team']
        self.assertIn('INVALID_TEAM_ORIENTATION', build_flip_diagnostics(b)['flags'])

    def test_missing_model_ids_fail_visible_but_external_binding_works(self):
        for arm in ('base', 'qb'):
            b = fixture()
            del b['arms'][arm]['model_id']
            d = build_flip_diagnostics(b)
            self.assertEqual(d['status'], 'NOT_COMPARABLE')
            self.assertIsNone(d['pick_flip'])
            self.assertIn('MISSING_ARM_MODEL_ID:' + arm, d['flags'])
            recovered = build_flip_diagnostics(b, {'base': 'base-model', 'qb': 'qb-model'})
            self.assertEqual(recovered['status'], 'COMPARABLE')
        for missing in (None, '', ' ', False):
            b = fixture()
            b['model_id'] = missing
            d = build_flip_diagnostics(b)
            self.assertEqual(d['status'], 'NOT_COMPARABLE')
            self.assertIn('MISSING_SOURCE_IDENTITY:selected_model_id', d['flags'])
        b = fixture()
        self.assertIn('MISSING_ARM_MODEL_ID:base', build_flip_diagnostics(b, {'base': ''})['flags'])

    def test_live_market_aware_and_unknown_scope_fail_visible(self):
        for mode, market in (('live', False), ('enhanced_pregame', True),
                             ('research_pregame', True), ('research_pregame', None),
                             ('research_pregame', 0), (None, False)):
            with self.subTest(mode=mode, market=market):
                b = fixture()
                b['mode'], b['market_input'] = mode, market
                d = build_flip_diagnostics(b)
                self.assertEqual(d['status'], 'NOT_COMPARABLE')
                self.assertIsNone(d['pick_flip'])
                self.assertIsNone(d['delta_pp'])
                self.assertEqual(d['source']['mode'], mode)
                self.assertEqual(d['source']['market_input'], market)
                if mode != 'research_pregame':
                    self.assertIn('UNSUPPORTED_SOURCE_MODE', d['flags'])
                if market is not False:
                    self.assertIn('SOURCE_NOT_VERIFIED_MARKET_BLIND', d['flags'])

    def test_endpoint_probabilities_remain_finite_json(self):
        for b, q in ((0., 1.), (1., 0.), (0., 0.), (1., .8)):
            with self.subTest(base=b, qb=q):
                d = build_flip_diagnostics(fixture(b, q))
                self.assertEqual(d['status'], 'COMPARABLE')
                self.assertIsNone(d['delta_logit'])
                self.assertIn('LOGIT_UNAVAILABLE_AT_ENDPOINT', d['flags'])
                json.dumps(d, allow_nan=False)

    def test_no_mutation_tags_warnings_and_self_exclusion(self):
        bundle = fixture()
        before = copy.deepcopy(bundle)
        d = build_flip_diagnostics(bundle)
        self.assertEqual(bundle, before)
        self.assertEqual(d['source_tags'], bundle['tags'])
        self.assertEqual(d['source_warnings'], bundle['warnings'])
        self.assertEqual(len(d['reporter_sha256']), 64)
        self.assertEqual(len(d['source_projection_sha256']), 64)
        bundle['flip_diagnostics'] = d
        self.assertEqual(build_flip_diagnostics(bundle), d)
        d['source_warnings'].append('not-in-source')
        self.assertEqual(bundle['warnings'], before['warnings'])

    def test_contribution_decomposition_and_absolute_share(self):
        d = build_flip_diagnostics(with_traces(fixture()))
        c = d['contributions']
        self.assertEqual(c['status'], 'COMPLETE')
        self.assertAlmostEqual(c['qb_group_signed'], .2)
        self.assertAlmostEqual(c['shared_feature_shift'], -.2)
        self.assertAlmostEqual(c['qb_absolute_share'], .8)
        self.assertAlmostEqual(c['absolute_feature_sum'], .5)
        self.assertAlmostEqual(c['trace_logit_difference'], d['delta_logit'])
        self.assertAlmostEqual(c['qb_group_signed'] + c['shared_feature_shift'] + c['intercept_shift'], d['delta_logit'])
        self.assertTrue(c['denominator_excludes_intercept'])

    def test_incomplete_and_inconsistent_traces_not_invented(self):
        for change in ('missing', 'bad_units', 'bad_sum', 'bad_probability', 'extra_feature', 'nonfinite'):
            b = with_traces(fixture())
            q = b['arms']['qb']['contribution_trace']['home_win']
            if change == 'missing':
                del q['features']['qb_quality_diff']
            elif change == 'bad_units':
                q['units'] = 'POINTS'
            elif change == 'bad_sum':
                q['linear_value'] = 1.
            elif change == 'bad_probability':
                b['arms']['qb']['prediction']['home_win'] = .2
            elif change == 'extra_feature':
                q['features']['not_in_base'] = 0.
            else:
                q['features']['qb_quality_diff'] = float('nan')
            d = build_flip_diagnostics(b)
            self.assertIn('INCOMPLETE_CONTRIBUTION_TRACE', d['flags'])
            self.assertIsNone(d['contributions']['qb_group_signed'])

    def test_zero_contribution_denominator(self):
        b = with_traces(fixture(.5, .5))
        for arm in b['arms'].values():
            t = arm['contribution_trace']['home_win']
            t['features'] = dict.fromkeys(t['features'], 0.)
            t['intercept'] = t['linear_value'] = 0.
        c = build_flip_diagnostics(b)['contributions']
        self.assertEqual(c['status'], 'COMPLETE')
        self.assertIsNone(c['qb_absolute_share'])
        self.assertEqual(c['share_status'], 'ZERO_ABSOLUTE_FEATURE_SUM')

    def test_append_idempotence_and_true_writer_time_after_start(self):
        b = fixture()
        b['event']['start_time_utc'] = '2000-01-01T00:00:00Z'
        d = build_flip_diagnostics(b)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'diagnostics.jsonl'
            before = dt.datetime.now(dt.timezone.utc)
            first = append_flip_diagnostic(path, d)
            written = path.read_bytes()
            second = append_flip_diagnostic(path, d)
            after = dt.datetime.now(dt.timezone.utc)
            self.assertTrue(first['appended'])
            self.assertFalse(second['appended'])
            self.assertEqual(written, path.read_bytes())
            self.assertEqual(first['record'], second['record'])
            stamp = dt.datetime.fromisoformat(first['record']['created_at_utc'])
            self.assertLessEqual(before, stamp)
            self.assertLessEqual(stamp, after)
            self.assertFalse(first['record']['canonical_prospective_eligible'])
            b['identity'] = 'another-forecast'
            third = append_flip_diagnostic(path, build_flip_diagnostics(b))
            self.assertEqual(third['record']['previous_hash'], first['record']['record_hash'])

    def test_identity_conflict_rejected_without_mutation(self):
        left, right = build_flip_diagnostics(fixture()), build_flip_diagnostics(fixture(.521, .48))
        self.assertEqual(left['diagnostic_identity'], right['diagnostic_identity'])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'diagnostics.jsonl'
            append_flip_diagnostic(path, left)
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'IDENTITY_CONFLICT'):
                append_flip_diagnostic(path, right)
            self.assertEqual(before, path.read_bytes())

    def test_corrupt_chain_rejected_even_when_matching_record_earlier(self):
        d = build_flip_diagnostics(fixture())
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'diagnostics.jsonl'
            append_flip_diagnostic(path, d)
            with path.open('a') as f:
                f.write('{"previous_hash":"corrupted","record_hash":"bad"}\n')
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'CHAIN_INVALID'):
                append_flip_diagnostic(path, d)
            self.assertEqual(before, path.read_bytes())

    def test_truncated_stream_and_tampered_diagnostic_rejected(self):
        d = build_flip_diagnostics(fixture())
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'diagnostics.jsonl'
            append_flip_diagnostic(path, d)
            path.write_bytes(path.read_bytes().rstrip(b'\n'))
            before = path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'TRUNCATED'):
                append_flip_diagnostic(path, d)
            self.assertEqual(before, path.read_bytes())
            d['pick_flip'] = False
            with self.assertRaisesRegex(ValueError, 'CONTENT_HASH'):
                append_flip_diagnostic(path, d)
            self.assertEqual(before, path.read_bytes())

    def test_scope_and_identity_integrity_enforced(self):
        d = build_flip_diagnostics(fixture())
        with tempfile.TemporaryDirectory() as temp:
            for field in ('promotion_eligible', 'canonical_prospective_eligible', 'action_authority', 'market_input'):
                forged = copy.deepcopy(d)
                forged[field] = True
                forged['content_sha256'] = _digest({k: v for k, v in forged.items() if k != 'content_sha256'})
                with self.assertRaisesRegex(ValueError, 'SCOPE'):
                    append_flip_diagnostic(Path(temp) / 'scope.jsonl', forged)
            forged = copy.deepcopy(d)
            forged['diagnostic_identity'] = 'bad'
            forged['content_sha256'] = _digest({k: v for k, v in forged.items() if k != 'content_sha256'})
            with self.assertRaisesRegex(ValueError, 'IDENTITY_HASH'):
                append_flip_diagnostic(Path(temp) / 'id.jsonl', forged)

    def test_invalid_threshold_rejected(self):
        for threshold in (-1, True, float('nan'), float('inf'), '10'):
            with self.assertRaisesRegex(ValueError, 'INVALID_GAP_THRESHOLD'):
                build_flip_diagnostics(fixture(), gap_threshold_pp=threshold)


if __name__ == '__main__':
    unittest.main()
