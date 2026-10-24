import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from research.candidate_methods.methods import (verify_source, verified_pit_rows, check_partitions,
    choose_model, fit_sigmoid, lineup_quality, lineup_design, fit_rapm, lineup_effect)
from research.candidate_methods.features import nfl_history, pbp_features


def pit_row():
    return {'id':'g1','cutoff':'2026-09-17T10:00:00Z','start':'2026-09-17T11:00:00Z',
            'features':{'prior_epa':.1},'known_at':{'prior_epa':'2026-09-16T12:00:00Z'},
            'target':1,'target_known_at':'2026-09-17T15:00:00Z'}


def possession(i=0):
    d={'game_id':'g','poss_id':i,'points':2,'fgm':1,'fg3m':0,'ftm':0,'game_date':'2026-05-01'}
    d.update({f'{s}_p{k}':f'{s}{k}' for s in ['off','def'] for k in range(1,6)})
    return d


class SourceAndTimeTests(unittest.TestCase):
    def test_modified_source_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'x';p.write_bytes(b'a');h=hashlib.sha256(b'a').hexdigest()
            verify_source(p,h);p.write_bytes(b'b')
            with self.assertRaises(ValueError):verify_source(p,h)

    def test_pit_and_late_evidence(self):
        r=pit_row();verified_pit_rows([r],['prior_epa'])
        r['known_at']['prior_epa']='2026-09-18T00:00:00Z'
        with self.assertRaises(ValueError):verified_pit_rows([r],['prior_epa'])

    def test_poststart_cutoff(self):
        r=pit_row();r['cutoff']=r['start']
        with self.assertRaises(ValueError):verified_pit_rows([r],['prior_epa'])

    def test_duplicate_event(self):
        r=pit_row()
        with self.assertRaises(ValueError):verified_pit_rows([r,r],['prior_epa'])

    def test_market_field(self):
        r=pit_row();r['features']={'market_odds':1};r['known_at']={'market_odds':r['cutoff']}
        with self.assertRaises(ValueError):verified_pit_rows([r],['market_odds'])

    def test_missing_known_at(self):
        r=pit_row();r['known_at']={}
        with self.assertRaises(ValueError):verified_pit_rows([r],['prior_epa'])

    def test_whole_games_and_date_groups(self):
        p=[pd.DataFrame({'game_id':[f'g{i}',f'g{i}'],'date':[f'202{i}-01-01']*2}) for i in range(4)]
        check_partitions(*p)
        p[1]['game_id']='g0'
        with self.assertRaises(ValueError):check_partitions(*p)

    def test_same_date_and_reversed_calibration(self):
        p=[pd.DataFrame({'game_id':[f'g{i}'],'date':[f'202{i}-01-01']}) for i in range(4)]
        with self.assertRaises(ValueError):check_partitions(p[0],p[2],p[1],p[3])
        p[2]['date']=p[1].date
        with self.assertRaises(ValueError):check_partitions(*p)


class LearningTests(unittest.TestCase):
    def test_scaler_and_imputer_see_training_only(self):
        train=pd.DataFrame({'x':[0.,2.,np.nan],'z':[1.,3.,5.]})
        tune=pd.DataFrame({'x':[1000.,2000.],'z':[1000.,2000.]})
        model,_,_=choose_model('ridge',[{'alpha':1}],1,train,np.array([0.,1.,2.]),tune,np.array([1.,1.]))
        np.testing.assert_allclose(model.named_steps['missing'].statistics_,[1,3])
        np.testing.assert_allclose(model.named_steps['scale'].mean_[:2],[1,3])

    def test_future_targets_cannot_change_fitted_predictions(self):
        x=pd.DataFrame({'x':np.arange(30.)});y=np.arange(30.)
        a,_,_=choose_model('ridge',[{'alpha':1},{'alpha':10}],1,x.iloc[:10],y[:10],x.iloc[10:20],y[10:20])
        changed=y.copy();changed[20:]=999
        b,_,_=choose_model('ridge',[{'alpha':1},{'alpha':10}],1,x.iloc[:10],changed[:10],x.iloc[10:20],changed[10:20])
        np.testing.assert_array_equal(a.predict(x.iloc[20:]),b.predict(x.iloc[20:]))

    def test_calibration_discriminates_and_requires_both_classes(self):
        c=fit_sigmoid([-10,-5,5,10],[-7,-2,3,7])
        self.assertGreater(c.predict_proba([[5]])[0,1],c.predict_proba([[-5]])[0,1])
        with self.assertRaises(ValueError):fit_sigmoid([1,2],[1,2])

    def test_xgboost_is_deterministic(self):
        x=pd.DataFrame({'x':np.arange(30.)});y=np.arange(30.)
        grid=[{'n_estimators':5,'max_depth':2,'n_jobs':1}]
        a,_,_=choose_model('xgb',grid,17,x[:20],y[:20],x[20:],y[20:])
        b,_,_=choose_model('xgb',grid,17,x[:20],y[:20],x[20:],y[20:])
        np.testing.assert_array_equal(a.predict(x),b.predict(x))


class LineupTests(unittest.TestCase):
    def test_defense_sign_and_exposure(self):
        d=pd.DataFrame([possession()]);X,players=lineup_design(d)
        self.assertEqual(X[:,:len(players)].sum(),5)
        self.assertEqual(X[:,len(players):].sum(),-5)
        self.assertEqual(lineup_effect({str(i):2 for i in range(5)},{str(i):1 for i in range(5)}),10)
        with self.assertRaises(ValueError):lineup_effect({'a':2},{'a':1})

    def test_anomalous_points_block_entire_fit(self):
        d=pd.DataFrame([possession(0),possession(1)]);d.loc[1,'points']=105
        self.assertEqual(lineup_quality(d)['status'],'BLOCKED')
        with self.assertRaises(ValueError):fit_rapm(d)

    def test_scoring_mismatch_and_unknown_player(self):
        d=pd.DataFrame([possession()]);d.loc[0,'points']=3
        with self.assertRaises(ValueError):lineup_design(d)
        d.loc[0,'points']=2
        with self.assertRaises(ValueError):lineup_design(d,['unknown'])

    def test_duplicate_player_or_possession(self):
        d=pd.DataFrame([possession(),possession()])
        self.assertEqual(lineup_quality(d)['status'],'BLOCKED')
        d=d.iloc[:1].copy();d.loc[0,'def_p1']=d.loc[0,'off_p1']
        with self.assertRaises(ValueError):fit_rapm(d)

    def test_independent_fit_smoke_only(self):
        d=pd.DataFrame([possession(i) for i in range(20)])
        model,players=fit_rapm(d)
        X,_=lineup_design(d,players)
        np.testing.assert_allclose(model.predict(X),200)


class FeatureTests(unittest.TestCase):
    def test_current_result_not_in_current_features(self):
        games=pd.DataFrame([{'game_id':f'g{i}','gameday':f'{1999+i}-09-01','season':1999+i,
            'game_type':'REG','week':1,'home_team':'A','away_team':'B','home_score':20,'away_score':10} for i in range(3)])
        callers=pd.DataFrame([{'game_id':f'g{i}','team':t,'head_coach':'H','off_play_caller':'O','def_play_caller':'D'} for i in range(3) for t in ['A','B']])
        a=nfl_history(games,callers);games.loc[2,'home_score']=100;b=nfl_history(games,callers)
        pd.testing.assert_frame_equal(a.drop(columns='target_margin'),b.drop(columns='target_margin'))
        self.assertEqual(a.iloc[-1].home_coach_prior_games,2)
        games=pd.concat([games,games.iloc[:1]])
        with self.assertRaises(ValueError):nfl_history(games,callers)

    def test_pace_resets_game_and_uses_sequence(self):
        base={'posteam':'A','play_type':'run','epa':.1,'success':1,'pass_attempt':0,'rush_attempt':1,
            'sack':0,'interception':0,'fumble_lost':0,'down':1,'score_differential':0,'qtr':1,
            'drive':1,'timeout':0,'out_of_bounds':0,'incomplete_pass':0,'touchdown':0,'penalty':0,
            'complete_pass':0,'yardline_100':50,'receiver_player_id':None,'rusher_player_id':'p',
            'yards_after_catch':None,'xyac_mean_yardage':None,'play_deleted':0}
        rows=[]
        for game in ['a','b']:
            for seq,clock,pid in [(1,900,99),(2,880,3)]:
                rows.append(dict(base,game_id=game,order_sequence=seq,game_seconds_remaining=clock,play_id=pid))
        p=pd.DataFrame(rows).sample(frac=1,random_state=1)
        observed,_=pbp_features(p)
        self.assertEqual(observed.running_clock_n.tolist(),[1,1])
        self.assertEqual(observed.running_clock_seconds.tolist(),[20.,20.])
        p.loc[(p.game_id=='a')&(p.order_sequence==1),'timeout']=1
        observed,_=pbp_features(p)
        self.assertEqual(observed.running_clock_n.tolist(),[0,1])


if __name__=='__main__':unittest.main()
