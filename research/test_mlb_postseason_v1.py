import copy
import unittest
import tempfile
import json
from pathlib import Path
import numpy as np
from research.mlb_postseason_v1 import simulate,validate_inputs,run_event,MODEL_ID,save_once,sha,stamp,ROOT

def fixture():
    s={'era':4.2,'gs':25,'k':22.,'bb':8.5,'observed_game_ids':['fixture']}
    return {'game_type':'F','home_team':'HOME','away_team':'AWAY','through_date':'2026-09-29','slate_date':'2026-09-30','away_form':{'rf':4.45,'ra':4.45,'games':162},'home_form':{'rf':4.45,'ra':4.45,'games':162},'sp_away':s,'sp_home':copy.deepcopy(s),'park_factor':1.0}

class ContractTests(unittest.TestCase):
    def test_replay_and_complete_paths(self):
        r,d=simulate(fixture(),100000,310930);r2,d2=simulate(fixture(),100000,310930)
        self.assertEqual(r,r2)
        for k in d:self.assertTrue(np.array_equal(d[k],d2[k]))
        self.assertEqual(len(d['postseason_home_win']),100000)
        self.assertEqual(r['unresolved_paths'],0)
        self.assertEqual(r['home_win_probability']+r['away_win_probability'],1)
    def test_non_ties_unchanged(self):
        _,d=simulate(fixture(),20000,91);m=d['nine_inning_home_runs']!=d['nine_inning_away_runs']
        self.assertTrue(np.array_equal(d['postseason_home_win'][m],d['baseline_home_win'][m]))
        self.assertTrue(np.all(d['extra_innings'][~m]>=1));self.assertTrue(np.all(d['extra_innings'][m]==0))
    def test_same_day_rejected(self):
        x=fixture();x['through_date']=x['slate_date']
        with self.assertRaisesRegex(ValueError,'SAME_DAY'):validate_inputs(x)
    def test_regular_season_rejected(self):
        x=fixture();x['game_type']='R'
        with self.assertRaisesRegex(ValueError,'NOT_POSTSEASON'):validate_inputs(x)
    def test_missing_or_invalid_starter_rejected(self):
        for v in (None,float('nan'),-1,True):
            x=fixture();x['sp_home']['era']=v
            with self.assertRaises(ValueError):validate_inputs(x)
    def test_effect_direction(self):
        x=fixture();low,_=simulate(x,100000,919);x['home_form']['rf']=6.;high,_=simulate(x,100000,919)
        self.assertGreater(high['home_win_probability'],low['home_win_probability'])
    def test_no_unsupported_products(self):
        r,_=simulate(fixture(),1000,123);self.assertIsNone(r['score_total_runline_outputs']);self.assertFalse(r['action_authority'])
    def test_writer_refuses_post_start_without_diagnostic(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);x=dict(fixture(),event_id='TEST',start_time_utc='2000-01-01T00:00:00Z',captured_status='Final')
            save_once(p/'sources/raw.json',{'test_only':True})
            rec={'status':'CAPTURED','retrieved_at_utc':stamp(),'raw_path':'raw.json','raw_sha256':sha(p/'sources/raw.json')}
            save_once(p/'package.json',{'model_id':MODEL_ID,'events':[x],'source_receipts':[rec]})
            save_once(p/'contract.json',{'model_id':MODEL_ID,'code_pins':{'research/mlb_postseason_v1.py':sha(ROOT/'research/mlb_postseason_v1.py')}})
            save_once(p/'review.json',{'reviewed_at_utc':stamp(),'package_sha256':sha(p/'package.json'),'reviewed_event_ids':['TEST']})
            with self.assertRaisesRegex(ValueError,'POST_START'):
                run_event(x,p/'out',p/'package.json',p/'contract.json',p/'review.json')
            self.assertFalse((p/'out').exists())
    def test_changed_review_binding_refused(self):
        with tempfile.TemporaryDirectory()as d:
            p=Path(d);x=fixture()
            save_once(p/'package.json',{'model_id':MODEL_ID,'events':[x]})
            save_once(p/'contract.json',{'model_id':MODEL_ID})
            save_once(p/'review.json',{'package_sha256':'wrong','reviewed_event_ids':[]})
            with self.assertRaisesRegex(ValueError,'PACKAGE_OR_AGENT_REVIEW'):
                run_event(x,p/'out',p/'package.json',p/'contract.json',p/'review.json')
            self.assertFalse((p/'out').exists())

if __name__=='__main__':unittest.main()
