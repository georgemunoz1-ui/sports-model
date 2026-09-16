from __future__ import annotations
from pathlib import Path
import tempfile
import unittest

from research.evaluate_frozen_forecasts import evaluate
from research.tests.common import write_json, write_jsonl, write_manifest


class MLSAdapterTests(unittest.TestCase):
    def run_case(self,identity="VALID",exclude=None):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td); forecast={"model_id":"mls.dixon_coles.v1","forecast_cutoff_utc":"2026-09-05T09:00:00Z","registration_scope":"LOCAL_ONLY","games":[{"event_id":"MLS:1","start_utc":"2026-09-05T23:00:00Z","forecast_output_hash":"d"*64,"probabilities":{"home_win":.292,"draw":.247,"away_win":.461},"identity_status":"VALID"}]}; art=write_json(td/"mls.json",forecast)
            grade={"schema_version":"outcome_grade.v1","league":"MLS","event_id":"MLS:1","forecast_output_hash":"d"*64,"evidence_scope":"LOCAL_DIAGNOSTIC","identity_status":identity,"event_date_local":"2026-09-05","graded_at_utc":"2026-09-06T06:00:00Z","home_score":1,"away_score":1}; ledger=write_jsonl(td/"grades.jsonl",[grade]); man=write_manifest(td/"manifest.json",[{"absolute_path":art,"league":"MLS","artifact_schema":"mls.dixon_coles_bundle.v1","source_evidence_scope":"LOCAL_ONLY","canonical_prospective_eligible":False}])
            return evaluate(forecast_manifest=man,grade_ledger=ledger,scope="LOCAL_DIAGNOSTIC",league="MLS",output_dir=td/"out",report_date="2026-09-06",exclude_statuses=set(exclude or []),fail_on_unexpected_row=True,write_canonical_rows=True)

    def test_valid_hda_emits_multiclass_metrics(self):
        r=self.run_case(); self.assertEqual(r["rows"][0]["outcome_value"],"DRAW"); m=r["report"]["model_summaries"][0]["probability_metrics"]; self.assertIn("multiclass_brier_class_sum_mean",m); self.assertIn("multiclass_log_loss_mean",m)

    def test_quarantined_identity_is_excluded(self):
        with self.assertRaisesRegex(Exception,"no canonical evaluation rows produced"): self.run_case(identity="QUARANTINED_IDENTITY_FAILURE",exclude={"QUARANTINED_IDENTITY_FAILURE"})


if __name__ == "__main__": unittest.main()
