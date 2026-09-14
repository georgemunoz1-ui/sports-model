import copy,datetime as dt,json,tempfile,unittest
from pathlib import Path
import numpy as np
from pipelines.cards.adapters import nfl
from models.nfl.contextual.runtime import run,persist_run
from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.recovered_inference import digest
from models.nfl.modes.core import devig,state_features,state_from_nflverse,predict_live,categorical_simulation
from models.nfl.modes.runtime import market_values

ROOT=Path(__file__).resolve().parents[1];D=ROOT/'data/nfl/contextual_v1';M=ROOT/'data/nfl/modes_v1'
class Modes(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.f=load_artifact(D/'model_packed.json');cls.r=json.loads((D/'recovered_parameters.json').read_text());cls.base=json.loads((D/'mnf_base_row.json').read_text())[0];cls.c=json.loads((D/'mnf_context_integrated.json').read_text());cls.e=json.loads((D/'mnf_event.json').read_text());cls.market=nfl.mode_artifact('enhanced_pregame');cls.live=nfl.mode_artifact('live');cls.cut='2026-09-14T12:00:00Z'
  cls.mp={k:cls.e[k] for k in ['event_id','home_team','away_team']};cls.mp.update({'source':'UNIT_TEST_FIXTURE_NOT_ACTUAL_QUOTE','source_sha256':'a'*64,'observed_at_utc':'2026-09-14T11:59:00Z','retrieved_at_utc':'2026-09-14T11:59:01Z','period':'FULL_GAME','odds_format':'AMERICAN','state':'PREGAME','quotes':{'home_moneyline':-132,'away_moneyline':112,'home_spread':-2.5,'total_line':43.5}})
  cls.sp={k:cls.e[k] for k in ['event_id','home_team','away_team']};cls.sp.update({'source':'UNIT_TEST_SYNTHETIC_STATE','source_sha256':'b'*64,'observed_at_utc':'2026-09-15T01:00:00Z','retrieved_at_utc':'2026-09-15T01:00:01Z','effective_at_utc':'2026-09-15T00:59:59Z','state_boundary':'PRE_PLAY','game_status':'IN_PROGRESS','features':{'home_score':10,'away_score':7,'seconds_remaining':2400,'quarter_seconds_remaining':600,'quarter':2,'possession':'AWAY','yardline_100':50,'down':2,'yards_to_go':6,'home_timeouts':3,'away_timeouts':2}})
 def enhanced(self,**kw):
  return run(self.f,self.r,self.base,self.c,self.e,self.cut,1000,mode='enhanced_pregame',mode_artifact=self.market,market=kw.get('market',self.mp),model_id=kw.get('model_id',self.market['model_id']),live_state=kw.get('live_state'))
 def test_devig_known_pair_and_orientation(self):
  p=132/232/(132/232+100/212);self.assertAlmostEqual(devig(-132,112),p,places=14);v,_=market_values(self.mp,self.e,self.cut);self.assertEqual(v['home_margin'],2.5)
 def test_enhanced_runs_fitted_selected_weights(self):
  b,w,s=self.enhanced();self.assertTrue(b['market_input']);self.assertEqual(b['mode'],'enhanced_pregame');self.assertEqual(w.shape,(1000,));self.assertEqual(s.shape,(1000,2));self.assertEqual(b['prediction']['home_win'],b['market_benchmark']['home_win']);self.assertEqual(b['contribution_trace']['home_win']['football_weight'],0)
 def test_bad_id_or_wrong_football_artifact_never_fallback(self):
  with self.assertRaisesRegex(ValueError,'EXACT_MODEL'):self.enhanced(model_id='bad')
  bad=copy.deepcopy(self.market);bad['football_artifact_sha256']='bad'
  with self.assertRaisesRegex(ValueError,'ARTIFACT_MISMATCH'):run(self.f,self.r,self.base,self.c,self.e,self.cut,100,mode='enhanced_pregame',mode_artifact=bad,market=self.mp)
 def test_pregame_market_and_live_time_firewalls(self):
  late=copy.deepcopy(self.mp);late['observed_at_utc']='2026-09-15T01:00:00Z';late['retrieved_at_utc']='2026-09-15T01:00:01Z'
  with self.assertRaisesRegex(ValueError,'POST_CUTOFF'):self.enhanced(market=late)
  with self.assertRaisesRegex(ValueError,'LIVE_INPUT_IN_PREGAME'):self.enhanced(live_state=self.sp)
  with self.assertRaisesRegex(ValueError,'FOOTBALL_ONLY'):run(self.f,self.r,self.base,self.c,self.e,self.cut,100,market=self.mp)
 def test_live_requires_start_and_fresh_state(self):
  with self.assertRaisesRegex(ValueError,'GAME_NOT_STARTED'):run(self.f,self.r,self.base,self.c,self.e,self.cut,100,mode='live',mode_artifact=self.live,market=self.mp,live_state=self.sp)
  with self.assertRaisesRegex(ValueError,'STALE_LIVE'):run(self.f,self.r,self.base,self.c,self.e,'2026-09-15T01:03:00Z',100,mode='live',mode_artifact=self.live,market=self.mp,live_state=self.sp)
 def test_live_end_to_end_three_way(self):
  args=(self.f,self.r,self.base,self.c,self.e,'2026-09-15T01:00:02Z',10000)
  a,w,s=run(*args,mode='live',mode_artifact=self.live,market=self.mp,live_state=self.sp);b,v,_=run(*args,mode='live',mode_artifact=self.live,market=self.mp,live_state=self.sp)
  self.assertEqual(a,b);self.assertTrue(np.array_equal(w,v));self.assertIsNone(s);self.assertAlmostEqual(sum(a['prediction'].values()),1);self.assertGreater(a['prediction']['TIE'],0)
 def test_actual_postplay_scores_cannot_enter_features(self):
  row={'game_id':self.e['event_id'],'home_team':'KC','away_team':'DEN','posteam':'KC','posteam_score':0,'defteam_score':3,'total_home_score':6,'posteam_score_post':6,'qtr':2,'quarter_seconds_remaining':866,'game_seconds_remaining':2666,'down':2,'ydstogo':3,'yardline_100':18,'home_timeouts_remaining':3,'away_timeouts_remaining':3}
  a=state_from_nflverse(row,self.e);row['total_home_score']=99;row['posteam_score_post']=99;b=state_from_nflverse(row,self.e);self.assertEqual(a,b);self.assertEqual(a['home_score'],0)
 def test_overtime_clock_normalization(self):
  row={'game_id':self.e['event_id'],'home_team':'KC','away_team':'DEN','posteam':'KC','posteam_score':20,'defteam_score':20,'qtr':5,'quarter_seconds_remaining':400,'game_seconds_remaining':400,'down':2,'ydstogo':3,'yardline_100':18,'home_timeouts_remaining':2,'away_timeouts_remaining':2};s=state_from_nflverse(row,self.e);self.assertEqual(s['seconds_remaining'],0);self.assertEqual(s['quarter_seconds_remaining'],400);self.assertTrue(np.isfinite(state_features(s,.5)).all())
 def test_future_writer_cutoff_never_saved(self):
  b,w,s=self.enhanced();b['cutoff_utc']='2099-01-01T00:00:00Z'
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaisesRegex(ValueError,'FUTURE_INFORMATION'):persist_run(Path(d)/'future',b,w,s,{})
   self.assertFalse((Path(d)/'future').exists())
 def test_market_wrong_product_event_or_future_model(self):
  wrong=copy.deepcopy(self.mp);wrong['period']='FIRST_HALF'
  with self.assertRaisesRegex(ValueError,'PRODUCT_SCHEMA'):self.enhanced(market=wrong)
  wrong=copy.deepcopy(self.mp);wrong['home_team']='DEN'
  with self.assertRaisesRegex(ValueError,'EVENT_BINDING'):self.enhanced(market=wrong)
  bad=copy.deepcopy(self.market);bad['deployment_packaged_at_utc']='2026-09-14T13:00:00Z'
  with self.assertRaisesRegex(ValueError,'ARTIFACT_AFTER_CUTOFF'):run(self.f,self.r,self.base,self.c,self.e,self.cut,100,mode='enhanced_pregame',mode_artifact=bad,market=self.mp)
 def test_live_raw_state_rejects_extra_or_inconsistent_fields(self):
  s=copy.deepcopy(self.sp['features']);s['posteam_score_post']=99
  with self.assertRaisesRegex(ValueError,'EXACT_LIVE'):state_features(s,.5)
  s=copy.deepcopy(self.sp['features']);s['seconds_remaining']=20
  with self.assertRaisesRegex(ValueError,'CLOCK_INCONSISTENT'):state_features(s,.5)
if __name__=='__main__':unittest.main()
