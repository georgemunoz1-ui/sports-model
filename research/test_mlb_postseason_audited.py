import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from scripts.mlb_postseason_audited import audit_event, source_map, run
from research.mlb_postseason_v1 import sha


def fixture():
    now = dt.datetime(2026, 10, 6, 20, tzinfo=dt.timezone.utc)
    e = {'event_id': 'MLB:42', 'slate_date': '2026-10-06', 'through_date': '2026-10-05',
         'start_time_utc': '2026-10-06T22:00:00Z', 'game_type': 'D', 'park_factor': 1.0}
    gd = {'game': {'type': 'D'}, 'datetime': {'dateTime': e['start_time_utc']},
          'status': {'abstractGameState': 'Preview'}, 'probablePitchers': {}, 'teams': {}}
    rosters, history, boxes = {}, {}, {}
    for side, pid, tid in [('away', 10, 1), ('home', 20, 2)]:
        e[side + '_pitcher_id'] = pid; e[side + '_starter'] = str(pid)
        e['sp_' + side] = {'era': 4., 'gs': 8, 'k': 22., 'bb': 8.}
        gd['probablePitchers'][side] = {'id': pid}; gd['teams'][side] = {'id': tid}
        rosters[tid] = {'roster': [{'person': {'id': pid}, 'status': {'code': 'A'}}]}
        history[pid] = [{'date': '2026-10-01', 'player': {'id': pid}, 'game': {'gamePk': pid},
                         'gameType': 'F', 'stat': {'inningsPitched': '3.1', 'outs': 10,
                                                   'gamesStarted': 1, 'numberOfPitches': 66}}]
        boxes[side] = {'battingOrder': [], 'players': {}}
    return e, {'gamePk': 42, 'gameData': gd, 'liveData': {'boxscore': {'teams': boxes}}}, rosters, history, now


class AuditTests(unittest.TestCase):
    def test_missing_lineup_is_disclosed_not_neutral_imputed(self):
        row = audit_event(*fixture())
        self.assertFalse(row['final_ready'])
        self.assertEqual(row['sides']['away']['lineup_status'], 'MISSING_NOT_USED')
        self.assertIn('announced_workload', row['not_used'])

    def test_postseason_workload_is_context_not_used(self):
        row = audit_event(*fixture())
        self.assertAlmostEqual(row['sides']['home']['last_five_starts_mean_innings_not_used'], 10 / 3)
        self.assertEqual(row['starter_innings_prior']['mean'], 5.4)
        self.assertFalse(row['score_total_runline_supported'])

    def test_starter_roster_conflict(self):
        a = fixture(); a[2][1]['roster'] = []
        with self.assertRaisesRegex(ValueError, 'STARTER_ACTIVE_ROSTER_CONFLICT'): audit_event(*a)

    def test_starter_id_conflict(self):
        a = fixture(); a[1]['gameData']['probablePitchers']['home']['id'] = 99
        with self.assertRaisesRegex(ValueError, 'STARTER_IDENTITY'): audit_event(*a)

    def test_feed_start_conflict(self):
        a = fixture(); a[1]['gameData']['datetime']['dateTime'] = '2026-10-06T23:00:00Z'
        with self.assertRaisesRegex(ValueError, 'FEED_EVENT_OR_START_CONFLICT'): audit_event(*a)

    def test_post_start_status(self):
        a = fixture(); a[1]['gameData']['status']['abstractGameState'] = 'Live'
        with self.assertRaisesRegex(ValueError, 'POST_START'): audit_event(*a)

    def test_invalid_lineup(self):
        a = fixture(); a[1]['liveData']['boxscore']['teams']['away']['battingOrder'] = [1] * 9
        with self.assertRaisesRegex(ValueError, 'INVALID_BATTING_ORDER'): audit_event(*a)

    def test_stale_day_and_boolean_numeric(self):
        for key, value in [('through_date', '2026-10-04'), ('park_factor', True), ('park_factor', float('nan'))]:
            with self.subTest(key=key, value=value):
                a = fixture(); a[0][key] = value
                with self.assertRaises(ValueError): audit_event(*a)
        a = fixture(); a[0]['sp_away']['gs'] = True
        with self.assertRaisesRegex(ValueError, 'STARTER_NUMERIC_TYPE'): audit_event(*a)

    def test_duplicate_history_and_outs(self):
        a = fixture(); a[3][10] *= 2
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_PITCHER_GAME'): audit_event(*a)
        a = fixture(); a[3][10][0]['stat']['outs'] = 11
        with self.assertRaisesRegex(ValueError, 'HISTORY_OUTS_MISMATCH'): audit_event(*a)

    def test_stale_future_and_tampered_source(self):
        now = fixture()[-1]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root/'raw.json').write_text('{}')
            rec = {'kind': 'test', 'raw_path': 'raw.json', 'status': 'CAPTURED',
                   'raw_sha256': sha(root/'raw.json'), 'retrieved_at_utc': now.isoformat()}
            source_map(root, {'sources': [rec]}, now)
            for hours in [-7, 1]:
                r = dict(rec, retrieved_at_utc=(now+dt.timedelta(hours=hours)).isoformat())
                with self.assertRaisesRegex(ValueError, 'STALE_OR_FUTURE'): source_map(root, {'sources': [r]}, now)
            (root/'raw.json').write_text('{"tampered":true}')
            with self.assertRaisesRegex(ValueError, 'SOURCE_BINDING'): source_map(root, {'sources': [rec]}, now)

    def test_existing_output_rejected_before_any_write(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); (p/'sentinel').write_text('frozen')
            with self.assertRaisesRegex(ValueError, 'OUTPUT_MUST_BE_NEW'): run(p,p,p,p,p)
            self.assertEqual((p/'sentinel').read_text(), 'frozen')
            self.assertEqual(len(list(p.iterdir())), 1)


if __name__ == '__main__': unittest.main()
