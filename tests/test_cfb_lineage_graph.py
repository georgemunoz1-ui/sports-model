"""Complete synthetic graph tests; these do not measure CFB forecast skill."""
import copy,tempfile,unittest
from research.cfb_lineage.core import *
from research.cfb_lineage.registry import *
from research.cfb_lineage.fixture import build_fixture

class EndGraph(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=Store(self.tmp.name);self.f=build_fixture(self.s)
    def snapshot(self,**changes):
        f=self.f;args=dict(set_hash=f['feature_set'],state_hash=f['state'],event=f['event'],rows=[f['row']],source_hashes={'fixture-pbp':f['source_hash']},cutoff=f['cutoff']);args.update(changes)
        return snapshot(self.s,**args)
    def freeze(self,**changes):
        f=self.f;args=dict(feature_hash=f['features'],model_hash=f['model'],calibration_hash=f['calibration'],projection={'home_win_probability_raw':.5,'home_win_probability':.5},mode='SYNTHETIC_TEST');args.update(changes)
        return freeze_forecast(self.s,**args)
    def test_full_graph_resolves(self):self.assertGreater(self.f['proof']['node_count'],15)
    def test_two_weeks_accumulate_without_duplicate(self):self.assertEqual(self.f['state_feature_value'],1.5)
    def test_frozen_output_declares_no_fitted_forecast(self):
        p=self.s.node(self.f['forecast'])['payload'];self.assertEqual(p['mode'],'SYNTHETIC_TEST');self.assertFalse(p['action_authority']);self.assertEqual(p['simulation']['status'],'NOT_RUN')
    def test_required_feature_absent(self):
        with self.assertRaisesRegex(GateError,'REQUIRED'):self.snapshot(rows=[])
    def test_wrong_player_team_orientation(self):
        r=dict(self.f['row'],team_id='OTHER')
        with self.assertRaisesRegex(GateError,'TEAM_MISMATCH'):self.snapshot(rows=[r])
    def test_wrong_event_week(self):
        r=dict(self.f['row'],week=2)
        with self.assertRaisesRegex(GateError,'WEEK_MISMATCH'):self.snapshot(rows=[r])
    def test_state_sealed_after_cutoff_refused(self):
        n=self.s.node(self.f['state']);n['payload']['created_at']='2099-01-01T00:00:00Z';h=self.s.put(n['kind'],n['payload'],n['parents'])
        with self.assertRaisesRegex(GateError,'STATE_PUBLISHED'):self.snapshot(state_hash=h)
    def test_mixed_pbp_families_refused(self):
        a=dict(self.f['definition'],source_family='cfbfastR_legacy_pbp');a=seal_definition(a)
        b=seal_definition(dict(a,feature_id='cfb.fixture.alternate.v1',source_family='espn_cfb_pbp'))
        with self.assertRaisesRegex(GateError,'MIXED_PBP'):feature_set(self.s,'mixed',[a,b],[])
    def test_calibration_other_model_refused(self):
        n=self.s.node(self.f['calibration']);n['parents']['model']=self.f['feature_set'];h=self.s.put(n['kind'],n['payload'],n['parents'])
        with self.assertRaisesRegex(GateError,'CALIBRATION_MODEL'):self.freeze(calibration_hash=h)
    def test_training_lineage_required(self):
        n=self.s.node(self.f['model']);n['parents'].pop('training_data');h=self.s.put(n['kind'],n['payload'],n['parents'])
        with self.assertRaisesRegex(GateError,'TRAINING_LINEAGE'):self.freeze(model_hash=h)
    def test_no_live_default_override(self):
        with self.assertRaisesRegex(GateError,'LIVE_DEFAULT'):self.freeze(mode='LIVE_DEFAULT')
    def test_no_extra_narrative_numeric_override(self):
        with self.assertRaisesRegex(GateError,'UNSUPPORTED_OUTPUT'):self.freeze(projection={'home_win_probability_raw':.5,'home_win_probability':.5,'confidence':.9})
    def test_model_available_after_cutoff(self):
        n=self.s.node(self.f['model']);n['payload']['available_at']='2099-01-01T00:00:00Z';h=self.s.put(n['kind'],n['payload'],n['parents'])
        c=self.s.node(self.f['calibration']);c['parents']['model']=h;ch=self.s.put(c['kind'],c['payload'],c['parents'])
        with self.assertRaisesRegex(GateError,'AFTER_CUTOFF'):self.freeze(model_hash=h,calibration_hash=ch)
    def test_nonlinear_model_cannot_claim_coefficient(self):
        d=self.f['definition'];p=dict(feature_id=d['feature_id'],feature_set_hash=self.f['feature_set'],target='home_win_probability',model_family='xgboost',coefficient=.2,member_weight=.5)
        m=self.s.node(self.f['model'])['payload']
        with self.assertRaisesRegex(GateError,'NONLINEAR'):check_model_path(p,d,m,self.f['feature_set'])
    def test_parquet_tables_keep_empty_schema(self):
        try:import pyarrow.parquet as pq
        except ImportError:self.skipTest('pyarrow is required in the clean CI environment')
        out=self.s.root/'registry';manifest=export_tables(out,{'feature_definitions':[self.f['definition']]})
        for k,fields in TABLES.items():self.assertEqual(pq.read_table(out/(k+'.parquet')).column_names,fields)
        self.assertEqual(manifest['feature_model_paths']['rows'],0)

if __name__=='__main__':unittest.main()
