import copy
import math
import unittest
from research import offline_benchmark as B


def fixture():
    return [{'id': str(i), 'cutoff': f'2026-08-{i:02d}T10:00:00Z',
             'start': f'2026-08-{i:02d}T11:00:00Z',
             'target_known_at': f'2026-08-{i:02d}T20:00:00Z',
             'features': {'runs': None if i == 2 else 4.0},
             'known_at': {'runs': f'2026-08-{i:02d}T09:00:00Z'}, 'target': 1}
            for i in range(1, 6)]


class Tests(unittest.TestCase):
    def test_pit_and_hash(self):
        rows = fixture()
        self.assertEqual(B.validate_rows(rows, ['runs']), B.digest(rows))
        rows[-1]['known_at']['runs'] = '2027-01-01T00:00:00Z'
        with self.assertRaises(ValueError): B.validate_rows(rows, ['runs'])

    def test_contract_attacks(self):
        for mutation in ('duplicate', 'nan', 'nested', 'naive', 'cutoff'):
            rows = fixture()
            if mutation == 'duplicate': rows.append(copy.deepcopy(rows[0]))
            if mutation == 'nan': rows[-1]['features']['runs'] = float('nan')
            if mutation == 'nested': rows[-1]['features']['runs'] = {'odds': 100}
            if mutation == 'naive': rows[-1]['cutoff'] = '2026-08-05T10:00:00'
            if mutation == 'cutoff': rows[-1]['cutoff'] = rows[-1]['start']
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                B.validate_rows(rows, ['runs'])
        with self.assertRaises(ValueError): B.validate_rows(fixture(), ['market_odds'])

    def test_folds(self):
        f = B.rolling_folds(fixture(), ['2026-08-03T00:00:00Z'], 1, '2026-08-05T00:00:00Z')
        self.assertEqual(f['folds'][0]['train'], ['1', '2'])
        self.assertEqual(f['folds'][0]['test'], ['3'])
        with self.assertRaises(ValueError):
            B.rolling_folds(fixture(), ['2026-08-03T00:00:00Z'], 3, '2026-08-05T00:00:00Z')

    def test_delayed_labels(self):
        rows = fixture()
        rows[1]['target_known_at'] = '2026-08-04T00:00:00Z'
        f = B.rolling_folds(rows, ['2026-08-03T00:00:00Z'], 1, '2026-08-05T00:00:00Z')
        self.assertEqual(f['folds'][0]['train'], ['1'])

    def test_scores(self):
        r = B.probability_scores([1], [[.25, .75]])
        self.assertAlmostEqual(r['log_loss'], -math.log(.75))
        self.assertAlmostEqual(r['brier_sum'], .125)
        self.assertAlmostEqual(B.probability_scores([2], [[.2, .3, .5]])['log_loss'], math.log(2))
        for p in ([[0, 0]], [[0, 1]], [[float('nan'), 1]]):
            with self.assertRaises(ValueError): B.probability_scores([0], p)

    def test_intervals(self):
        qs = {.05: 0, .1: 1, .25: 2, .5: 3, .75: 4, .9: 5, .95: 6}
        r = B.state_scores([3], [3], [qs])
        self.assertEqual(r['mae'], 0)
        self.assertEqual(r['coverage'][90], 1)
        self.assertEqual(r['interval_width'][50], 2)
        qs[.5] = 100
        with self.assertRaises(ValueError): B.state_scores([3], [3], [qs])

    def test_bootstrap_and_population(self):
        args = (['a', 'b'], {'a': '2026-08-01', 'b': '2026-08-02'},
                {'a': 1., 'b': 1.}, {'a': .5, 'b': .5}, 42)
        r = B.paired_day_bootstrap(*args)
        self.assertEqual(r, B.paired_day_bootstrap(*args))
        self.assertEqual(r['ci95'], [-.5, -.5])
        with self.assertRaises(ValueError):
            B.paired_day_bootstrap(args[0], args[1], args[2], {'a': .5}, 42)

    def test_intake_blocks_unpinned(self):
        self.assertTrue(B.intake_defects({'model_id': 'toto', 'operational_use_approved': False}))


if __name__ == '__main__': unittest.main()
