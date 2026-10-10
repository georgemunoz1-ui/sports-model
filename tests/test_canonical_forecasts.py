"""Synthetic software tests, never prospective performance evidence."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from scripts import canonical_forecasts as c

class CanonicalForecastTests(unittest.TestCase):
    def setUp(self):
        self.source_check = patch.object(c, 'verify_result_source', return_value=True)
        self.source_check.start(); self.addCleanup(self.source_check.stop)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.root = self.base / 'canonical'
        self.path = self.base / 'card' / 'diagnostic_card.json'; self.path.parent.mkdir()
        self.card = {'league': 'NBA', 'card_date': '2026-10-20',
            'requested_as_of_utc': '2026-10-20T10:00:00Z', 'generated_at_utc': '2026-10-20T10:01:00Z',
            'pit_provenance': {'pit_status': 'PIT_ORDERED', 'max_source_timestamp_utc': '2026-10-20T09:59:00Z',
                'source_fetches': [{'fetched_at_utc': '2026-10-20T09:59:00Z'}]},
            'action_authority': False, 'forecasts': []}
        self.artifact = {'id': 1, 'digest': 'sha256:'+'a'*64, 'run_id': 100, 'created_at': '2026-10-20T10:02:00Z'}
        self.add_event('NBA:1')

    def add_event(self, event):
        draws = np.array([1, 0, 1, 1], dtype='u1')
        path = self.path.parent / 'draws' / event.replace(':', '_'); path.mkdir(parents=True)
        np.save(path / 'winner_draws.npy', draws, allow_pickle=False)
        self.card['forecasts'].append({'event_id': event, 'model_id': 'test.winner.v1', 'home_team': 'HOME', 'away_team': 'AWAY',
            'start_time_utc': '2026-10-20T18:00:00Z', 'forecast_status': 'FORECAST_GENERATED', 'model_winner': 'HOME',
            'analytic_p': .7, 'stochastic_sim_p': .75, 'input_snapshot_hash': 'test-input', 'model_state_config_hash': 'test-model',
            'simulation': {'binary': {'count': 4, 'seed': 1, 'sha256': hashlib.sha256(draws.tobytes()).hexdigest(), 'home_win_probability': .75}},
            'grading': {'eligible_for_prospective_grading': False, 'eligibility_reason': 'MLB_CALIBRATION_ONLY'}, 'action_authority': False})

    def register(self, now='2026-10-20T10:03:00Z'):
        self.path.write_text(json.dumps(self.card))
        with patch.object(c, 'utcnow', return_value=now):
            return c.register(self.path, self.root, 100, self.artifact)

    def results(self, event='NBA:1', **kw):
        return {'league': self.card['league'], 'event_id': event, 'home_team': 'HOME', 'away_team': 'AWAY', 'status': 'FINAL',
            'home_score': 100, 'away_score': 90, 'start_time_utc': self.card['forecasts'][0]['start_time_utc'], 'source_sha256': 'b'*64, 'source_url': 'https://example.test/fixture',
            'fetched_at_utc': '2026-10-20T22:00:00Z', **kw}

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file() and p.suffix != '.lock'}

    def test_all_five_leagues_registration_grade_and_replay(self):
        for league in sorted(c.LEAGUES):
            with self.subTest(league=league):
                self.root = self.base / league; self.card['league'] = league
                self.assertEqual(self.register()['status'], 'REGISTERED')
                frozen = self.path.read_bytes()
                self.assertEqual(c.grade(self.root, [self.results()])['added_count'], 1)
                before = self.snapshot()
                self.assertEqual(self.register(now='2026-10-21T00:00:00Z')['status'], 'ALREADY_REGISTERED')
                self.assertEqual(c.grade(self.root, [self.results()])['added_count'], 0)
                self.assertEqual(before, self.snapshot()); self.assertEqual(frozen, self.path.read_bytes())
                summary = json.loads((self.root / 'summary.json').read_text())
                self.assertEqual(summary['graded_count'], 1); self.assertEqual(summary['certified_calibration_count'], 0)
                self.assertEqual(len(summary['groups']), 2)
                self.assertAlmostEqual(sorted(g['brier'] for g in summary['groups'].values())[0], .0625)

    def test_late_registration_refused_without_registry(self):
        for stamp in ['2026-10-20T18:00:00Z', '2026-10-21T00:00:00Z']:
            with self.assertRaisesRegex(ValueError, 'NOT_PREGAME'): self.register(stamp)
        self.assertFalse((self.root / 'registry.json').exists())

    def test_missing_unordered_future_sources_rejected(self):
        for key, value in [('pit_status', 'PIT_UNKNOWN'), ('source_fetches', []), ('max_source_timestamp_utc', '2026-10-20T10:05:00Z')]:
            card = copy.deepcopy(self.card)
            self.card['pit_provenance'][key] = value
            with self.assertRaises(ValueError): self.register()
            self.assertFalse((self.root / 'registry.json').exists()); self.card = card

    def test_source_unverified_never_enters_certified_cohort(self):
        self.register(); c.grade(self.root, [self.results()])
        receipt = next(iter(json.loads((self.root / 'registry.json').read_text())['forecasts'].values()))
        grade = c.load_ledger(self.root / 'ledger.jsonl')[0]
        for value in [receipt, grade]:
            self.assertFalse(value['certified_calibration_eligible'])
            self.assertEqual(value['evaluation_cohort'], 'PROSPECTIVE_RESEARCH_SOURCE_UNVERIFIED')
        self.assertEqual(receipt['unsupported_products'], ['cover', 'total'])

    def test_market_action_nested_refused(self):
        self.card['forecasts'][0]['diagnostics'] = {'nested': {'market_features_used': True}}
        with self.assertRaisesRegex(ValueError, 'FIREWALL'): self.register()

    def test_draw_missing_tamper_count_or_probability_refused(self):
        path = self.path.parent / 'draws/NBA_1/winner_draws.npy'
        for draws in [np.array([1,1], dtype='u1'), np.array([0,0,0,0], dtype='u1')]:
            np.save(path, draws)
            with self.assertRaises(ValueError): self.register()
        path.unlink()
        with self.assertRaises(OSError): self.register()

    def test_invalid_probability_boolean_nan_refused(self):
        for value in [True, float('nan'), 1.1, -.1]:
            self.card['forecasts'][0]['analytic_p'] = value
            with self.assertRaises(ValueError): self.register()

    def test_mc_only_is_distinct_not_invented_analytic(self):
        row = self.card['forecasts'][0]; row['analytic_p'] = None; row['probability_estimator'] = 'MONTE_CARLO_ONLY'
        self.register(); c.grade(self.root, [self.results()])
        self.assertEqual(set(c.load_ledger(self.root / 'ledger.jsonl')[0]['scores']), {'simulation'})

    def test_partial_then_final_appends_and_retains_prefix(self):
        self.add_event('NBA:2'); self.register()
        self.assertEqual(c.grade(self.root, [self.results()])['added_count'], 1)
        prefix = (self.root / 'ledger.jsonl').read_bytes()
        self.assertEqual(c.grade(self.root, [self.results(), self.results('NBA:2')])['added_count'], 1)
        self.assertTrue((self.root / 'ledger.jsonl').read_bytes().startswith(prefix))

    def test_conflicting_final_batch_never_mutates(self):
        self.add_event('NBA:2'); self.register(); c.grade(self.root, [self.results()]); before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'CONFLICT'):
            c.grade(self.root, [self.results(home_score=80), self.results('NBA:2')])
        self.assertEqual(before, self.snapshot())

    def test_live_tie_wrong_teams_and_invalid_scores(self):
        self.register()
        self.assertEqual(c.grade(self.root, [self.results(status='LIVE')])['added_count'], 0)
        r = c.grade(self.root, [self.results(home_score=90)])
        self.assertEqual(r['excluded'][0]['reason'], 'UNSUPPORTED_TIE')
        for kw in [{'home_team':'WRONG'}, {'home_score':True}, {'home_score':-1}, {'start_time_utc':'2026-10-21T18:00:00Z'}, {'fetched_at_utc':'2026-10-20T09:00:00Z'}]:
            before = self.snapshot()
            with self.assertRaises(ValueError): c.grade(self.root, [self.results(**kw)])
            self.assertEqual(before, self.snapshot())

    def test_receipt_or_draw_tamper_rejected(self):
        self.register()
        registry = self.root / 'registry.json'; value = json.loads(registry.read_text())
        next(iter(value['forecasts'].values()))['model_id'] = 'other'
        registry.write_text(json.dumps(value)); before = self.snapshot()
        with self.assertRaises(ValueError): c.grade(self.root, [self.results()])
        self.assertEqual(before, self.snapshot())

    def test_refresh_cannot_replace_first_event_model(self):
        self.register(); before = self.snapshot()
        self.card['forecasts'][0]['analytic_p'] = .8
        self.assertEqual(self.register()['status'], 'ALREADY_REGISTERED'); self.assertEqual(before, self.snapshot())

    def test_independent_models_never_pooled(self):
        self.register(); self.card['forecasts'][0]['model_id'] = 'challenger.v1'; self.register()
        c.grade(self.root, [self.results()]); summary=json.loads((self.root/'summary.json').read_text())
        self.assertEqual(summary['graded_count'], 2); self.assertEqual(len(summary['groups']), 4)

    def test_recovery_after_append_before_summary(self):
        self.register(); original = c.atomic_json
        def fail(path,value):
            if Path(path).name == 'summary.json': raise OSError('synthetic crash')
            return original(path,value)
        with patch.object(c,'atomic_json',side_effect=fail), self.assertRaises(OSError): c.grade(self.root,[self.results()])
        prefix=(self.root/'ledger.jsonl').read_bytes(); c.grade(self.root,[self.results()])
        self.assertEqual(prefix,(self.root/'ledger.jsonl').read_bytes())
        self.assertEqual(json.loads((self.root/'summary.json').read_text())['graded_count'],1)

    def test_retained_provider_bytes_end_to_end_and_tamper(self):
        from scripts import canonical_results as r
        self.source_check.stop()
        self.card = json.loads(json.dumps(self.card).replace('2026-10-20', '2026-09-20'))
        self.artifact['created_at'] = '2026-09-20T10:02:00Z'
        self.register('2026-09-20T10:03:00Z')
        f = {**self.card['forecasts'][0], 'league': 'NBA'}
        payload = {'events': [{'id': '1', 'date': f['start_time_utc'], 'season': {'year': 2026},
            'competitions': [{'competitors': [
                {'homeAway': 'home', 'team': {'displayName': 'HOME'}, 'score': '100'},
                {'homeAway': 'away', 'team': {'displayName': 'AWAY'}, 'score': '90'}],
                'status': {'period': 4, 'type': {'completed': True, 'state': 'post', 'name': 'STATUS_FINAL'}}}]}]}
        results = r.acquire_results([f], self.base/'sources', lambda url: json.dumps(payload).encode())
        self.assertEqual(c.grade(self.root, results)['added_count'], 1)
        before = self.snapshot()
        Path(results[0]['raw_path']).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'RAW_HASH_MISMATCH'): c.grade(self.root, results)
        self.assertEqual(before, self.snapshot())

    def test_all_five_provider_registration_to_grade_routes(self):
        from scripts import canonical_results as r
        self.source_check.stop()
        template = json.loads(json.dumps(self.card).replace('2026-10-20', '2026-09-20'))
        self.artifact['created_at'] = '2026-09-20T10:02:00Z'
        for league in sorted(c.LEAGUES):
            with self.subTest(provider=league):
                self.card = copy.deepcopy(template); self.card['league'] = league
                self.root = self.base / ('provider-' + league)
                row = self.card['forecasts'][0]
                eid = '2026_03_AWAY_HOME' if league == 'NFL' else ('WNBA:1022600001' if league == 'WNBA' else league + ':1')
                row['event_id'] = eid
                folder = self.path.parent / 'draws' / eid.replace(':', '_'); folder.mkdir(exist_ok=True)
                np.save(folder/'winner_draws.npy', np.array([1,0,1,1], dtype='u1'))
                self.register('2026-09-20T10:03:00Z')
                f = {**row, 'league': league}
                if league == 'WNBA':
                    payload = {'game': {'gameId': '1022600001', 'gameTimeUTC': row['start_time_utc'], 'gameStatus': 3, 'period': 4,
                        'homeTeam': {'teamTricode': 'HOME', 'score': 100}, 'awayTeam': {'teamTricode': 'AWAY', 'score': 90}}}
                else:
                    payload = {'events': [{'id': '1', 'date': row['start_time_utc'], 'season': {'year': 2026}, 'week': {'number': 3},
                        'competitions': [{'competitors': [
                            {'homeAway': 'home', 'team': {'displayName': 'HOME', 'abbreviation': 'HOME'}, 'score': '100'},
                            {'homeAway': 'away', 'team': {'displayName': 'AWAY', 'abbreviation': 'AWAY'}, 'score': '90'}],
                            'status': {'period': 4, 'type': {'completed': True, 'state': 'post', 'name': 'STATUS_FINAL'}}}]}]}
                results = r.acquire_results([f], self.base/('source-'+league), lambda url: json.dumps(payload).encode())
                self.assertEqual(results[0]['status'], 'FINAL', results)
                self.assertEqual(c.grade(self.root, results)['added_count'], 1)
                before = self.snapshot()
                self.assertEqual(c.grade(self.root, results)['added_count'], 0)
                self.assertEqual(before, self.snapshot())
                self.assertEqual(json.loads((self.root/'summary.json').read_text())['certified_calibration_count'], 0)

    def test_concurrent_grades_append_once(self):
        self.register(); result=self.base/'results.json'; result.write_text(json.dumps([self.results()]))
        ps=[subprocess.Popen([sys.executable,'-c','from scripts import canonical_forecasts as c; c.verify_result_source=lambda result: True; c.main()','grade','--root',str(self.root),'--results',str(result),'--report',str(self.base/f'report{i}.json')],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for i in range(2)]
        for p in ps:
            out,err=p.communicate(timeout=20); self.assertEqual(p.returncode,0,out+err)
        self.assertEqual(len(c.load_ledger(self.root/'ledger.jsonl')),1)

if __name__ == '__main__': unittest.main()
