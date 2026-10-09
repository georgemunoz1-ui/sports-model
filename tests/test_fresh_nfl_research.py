"""Synthetic orchestration fixtures only; not forecasts or live-source acceptance."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from scripts.run_fresh_nfl_research import run


class FreshNFLTests(unittest.TestCase):
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
        package = {'covered_dates': ['2026-10-11'], 'events': [{'event_id': 'FIXTURE_ONLY', 'gameday': '2026-10-11'}], 'source_fetches': [self.source], 'selected_model_id': 'fixture-model', 'model_digest': 'fixture-model-digest'}
        output.write_text(json.dumps(package))
        return package

    def generate(self, date, league, cutoff, simulations, overrides):
        self.assertTrue(Path(os.environ['NFL_CONTEXT_PACKAGE']).is_file())
        directory = Path(os.environ['SPORTS_RESEARCH_DRAW_OUTPUT']) / 'fixture'
        directory.mkdir(parents=True)
        diag = {'features': {'fixture_feature': 1.0}, 'assimilation': {'state_id': 'different' if self.different_state else 'state'}}
        (directory / 'forecast.json').write_text(json.dumps(diag))
        (directory / 'winner_draws.npy').write_bytes(b'fixture draw bytes, not a real simulation')
        files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir()}
        (directory / 'manifest.json').write_text(json.dumps(files))
        if self.mutate_draw:
            (directory / 'winner_draws.npy').write_bytes(b'changed')
        return {'forecasts': [{'forecast_status': 'FORECAST_GENERATED', 'event_id': 'FIXTURE_ONLY', 'model_id': 'fixture-model', 'simulation': {'draw_directory': str(directory)}, 'model_input_snapshot': diag['features'], 'input_snapshot_hash': hashlib.sha256(json.dumps(diag['features'], sort_keys=True, separators=(',', ':')).encode()).hexdigest(), 'model_state_config_hash': 'fixture-model-digest', 'diagnostics': diag}], 'incidents': []}

    def execute(self, date='2026-10-11'):
        with patch.dict(sys.modules, {'scripts.prepare_nfl_weekly_events': self.fake}), patch.dict(os.environ, {'NFL_WEEKLY_STATE_SEED_SHA256': 'seed'}), patch('scripts.generate_card_force.generate', self.generate):
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

    def test_independent_seed_pin_required(self):
        with patch.dict(sys.modules, {'scripts.prepare_nfl_weekly_events': self.fake}), patch.dict(os.environ, {'NFL_WEEKLY_STATE_SEED_SHA256': 'wrong'}):
            with self.assertRaisesRegex(ValueError, 'INDEPENDENT_OPERATOR_SEED_PIN_REQUIRED'):
                run(self.root, 'state', 'seed', [self.sources], '2026-10-11', self.root / 'out')
        self.assertFalse((self.root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
