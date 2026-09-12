import unittest
from reprice import METHOD,reprice_cfb_spread
from reprice_push_v2 import reprice_with_push
class Tests(unittest.TestCase):
 def setUp(self):self.r={'simulation_method':METHOD,'model':{'n_sims':4,'full_game_home_margin':0.,'margin_sigma':2.},'full_margin_histogram':{'-5':1,'-4':2,'0':1}}
 def test_push_orientation(self):
  x=reprice_with_push(self.r,4,research_only=True);self.assertEqual(x['counts'],dict(home_cover=1,away_cover=1,push=2));self.assertEqual(x['simulation']['home_cover_given_no_push'],.5)
 def test_all_push(self):
  self.r['full_margin_histogram']={'-4':4};x=reprice_with_push(self.r,4,research_only=True);self.assertIsNone(x['simulation']['away_cover_given_no_push'])
 def test_mass(self):
  x=reprice_with_push(self.r,0,research_only=True)['model'];self.assertAlmostEqual(x['home_cover'],x['away_cover']);self.assertAlmostEqual(x['home_cover']+x['away_cover']+x['push'],1)
 def test_half_unchanged(self):
  a=reprice_with_push(self.r,4.5,research_only=True);b=reprice_cfb_spread(self.r,4.5);self.assertEqual(a['simulation']['push'],0);self.assertEqual(a['simulation']['home_cover'],b['sim_home_cover']);self.assertAlmostEqual(a['model']['home_cover'],b['model_home_cover'])
 def test_bad_line(self):
  for v in [True,float('nan'),float('inf'),4.25]:
   with self.assertRaises(ValueError):reprice_with_push(self.r,v,research_only=True)
 def test_optin(self):
  with self.assertRaises(ValueError):reprice_with_push(self.r,4)
 def test_period(self):
  with self.assertRaises(ValueError):reprice_with_push(self.r,4,research_only=True,period='first_half')
 def test_legacy_gate(self):
  with self.assertRaises(ValueError):reprice_cfb_spread(self.r,4)
if __name__=='__main__':unittest.main()
