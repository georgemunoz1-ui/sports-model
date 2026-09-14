from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest

from research.adapters.base import EvaluationError
from research.evaluate_frozen_forecasts import evaluate
from research.tests.common import write_manifest

FIX=Path(__file__).parent/"fixtures"


class EvaluateFrozenForecastsTests(unittest.TestCase):
    def run_mlb(self, *, mutate_manifest=None):
        td_obj=tempfile.TemporaryDirectory(); self.addCleanup(td_obj.cleanup); td=Path(td_obj.name)
        art=td/"f.json"; art.write_bytes((FIX/"mlb_sept6_deidentified_forecast.json").read_bytes())
        grade=td/"g.jsonl"; grade.write_bytes((FIX/"mlb_sept6_deidentified_grades.jsonl").read_bytes())
        manifest=write_manifest(td/"manifest.json",[{"absolute_path":art,"league":"MLB","artifact_schema":"mlb.phase1_1_shadow.v1","source_evidence_scope":"LOCAL_ONLY","canonical_prospective_eligible":False}])
        if mutate_manifest:
            m=json.loads(manifest.read_text()); mutate_manifest(m); manifest.write_text(json.dumps(m,sort_keys=True,separators=(",",":")))
        return td,art,grade,manifest

    def test_binary_brier_primary_and_two_class_exactly_double(self):
        td,art,grade,manifest=self.run_mlb(); r=evaluate(forecast_manifest=manifest,grade_ledger=grade,scope="LOCAL_DIAGNOSTIC",league="MLB",output_dir=td/"out",report_date="2026-09-07",exclude_statuses=set(),fail_on_unexpected_row=True,write_canonical_rows=True)
        for s in r["report"]["model_summaries"]:
            m=s["probability_metrics"]; self.assertAlmostEqual(m["binary_brier_multiclass_sum_mean"],2*m["binary_brier_single_class_mean"],places=14); self.assertEqual(m["brier_convention"],"SINGLE_CLASS_MEAN_(P-Y)^2")

    def test_p10_p90_only_has_80pct_coverage_not_50_or_90(self):
        td,art,grade,manifest=self.run_mlb(); r=evaluate(forecast_manifest=manifest,grade_ledger=grade,scope="LOCAL_DIAGNOSTIC",league="MLB",output_dir=td/"out",report_date="2026-09-07",exclude_statuses=set(),fail_on_unexpected_row=True,write_canonical_rows=True)
        mc=[x for x in r["report"]["model_summaries"] if x["model_arm_id"]=="monte_carlo"][0]; q=mc["continuous_metrics"]["home_margin"]["quantiles"]; cov=q["central_interval_coverage"]
        self.assertEqual(cov["80_percent"]["status"],"AVAILABLE"); self.assertEqual(cov["50_percent"]["status"],"NOT_AVAILABLE_IN_FROZEN_ARTIFACT"); self.assertEqual(cov["90_percent"]["status"],"NOT_AVAILABLE_IN_FROZEN_ARTIFACT")
        self.assertEqual(q["pinball_by_quantile"]["p10"]["status"],"AVAILABLE"); self.assertEqual(q["pinball_by_quantile"]["p90"]["status"],"AVAILABLE"); self.assertEqual(q["pinball_by_quantile"]["p25"]["status"],"NOT_AVAILABLE_IN_FROZEN_ARTIFACT")

    def test_unknown_artifact_schema_fails_closed(self):
        td,art,grade,manifest=self.run_mlb(mutate_manifest=lambda m:m["artifacts"][0].update({"artifact_schema":"unknown.v99"}))
        with self.assertRaisesRegex(EvaluationError,"unknown MLB artifact schema"): evaluate(forecast_manifest=manifest,grade_ledger=grade,scope="LOCAL_DIAGNOSTIC",league="MLB",output_dir=td/"out",report_date="2026-09-07",exclude_statuses=set(),fail_on_unexpected_row=True,write_canonical_rows=True)

    def test_manifest_hash_mismatch_fails(self):
        td,art,grade,manifest=self.run_mlb(mutate_manifest=lambda m:m["artifacts"][0].update({"sha256":"f"*64}))
        with self.assertRaisesRegex(EvaluationError,"artifact hash mismatch"): evaluate(forecast_manifest=manifest,grade_ledger=grade,scope="LOCAL_DIAGNOSTIC",league="MLB",output_dir=td/"out",report_date="2026-09-07",exclude_statuses=set(),fail_on_unexpected_row=True,write_canonical_rows=True)

    def test_report_is_content_addressed_and_repeat_is_byte_identical(self):
        td,art,grade,manifest=self.run_mlb(); kw=dict(forecast_manifest=manifest,grade_ledger=grade,scope="LOCAL_DIAGNOSTIC",league="MLB",output_dir=td/"out",report_date="2026-09-07",exclude_statuses=set(),fail_on_unexpected_row=True,write_canonical_rows=True)
        one=evaluate(**kw); two=evaluate(**kw); self.assertEqual(one["output_dir"],two["output_dir"]); self.assertEqual(one["report_hash"],two["report_hash"])
        out=Path(one["output_dir"]); self.assertEqual(out.parts[-2],one["dataset_sha256"]); self.assertEqual(out.parts[-1],one["report_hash"]); self.assertTrue((out/"evaluation_manifest.sha256").exists())


if __name__ == "__main__": unittest.main()
