import unittest

from models.common.expanded_game_state_standard_v1 import (
    LEAGUE_DIMENSIONS,
    STANDARD_ID,
    build_game_state_envelope,
    policy_for_league,
)


class ExpandedGameStateStandardTests(unittest.TestCase):
    def _base(self, league="NFL", **kwargs):
        dims = {name: "UNKNOWN" for name in LEAGUE_DIMENSIONS[league]}
        dims["team_strength"] = "RESOLVED"
        params = dict(
            league=league,
            event_id=f"{league}_TEST_EVENT",
            cutoff_utc="2026-09-09T12:00:00Z",
            baseline_model_id=f"{league.lower()}.baseline.test",
            dimensions=dims,
        )
        params.update(kwargs)
        return params

    def test_all_required_leagues_have_policy(self):
        self.assertEqual(set(LEAGUE_DIMENSIONS), {"MLB", "NFL", "CFB", "NBA", "WNBA", "NHL", "MLS"})
        for league in LEAGUE_DIMENSIONS:
            policy = policy_for_league(league)
            self.assertTrue(policy.baseline_required)
            self.assertIn("team_strength", policy.dimensions)

    def test_unresolved_enrichment_keeps_baseline_forecast(self):
        envelope = build_game_state_envelope(**self._base())
        self.assertEqual(envelope["standard_id"], STANDARD_ID)
        self.assertTrue(envelope["baseline_forecast_required"])
        self.assertEqual(envelope["coverage_label"], "BASELINE_ONLY")
        self.assertFalse(envelope["information_enhancement_available"])

    def test_partial_enrichment_is_visible_not_omitted(self):
        params = self._base()
        params["dimensions"]["quarterback"] = "RESOLVED"
        params["dimensions"]["availability"] = "PARTIAL"
        envelope = build_game_state_envelope(**params)
        self.assertEqual(envelope["coverage_label"], "BASELINE_WITH_UNRESOLVED_INPUTS")
        self.assertTrue(envelope["information_enhancement_available"])

    def test_full_enrichment_is_shadow_label(self):
        params = self._base("MLS")
        params["dimensions"] = {name: "RESOLVED" for name in LEAGUE_DIMENSIONS["MLS"]}
        envelope = build_game_state_envelope(**params)
        self.assertEqual(envelope["coverage_label"], "FULL_INFORMATION_SHADOW")

    def test_source_conflict_remains_visible(self):
        envelope = build_game_state_envelope(**self._base(source_conflict=True))
        self.assertEqual(envelope["coverage_label"], "SOURCE_CONFLICT_BASELINE")

    def test_market_input_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "MARKET_INPUT_FORBIDDEN"):
            build_game_state_envelope(**self._base(market_input_used=True))

    def test_subjective_sentiment_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "SUBJECTIVE_SENTIMENT_PREDICTIVE_INPUT_FORBIDDEN"):
            build_game_state_envelope(**self._base(subjective_sentiment_used=True))

    def test_baseline_team_strength_must_exist(self):
        params = self._base()
        params["dimensions"]["team_strength"] = "UNKNOWN"
        with self.assertRaisesRegex(ValueError, "BASELINE_TEAM_STRENGTH_UNAVAILABLE"):
            build_game_state_envelope(**params)

    def test_nonzero_adjustment_requires_versioned_transform(self):
        with self.assertRaisesRegex(ValueError, "IMPACT_TRANSFORM_ID_REQUIRED"):
            build_game_state_envelope(**self._base(feature_contributions={"QB_OUT": -2.5}))

        envelope = build_game_state_envelope(**self._base(
            feature_contributions={"QB_OUT": -2.5},
            impact_transform={
                "id": "nfl.contextual.test",
                "version": "0.1.0",
                "status": "SHADOW_UNVALIDATED",
            },
        ))
        self.assertEqual(envelope["feature_contributions"]["QB_OUT"], -2.5)
        self.assertFalse(envelope["action_authority"])

    def test_unknown_dimension_fails_closed(self):
        params = self._base()
        params["dimensions"]["sportsbook_line"] = "RESOLVED"
        with self.assertRaisesRegex(ValueError, "UNKNOWN_GAME_STATE_DIMENSIONS"):
            build_game_state_envelope(**params)


if __name__ == "__main__":
    unittest.main()
