import unittest
from reprice import margin_quantiles, reprice_cfb_spread, reprice_cfb_total, METHOD

class RepricingTests(unittest.TestCase):
    def setUp(self):
        self.row={'simulation_method':METHOD,'model':{'n_sims':4,'full_game_home_margin':0.,'margin_sigma':2.},'full_margin_histogram':{'-7':1,'0':1,'7':1,'14':1}}
    def test_orientation(self):
        r=reprice_cfb_spread(self.row,-6.5)
        self.assertEqual(r['sim_home_cover'],.5)
        self.assertEqual(r['p_push'],0)
        self.assertAlmostEqual(r['model_home_cover']+r['model_away_cover'],1)
    def test_positive_line(self):
        self.assertEqual(reprice_cfb_spread(self.row,7.5)['sim_home_cover'],1)
    def test_quantiles(self):
        self.assertEqual(margin_quantiles(self.row)['values'],dict(p10=-7,p25=-7,p50=0,p75=7,p90=14))
    def test_bad_lines(self):
        for line in [-7,0,6.25,float('nan'),float('inf'),True]:
            with self.assertRaises(ValueError):reprice_cfb_spread(self.row,line)
    def test_wrong_period(self):
        with self.assertRaises(ValueError):reprice_cfb_spread(self.row,-6.5,'first_half')
    def test_bad_counts(self):
        for count in [-1,1.5,True]:
            self.row['full_margin_histogram']['7']=count
            with self.assertRaises(ValueError):margin_quantiles(self.row)
    def test_count_mismatch(self):
        self.row['model']['n_sims']=5
        with self.assertRaises(ValueError):margin_quantiles(self.row)
    def test_invalid_distribution(self):
        self.row['simulation_method']='FIRST_HALF_TOTAL'
        with self.assertRaises(ValueError):margin_quantiles(self.row)
    def test_total_unsupported(self):
        r=reprice_cfb_total(49.5)
        self.assertEqual(r['status'],'UNSUPPORTED');self.assertIsNone(r['p_under'])

if __name__=='__main__':unittest.main()
