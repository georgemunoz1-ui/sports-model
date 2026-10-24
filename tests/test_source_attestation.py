import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.source_attestation import attest_sources, instant
from scripts.capture_priority_schedules import requests_for, build_schedule, parse_event
from scripts.generate_card_force import summarize_pit

STAMP = '2026-10-09T01:00:00Z'
CUTOFF = '2026-10-09T01:05:00Z'


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        raw = b'{"events":[]}'
        (self.root / 'raw').mkdir()
        (self.root / 'raw/a.json').write_bytes(raw)
        self.source = {'source': 'https://example.invalid/source', 'sha256': hashlib.sha256(raw).hexdigest(), 'fetched_at_utc': STAMP}
        self.receipt = {'url': self.source['source'], 'raw_sha256': self.source['sha256'], 'retrieved_at_utc': STAMP, 'raw_path': 'raw/a.json', 'status': 'CAPTURED'}
        self.report()

    def report(self, row=None):
        (self.root / 'report.json').write_text(json.dumps({'sources': [row or self.receipt]}))

    def test_retention_is_not_pit_or_provider_authenticity(self):
        result = attest_sources([self.source], [self.root], CUTOFF)
        self.assertEqual(result['status'], 'RAW_BYTES_AND_RECEIPTS_VERIFIED')
        for k in ('historical_pit_validity_proven', 'provider_authenticity_proven', 'model_input_usage_proven', 'certified_calibration_eligible', 'action_authority'):
            self.assertIs(result[k], False)

    def test_corrupt_bytes_refused(self):
        (self.root / 'raw/a.json').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'DIGEST_MISMATCH'):
            attest_sources([self.source], [self.root], CUTOFF)

    def test_unbound_timestamp_refused(self):
        bad = {**self.source, 'fetched_at_utc': '2026-10-09T00:59:00Z'}
        with self.assertRaisesRegex(ValueError, 'RETENTION_UNVERIFIED'):
            attest_sources([bad], [self.root], CUTOFF)

    def test_after_cutoff_refused(self):
        with self.assertRaisesRegex(ValueError, 'AFTER_CUTOFF'):
            attest_sources([self.source], [self.root], '2026-10-09T00:00:00Z')

    def test_timezone_required(self):
        with self.assertRaisesRegex(ValueError, 'TIMEZONE'):
            instant('2026-10-09T01:00:00')

    def test_path_escape_refused(self):
        self.report({**self.receipt, 'raw_path': '../escape'})
        with self.assertRaisesRegex(ValueError, 'PATH_OUTSIDE'):
            attest_sources([self.source], [self.root], CUTOFF)

    def test_writer_keeps_pit_ordered_after_retention_proof(self):
        with patch.dict('os.environ', {'SPORTS_SOURCE_BUNDLES': json.dumps([str(self.root)])}):
            result = summarize_pit({'pit_provenance': {'source_fetches': [self.source]}}, CUTOFF, CUTOFF)
        self.assertEqual(result['pit_status'], 'PIT_ORDERED')
        self.assertEqual(result['source_attestation']['status'], 'RAW_BYTES_AND_RECEIPTS_VERIFIED')

    def test_writer_records_missing_proof(self):
        with patch.dict('os.environ', {'SPORTS_SOURCE_BUNDLES': '[]'}):
            result = summarize_pit({'pit_provenance': {'source_fetches': [self.source]}}, CUTOFF, CUTOFF)
        self.assertEqual(result['source_attestation']['status'], 'SOURCE_RETENTION_UNVERIFIED')

    def test_nfl_operational_receipt_supported(self):
        (self.root / 'nfl').mkdir()
        (self.root / 'nfl/games.csv').write_bytes((self.root / 'raw/a.json').read_bytes())
        (self.root / 'report.json').write_text(json.dumps({'nfl_sources': [{'filename': 'games.csv', 'source_url': self.source['source'], 'sha256': self.source['sha256'], 'retrieved_at_utc': STAMP, 'status': 'captured'}]}))
        self.assertEqual(attest_sources([self.source], [self.root], CUTOFF)['status'], 'RAW_BYTES_AND_RECEIPTS_VERIFIED')


class ScheduleTests(unittest.TestCase):
    def event(self, typ=2):
        return {'id': '1', 'date': '2026-10-10T02:00:00Z', 'season': {'type': typ, 'year': 2026}, 'competitions': [{'competitors': [{'homeAway': s, 'team': {'id': str(i), 'displayName': s}} for i, s in enumerate(('home', 'away'))], 'status': {'type': {'state': 'pre'}}}]}

    def test_local_date_and_provider_namespace(self):
        row = parse_event(self.event(), 'wnba', 'America/Los_Angeles')
        self.assertEqual(row['slate_date'], '2026-10-09')
        self.assertEqual(row['event_id'], 'espn:wnba:1')
        self.assertIsNone(row['official_event_id'])

    def test_postseason_explicit(self):
        self.assertEqual(parse_event(self.event(3), 'wnba', 'UTC')['season_scope'], 'postseason')
        self.assertTrue(all('seasontype=3' in r[2] for r in requests_for('wnba', '2026-10-09', ['postseason'])))

    def test_incomplete_requests_never_zero_games(self):
        with self.assertRaisesRegex(ValueError, 'COVERAGE_INCOMPLETE'):
            build_schedule(Path('.'), 'nfl', '2026-10-09', 'UTC', ['regular'], [])

    def test_empty_complete_response_still_not_official_zero_game(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            raw = b'{"events":[]}'
            (root / 'raw.json').write_bytes(raw)
            results = [({'url': s[2], 'status': 'CAPTURED', 'raw_path': 'raw.json', 'raw_sha256': hashlib.sha256(raw).hexdigest(), 'retrieved_at_utc': STAMP}, {'events': []}) for s in requests_for('nfl', '2026-10-09', ['regular'])]
            result = build_schedule(root, 'nfl', '2026-10-09', 'UTC', ['regular'], results)
            self.assertFalse(result['no_games_verified'])
            self.assertEqual(result['model_input_status'], 'ACQUIRE_REQUIRED')
            bad = copy.deepcopy(results)
            bad[0][0]['status'] = 'FAILED'
            with self.assertRaisesRegex(ValueError, 'ACQUIRE_REQUIRED'):
                build_schedule(root, 'nfl', '2026-10-09', 'UTC', ['regular'], bad)

    def test_duplicate_team_refused(self):
        event = self.event()
        event['competitions'][0]['competitors'][1]['team']['id'] = '0'
        with self.assertRaisesRegex(ValueError, 'SELF_MATCH'):
            parse_event(event, 'nfl', 'UTC')


if __name__ == '__main__':
    unittest.main()
