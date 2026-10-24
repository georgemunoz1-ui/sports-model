"""Cross-cutting equivalents of the October 19 external review probes.

These synthetic tests verify software contracts, not predictive performance.
"""
import copy
import math
import unittest
from unittest.mock import patch

import numpy as np

from models.common import discrete_research as D
from models.common import margin_system as M
from research.evaluate_margin_system import _block, evaluate, score_row
from tests.test_margin_system import binding, distribution
from tests.test_margin_system_evaluation import row


def seal(report):
    report["report_sha256"] = D.digest({k: v for k, v in report.items()
                                        if k != "report_sha256"})
    return report


class ExternalReviewRegressions(unittest.TestCase):
    def test_all_push_report_round_trips_and_stays_unconditional(self):
        d = distribution((3,), (1,))
        report = M.build_margin_report(d, home_spreads=[-3], draws=1000)
        self.assertEqual(M.validate_report(report, d), report["report_sha256"])
        quote = report["cover_ladder"][0]
        self.assertEqual(quote["probability_basis"], M.PROBABILITY_BASIS)
        for side in ("home", "away"):
            self.assertEqual(quote[side], dict(win=0., half_win=0., push=1., half_loss=0., loss=0.))
            self.assertIsNone(quote[side + "_fair_odds"]["decimal"])
        self.assertNotIn("p_cover_ex_push", quote)

    def test_resealed_cover_basis_removal_and_false_conditional_label_reject(self):
        d = distribution()
        original = M.build_margin_report(d, home_spreads=[-3], draws=50)
        for label in (None, "EXCLUDING_PUSHES"):
            candidate = copy.deepcopy(original)
            quote = candidate["cover_ladder"][0]
            if label is None:
                quote.pop("probability_basis")
            else:
                quote["probability_basis"] = label
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, "COVER_MISMATCH"):
                M.validate_report(seal(candidate), d)

    def test_resealed_derived_fields_and_simulation_reject(self):
        d = distribution()
        original = M.build_margin_report(d, home_spreads=[-3], draws=50)
        for field in ("analytics", "cover_ladder", "simulation"):
            candidate = copy.deepcopy(original)
            if field == "analytics":
                candidate[field]["mean_margin"] += .1
            elif field == "cover_ladder":
                candidate[field][0]["home"]["push"] = 0.
            else:
                candidate[field]["winner"]["home_win"]["count"] += 1
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "MISMATCH"):
                M.validate_report(seal(candidate), d)

    def test_builder_calls_validator_before_return(self):
        with patch.object(M, "validate_report", side_effect=ValueError("VALIDATOR_SENTINEL")):
            with self.assertRaisesRegex(ValueError, "VALIDATOR_SENTINEL"):
                M.build_margin_report(distribution(), draws=10)

    def test_nan_line_uses_coded_failure_at_all_entry_points(self):
        d = distribution()
        for value in (math.nan, math.inf, -math.inf):
            for call in (lambda: M.cover_ladder(d, [value]),
                         lambda: M.simulate_margin(d, draws=10, home_spreads=[value]),
                         lambda: D.price(d, value, "HOME")):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "FINITE_NUMBER_REQUIRED"):
                    call()

    def test_empirical_integer_atoms_have_matching_push_mass_and_simulation(self):
        d = M.from_margin_draws([-3, 3, 3, 7], orientation=M.ORIENTATION, **binding())
        values, simulation = M.simulate_margin(d, draws=100000, home_spreads=[-3, -3.5])
        quotes = M.cover_ladder(d, [-3.5, -3])
        self.assertEqual(quotes[1]["home"]["push"], .5)
        self.assertEqual(quotes[0]["home"]["push"], 0.)
        for analytic, simulated in zip(quotes, simulation["cover_ladder"]):
            for state in D.STATES:
                estimate = simulated["home"][state]
                self.assertLessEqual(abs(estimate["probability"] - analytic["home"][state]), .01)
        self.assertEqual(simulation["cover_ladder"][1]["home"]["push"]["count"],
                         int(np.count_nonzero(values == 3)))

    def test_degenerate_pmf_evaluation_keeps_push_category(self):
        r = row(observed=0, masses=(0, 1, 0))
        r["contracts"] = [{"line": 0, "side": "HOME"}]
        result = next(iter(score_row(r)["contracts"].values()))
        self.assertEqual(result["outcome"], "push")
        self.assertEqual(result["push"]["brier"], 0.)
        self.assertEqual(result["category_log_loss"], 0.)

    def test_actual_timestamps_control_chronology_not_season_strings(self):
        # Seasons are optional descriptive metadata here, never ordering keys.
        rows = [row(model, i) for i in range(4) for model in ("baseline", "challenger")]
        for i, record in enumerate(rows):
            record["season"] = 10 if i < 4 else 9
        a = evaluate(rows, baseline_id="baseline", challenger_id="challenger", bootstrap=100)
        for record in rows:
            record["season"] = str(record["season"])
        b = evaluate(list(reversed(rows)), baseline_id="baseline", challenger_id="challenger", bootstrap=100)
        for key in ("paired", "summaries_all_available", "bootstrap"):
            self.assertEqual(a[key], b[key])
        self.assertLess(_block("0009-06-01T00:00:00Z", "week"),
                        _block("0010-06-01T00:00:00Z", "week"))

    def test_scalar_sigma_or_sigma_dictionary_cannot_supply_a_distribution(self):
        for value in (12., {"sport": "nfl", "sigma": 12.}, {"sigma": 12., "provenance": {}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                M.from_discrete(value)

    def test_malformed_provenance_refuses_with_coded_error(self):
        for value in (None, [], ["base"], "database_residuals", 7):
            d = distribution()
            d["provenance"] = value
            d["distribution_sha256"] = D.digest({k: v for k, v in d.items() if k != "distribution_sha256"})
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "PROVENANCE_OBJECT_REQUIRED"):
                M.from_discrete(d)


if __name__ == "__main__":
    unittest.main()
