from __future__ import annotations
import hashlib
import unittest

from research.mlb_distribution_experiment import DistributionExperimentError, evaluate


def h(value):
    return hashlib.sha256(value.encode()).hexdigest()


def rows_for_dates(n_dates=3):
    rows=[]
    for day in range(1,n_dates+1):
        outcome=0 if day==2 else 1
        for arm,p in (("analytic",.80),("monte_carlo",.65)):
            rows.append({
                "league":"MLB",
                "event_id":f"g{day}",
                "event_date_local":f"2026-09-{day:02d}",
                "forecast_cutoff_utc":f"2026-09-{day:02d}T00:00:00Z",
                "evidence_scope":"LOCAL_DIAGNOSTIC",
                "target_contract":{"winner_target":"MODEL_WINNER_WITH_DISCLOSED_TIE_PROXY"},
                "model_arm_id":arm,
                "model_id":"mlb.test.v1",
                "outcome_type":"BINARY_HOME_WIN",
                "outcome_value":outcome,
                "probabilities":{"home_win":p,"away_win":1-p},
                "grade_record_hash":h(f"grade-{day}"),
            })
    return rows


class MLBDistributionExperimentTests(unittest.TestCase):
    def test_scores_arms_separately_and_pairs_exact_population(self):
        r=evaluate(rows_for_dates(),bootstrap_draws=200)
        self.assertEqual(r["population"]["paired_event_count"],3)
        self.assertEqual(r["population"]["date_cluster_count"],3)
        self.assertIn("fixed_poisson",r["arm_metrics"])
        self.assertIn("gamma_poisson_workload_mc",r["arm_metrics"])
        self.assertEqual(r["paired_deltas_gamma_minus_fixed"]["log_loss_date_cluster_bootstrap"]["status"],"AVAILABLE")
        self.assertFalse(r["interpretation_contract"]["posthoc_arm_selection_permitted"])
        self.assertFalse(r["interpretation_contract"]["action_authority"])

    def test_missing_one_arm_fails_closed(self):
        rows=rows_for_dates()
        rows.pop()
        with self.assertRaisesRegex(DistributionExperimentError,"identical complete arm populations required"):
            evaluate(rows,bootstrap_draws=200)

    def test_one_date_refuses_bootstrap_but_keeps_descriptive_scores(self):
        r=evaluate(rows_for_dates(1),bootstrap_draws=200)
        self.assertEqual(r["paired_deltas_gamma_minus_fixed"]["log_loss_date_cluster_bootstrap"]["status"],"NOT_RUN_INSUFFICIENT_DATE_CLUSTERS")
        self.assertEqual(r["population"]["paired_event_count"],1)

    def test_unexpected_arm_fails_closed(self):
        rows=rows_for_dates()
        rows[0]["model_arm_id"]="mystery"
        with self.assertRaisesRegex(DistributionExperimentError,"unexpected MLB model arms"):
            evaluate(rows,bootstrap_draws=200)


if __name__ == "__main__": unittest.main()
