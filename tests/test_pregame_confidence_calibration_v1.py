import unittest

from models.common.pregame_confidence_calibration_v1 import (
    RULE_ID,
    STANDARD_ID,
    evaluate_pregame_confidence,
    validate_confidence_record,
)


class PregameConfidenceCalibrationTests(unittest.TestCase):
    def _triggering(self, **kwargs):
        params = dict(
            league="NFL",
            event_id="401872657",
            season_week=2,
            rating_freshness="PRIOR_SEASON_ONLY",
            current_state_application="CAPTURED_NOT_APPLIED",
            known_disruption=True,
            current_season_form_state="UNAVAILABLE",
        )
        params.update(kwargs)
        return params

    def test_named_rule_triggers_without_outcome_input(self):
        record = evaluate_pregame_confidence(**self._triggering())
        self.assertEqual(record["standard_id"], STANDARD_ID)
        self.assertEqual(record["rule_id"], RULE_ID)
        self.assertTrue(record["rule_triggered"])
        self.assertEqual(record["forecast_tier"], "REDUCED")
        self.assertEqual(record["confidence_support_dose_cap"], 0.6)
        self.assertEqual(record["uncertainty_policy"], "WIDEN_REQUIRED_EXACT_SCALE_NOT_ESTABLISHED")
        self.assertIsNone(record["uncertainty_scale_numeric"])
        self.assertFalse(record["hindsight_outcome_used_by_rule"])

    def test_rule_does_not_rewrite_probability_or_mean(self):
        record = evaluate_pregame_confidence(**self._triggering())
        self.assertFalse(record["probability_rescaling_permitted"])
        self.assertFalse(record["mean_forecast_adjustment_permitted"])
        self.assertFalse(record["historical_forecast_rewrite_permitted"])
        self.assertEqual(record["causal_attribution"], "NOT_CLAIMED")

    def test_week_three_does_not_trigger_this_named_rule(self):
        record = evaluate_pregame_confidence(**self._triggering(season_week=3))
        self.assertFalse(record["rule_triggered"])
        self.assertEqual(record["forecast_tier"], "STANDARD")
        self.assertEqual(record["confidence_support_dose_cap"], 1.0)

    def test_applied_current_state_does_not_trigger_this_named_rule(self):
        record = evaluate_pregame_confidence(**self._triggering(current_state_application="APPLIED"))
        self.assertFalse(record["rule_triggered"])

    def test_no_known_disruption_does_not_trigger_this_named_rule(self):
        record = evaluate_pregame_confidence(**self._triggering(known_disruption=False))
        self.assertFalse(record["rule_triggered"])

    def test_action_authority_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "ACTION_AUTHORITY_NOT_GRANTED_BY_CONFIDENCE_STANDARD"):
            evaluate_pregame_confidence(**self._triggering(action_authority=True))

    def test_validator_rejects_tampered_dose(self):
        record = evaluate_pregame_confidence(**self._triggering())
        tampered = dict(record)
        tampered["confidence_support_dose_cap"] = 0.9
        with self.assertRaisesRegex(ValueError, "CONFIDENCE_RECORD_MISMATCH"):
            validate_confidence_record(tampered)


if __name__ == "__main__":
    unittest.main()
