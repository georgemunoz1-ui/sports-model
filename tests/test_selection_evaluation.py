import copy
import math
import unittest

from research.selection_evaluation import (EvaluationError, evaluate_decisions,
                                           holm_adjust, paired_block_comparison, power_curve)
from research.validation_registry import content_id


def evaluation_fixture():
    rows = []
    for index, (decision, outcome, probability, baseline) in enumerate([
        ("BLOCKED", "LOSS", .9, .5), ("ELIGIBLE_NOT_SELECTED", "LOSS", .55, .5),
        ("SHADOW_SELECTED", "WIN", .7, .4), ("SHADOW_SELECTED", "PUSH", .8, .5),
        ("SHADOW_SELECTED", "LIVE", .75, .4), ("SHADOW_SELECTED", "VOID", .6, .5)]):
        rows.append({"event_id": str(index), "target_id": "target"+str(index), "slate_id": "slate"+str(index//2),
                     "procedure_id": content_id({"procedure": "candidate"}), "selector_config_id": content_id({"threshold": .6}),
                     "control_procedure_id": content_id({"procedure": "control"}), "target_family_id": content_id({"family": "nfl-spread"}),
                     "decision_class": decision, "outcome": outcome, "raw_probability": probability,
                     "control_probability": baseline, "control_target_id": "target"+str(index),
                     "control_predicted_outcome": "LOSS" if baseline < .5 else "WIN"})
    population = [{k: r[k] for k in ("event_id", "target_id", "slate_id")} for r in rows]
    return rows, population


class SelectionEvaluationTests(unittest.TestCase):
    def evaluate(self, rows, population):
        return evaluate_decisions(rows, population=population, evidence_scope="DISCOVERY", bootstrap_samples=100, seed=9)

    def test_full_denominator_no_abstention_wins_and_live_not_final(self):
        rows, population = evaluation_fixture()
        result = self.evaluate(rows, population)
        self.assertEqual(result["n_events"], 6)
        self.assertEqual(result["n_blocked"], 1)
        self.assertEqual(result["total_coverage"], 4/6)
        self.assertEqual(result["eligible_coverage"], 4/5)
        selected = result["selected_settlement"]
        self.assertEqual(selected["n_settled"], 3)
        self.assertEqual(selected["wins"], 1)
        self.assertEqual(selected["unconditional_win_accuracy"], 1/3)
        self.assertEqual(selected["decisive_only_accuracy_diagnostic"], 1)
        self.assertEqual(result["selected_unsettled"], 1)
        self.assertEqual(result["full_slate_raw_forecast_scores"]["n"], 5)
        self.assertFalse(result["qualification_granted"])

    def test_same_event_control_and_void_proper_score(self):
        rows, population = evaluation_fixture()
        result = self.evaluate(rows, population)
        pair = result["selected_same_event_control"]
        self.assertEqual(pair["n"], 3)
        self.assertAlmostEqual(pair["candidate_scores"]["brier"], (.09+.64+.36)/3)
        self.assertAlmostEqual(pair["control_scores"]["brier"], (.36+.25+.25)/3)
        self.assertEqual(pair["control_unconditional_win_accuracy"], 0)
        self.assertEqual(result["selected_settlement"]["voids"], 1)

    def test_population_cannot_drop_blocked_or_duplicate_games(self):
        rows, population = evaluation_fixture()
        for bad in (rows[1:], rows+[rows[0]]):
            with self.assertRaises(EvaluationError):
                self.evaluate(bad, population)
        with self.assertRaises(EvaluationError):
            self.evaluate(rows, population+[population[0]])

    def test_mixed_versions_and_mismatched_control_rejected(self):
        rows, population = evaluation_fixture()
        for key in ("procedure_id", "selector_config_id", "control_procedure_id", "target_family_id", "control_target_id"):
            mutated = copy.deepcopy(rows)
            mutated[0][key] = "f"*64
            with self.subTest(key=key), self.assertRaises(EvaluationError):
                self.evaluate(mutated, population)

    def test_missing_control_is_visible_and_does_not_change_candidate_population(self):
        rows, population = evaluation_fixture()
        for row in rows:
            row["control_probability"] = None
            row["control_procedure_id"] = None
        result = self.evaluate(rows, population)
        self.assertEqual(result["selected_same_event_control"]["n"], 0)
        self.assertEqual(result["selected_same_event_control"]["unpaired_settled_count"], 3)
        self.assertEqual(result["selected_forecast_scores"]["n"], 3)

    def test_no_selection_is_not_perfect_accuracy(self):
        rows, population = evaluation_fixture()
        for row in rows:
            row["decision_class"] = "BLOCKED"
        result = self.evaluate(rows, population)
        self.assertEqual(result["total_coverage"], 0)
        self.assertIsNone(result["eligible_coverage"])
        self.assertIsNone(result["selected_settlement"]["unconditional_win_accuracy"])
        self.assertEqual(result["risk_coverage_diagnostic_only"], [])

    def test_zero_realized_probability_is_not_epsilon_clipped(self):
        rows, population = evaluation_fixture()
        rows[2]["raw_probability"] = 0
        result = self.evaluate(rows, population)
        self.assertIsNone(result["selected_forecast_scores"]["log_loss"])
        self.assertEqual(result["selected_forecast_scores"]["infinite_log_loss_count"], 1)

    def test_tied_probability_curve_has_no_partial_tie_selection(self):
        rows, population = evaluation_fixture()
        for row in rows:
            row["raw_probability"] = .7
        result = self.evaluate(rows, population)
        self.assertEqual(len(result["risk_coverage_diagnostic_only"]), 1)
        self.assertEqual(result["risk_coverage_diagnostic_only"][0]["n_selected"], 5)

    def test_invalid_inputs_and_nonfinite_fail(self):
        rows, population = evaluation_fixture()
        for value in (True, math.nan, math.inf, 1.01):
            mutated = copy.deepcopy(rows)
            mutated[0]["raw_probability"] = value
            with self.assertRaises(EvaluationError):
                self.evaluate(mutated, population)


class PairedInferenceTests(unittest.TestCase):
    def test_block_bootstrap_deterministic_and_paired(self):
        records = [{"event_id": str(i), "block_id": str(i//2), "candidate_loss": .1, "control_loss": .2} for i in range(8)]
        a = paired_block_comparison(records, samples=100, seed=7)
        self.assertEqual(a, paired_block_comparison(records, samples=100, seed=7))
        self.assertAlmostEqual(a["mean_delta"], -.1)
        self.assertAlmostEqual(a["ci_lower"], -.1)
        self.assertAlmostEqual(a["ci_upper"], -.1)
        with self.assertRaises(EvaluationError):
            paired_block_comparison(records+[records[0]])

    def test_one_block_cannot_supply_uncertainty_interval(self):
        result = paired_block_comparison([{"event_id": "1", "block_id": "a", "candidate_loss": 0, "control_loss": 1}])
        self.assertEqual(result["status"], "INSUFFICIENT_BLOCKS")
        self.assertIsNone(result["ci_upper"])

    def test_holm_counts_unreported_configurations(self):
        result = holm_adjust({"a": .01, "b": .03}, total_trials=4)
        self.assertAlmostEqual(result["tests"]["a"]["adjusted_p_value"], .04)
        self.assertAlmostEqual(result["tests"]["b"]["adjusted_p_value"], .09)
        self.assertTrue(result["tests"]["a"]["reject"])
        self.assertFalse(result["tests"]["b"]["reject"])
        with self.assertRaises(EvaluationError):
            holm_adjust({"a": .01, "b": .03}, total_trials=1)
        with self.assertRaises(EvaluationError):
            holm_adjust({"a": .01})

    def test_power_uses_dependence_multiplicity_and_declared_effect(self):
        args = dict(minimum_useful_improvement=.02, paired_loss_sd=.2, design_effect=1,
                    alpha=.05, total_trials=1, target_power=.8)
        result = power_curve([100, 500, 1000], **args)
        self.assertLess(result["curve"][0]["power"], result["curve"][-1]["power"])
        conservative = power_curve([100], **dict(args, design_effect=2, total_trials=20))
        self.assertGreater(conservative["required_events_approximation"], result["required_events_approximation"])
        self.assertEqual(conservative["curve"][0]["effective_sample_size"], 50)
        self.assertFalse(result["qualification_granted"])
        with self.assertRaises(EvaluationError):
            power_curve([100], **dict(args, paired_loss_sd=0))


if __name__ == "__main__":
    unittest.main()
