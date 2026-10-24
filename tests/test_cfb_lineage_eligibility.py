"""Do not force an ensemble; do not admit refused feature rows."""
import tempfile,unittest
from research.cfb_lineage.core import Store,GateError
from research.cfb_lineage.registry import active_eligible,snapshot,validate_observation
from research.cfb_lineage.fixture import build_fixture

class Eligibility(unittest.TestCase):
    def setUp(self):
        self.o={'validation_status':'PASS','as_of_eligible':True,'is_missing':False}
        self.p={'path_status':'FITTED','path_end_state':'REACHES_STANDALONE_FORECAST','member_weight':None,'ensemble_id':None}
        self.e={'decision':'PROMOTION_CANDIDATE','prospective_gate_passed':True,'integrity_gate_passed':True}
    def test_standalone_need_not_be_forced_into_ensemble(self):self.assertTrue(active_eligible(self.o,self.p,self.e))
    def test_zero_weight_ensemble_not_active(self):
        self.p.update(path_end_state='REACHES_FINAL_FORECAST',member_weight=0,ensemble_id='e');self.assertFalse(active_eligible(self.o,self.p,self.e))
    def test_nonzero_weight_without_oos_gate_not_active(self):
        self.p.update(path_end_state='REACHES_FINAL_FORECAST',member_weight=.5,ensemble_id='e');self.e['prospective_gate_passed']=False
        self.assertFalse(active_eligible(self.o,self.p,self.e))
    def test_failed_eligibility_cannot_enter_snapshot(self):
        with tempfile.TemporaryDirectory() as t:
            s=Store(t);f=build_fixture(s);r=dict(f['row'],as_of_eligible=False)
            with self.assertRaisesRegex(GateError,'NOT_ELIGIBLE'):snapshot(s,f['feature_set'],f['state'],f['event'],[r],{'fixture-pbp':f['source_hash']},f['cutoff'])
    def test_infinite_denominator_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            s=Store(t);f=build_fixture(s);r=dict(f['row'],feature_value_raw=0.,feature_value_model=0.,numerator=1.,denominator=float('inf'))
            with self.assertRaisesRegex(GateError,'DENOMINATOR'):validate_observation(f['definition'],r,s.node(f['source_hash'])['payload'],f['cutoff'])
if __name__=='__main__':unittest.main()
