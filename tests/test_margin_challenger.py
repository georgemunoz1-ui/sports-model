"""Software falsifications for a new challenger, not evidence of sporting skill."""
import copy
import datetime as dt
import unittest
from unittest import mock

import numpy as np

from models.common import margin_challenger as challenger
from models.common.discrete_research import digest, price, score, simulate, validate


def cohort(league="cfb", settlement="FULL_GAME_OT", count=90):
    start = dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc)
    out = []
    for i in range(count):
        game = start + dt.timedelta(days=i * 3)
        x = i % 2
        error = [-3, -2, -1, 1, 2, 3][i % 6] * (1 + 3 * x)
        observed = 7 + error
        if observed == 0 and settlement != "REGULATION_90_STOPPAGE":
            observed = 1
        out.append({"event_id": f"{league}:{i}", "league": league, "product": "margin",
                    "settlement": settlement, "parent_model_id": league + ".parent",
                    "information_set": "SYNTHETIC_SOFTWARE_TEST_ONLY", "market_input": False,
                    "parent_fit_cutoff": "2021-01-01T00:00:00Z",
                    "forecast_cutoff": (game - dt.timedelta(hours=1)).isoformat(),
                    "start_time_utc": game.isoformat(),
                    "result_available_at": (game + dt.timedelta(days=1)).isoformat(),
                    "forecast_sha256": digest({"software_forecast": i}),
                    "result_source_sha256": digest({"software_result": i}),
                    "prediction_kind": "CHRONOLOGICAL_OUT_OF_TIME", "predicted_mean": 7.,
                    "observed": observed, "scale_features": {"dispersion_driver": float(x)},
                    "source_capture_kind": "SYNTHETIC_SOFTWARE_TEST",
                    "timestamp_basis": "SIMULATED", "historical_availability_proven": False})
    return out


def fit(rows, **overrides):
    args = {"league": rows[0]["league"], "settlement": rows[0]["settlement"],
            "parent_model_id": rows[0]["parent_model_id"],
            "information_set": rows[0]["information_set"],
            "fitted_at": "2023-01-01T00:00:00Z", "scale_features": ("dispersion_driver",)}
    args.update(overrides)
    return challenger.fit(rows, **args)


def prediction(model, **overrides):
    args = {"mean": 7., "event_id": "UNSEEN_EVENT", "cutoff": "2023-02-01T00:00:00Z",
            "start_time_utc": "2023-02-01T01:00:00Z", "parent_model_id": model["parent_model_id"],
            "information_set": model["information_set"], "parent_forecast_sha256": "a" * 64,
            "scale_features": {"dispersion_driver": 0.}}
    args.update(overrides)
    return challenger.predict(model, **args)


def reseal(model):
    """Recompute both hashes so structural tests cannot pass on hash failure."""
    model.pop("artifact_sha256", None)
    model.pop("model_id", None)
    model["model_id"] = f"{model['league']}.margin.full_support.research." + digest(model)[:16]
    model["artifact_sha256"] = digest(model)
    return model


class MarginChallengerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = cohort()
        cls.model = fit(cls.rows)

    def test_full_integer_support_repairs_unseen_fifty_two_margin(self):
        distribution = prediction(self.model)
        x, p = validate(distribution)
        self.assertNotIn(0, x)
        self.assertTrue(np.all(p > 0))
        self.assertEqual(set(x), set(range(int(x.min()), int(x.max()) + 1)) - {0})
        self.assertFalse(score(distribution, 52)["zero_probability_outcome"])
        self.assertTrue(np.isfinite(score(distribution, 52)["log_loss"]))
        self.assertAlmostEqual(float(p.sum()), 1.)

    def test_removed_zero_and_truncated_tails_are_explicit(self):
        provenance = prediction(self.model)["provenance"]
        self.assertGreater(provenance["removed_zero_margin_mass_before_conditioning"], 0.)
        self.assertLessEqual(provenance["omitted_tail_probability_before_finite_renormalization"], challenger.TAIL_TOLERANCE)
        self.assertFalse(provenance["no_tie_conditioning_is_mechanistic_overtime_model"])
        self.assertEqual(provenance["outside_represented_support"], "OMITTED_TAIL_NOT_IMPOSSIBLE")

    def test_conditional_scale_is_fitted_and_consumed(self):
        low = prediction(self.model)["provenance"]
        high = prediction(self.model, scale_features={"dispersion_driver": 1.})["provenance"]
        self.assertGreater(high["conditional_scale"], low["conditional_scale"])
        self.assertEqual(high["scale_features_used"], {"dispersion_driver": 1.})

    def test_home_minus_away_contract_and_push(self):
        d = prediction(self.model)
        home = price(d, -7, "HOME")
        away = price(d, -7, "AWAY")
        self.assertGreater(home["push"], 0.)
        self.assertAlmostEqual(home["win"], away["loss"])
        self.assertAlmostEqual(home["loss"], away["win"])
        self.assertEqual(price(d, -7.5, "HOME")["push"], 0.)

    def test_real_draws_replay_exactly(self):
        d = prediction(self.model)
        a, ar = simulate(d, draws=100000)
        b, br = simulate(d, draws=100000)
        self.assertTrue(np.array_equal(a, b))
        self.assertEqual(ar["draw_sha256"], br["draw_sha256"])

    def test_internal_tuning_is_purged_and_never_claimed_validation(self):
        selection = self.model["selection"]
        rows = {r["event_id"]: r for r in self.rows}
        cutoff = challenger.stamp(selection["first_tuning_forecast_cutoff"])
        for eid in selection["inner_training_event_ids"]:
            self.assertLess(challenger.stamp(rows[eid]["result_available_at"]), cutoff)
        self.assertFalse(set(selection["inner_training_event_ids"]) & set(selection["tuning_event_ids"]))
        self.assertFalse(selection["external_performance_evidence"])
        self.assertEqual(len(selection["tail_trials"]), 48)
        self.assertEqual(len(selection["lattice_trials"]), 3)

    def test_source_attestation_cannot_be_created_by_fitting(self):
        self.assertFalse(self.model["historical_availability_proven"])
        d = prediction(self.model)
        self.assertFalse(d["provenance"]["historical_availability_proven"])
        self.assertFalse(d["provenance"]["artifact_existed_at_forecast_cutoff"])
        self.assertFalse(d["action_authority"])
        self.assertFalse(d["prospective_grade_eligible"])

    def test_hash_tampering_refused(self):
        model = copy.deepcopy(self.model)
        model["parameters"]["student_weight"] = .99
        with self.assertRaisesRegex(ValueError, "HASH_MISMATCH"):
            prediction(model)

    def test_training_oof_evidence_is_retained_and_revalidated(self):
        self.assertEqual(len(self.model["training_evidence"]), len(self.rows))
        self.assertEqual(challenger.validate_model(self.model), self.model["artifact_sha256"])
        for row in self.model["training_evidence"]:
            self.assertEqual(row["prediction_kind"], "CHRONOLOGICAL_OUT_OF_TIME")
            self.assertEqual(row["parent_model_id"], self.model["parent_model_id"])

    def test_resealed_zero_or_missing_oof_evidence_is_rejected(self):
        for mutation in (
                lambda m: m.update(training_n=0),
                lambda m: m.pop("training_evidence"),
                lambda m: m.update(training_evidence=[]),
                lambda m: m.update(training_event_ids=[]),
                lambda m: m["training_evidence"][0].pop("prediction_kind"),
                lambda m: m["training_evidence"][0].update(prediction_kind="IN_SAMPLE"),
                lambda m: m["training_evidence"][0].update(label_in_sample=True),
                lambda m: m["training_evidence"][0].update(oof=False)):
            with self.subTest(mutation=mutation):
                model = copy.deepcopy(self.model)
                mutation(model)
                with self.assertRaises(ValueError):
                    challenger.validate_model(reseal(model))

    def test_resealed_parent_chronology_state_and_selection_are_rejected(self):
        cases = (
            lambda m: m.update(parent_model_id=""),
            lambda m: m.update(parent_model_id="other-parent"),
            lambda m: m.update(last_result_available_at="2024-01-01T00:00:00Z"),
            lambda m: m["training_evidence"][0].update(parent_fit_cutoff="2024-01-01T00:00:00Z"),
            lambda m: m["training_evidence"][0].update(forecast_sha256="unhashed"),
            lambda m: m["state"].update(residuals=[]),
            lambda m: m["state"].update(student_standard_deviation=0.),
            lambda m: m["state"]["scaling"].update(sd=[0.]),
            lambda m: m["parameters"].update(degrees_of_freedom=1.),
            lambda m: m["lattice"].update(factors=[0.]),
            lambda m: m["selection"].update(tuning_event_ids=m["selection"]["inner_training_event_ids"]),
            lambda m: m["selection"].update(first_tuning_forecast_cutoff="2021-01-01T00:00:00Z"),
            lambda m: m.update(historical_availability_proven=True),
            lambda m: m["support_policy"].update(tail_tolerance=1.),
        )
        for mutation in cases:
            with self.subTest(mutation=mutation):
                model = copy.deepcopy(self.model)
                mutation(model)
                with self.assertRaises(ValueError):
                    challenger.validate_model(reseal(model))

    def test_hash_valid_but_wrong_model_identity_is_rejected(self):
        model = copy.deepcopy(self.model)
        model["model_id"] = "invented"
        model.pop("artifact_sha256")
        model["artifact_sha256"] = digest(model)
        with self.assertRaisesRegex(ValueError, "ID_MISMATCH"):
            challenger.validate_model(model)

    def test_old_artifact_is_rejected_explicitly_before_new_evidence_requirement(self):
        model = copy.deepcopy(self.model)
        model.pop("training_evidence")
        model["code_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "CODE_DRIFT"):
            challenger.validate_model(reseal(model))

    def test_fit_checks_own_artifact_before_returning(self):
        with mock.patch.object(challenger, "validate_model", side_effect=ValueError("SELF_VALIDATION_SENTINEL")) as check:
            with self.assertRaisesRegex(ValueError, "SELF_VALIDATION_SENTINEL"):
                fit(self.rows)
            check.assert_called_once()

    def test_missing_or_contradictory_oof_claim_cannot_fit(self):
        for change in ({"prediction_kind": None}, {"label_in_sample": True}, {"oof": False},
                       {"label_in_sample": 0}, {"oof": 1}):
            with self.subTest(change=change):
                rows = copy.deepcopy(self.rows)
                rows[0].update(change)
                with self.assertRaisesRegex(ValueError, "OUT_OF_TIME"):
                    fit(rows)
        rows = copy.deepcopy(self.rows)
        rows[0].pop("prediction_kind")
        with self.assertRaisesRegex(ValueError, "OUT_OF_TIME"):
            fit(rows)

    def test_missing_required_row_field_has_coded_failure(self):
        for key in ("parent_fit_cutoff", "forecast_sha256", "observed", "parent_model_id"):
            rows = copy.deepcopy(self.rows)
            rows[-1].pop(key)
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "TRAINING_ROW_STRUCTURE_INVALID"):
                fit(rows)

    def test_reversed_training_window_and_single_row_are_rejected(self):
        rows = copy.deepcopy(self.rows)
        rows[-1]["parent_fit_cutoff"] = "2024-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "TRAINING_CHRONOLOGY_INVALID"):
            fit(rows)
        with self.assertRaisesRegex(ValueError, "AT_LEAST_60"):
            fit(self.rows[:1])

    def test_zero_variance_retains_declared_positive_floor_and_replays(self):
        rows = cohort(count=60)
        for row in rows:
            row["observed"] = row["predicted_mean"] = 7.
        model = fit(rows, scale_features=())
        self.assertEqual(model["state"]["student_standard_deviation"], .25)
        self.assertEqual(model["state"]["minimum_standard_deviation"], .25)
        distribution = prediction(model, scale_features=None)
        x, p = validate(distribution)
        self.assertTrue(np.all(np.isfinite(p)))
        self.assertTrue(np.all(p > 0))
        first, receipt = simulate(distribution, draws=10000)
        second, replay = simulate(distribution, draws=10000)
        self.assertTrue(np.array_equal(first, second))
        self.assertEqual(receipt, replay)

    def test_future_fit_late_forecast_and_reused_event_refused(self):
        cases = [{"cutoff": "2022-12-31T00:00:00Z"},
                 {"start_time_utc": "2023-01-31T00:00:00Z"},
                 {"event_id": self.rows[0]["event_id"]}]
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                prediction(self.model, **overrides)

    def test_parent_and_information_scope_refused(self):
        for overrides in ({"parent_model_id": "different-parent"}, {"information_set": "other"},
                          {"parent_forecast_sha256": "unhashed"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                prediction(self.model, **overrides)

    def test_extra_or_missing_prediction_features_refused(self):
        for features in ({}, {"dispersion_driver": 0., "market_odds": 2.}):
            with self.subTest(features=features), self.assertRaises((ValueError, KeyError)):
                prediction(self.model, scale_features=features)

    def test_small_training_sample_refused(self):
        with self.assertRaisesRegex(ValueError, "AT_LEAST_60"):
            fit(self.rows[:59])

    def test_future_result_bad_source_and_wrong_parent_refused(self):
        cases = [("result_available_at", "2024-01-01T00:00:00Z"),
                 ("forecast_sha256", "bad-source"), ("parent_model_id", "other"),
                 ("settlement", "REGULATION"), ("prediction_kind", "IN_SAMPLE")]
        for field, value in cases:
            rows = copy.deepcopy(self.rows)
            rows[-1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                fit(rows)

    def test_market_and_outcome_features_refused(self):
        for feature in ("market_odds", "final_score"):
            rows = copy.deepcopy(self.rows)
            for row in rows:
                row["scale_features"][feature] = 1.
            with self.subTest(feature=feature), self.assertRaises(ValueError):
                fit(rows, scale_features=(feature,))

    def test_duplicate_rows_refused(self):
        with self.assertRaisesRegex(ValueError, "DUPLICATE_TRAINING_EVENT"):
            fit(self.rows + [self.rows[0]])

    def test_no_remaining_training_block_after_embargo_refused(self):
        rows = copy.deepcopy(self.rows)
        for row in rows:
            row["result_available_at"] = "2022-12-31T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "INSUFFICIENT_PURGED"):
            fit(rows)

    def test_unrepresentable_tail_is_not_silently_clipped(self):
        with self.assertRaisesRegex(ValueError, "TAIL_TRUNCATION|NO_REPRESENTABLE"):
            prediction(self.model, scale_features={"dispersion_driver": 1000.})

    def test_all_seven_sport_scopes_and_draw_semantics(self):
        scopes = [("nfl", "FULL_GAME_OT_REGULAR", True), ("cfb", "FULL_GAME_OT", False),
                  ("nba", "FULL_GAME_OT", False), ("wnba", "FULL_GAME_OT", False),
                  ("mlb", "COMPLETED_GAME_EXTRA_INNINGS", False),
                  ("nhl", "FULL_GAME_OT_SO_PLUS_ONE", False), ("mls", "REGULATION_90_STOPPAGE", True)]
        for league, settlement, ties in scopes:
            with self.subTest(league=league):
                model = self.model if league == "cfb" else fit(cohort(league, settlement, count=60))
                distribution = prediction(model)
                self.assertEqual(distribution["league"], league)
                self.assertEqual(distribution["settlement"], settlement)
                self.assertEqual(0 in distribution["support"], ties)


if __name__ == "__main__":
    unittest.main()
