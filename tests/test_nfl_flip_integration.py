"""Diagnostic plumbing contracts; no model evaluation or prospective forecasts."""
import copy
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import numpy as np

from pipelines.cards import nfl_flip_integration as runtime
from models.nfl.contextual.capabilities import reporter_hash
from models.nfl.contextual.flip_diagnostics import build_flip_diagnostics, append_flip_diagnostic
from models.nfl.contextual.model import load_artifact
from scripts import generate_card_force as cards

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/nfl/contextual_v1'


class FlipIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact = load_artifact(DATA / 'model_packed.json')
        cls.recovered = json.loads((DATA / 'recovered_parameters.json').read_text())
        cls.base = json.loads((DATA / 'mnf_base_row.json').read_text())[0]
        cls.context = json.loads((DATA / 'mnf_context_integrated.json').read_text())
        cls.event = json.loads((DATA / 'mnf_event.json').read_text())
        cls.bundle, cls.draws, _ = runtime.run(cls.artifact, cls.recovered, cls.base,
            cls.context, cls.event, '2026-09-14T12:00:00Z', 1000,
            model_id=cls.artifact['arms']['qb']['model_id'])

    def test_report_preserves_legacy_and_numeric_v2_identity_and_draws(self):
        from models.nfl.contextual import runtime as numerical
        from pipelines.cards.semantic_identity import reidentify_nfl_run, SEMANTIC
        original, winner, scores = numerical.run(self.artifact, self.recovered, self.base,
            self.context, self.event, '2026-09-14T12:00:00Z', 1000,
            model_id=self.artifact['arms']['qb']['model_id'])
        self.assertEqual(original['identity'], self.bundle['identity'])
        self.assertEqual(original['prediction'], self.bundle['prediction'])
        np.testing.assert_array_equal(winner, self.draws)
        left, left_draws, _ = reidentify_nfl_run(self.artifact, self.event,
            original['cutoff_utc'], original, winner, scores, semantics=SEMANTIC)
        right = runtime.attach_diagnostic(left, self.artifact)
        self.assertEqual(left['numerical_identity'], right['numerical_identity'])
        self.assertEqual(right['flip_diagnostics']['source']['forecast_identity'], left['identity'])
        decorated, decorated_draws, _ = reidentify_nfl_run(self.artifact, self.event,
            original['cutoff_utc'], self.bundle, self.draws, scores, semantics=SEMANTIC)
        self.assertEqual(left['identity'], decorated['identity'])
        np.testing.assert_array_equal(left_draws, decorated_draws)
        self.assertNotIn('flip_diagnostics', original)

    def test_runtime_attaches_bound_diagnostic_without_changing_selected_arm(self):
        bundle = self.bundle
        diag = bundle['flip_diagnostics']
        self.assertEqual(diag['status'], 'COMPARABLE')
        self.assertEqual(diag['source']['forecast_identity'], bundle['identity'])
        self.assertEqual(diag['source']['arm_model_ids']['base'], self.artifact['arms']['base']['model_id'])
        self.assertEqual(bundle['prediction'], bundle['arms']['qb']['prediction'])
        self.assertEqual(diag['contributions']['status'], 'COMPLETE')
        self.assertFalse(bundle['market_input'])
        before, draws = copy.deepcopy(bundle), self.draws.copy()
        rebuilt = build_flip_diagnostics(bundle, {n: p['model_id'] for n, p in self.artifact['arms'].items()})
        self.assertEqual(diag, rebuilt)
        self.assertEqual(bundle, before)
        np.testing.assert_array_equal(self.draws, draws)

    def row(self):
        p = self.bundle['prediction']['home_win']
        return cards.normalize(self.event, {'model_p': p, 'sim_p': p, 'dose': 0,
            'model_winner': self.event['home_team'], 'diagnostics': copy.deepcopy(self.bundle)})

    def test_fitted_reference_values_replay_and_do_not_alias_artifact(self):
        bundle = copy.deepcopy(self.bundle)
        refs = bundle['flip_diagnostics']['feature_references']
        self.assertEqual(refs['status'], 'TRACE_VERIFIED')
        for name in ('base', 'qb'):
            params = self.artifact['arms'][name]
            for i, feature in enumerate(params['feature_names']):
                term = refs['arms'][name]['features'][feature]
                self.assertEqual(term['center'], params['heads']['home_win']['center'][i])
                self.assertEqual(term['scale'], params['heads']['home_win']['scale'][i])
                self.assertEqual(term['raw_value'], bundle['features'][feature])
                self.assertAlmostEqual(term['contribution'], bundle['arms'][name]['contribution_trace']['home_win']['features'][feature])
        prior = copy.deepcopy(self.artifact)
        bundle['arm_feature_references']['arms']['qb']['home_win_head']['center'][0] += 999
        self.assertEqual(self.artifact, prior)
        self.assertEqual(build_flip_diagnostics(bundle, {n: p['model_id'] for n, p in self.artifact['arms'].items()})['feature_references']['status'], 'INVALID')

    def test_missing_or_misbound_references_remain_visible(self):
        models = {n: p['model_id'] for n, p in self.artifact['arms'].items()}
        for change in ('missing', 'artifact', 'arm', 'scale'):
            bundle = copy.deepcopy(self.bundle)
            if change == 'missing':
                del bundle['arm_feature_references']
            elif change == 'artifact':
                bundle['arm_feature_references']['model_artifact_sha256'] = 'wrong'
            elif change == 'arm':
                bundle['arm_feature_references']['arms']['qb']['model_id'] = 'wrong'
            else:
                bundle['arm_feature_references']['arms']['qb']['home_win_head']['scale'][0] = 0
            report = build_flip_diagnostics(bundle, models)
            self.assertEqual(report['status'], 'COMPARABLE')
            self.assertEqual(report['feature_references']['status'], 'UNAVAILABLE' if change == 'missing' else 'INVALID')
            self.assertTrue(any(flag.startswith('FEATURE_REFERENCES_') for flag in report['flags']))

    def card(self):
        return {'league': 'NFL', 'card_date': '2099-01-01', 'pregame_coverage': 1,
            'forecasts': [self.row()], 'incidents': [], 'coverage_breach_event_ids': [],
            'as_of_utc': '2026-09-14T12:00:00Z', 'generated_at_utc': '2026-09-14T12:00:00Z', 'requested_as_of_utc': '2026-09-14T12:00:00Z'}

    def test_card_retains_exact_fields_and_missing_diagnostic_is_visible(self):
        row = self.row()
        diag = self.bundle['flip_diagnostics']
        self.assertEqual(row['base_home_probability'], diag['base']['home_win_probability'])
        self.assertEqual(row['base_qb_pick_flip'], diag['pick_flip'])
        card = self.card()
        text = cards.render_md(card)
        self.assertIn('Base versus QB diagnostics', text)
        self.assertIn('COMPARABLE', text)
        card['forecasts'][0]['diagnostics'].pop('flip_diagnostics')
        text = cards.render_md(card)
        self.assertIn('DIAGNOSTIC_MISSING', text)
        self.assertIn('UNKNOWN', text)

    def test_card_writer_emits_json_csv_and_separate_stream(self):
        card = self.card()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'card'
            with patch.object(cards, 'generate', return_value=card), patch('sys.argv',
                    ['generate_card_force.py', '--date', '2099-01-01', '--league', 'nfl', '--output-dir', str(output)]), \
                    patch.dict('os.environ', {}, clear=False), redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    cards.main()
            self.assertEqual(caught.exception.code, 0)
            self.assertIn('base_qb_pick_flip', (output / 'diagnostic_card.csv').read_text())
            saved = json.loads((output / 'diagnostic_card.json').read_text())
            self.assertEqual(saved['forecasts'][0]['diagnostics']['flip_diagnostics'], self.bundle['flip_diagnostics'])
            path = output / 'flip_diagnostics.jsonl'
            before = path.read_bytes()
            self.assertFalse(append_flip_diagnostic(path, self.bundle['flip_diagnostics'])['appended'])
            self.assertEqual(path.read_bytes(), before)

    def test_persistence_hashes_sidecar_and_preserves_draws(self):
        # Synthetic future event exercises writer mechanics, not model eligibility.
        bundle = copy.deepcopy(self.bundle)
        bundle['event']['start_time_utc'] = '2100-01-01T00:00:00Z'
        bundle['identity'] = 'synthetic-writer-only'
        bundle['capability_report'] = {'reporter_sha256': reporter_hash(), 'rows': []}
        bundle['flip_diagnostics'] = build_flip_diagnostics(bundle,
            {n: p['model_id'] for n, p in self.artifact['arms'].items()})
        before = copy.deepcopy(bundle)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / 'event'
            runtime.persist_run(folder, bundle, self.draws, None, {'synthetic': True})
            sidecar = folder / 'diagnostics' / 'flip_diagnostics.json'
            manifest = json.loads((folder / 'diagnostics' / 'manifest.json').read_text())
            self.assertEqual(manifest['flip_diagnostics.json'], hashlib.sha256(sidecar.read_bytes()).hexdigest())
            self.assertEqual(json.loads(sidecar.read_text()), bundle['flip_diagnostics'])
            np.testing.assert_array_equal(np.load(folder / 'winner_draws.npy'), self.draws)
            stream = Path(directory) / 'flip_diagnostics.jsonl'
            self.assertEqual(len(stream.read_text().splitlines()), 1)
            self.assertFalse(append_flip_diagnostic(stream, bundle['flip_diagnostics'])['appended'])
        self.assertEqual(bundle, before)

    def test_enhanced_mode_keeps_diagnostic_only_under_football_reference(self):
        from models.nfl.modes import runtime as modes
        football = copy.deepcopy(self.bundle)
        model = {'model_id': 'synthetic-market-model', 'football_model_id': football['model_id'],
            'football_artifact_sha256': football['model_artifact_sha256'],
            'final_score_residuals': [], 'tie_rate': 0,
            'weights': {k: .5 for k in football['prediction']}}
        with patch.object(modes, 'market_values', return_value=(football['prediction'], {})), \
                patch.object(modes, 'ensemble', return_value=football['prediction']), \
                patch.object(modes, 'simulate_joint', return_value=(np.zeros((2, 2)), {})), \
                patch('models.nfl.contextual.capabilities.describe_ensemble', return_value={}):
            bundle, _, _ = runtime.enhanced(football, model, {}, football['event'], football['cutoff_utc'], 2)
        self.assertNotIn('flip_diagnostics', bundle)
        self.assertEqual(bundle['football_reference']['flip_diagnostics'], football['flip_diagnostics'])
        self.assertTrue(bundle['market_input'])
        self.assertEqual(football, self.bundle)


if __name__ == '__main__':
    unittest.main()
