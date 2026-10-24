import copy,hashlib,unittest
import numpy as np
import pandas as pd
from research.nfl_fusion.contracts import *
from research.nfl_fusion.ensemble import weights,binary_score,simulate_binary,align,CONTEXT,CANDIDATE_MAP,predict_packets,fit,predict_frame

class ContractTests(unittest.TestCase):
    def test_fraction_percent(self):self.assertEqual(fraction(58.5,'PERCENT'),.585)
    def test_fraction_fraction(self):self.assertEqual(fraction(.585,'FRACTION'),.585)
    def test_missing_unit_rejected(self):
        with self.assertRaisesRegex(ValueError,'UNIT'):fraction(.5,'GUESS')
    def test_percent_not_fraction(self):
        with self.assertRaisesRegex(ValueError,'RANGE'):fraction(58.5,'FRACTION')
    def test_nonfinite_rate(self):
        with self.assertRaises(ValueError):fraction(float('nan'),'FRACTION')
    def test_probability_home(self):self.assertEqual(home_probability(.6,'BUF','BUF','DET'),.6)
    def test_probability_away(self):self.assertEqual(home_probability(.4,'DET','BUF','DET'),.6)
    def test_probability_wrongteam(self):
        with self.assertRaises(ValueError):home_probability(.6,'KC','BUF','DET')
    def test_aliases(self):self.assertEqual(home_probability(.6,'LAR','LA','SF'),.6)
    def test_score_orientation(self):self.assertEqual(point_targets(41,31),{'home_win':1,'home_margin':10,'total_points':72})
    def test_tie_binary_missing(self):self.assertIsNone(point_targets(20,20)['home_win'])
    def test_scores_not_rates(self):
        with self.assertRaises(ValueError):point_targets(4.1,3.1)
    def test_spread_sign(self):self.assertEqual(nflverse_spread_to_home_handicap(5.5),-5.5)
    def test_denominators(self):self.assertEqual(metric_mean([1.,None,3.]),{'value':2.,'observed_n':2,'eligible_n':3,'missing_n':1})
    def test_empty_not_zero(self):self.assertIsNone(metric_mean([])['value'])
    def test_receipt_bytes(self):
        b=b'abc';r={'source_url':'fixture','sha256':hashlib.sha256(b).hexdigest(),'retrieved_at_utc':'2026-09-18T10:00:00Z'}
        require_receipt(r,'2026-09-18T11:00:00Z',b)
        with self.assertRaisesRegex(ValueError,'HASH'):require_receipt(r,'2026-09-18T11:00:00Z',b'changed')
    def test_receipt_late(self):
        r={'source_url':'fixture','sha256':'a'*64,'retrieved_at_utc':'2026-09-18T12:00:00Z'}
        with self.assertRaisesRegex(ValueError,'CUTOFF'):require_receipt(r,'2026-09-18T11:00:00Z')
    def test_naive_time(self):
        with self.assertRaisesRegex(ValueError,'TIMEZONE'):utc('2026-09-18T00:00:00')
    def packet(self):
        return {'event_id':'2026_03_A_B','target':TARGETS['home_win'],'orientation':'HOME','period':'FULL_GAME_INCLUDING_OVERTIME','information_cutoff_utc':'2026-09-20T10:00:00Z','created_at_utc':'2026-09-20T10:00:01Z','event_start_utc':'2026-09-27T17:00:00Z','model_artifact_sha256':'a'*64,'feature_snapshot_sha256':'b'*64,'source_manifest_sha256':'c'*64,'market_input':False,'value':.6}
    def validate(self,p):return validate_prediction_packet(p,'2026_03_A_B','2026-09-20T10:00:00Z','home_win')
    def test_packet_admission(self):self.assertEqual(self.validate(self.packet()),.6)
    def test_packet_wrong_target(self):
        p=self.packet();p['target']=TARGETS['home_margin']
        with self.assertRaises(ValueError):self.validate(p)
    def test_packet_wrong_period(self):
        p=self.packet();p['period']='FIRST_HALF'
        with self.assertRaises(ValueError):self.validate(p)
    def test_packet_stale_cutoff(self):
        p=self.packet();p['information_cutoff_utc']='2026-09-19T10:00:00Z'
        with self.assertRaises(ValueError):self.validate(p)
    def test_packet_market_rejected(self):
        p=self.packet();p['market_input']=True
        with self.assertRaisesRegex(ValueError,'MARKET'):self.validate(p)
    def test_packet_missing_pins(self):
        p=self.packet();p.pop('feature_snapshot_sha256')
        with self.assertRaisesRegex(ValueError,'PIN'):self.validate(p)
    def test_packet_post_start(self):
        p=self.packet();p['created_at_utc']='2026-09-27T18:00:00Z'
        with self.assertRaisesRegex(ValueError,'PREGAME'):self.validate(p)
    def test_weighted_trace(self):
        model={'heads':{'home_win':{'target':TARGETS['home_win'],'arms':['a','b'],'weights':[.3,.7],'calibration':{'slope':1,'intercept':0}}}}
        a=self.packet();b=self.packet();b['value']=.8
        r=predict_packets(model,{'a':a,'b':b},a['event_id'],a['information_cutoff_utc'],'home_win')
        self.assertAlmostEqual(r['value'],.74);self.assertAlmostEqual(sum(r['weighted_components'].values()),r['raw_blend'])
        with self.assertRaisesRegex(ValueError,'ARMS'):predict_packets(model,{'a':a},a['event_id'],a['information_cutoff_utc'],'home_win')

class NumericTests(unittest.TestCase):
    def test_brier_logloss(self):
        x=binary_score([1],[.585779175173204]);self.assertAlmostEqual(x['brier'],(1-.585779175173204)**2);self.assertEqual(x['correct'],1)
    def test_nonbinary_scoring_refused(self):
        with self.assertRaises(ValueError):binary_score([.5],[.6])
    def test_invalid_probability_scoring(self):
        with self.assertRaises(ValueError):binary_score([1],[60.])
    def test_weight_simplex(self):
        y=np.array([0,1]*100);X=np.column_stack([np.ones(200)*.5,.1+.8*y]);w=weights(X,y)
        self.assertAlmostEqual(w.sum(),1);self.assertTrue((w>=0).all());self.assertGreater(w[1],.99)
    def test_exact_sim_replay(self):
        a,x=simulate_binary(.63,'test');b,y=simulate_binary(.63,'test')
        self.assertTrue(np.array_equal(a,b));self.assertEqual(x,y);self.assertEqual(len(a),100000)
    def test_sim_se(self):
        _,x=simulate_binary(.5,'test');self.assertAlmostEqual(x['mc_standard_error'],(.25/100000)**.5)
    def test_sim_count_refused(self):
        with self.assertRaises(ValueError):simulate_binary(.5,'x',10)
    def test_fit_never_touches_test_year(self):
        p={'weight_fit_years':[2019,2021],'calibration_years':[2022,2022],'weight_penalty':.001}
        with self.assertRaisesRegex(ValueError,'TEST_DATA'):fit(pd.DataFrame({'season':[2023]}),p)
    def test_actual_defensive_perspective(self):
        p=pd.DataFrame([{'game_id':'x','posteam':'BUF','defteam':'DET','play_type':'pass','qb_kneel':0,'qb_spike':0,'epa':2.,'success':1,'qb_dropback':1,'passer_player_id':'a'},
                        {'game_id':'x','posteam':'DET','defteam':'BUF','play_type':'run','qb_kneel':0,'qb_spike':0,'epa':-1.,'success':0,'qb_dropback':0,'passer_player_id':None}])
        r={v['team']:v for v in observations(p)}
        self.assertEqual(r['BUF']['defense_epa_allowed_per_play']['value'],-1.);self.assertEqual(r['DET']['defense_epa_prevented_per_play'],-2.)
        self.assertFalse(r['BUF']['active_in_forecast'])

class ScopeTests(unittest.TestCase):
    def fixture(self):
        g=pd.DataFrame([{'game_id':'2026_02_DET_BUF','season':2026,'week':2,'home_team':'BUF','away_team':'DET','home_score':41,'away_score':31}])
        p=pd.DataFrame([{**g.iloc[0].to_dict(),'play_id':1,'total_home_score':41,'total_away_score':31}])
        r={'source_url':'fixture','sha256':'a'*64,'retrieved_at_utc':'2026-09-18T10:00:00Z'}
        return p,g,r
    def call(self,p,g,r,**kw):return select_pbp_scope(p,g,'2026-09-18T11:00:00Z',r,**kw)
    def test_scope_correct(self):
        p,g,r=self.fixture();d,a=self.call(p,g,r);self.assertEqual(len(d),1)
    def test_scope_wrong_week(self):
        p,g,r=self.fixture();p['week']=1
        with self.assertRaisesRegex(ValueError,'BINDING'):self.call(p,g,r)
    def test_scope_duplicate_play(self):
        p,g,r=self.fixture()
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):self.call(pd.concat([p,p]),g,r)
    def test_scope_wrong_score(self):
        p,g,r=self.fixture();p['total_home_score']=40
        with self.assertRaisesRegex(ValueError,'SCORE'):self.call(p,g,r)
    def test_scope_extra_game_refused(self):
        p,g,r=self.fixture();e=p.copy();e['game_id']='2026_03_A_B'
        with self.assertRaisesRegex(ValueError,'OUT_OF_SCOPE'):self.call(pd.concat([p,e]),g,r,historical_rebuild=True)
    def test_scope_explicit_exclusion_receipt(self):
        p,g,r=self.fixture();e=p.copy();e['game_id']='2026_03_A_B';d,a=self.call(pd.concat([p,e]),g,r)
        self.assertEqual(len(d),1);self.assertEqual(a['excluded_rows'],1)
    def test_scope_missing_completed(self):
        p,g,r=self.fixture()
        with self.assertRaisesRegex(ValueError,'MISSING_COMPLETED'):self.call(p.iloc[:0],g,r)

class AlignmentTests(unittest.TestCase):
    def fixture(self):
        context=pd.DataFrame([dict(game_id='2019_01_A_B',season=2019,week=1,arm=a,trained_through_season=2018,home_win=1.,home_margin=3.,total_points=43.,p_home=.6,pred_margin=2.,pred_total=44.) for a in CONTEXT])
        candidates=pd.DataFrame([dict(game_id='2019_01_A_B',season=2019,arm=a,target_margin=3.,p_home_calibrated=.58,predicted_margin=1.8) for a in CANDIDATE_MAP])
        schedule=pd.DataFrame([dict(game_id='2019_01_A_B',season=2019,week=1,home_team='B',away_team='A',home_score=23,away_score=20)])
        return context,candidates,schedule
    def test_exact_common_cohort(self):
        c,q,g=self.fixture();r=align(c,q,g);self.assertEqual(len(r),1);self.assertEqual(r.iloc[0].home_margin,3.)
    def test_no_totals_invented_for_margin_only_candidates(self):
        c,q,g=self.fixture();r=align(c,q,g);self.assertEqual(len([x for x in r if x.startswith('t__')]),5)
    def test_duplicate_arm_game_refused(self):
        c,q,g=self.fixture()
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):align(pd.concat([c,c.iloc[[0]]]),q,g)
    def test_missing_model_arm_refused(self):
        c,q,g=self.fixture()
        with self.assertRaisesRegex(ValueError,'ARM_SET'):align(c.iloc[1:],q,g)
    def test_mismatched_population_refused(self):
        c,q,g=self.fixture();q.loc[0,'game_id']='2019_01_C_D'
        with self.assertRaisesRegex(ValueError,'COHORT'):align(c,q,g)
    def test_in_sample_base_predictions_refused(self):
        c,q,g=self.fixture();c.loc[0,'trained_through_season']=2019
        with self.assertRaisesRegex(ValueError,'IN_SAMPLE'):align(c,q,g)
    def test_reversed_home_target_refused(self):
        c,q,g=self.fixture();q.loc[0,'target_margin']=-3.
        with self.assertRaisesRegex(ValueError,'ORIENTATION'):align(c,q,g)
    def test_percentage_in_probability_column_refused(self):
        c,q,g=self.fixture();q.loc[0,'p_home_calibrated']=58.
        with self.assertRaisesRegex(ValueError,'UNITS'):align(c,q,g)
    def test_2026_outcome_never_admitted(self):
        c,q,g=self.fixture();c['season']=2026
        with self.assertRaisesRegex(ValueError,'EXCLUDED'):align(c,q,g)

if __name__=='__main__':unittest.main()
