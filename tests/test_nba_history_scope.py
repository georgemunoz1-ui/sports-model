import copy
import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from scripts.nba_history_scope import (BASE, build_scope, current_season, history_urls,
                                       history_sources, load_scope, verify_current_events)
from scripts.prepare_initial_baselines import histories


class NbaScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cutoff = dt.datetime(2026, 10, 22, 6, 31, tzinfo=dt.timezone.utc)

    def capture(self, payload, kind, url, *, cutoff=None):
        cutoff = cutoff or self.cutoff
        raw = json.dumps(payload, sort_keys=True).encode(); sha = hashlib.sha256(raw).hexdigest()
        (self.root / (sha+'.json')).write_bytes(raw)
        return {'league': 'nba', 'kind': kind, 'url': url, 'raw_path': sha+'.json', 'raw_sha256': sha,
                'status': 'CAPTURED', 'http_status': 200,
                'requested_at_utc': (cutoff-dt.timedelta(minutes=2)).isoformat(),
                'retrieved_at_utc': (cutoff-dt.timedelta(minutes=1)).isoformat()}

    def fixture(self, year=2027, cutoff=None):
        cutoff = cutoff or self.cutoff
        self.event = {'id': 'fixture', 'date': (cutoff+dt.timedelta(hours=12)).isoformat(),
                      'season': {'year': year, 'type': 2, 'slug': 'regular-season'}}
        self.schedule = self.capture({'events': [self.event]}, 'schedule', BASE+'/scoreboard?dates='+cutoff.strftime('%Y%m%d'), cutoff=cutoff)
        (self.root/'report.json').write_text(json.dumps({'sources': [self.schedule]}))
        directory = {'sports': [{'leagues': [{'teams': [{'team': {'id': str(i)}} for i in range(1,31)]}]}]}
        self.directory = self.capture(directory, 'team_directory', BASE+'/teams?limit=1000', cutoff=cutoff)
        return build_scope(self.root, self.root, self.directory, cutoff.isoformat())

    def history_bundle(self, scope):
        rows = []
        for url in sorted(history_urls(scope)):
            parsed = urlparse(url); team = parsed.path.split('/teams/')[1].split('/')[0]
            year = int(parse_qs(parsed.query)['season'][0])
            payload = {'team': {'id': team}, 'requestedSeason': {'year': year}, 'events': []}
            rows.append(self.capture(payload, 'team_season_schedule', url))
        report = {'sources': [self.directory]+rows, 'nba_acquisition_scope_sha256': scope['scope_sha256'],
                  'pending_requests': 0, 'status': 'COMPLETE', 'action_authority': False}
        return report

    def test_october_uses_provider_end_year_not_wall_year(self):
        scope = self.fixture()
        self.assertEqual(scope['last_provider_season'], 2027)
        self.assertEqual(len(history_urls(scope)), 210)
        self.assertTrue(any('season=2027&' in u for u in history_urls(scope)))
        self.assertFalse(any('season=2028&' in u for u in history_urls(scope)))

    def test_historical_april_scope_does_not_use_today_or_future_season(self):
        cutoff = dt.datetime(2026,4,12,6,31,tzinfo=dt.timezone.utc)
        scope = self.fixture(2026, cutoff)
        self.assertEqual(scope['last_provider_season'], 2026)
        self.assertEqual(len(history_urls(scope)), 180)

    def test_january_keeps_same_provider_year(self):
        cutoff = dt.datetime(2027,1,2,6,31,tzinfo=dt.timezone.utc)
        self.assertEqual(self.fixture(2027, cutoff)['last_provider_season'], 2027)

    def test_no_current_events_means_unproven_not_guess(self):
        self.fixture()
        old = copy.deepcopy(self.event); old['date']='2026-04-13T00:30:00Z'
        rec=self.capture({'events':[old]},'schedule',BASE+'/scoreboard?dates=20260413')
        (self.root/'report.json').write_text(json.dumps({'sources':[rec]}))
        with self.assertRaisesRegex(ValueError, 'UNPROVEN'):
            current_season(self.root, self.cutoff)

    def test_capture_after_historical_cutoff_is_rejected(self):
        self.fixture()
        with self.assertRaisesRegex(ValueError, 'NOT_AVAILABLE'):
            current_season(self.root, self.cutoff-dt.timedelta(hours=1))

    def test_missing_2027_request_fails_census(self):
        scope=self.fixture(); report=self.history_bundle(scope)
        report['sources']=[r for r in report['sources'] if 'season=2027&' not in r['url']]
        with self.assertRaisesRegex(ValueError,'REQUEST_CENSUS'):
            history_sources(self.root,report,scope,self.cutoff)

    def test_complete_scope_preparation_accepts_2027_requests(self):
        scope=self.fixture(); report=self.history_bundle(scope)
        (self.root/'report.json').write_text(json.dumps(report))
        games, receipts, _=histories(self.root,'nba',cutoff=self.cutoff,nba_acquisition_scope=scope)
        self.assertEqual(len(receipts),210)
        self.assertEqual(games,[])  # Acquisition is verified; no invented played games.

    def test_scope_tamper_is_rejected(self):
        scope=self.fixture(); scope['last_provider_season']=2026
        path=self.root/'scope.json';path.write_text(json.dumps(scope))
        with self.assertRaisesRegex(ValueError,'DIGEST_MISMATCH'):load_scope(path)

    def test_current_event_packet_must_match_raw_source(self):
        self.fixture()
        packet={'fixture':{'event':self.event,'source_sha256':self.schedule['raw_sha256'],
                           'retrieved_at_utc':self.schedule['retrieved_at_utc']}}
        verify_current_events(self.root,packet,self.cutoff)
        packet['fixture']['event']={**self.event,'id':'different'}
        with self.assertRaisesRegex(ValueError,'SOURCE_BINDING'):
            verify_current_events(self.root,packet,self.cutoff)


if __name__=='__main__':unittest.main()
