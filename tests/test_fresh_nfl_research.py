"""Synthetic orchestration fixtures only; not forecasts or live-source acceptance."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np

from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.recovered_inference import digest
from pipelines.cards.adapters import nfl
from scripts.generate_card_force import generate as generate_card
from scripts.run_fresh_nfl_research import run, verify_inference_traces


class FreshNFLTests(unittest.TestCase):
    model_path = Path(__file__).resolve().parents[1] / 'data/nfl/contextual_v1/model_packed.json'

    @classmethod
    def setUpClass(cls):
        cls.artifact = load_artifact(cls.model_path)
        cls.model_digest = digest(cls.artifact)
        cls.model_id = cls.artifact['arms']['qb']['model_id']

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sources = self.root / 'sources'
        self.sources.mkdir()
        raw = b'fixture raw schedule bytes'
        (self.sources / 'raw.csv').write_bytes(raw)
        self.source = {'source': 'https://example.invalid/schedule', 'sha256': hashlib.sha256(raw).hexdigest(), 'fetched_at_utc': '2026-01-01T00:00:00Z'}
        (self.sources / 'report.json').write_text(json.dumps({'sources': [{'url': self.source['source'], 'raw_sha256': self.source['sha256'], 'retrieved_at_utc': self.source['fetched_at_utc'], 'raw_path': 'raw.csv', 'status': 'CAPTURED'}]}))
        self.fake = types.ModuleType('scripts.prepare_nfl_weekly_events')
        self.fake.build = self.build
        self.different_state = False
        self.mutate_draw = False

    def build(self, store, state, seed, output):
        event = {'event_id': '2026_05_A_H', 'gameday': '2026-10-11',
                 'home_team': 'H', 'away_team': 'A', 'start_time_utc': '2026-10-11T20:00:00Z'}
        self.package = {'covered_dates': ['2026-10-11'], 'events': [event],
                        'event_inputs': {event['event_id']: {'base': {'season': 2026, 'week': 5}, 'context': {}}},
                        'source_fetches': [self.source], 'selected_model_id': self.model_id,
                        'model_digest': self.model_digest, 'model_path': str(self.model_path)}
        output.write_text(json.dumps(self.package))
        return self.package

    def generate(self, date, league, cutoff, simulations, overrides):
        self.assertTrue(Path(os.environ['NFL_CONTEXT_PACKAGE']).is_file())
        event, = self.package['events']
        draws = (np.arange(simulations) % 2).astype(np.uint8)
        trace = {'schema': 'nfl.integrated_context_forecast.v1', 'mode': 'research_pregame',
                 'features': {'fixture_feature': 1.0}, 'event': event, 'cutoff_utc': cutoff,
                 'assimilation': {'state_id': 'different' if self.different_state else 'state'},
                 'model_id': self.model_id, 'model_artifact_sha256': self.model_digest,
                 'winner_simulation': {'count': simulations, 'sha256': hashlib.sha256(draws.tobytes()).hexdigest(),
                                       'home_win_probability': float(draws.mean())},
                 'prediction': {'home_win': 0.35}, 'joint_distribution': None, 'market_input': False,
                 'score_simulation': {'status': 'UNAVAILABLE_FOR_SELECTED_ARM'}, 'warnings': [],
                 'coverage_label': 'SYNTHETIC_TEST_ONLY', 'identity': 'synthetic', 'selected_arm': 'qb',
                 'arms': {'base': {'prediction': {'home_win': .6}}, 'qb': {'prediction': {'home_win': .35}}}}
        def persist(directory, result, winner, scores, design):
            directory.mkdir(parents=True)
            (directory / 'forecast.json').write_text(json.dumps(result))
            np.save(directory / 'winner_draws.npy', winner, allow_pickle=False)
            files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir()}
            (directory / 'manifest.json').write_text(json.dumps(files))
            if self.mutate_draw:
                (directory / 'winner_draws.npy').write_bytes(b'changed')

        context = {'model': self.artifact, 'recovered': {}, 'cutoff': cutoff, 'package': self.package}
        with patch.object(nfl, 'load_schedule', return_value=[event]), patch.object(nfl, 'build_context', return_value=context), \
                patch.object(nfl, 'run', return_value=(trace, draws, None)), \
                patch('models.nfl.contextual.runtime.persist_run', side_effect=persist), \
                patch('scripts.generate_card_force.now_utc', return_value=datetime(2026, 10, 11, 10, 1, tzinfo=timezone.utc)):
            return generate_card(date, league, cutoff, simulations, overrides)

    def execute(self, date='2026-10-11'):
        with patch.dict(sys.modules, {'scripts.prepare_nfl_weekly_events': self.fake}), patch.dict(os.environ, {'NFL_WEEKLY_STATE_SEED_SHA256': 'seed'}), patch('scripts.run_fresh_nfl_research.utc', return_value='2026-10-11T10:00:00Z'), patch('scripts.generate_card_force.generate', self.generate):
            return run(self.root / 'state', 'state', 'seed', [self.sources], date, self.root / 'out', 10)

    def test_bound_frozen_package_and_trace(self):
        result = self.execute()
        self.assertTrue(result['forecast_consumption_verified'])
        self.assertFalse(result['model_refitted'])
        self.assertFalse(result['defaults_changed'])
        self.assertFalse(result['action_authority'])
        self.assertTrue((self.root / 'out/manifest.json').exists())

    def test_wrong_date_refused_without_running(self):
        result = self.execute('2026-10-12')
        self.assertFalse(result['forecast_consumption_verified'])
        self.assertIn('DATE_NOT_IN', result['reason'])
        self.assertFalse((self.root / 'out/draws').exists())

    def test_wrong_state_trace_refused(self):
        self.different_state = True
        result = self.execute()
        self.assertFalse(result['forecast_consumption_verified'])
        self.assertIn('STATE_CONSUMPTION_UNVERIFIED', result['reason'])

    def test_mutated_draw_refused(self):
        self.mutate_draw = True
        result = self.execute()
        self.assertFalse(result['forecast_consumption_verified'])
        self.assertIn('TRACE_DIGEST_MISMATCH', result['reason'])

    def test_display_must_reproduce_from_raw_forecast(self):
        self.assertTrue(self.execute()['forecast_consumption_verified'])
        output = self.root / 'out'
        pristine = (output / 'diagnostic_card.json').read_bytes()
        trace_file = next((output / 'draws').glob('*/forecast.json'))
        raw_bytes = trace_file.read_bytes()
        mutations = [
            ('model_p', .51), ('model_winner', 'H'), ('qb_home_probability', .99), ('selection_hash', 'wrong'),
            ('diagnostics.prediction.home_win', .8), ('diagnostics.market_input', 0),
            ('diagnostics.flip_diagnostics.delta_pp', 75), ('diagnostics.flip_diagnostics.extra', 'unknown'),
            ('diagnostics.default_selection.action_authority', True),
            ('diagnostics.arm_feature_references.model_artifact_sha256', 'wrong'),
            ('diagnostics', json.loads(raw_bytes)), ('unknown_display_field', True),
        ]
        for field, value in mutations:
            with self.subTest(field=field):
                card = json.loads(pristine)
                obj = card['forecasts'][0]
                parts = field.split('.')
                for part in parts[:-1]:
                    obj = obj[part]
                obj[parts[-1]] = value
                with self.assertRaisesRegex(ValueError, 'TRACE_CARD_MISMATCH'):
                    verify_inference_traces(card, self.package['events'], self.package, 'state', output)
        self.assertEqual(trace_file.read_bytes(), raw_bytes)
        self.assertEqual((output / 'diagnostic_card.json').read_bytes(), pristine)

    def test_resealed_winner_file_still_requires_frozen_draw_digest(self):
        self.assertTrue(self.execute()['forecast_consumption_verified'])
        output = self.root / 'out'
        card = json.loads((output / 'diagnostic_card.json').read_bytes())
        folder = Path(card['forecasts'][0]['simulation']['draw_directory'])
        draws = folder / 'winner_draws.npy'
        np.save(draws, 1 - np.load(draws, allow_pickle=False), allow_pickle=False)
        manifest = json.loads((folder / 'manifest.json').read_text())
        manifest[draws.name] = hashlib.sha256(draws.read_bytes()).hexdigest()
        (folder / 'manifest.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'WINNER_DRAW_MISMATCH'):
            verify_inference_traces(card, self.package['events'], self.package, 'state', output)

    def test_independent_seed_pin_required(self):
        with patch.dict(sys.modules, {'scripts.prepare_nfl_weekly_events': self.fake}), patch.dict(os.environ, {'NFL_WEEKLY_STATE_SEED_SHA256': 'wrong'}):
            with self.assertRaisesRegex(ValueError, 'INDEPENDENT_OPERATOR_SEED_PIN_REQUIRED'):
                run(self.root, 'state', 'seed', [self.sources], '2026-10-11', self.root / 'out')
        self.assertFalse((self.root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
