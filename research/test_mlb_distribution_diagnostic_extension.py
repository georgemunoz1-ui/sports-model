import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class MLBDiagnosticExtensionTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads((ROOT / "mlb_distribution_diagnostic_extension_v1.json").read_text())
        self.obs = json.loads((ROOT / "mlb_two_night_diagnostic_2026-09-08_09.json").read_text())

    def test_extension_cannot_promote_or_retire_arms(self):
        gov = self.spec["governance"]
        self.assertFalse(gov["automatic_arm_promotion"])
        self.assertFalse(gov["automatic_arm_retirement"])
        self.assertFalse(gov["automatic_blend"])
        self.assertFalse(gov["posthoc_parameter_retuning"])
        self.assertFalse(gov["posthoc_direction_flip_threshold_rule"])
        self.assertFalse(gov["promotion_authority"])
        self.assertFalse(gov["action_authority"])

    def test_direction_flip_is_a_stratum_not_a_rule(self):
        dist = self.spec["research_tracks"]["distribution"]
        self.assertIn("direction_flip", dist["required_strata"])
        self.assertIsNone(dist["near_even_threshold"])
        self.assertFalse(dist["anti_gamma_flip_rule_permitted"])

    def test_run_mean_is_separate_from_distribution_arm(self):
        mean = self.spec["research_tracks"]["mean_run_environment"]
        self.assertEqual(mean["priority"], "HIGH")
        self.assertIn("GAME_TOTAL_SIGNED_ERROR_ACTUAL_MINUS_PROJECTED", mean["required_metrics"])
        self.assertIn("starter_binding_state", mean["required_audit_dimensions"])
        self.assertIn("bullpen_workload_state", mean["required_audit_dimensions"])
        self.assertIn("lineup_binding_state", mean["required_audit_dimensions"])
        self.assertIn("Distribution-arm changes must not be used", mean["rule"])

    def test_two_night_observation_is_not_canonical_promotion_evidence(self):
        self.assertFalse(self.obs["canonical_prospective_eligible"])
        self.assertFalse(self.obs["counts_toward_distribution_decision_gate"])
        self.assertFalse(self.obs["counts_toward_final_holdout"])
        self.assertFalse(self.obs["decisions"]["promote_arm"])
        self.assertFalse(self.obs["decisions"]["retire_arm"])
        self.assertFalse(self.obs["decisions"]["blend_arms"])

    def test_observed_counts_are_preserved_but_not_overinterpreted(self):
        fixed = self.obs["arm_results"]["fixed_poisson"]["winner_record"]
        gamma = self.obs["arm_results"]["gamma_poisson_workload_mc"]["winner_record"]
        flips = self.obs["direction_flip_observation"]
        self.assertEqual((fixed["wins"], fixed["losses"]), (16, 14))
        self.assertEqual((gamma["wins"], gamma["losses"]), (12, 18))
        self.assertEqual(flips["near_even_direction_flips"], 4)
        self.assertEqual(flips["gamma_selected_side_wins"], 0)
        self.assertEqual(flips["fixed_selected_side_wins"], 4)
        self.assertEqual(flips["status"], "HYPOTHESIS_ONLY_SMALL_SAMPLE")
        self.assertFalse(flips["hardcoded_threshold_rule"])

    def test_unresolved_sept9_flip_ids_stay_null(self):
        unresolved = self.obs["direction_flip_observation"]["unresolved_event_details"]
        self.assertEqual(len(unresolved), 2)
        self.assertTrue(all(item["event_id"] is None for item in unresolved))

    def test_signed_error_requires_reconciliation_before_machine_use(self):
        sept9 = self.obs["run_environment_observation"]["2026-09-09"]
        self.assertEqual(sept9["game_total_mean_signed_error_actual_minus_projected_runs"], -2.58)
        self.assertIn("sign convention requires canonical reconciliation", sept9["sign_convention_note"])


if __name__ == "__main__":
    unittest.main()
