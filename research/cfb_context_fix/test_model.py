import unittest,numpy as np
from model import roster_state,fit,predict
class Tests(unittest.TestCase):
 def test_active_is_not_starter(self):
  s=roster_state({'athletes':[{'items':[{'id':'1','displayName':'QB','position':{'abbreviation':'QB'},'status':{'name':'Active'}}]}]});self.assertEqual(s['starting_qb'],'UNCONFIRMED')
 def test_missing_roster_not_clean(self):self.assertEqual(roster_state({})['game_day_availability'],'UNRESOLVED')
 def test_history_required(self):
  with self.assertRaises(ValueError):fit([])
 def test_team_identity_and_replay(self):
  m={'team_ids':['h','a'],'half_coef':[12,2,0,0,1],'margin_coef':[0,10],'margin_sigma':14,'half_total_sigma':10}
  p,x,y=predict(m,'h','a',1600,1500,'e','h');q,a,b=predict(m,'h','a',1600,1500,'e','h');self.assertEqual(p['first_half_home_points'],15);self.assertTrue(np.array_equal(x,a));self.assertTrue(np.array_equal(y,b));self.assertTrue((y>=0).all())
if __name__=='__main__':unittest.main()
