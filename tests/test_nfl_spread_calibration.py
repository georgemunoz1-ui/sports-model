import copy,json,unittest
from pathlib import Path
import numpy as np
from models.nfl.contextual.spread_calibration import (transform_cdf,margin_distribution,
    price_spread,calibrated_distribution,exact_kernel_margin,simulate_margins)
from models.nfl.contextual.model import simulate_joint
from models.nfl.contextual.spread_runtime import load_calibrator,build_overlay
ROOT=Path(__file__).resolve().parents[1]

class SpreadCalibrationTests(unittest.TestCase):
    def setUp(self):
        # Known football margins with exact key-number masses.
        self.m=np.array([-7,-3,0,3,7]);self.w=np.array([.1,.2,.1,.4,.2])
    def test_hand_computed_push_contract(self):
        p=price_spread(self.m,self.w,-3)
        for name,value in {'win':.2,'push':.4,'loss':.4}.items():self.assertAlmostEqual(p[name],value)
        p=price_spread(self.m,self.w,-2.5)
        self.assertAlmostEqual(p['win'],.6);self.assertEqual(p['push'],0)
    def test_identity_exact(self):
        f=np.array([0,.1,.4,.9,1]);np.testing.assert_array_equal(f,transform_cdf(f))
    def test_known_sigmoid_transform(self):
        # G(.8) with slope 1/2 is sigmoid(log(4)/2)=2/3.
        self.assertAlmostEqual(float(transform_cdf(.8,0,.5)),2/3)
    def test_probability_mass_coherence(self):
        m,w=calibrated_distribution(self.m,self.w,.1,.5)
        self.assertTrue((w>=0).all());self.assertAlmostEqual(w.sum(),1)
        for line in np.arange(-12,12,.5):
            p=price_spread(self.m,self.w,line,intercept=.1,slope=.5)
            q=price_spread(m,w,line)
            for key in p:self.assertAlmostEqual(p[key],q[key])
            self.assertAlmostEqual(sum(p.values()),1)
    def test_opposing_sides_and_monotonic_alternates(self):
        previous=-1
        for line in np.arange(-12,12,.5):
            h=price_spread(self.m,self.w,line,intercept=.1,slope=.5)
            a=price_spread(self.m,self.w,line,side='AWAY',intercept=.1,slope=.5)
            self.assertEqual(h['win'],a['loss']);self.assertEqual(h['push'],a['push'])
            self.assertGreaterEqual(h['win'],previous);previous=h['win']
            if line%1:self.assertEqual(h['push'],0)
    def test_reject_bad_inputs_and_first_half(self):
        for f in [np.nan,-.1,1.1]:
            with self.assertRaises(ValueError):transform_cdf(f)
        with self.assertRaises(ValueError):transform_cdf(.5,slope=-1)
        with self.assertRaises(ValueError):margin_distribution([1.5,2])
        with self.assertRaises(ValueError):price_spread(self.m,self.w,-2.25)
        with self.assertRaises(ValueError):price_spread(self.m,self.w,-2.5,period='FIRST_HALF')
    def test_exact_kernel_matches_mc(self):
        rng=np.random.default_rng(42);pool=rng.normal(0,12,(1000,2))
        m,w=exact_kernel_margin(2,45,.57,pool,.004)
        scores,info=simulate_joint(2,45,.57,pool,.004,'CALIBRATION_TEST',100000)
        sim=scores[:,0].astype(int)-scores[:,1].astype(int)
        for line in [-7,-3,-2.5,0,3,7]:
            expected=price_spread(m,w,line);sample=price_spread(sim,np.ones(len(sim)),line)
            for key in expected:self.assertLess(abs(expected[key]-sample[key]),.008)
    def test_seeded_calibrated_replay(self):
        m,w=calibrated_distribution(self.m,self.w,.1,.5)
        a,x=simulate_margins(m,w,1234);b,y=simulate_margins(m,w,1234)
        np.testing.assert_array_equal(a,b);self.assertEqual(x,y)
    def fixture(self):
        from models.nfl.contextual.model import load_artifact
        from models.nfl.contextual.recovered_inference import digest
        import hashlib
        scores=np.array([[20,17],[17,20],[24,24],[30,20]],dtype='<i2')
        f={'model_id':'nfl.integrated_context.combined.v1.research','mode':'research_pregame',
           'cutoff_utc':'2026-09-14T09:25:55Z','identity':'UNIT_TEST_NOT_A_FORECAST',
           'model_artifact_sha256':digest(load_artifact(ROOT/'data/nfl/contextual_v1/model_packed.json')),
           'event':{'event_id':'UNIT_TEST','home_team':'KC','away_team':'DEN','start_time_utc':'2030-01-01T00:00:00Z'},
           'score_simulation':{'distribution':'OUTCOME_ALIGNED_FINAL_SCORE_KERNEL_V2',
             'target':'FINAL_SCORE_INCLUDING_OVERTIME','n':4,'sha256':hashlib.sha256(scores.tobytes()).hexdigest()}}
        return f,scores
    def test_overlay_isolation_and_adapter(self):
        from pipelines.cards.adapters.nfl import calibrate_spreads
        f,s=self.fixture();before=copy.deepcopy(f);orig=s.copy()
        a,x=calibrate_spreads(f,s,[-2.5,-3],n=1000)
        b,y=calibrate_spreads(f,s,[-2.5],n=1000)
        self.assertEqual(f,before);np.testing.assert_array_equal(s,orig)
        np.testing.assert_array_equal(x,y);self.assertEqual(a['simulation'],b['simulation'])
        self.assertFalse(a['calibrator_existed_at_original_forecast_cutoff'])
    def test_overlay_rejects_forecast_or_draw_substitution(self):
        f,s=self.fixture();bad=s.copy();bad[0,0]+=1
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):build_overlay(f,bad,[-2.5])
        f['model_id']='nfl.market_ensemble.v1.research'
        with self.assertRaisesRegex(ValueError,'REFERENCE_MISMATCH'):build_overlay(f,s,[-2.5])
    def test_overlay_exclusive_persistence(self):
        import tempfile
        from models.nfl.contextual.spread_runtime import persist_overlay
        f,s=self.fixture();o,d=build_overlay(f,s,[-2.5],n=1000)
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'new';persist_overlay(p,o,d)
            with self.assertRaises(FileExistsError):persist_overlay(p,o,d)
    def test_fitted_artifact_and_evaluation_population(self):
        m,e=load_calibrator();self.assertEqual(m['fit_seasons'],[2020,2021,2022]);self.assertEqual(e['evaluation_seasons'],[2023,2024,2025])
        self.assertGreater(m['slope'],0);self.assertFalse(m['promotion'])
        self.assertEqual(e['raw']['games'],e['calibrated']['games'])
        self.assertFalse(e['calibration_reliability_established'])

if __name__=='__main__':unittest.main()
