"""Known HTML fixtures, not an independently labeled extraction corpus."""
import unittest
from research.news_information.contracts import sha256_bytes
from research.news_information.nfl_official_report import parse_nfl_report


def fixture(practice='Full Participation in Practice', status=''):
    return ('''<h1>2026 NFL Injury Report</h1>Injuries - WEEK 1
<div class="d3-o-section-sub-title"><span>Example Team</span></div></div>
<div class="d3-o-table--horizontal-scroll"><table><tr>
<th>Player</th><th>Position</th><th>Injuries</th><th>Practice Status</th><th>Game Status</th>
</tr><tr><td><a href="/players/example-player/">Example Player</a></td><td>QB</td>
<td>Knee</td><td>''' + practice + '</td><td>' + status + '</td></tr></table></div>').encode()


def parse(raw):
    return parse_nfl_report(raw, {'raw_sha256': sha256_bytes(raw),
                                 'retrieved_at_utc': '2026-09-08T19:50:00Z'})


class NFLReportTests(unittest.TestCase):
    def test_blank_is_unknown_and_identity_unbound(self):
        row = parse(fixture())['observations'][0]
        self.assertEqual(row['practice_state'], 'FULL')
        self.assertEqual(row['game_status'], 'UNKNOWN')
        for field in ('canonical_player_id', 'event_id', 'practice_date', 'effective_at_utc'):
            self.assertIsNone(row[field])
        self.assertFalse(row['forecast_adjustment_eligible'])

    def test_known_and_unknown_designations(self):
        row = parse(fixture('Did Not Participate In Practice', 'Out'))['observations'][0]
        self.assertEqual((row['practice_state'], row['game_status']), ('DNP', 'OUT'))
        row = parse(fixture('New Provider Label', 'New Designation'))['observations'][0]
        self.assertEqual((row['practice_state'], row['game_status']), ('UNRESOLVED', 'UNRESOLVED'))

    def test_source_tamper_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            parse_nfl_report(fixture(), {'raw_sha256': '0' * 64})

    def test_provider_changes_fail_visibly(self):
        for raw in (fixture().replace(b'Practice Status', b'Changed'),
                    fixture().replace(b'/players/example-player/', b'/unbound/'),
                    b'<h1>2026 NFL Injury Report</h1>Injuries - WEEK 1'):
            with self.assertRaises(ValueError): parse(raw)


if __name__ == '__main__': unittest.main()
