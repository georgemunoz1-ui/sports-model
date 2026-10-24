"""Software contract tests; synthetic PMFs do not validate predictive quality."""
import copy
import hashlib
import json
import math
import unittest

import numpy as np

from models.common import discrete_research as D
from models.common import margin_system as M


SOURCE = "a" * 64
CUTOFF = "2026-10-19T12:00:00+00:00"


def distribution(values=(-7, 0, 3, 7), weights=(0.2, 0.1, 0.3, 0.4),
                 league="nfl", settlement="FULL_GAME_OT_REGULAR", provenance=None):
    return D.make_distribution(values, weights, league=league, product="margin",
                               settlement=settlement, model_id=league + ".fixture.research",
                               provenance=provenance or {"event_id": "fixture", "cutoff": CUTOFF})


def binding(league="nfl", settlement="FULL_GAME_OT_REGULAR"):
    return dict(league=league, settlement=settlement, model_id=league + ".fixture.research",
                event_id="fixture", cutoff=CUTOFF, source_sha256=SOURCE)


class SummaryTests(unittest.TestCase):
    def test_mean_and_winner_are_distinct_coherent_summaries(self):
        # Negative mean does not imply <50% home wins: magnitude and frequency
        # are different. Never manufacture agreement by replacing one output.
        s = M.summarize(distribution((-100, 1), (0.4, 0.6)))
        self.assertAlmostEqual(s["mean_margin"], -39.4)
        self.assertEqual(s["median_margin"], 1)
        self.assertEqual(s["mode_margins"], [1])
        self.assertAlmostEqual(s["winner"]["home_win"], 0.6)
        self.assertEqual(s["winner"]["method"], "SAME_MARGIN_PMF")

    def test_prediction_intervals_preserve_discrete_mass(self):
        d = distribution((-7, 0, 3, 7), (0.2, 0.1, 0.3, 0.4))
        s = M.summarize(d)
        self.assertEqual(s["median_margin"], 3)
        self.assertEqual(s["prediction_intervals"]["50"]["lower"], 0)
        self.assertEqual(s["prediction_intervals"]["50"]["upper"], 7)
        self.assertAlmostEqual(s["prediction_intervals"]["50"]["attained_probability"], 0.8)
        for interval in s["prediction_intervals"].values():
            self.assertGreaterEqual(interval["attained_probability"] + 1e-14,
                                    interval["nominal_probability"])
        self.assertEqual(s["prediction_intervals"]["95"]["lower"], -7)

    def test_quantiles_are_supported_integers_and_endpoints(self):
        d = distribution((-52, -3, 7, 52), (1, 1, 1, 1))
        self.assertEqual(M.quantile(d, 0), -52)
        self.assertEqual(M.quantile(d, 1), 52)
        self.assertEqual(M.quantile(d, 0.5), -3)
        self.assertEqual(M.summarize(d)["mode_margins"], [-52, -3, 7, 52])
        for q in [-0.01, 1.01, True, math.nan]:
            with self.subTest(q=q), self.assertRaises(ValueError):
                M.quantile(d, q)

    def test_winner_draw_mass_is_not_redistributed(self):
        s = M.summarize(distribution((-1, 0, 1), (0.2, 0.5, 0.3), "mls", "REGULATION_90_STOPPAGE"))
        self.assertEqual(s["winner"]["draw"], 0.5)
        self.assertEqual(s["winner"]["away_win"], 0.2)
        self.assertEqual(s["winner"]["home_win"], 0.3)

    def test_existing_zero_conditioning_is_visible_without_changing_forecast(self):
        d = distribution((-1, 1), (0.4, 0.6), "nhl", "FULL_GAME_OT_SO_PLUS_ONE",
                         {"removed_illegal_support_mass": 0.125,
                          "support_policy": "CONDITION_ON_LEGAL_SUPPORT"})
        before = copy.deepcopy(d)
        summary = M.summarize(d)
        self.assertEqual(summary["upstream_removed_illegal_support_mass"], 0.125)
        self.assertIn("UPSTREAM_ILLEGAL_SUPPORT_CONDITIONING_PRESENT", summary["limitations"])
        self.assertEqual(d, before)

    def test_new_challenger_conditioning_and_tail_truncation_are_visible(self):
        d = distribution((-1, 1), (0.4, 0.6), "nhl", "FULL_GAME_OT_SO_PLUS_ONE",
                         {"removed_zero_margin_mass_before_conditioning": 0.12,
                          "omitted_tail_probability_before_finite_renormalization": 4e-8})
        summary = M.summarize(d)
        self.assertEqual(summary["upstream_support_adjustments"]["removed_zero_margin_mass_before_conditioning"], 0.12)
        self.assertEqual(summary["upstream_support_adjustments"]["omitted_tail_probability_before_finite_renormalization"], 4e-8)
        self.assertIn("UPSTREAM_ILLEGAL_SUPPORT_CONDITIONING_PRESENT", summary["limitations"])
        self.assertIn("UPSTREAM_FINITE_TAIL_TRUNCATION_PRESENT", summary["limitations"])
        self.assertIsNone(summary["upstream_removed_illegal_support_mass"])

    def test_invalid_conditioning_mass_rejected(self):
        for value in (-0.1, 1.1, True, math.inf):
            d = distribution(provenance={"removed_zero_margin_mass_before_conditioning": value}) if math.isfinite(value) else None
            with self.subTest(value=value), self.assertRaises(ValueError):
                if d is None:
                    distribution(provenance={"removed_zero_margin_mass_before_conditioning": value})
                else:
                    M.summarize(d)

    def test_all_seven_leagues_have_contract_specific_summary(self):
        for league, options in D.SETTLEMENTS.items():
            for settlement, ties_allowed in options.items():
                with self.subTest(league=league, settlement=settlement):
                    values = [-2, 0, 3] if ties_allowed else [-2, 3]
                    d = distribution(values, [1] * len(values), league, settlement)
                    result = M.build_margin_report(d, home_spreads=[-1.5, 0, 1.5], draws=100)
                    self.assertEqual(result["settlement"], settlement)
                    self.assertEqual(result["analytics"]["winner"]["draw"] > 0, ties_allowed)
                    self.assertFalse(result["action_authority"])
                    self.assertFalse(result["prospective_grade_eligible"])

    def test_52_point_win_retains_real_tail_support(self):
        d = distribution((-7, 3, 52), (0.3, 0.6, 0.1), "cfb", "FULL_GAME_OT")
        row = M.cover_ladder(d, [-51.5])[0]
        self.assertAlmostEqual(row["home"]["win"], 0.1)
        self.assertEqual(M.summarize(d)["support_max"], 52)


class CoverTests(unittest.TestCase):
    def test_whole_number_push_and_selected_side_handicap(self):
        row = M.cover_ladder(distribution(), [-3])[0]
        self.assertEqual(row["side_handicaps"], {"HOME": -3.0, "AWAY": 3.0})
        self.assertEqual(row["line_basis"], "HOME_HANDICAP")
        self.assertAlmostEqual(row["home"]["win"], 0.4)
        self.assertAlmostEqual(row["home"]["push"], 0.3)
        self.assertAlmostEqual(row["home"]["loss"], 0.3)
        self.assertAlmostEqual(row["away"]["win"], 0.3)
        self.assertAlmostEqual(row["away"]["push"], 0.3)
        self.assertAlmostEqual(row["away"]["loss"], 0.4)

    def test_ladders_monotone_and_complementary(self):
        rows = M.cover_ladder(distribution(), [7, -7, -3.5, -3, -2.5, 0, 3])
        self.assertEqual([r["home_spread"] for r in rows], [-7, -3.5, -3, -2.5, 0, 3, 7])
        home_wins = [r["home"]["win"] for r in rows]
        self.assertEqual(home_wins, sorted(home_wins))
        for row in rows:
            for side in ("home", "away"):
                self.assertAlmostEqual(sum(row[side].values()), 1)
            for a, b in zip(D.STATES, reversed(D.STATES)):
                self.assertAlmostEqual(row["home"][a], row["away"][b])

    def test_negative_asian_quarter_uses_half_loss(self):
        d = distribution((-1, 0, 1), (0.2, 0.3, 0.5), "mls", "REGULATION_90_STOPPAGE")
        row = M.cover_ladder(d, [-0.25])[0]
        self.assertEqual(row["home"], dict(win=0.5, half_win=0, push=0, half_loss=0.3, loss=0.2))
        self.assertEqual(row["away"], dict(win=0.2, half_win=0.3, push=0, half_loss=0, loss=0.5))
        self.assertAlmostEqual(row["home_fair_odds"]["decimal"], 1.7)
        self.assertAlmostEqual(row["away_fair_odds"]["decimal"], 1 + 0.5 / 0.35)

    def test_positive_asian_quarter_uses_half_win(self):
        d = distribution((-1, 0, 1), (0.2, 0.3, 0.5), "mls", "REGULATION_90_STOPPAGE")
        row = M.cover_ladder(d, [0.25])[0]
        self.assertEqual(row["home"]["half_win"], 0.3)
        self.assertEqual(row["home"]["win"], 0.5)
        self.assertEqual(row["home"]["loss"], 0.2)

    def test_fair_odds_for_all_push_is_null_and_json_safe(self):
        row = M.cover_ladder(distribution((3,), (1,)), [-3])[0]
        self.assertIsNone(row["home_fair_odds"]["decimal"])
        self.assertEqual(row["home"]["push"], 1)
        json.dumps(row, allow_nan=False)

    def test_invalid_line_increments_and_duplicates_rejected(self):
        for lines in [[0, 0], [0.25], [1.1], [math.inf], [False]]:
            with self.subTest(lines=lines), self.assertRaises(ValueError):
                M.cover_ladder(distribution(), lines)


class AdapterTests(unittest.TestCase):
    def test_joint_score_pairing_weights_and_identity_preserved(self):
        d = M.from_joint_scores([17, 10, 3], [10, 17, 3], weights=[2, 1, 1], **binding())
        self.assertEqual(d["support"], [-7, 0, 7])
        self.assertEqual(d["masses"], [0.25, 0.25, 0.5])
        self.assertEqual(d["provenance"]["source_sha256"], SOURCE)
        self.assertTrue(d["provenance"]["joint_score_distribution"])
        self.assertEqual(d["provenance"]["removed_illegal_support_mass"], 0)

    def test_explicit_reverse_orientation_converts_exactly_once(self):
        d = M.from_margin_draws([7, -3, -3], orientation="AWAY_MINUS_HOME", **binding())
        self.assertEqual(d["support"], [-7, 3])
        self.assertEqual(d["masses"], [1 / 3, 2 / 3])
        self.assertEqual(d["provenance"]["input_orientation"], "AWAY_MINUS_HOME")
        self.assertEqual(d["provenance"]["orientation"], "HOME_MINUS_AWAY")

    def test_draw_adapter_exposes_source_sampling_uncertainty(self):
        d = M.from_margin_draws([1, 1, 3], orientation=M.ORIENTATION, **binding())
        self.assertIn("SOURCE_SAMPLING_UNCERTAINTY_NOT_ESTIMATED_BY_RESIMULATION",
                      M.summarize(d)["limitations"])

    def test_no_tie_contract_never_drops_zero_margin(self):
        for league, settlements in D.SETTLEMENTS.items():
            for settlement, ties_allowed in settlements.items():
                if not ties_allowed:
                    kwargs = binding(league, settlement)
                    with self.subTest(league=league, settlement=settlement):
                        with self.assertRaisesRegex(ValueError, "FINAL_TIE_UNSUPPORTED"):
                            M.from_margin_draws([0, 1], orientation=M.ORIENTATION, **kwargs)
                        with self.assertRaisesRegex(ValueError, "FINAL_TIE_UNSUPPORTED"):
                            M.from_joint_scores([2, 3], [2, 2], **kwargs)

    def test_regulation_ties_cannot_be_relabelled_final_nhl(self):
        d = M.from_joint_scores([1, 2], [1, 1], **binding("nhl", "REGULATION"))
        self.assertEqual(M.summarize(d)["winner"]["draw"], 0.5)
        with self.assertRaisesRegex(ValueError, "FINAL_TIE_UNSUPPORTED"):
            M.from_joint_scores([1, 2], [1, 1], **binding("nhl", "FULL_GAME_OT_SO_PLUS_ONE"))

    def test_malformed_scores_and_weights_rejected(self):
        cases = [([1], [1, 2], None), ([1.5], [2], None), ([-1], [2], None),
                 ([True], [2], None), ([math.nan], [2], None), ([2**60], [2], None),
                 ([], [], None), ([1], [2], [-1]), ([1], [2], [0]),
                 ([1], [2], [1, 1])]
        for home, away, weights in cases:
            with self.subTest(home=home, away=away, weights=weights), self.assertRaises(ValueError):
                M.from_joint_scores(home, away, weights=weights, **binding())

    def test_binding_requires_hash_timezone_and_event(self):
        for field, value in [("source_sha256", "fake"), ("cutoff", "2026-10-19"), ("event_id", "")]:
            kwargs = binding()
            kwargs[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                M.from_joint_scores([1], [2], **kwargs)

    def test_noninteger_or_unspecified_margin_rejected(self):
        for values, orientation in [([0.55], M.ORIENTATION), ([1], "UNKNOWN"), ([False], M.ORIENTATION)]:
            with self.subTest(values=values, orientation=orientation), self.assertRaises(ValueError):
                M.from_margin_draws(values, orientation=orientation, **binding())
        with self.assertRaises(TypeError):
            M.from_margin_draws([1], **binding())

    def test_adapter_does_not_mutate_or_alias_source(self):
        original = distribution()
        adapted = M.from_discrete(original)
        self.assertEqual(original, adapted)
        adapted["provenance"]["event_id"] = "changed"
        self.assertEqual(original["provenance"]["event_id"], "fixture")

    def test_hash_tampering_and_wrong_product_rejected(self):
        d = distribution()
        d["masses"][0] += 0.01
        with self.assertRaisesRegex(ValueError, "HASH_MISMATCH"):
            M.summarize(d)
        total = D.make_distribution([1, 2], [1, 1], league="nfl", product="total",
                                    settlement="FULL_GAME_OT_REGULAR", model_id="test", provenance={})
        with self.assertRaisesRegex(ValueError, "MARGIN_DISTRIBUTION_REQUIRED"):
            M.summarize(total)

    def test_silently_reversed_provenance_rejected(self):
        d = distribution(provenance={"orientation": "AWAY_MINUS_HOME"})
        with self.assertRaisesRegex(ValueError, "HOME_MINUS_AWAY_REQUIRED"):
            M.from_discrete(d)


class SimulationTests(unittest.TestCase):
    def test_100k_draws_replay_bytes_and_hash(self):
        d = distribution()
        first, report = M.simulate_margin(d, home_spreads=[-3, -3.5])
        second, replay = M.simulate_margin(d, home_spreads=[-3, -3.5])
        self.assertEqual(len(first), 100000)
        self.assertEqual(first.tobytes(), second.tobytes())
        self.assertEqual(report, replay)
        self.assertEqual(report["receipt"]["draw_sha256"], hashlib.sha256(first.tobytes()).hexdigest())
        self.assertEqual(report["winner"]["home_win"]["count"], int((first > 0).sum()))
        self.assertEqual(report["cover_ladder"][1]["home"]["push"]["count"], int((first == 3).sum()))
        # Sampling precision is checked against its actual binomial sampling
        # scale; this is not an accuracy or model-calibration test.
        estimate = report["winner"]["home_win"]
        self.assertLess(abs(estimate["probability"] - 0.7), 6 * math.sqrt(0.7 * 0.3 / 100000))

    def test_mc_uncertainty_is_distinct_and_nonzero_at_no_observed_events(self):
        _, r = M.simulate_margin(distribution((1,), (1,)), draws=1000)
        e = r["winner"]["away_win"]
        self.assertEqual(e["count"], 0)
        self.assertEqual(e["mc_standard_error"], 0)
        self.assertGreater(e["mc_confidence_interval"][1], 0)
        self.assertEqual(r["uncertainty_kind"], "NUMERICAL_MONTE_CARLO_ERROR_CONDITIONAL_ON_FIXED_PMF")
        self.assertIn("NOT_PREDICTIVE_OR_PARAMETER_UNCERTAINTY", r["limitations"])

    def test_simulated_quarter_state_counts_match_direct_settlement(self):
        d = distribution((-1, 0, 1), (0.2, 0.3, 0.5), "mls", "REGULATION_90_STOPPAGE")
        values, r = M.simulate_margin(d, draws=1000, home_spreads=[-0.25])
        row = r["cover_ladder"][0]
        self.assertEqual(row["home"]["half_loss"]["count"], int((values == 0).sum()))
        self.assertEqual(row["away"]["half_win"]["count"], int((values == 0).sum()))

    def test_report_is_json_safe_hash_bound_and_nonmutating(self):
        d = distribution()
        before = copy.deepcopy(d)
        r = M.build_margin_report(d, home_spreads=(line for line in [-3, 3]), draws=100)
        json.dumps(r, allow_nan=False)
        expected_hash = r.pop("report_sha256")
        self.assertEqual(D.digest(r), expected_hash)
        self.assertEqual(d, before)
        self.assertEqual(r["distribution_sha256"], d["distribution_sha256"])
        self.assertEqual(len(r["cover_ladder"]), 2)

    def test_draw_count_limits_and_one_draw_mean_se(self):
        for n in [0, -1, 1000001, True, 1.5]:
            with self.subTest(n=n), self.assertRaises(ValueError):
                M.simulate_margin(distribution(), draws=n)
        _, r = M.simulate_margin(distribution(), draws=1)
        self.assertIsNone(r["mean_margin_mc_standard_error"])


if __name__ == "__main__":
    unittest.main()
