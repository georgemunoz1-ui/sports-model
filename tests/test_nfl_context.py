import copy,datetime as dt,json,unittest
from pathlib import Path
import numpy as np
import pandas as pd
from models.nfl.contextual.features import availability_features,prepare_reports,qb_features,travel_features,build_history
from models.nfl.contextual.model import load_artifact,predict_frame,simulate_joint,price_contract
from models.nfl.contextual.recovered_inference import predict,utc
from models.nfl.contextual.runtime import run,persist_run
from pipelines.cards.adapters import nfl

ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data/nfl/contextual_v1'
class Integrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact=load_artifact(DATA/'model_packed.json');cls.recovered=json.loads((DATA/'recovered_parameters.json').read_text());cls.base=json.loads((DATA/'mnf_base_row.json').read_text())[0];cls.context=json.loads((DATA/'mnf_context_integrated.json').read_text());cls.event=json.loads((DATA/'mnf_event.json').read_text());cls.cutoff='2026-09-14T12:00:00Z'
    def test_exact_feature_firewall(self):
        p=self.artifact['arms']['combined'];x={k:0 for k in p['feature_names']};x['moneyline']=-120
        with self.assertRaisesRegex(ValueError,'EXACT_FEATURE'):predict(p,x)
    def test_postcutoff_weather_rejected(self):
        c=copy.deepcopy(self.context);c['weather']['published_at_utc']='2026-09-14T13:00:00Z'
        with self.assertRaisesRegex(ValueError,'POST_CUTOFF'):run(self.artifact,self.recovered,self.base,c,self.event,self.cutoff,1000)
    def test_wrong_event_binding(self):
        e=copy.deepcopy(self.event);e['home_team']='DEN';e['away_team']='KC'
        with self.assertRaisesRegex(ValueError,'HOME_AWAY'):run(self.artifact,self.recovered,self.base,self.context,e,self.cutoff,1000)
    def test_night_low_not_hourly(self):
        c=copy.deepcopy(self.context);c['weather']['temperature_kind']='OVERNIGHT_LOW'
        with self.assertRaisesRegex(ValueError,'QUANTITY'):run(self.artifact,self.recovered,self.base,c,self.event,self.cutoff,1000)
    def test_latest_prestart_report(self):
        r={'home_team':'HOU','away_team':'KC','gameday':'2024-12-15','gametime':'13:00'}
        rows=[{'team':'HOU','gsis_id':'p','full_name':'Test','position':'TE','report_status':s,'practice_status':'DNP','date_modified':t} for s,t in [('Questionable','2024-12-15T03:00:00Z'),('Out','2024-12-15T14:00:00Z'),('Probable','2024-12-15T19:00:00Z')]]
        reports,late,_=prepare_reports(pd.DataFrame(rows),r)
        self.assertEqual(reports['HOU'][0]['report_status'],'Out');self.assertEqual(late,1)
    def test_full_practice_not_unrestricted(self):
        r={'home_team':'KC','away_team':'DEN','gameday':'2026-09-14'}
        f,a=availability_features(r,{'KC':[{'full_name':'Receiver','position':'WR','report_status':'QUESTIONABLE','practice_status':'FULL'}],'DEN':[]},{})
        self.assertEqual(f['WRTE_questionable_diff'],1);self.assertEqual(f['WRTE_out_diff'],0)
    def test_unknown_role_not_one_full_starter(self):
        f,a=availability_features({'home_team':'KC','away_team':'DEN','gameday':'2026-09-14'},{'KC':[{'full_name':'Unknown','position':'T','report_status':'OUT'}],'DEN':[]},{})
        self.assertEqual(f['OL_out_diff'],1);self.assertEqual(f['OL_out_snap_diff'],0);self.assertEqual(f['out_role_unknown_count'],1);self.assertIsNone(a[0]['prior_snap_share'])
    def test_feature_effect_and_trace(self):
        b,_,_=run(self.artifact,self.recovered,self.base,self.context,self.event,self.cutoff,1000)
        c=copy.deepcopy(self.context);c['personnel']['state']['injury_observations']=[x for x in c['personnel']['state']['injury_observations'] if x['player']!='Josh Simmons']
        alt,_,_=run(self.artifact,self.recovered,self.base,c,self.event,self.cutoff,1000)
        self.assertNotEqual(b['prediction']['home_margin'],alt['prediction']['home_margin'])
        self.assertEqual(b['arms']['base'],alt['arms']['base'])
        for t,v in b['arms']['combined']['contribution_trace'].items():self.assertAlmostEqual(v['linear_value'],v['intercept']+sum(v['features'].values()),places=12)
    def test_travel_relocation_unknown(self):
        r={'home_team':'KC','away_team':'LV','season':2015,'gameday':'2015-09-14','gametime':'20:15','location':'Home'}
        self.assertEqual(travel_features(r,self.artifact['airports'])['travel_unknown'],1)
    def test_current_travel_east_one_zone(self):
        r={**self.base,**self.event};f=travel_features(r,self.artifact['airports']);self.assertEqual(f['away_east_hours'],1);self.assertTrue(.8<f['away_travel_1000km']<.9)
    def test_weekly_no_future_qb_or_snap_leak(self):
        base=pd.DataFrame([{'game_id':'g1','season':2020,'week':1,'home_margin':2},{'game_id':'g2','season':2020,'week':2,'home_margin':3}])
        games=pd.DataFrame([{'game_id':f'g{i}','season':2020,'week':i,'home_team':'KC','away_team':'DEN','gameday':f'2020-09-{6+7*(i-1):02d}','gametime':'13:00','home_qb_id':'q1','away_qb_id':'q2','location':'Home'} for i in [1,2]])
        inj=pd.DataFrame(columns=['season','week','team']);snaps=pd.DataFrame(columns=['season','week']);q=pd.DataFrame([{'game_id':'g1','season':2020,'week':1,'passer_player_id':'q1','epa_sum':10.,'dropbacks':30},{'game_id':'g2','season':2020,'week':2,'passer_player_id':'q1','epa_sum':9999.,'dropbacks':30}])
        a,_,_=build_history(base,games,inj,snaps,q,self.artifact['airports']);q.loc[1,'epa_sum']=-9999;b,_,_=build_history(base,games,inj,snaps,q,self.artifact['airports'])
        self.assertEqual(a.qb_quality_diff.tolist(),b.qb_quality_diff.tolist());self.assertEqual(a.iloc[0].qb_quality_diff,0);self.assertGreater(a.iloc[1].qb_quality_diff,0)
    def test_joint_replay_and_tie_mass(self):
        args=(0.,45.,.55,self.artifact['final_score_residuals'],self.artifact['simulation_v2']['tie_rate'],'test',100000)
        a,s=simulate_joint(*args);b,t=simulate_joint(*args);self.assertTrue(np.array_equal(a,b));self.assertEqual(s,t);self.assertAlmostEqual(s['p_home_win']+s['p_away_win']+s['p_tie'],1)
        self.assertLess(abs(s['p_home_win_conditional_non_tie']-.55),.006);self.assertLess(s['p_tie'],.01)
    def test_product_settlement(self):
        scores=np.array([[23,20],[20,23],[20,20]])
        s=price_contract(scores,'SPREAD','HOME',-3);self.assertAlmostEqual(s['push_or_refund'],1/3);self.assertAlmostEqual(s['loss'],2/3)
        with self.assertRaisesRegex(ValueError,'TIE_CONTRACT'):price_contract(scores,'MONEYLINE','HOME')
        with self.assertRaisesRegex(ValueError,'PERIOD'):price_contract(scores,'TOTAL','OVER',43.5,'FIRST_HALF')
    def test_canonical_loader_and_zero_dose(self):
        from scripts.generate_card_force import load_adapter,normalize
        self.assertEqual(load_adapter('nfl').__name__,nfl.__name__)
        e=nfl.load_schedule('2026-09-14',self.cutoff)[0];c=nfl.build_context([e],self.cutoff);raw=nfl.forecast_event(e,c,1000);row=normalize(e,raw)
        self.assertEqual(row['dose'],0);self.assertEqual(row['model_id'],'nfl.integrated_context.combined.v1.research');self.assertIn('score_simulation',row['diagnostics'])
    def test_explicit_arm_no_fallback(self):
        args=(self.artifact,self.recovered,self.base,self.context,self.event,self.cutoff,1000)
        with self.assertRaisesRegex(ValueError,'EXACT_MODEL_ID_REQUIRED'):run(*args,model_id='missing')
        b,_,scores=run(*args,model_id=self.artifact['arms']['qb']['model_id'])
        e=nfl.load_schedule('2026-09-14',self.cutoff)[0];c=nfl.build_context([e],self.cutoff)
        with self.assertRaisesRegex(ValueError,'EXACT_MODEL_ID_REQUIRED'):nfl.forecast_event(e,c,1000,model_id='')
        self.assertEqual(b['selected_arm'],'qb');self.assertEqual(b['prediction'],b['arms']['qb']['prediction'])
        self.assertIsNone(scores);self.assertEqual(b['score_simulation']['status'],'UNAVAILABLE_FOR_SELECTED_ARM')
        self.assertNotIn('AIRPORT_TRAVEL_PROXY',b['current_context_numerically_applied'])
    def test_information_regime_no_relabeling(self):
        args=(self.artifact,self.recovered,self.base,self.context,self.event,self.cutoff,1000)
        for mode in ('official_pregame','postgame_research','typo'):
            with self.assertRaisesRegex(ValueError,'MODE_UNAVAILABLE'):run(*args,mode=mode)
        for mode in ('enhanced_pregame','live'):
            with self.assertRaisesRegex(ValueError,'FITTED_MODE_ARTIFACT_REQUIRED'):run(*args,mode=mode)
        c=copy.deepcopy(self.context);c['market']={'home_probability':.8}
        with self.assertRaisesRegex(ValueError,'UNKNOWN_CONTEXT'):run(self.artifact,self.recovered,self.base,c,self.event,self.cutoff,1000)
    def test_coverage_does_not_claim_observed_workload(self):
        from models.nfl.contextual.operating import coverage
        from models.nfl.contextual.runtime import live_features
        x,a=live_features(self.artifact,self.recovered,self.base,self.context,self.event,self.cutoff)
        x['wind_mph']=None
        out=coverage(self.artifact['arms']['combined'],x,a)
        self.assertEqual(out['matrix_columns_declared'],100);self.assertIn('wind_mph',out['imputed_feature_names'])
        self.assertIn('UNKNOWN',out['workload_source']);self.assertTrue(out['matrix_coverage_is_not_source_completeness'])
    def test_missing_date_not_zero_slate(self):
        with self.assertRaisesRegex(ValueError,'DATE_NOT_CAPTURED'):nfl.load_schedule('2026-09-21',self.cutoff)

if __name__=='__main__':unittest.main()
