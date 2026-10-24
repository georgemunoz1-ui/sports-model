"""Regressions from real package acquisition, not new predictive weights."""
import unittest
import pandas as pd
from research.nfl_fusion.contracts import observations

class FeedRows(unittest.TestCase):
    def frame(self):
        return pd.DataFrame([
            dict(game_id='x',posteam='BUF',defteam='DET',play_type='pass',qb_kneel=0,qb_spike=0,epa=2.,success=1.,qb_dropback=1,passer_player_id='qb'),
            dict(game_id='x',posteam=None,defteam=None,play_type=None,qb_kneel=None,qb_spike=None,epa=None,success=None,qb_dropback=None,passer_player_id=None)])
    def test_null_nonplay_does_not_become_an_observation(self):
        rows=observations(self.frame())
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['offense_epa_per_play']['eligible_n'],1)
        self.assertEqual(rows[0]['offense_epa_per_play']['value'],2.)
    def test_missing_team_on_real_play_is_rejected(self):
        p=self.frame();p.loc[0,'defteam']=None
        with self.assertRaisesRegex(ValueError,'TEAM_ID_MISSING'):observations(p)
    def test_missing_epa_is_not_zero(self):
        p=self.frame();p.loc[0,'epa']=None
        rows=observations(p)
        self.assertIsNone(rows[0]['offense_epa_per_play']['value'])
        self.assertEqual(rows[0]['offense_epa_per_play']['missing_n'],1)
        self.assertEqual(rows[0]['offense_epa_per_play']['eligible_n'],1)

if __name__=='__main__':unittest.main()
