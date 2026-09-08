from __future__ import annotations
from pathlib import Path
import tempfile
import unittest

from research.adapters.base import digest
from research.evaluate_frozen_forecasts import evaluate
from research.tests.common import write_json, write_jsonl, write_manifest


def arm_payload(model, arm, role, universe, games):
    return {"model_id":model,"model_arm_id":arm,"experiment_id":"cfb_sigma_phase1_2026","pair_role":role,"paired_game_universe_hash":universe,"paired_with_model_id":"challenger" if role=="incumbent" else "incumbent","forecast_cutoff_utc":"2026-09-06T08:54:51Z","registration_scope":"LOCAL_ONLY","target_contract":{"winner_target":"FINAL_WINNER_WITH_DISCLOSED_OT_PROXY","margin_target":"DECLARED_CFB_SCORE_DISTRIBUTION","total_target":"DECLARED_CFB_SCORE_DISTRIBUTION"},"games":games}


def game(event,h,start,p,margin):
    return {"event_id":event,"start_utc":start,"forecast_output_hash":h*64,"home_win_probability":p,"home_margin_prediction":margin,"total_prediction":52.0,"quantiles":{"home_margin":{"p10":-10,"p90":25},"total":{"p10":35,"p90":70}}}


def grade(event,model,arm,h,date="2026-09-06"):
    return {"schema_version":"outcome_grade.v1","league":"CFB","event_id":event,"model_id":model,"model_arm_id":arm,"forecast_output_hash":h*64,"forecast_cutoff_utc":"2026-09-06T08:54:51Z","evidence_scope":"LOCAL_DIAGNOSTIC","event_date_local":date,"graded_at_utc":"2026-09-07T06:00:00Z","home_score":30,"away_score":20}


class CFBAdapterTests(unittest.TestCase):
    def run_case(self,bg,cg,grades):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); u=digest(sorted([g["event_id"] for g in bg])); b=write_json(td/"b.json",arm_payload("incumbent","fixed_sigma","incumbent",u,bg)); c=write_json(td/"c.json",arm_payload("challenger","conditional_sigma","challenger",u,cg)); ledger=write_jsonl(td/"grades.jsonl",grades)
            man=write_manifest(td/"manifest.json",[{"absolute_path":b,"league":"CFB","artifact_schema":"cfb.arm_bundle.v1","source_evidence_scope":"LOCAL_ONLY","canonical_prospective_eligible":False,"allow_shared_result_grade":False},{"absolute_path":c,"league":"CFB","artifact_schema":"cfb.arm_bundle.v1","source_evidence_scope":"LOCAL_ONLY","canonical_prospective_eligible":False,"allow_shared_result_grade":False}])
            return evaluate(forecast_manifest=man,grade_ledger=ledger,scope="LOCAL_DIAGNOSTIC",league="CFB",output_dir=td/"out",report_date="2026-09-07",exclude_statuses=set(),fail_on_unexpected_row=True,write_canonical_rows=True)

    def test_complete_two_arm_pair_emits_rows_and_pairing_index(self):
        bg=[game("CFB:1","a","2026-09-06T20:00:00Z",.70,8.0)]; cg=[game("CFB:1","b","2026-09-06T20:00:00Z",.72,9.0)]; grades=[grade("CFB:1","incumbent","fixed_sigma","a"),grade("CFB:1","challenger","conditional_sigma","b")]; r=self.run_case(bg,cg,grades); self.assertEqual(len(r["rows"]),2); p=r["report"]["paired_comparisons"][0]; self.assertEqual(p["paired_comparison_status"],"PAIRED_POPULATION_VALID"); self.assertEqual(p["paired_date_cluster_bootstrap"]["status"],"NOT_RUN_INSUFFICIENT_DATE_CLUSTERS")

    def test_missing_challenger_event_rejects_paired_analysis(self):
        bg=[game("CFB:1","a","2026-09-06T20:00:00Z",.70,8.0),game("CFB:2","c","2026-09-06T21:00:00Z",.60,4.0)]; cg=[game("CFB:1","b","2026-09-06T20:00:00Z",.72,9.0)]; grades=[grade("CFB:1","incumbent","fixed_sigma","a"),grade("CFB:2","incumbent","fixed_sigma","c"),grade("CFB:1","challenger","conditional_sigma","b")]; r=self.run_case(bg,cg,grades); p=r["report"]["paired_comparisons"][0]; self.assertEqual(p["paired_comparison_status"],"REJECTED_INCOMPLETE_POPULATION"); self.assertNotIn("paired_date_cluster_bootstrap",p)


if __name__ == "__main__": unittest.main()
