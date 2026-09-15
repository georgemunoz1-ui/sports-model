"""Synthetic contract tests; historical calibration is explicitly out of scope."""
import copy,json,unittest,hashlib
from dataclasses import asdict
from pathlib import Path
import numpy as np
import pandas as pd
from models.nfl.contextual import base_features as bf
from models.nfl.contextual.week2 import selection,applies,require_assimilation,coherence,STATE_FEATURES
from models.nfl.contextual.recovered_inference import digest
from models.nfl.contextual.joint_distribution import kernel,summary,contract
from models.nfl.contextual.model import simulate_joint

class Week2(unittest.TestCase):
    def test_failed_and_unscreened_models_cannot_headline(self):
        for arm in ('combined','availability','travel','base'):
            with self.assertRaisesRegex(ValueError,'HEADLINE_NOT_ELIGIBLE'):
                selection(f'nfl.integrated_context.{arm}.v1.research',headline=True)
        self.assertEqual(selection('nfl.integrated_context.combined.v1.research')['presentation_role'],'EXPERIMENTAL_ONLY')
    def test_qb_default_selected_without_official_promotion(self):
        s=selection('nfl.integrated_context.qb.v1.research',headline=True)
        self.assertTrue(s['headline_eligible']);self.assertFalse(s['official_eligible'])
    def test_week_cannot_be_spoofed(self):
        with self.assertRaisesRegex(ValueError,'BINDING'):applies({'season':2026,'week':1},{'event_id':'2026_02_IND_KC'})
    def fixture(self):
        before={'KC':asdict(bf.TeamState()),'IND':asdict(bf.TeamState())}
        after=copy.deepcopy(before);after['KC']['off_epa']=.1;after['KC']['effective_plays']=30
        event={'event_id':'2026_02_IND_KC','gameday':'2026-09-20','gametime':'13:00','home_team':'KC','away_team':'IND'}
        game={'game_id':event['event_id'],'season':2026,'week':2,'home_score':None,'away_score':None,'home_rest':6,'away_rest':7,'location':'Home','roof':'outdoors','temp':None,'wind':None,**event}
        base=bf._feature_row(pd.Series(game),bf.TeamState(**after['KC']),bf.TeamState(**after['IND']))
        rows=[{'game_id':f'2026_01_A{i}_B{i}','state_update_eligible':True} for i in range(16)]
        report={'status':'reconciled','state_update_applied':True,'cutoff_utc':'2026-09-15T22:00:00Z','snapshot':{'sha256':'synthetic','source_url':'synthetic-test-only','retrieved_at_utc':'2026-09-15T21:00:00Z'},'state_before_sha256':digest(before),'state_after_sha256':digest(after),'coverage':{'weekly_state_update_eligible':True,'rows':rows}}
        context={'assimilation':{'audit':report,'state_before':before,'state_after':after,'base_feature_code_sha256':hashlib.sha256(Path(bf.__file__).read_bytes()).hexdigest()}}
        return base,context,event,'2026-09-16T00:00:00Z'
    def test_missing_assimilation_rejected(self):
        b,c,e,t=self.fixture()
        with self.assertRaisesRegex(ValueError,'EVIDENCE_REQUIRED'):require_assimilation(b,{},e,t)
    def test_recomputed_state_is_active(self):
        b,c,e,t=self.fixture();a=require_assimilation(b,c,e,t)
        self.assertIn('epa_matchup_edge',a['feature_changes']);self.assertFalse(a['official_gamebook_clearance'])
    def test_stale_base_rejected(self):
        b,c,e,t=self.fixture();b['epa_matchup_edge']=0
        with self.assertRaisesRegex(ValueError,'NOT_ACTIVE_IN_RUN'):require_assimilation(b,c,e,t)
    def test_incomplete_week_rejected(self):
        b,c,e,t=self.fixture();c['assimilation']['audit']['coverage']['rows'].pop()
        with self.assertRaisesRegex(ValueError,'16_FINALS'):require_assimilation(b,c,e,t)
    def test_future_evidence_rejected(self):
        b,c,e,t=self.fixture()
        with self.assertRaisesRegex(ValueError,'AFTER_CUTOFF'):require_assimilation(b,c,e,'2026-09-15T20:00:00Z')
    def test_state_tampering_rejected(self):
        b,c,e,t=self.fixture();c['assimilation']['state_after']['KC']['off_epa']=2
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):require_assimilation(b,c,e,t)
    def test_exact_kernel_matches_sampler(self):
        pool=np.tile([[10,-10],[-10,10],[0,0]],(40,1))
        s,w=kernel(0,40,.55,pool,.02);a=summary(s,w)
        draws,mc=simulate_joint(0,40,.55,pool,.02,'synthetic-reproducibility',100000)
        self.assertAlmostEqual(a['p_home_win_conditional_non_tie'],.55)
        self.assertAlmostEqual(a['mean_total'],40)
        self.assertLess(abs(mc['mean_margin']-a['mean_margin']),.2)
        self.assertAlmostEqual(sum(contract(s,w,'SPREAD','HOME',-2.5)[k] for k in ('win','push_or_refund','loss')),1)
    def test_one_distribution_can_have_opposite_mean_and_majority(self):
        s=np.array([[21,20],[0,30]]);w=np.array([.6,.4]);a=summary(s,w)
        self.assertGreater(a['p_home_win'],.5);self.assertLess(a['mean_margin'],0)
        self.assertTrue(coherence({'home_win':.6,'home_margin':2},a)['cross_head_direction_disagreement'])
    def test_missing_stratum_rejected(self):
        with self.assertRaisesRegex(ValueError,'SUPPORT_MISSING'):kernel(0,40,.5,np.zeros((100,2)),.01)

if __name__=='__main__':unittest.main()
