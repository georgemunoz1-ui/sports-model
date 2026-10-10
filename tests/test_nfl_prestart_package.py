"""Future events remain independent of started peers; no synthetic forecasts."""
import copy
import unittest
import pandas as pd
from scripts.prepare_nfl_weekly_events import select_prestart_events


class PrestartSelection(unittest.TestCase):
    def fixture(self):
        return pd.DataFrame([
            {'game_id':'2026_05_TB_DAL','gameday':'2026-10-08','gametime':'20:15'},
            {'game_id':'2026_05_PHI_JAX','gameday':'2026-10-11','gametime':'09:30'},
            {'game_id':'2026_05_BUF_LA','gameday':'2026-10-12','gametime':'20:15'}])

    def test_thursday_does_not_block_sunday_and_monday(self):
        games=self.fixture(); original=games.copy(deep=True)
        future,excluded=select_prestart_events(games,'2026-10-10T02:00:00Z')
        self.assertEqual([r['game_id'] for r,_ in future],['2026_05_PHI_JAX','2026_05_BUF_LA'])
        self.assertEqual(excluded,[{'event_id':'2026_05_TB_DAL','start_time_utc':'2026-10-09T00:15:00+00:00','disposition':'POST_START'}])
        pd.testing.assert_frame_equal(games,original)

    def test_at_kickoff_is_already_post_start(self):
        future,excluded=select_prestart_events(self.fixture(),'2026-10-11T13:30:00Z')
        self.assertEqual([r['game_id'] for r,_ in future],['2026_05_BUF_LA'])
        self.assertEqual(len(excluded),2)

    def test_before_all_starts_preserves_full_coverage(self):
        future,excluded=select_prestart_events(self.fixture(),'2026-10-09T00:14:59Z')
        self.assertEqual(len(future),3);self.assertEqual(excluded,[])

    def test_all_started_never_creates_a_future_event(self):
        future,excluded=select_prestart_events(self.fixture(),'2026-10-13T00:15:00Z')
        self.assertEqual(future,[]);self.assertEqual(len(excluded),3)

    def test_invalid_time_fails_instead_of_assuming_pregame(self):
        games=self.fixture();games.loc[1,'gametime']='unknown'
        with self.assertRaises(ValueError):select_prestart_events(games,'2026-10-10T02:00:00Z')


if __name__=='__main__':unittest.main()
