"""Synthetic routing regression, not current forecasts or predictive validation."""
import copy,hashlib,json,unittest
from dataclasses import asdict
from pathlib import Path
import pandas as pd
from models.nfl.contextual import base_features as bf
from models.nfl.contextual.recovered_inference import digest
from models.nfl.contextual.qb_assimilation import apply
from models.nfl.contextual.runtime import live_features
from models.nfl.contextual.model import load_artifact
ROOT=Path(__file__).resolve().parents[1]
class Week2Admission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=load_artifact(ROOT/'data/nfl/contextual_v1/model_packed.json')
        cls.recovered=json.loads((ROOT/'data/nfl/contextual_v1/recovered_parameters.json').read_text())
    def fixture(self):
        before={'KC':asdict(bf.TeamState()),'IND':asdict(bf.TeamState())}
        after=copy.deepcopy(before);after['KC']['off_epa']=.1;after['KC']['effective_plays']=30
        event={'event_id':'2026_02_IND_KC','gameday':'2026-09-20','gametime':'13:00','start_time_utc':'2026-09-20T17:00:00Z','home_team':'KC','away_team':'IND','location':'Home'}
        game={'game_id':event['event_id'],'season':2026,'week':2,'home_score':None,'away_score':None,'home_rest':6,'away_rest':7,'roof':'outdoors','temp':70,'wind':5,**event}
        base=bf._feature_row(pd.Series(game),bf.TeamState(**after['KC']),bf.TeamState(**after['IND']))
        base={k:None if pd.isna(v) else v for k,v in base.items()}
        ids=[f'2026_01_A{i}_B{i}' for i in range(16)]
        report={'status':'reconciled','state_update_applied':True,'cutoff_utc':'2026-09-15T22:00:00Z','snapshot':{'sha256':'synthetic-only','source_url':'synthetic-test-only','retrieved_at_utc':'2026-09-15T21:00:00Z'},'state_before_sha256':digest(before),'state_after_sha256':digest(after),'coverage':{'weekly_state_update_eligible':True,'rows':[{'game_id':i,'state_update_eligible':True} for i in ids]}}
        update={'season':2026,'completed_week':1,'parent_model_sha256':digest(self.model),'source_sha256':'synthetic-only','completed_game_ids':ids,'completed_starters':{'KC':'00-0033873','IND':'synthetic-qb'},'aggregates':[{'game_id':ids[0],'passer_player_id':'00-0033873','epa_sum':1.,'dropbacks':30}]}
        update['state_after_sha256']=digest(apply(self.model,update))
        evidence={'audit':report,'state_before':before,'state_after':after,'base_feature_code_sha256':hashlib.sha256(Path(bf.__file__).read_bytes()).hexdigest(),'qb_update':update}
        context={'assimilation':evidence,'personnel':{'event_id':event['event_id'],'source':'synthetic-test-only','source_sha256':'synthetic-only','retrieved_at_utc':'2026-09-15T21:00:00Z','available_by_utc':'2026-09-15T21:00:00Z','state':{'quarterbacks':{'KC':{'id':'00-0033873'},'IND':{'id':'synthetic-qb'}}}}}
        return base,context,event,'2026-09-16T00:00:00Z'
    def invoke(self,b,c,e,t):return live_features(self.model,self.recovered,b,c,e,t)
    def test_valid_week2_evidence_is_not_a_predictive_dimension(self):
        b,c,e,t=self.fixture();x,a=self.invoke(b,c,e,t)
        self.assertIn('qb_quality_diff',x);self.assertNotIn('assimilation',x)
        self.assertNotIn('assimilation',a['recovered_model']['context_admission'])
    def test_missing_assimilation_still_fails(self):
        b,c,e,t=self.fixture();del c['assimilation']
        with self.assertRaisesRegex(ValueError,'EVIDENCE_REQUIRED'):self.invoke(b,c,e,t)
    def test_tampered_state_still_fails(self):
        b,c,e,t=self.fixture();c['assimilation']['state_after']['KC']['off_epa']=99
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):self.invoke(b,c,e,t)
    def test_incomplete_week_still_fails(self):
        b,c,e,t=self.fixture();c['assimilation']['audit']['coverage']['rows'].pop()
        with self.assertRaisesRegex(ValueError,'16_FINALS'):self.invoke(b,c,e,t)
    def test_market_dimension_still_rejected(self):
        b,c,e,t=self.fixture();c['market']={'home_win':.9}
        with self.assertRaisesRegex(ValueError,'UNKNOWN_CONTEXT'):self.invoke(b,c,e,t)
    def test_qb_source_mismatch_still_rejected(self):
        b,c,e,t=self.fixture();c['assimilation']['qb_update']['source_sha256']='changed'
        with self.assertRaisesRegex(ValueError,'QB_SOURCE_MISMATCH'):self.invoke(b,c,e,t)
    def test_state_not_assimilated_into_base_still_rejected(self):
        b,c,e,t=self.fixture();b['epa_matchup_edge']=0
        with self.assertRaisesRegex(ValueError,'NOT_ACTIVE_IN_RUN'):self.invoke(b,c,e,t)
    def test_future_assimilation_still_rejected(self):
        b,c,e,t=self.fixture();c['assimilation']['audit']['cutoff_utc']='2026-09-21T00:00:00Z'
        with self.assertRaisesRegex(ValueError,'AFTER_CUTOFF'):self.invoke(b,c,e,t)
if __name__=='__main__':unittest.main()
