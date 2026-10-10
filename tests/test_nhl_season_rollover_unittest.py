"""Offline synthetic boundary/replay checks; fixture values are not forecasts."""
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from scripts import prepare_initial_baselines as baseline
from scripts.nhl_history_applicability import BASE, EXCLUDED, SCOPE_SHA256, TEAM_IDS, history_urls, receipt
from models.current.common import save
from scripts.generate_card_force import load_adapter
from pipelines.cards.selection import SelectionError

ROOT = Path(__file__).resolve().parents[1]
SCOPE = ROOT / 'research/nhl-season-scope-2026-27-v2.json'
CUTOFF = '2026-10-10T01:00:00+00:00'


def event(year=2027, team='1', eid='1', final=True, kind=2, date=None, win=True):
    return {'id': eid, 'date': date or f'{year-1}-10-07T23:00:00Z',
            'season': {'year': year, 'slug': 'regular-season' if kind == 2 else 'pre-season'},
            'seasonType': {'id': str(kind), 'name': 'Regular Season' if kind == 2 else 'Preseason'},
            'competitions': [{'neutralSite': False, 'status': {'type': {'completed': final, 'state': 'post' if final else 'pre'}},
                             'competitors': [{'homeAway': 'home', 'team': {'id': team, 'displayName': 'Team ' + team}, 'score': 3 if win else 2},
                                             {'homeAway': 'away', 'team': {'id': '2' if team == '1' else '1', 'displayName': 'Opponent'}, 'score': 2 if win else 3}]}]}


class SeasonRolloverTests(unittest.TestCase):
    def setUp(self):
        self.scope = baseline.load_season_scope(SCOPE)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def raw(self, root, value):
        raw = json.dumps(value, sort_keys=True).encode()
        digest = hashlib.sha256(raw).hexdigest()
        (root / 'raw').mkdir(exist_ok=True, parents=True)
        path = 'raw/' + digest + '.json'
        (root / path).write_bytes(raw)
        return {'raw_path': path, 'raw_sha256': digest}

    def source(self, root, value, url, kind):
        return {'league': 'nhl', 'kind': kind, 'url': url, 'status': 'CAPTURED', 'http_status': 200,
                'requested_at_utc': '2026-10-10T00:58:00Z', 'retrieved_at_utc': '2026-10-10T00:59:00Z', **self.raw(root, value)}

    def history(self):
        root = self.root / 'history'
        sources = []
        for i, url in enumerate(sorted(history_urls())):
            team = urlparse(url).path.split('/teams/')[1].split('/')[0]
            year = int(parse_qs(urlparse(url).query)['season'][0])
            e = event(year, team, f'{year}-{team}', win=bool(i % 2))
            sources.append(self.source(root, {'team': {'id': team}, 'requestedSeason': {'year': year}, 'events': [e]}, url, 'team_season_schedule'))
        report = {'schema': 'nhl.atomic_history_capture.v1', 'sources': sources, 'season_scope_sha256': SCOPE_SHA256,
                  'inapplicable_team_seasons': copy.deepcopy(self.scope['nonexistent_team_seasons']), 'action_authority': False}
        self.write_report(root, report)
        return root, report

    def current(self):
        root = self.root / 'current'
        e = event(final=False, date='2026-10-11T01:00:00Z')
        sources = [self.source(root, {'events': [e] if day == '20261011' else [], 'day': day},
                               BASE + '/scoreboard?dates=' + day + '&limit=1000', 'schedule') for day in ['20261009', '20261010', '20261011']]
        r = sources[-1]
        events = {'1': {'event': e, 'source_sha256': r['raw_sha256'], 'retrieved_at_utc': r['retrieved_at_utc']}}
        report = {'schema': 'nhl.atomic_current_capture.v1', 'sources': sources, 'season_scope_sha256': SCOPE_SHA256,
                  'covered_dates': ['2026-10-10'], 'date': '2026-10-10', 'timezone': 'America/Los_Angeles', 'action_authority': False}
        (root / 'events.json').write_text(json.dumps({'nhl': events}))
        self.write_report(root, report)
        return root, report, events

    def write_report(self, root, report):
        (root / 'report.json').write_text(json.dumps(report))
        (root / 'manifest.json').write_text(json.dumps({str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and p.name != 'manifest.json'}))

    def history_error(self, alter, reason):
        root, report = self.history()
        alter(report)
        self.write_report(root, report)
        with self.assertRaisesRegex(ValueError, reason):
            baseline.histories(root, 'nhl', self.scope, dt.datetime.fromisoformat(CUTOFF))

    def mutate_payload(self, report, mutate):
        row = report['sources'][0]
        root = self.root / 'history'
        data = json.loads((root / row['raw_path']).read_text())
        mutate(data)
        row.update(self.raw(root, data))

    def test_provider_end_year_preserved(self):
        root, _ = self.history()
        games, sources, _ = baseline.histories(root, 'nhl', self.scope)
        self.assertEqual(len(sources), 219)
        self.assertEqual({r['season'] for r in games}, set(range(2021, 2028)))
        self.assertTrue(games[-1]['start_time_utc'].startswith('2026-10'))
        self.assertEqual(games[-1]['season'], 2027)

    def test_legacy_scope_still_rejects_2027(self):
        root, _ = self.history()
        with self.assertRaisesRegex(ValueError, 'SEASON_OUT_OF_SCOPE'):
            baseline.histories(root, 'nhl')

    def test_exact_five_exclusions_and_distinct_arizona(self):
        self.assertEqual(EXCLUDED, {('124292', 2021), ('129764', 2021), ('129764', 2022), ('129764', 2023), ('129764', 2024)})
        self.assertEqual(len(TEAM_IDS), 32)
        self.assertNotIn('24', TEAM_IDS)
        self.assertIn(BASE + '/teams/129764/schedule?season=2025&seasontype=2', history_urls())
        state = {}
        from models.current.baseline import update
        for team in ('24', '129764'):
            update(state, baseline.parse(event(team=team), 'nhl', True))
        self.assertEqual(state['24']['n'], 1)
        self.assertEqual(state['129764']['n'], 1)

    def test_scope_mutations_require_separate_review(self):
        for key, value in [('last_provider_season', 2028), ('later_audit_provider_season', 2027), ('nonexistent_team_seasons', []), ('action_authority', True), ('team_identity_policy', 'ALIAS_ARIZONA')]:
            with self.subTest(key=key):
                scope = copy.deepcopy(self.scope); scope[key] = value
                path = self.root / 'scope.json'; path.write_text(json.dumps(scope))
                with self.assertRaisesRegex(ValueError, 'UNREVIEWED_NHL_SEASON_SCOPE'):
                    baseline.load_season_scope(path)

    def test_regular_and_preseason_remain_separate(self):
        self.assertIsNotNone(baseline.parse(event(), 'nhl', True))
        self.assertIsNone(baseline.parse(event(kind=1), 'nhl', True))
        self.assertIsNone(baseline.parse(event(kind=1), 'nhl'))

    def test_missing_single_applicable_request_refused(self):
        self.history_error(lambda r: r['sources'].pop(), 'APPLICABLE_HISTORY_REQUEST_CENSUS')

    def test_duplicate_receipt_cannot_replace_missing_request(self):
        self.history_error(lambda r: r['sources'].__setitem__(-1, copy.deepcopy(r['sources'][0])), 'APPLICABLE_HISTORY_REQUEST_CENSUS')

    def test_new_future_provider_season_refused(self):
        self.history_error(lambda r: r['sources'][0].__setitem__('url', r['sources'][0]['url'].replace('2021', '2028')), 'APPLICABLE_HISTORY_REQUEST_CENSUS')

    def test_current_fallback_payload_cannot_stand_for_history(self):
        self.history_error(lambda r: self.mutate_payload(r, lambda j: j.__setitem__('requestedSeason', {'year': 2027})), 'APPLICABLE_PAYLOAD_IDENTITY')

    def test_empty_payload_still_requires_requested_season_identity(self):
        def change(report):
            self.mutate_payload(report, lambda j: (j.__setitem__('events', []), j.pop('requestedSeason')))
        self.history_error(change, 'APPLICABLE_PAYLOAD_IDENTITY')

    def test_event_provider2027_never_relabeled2026(self):
        self.history_error(lambda r: self.mutate_payload(r, lambda j: j['events'][0]['season'].__setitem__('year', 2027)), 'REQUESTED_SEASON_MISMATCH')

    def test_event_must_involve_requested_team(self):
        self.history_error(lambda r: self.mutate_payload(r, lambda j: j['events'][0]['competitions'][0]['competitors'][0]['team'].__setitem__('id', '999')), 'HISTORY_EVENT_TEAM_IDENTITY')

    def test_conflicting_provider_event_copies_refused(self):
        root, report = self.history()
        first = next(r for r in report['sources'] if '/teams/1/' in r['url'] and 'season=2021' in r['url'])
        second = next(r for r in report['sources'] if '/teams/2/' in r['url'] and 'season=2021' in r['url'])
        data = json.loads((root / first['raw_path']).read_text())
        conflicting = copy.deepcopy(data['events'][0])
        conflicting['competitions'][0]['competitors'][0]['score'] = 8
        second.update(self.raw(root, {'team': {'id': '2'}, 'requestedSeason': {'year': 2021}, 'events': [conflicting]}))
        self.write_report(root, report)
        with self.assertRaisesRegex(ValueError, 'PROVIDER_ID_REVISION'):
            baseline.histories(root, 'nhl', self.scope)

    def test_receipt_hash_tamper_refused(self):
        self.history_error(lambda r: r['sources'][0].__setitem__('raw_sha256', '0' * 64), 'SOURCE_RAW_DIGEST_MISMATCH')

    def test_failed_applicable_request_not_excluded(self):
        self.history_error(lambda r: r['sources'][0].__setitem__('status', 'FAILED'), 'SOURCE_CAPTURE_INCOMPLETE')

    def test_arbitrary_exclusion_refused(self):
        self.history_error(lambda r: r['inapplicable_team_seasons'].append({'team_id': '1', 'provider_season': 2021}), 'INAPPLICABLE_SCOPE_MISMATCH')

    def test_exact_receipt_boundaries(self):
        root, report = self.history(); row = report['sources'][0]
        for change, reason in [({'requested_at_utc': None}, 'EXACT_SOURCE_TIMESTAMP_REQUIRED'),
                               ({'requested_at_utc': '2026-10-10T01:00:00Z'}, 'SOURCE_RECEIPT_CLOCK_ORDER'),
                               ({'requested_at_utc': '2026-10-10T00:58:00'}, 'SOURCE_TIMEZONE_REQUIRED'),
                               ({'capture_interval_utc': ['a', 'b']}, 'EXACT_SOURCE_RECEIPT_REQUIRED'),
                               ({'retrieved_at_utc': '2026-10-10T01:01:00Z'}, 'SOURCE_NOT_AVAILABLE_AND_CURRENT_AT_CUTOFF'),
                               ({'requested_at_utc': '2026-10-09T18:58:00Z', 'retrieved_at_utc': '2026-10-09T18:59:59Z'}, 'SOURCE_NOT_AVAILABLE_AND_CURRENT_AT_CUTOFF'),
                               ({'raw_path': '../escape.json'}, 'SOURCE_PATH_ESCAPE')]:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, reason):
                receipt(root, {**row, **change}, dt.datetime.fromisoformat(CUTOFF))
        receipt(root, {**row, 'requested_at_utc': '2026-10-09T18:58:00Z', 'retrieved_at_utc': '2026-10-09T19:00:00Z'}, dt.datetime.fromisoformat(CUTOFF))

    def test_same_and_previous_utc_day_stay_embargoed(self):
        games = [baseline.parse(event(eid=str(i), date=f'2026-10-0{i}T23:00:00Z'), 'nhl', True) for i in [7, 8, 9]]
        _, state, used = baseline.causal_rows(games, 3, '2026-10-09T23:30:00Z')
        self.assertEqual(used, ['NHL:7']); self.assertEqual(state['1']['n'], 1)

    def test_current_source_and_timestamp_binding(self):
        root, report, events = self.current()
        baseline.verify_current_sources(root, 'nhl', report, events, dt.datetime.fromisoformat(CUTOFF))
        events['1']['retrieved_at_utc'] = CUTOFF
        with self.assertRaisesRegex(ValueError, 'CURRENT_EVENT_RECEIPT_BINDING'):
            baseline.verify_current_sources(root, 'nhl', report, events)

    def test_fabricated_or_truncated_current_event_refused(self):
        root, report, events = self.current()
        with self.assertRaisesRegex(ValueError, 'CURRENT_SOURCE_EVENT_COVERAGE'):
            baseline.verify_current_sources(root, 'nhl', report, {})
        events['1']['event']['season']['year'] = 2026
        with self.assertRaisesRegex(ValueError, 'CURRENT_EVENT_SOURCE_BINDING'):
            baseline.verify_current_sources(root, 'nhl', report, events)

    def test_pacific_date_edge_requires_adjacent_scoreboards(self):
        root, report, events = self.current(); report['sources'].pop(0)
        with self.assertRaisesRegex(ValueError, 'CURRENT_SLATE_TIMEZONE_COVERAGE'):
            baseline.verify_current_sources(root, 'nhl', report, events)

    def test_synthetic_packages_replay_exactly(self):
        history, _ = self.history(); current, _, _ = self.current()
        for name in ('one', 'two'):
            baseline.prepare(history, current, self.root / name, leagues=['nhl'], season_scope_path=SCOPE, as_of_utc=CUTOFF)
        for filename in ('evaluation.json', 'evaluation_model.json', 'package.json'):
            self.assertEqual((self.root / 'one/nhl' / filename).read_bytes(), (self.root / 'two/nhl' / filename).read_bytes())
        package = json.loads((self.root / 'one/nhl/package.json').read_text())
        self.assertEqual(package['ttl_hours'], 6)
        self.assertEqual(package['model_lineage']['embargo'], 'PREVIOUS_UTC_DAY_EXCLUDED')
        self.assertEqual(package['covered_dates'], ['2026-10-10'])
        self.assertEqual(package['events'][0]['season'], 2027)
        self.assertFalse(package['action_authority'])
        self.assertEqual(package['model_lineage']['evaluation']['training_seasons'], [2021, 2022, 2023, 2024])

    def test_actual_collector_census_with_synthetic_transport(self):
        from scripts import capture_team_histories as capture
        from scripts import nhl_atomic_capture as atomic
        def transport(spec):
            data = {'team': {'id': spec['team_id']}, 'requestedSeason': {'year': spec['provider_season']}, 'events': []}
            return atomic.Response(json.dumps(data).encode(), 200, {}, spec['url'])
        out = self.root / 'captured'
        original = atomic.collect_history
        def collect(*args, **kwargs):
            return original(*args, **kwargs, transport=transport, clock=lambda: CUTOFF)
        with patch.object(atomic, 'collect_history', side_effect=collect), patch('sys.argv', ['capture_team_histories.py', '--league', 'nhl', '--season-scope', str(SCOPE), '--output', str(out)]):
            capture.main()
        games, receipts, _ = baseline.histories(out, 'nhl', self.scope)
        self.assertEqual(len(receipts), 219); self.assertEqual(games, [])
        self.assertEqual(len(list((out / 'journal').rglob('*.json'))), 219)
        with patch.object(atomic, 'collect_history', side_effect=collect), patch('sys.argv', ['capture_team_histories.py', '--league', 'nhl', '--season-scope', str(SCOPE), '--output', str(out), '--resume']):
            capture.main()
        self.assertEqual(len(list((out / 'journal').rglob('*.json'))), 219)

    def test_future_cutoff_refused(self):
        with self.assertRaisesRegex(ValueError, 'FUTURE_PACKAGE_CUTOFF'):
            baseline.preparation_cutoff((dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat())

    def test_old_artifacts_cannot_be_overwritten(self):
        path = self.root / 'artifact.json'; save(path, {'season': 2026}); before = path.read_bytes()
        with self.assertRaises(FileExistsError):save(path, {'season': 2027})
        self.assertEqual(path.read_bytes(), before)

    def test_research_default_stays_unselected(self):
        import os
        with patch.dict(os.environ):
            os.environ.pop('SPORTS_INITIAL_BASELINES', None)
            with self.assertRaises(SelectionError):load_adapter('nhl')


if __name__ == '__main__':
    unittest.main()
