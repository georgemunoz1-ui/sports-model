"""Synthetic support-contract tests; not a native full-runtime certification."""
import copy
import unittest
from unittest.mock import patch
from models.nfl.contextual import report_support as R

class Support(unittest.TestCase):
    def setUp(self):
        self.model = {'arms': {name: {'model_id': 'nfl.integrated_context.' + name + '.v1.research',
                       'feature_names': ['epa'] + ([R.FEATURE] if name in R.CERTIFIED_ARMS else []),
                       'training_rows': R.FIT_N} for name in ('base','qb','availability','travel','combined')}}
        self.pin = patch.object(R, 'MODEL_SHA256', R._digest(self.model))
        self.pin.start(); self.addCleanup(self.pin.stop)
    def test_observed_zero_support_only(self):
        out=R.report_support(self.model,{R.FEATURE:0})
        self.assertEqual(out['arms']['combined']['status'],R.PASS)
        self.assertFalse(out['personnel_completeness_verified']); self.assertFalse(out['action_authority'])
    def test_one_and_two_refused(self):
        for v,reason in ((1,'REFUSE_UNQUALIFIED_MISSING_REPORT_REGIME'),(2,'REFUSE_UNSEEN_REPORTING_REGIME')):
            out=R.report_support(self.model,{R.FEATURE:v})
            for a in R.CERTIFIED_ARMS:
                self.assertEqual(out['arms'][a]['status'],reason)
                with self.assertRaisesRegex(ValueError,reason):R.require_selected_support(out,a,'TEST','TEST')
    def test_unaffected_selected_arms_continue(self):
        for v in (0,1,2,None):
            out=R.report_support(self.model,{R.FEATURE:v})
            for a in ('base','qb','travel'):
                self.assertEqual(R.require_selected_support(out,a,'TEST','TEST')['status'],R.NA)
    def test_invalid_values_fail_closed(self):
        for v in (None,True,'0',-1,.5,3,float('nan'),float('inf')):
            out=R.report_support(self.model,{R.FEATURE:v})
            self.assertEqual(out['arms']['combined']['status'],'REFUSE_INVALID_REPORT_MISSING_COUNT')
    def test_changed_artifact_refused_even_at_zero(self):
        m=copy.deepcopy(self.model);m['arms']['combined']['training_rows']+=1
        self.assertEqual(R.report_support(m,{R.FEATURE:0})['arms']['combined']['status'],'REFUSE_UNBOUND_REPORTING_SUPPORT')
    def test_no_feature_mutation(self):
        f={R.FEATURE:2,'epa':.2};old=copy.deepcopy(f)
        R.report_support(self.model,f);self.assertEqual(f,old)
    def test_certificate_counts(self):
        self.assertEqual(sum(R.FIT_COUNTS.values()),R.FIT_N)
        self.assertEqual(R.FIT_COUNTS,{'0':2877,'1':8,'2':0})


class NativeRuntimeSupport(unittest.TestCase):
    """Actual native run and pinned model, synthetic reporting perturbations."""
    @classmethod
    def setUpClass(cls):
        import json
        from pathlib import Path
        from models.nfl.contextual.model import load_artifact
        data=Path(__file__).resolve().parents[1]/'data/nfl/contextual_v1'
        cls.model=load_artifact(data/'model_packed.json')
        cls.recovered=json.loads((data/'recovered_parameters.json').read_text())
        cls.base=json.loads((data/'mnf_base_row.json').read_text())[0]
        cls.context=json.loads((data/'mnf_context_integrated.json').read_text())
        cls.event=json.loads((data/'mnf_event.json').read_text())
        cls.cutoff='2026-09-14T12:00:00Z'
    def inputs(self):
        from models.nfl.contextual import runtime
        return runtime.live_features(self.model,self.recovered,self.base,self.context,self.event,self.cutoff)
    def call(self, arm):
        from models.nfl.contextual import runtime
        return runtime.run(self.model,self.recovered,self.base,self.context,self.event,self.cutoff,1000,
                           model_id=self.model['arms'][arm]['model_id'])
    def test_exact_model_certificate(self):
        self.assertEqual(R._digest(self.model),R.MODEL_SHA256)
        out=R.report_support(self.model,{R.FEATURE:0})
        for a in R.CERTIFIED_ARMS:
            self.assertEqual(out['arms'][a]['status'],R.PASS)
    def test_selected_unsupported_refuses_before_prediction(self):
        from models.nfl.contextual import runtime
        x,audit=self.inputs()
        for count,reason in ((1,'REFUSE_UNQUALIFIED_MISSING_REPORT_REGIME'),(2,'REFUSE_UNSEEN_REPORTING_REGIME')):
            with patch.object(runtime,'live_features',return_value=({**x,R.FEATURE:count},audit)), patch.object(runtime,'predict') as pred:
                with self.assertRaisesRegex(ValueError,reason):self.call('combined')
                pred.assert_not_called()
    def test_selected_qb_preserves_numeric_heads_and_refuses_siblings(self):
        from models.nfl.contextual import runtime
        x,audit=self.inputs()
        p=runtime.predict(self.model['arms']['qb'],{k:x[k] for k in self.model['arms']['qb']['feature_names']})['prediction']
        with patch.object(runtime,'live_features',return_value=({**x,R.FEATURE:2},audit)), patch.object(runtime,'predict',wraps=runtime.predict) as pred:
            bundle,_,scores=self.call('qb')
        self.assertEqual(bundle['prediction'],p)
        self.assertEqual(bundle['features'][R.FEATURE],2)
        self.assertIsNone(scores)
        self.assertFalse(bundle['action_authority'])
        for a in R.CERTIFIED_ARMS:
            self.assertIsNone(bundle['arms'][a]['prediction'])
            self.assertEqual(bundle['reporting_support']['arms'][a]['status'],'REFUSE_UNSEEN_REPORTING_REGIME')
        self.assertEqual({c.args[0]['model_id'] for c in pred.call_args_list},{self.model['arms'][a]['model_id'] for a in ('base','qb','travel')})
    def test_supported_combined_exact_prediction(self):
        from models.nfl.contextual import runtime
        x,audit=self.inputs()
        self.assertEqual(x[R.FEATURE],0)
        p=runtime.predict(self.model['arms']['combined'],{k:x[k] for k in self.model['arms']['combined']['feature_names']})['prediction']
        bundle,_,scores=self.call('combined')
        self.assertEqual(bundle['prediction'],p)
        self.assertEqual(bundle['reporting_support']['arms']['combined']['status'],R.PASS)
        self.assertIsNotNone(scores)
        self.assertFalse(bundle['action_authority'])
