import copy
import json
import tempfile
import unittest
from pathlib import Path

from harness.current_sports_data import (available_before, immutable_json, league_status,
    local_date, parse_sports_extract, reconcile, slate_clock)


class CurrentSportsDataTests(unittest.TestCase):
    def setUp(self):
        self.clock = slate_clock('2026-09-14T15:00:00Z')
        self.rec = {'sha256': 'a'*64, 'retrieved_at': '2026-09-14T15:00:00+00:00'}

    def test_today_uses_local_timezone_not_utc_slice(self):
        c = slate_clock('2026-09-15T00:15:00Z')
        self.assertEqual(c['slate_date'], '2026-09-14')
        self.assertEqual(local_date('2026-09-15T00:15:00Z'), '2026-09-14')

    def test_requires_explicit_historical_request(self):
        with self.assertRaisesRegex(ValueError, 'HISTORICAL'):
            slate_clock('2026-09-14T15:00:00Z', '2026-08-17')
        self.assertEqual(slate_clock('2026-09-14T15:00:00Z', '2026-08-17', historical=True)['information_regime'], 'historical_reconstruction')

    def test_dst_window_is_not_always_24_hours(self):
        from harness.current_sports_data import instant
        c = slate_clock('2026-11-01T12:00:00Z')
        self.assertEqual((instant(c['window_end_utc']) - instant(c['window_start_utc'])).total_seconds(), 25*3600)

    def test_naive_time_rejected(self):
        with self.assertRaisesRegex(ValueError, 'TIMEZONE'):
            slate_clock('2026-09-14T15:00:00')

    def test_backfilled_results_are_not_earlier_pregame_inputs(self):
        self.assertFalse(available_before(self.rec, '2026-09-13T12:00:00Z'))

    def test_no_games_without_coverage_is_unknown(self):
        s = league_status('wnba', self.clock, [], {}, {})
        self.assertEqual(s['schedule_status'], 'UNACQUIRED')
        self.assertFalse(s['forecast_ready'])

    def test_pause_and_stale_sources_are_distinct(self):
        cov = {'source_sha256': 'a'*64, 'verified_at': '2026-09-14T14:00:00Z', 'complete': True,
               'date_from': '2026-08-31', 'date_to': '2026-09-16', 'expected_slate_count': 0,
               'season': 2026, 'phase': 'FIBA_BREAK'}
        self.assertEqual(league_status('wnba', self.clock, [], cov, {})['schedule_status'], 'VERIFIED_EMPTY')
        cov['verified_at'] = '2026-08-10T14:00:00Z'
        self.assertEqual(league_status('wnba', self.clock, [], cov, {})['schedule_status'], 'UNACQUIRED')

    def test_nfl_week_is_explicit_calendar_metadata(self):
        cov = {'date_from':'2026-09-09', 'date_to':'2026-09-14', 'season':2026, 'league_week':1}
        self.assertEqual(league_status('nfl', self.clock, [], cov, {})['league_week'], 1)
        self.assertIsNone(league_status('nfl', slate_clock('2026-09-17T15:00:00Z'), [], cov, {})['league_week'])

    def test_parser_preserves_doubleheader(self):
        text = '\n'.join('Cubs (CHC) @ Reds (CIN) on Sunday, Sep 13, 2026 at '+t+' PDT. Final score: CHC 2 - CIN 1' for t in ['10:00 AM','04:00 PM'])
        events = parse_sports_extract(text, 'mlb', self.rec)
        rows, conflicts = reconcile(events + events)
        self.assertEqual(len(rows), 2)
        self.assertEqual(conflicts, [])

    def test_parser_rejects_bad_orientation_and_future_final(self):
        for text in ['Cubs (CHC) @ Reds (CIN) on Sunday, Sep 13, 2026 at 10:00 AM PDT. Final score: CIN 2 - CHC 1',
                     'Cubs (CHC) @ Reds (CIN) on Tuesday, Sep 15, 2026 at 10:00 AM PDT. Final score: CHC 2 - CIN 1']:
            with self.assertRaises(ValueError):
                parse_sports_extract(text, 'mlb', self.rec)

    def test_pending_scores_null_and_conflicts_retained(self):
        events = parse_sports_extract('Broncos @ Chiefs on Monday, Sep 14, 2026 at 05:15 PM PDT', 'nfl', self.rec)
        self.assertIsNone(events[0]['home_score'])
        corrected = copy.deepcopy(events[0]); corrected['status'] = 'postponed'
        rows, conflicts = reconcile(events + [corrected])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(rows[0]['status'], 'scheduled')

    def test_immutable_output_rejects_rewrite(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'run.json'
            immutable_json(path, {'p':0.5}); immutable_json(path, {'p':0.5})
            with self.assertRaisesRegex(ValueError, 'IMMUTABLE'):
                immutable_json(path, {'p':0.6})

    def test_current_feature_label_requires_artifact_and_timestamp(self):
        events = parse_sports_extract('Broncos @ Chiefs on Monday, Sep 14, 2026 at 05:15 PM PDT', 'nfl', self.rec)
        cov = {'source_sha256':'a'*64, 'verified_at':self.rec['retrieved_at'], 'complete':True,
               'date_from':'2026-09-14','date_to':'2026-09-14','expected_slate_count':1}
        s = league_status('nfl', self.clock, events, cov, {'status':'CURRENT'})
        self.assertEqual(s['feature_status'], 'UNVERIFIED')
        self.assertFalse(s['forecast_ready'])

    def test_runtime_pointer_checks_digest_and_expiration(self):
        from harness.current_sports_data import runtime_readiness
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            report={'clock':self.clock, 'leagues':[]}
            digest=immutable_json(root/'data/current/status.json',report)
            immutable_json(root/'data/current/runtime.json',{'status_path':'data/current/status.json','status_sha256':digest,'ttl_hours':6})
            self.assertEqual(runtime_readiness(root,'2026-09-14T16:00:00Z')['status'],'PARTIAL')
            self.assertEqual(runtime_readiness(root,'2026-09-15T16:00:00Z')['status'],'STALE_SNAPSHOT')
            (root/'data/current/status.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'DIGEST'):
                runtime_readiness(root,'2026-09-14T16:00:00Z')


if __name__ == '__main__':
    unittest.main()
