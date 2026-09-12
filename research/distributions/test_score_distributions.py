import copy, unittest
import numpy as np
from models.common.score_distributions_v1 import extract,decode,reprice
from models.mlb.monte_carlo_v1 import run

class DistributionTests(unittest.TestCase):
    def artifact(self):return extract(np.array([0,1,2,3],dtype='uint8'),[1,1,1,1],score_period='MLB_NINE_INNING_PROXY')
    def test_signed_and_lossless(self):
        d=self.artifact();h,a=decode(d)
        self.assertEqual(d['margin']['mean'],.5)
        self.assertEqual(d['margin']['pmf'][0]['value'],-1)
        np.testing.assert_array_equal(h,[0,1,2,3])
    def test_push_conditional(self):
        r=reprice(self.artifact(),0,kind='spread',score_period='MLB_NINE_INNING_PROXY')
        self.assertEqual(r['probabilities'],{'home_cover':.5,'away_cover':.25,'push':.25})
        self.assertAlmostEqual(r['conditional_on_no_push']['home_cover'],2/3)
    def test_all_push_and_undefined_correlation(self):
        d=extract([1,1],[1,1],score_period='MLS_REGULATION_GRID')
        self.assertIsNone(d['margin_total_correlation'])
        r=reprice(d,2,kind='total',score_period='MLS_REGULATION_GRID')
        self.assertIsNone(r['conditional_on_no_push']['over'])
    def test_half_total(self):
        r=reprice(self.artifact(),2.5,kind='total',score_period='MLB_NINE_INNING_PROXY')
        self.assertEqual(r['probabilities'],{'over':.5,'under':.5,'push':0})
    def test_malformed_scores(self):
        for h,a in [([],[]),([1.1],[0]),([np.nan],[0]),([-1],[0]),([1,2],[0])]:
            with self.assertRaises(ValueError):extract(h,a,score_period='MLS_REGULATION_GRID')
    def test_hash_tamper(self):
        d=self.artifact();d['score_draws']['sha256']='0'*64
        with self.assertRaises(ValueError):decode(d)
    def test_invalid_market_scope(self):
        with self.assertRaises(ValueError):reprice(self.artifact(),1.5,kind='spread',score_period='MLB_FULL_GAME')
        with self.assertRaises(ValueError):reprice(self.artifact(),.25,kind='spread',score_period='MLB_NINE_INNING_PROXY')
    def test_engine_rng_and_hash_unchanged(self):
        s={'event_id':'fixture','away_rf_pg':4.1,'away_ra_pg':4.3,'home_rf_pg':4.7,'home_ra_pg':4.4}
        before=run(s,{},100000);captured=[]
        after=run(s,{},100000,score_sink=lambda h,a:captured.append(extract(h,a,score_period='MLB_NINE_INNING_PROXY')))
        self.assertEqual(before['output_hash'],after['output_hash'])
        self.assertEqual(before['projection'],after['projection'])
        self.assertEqual(captured[0]['margin']['mean'],before['projection']['home_margin_mean'])

if __name__=='__main__':unittest.main()
