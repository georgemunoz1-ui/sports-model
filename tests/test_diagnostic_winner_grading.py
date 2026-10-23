"""Synthetic identity fixtures model the retained NMSU naming regression."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.diagnostic_winner_grading import bind_side, correct_assessment, winner_identity


def fixture():
    teams = [
        {'homeAway': 'away', 'score': '30', 'team': {'id': '166', 'displayName': 'New Mexico State Aggies', 'location': 'New Mexico State', 'shortDisplayName': 'NM State', 'abbreviation': 'NMSU'}},
        {'homeAway': 'home', 'score': '24', 'team': {'id': '2534', 'displayName': 'Sam Houston Bearkats', 'location': 'Sam Houston', 'shortDisplayName': 'Sam Houston', 'abbreviation': 'SHSU'}},
    ]
    payload = {'leagues': [{'id': '23', 'slug': 'college-football'}], 'events': [{'id': '401871070', 'competitions': [{'competitors': teams, 'status': {'type': {'completed': True, 'state': 'post', 'name': 'STATUS_FINAL'}}}]}]}
    raw = json.dumps(payload).encode(); sha = hashlib.sha256(raw).hexdigest()
    row = {'league': 'CFB', 'event_id': 'CFB:401871070', 'home_team': 'Sam Houston Bearkats', 'away_team': 'New Mexico State Aggies', 'model_pick': 'New Mexico State', 'final_score': '30-24', 'winner_correct': False, 'brier': 0.2025, 'result_source_sha256': sha, 'forecast_hash': 'frozen'}
    return row, payload, raw


class IdentityTests(unittest.TestCase):
    def test_nmsu_alias_and_preserve_metrics(self):
        row, payload, raw = fixture()
        original = {'grades': [row], 'summary': {'winner_correct': 0, 'winner_accuracy': 0, 'forecast_count': 1, 'CFB': {'n': 1, 'correct': 0}}, 'source_hashes': {'CFB': hashlib.sha256(raw).hexdigest()}, 'eligibility': 'DESCRIPTIVE_ONLY_NOT_CANONICAL_GRADE', 'canonical_ledger_changed': False}
        before = copy.deepcopy(original)
        out = correct_assessment(original, {'CFB': raw})
        self.assertEqual(original, before)
        self.assertTrue(out['grades'][0]['winner_correct'])
        self.assertEqual(out['summary']['winner_correct'], 1)
        self.assertEqual(out['grades'][0]['brier'], row['brier'])
        self.assertEqual(out['grades'][0]['forecast_hash'], 'frozen')
        self.assertEqual(out['grades'][0]['identity_binding']['away_team_id'], '166')

    def test_aliases_home_and_away(self):
        row, payload, _ = fixture()
        for name in ['NMSU', 'NM State', 'New Mexico State Aggies', ' New  Mexico State ']:
            row['model_pick'] = name
            self.assertTrue(winner_identity(row, payload)['winner_correct'])
        row['model_pick'] = 'SHSU'
        self.assertFalse(winner_identity(row, payload)['winner_correct'])

    def test_no_fuzzy_or_mascot(self):
        row, payload, _ = fixture()
        for name in ['New Mexico', 'Aggies', 'New Mexico States', None]:
            row['model_pick'] = name
            with self.assertRaisesRegex(ValueError, 'TEAM_LABEL_UNRESOLVED'):
                winner_identity(row, payload)

    def test_conflicting_id_and_label(self):
        row, payload, _ = fixture(); row['model_pick_team_id'] = '2534'
        with self.assertRaisesRegex(ValueError, 'TEAM_ID_LABEL_CONFLICT'):
            winner_identity(row, payload)

    def test_unknown_id_never_falls_back(self):
        row, payload, _ = fixture(); row['model_pick_team_id'] = '999'
        with self.assertRaisesRegex(ValueError, 'TEAM_ID_MISMATCH'):
            winner_identity(row, payload)

    def test_exact_ids(self):
        row, payload, _ = fixture(); row['model_pick_team_id'] = '166'
        self.assertTrue(winner_identity(row, payload)['winner_correct'])

    def test_alias_collision(self):
        row, payload, _ = fixture()
        payload['events'][0]['competitions'][0]['competitors'][1]['team']['location'] = 'New Mexico State'
        with self.assertRaisesRegex(ValueError, 'TEAM_LABEL_AMBIGUOUS'):
            winner_identity(row, payload)

    def test_event_league_binding(self):
        row, payload, _ = fixture(); row['event_id'] = 'NBA:401871070'
        with self.assertRaisesRegex(ValueError, 'LEAGUE_EVENT_BINDING'):
            winner_identity(row, payload)

    def test_duplicate_event(self):
        row, payload, _ = fixture(); payload['events'] *= 2
        with self.assertRaisesRegex(ValueError, 'AMBIGUOUS_EVENT_MATCH'):
            winner_identity(row, payload)

    def test_side_reversal(self):
        row, payload, _ = fixture(); row['home_team'], row['away_team'] = row['away_team'], row['home_team']
        with self.assertRaisesRegex(ValueError, 'RESULT_TEAM_SIDE_MISMATCH'):
            winner_identity(row, payload)

    def test_nonfinal_and_cancelled(self):
        row, payload, _ = fixture()
        kind = payload['events'][0]['competitions'][0]['status']['type']
        for field, value in [('completed', False), ('state', 'in'), ('name', 'STATUS_CANCELED')]:
            p = copy.deepcopy(payload); p['events'][0]['competitions'][0]['status']['type'][field] = value
            with self.assertRaisesRegex(ValueError, 'PROVIDER_NOT_PLAYED_FINAL'):
                winner_identity(row, p)

    def test_tie_not_away_win(self):
        row, payload, _ = fixture(); payload['events'][0]['competitions'][0]['competitors'][0]['score'] = '24'; row['final_score'] = '24-24'
        with self.assertRaisesRegex(ValueError, 'UNSUPPORTED_TIED_FINAL'):
            winner_identity(row, payload)
        row['league'] = 'MLS'; row['event_id'] = 'MLS:401871070'; row['model_pick'] = 'Draw'
        payload['leagues'] = [{'id': '770', 'slug': 'usa.1'}]
        payload['events'][0]['competitions'][0]['status']['type']['name'] = 'STATUS_FULL_TIME'
        self.assertTrue(winner_identity(row, payload)['winner_correct'])

    def test_output_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'assessment.json'
            row, _, raw = fixture()
            original = {'grades': [row], 'summary': {}, 'source_hashes': {'CFB': hashlib.sha256(raw).hexdigest()}, 'eligibility': 'DESCRIPTIVE_ONLY_NOT_CANONICAL_GRADE', 'canonical_ledger_changed': False}
            p.write_text(json.dumps(original)); before = p.read_bytes(); s = Path(tmp) / 'source.json'; s.write_bytes(raw)
            run = subprocess.run([sys.executable, 'scripts/diagnostic_winner_grading.py', '--assessment', str(p), '--scoreboard', 'CFB='+str(s), '--output', str(p)], capture_output=True)
            self.assertNotEqual(run.returncode, 0); self.assertEqual(p.read_bytes(), before)

    def test_invalid_scores(self):
        row, payload, _ = fixture()
        for value in ['nan', 'inf', '-1', '3.5', True, None]:
            p = copy.deepcopy(payload); p['events'][0]['competitions'][0]['competitors'][0]['score'] = value
            with self.assertRaisesRegex(ValueError, 'INVALID_FINAL_SCORE'):
                winner_identity(row, p)




class BoardTests(unittest.TestCase):
    def board_row(self):
        r, p, raw = fixture()
        return {k: r[k] for k in ('league', 'event_id', 'home_team', 'away_team')} | {'named_outcome': r['model_pick'], 'simulations': 100000, 'model_probability': .55, 'simulation_probability': .549}, raw

    def test_full_board_alias_brier_and_home_alias(self):
        from scripts.grade_research_board import grade_board
        row, raw = self.board_row()
        for pick, expected, correct in [('New Mexico State', .45**2, True), ('Sam Houston', .55**2, False)]:
            row['named_outcome'] = pick
            out = grade_board({'rows': [row]}, {'CFB': raw})
            self.assertEqual(out['status'], 'COMPLETED')
            self.assertEqual(out['grades'][0]['winner_correct'], correct)
            self.assertAlmostEqual(out['grades'][0]['brier'], expected)

    def test_explicit_probability_no_eager_fallback(self):
        from scripts.grade_research_board import grade_board
        row, raw = self.board_row(); del row['model_probability']; del row['simulation_probability']
        row['probabilities'] = {'analytic_home': .45, 'simulation_home': .451}
        self.assertEqual(grade_board({'rows': [row]}, {'CFB': raw})['status'], 'COMPLETED')

    def test_unresolved_blocks_not_loss(self):
        from scripts.grade_research_board import grade_board
        row, raw = self.board_row(); row['named_outcome'] = 'Aggies'
        out = grade_board({'rows': [row]}, {'CFB': raw})
        self.assertEqual(out['summary']['winner_graded_count'], 0)
        self.assertNotIn('winner_correct', out['grades'][0])
        self.assertEqual(out['blocked_count'], 1)

    def test_missing_league_and_duplicate(self):
        from scripts.grade_research_board import grade_board
        row, raw = self.board_row()
        self.assertEqual(grade_board({'rows': [row]}, {})['blocked_count'], 1)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_FORECAST_EVENT'):
            grade_board({'rows': [row, row]}, {'CFB': raw})

class ProvenanceTests(unittest.TestCase):
    def test_swapped_provider_league(self):
        row, payload, _ = fixture()
        row.update(league='NBA', event_id='NBA:401871070')
        with self.assertRaisesRegex(ValueError, 'PROVIDER_LEAGUE_BINDING'):
            winner_identity(row, payload)

    def test_draw_conflicting_team_id(self):
        row, payload, _ = fixture()
        row.update(league='MLS', event_id='MLS:401871070', model_pick='Draw', model_pick_team_id='166')
        payload['leagues'] = [{'id': '770', 'slug': 'usa.1'}]
        payload['events'][0]['competitions'][0]['status']['type']['name'] = 'STATUS_FULL_TIME'
        with self.assertRaisesRegex(ValueError, 'DRAW_TEAM_ID_CONFLICT'):
            winner_identity(row, payload)

    def test_corrupt_receipt_and_blocked_denominator(self):
        row, payload, raw = fixture()
        original = {'grades': [row], 'summary': {'forecast_count': 1}, 'source_hashes': {'CFB': hashlib.sha256(raw).hexdigest()}, 'eligibility': 'DESCRIPTIVE_ONLY_NOT_CANONICAL_GRADE', 'canonical_ledger_changed': False}
        with self.assertRaisesRegex(ValueError, 'RESULT_SOURCE_HASH_MISMATCH'):
            correct_assessment(original, {'CFB': b'{}'})
        original['grades'][0]['model_pick'] = 'Aggies'
        out = correct_assessment(original, {'CFB': raw})
        self.assertIsNone(out['grades'][0]['winner_correct'])
        self.assertEqual(out['summary']['winner_graded_count'], 0)
        self.assertEqual(out['summary']['winner_blocked_count'], 1)

class StrictSchemaTests(unittest.TestCase):
    def test_truthy_completed_is_not_final(self):
        row, payload, _ = fixture()
        payload['events'][0]['competitions'][0]['status']['type']['completed'] = 'false'
        with self.assertRaisesRegex(ValueError, 'PROVIDER_NOT_PLAYED_FINAL'):
            winner_identity(row, payload)

    def test_invalid_label_with_valid_id(self):
        row, payload, _ = fixture(); row.update(model_pick=47, model_pick_team_id='166')
        with self.assertRaisesRegex(ValueError, 'INVALID_TEAM_LABEL'):
            winner_identity(row, payload)

    def test_soccer_extra_time_is_not_three_way(self):
        row, payload, _ = fixture(); row.update(league='MLS', event_id='MLS:401871070')
        payload['leagues'] = [{'id': '770', 'slug': 'usa.1'}]
        payload['events'][0]['competitions'][0]['status']['type']['name'] = 'STATUS_FINAL_OT'
        with self.assertRaisesRegex(ValueError, 'PROVIDER_NOT_PLAYED_FINAL'):
            winner_identity(row, payload)

if __name__ == '__main__': unittest.main()
