import math
import unittest

from models.common.post_freeze_shock_ledger_v1 import (
    SCHEMA_VERSION,
    build_shock_record,
    compute_official_grade,
    validate_shock_record,
)


class PostFreezeShockLedgerTests(unittest.TestCase):
    def _base(self, **kwargs):
        params = {
            "shock_id": "NFL_2026-09-09_NE_SEA_001",
            "event_id": "NFL_2026-09-09_NE_SEA",
            "forecast_identity": {
                "forecast_output_hash": "sha256:test",
                "registered_at_utc": "2026-09-10T00:01:52Z",
                "scheduled_start_utc": "2026-09-10T00:20:00Z",
                "model_id": "nfl.contextual_information_shadow.v0_2.research",
                "model_version": "0.2.0",
            },
            "pregame_state": {
                "team_id": "SEA",
                "expected_player_id": "SAM_DARNOLD",
                "expected_player_role": "QB1",
                "qb_availability_probability": 1.0,
                "forecast_home_win_probability": 0.634384,
                "forecast_home_margin": 4.883138,
                "forecast_total": 46.958898,
            },
            "observed_final": {"home_score": 13, "away_score": 10},
            "realized_state": {
                "shock_type": "STARTING_QB_INJURY",
                "occurred_after_kickoff": True,
                "timing_phase": "FIRST_DRIVE",
                "outgoing_player_id": "SAM_DARNOLD",
                "outgoing_player_returned": False,
                "incoming_player_id": "DREW_LOCK",
                "incoming_player_role": "QB2",
                "replacement_share_of_game": "NEAR_FULL_GAME",
                "severity": "HIGH",
            },
            "value_delta": {
                "status": "NOT_ESTABLISHED",
                "method": "UNVALIDATED_RESEARCH_ESTIMATE",
                "metric": "EXPECTED_OFFENSIVE_POINTS_PER_FULL_GAME",
                "outgoing_value": None,
                "incoming_value": None,
                "incoming_minus_outgoing": None,
                "posterior_interval_50": None,
                "posterior_interval_90": None,
                "model_confidence": None,
                "source_model_id": None,
                "source_model_version": None,
            },
        }
        params.update(kwargs)
        return params

    def test_official_grade_is_frozen_forecast_vs_final(self):
        grade = compute_official_grade(
            forecast_home_win_probability=0.634384,
            forecast_home_margin=4.883138,
            forecast_total=46.958898,
            observed_home_score=13,
            observed_away_score=10,
        )
        self.assertAlmostEqual(grade["brier"], 0.133675059456, places=12)
        self.assertAlmostEqual(grade["log_loss"], -math.log(0.634384), places=12)
        self.assertAlmostEqual(grade["margin_absolute_error"], 1.883138, places=12)
        self.assertAlmostEqual(grade["total_absolute_error"], 23.958898, places=12)
        self.assertTrue(grade["official_grade_unchanged"])
        self.assertFalse(grade["shock_adjustment_applied"])

    def test_not_established_delta_stays_null(self):
        record = build_shock_record(**self._base())
        self.assertEqual(record["schema_version"], SCHEMA_VERSION)
        delta = record["layer_2_realized_state_diagnostic"]["value_delta"]
        self.assertEqual(delta["status"], "NOT_ESTABLISHED")
        self.assertIsNone(delta["incoming_minus_outgoing"])
        self.assertFalse(delta["eligible_for_official_rescoring"])
        self.assertFalse(record["layer_2_realized_state_diagnostic"]["counterfactual_analysis_allowed"])

    def test_shock_never_rewrites_layer_1(self):
        record = build_shock_record(**self._base())
        layer1 = record["layer_1_official_prospective_grade"]
        self.assertEqual(layer1["pregame_state"]["forecast_home_win_probability"], 0.634384)
        self.assertEqual(layer1["pregame_state"]["forecast_home_margin"], 4.883138)
        self.assertEqual(layer1["pregame_state"]["forecast_total"], 46.958898)
        self.assertFalse(layer1["counterfactual_qb_replacement_applied"])
        self.assertTrue(layer1["primary_scores_retained"])

    def test_post_kickoff_requirement_fails_closed(self):
        params = self._base()
        params["realized_state"]["occurred_after_kickoff"] = False
        with self.assertRaisesRegex(ValueError, "POST_FREEZE_SHOCK_MUST_OCCUR_AFTER_KICKOFF"):
            build_shock_record(**params)

    def test_not_established_cannot_smuggle_numeric_delta(self):
        params = self._base()
        params["value_delta"]["incoming_minus_outgoing"] = -4.0
        with self.assertRaisesRegex(ValueError, "VALUE_DELTA_NOT_ESTABLISHED_MUST_NOT_CONTAIN_ESTIMATES"):
            build_shock_record(**params)

    def test_unvalidated_delta_requires_versioned_source_and_still_cannot_rescore(self):
        params = self._base()
        params["value_delta"] = {
            "status": "UNVALIDATED_RESEARCH_ESTIMATE",
            "method": "POSTERIOR_PLAYER_VALUE_MODEL",
            "metric": "EXPECTED_OFFENSIVE_POINTS_PER_FULL_GAME",
            "outgoing_value": 4.0,
            "incoming_value": 1.0,
            "incoming_minus_outgoing": -3.0,
            "posterior_interval_50": [-4.0, -2.0],
            "posterior_interval_90": [-6.0, 0.0],
            "model_confidence": "LOW",
            "source_model_id": "nfl.qb_value.experimental",
            "source_model_version": "0.1.0",
        }
        record = build_shock_record(**params)
        delta = record["layer_2_realized_state_diagnostic"]["value_delta"]
        self.assertEqual(delta["status"], "UNVALIDATED_RESEARCH_ESTIMATE")
        self.assertFalse(delta["eligible_for_pregame_adjustment"])
        self.assertFalse(delta["eligible_for_official_rescoring"])
        self.assertFalse(delta["eligible_for_model_promotion"])
        self.assertFalse(record["layer_2_realized_state_diagnostic"]["counterfactual_analysis_allowed"])

    def test_counterfactual_requires_validated_research_value_model(self):
        with self.assertRaisesRegex(ValueError, "COUNTERFACTUAL_REQUIRES_VALIDATED_RESEARCH_VALUE_MODEL"):
            build_shock_record(**self._base(counterfactual_status="RESEARCH_ONLY"))

    def test_validator_detects_official_grade_mutation(self):
        record = build_shock_record(**self._base())
        record["layer_1_official_prospective_grade"]["official_grade"]["brier"] = 0.0
        with self.assertRaisesRegex(ValueError, "OFFICIAL_GRADE_MUTATION_OR_MISMATCH"):
            validate_shock_record(record)


if __name__ == "__main__":
    unittest.main()
