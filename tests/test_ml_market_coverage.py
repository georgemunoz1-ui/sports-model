"""Data-free regression tests for the canonical MLB feature firewall."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'harness'))
import build_ml_asof as B


def rows(n=101):
    return [dict(gamePk=str(i), slate_date='2026-09-05',
                 team={s: {'last_obs_date': '2026-09-04'} for s in ('home', 'away')},
                 sp={'home': None, 'away': None}, executable_eligible=False,
                 starter_status='UNRESOLVED', starter_confirmed_pregame=False,
                 flags={'sp_missing_sides': ['home', 'away']}) for i in range(n)]


class MarketCoverage(unittest.TestCase):
    def test_every_row_reaches_validation(self):
        for index in (0, 49, 50, 100):
            for section in ('team', 'sp'):
                with self.subTest(index=index, section=section):
                    data = rows()
                    data[index][section]['home'] = {'nested': [{'ODDS': -110}]}
                    if section == 'team':
                        data[index][section]['home']['last_obs_date'] = None
                    defects = B.validate(data, len(data), [{} for _ in data])
                    self.assertTrue(any('market token' in d for d in defects))

    def test_clean_input_is_not_mutated(self):
        data = rows()
        before = B.dataset_bytes(data)
        self.assertEqual(B.assert_no_market_fields(data), [])
        self.assertEqual(before, B.dataset_bytes(data))

    def test_empty_input(self):
        self.assertEqual(B.assert_no_market_fields([]), [])

    def test_labels_remain_outside_feature_scan(self):
        data = rows(1)
        data[0]['label_total'] = 9
        self.assertEqual(B.assert_no_market_fields(data), [])


if __name__ == '__main__':
    unittest.main()
