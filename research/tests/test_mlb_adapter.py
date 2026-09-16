from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest

from research.adapters.base import EvaluationError, GradeIndex, digest, sha256_file
from research.adapters.mlb import MLBAdapter
from research.tests.common import write_json, write_manifest
from research.evaluate_frozen_forecasts import evaluate

FIX = Path(__file__).parent / "fixtures"


class MLBAdapterTests(unittest.TestCase):
    def fixture_payload(self): return json.loads((FIX / "mlb_sept6_deidentified_forecast.json").read_text())
    def fixture_grade(self): return json.loads((FIX / "mlb_sept6_deidentified_grades.jsonl").read_text())

    def direct(self, payload, grade):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); art=write_json(td/"forecast.json",payload); entry={"league":"MLB","artifact_schema":"mlb.phase1_1_shadow.v1","sha256":sha256_file(art),"source_evidence_scope":"LOCAL_ONLY","canonical_prospective_eligible":False}; grade=dict(grade)
            if "grade_record_hash" not in grade: grade["grade_record_hash"]=digest(grade)
            return MLBAdapter().adapt(payload,entry,GradeIndex([grade]),"LOCAL_DIAGNOSTIC",exclude_statuses=set(),fail_on_unexpected_row=True,allow_combined_descriptive=False)

    def test_valid_frozen_mlb_emits_analytic_and_mc_rows(self):
        a=self.direct(self.fixture_payload(),self.fixture_grade()); self.assertEqual([r["model_arm_id"] for r in a.rows],["analytic","monte_carlo"]); self.assertEqual(len(a.rows),2); self.assertEqual(a.rows[0]["evidence_scope"],"LOCAL_DIAGNOSTIC"); self.assertFalse(a.rows[0]["canonical_prospective_eligible"])

    def test_extra_innings_preserves_winner_but_excludes_score_metrics(self):
        g=self.fixture_grade(); g.update({"home_score":5,"away_score":4,"innings_played":10,"went_extra_innings":True}); a=self.direct(self.fixture_payload(),g)
        for r in a.rows: self.assertFalse(r["score_target_compatible"]); self.assertEqual(r["score_metrics_excluded_reason"],"EXTRA_INNINGS_UNSUPPORTED"); self.assertEqual(r["outcome_value"],1)

    def test_wrong_grade_forecast_record_hash_fails(self):
        g=self.fixture_grade(); g["forecast_record_hash"]="f"*64
        with self.assertRaisesRegex(EvaluationError,"wrong forecast record hash"): self.direct(self.fixture_payload(),g)

    def test_duplicate_forecast_hash_fails(self):
        p=self.fixture_payload(); p["games"][0]["forecast"]["simulation_output_hash"]=p["games"][0]["forecast"]["forecast_output_hash"]
        with self.assertRaisesRegex(EvaluationError,"duplicate.*forecast hash"): self.direct(p,self.fixture_grade())

    def test_local_only_rejected_under_canonical_scope(self):
        p=self.fixture_payload(); g=self.fixture_grade()
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); art=write_json(td/"forecast.json",p); entry={"league":"MLB","artifact_schema":"mlb.phase1_1_shadow.v1","sha256":sha256_file(art),"source_evidence_scope":"LOCAL_ONLY","canonical_prospective_eligible":False}; g["grade_record_hash"]=digest(g)
            with self.assertRaisesRegex(EvaluationError,"evidence scope mismatch"): MLBAdapter().adapt(p,entry,GradeIndex([g]),"REMOTE_DURABLE_PROSPECTIVE",exclude_statuses=set(),fail_on_unexpected_row=True,allow_combined_descriptive=False)

    def test_deidentified_sept6_fixture_end_to_end_is_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); art=td/"frozen.json"; art.write_bytes((FIX/"mlb_sept6_deidentified_forecast.json").read_bytes()); grade=td/"grades.jsonl"; grade.write_bytes((FIX/"mlb_sept6_deidentified_grades.jsonl").read_bytes())
            manifest=write_manifest(td/"manifest.json",[{"absolute_path":art,"league":"MLB","artifact_schema":"mlb.phase1_1_shadow.v1","source_evidence_scope":"LOCAL_ONLY","canonical_prospective_eligible":False}]); before=(sha256_file(art),sha256_file(grade))
            r=evaluate(forecast_manifest=manifest,grade_ledger=grade,scope="LOCAL_DIAGNOSTIC",league="MLB",output_dir=td/"out",report_date="2026-09-07",exclude_statuses=set(),fail_on_unexpected_row=True,write_canonical_rows=True); self.assertEqual(before,(sha256_file(art),sha256_file(grade))); self.assertFalse(r["report"]["forecast_artifacts_mutated"]); self.assertFalse(r["report"]["outcome_grades_mutated"]); self.assertFalse(r["report"]["canonical_prospective_eligible"])


if __name__ == "__main__": unittest.main()
