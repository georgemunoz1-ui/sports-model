import copy
import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from models.nfl.contextual import qb_margin as qm
from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.recovered_inference import digest, predict


class QbMarginTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{'game_id': f'2019_TEST_{i}', 'season': 2019, 'arm': 'qb',
                      'home_margin': [-7, -3, 0, 3, 7][i % 5], 'pred_margin': 0.0} for i in range(200)]
        self.law = qm.fit_residuals(self.rows, before_season=2020)
        self.law['tie_rate'] = .1

    def test_hand_calculated_cover_and_push_orientation(self):
        s, w = qm.kernel(0, .6, self.law)
        p = qm.price(s, w, -3)
        for name, value in {'cover': .27, 'push': .27, 'loss': .46}.items():
            self.assertAlmostEqual(p[name], value)
        away = qm.price(s, w, -3, side='AWAY')
        self.assertAlmostEqual(away['cover'], p['loss'])
        self.assertAlmostEqual(away['push'], p['push'])
        self.assertEqual(qm.price(s, w, -3.5)['push'], 0)

    def test_past_only_pool_and_no_combined_substitution(self):
        for key, value, error in [('season', 2020, 'FUTURE'), ('arm', 'combined', 'ARM'),
                                  ('game_id', self.rows[1]['game_id'], 'DUPLICATE'),
                                  ('home_margin', float('nan'), 'INVALID')]:
            bad = copy.deepcopy(self.rows); bad[0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, error):
                qm.fit_residuals(bad, before_season=2020)
        with self.assertRaisesRegex(ValueError, 'INSUFFICIENT'):
            qm.fit_residuals(self.rows[:199], before_season=2020)

    def test_mass_winner_coherence_and_monotonic_lines(self):
        s, w = qm.kernel(0, .6, self.law)
        summary = qm.summarize(s, w)
        self.assertAlmostEqual(summary['p_home_non_tie'], .6)
        self.assertAlmostEqual(summary['p_tie'], .1)
        previous = -1
        for line in np.arange(-10, 10, .5):
            p, q = qm.price(s, w, line), qm.price(s, w, line, side='AWAY')
            self.assertAlmostEqual(sum(p.values()), 1)
            self.assertGreaterEqual(p['cover'], previous); previous = p['cover']
            self.assertAlmostEqual(p['cover'], q['loss'])

    def test_side_swap_symmetry(self):
        s, w = qm.kernel(3.2, .6, self.law)
        reversed_law = copy.deepcopy(self.law)
        reversed_law['residuals'] = [-x for x in self.law['residuals']]
        other_s, other_w = qm.kernel(-3.2, .4, reversed_law)
        for line in [-7, -3.5, 0, 3.5, 7]:
            self.assertAlmostEqual(qm.price(s, w, line)['cover'], qm.price(other_s, other_w, -line, side='AWAY')['cover'])

    def test_simulation_replay_and_agreement(self):
        s, w = qm.kernel(0, .6, self.law)
        a, info = qm.simulate(s, w, 'UNIT_TEST_NOT_A_FORECAST')
        b, again = qm.simulate(s, w, 'UNIT_TEST_NOT_A_FORECAST')
        np.testing.assert_array_equal(a, b); self.assertEqual(info, again)
        self.assertEqual(a.dtype, np.dtype('<i2')); self.assertEqual(a.shape, (100000,))
        self.assertLess(abs(np.mean(a-3.5 > 0)-qm.price(s, w, -3.5)['cover']), .006)
        self.assertEqual(hashlib.sha256(a.tobytes()).hexdigest(), info['raw_sha256'])

    def test_bad_product_and_numeric_refusals(self):
        s, w = qm.kernel(0, .6, self.law)
        for line in [-3.25, float('nan'), float('inf'), True]:
            with self.assertRaises(ValueError): qm.price(s, w, line)
        for side, period in [('OVER', 'FULL_GAME'), ('HOME', 'FIRST_HALF')]:
            with self.assertRaises(ValueError): qm.price(s, w, 3.5, side=side, period=period)
        for n in [True, 0, 1.5]:
            with self.assertRaises(ValueError): qm.simulate(s, w, 'TEST', n)
        for location, probability in [(float('nan'), .5), (0, 1.1), (40000, .5)]:
            with self.assertRaises(ValueError): qm.kernel(location, probability, self.law)
        with self.assertRaisesRegex(ValueError, 'OUTCOME_SUPPORT_MISSING'):
            qm.kernel(1.2, .6, self.law)

    def fixture(self):
        path = qm.ROOT/'data/nfl/contextual_v1/model_packed.json'
        reference = load_artifact(path); qb = reference['arms']['qb']
        features = {key: 0.0 for key in qb['feature_names']}
        f = {'model_id': qm.REFERENCE_ID, 'selected_arm': 'qb', 'mode': 'research_pregame',
             'market_input': False, 'action_authority': False, 'identity': 'SYNTHETIC_UNIT_TEST',
             'event': {'event_id': '2100_01_A_B', 'away_team': 'A', 'home_team': 'B', 'start_time_utc': '2100-01-01T00:00:00Z'},
             'cutoff_utc': '2026-01-01T00:00:00Z', 'features': features,
             'prediction': predict(qb, features)['prediction'], 'model_artifact_sha256': digest(reference)}
        model = {'fitted_at_utc': '2026-01-01T00:00:00Z', 'reference_packed_sha256': qm.file_sha(path),
                 'reference_qb_coefficients_sha256': digest(qb), 'law': self.law}
        return f, model, {'retrospective_screen_passed': False}

    def test_head_and_reference_binding(self):
        f, model, evaluation = self.fixture()
        with patch.object(qm, 'load_registered', return_value=(model, evaluation)):
            result, draws = qm.build(f, n=1000)
            self.assertTrue(result['coherence']['non_tie_winner_head_preserved'])
            for key, value, error in [('model_id', 'nfl.integrated_context.combined.v1.research', 'REFERENCE'),
                                      ('market_input', True, 'FIREWALL'), ('model_artifact_sha256', 'bad', 'REFERENCE_HASH')]:
                bad = copy.deepcopy(f); bad[key] = value
                with self.assertRaisesRegex(ValueError, error): qm.build(bad)
            bad = copy.deepcopy(f); bad['prediction']['home_margin'] += 1
            with self.assertRaisesRegex(ValueError, 'HEAD_REPLAY'): qm.build(bad)

    def test_lines_do_not_change_frozen_draws_or_parent(self):
        f, model, evaluation = self.fixture(); original = copy.deepcopy(f)
        with patch.object(qm, 'load_registered', return_value=(model, evaluation)):
            bundle, draws = qm.build(f, n=1000)
        before = digest(bundle); raw = draws.copy()
        a = qm.compare(bundle, draws, [3.5]); b = qm.compare(bundle, draws, [3.5, 7])
        self.assertEqual(a['rows'], b['rows'][:2]); self.assertEqual(digest(bundle), before)
        self.assertEqual(f, original); np.testing.assert_array_equal(raw, draws)
        bad = draws.copy(); bad[0] += 1
        with self.assertRaisesRegex(ValueError, 'BINDING'): qm.compare(bundle, bad, [3.5])

    def test_writer_exclusive_hash_and_actual_clock(self):
        f, model, evaluation = self.fixture()
        with patch.object(qm, 'load_registered', return_value=(model, evaluation)):
            bundle, draws = qm.build(f, n=1000)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/'frozen'; qm.persist(folder, bundle, draws)
            before = {p.name: qm.file_sha(p) for p in folder.iterdir()}
            with self.assertRaises(FileExistsError): qm.persist(folder, bundle, draws)
            self.assertEqual(before, {p.name: qm.file_sha(p) for p in folder.iterdir()})
            bad = copy.deepcopy(bundle); bad['event']['start_time_utc'] = '2000-01-01T00:00:00Z'
            with self.assertRaisesRegex(ValueError, 'CHRONOLOGY'): qm.persist(Path(tmp)/'late', bad, draws)
            self.assertFalse((Path(tmp)/'late').exists())
            bad_draws = draws.copy(); bad_draws[0] += 1
            with self.assertRaisesRegex(ValueError, 'DRAW_HASH'): qm.persist(Path(tmp)/'bad', bundle, bad_draws)
            self.assertFalse((Path(tmp)/'bad').exists())

    def test_registered_artifact_and_historical_binding(self):
        model, evaluation = qm.load_registered()
        self.assertEqual(model['reference_model_id'], qm.REFERENCE_ID)
        self.assertEqual(model['law']['count'], 1871)
        self.assertEqual(model['law']['max_season'], 2025)
        self.assertEqual(evaluation['metrics']['games'], 1615)
        self.assertFalse(model['market_input']); self.assertFalse(model['action_authority'])
        for fold in evaluation['head_replay']:
            self.assertLess(fold['training_max_season'], fold['season'])


if __name__ == '__main__': unittest.main()
