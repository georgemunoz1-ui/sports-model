from __future__ import annotations

import unittest

from research.news_information.benchmark import score_ensemble, score_event_extraction
from research.news_information.ensemble import consensus, destructive_claim_gate
from research.news_information.model_adapters import InjectedBackendAdapter, candidate_operations


class EnsembleBenchmarkTests(unittest.TestCase):
    def output(self,candidate,event_type):
        return {"status":"PASS","candidate_id":candidate,"payload":[{"event_type":event_type,"subject_id":"P1"}]}

    def test_consensus_and_conflict_are_retained(self):
        c=consensus([self.output("gliner25_base","PLAYER_OUT"),self.output("sports_injury_ner","PLAYER_OUT")],subject_id="P1")
        self.assertEqual(c["cross_model_state"],"CONSENSUS"); self.assertEqual(c["event_type"],"PLAYER_OUT")
        c=consensus([self.output("gliner25_base","PLAYER_OUT"),self.output("sports_injury_ner","PLAYER_ACTIVE")],subject_id="P1")
        self.assertEqual(c["cross_model_state"],"CONFLICTING"); self.assertIsNone(c["event_type"])

    def test_destructive_claim_never_grants_forecast_authority(self):
        g=destructive_claim_gate(event_type="PLAYER_OUT",cross_model_state="CONSENSUS",source_tier=1,
                                 source_verified=True,nli_label="ENTAILMENT",entity_resolved=True,pit_pass=True)
        self.assertTrue(g["research_feature_eligible"]); self.assertFalse(g["forecast_adjustment_eligible"]); self.assertEqual(g["action_authority"],"OFF")
        bad=destructive_claim_gate(event_type="PLAYER_OUT",cross_model_state="CONFLICTING",source_tier=1,
                                   source_verified=True,nli_label="ENTAILMENT",entity_resolved=True,pit_pass=True)
        self.assertFalse(bad["research_feature_eligible"]); self.assertIn("DESTRUCTIVE_NO_CONSENSUS",bad["reasons"])

    def test_benchmark_names_destructive_false_positive_and_leakage(self):
        gold=[{"example_id":"1","event_type":"PLAYER_ACTIVE","subject_id":"P1","event_id":"G1"}]
        pred=[{"example_id":"1","event_type":"PLAYER_OUT","subject_id":"P1","event_id":"G1","known_before_cutoff":False,"used_as_prediction":True}]
        r=score_event_extraction(gold,pred); self.assertEqual(r["destructive_false_positive_count"],1); self.assertEqual(r["post_cutoff_leakage_count"],1)

    def test_all_candidate_roles_have_parallel_operations(self):
        ops=candidate_operations(); self.assertEqual(len(ops),9)
        self.assertEqual(ops["finbert_control"],"SENTIMENT_TRIAGE"); self.assertEqual(ops["nuextract3"],"DOCUMENT_EXTRACT")

    def test_injected_adapter_retains_identity_and_zero_authority(self):
        a=InjectedBackendAdapter("gliner25_base",lambda **kw:[{"event_type":"PLAYER_OUT"}])
        out=a.run("EXTRACT",text="x",labels=["player"]); self.assertEqual(out["status"],"PASS")
        self.assertFalse(out["trusted"]); self.assertFalse(out["forecast_adjustment_eligible"]); self.assertFalse(out["market_input"])

    def test_ensemble_rate_report(self):
        r=score_ensemble([{"cross_model_state":"CONSENSUS"},{"cross_model_state":"CONFLICTING"},{"cross_model_state":"ABSTAIN"}])
        self.assertEqual(r["n"],3); self.assertAlmostEqual(r["agreement_rate"],1/3)

if __name__=="__main__": unittest.main()
