import copy,json,unittest
import numpy as np
from recovered_pipeline import ROOT,predict,bind_context,bernoulli_simulation
from run_recovered import drive_bridge

class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.params=json.loads((ROOT/'fitted_parameters.json').read_text())
        cls.row=json.loads((ROOT/'frozen_feature_row.json').read_text())[0]
        cls.ctx=json.loads((ROOT/'current_context.json').read_text())
        cls.bundle=json.loads((ROOT/'results_final/bundle.json').read_text())
    def bind(self,c):return bind_context(self.params,self.row,c,self.bundle['cutoff_utc'],self.bundle['start_utc'])
    def test_market_field_rejected(self):
        f={n:self.row[n] for n in self.params['feature_names']};f['moneyline']=-132
        with self.assertRaisesRegex(ValueError,'EXACT_FEATURE_SCHEMA'):predict(self.params,f)
        with self.assertRaisesRegex(ValueError,'UNKNOWN_CONTEXT'):self.bind({**self.ctx,'market':{}})
    def test_late_source_rejected(self):
        c=copy.deepcopy(self.ctx);c['weather']['published_at_utc']='2026-09-16T00:00:00Z'
        with self.assertRaisesRegex(ValueError,'POST_CUTOFF'):self.bind(c)
    def test_wrong_event_rejected(self):
        c=copy.deepcopy(self.ctx);c['weather']['event_id']='2026_01_KC_DEN'
        with self.assertRaisesRegex(ValueError,'EVENT_MISMATCH'):self.bind(c)
    def test_night_low_not_hourly(self):
        c=copy.deepcopy(self.ctx);c['weather']['temperature_kind']='OVERNIGHT_LOW'
        with self.assertRaisesRegex(ValueError,'WEATHER_QUANTITY'):self.bind(c)
    def test_weather_actually_changes_model(self):
        x=self.bind(self.ctx)
        self.assertNotEqual(x['baseline']['prediction']['home_margin'],x['current']['prediction']['home_margin'])
        for name in ('home_margin','total_points'):
            change=sum(x['context_contribution_changes'][name].values())
            self.assertAlmostEqual(x['current']['prediction'][name]-x['baseline']['prediction'][name],change,places=12)
    def test_unfitted_personnel_not_silently_numeric(self):
        x=self.bind(self.ctx)
        self.assertIsNone(x['context_admission']['personnel']['numeric_adjustment'])
        y=self.bind({k:v for k,v in self.ctx.items() if k!='personnel'})
        self.assertEqual(x['current'],y['current'])
    def test_rest_is_fitted_and_effective(self):
        a=self.bind(self.ctx);c=copy.deepcopy(self.ctx);c['rest']['home_rest']=10
        b=self.bind(c)
        self.assertNotEqual(a['current']['prediction'],b['current']['prediction'])
    def test_replay_arrays_and_mass(self):
        b=self.bundle;p=b['current']['prediction'];s,info=drive_bridge(p['home_margin'],p['total_points'],b['identity'])
        self.assertTrue(np.array_equal(s,np.load(ROOT/'results_final/drive_scores.npy')))
        self.assertAlmostEqual(info['home_win']+info['away_win']+info['tie'],1,places=14)
        self.assertTrue((s[:,:2]>=0).all())
        self.assertTrue(np.allclose(info['expected_regulation_scores'],info['regulation_score_targets'],atol=1e-8))
        draws,_=bernoulli_simulation(p['home_win'],b['identity'])
        self.assertTrue(np.array_equal(draws,np.load(ROOT/'results_final/winner_draws.npy')))

if __name__=='__main__':unittest.main()
