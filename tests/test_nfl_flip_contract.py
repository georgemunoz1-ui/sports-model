"""Fail-visible comparison and fitted-reference regression cases for #55-A."""
import copy
import unittest

from models.nfl.contextual.flip_diagnostics import build_flip_diagnostics
from test_nfl_flip_diagnostics import fixture


class FlipContractTests(unittest.TestCase):
    def test_invalid_or_naive_cutoff_is_not_comparable(self):
        for cutoff in ('not-a-time', '2026-10-05T15:00:00', '2026-13-05T15:00:00Z'):
            with self.subTest(cutoff=cutoff):
                bundle = fixture()
                bundle['cutoff_utc'] = cutoff
                report = build_flip_diagnostics(bundle)
                self.assertEqual(report['status'], 'NOT_COMPARABLE')
                self.assertIsNone(report['pick_flip'])
                self.assertIn('INVALID_SOURCE_TIME:cutoff_utc', report['flags'])

    def test_missing_or_invalid_start_is_not_comparable(self):
        for start in (None, '', '2026-10-06T00:15:00', 'invalid'):
            with self.subTest(start=start):
                bundle = fixture()
                bundle['event']['start_time_utc'] = start
                report = build_flip_diagnostics(bundle)
                self.assertEqual(report['status'], 'NOT_COMPARABLE')
                self.assertIn('INVALID_SOURCE_TIME:start_time_utc', report['flags'])

    def test_cutoff_at_or_after_start_is_not_pregame(self):
        for cutoff in ('2026-10-06T00:15:00Z', '2026-10-06T00:16:00Z'):
            bundle = fixture()
            bundle['cutoff_utc'] = cutoff
            report = build_flip_diagnostics(bundle)
            self.assertEqual(report['status'], 'NOT_COMPARABLE')
            self.assertIn('SOURCE_CUTOFF_NOT_PREGAME', report['flags'])

    def test_unknown_forecast_schema_cannot_inherit_target(self):
        for schema in (None, 'unrelated.forecast.v1'):
            bundle = fixture()
            bundle['schema'] = schema
            report = build_flip_diagnostics(bundle)
            self.assertEqual(report['status'], 'NOT_COMPARABLE')
            self.assertIn('UNSUPPORTED_SOURCE_SCHEMA', report['flags'])

    def test_contradictory_target_scope_is_not_comparable(self):
        changes = {'target': 'away_win', 'period': 'FIRST_HALF',
                   'probability_orientation': 'AWAY', 'tie_policy': 'TIE_IS_LOSS',
                   'settlement_definition': 'REGULATION_ONLY'}
        for where in ('bundle', 'base', 'qb'):
            for key, value in changes.items():
                with self.subTest(where=where, field=key):
                    bundle = fixture()
                    target = bundle if where == 'bundle' else bundle['arms'][where]
                    target[key] = value
                    report = build_flip_diagnostics(bundle)
                    self.assertEqual(report['status'], 'NOT_COMPARABLE')
                    self.assertIsNone(report['pick_flip'])
                    self.assertIn('TARGET_CONTRACT_MISMATCH:' + where + ':' + key, report['flags'])

    def test_explicit_contract_and_timezone_equivalence(self):
        bundle = fixture()
        bundle['arms']['qb']['cutoff_utc'] = '2026-10-05T08:00:00-07:00'
        contract = {'target': 'home_win', 'period': 'FULL_GAME',
                    'probability_orientation': 'HOME', 'tie_policy': 'CONDITIONAL_ON_NON_TIE',
                    'settlement_definition': 'FINAL_RESULT_INCLUDING_OVERTIME'}
        bundle.update(contract)
        bundle['arms']['qb'].update(contract)
        before = copy.deepcopy(bundle)
        report = build_flip_diagnostics(bundle)
        self.assertEqual(report['status'], 'COMPARABLE')
        self.assertEqual(report['source']['target_contract'], contract)
        self.assertEqual(report['numeric_policy']['pick_tolerance'], 0.0)
        self.assertEqual(bundle, before)


if __name__ == '__main__':
    unittest.main()
