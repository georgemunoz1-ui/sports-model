from __future__ import annotations
import json
import math
from pathlib import Path
import tempfile
import unittest

from research.adapters.base import digest
from research.evaluate_frozen_forecasts import evaluate
from research.tests.common import write_json, write_jsonl, write_manifest


FIXTURES = Path(__file__).parent / "fixtures"


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

    def test_smu_fsu_real_game_golden_fixture_keeps_analytic_and_mc_separate(self):
        """Real game/forecast values; fixture forecast hashes are explicitly synthetic identities."""
        analytic = json.loads((FIXTURES / "cfb_smu_fsu_20260907_analytic_fixture.json").read_text())
        mc = json.loads((FIXTURES / "cfb_smu_fsu_20260907_mc_fixture.json").read_text())
        grades = [json.loads(line) for line in (FIXTURES / "cfb_smu_fsu_20260907_grades_fixture.jsonl").read_text().splitlines() if line.strip()]
        self.assertTrue(analytic["fixture_only"] and mc["fixture_only"])
        self.assertIn("SYNTHETIC_FORECAST_HASH", analytic["fixture_identity_note"])
        self.assertIn("SYNTHETIC_FORECAST_HASH", mc["fixture_identity_note"])

        with tempfile.TemporaryDirectory() as td_raw:
            td = Path(td_raw)
            a = write_json(td / "analytic.json", analytic)
            m = write_json(td / "mc.json", mc)
            ledger = write_jsonl(td / "grades.jsonl", grades)
            manifest = write_manifest(td / "manifest.json", [
                {"absolute_path":a,"league":"CFB","artifact_schema":"cfb.research_score_bundle.v1","source_evidence_scope":"LOCAL_ONLY","canonical_prospective_eligible":False,"allow_shared_result_grade":False},
                {"absolute_path":m,"league":"CFB","artifact_schema":"cfb.research_score_bundle.v1","source_evidence_scope":"LOCAL_ONLY","canonical_prospective_eligible":False,"allow_shared_result_grade":False},
            ])
            result = evaluate(forecast_manifest=manifest,grade_ledger=ledger,scope="LOCAL_DIAGNOSTIC",league="CFB",output_dir=td/"out",report_date="2026-09-08",exclude_statuses=set(),fail_on_unexpected_row=True,write_canonical_rows=True)

        self.assertEqual(len(result["rows"]), 2)
        rows = {row["model_arm_id"]: row for row in result["rows"]}
        self.assertEqual(set(rows), {"analytic", "monte_carlo"})
        for row in rows.values():
            self.assertEqual(row["event_id"], "SMU_AT_FSU_2026-09-07")
            self.assertEqual(row["evidence_scope"], "LOCAL_DIAGNOSTIC")
            self.assertFalse(row["canonical_prospective_eligible"])
            self.assertEqual(row["outcome_value"], 0)
            self.assertEqual(row["actuals"], {"home_score":24.0,"away_score":27.0,"home_margin":-3.0,"total":51.0})
            self.assertTrue(row["score_target_compatible"])

        self.assertEqual(rows["analytic"]["probabilities"], {"home_win":0.249,"away_win":0.751})
        self.assertIsNone(rows["analytic"]["quantiles"]["home_margin"]["p10"])
        self.assertIsNone(rows["analytic"]["quantiles"]["total"]["p90"])
        self.assertEqual(rows["monte_carlo"]["probabilities"], {"home_win":0.244,"away_win":0.756})
        self.assertEqual(rows["monte_carlo"]["quantiles"]["home_margin"]["p10"], -36.0)
        self.assertEqual(rows["monte_carlo"]["quantiles"]["home_margin"]["p90"], 11.0)
        self.assertEqual(rows["monte_carlo"]["quantiles"]["total"]["p10"], 35.0)
        self.assertEqual(rows["monte_carlo"]["quantiles"]["total"]["p90"], 75.0)

        summaries = {s["model_arm_id"]: s for s in result["report"]["model_summaries"]}
        ana = summaries["analytic"]
        sim = summaries["monte_carlo"]
        self.assertAlmostEqual(ana["probability_metrics"]["binary_brier_single_class_mean"], 0.062001, places=12)
        self.assertAlmostEqual(ana["probability_metrics"]["binary_brier_multiclass_sum_mean"], 0.124002, places=12)
        self.assertAlmostEqual(ana["probability_metrics"]["log_loss_mean"], -math.log(0.751), places=12)
        self.assertAlmostEqual(sim["probability_metrics"]["binary_brier_single_class_mean"], 0.059536, places=12)
        self.assertAlmostEqual(sim["probability_metrics"]["binary_brier_multiclass_sum_mean"], 0.119072, places=12)
        self.assertAlmostEqual(sim["probability_metrics"]["log_loss_mean"], -math.log(0.756), places=12)
        self.assertAlmostEqual(ana["continuous_metrics"]["home_margin"]["point_error"]["mae"], 9.45, places=12)
        self.assertAlmostEqual(ana["continuous_metrics"]["total"]["point_error"]["mae"], 2.85, places=12)
        self.assertAlmostEqual(sim["continuous_metrics"]["home_margin"]["point_error"]["mae"], 9.50, places=12)
        self.assertAlmostEqual(sim["continuous_metrics"]["total"]["point_error"]["mae"], 3.82, places=12)

        aq = ana["continuous_metrics"]["home_margin"]["quantiles"]
        self.assertEqual(aq["pinball_by_quantile"]["p10"]["status"], "NOT_AVAILABLE_IN_FROZEN_ARTIFACT")
        mq = sim["continuous_metrics"]["home_margin"]["quantiles"]
        tq = sim["continuous_metrics"]["total"]["quantiles"]
        self.assertAlmostEqual(mq["pinball_by_quantile"]["p10"]["mean"], 3.30, places=12)
        self.assertAlmostEqual(mq["pinball_by_quantile"]["p90"]["mean"], 1.40, places=12)
        self.assertAlmostEqual(tq["pinball_by_quantile"]["p10"]["mean"], 1.60, places=12)
        self.assertAlmostEqual(tq["pinball_by_quantile"]["p90"]["mean"], 2.40, places=12)
        self.assertEqual(mq["central_interval_coverage"]["80_percent"]["coverage"], 1)
        self.assertEqual(tq["central_interval_coverage"]["80_percent"]["coverage"], 1)
        self.assertEqual(mq["central_interval_coverage"]["50_percent"]["status"], "NOT_AVAILABLE_IN_FROZEN_ARTIFACT")
        self.assertEqual(mq["central_interval_coverage"]["90_percent"]["status"], "NOT_AVAILABLE_IN_FROZEN_ARTIFACT")

        paired = result["report"]["paired_comparisons"][0]
        self.assertEqual(paired["paired_comparison_status"], "PAIRED_POPULATION_VALID")
        self.assertEqual(paired["eligible_pair_count"], 1)
        self.assertEqual(paired["paired_date_cluster_bootstrap"]["status"], "NOT_RUN_INSUFFICIENT_DATE_CLUSTERS")
        self.assertLess(paired["mean_log_loss_delta_challenger_minus_incumbent"], 0)


if __name__ == "__main__": unittest.main()
