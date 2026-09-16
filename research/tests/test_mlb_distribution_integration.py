from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from research.adapters.base import GradeIndex, digest, sha256_file
from research.adapters.mlb import EXPERIMENT_ID, MLBAdapter
from research.mlb_distribution_experiment import evaluate, load_registry

FIX = Path(__file__).parent / "fixtures"


class MLBDistributionIntegrationTests(unittest.TestCase):
    def test_deidentified_frozen_artifact_flows_adapter_to_paired_scorer(self):
        payload = json.loads((FIX / "mlb_sept6_deidentified_forecast.json").read_text())
        grade = json.loads((FIX / "mlb_sept6_deidentified_grades.jsonl").read_text())
        payload["model_code_identity"] = "integration-fixture-code-v1"
        payload["feature_contract_version"] = "mlb.integration.features.v1"
        payload["predictive_input_field_names"] = ["starter_era", "team_run_state"]
        payload["market_input_used"] = False
        payload["source_input_hashes"] = {
            "stats": "1" * 64,
            "starters": "2" * 64,
        }
        payload["simulation_count"] = 100000
        payload["games"][0]["away_team"] = "AWAY_FIXTURE"
        payload["games"][0]["home_team"] = "HOME_FIXTURE"
        payload["games"][0]["forecast"]["simulation_seed"] = 424242
        if "grade_record_hash" not in grade:
            grade["grade_record_hash"] = digest(grade)
        with tempfile.TemporaryDirectory() as td:
            art = Path(td) / "forecast.json"
            art.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            entry = {
                "league": "MLB",
                "artifact_schema": "mlb.phase1_1_shadow.v1",
                "sha256": sha256_file(art),
                "source_evidence_scope": "LOCAL_ONLY",
                "canonical_prospective_eligible": False,
                "experiment_id": EXPERIMENT_ID,
                "simulation_count": 100000,
            }
            adapted = MLBAdapter().adapt(
                payload, entry, GradeIndex([grade]), "LOCAL_DIAGNOSTIC",
                exclude_statuses=set(), fail_on_unexpected_row=True,
                allow_combined_descriptive=False,
            )
        self.assertEqual([r["model_arm_id"] for r in adapted.rows], ["analytic", "monte_carlo"])
        self.assertTrue(all(r["pairing"] for r in adapted.rows))
        self.assertEqual(
            adapted.rows[0]["pairing"]["expected_run_input_hash"],
            adapted.rows[1]["pairing"]["expected_run_input_hash"],
        )
        self.assertEqual(adapted.rows[0]["pairing"]["distribution_contract_id"], "fixed_poisson.v1")
        self.assertEqual(adapted.rows[1]["pairing"]["distribution_contract_id"], "gamma_poisson_workload_mc.v1")
        report = evaluate(adapted.rows, registry=load_registry(), bootstrap_draws=100)
        self.assertEqual(report["population"]["descriptive_paired_event_count"], 1)
        self.assertEqual(report["population"]["promotion_sample_eligible_pair_count"], 0)
        self.assertEqual(report["decision"]["status"], "INSUFFICIENT_PROMOTION_SAMPLE")


if __name__ == "__main__":
    unittest.main()
