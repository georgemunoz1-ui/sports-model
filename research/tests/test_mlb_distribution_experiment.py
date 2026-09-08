from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path
import unittest

from research import offline_benchmark as B
from research.mlb_distribution_experiment import DistributionExperimentError, evaluate

REGISTRY_PATH = Path(__file__).parents[1] / "mlb_distribution_arms_v1.json"


def registry(holdout_start=None):
    r = json.loads(REGISTRY_PATH.read_text())
    r["evaluation_contract"]["final_holdout"]["start_date"] = holdout_start
    r["evaluation_contract"]["final_holdout"]["status"] = (
        "PREREGISTERED" if holdout_start else "NOT_PREDECLARED"
    )
    return r


def dates(n, start="2026-09-10", clusters=15):
    base = dt.date.fromisoformat(start)
    return [(base + dt.timedelta(days=i % clusters)).isoformat() for i in range(n)]


def population(specs, *, scope="LOCAL_DIAGNOSTIC", canonical=False):
    """spec: (event_id, date, fixed_home_p, gamma_home_p, y_home)."""
    universe = B.digest(sorted(s[0] for s in specs))
    rows = []
    for event_id, day, fixed_p, gamma_p, y in specs:
        orientation = B.digest({"event": event_id, "away": "AWAY", "home": "HOME"})
        expected = B.digest({"event": event_id, "home_expected_runs": 4.8, "away_expected_runs": 4.1})
        source_set = B.digest({"event": event_id, "sources": ["stats", "starters"]})
        grade_hash = B.digest({"grade": event_id})
        cutoff = f"{day}T12:00:00Z"
        start = f"{day}T23:00:00Z"
        for arm, p in (("analytic", fixed_p), ("monte_carlo", gamma_p)):
            contract = "fixed_poisson.v1" if arm == "analytic" else "gamma_poisson_workload_mc.v1"
            row = {
                "schema_version": "evaluation_row.v1",
                "league": "MLB",
                "event_id": event_id,
                "event_date_local": day,
                "forecast_output_hash": B.digest({"forecast": event_id, "arm": arm}),
                "grade_record_hash": grade_hash,
                "model_id": "mlb.distribution.synthetic.v1",
                "model_arm_id": arm,
                "experiment_id": "mlb.fixed_poisson_vs_gamma_poisson_workload.v1",
                "evidence_scope": scope,
                "canonical_prospective_eligible": canonical,
                "forecast_cutoff_utc": cutoff,
                "scheduled_start_utc": start,
                "graded_at_utc": f"{day}T23:59:59Z",
                "outcome_type": "BINARY_HOME_WIN",
                "outcome_value": y,
                "probabilities": {"home_win": p, "away_win": 1.0 - p},
                "point_predictions": {},
                "quantiles": {},
                "actuals": {"home_score": 5.0 if y else 3.0, "away_score": 3.0 if y else 5.0,
                            "home_margin": 2.0 if y else -2.0, "total": 8.0},
                "data_quality": {},
                "target_contract": {"winner_target": "MODEL_WINNER_WITH_DISCLOSED_TIE_PROXY",
                                    "margin_target": "REGULATION_ONLY", "total_target": "REGULATION_ONLY",
                                    "tie_resolution_method": "HALF_TIE"},
                "score_target_compatible": True,
                "score_metrics_excluded_reason": None,
                "pairing": {
                    "experiment_id": "mlb.fixed_poisson_vs_gamma_poisson_workload.v1",
                    "paired_game_universe_hash": universe,
                    "event_orientation_hash": orientation,
                    "expected_run_input_hash": expected,
                    "feature_contract_version": "mlb.features.synthetic.v1",
                    "source_input_hash_set_hash": source_set,
                    "model_code_identity": "synthetic-model-code-v1",
                    "predictive_input_field_names": ["starter_era", "team_run_state"],
                    "market_input_used": False,
                    "distribution_contract_id": contract,
                    "arm_context_hash": B.digest({"event": event_id, "arm": arm, "contract": contract}),
                    "simulation_seed": 12345 if arm == "monte_carlo" else None,
                },
            }
            rows.append(row)
    return rows


def simple_specs(n=1, *, fixed=.60, gamma=.58, y=1, start="2026-09-10", clusters=15):
    ds = dates(n, start=start, clusters=clusters)
    return [(f"GAME_{i:04d}", ds[i], fixed, gamma, y) for i in range(n)]


class MLBDistributionExperimentTests(unittest.TestCase):
    def test_same_event_two_valid_arms_scores_and_pairs(self):
        report = evaluate(population(simple_specs()), registry=registry(), bootstrap_draws=100)
        self.assertEqual(report["population"]["descriptive_paired_event_count"], 1)
        self.assertEqual(report["arm_metrics_descriptive"]["fixed_poisson"]["n"], 1)
        self.assertEqual(report["arm_metrics_descriptive"]["gamma_poisson_workload_mc"]["n"], 1)

    def test_missing_arm_rejects_complete_population(self):
        rows = population(simple_specs())
        rows = [r for r in rows if r["model_arm_id"] != "monte_carlo"]
        with self.assertRaisesRegex(DistributionExperimentError, "INCOMPLETE_PAIRED_POPULATION"):
            evaluate(rows, registry=registry(), bootstrap_draws=100)

    def test_different_cutoff_rejects_pair(self):
        rows = population(simple_specs())
        [r for r in rows if r["model_arm_id"] == "monte_carlo"][0]["forecast_cutoff_utc"] = "2026-09-10T13:00:00Z"
        with self.assertRaisesRegex(DistributionExperimentError, "PAIR_CUTOFF_MISMATCH"):
            evaluate(rows, registry=registry(), bootstrap_draws=100)

    def test_different_event_orientation_rejects_pair(self):
        rows = population(simple_specs())
        [r for r in rows if r["model_arm_id"] == "monte_carlo"][0]["pairing"]["event_orientation_hash"] = B.digest("reversed")
        with self.assertRaisesRegex(DistributionExperimentError, "PAIR_ORIENTATION_MISMATCH"):
            evaluate(rows, registry=registry(), bootstrap_draws=100)

    def test_different_expected_run_input_hash_rejects_pair(self):
        rows = population(simple_specs())
        [r for r in rows if r["model_arm_id"] == "monte_carlo"][0]["pairing"]["expected_run_input_hash"] = B.digest("changed")
        with self.assertRaisesRegex(DistributionExperimentError, "PAIR_EXPECTED_RUN_INPUT_HASH_MISMATCH"):
            evaluate(rows, registry=registry(), bootstrap_draws=100)

    def test_source_hash_or_feature_contract_mismatch_rejects_pair(self):
        for field, value in (("source_input_hash_set_hash", B.digest("other")),
                             ("feature_contract_version", "other.features.v2"),
                             ("model_code_identity", "other-code")):
            rows = population(simple_specs())
            [r for r in rows if r["model_arm_id"] == "monte_carlo"][0]["pairing"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(DistributionExperimentError, "PAIR_SHARED_METADATA_MISMATCH"):
                evaluate(rows, registry=registry(), bootstrap_draws=100)

    def test_market_field_in_predictive_inputs_rejected(self):
        rows = population(simple_specs())
        rows[0]["pairing"]["predictive_input_field_names"].append("market_odds")
        with self.assertRaisesRegex(DistributionExperimentError, "MARKET_INPUT_FORBIDDEN"):
            evaluate(rows, registry=registry(), bootstrap_draws=100)

    def test_posthoc_arm_selection_rejected(self):
        rows = population(simple_specs())
        rows[0]["pairing"]["selected_arm"] = "analytic"
        rows[0]["pairing"]["selection_basis"] = "outcome"
        with self.assertRaisesRegex(DistributionExperimentError, "POSTHOC_ARM_SELECTION_FORBIDDEN"):
            evaluate(rows, registry=registry(), bootstrap_draws=100)

    def test_local_only_is_descriptive_and_not_promotion_sample(self):
        report = evaluate(population(simple_specs()), registry=registry(), bootstrap_draws=100)
        self.assertEqual(report["population"]["promotion_sample_eligible_pair_count"], 0)
        self.assertEqual(report["population"]["promotion_sample_excluded_pair_count"], 1)
        self.assertEqual(report["decision"]["status"], "INSUFFICIENT_PROMOTION_SAMPLE")

    def test_duplicate_arm_event_rejected(self):
        rows = population(simple_specs())
        rows.append(copy.deepcopy(rows[0]))
        with self.assertRaisesRegex(DistributionExperimentError, "DUPLICATE_ARM_EVENT"):
            evaluate(rows, registry=registry(), bootstrap_draws=100)

    def test_one_date_cluster_scores_but_suppresses_bootstrap(self):
        specs = simple_specs(4, clusters=1)
        report = evaluate(population(specs), registry=registry(), bootstrap_draws=100)
        boot = report["paired_deltas_descriptive_gamma_minus_fixed"]["log_loss_date_cluster_bootstrap"]
        self.assertEqual(boot["status"], "NOT_RUN_INSUFFICIENT_DATE_CLUSTERS")

    def test_fewer_than_200_canonical_pairs_suppresses_decision(self):
        rows = population(simple_specs(30, clusters=15), scope="REMOTE_DURABLE_PROSPECTIVE", canonical=True)
        report = evaluate(rows, registry=registry(), bootstrap_draws=100)
        self.assertEqual(report["population"]["promotion_sample_eligible_pair_count"], 30)
        self.assertEqual(report["decision"]["status"], "INSUFFICIENT_PROMOTION_SAMPLE")

    def test_underpopulated_strong_favorite_band_is_labeled(self):
        rows = population(simple_specs(10, fixed=.90, gamma=.80, y=1, clusters=5))
        report = evaluate(rows, registry=registry(), bootstrap_draws=100)
        strong = report["favorite_strength_strata_descriptive"][-1]
        self.assertEqual(strong["n"], 10)
        self.assertEqual(strong["status"], "INSUFFICIENT_STRATUM_N")

    def test_report_hash_is_deterministic_for_same_rows_and_registry(self):
        rows = population(simple_specs(4, clusters=2))
        r = registry()
        one = evaluate(rows, registry=r, bootstrap_draws=100)
        two = evaluate(copy.deepcopy(rows), registry=copy.deepcopy(r), bootstrap_draws=100)
        self.assertEqual(one["report_hash"], two["report_hash"])
        self.assertEqual(one["population"]["pair_key_set_sha256"], two["population"]["pair_key_set_sha256"])

    def test_threshold_met_without_preregistered_holdout_still_cannot_decide(self):
        rows = population(simple_specs(210, fixed=.55, gamma=.90, y=1, clusters=15),
                          scope="REMOTE_DURABLE_PROSPECTIVE", canonical=True)
        report = evaluate(rows, registry=registry(), bootstrap_draws=100)
        self.assertEqual(report["decision"]["status"], "FINAL_HOLDOUT_NOT_PREDECLARED")
        self.assertIsNone(report["decision"]["favored_arm"])

    def test_opposite_high_volume_stratum_forces_regime_dependence(self):
        dev_dates = dates(220, start="2026-09-10", clusters=15)
        specs = []
        for i in range(180):
            specs.append((f"DEV_MOD_{i:04d}", dev_dates[i], .55, .90, 1))
        for i in range(40):
            specs.append((f"DEV_STRONG_{i:04d}", dev_dates[180 + i], .90, .70, 1))
        hold_dates = dates(40, start="2026-10-10", clusters=4)
        for i in range(40):
            specs.append((f"HOLD_{i:04d}", hold_dates[i], .55, .90, 1))
        rows = population(specs, scope="REMOTE_DURABLE_PROSPECTIVE", canonical=True)
        report = evaluate(rows, registry=registry("2026-10-10"), bootstrap_draws=100)
        self.assertEqual(report["decision"]["favored_arm"], "gamma_poisson_workload_mc")
        self.assertEqual(report["decision"]["status"], "REGIME_DEPENDENCE_RESEARCH_REQUIRED")
        self.assertEqual(report["decision"]["contradictory_stratum"], [0.8, 1.0])

    def test_untouched_holdout_must_confirm_same_arm(self):
        dev_dates = dates(220, start="2026-09-10", clusters=15)
        specs = [(f"DEV_{i:04d}", dev_dates[i], .55, .90, 1) for i in range(220)]
        hold_dates = dates(40, start="2026-10-10", clusters=4)
        specs += [(f"HOLD_{i:04d}", hold_dates[i], .90, .70, 1) for i in range(40)]
        rows = population(specs, scope="REMOTE_DURABLE_PROSPECTIVE", canonical=True)
        report = evaluate(rows, registry=registry("2026-10-10"), bootstrap_draws=100)
        self.assertEqual(report["decision"]["status"], "HOLDOUT_DID_NOT_CONFIRM")
        self.assertEqual(report["decision"]["favored_arm"], "gamma_poisson_workload_mc")

    def test_same_arm_confirmed_on_holdout_is_research_only_not_promotion(self):
        dev_dates = dates(220, start="2026-09-10", clusters=15)
        specs = [(f"DEV_{i:04d}", dev_dates[i], .55, .90, 1) for i in range(220)]
        hold_dates = dates(40, start="2026-10-10", clusters=4)
        specs += [(f"HOLD_{i:04d}", hold_dates[i], .55, .90, 1) for i in range(40)]
        rows = population(specs, scope="REMOTE_DURABLE_PROSPECTIVE", canonical=True)
        report = evaluate(rows, registry=registry("2026-10-10"), bootstrap_draws=100)
        self.assertEqual(report["decision"]["status"], "EVIDENCE_SUPPORTS_GAMMA_POISSON_RESEARCH_ONLY")
        self.assertFalse(report["decision"]["promotion_authority"])
        self.assertFalse(report["decision"]["action_authority"])


if __name__ == "__main__":
    unittest.main()
