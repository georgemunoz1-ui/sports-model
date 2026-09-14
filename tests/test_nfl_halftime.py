import unittest
import numpy as np
import pandas as pd
from models.nfl.contextual.halftime import support, sample, quantities, probabilities, crps, fit, predict

class HalftimeTests(unittest.TestCase):
    def test_known_contract_counts(self):
        s=np.array([[7,10,14,14],[10,10,7,3],[14,7,0,14],[10,14,7,0]])
        p=probabilities(s)
        self.assertEqual(p['h1_away_win'],.5)
        self.assertEqual(p['h1_home_win'],.25)
        self.assertEqual(p['h1_tie'],.25)
        self.assertEqual(p['h1_away_plus_1_5'],.75)
        self.assertEqual(p['fg_away_plus_2_5'],.5)
        self.assertEqual(p['combo_away_plus_2_5_and_h1_plus_1_5'],.25)
        self.assertEqual(p['h1_under_20_5'],.5)

    def test_complement_and_joint_bounds(self):
        s=np.random.default_rng(1).integers(0,35,size=(300,4));p=probabilities(s)
        self.assertAlmostEqual(p['h1_away_win']+p['h1_home_win']+p['h1_tie'],1)
        self.assertAlmostEqual(p['h1_under_20_5']+p['h1_over_20_5'],1)
        a,b,c=p['h1_away_plus_1_5'],p['fg_away_plus_2_5'],p['combo_away_plus_2_5_and_h1_plus_1_5']
        self.assertTrue(max(0,a+b-1)<=c<=min(a,b))

    def test_same_game_residual_pairing_and_replay(self):
        r=np.repeat([[-3,3,-2,2],[3,-3,2,-2]],60,axis=0)
        a,info=sample([14,14,14,14],r,{'event':'fixture'})
        b,other=sample([14,14,14,14],r,{'event':'fixture'})
        np.testing.assert_array_equal(a,b);self.assertEqual(info,other)
        q=quantities(a);self.assertTrue(np.all(np.sign(q['h1_home_margin'])==np.sign(q['fg_home_margin'])))

    def test_first_half_ties_not_resolved_by_full_game(self):
        p=probabilities(np.array([[10,10,7,0]]))
        self.assertEqual(p['h1_tie'],1);self.assertEqual(p['fg_home_win'],1)

    def test_invalid_scores(self):
        for scores in [np.array([[1,2,3,-1]]),np.array([[1.5,2,3,4]]),np.array([[1,2]])]:
            with self.assertRaises(ValueError):quantities(scores)

    def test_crps_known_answer(self):
        self.assertEqual(crps([0,2],1),.5)
        self.assertEqual(crps([4,4],4),0)

    def test_portable_predict_and_no_market_feature(self):
        n=120;frame=pd.DataFrame({'season':[2020]*n,'x':np.arange(n),
            'h1_home':np.arange(n)*.1+10,'h1_away':[11]*n,
            'remaining_home':[13]*n,'remaining_away':[12]*n})
        model=fit(frame,['x']);pred=predict(model,frame)
        self.assertEqual(pred.shape,(n,4));self.assertEqual(model['feature_names'],['x'])
        baseline=fit(frame,['x'],scaled=True);z=predict(baseline,frame)
        np.testing.assert_array_equal(z[:,:2],z[:,2:])

    def test_play_id_is_not_chronology(self):
        # A provider-inserted timeout ID follows the true end-half ID numerically.
        d=pd.DataFrame({'play_id':[2367,2482,2399,2462],'score':[10,10,13,13]})
        self.assertEqual(d.iloc[-1].score,13)
        self.assertEqual(d.sort_values('play_id').iloc[-1].score,10)

if __name__=='__main__':unittest.main()
