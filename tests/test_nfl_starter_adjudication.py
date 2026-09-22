"""Corrections are explicit, source-bound and refuse ambiguity; never guess a QB."""
import copy
import hashlib
import json
import unittest
import pandas as pd
from models.nfl.contextual.starter_adjudication import apply


def fixture():
    game = {'game_id': '2026_02_CAR_ATL', 'season': 2026, 'home_team': 'ATL',
            'away_team': 'CAR', 'gameday': '2026-09-20', 'home_score': 3, 'away_score': 34,
            'home_qb_id': 'old', 'away_qb_id': 'away'}
    j = {'header': {'id': '123', 'season': {'year': 2026, 'type': 2}, 'competitions': [{
        'status': {'type': {'completed': True}}, 'date': '2026-09-20T17:00:00Z',
        'competitors': [{'homeAway': side, 'team': {'abbreviation': game[side+'_team']},
                         'score': str(game[side+'_score'])} for side in ('home', 'away')]}]},
        'boxscore': {'players': [{'team': {'abbreviation': 'ATL'}, 'statistics': [
            {'name': 'passing', 'athletes': [{'athlete': {'id': '456', 'displayName': 'Test Quarterback'}}]}]}]}}
    raw = json.dumps(j)
    resolution = {'game_id': game['game_id'], 'team': 'ATL', 'qb_id': 'new',
        'expected_schedule_qb_id': 'old', 'espn_event_id': '123', 'espn_athlete_id': '456',
        'player_name': 'Test Quarterback', 'pbp_player_name': 'T.Quarterback',
        'reviewed_by': 'synthetic test', 'review_reason': 'TEST_ONLY',
        'reviewed_at_utc': '2026-09-22T00:00:00Z', 'evidence': {'text': raw, 'receipt': {
            'sha256': hashlib.sha256(raw.encode()).hexdigest(), 'retrieved_at_utc': '2026-09-21T00:00:00Z',
            'source_url': 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=123'}}}
    pbp = pd.DataFrame([{'game_id': game['game_id'], 'posteam': 'ATL', 'qb_dropback': 1,
        'play_id': 1, 'qb_scramble': 0, 'passer_player_id': 'new', 'passer_player_name': 'T.Quarterback'}])
    return pd.DataFrame([game]), pbp, resolution


class Adjudication(unittest.TestCase):
    def test_explicit_correction_preserves_input(self):
        games, pbp, r = fixture()
        self.assertEqual(apply(games, pbp, [], r['reviewed_at_utc']).iloc[0].home_qb_id, 'old')
        actual = apply(games, pbp, [r], r['reviewed_at_utc'])
        self.assertEqual(actual.iloc[0].home_qb_id, 'new')
        self.assertEqual(games.iloc[0].home_qb_id, 'old')

    def test_wrong_identity_time_source_and_duplicate_refused(self):
        games, pbp, base = fixture()
        cases = [('qb_id', 'other'), ('espn_athlete_id', 'other'), ('player_name', 'Other'),
                 ('pbp_player_name', 'Other'), ('expected_schedule_qb_id', 'other'),
                 ('reviewed_at_utc', '2026-09-23T00:00:00Z'), ('review_reason', '')]
        for key, value in cases:
            r = copy.deepcopy(base); r[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                apply(games, pbp, [r], base['reviewed_at_utc'])
        r = copy.deepcopy(base); r['evidence']['text'] += ' '
        with self.assertRaisesRegex(ValueError, 'SOURCE_HASH'):
            apply(games, pbp, [r], base['reviewed_at_utc'])
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
            apply(games, pbp, [base, base], base['reviewed_at_utc'])

    def test_bound_json_semantics_and_original_qb_participation_refused(self):
        games, pbp, base = fixture()
        for field, value in [('id', 'other'), ('season', {'year': 2025, 'type': 2})]:
            r = copy.deepcopy(base); j = json.loads(r['evidence']['text']); j['header'][field] = value
            r['evidence']['text'] = json.dumps(j)
            r['evidence']['receipt']['sha256'] = hashlib.sha256(r['evidence']['text'].encode()).hexdigest()
            with self.assertRaises(ValueError):
                apply(games, pbp, [r], base['reviewed_at_utc'])
        extra = pbp.copy(); extra['play_id'] = 2; extra['passer_player_id'] = 'old'
        with self.assertRaisesRegex(ValueError, 'PBP_IDENTITY_CONFLICT'):
            apply(games, pd.concat([pbp, extra]), [base], base['reviewed_at_utc'])


if __name__ == '__main__':
    unittest.main()
