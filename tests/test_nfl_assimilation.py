import copy,hashlib,json,tempfile,unittest
from pathlib import Path
import pandas as pd
from models.nfl.contextual.assimilation import *
from models.nfl.contextual.capabilities import validate_report,describe_run_capabilities,reporter_hash

class Assimilation(unittest.TestCase):
    def setUp(self):
        self.game={'game_id':'2025_17_DEN_KC','season':2025,'week':17,'home_team':'KC','away_team':'DEN',
          'home_score':7,'away_score':3,'gameday':'2025-12-25','home_rest':7,'away_rest':7,'roof':'outdoors',
          'location':'Home','temp':50,'wind':5}
        self.schedule=pd.DataFrame([self.game]);self.cutoff='2026-09-14T16:00:00Z'
        self.receipt={'source_url':'fixture://synthetic-not-real-game','retrieved_at_utc':'2026-09-14T15:00:00Z','snapshot_id':'fixture'}
        self.pbp=pd.DataFrame([{**{k:self.game[k] for k in ['game_id','season','week','home_team','away_team']},
          'play_id':i,'order_sequence':i,'qtr':q,'quarter_seconds_remaining':clock,'game_seconds_remaining':(4-q)*900+clock,
          'total_home_score':h,'total_away_score':a,'down':1,'play_type':'pass','qb_kneel':0,'qb_spike':0,
          'no_play':0,'wp':.5,'posteam':off,'defteam':'DEN' if off=='KC' else 'KC','epa':epa,
          'success':int(epa>0),'yards_gained':10 if epa>0 else 0,'sack':0,'interception':0,'fumble_lost':0}
          for i,q,clock,h,a,off,epa in [(1,1,600,0,0,'KC',2),(2,2,0,7,0,'DEN',-1),(3,3,900,7,0,'KC',1),(4,4,0,7,3,'DEN',-2)]])
    def check(self,p=None,s=None,receipt=None,previous=None):
        return reconcile_game_coverage(self.pbp if p is None else p,self.schedule if s is None else s,receipt or self.receipt,self.cutoff,previous)
    def test_clean_coverage_and_half(self):
        x=self.check();self.assertTrue(x['weekly_state_update_eligible']);self.assertEqual(x['rows'][0]['halftime_score'],{'home':7,'away':0})
    def test_missing_completed_game(self):
        s=pd.concat([self.schedule,pd.DataFrame([{**self.game,'game_id':'missing'}])]);r=self.check(s=s)
        self.assertFalse(r['weekly_state_update_eligible']);self.assertEqual(r['rows'][1]['coverage_status'],'partial')
    def test_duplicate_play(self):
        r=self.check(p=pd.concat([self.pbp,self.pbp.iloc[[0]]]))
        self.assertEqual(r['rows'][0]['coverage_status'],'conflicting');self.assertFalse(r['weekly_state_update_eligible'])
    def test_after_cutoff(self):
        r=self.check(receipt={**self.receipt,'retrieved_at_utc':'2026-09-14T17:00:00Z'})
        self.assertFalse(r['rows'][0]['pregame_eligible']);self.assertFalse(r['weekly_state_update_eligible'])
    def test_publication_after_cutoff(self):
        r=self.check(receipt={**self.receipt,'source_published_at_utc':'2026-09-14T17:00:00Z'})
        self.assertFalse(r['weekly_state_update_eligible'])
    def test_swapped_binding(self):
        p=self.pbp.copy();p['home_team']='DEN';p['away_team']='KC'
        self.assertEqual(self.check(p=p)['rows'][0]['coverage_status'],'invalid_binding')
    def test_revision_quarantines(self):
        r=self.check(previous={self.game['game_id']:[6,3]})
        self.assertTrue(r['rows'][0]['prior_state_quarantine_required']);self.assertFalse(r['weekly_state_update_eligible'])
    def test_no_week_release_with_mnf_pending(self):
        s=pd.concat([self.schedule,pd.DataFrame([{**self.game,'game_id':'pending','home_score':None,'away_score':None}])])
        r=self.check(s=s);self.assertTrue(r['completed_coverage_complete']);self.assertFalse(r['weekly_state_update_eligible'])
    def test_missing_epa(self):
        p=self.pbp.copy();p.loc[0,'epa']=None;self.assertFalse(self.check(p=p)['weekly_state_update_eligible'])
    def test_invalid_clock(self):
        p=self.pbp.copy();p.loc[1,['qtr','quarter_seconds_remaining']]=[1,700]
        self.assertIn('CLOCK_INCREASE_REQUIRES_REVISION_REVIEW',self.check(p=p)['rows'][0]['reason'])
    def test_order_sequence_not_identifier(self):
        p=self.pbp.copy();p['play_id']=[4,3,2,1];self.assertTrue(self.check(p=p)['weekly_state_update_eligible'])
    def test_halftime_boundary_missing(self):
        self.assertFalse(self.check(p=self.pbp[self.pbp.qtr!=2])['weekly_state_update_eligible'])
    def test_score_mismatch(self):
        p=self.pbp.copy();p.loc[3,'total_home_score']=8;self.assertFalse(self.check(p=p)['weekly_state_update_eligible'])
    def test_immutable_snapshot_and_failure_report(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);p=td/'source.csv';self.pbp.to_csv(p,index=False)
            receipt={**self.receipt,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
            _,a=ingest_pbp_snapshot(p,receipt,td/'archive');_,b=ingest_pbp_snapshot(p,receipt,td/'archive');self.assertEqual(a,b)
            result=run_nfl_assimilation_check(path=p,receipt={**receipt,'sha256':'bad'},schedule=self.schedule,cutoff=self.cutoff,archive=td/'archive',output=td/'failure')
            self.assertEqual(result['status'],'failed');self.assertTrue((td/'failure/audit.json').exists())
    def test_assimilation_changes_only_declared_features(self):
        prior={t:bf.TeamState() for t in ['KC','DEN']};updated,_=advance_states(prior,self.schedule,self.pbp)
        params=json.loads((Path(__file__).resolve().parents[1]/'data/nfl/contextual_v1/recovered_parameters.json').read_text())
        trace=trace_feature_effects_into_forecasts(prior,updated,{**self.game,'game_id':'future','week':18,'home_score':None,'away_score':None},params)
        self.assertIn('epa_matchup_edge',trace['changed_features']);self.assertNotIn('temperature_f',trace['changed_features'])
        self.assertNotEqual(trace['state_before_sha256'],trace['state_after_sha256']);self.assertNotEqual(trace['forecast_delta']['home_margin'],0)
    def test_end_to_end_orchestrator_and_same_week_refusal(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);p=td/'raw.csv';self.pbp.to_csv(p,index=False)
            receipt={**self.receipt,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
            params=json.loads((Path(__file__).resolve().parents[1]/'data/nfl/contextual_v1/recovered_parameters.json').read_text())
            r=run_nfl_assimilation_check(path=p,receipt=receipt,schedule=self.schedule,cutoff=self.cutoff,archive=td/'archive',output=td/'run',
              prior_states={t:bf.TeamState() for t in ['KC','DEN']},params=params,
              forecast_requests=[self.game,{**self.game,'game_id':'future','week':18,'home_score':None,'away_score':None}])
            self.assertTrue(r['state_update_applied']);self.assertEqual(r['forecast_traces'][0]['status'],'not_updated')
            self.assertNotEqual(r['forecast_traces'][1]['forecast_delta']['home_margin'],0)

class CapabilityValidation(unittest.TestCase):
    def setUp(self):
        self.report={'reporter_sha256':reporter_hash(),'rows':[{'feature':'epa','implemented':True,'fitted_artifact_available':True,'active_in_run':True,'value_status':'derived','pregame_eligible':True,'contribution_method':'exact_centered_linear_term','contribution':{'home_margin':.1}}]}
    def test_valid(self):validate_report(self.report)
    def test_active_missing_value(self):
        self.report['rows'][0]['value_status']='missing'
        with self.assertRaisesRegex(ValueError,'ACTIVE_MISSING'):validate_report(self.report)
    def test_active_missing_contribution(self):
        self.report['rows'][0]['contribution']=None
        with self.assertRaisesRegex(ValueError,'WITHOUT_CONTRIBUTION'):validate_report(self.report)
    def test_active_missing_fit(self):
        self.report['rows'][0]['fitted_artifact_available']=False
        with self.assertRaisesRegex(ValueError,'WITHOUT_FITTED'):validate_report(self.report)
    def test_reporter_hash(self):
        self.report['reporter_sha256']='bad'
        with self.assertRaisesRegex(ValueError,'REPORTER_HASH'):validate_report(self.report)
    def test_empty_contribution_rejected(self):
        self.report['rows'][0]['contribution']={}
        with self.assertRaisesRegex(ValueError,'WITHOUT_CONTRIBUTION'):validate_report(self.report)
    def test_mc_paired_flag_alone_insufficient(self):
        row=self.report['rows'][0];row['contribution_method']='paired_monte_carlo_counterfactual'
        row['uncertainty']={'paired':True}
        with self.assertRaisesRegex(ValueError,'MC_ESTIMATOR'):validate_report(self.report)
    def test_mc_explicit_estimator_and_error(self):
        row=self.report['rows'][0];row['contribution_method']='paired_monte_carlo_counterfactual'
        row['uncertainty']={'paired':True,'estimator':'mean_paired_outcome_difference','n_draws':100000,
          'standard_error':{'home_margin':0.01},'uncertainty_scope':'monte_carlo_only'}
        validate_report(self.report)
        row['uncertainty']['standard_error']['home_margin']=-1
        with self.assertRaisesRegex(ValueError,'MC_STANDARD_ERROR_INVALID'):validate_report(self.report)
    def test_mc_requires_paired_uncertainty(self):
        self.report['rows'][0]['contribution_method']='paired_monte_carlo_counterfactual'
        with self.assertRaisesRegex(ValueError,'UNCERTAINTY'):validate_report(self.report)

class Settlement(unittest.TestCase):
    def test_integer_push_and_halfpoint(self):
        from models.nfl.contextual.settlement import settle_contract
        x=dict(home_score=23,away_score=20,market_type='SPREAD',side='AWAY')
        self.assertEqual(settle_contract(**x,line=3)['result'],'PUSH')
        self.assertEqual(settle_contract(**x,line=2.5)['result'],'LOSS')
    def test_period_mismatch(self):
        from models.nfl.contextual.settlement import settle_contract
        with self.assertRaisesRegex(ValueError,'PERIOD'):
            settle_contract(home_score=23,away_score=20,market_type='TOTAL',side='OVER',line=20.5,period='FIRST_HALF')
    def test_price_absent_and_fee(self):
        from models.nfl.contextual.settlement import settle_contract
        x=dict(home_score=23,away_score=20,market_type='SPREAD',side='HOME',line=-2.5)
        self.assertIsNone(settle_contract(**x)['net_return_per_unit'])
        self.assertEqual(settle_contract(**x,decimal_price=2,fee_per_unit=.01)['net_return_per_unit'],.99)
    def test_first_half_and_void(self):
        from models.nfl.contextual.settlement import settle_contract
        x=dict(home_score=7,away_score=14,market_type='TOTAL',side='OVER',line=20.5,period='FIRST_HALF',score_period='FIRST_HALF')
        self.assertEqual(settle_contract(**x)['result'],'WIN');self.assertEqual(settle_contract(**x,void=True)['result'],'VOID')
    def test_moneyline_tie(self):
        from models.nfl.contextual.settlement import settle_contract
        x=dict(home_score=20,away_score=20,market_type='MONEYLINE',side='HOME')
        self.assertEqual(settle_contract(**x,tie_policy='REFUND')['result'],'PUSH');self.assertEqual(settle_contract(**x,tie_policy='LOSS')['result'],'LOSS')

if __name__=='__main__':unittest.main()
