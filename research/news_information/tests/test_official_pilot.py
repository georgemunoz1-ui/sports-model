import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from research.news_information.archive import RawArchive
from research.news_information.contracts import RawSourceRecord, digest
from research.news_information.official_pilot import parse_schedule, apply_roster
from research.news_information.state_reducer import reduce_claims


def claim(state, hour, prior=None):
    c = {'league': 'NFL', 'event_id': 'nfl:fixture', 'subject_id': 'nfl:player',
         'state_dimension': 'game_status', 'previous_state': prior['new_state'] if prior else None,
         'new_state': state, 'supersedes_claim_id': prior['claim_id'] if prior else None,
         'source_id': 'NFL_OFFICIAL', 'effective_at_utc': f'2026-09-08T{hour}:00Z',
         'published_at_utc': None, 'retrieved_at_utc': f'2026-09-08T{hour}:00Z',
         'evidence_set_hash': 'a' * 64}
    return {**c, 'claim_id': digest(c)}


class OfficialPilotTests(unittest.TestCase):
    def test_cutoff_supersession_and_permutation(self):
        a = claim('QUESTIONABLE', '10:02'); b = claim('OUT', '12:14', a); c = claim('ACTIVE', '14:25', b)
        before = copy.deepcopy([a, b, c])
        r = reduce_claims([a, b, c], '2026-09-08T12:30:00Z')
        self.assertEqual(r['states'][0]['value'], 'OUT')
        self.assertEqual(r, reduce_claims([c, b, a], '2026-09-08T12:30:00Z'))
        self.assertEqual(before, [a, b, c])
        self.assertEqual(reduce_claims([a, b, c], '2026-09-08T15:00:00Z')['states'][0]['value'], 'ACTIVE')

    def test_conflict_and_bad_chain(self):
        a = claim('OUT', '10:02'); b = claim('ACTIVE', '12:14')
        self.assertEqual(reduce_claims([a, b], '2026-09-08T15:00:00Z')['states'][0]['status'], 'CONFLICTING')
        c = claim('ACTIVE', '12:14', a)
        self.assertEqual(reduce_claims([c], '2026-09-08T15:00:00Z')['states'][0]['status'], 'INVALID_CHAIN')

    def test_late_retrieval_and_tampering(self):
        a = claim('OUT', '10:02')
        a['retrieved_at_utc'] = '2026-09-08T14:00:00Z'
        a['claim_id'] = digest({k: v for k, v in a.items() if k != 'claim_id'})
        self.assertEqual(reduce_claims([a], '2026-09-08T12:30:00Z')['states'], [])
        a['new_state'] = 'ACTIVE'
        with self.assertRaises(ValueError): reduce_claims([a], '2026-09-08T15:00:00Z')

    def test_recapture_keeps_separate_observations(self):
        with tempfile.TemporaryDirectory() as td:
            record = RawSourceRecord.from_bytes(raw=b'unchanged', source_id='MLB', source_tier=1,
                source_type='LEAGUE_OFFICIAL', retrieved_at_utc='2026-09-08T10:00:00Z',
                forecast_cutoff_utc='2026-09-08T12:00:00Z', game_start_utc='2026-09-08T13:00:00Z')
            archive = RawArchive(Path(td)); a = archive.put(b'unchanged', record)
            b = archive.put(b'unchanged', replace(record, retrieved_at_utc='2026-09-08T11:00:00Z'))
            self.assertEqual(a['raw_path'], b['raw_path'])
            self.assertNotEqual(a['metadata_path'], b['metadata_path'])
            self.assertTrue(Path(a['metadata_path']).exists())

    def test_mlb_ids_missing_probable_and_roster(self):
        obs = {'raw_sha256': 'a'*64, 'retrieved_at_utc': '2026-09-08T10:00:00Z'}
        g = {'gamePk': 123, 'gameDate': '2026-09-08T18:00:00Z', 'officialDate': '2026-09-08',
             'teams': {'home': {'team': {'id': 1, 'name': 'Home'}},
                       'away': {'team': {'id': 2, 'name': 'Away'},
                                'probablePitcher': {'id': 3, 'fullName': 'Pitcher'}}}}
        payload = {'totalGames': 1, 'dates': [{'games': [g]}]}
        games, teams, players, claims = parse_schedule(payload, obs)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]['starter_slots']['home']['status'], 'UNRESOLVED')
        self.assertEqual(players['mlb:3']['team_assignments'], [])
        apply_roster({'roster': [{'person': {'id': 3, 'fullName': 'Pitcher'}}]}, 'mlb:2', obs, players)
        self.assertEqual(players['mlb:3']['team_assignments'][0]['team_id'], 'mlb:2')
        payload['totalGames'] = 2
        with self.assertRaises(ValueError): parse_schedule(payload, obs)


if __name__ == '__main__': unittest.main()
