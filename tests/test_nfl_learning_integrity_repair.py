import copy,hashlib,json,tempfile,unittest
from pathlib import Path
import pandas as pd
from models.nfl.contextual import assimilation as ass
from models.nfl.contextual import qb_assimilation as qa
from models.nfl.contextual import base_features as bf
from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.recovered_inference import digest

class IntegrityRepair(unittest.TestCase):
    def setUp(self):
        self.games=pd.DataFrame([
          {'game_id':'2026_02_A_B','season':2026,'week':2,'home_team':'B','away_team':'A','gameday':'2026-09-17','gametime':'20:15','home_score':20,'away_score':10,'home_qb_id':'qbB','away_qb_id':'qbA'},
          {'game_id':'2026_02_C_D','season':2026,'week':2,'home_team':'D','away_team':'C','gameday':'2026-09-20','gametime':'13:00','home_score':21,'away_score':17,'home_qb_id':'qbD','away_qb_id':'qbC'}])
        self.binding=ass.authoritative_schedule_binding(self.games)
    def test_truncated_schedule_rejected(self):
        with self.assertRaisesRegex(ValueError,'AUTHORITATIVE_SCHEDULE_COVERAGE_MISMATCH'):
            ass.validate_schedule_binding(self.games.iloc[[0]],self.binding)
    def test_out_of_scope_pbp_rejected_before_aggregation(self):
        p=pd.DataFrame({'game_id':['2026_02_A_B','2026_03_X_Y'],'play_id':[1,1]})
        with self.assertRaisesRegex(ValueError,'OUT_OF_SCOPE_PBP'):
            ass.scope_pbp_to_schedule(p,self.games)
    def test_transition_identity_deterministic_and_parent_bound(self):
        rows=[{'game_id':'2026_02_A_B','content_sha256':'a'},{'game_id':'2026_02_C_D','content_sha256':'b'}]
        a=ass.transition_identity('parent',self.binding,rows);b=ass.transition_identity('parent',self.binding,list(reversed(rows)))
        self.assertEqual(a,b);self.assertNotEqual(a,ass.transition_identity('other',self.binding,rows))
    def test_qb_week2_to_week3_chain_without_second_offseason_shrink(self):
        artifact=load_artifact(Path(__file__).resolve().parents[1]/'data/nfl/contextual_v1/model_packed.json')
        parent=qa.offseason_prior(artifact,2026);parent['completed_week']=1
        before=copy.deepcopy(parent['qb_ratings'])
        ev={'season':2026,'completed_week':2,'completed_game_ids':['2026_02_A_B'],'completed_starters':{'A':'qbA','B':'qbB'},
            'aggregates':[{'game_id':'2026_02_A_B','passer_player_id':'qbA','epa_sum':3.0,'dropbacks':30}]}
        state=qa.apply_to_parent(parent,ev)
        untouched=next(k for k in before if k!='qbA')
        self.assertEqual(state['qb_ratings'][untouched],before[untouched])
        self.assertEqual(state['completed_week'],2)
        with self.assertRaisesRegex(ValueError,'DUPLICATE_QB_STATE_TRANSITION'):qa.apply_to_parent(state,{**ev,'completed_week':3})
    def test_qb_parent_week_mismatch_rejected(self):
        parent={'season':2026,'completed_week':1,'qb_ratings':{},'last_qb':{},'processed_player_games':[]}
        with self.assertRaisesRegex(ValueError,'PARENT_MISMATCH'):
            qa.apply_to_parent(parent,{'season':2026,'completed_week':3,'completed_game_ids':[],'completed_starters':{},'aggregates':[]})

if __name__=='__main__':unittest.main()
