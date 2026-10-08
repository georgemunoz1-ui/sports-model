"""Negative checks for the historical replay's temporal and data boundaries."""
import unittest
from scripts.run_distribution_history import ordered_splits, eligibility
from scripts.verify_distribution_study import equivalent


class HistoricalBoundaryTests(unittest.TestCase):
    def rows(self):
        return [({'event_id': str(y), 'season': y, 'start_time_utc': f'{y}-09-01T12:00:00Z'}, [0.])
                for y in range(2023, 2027)]

    def split(self):
        return dict(parent_train_max_season=2023, residual_season=2024,
                    calibration_season=2025, evaluation_season=2026)

    def test_late_season_labels_do_not_override_time(self):
        rows = self.rows(); rows[0][0]['start_time_utc'] = '2024-09-01T00:00:00Z'
        with self.assertRaisesRegex(ValueError, 'TEMPORAL_SPLIT_OVERLAP'):
            ordered_splits(rows, self.split())

    def test_missing_season_refused(self):
        with self.assertRaisesRegex(ValueError, 'EMPTY_TEMPORAL_SPLIT'):
            ordered_splits(self.rows()[:-1], self.split())

    def test_identity_cannot_cross_splits(self):
        rows = self.rows(); rows[2][0]['event_id'] = rows[1][0]['event_id']
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_STUDY_GAME'):
            ordered_splits(rows, self.split())

    def test_result_embargo_crosses_calendar_boundary(self):
        cutoff, available = eligibility({'start_time_utc': '2024-12-31T23:00:00Z'})
        self.assertEqual(cutoff, '2024-12-31T22:00:00+00:00')
        self.assertEqual(available, '2025-01-02T23:00:00+00:00')

    def test_platform_tolerance_cannot_mask_probability_change(self):
        equivalent({'p': .5 + 1e-14}, {'p': .5})
        with self.assertRaisesRegex(ValueError, 'REPLAY_NUMERIC'):
            equivalent({'p': .5 + 1e-8}, {'p': .5})

    def test_platform_tolerance_cannot_change_support_or_identity(self):
        with self.assertRaisesRegex(ValueError, 'REPLAY_IDENTITY'):
            equivalent({'support': [1, 2]}, {'support': [1, 3]})
        with self.assertRaisesRegex(ValueError, 'REPLAY_IDENTITY'):
            equivalent({'model': 'candidate'}, {'model': 'reference'})


if __name__ == '__main__': unittest.main()
