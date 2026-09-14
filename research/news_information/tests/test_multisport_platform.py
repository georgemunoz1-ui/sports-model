from __future__ import annotations

import json
import unittest

from research.news_information.contracts import RawSourceRecord, validate_information_event
from research.news_information.full_slate import build_full_slate_diagnostics
from research.news_information.identity_registry import CanonicalSportsEntityRegistry
from research.news_information.league_transforms import build_league_information_state
from research.news_information.multisport_benchmark import score_multisport_extraction
from research.news_information.source_adapters import (
    UNSTRUCTURED_REPORT,
    normalize_source_capture,
    source_adapter,
    source_profile,
)
from research.news_information.taxonomies import (
    allowed_event_types,
    taxonomy_for_league,
    validate_event_type_for_league,
)


class MultiSportPlatformTests(unittest.TestCase):
    def raw(self, *, tier=1, source_type="LEAGUE_OFFICIAL"):
        return RawSourceRecord.from_bytes(
            raw=b"fixture source bytes",
            source_id=f"fixture.{tier}.{source_type.lower()}",
            source_tier=tier,
            source_type=source_type,
            published_at_utc="2026-09-08T14:50:00Z",
            retrieved_at_utc="2026-09-08T15:00:00Z",
            forecast_cutoff_utc="2026-09-08T16:00:00Z",
            game_start_utc="2026-09-08T23:00:00Z",
        )

    def event(self, league, event_type, *, status="CONFIRMED", restriction=None, event_id="G1"):
        s = self.raw()
        return {
            "schema_version": "sports_information_event.v1",
            "information_event_id": None,
            "event_id": event_id,
            "league": league,
            "source": {
                "source_id": s.source_id,
                "source_tier": s.source_tier,
                "source_type": s.source_type,
                "source_url": None,
                "post_id": None,
                "published_at_utc": s.published_at_utc,
                "retrieved_at_utc": s.retrieved_at_utc,
                "raw_bytes_sha256": s.raw_bytes_sha256,
            },
            "forecast_timing": {
                "forecast_cutoff_utc": s.forecast_cutoff_utc,
                "game_start_utc": s.game_start_utc,
                "known_before_cutoff": True,
                "pit_status": "PASS",
            },
            "claim": {
                "subject_type": "PLAYER",
                "subject_id": "P1",
                "team_id": "T1",
                "event_type": event_type,
                "status": status,
                "restriction_value": restriction,
                "effective_game_id": event_id,
                "certainty": "CONFIRMED",
            },
            "extraction": {"fixture": True},
            "resolution": {
                "player_resolution_confidence": 1.0,
                "team_resolution_confidence": 1.0,
                "game_resolution_confidence": 1.0,
                "source_verification_state": "FIXTURE",
                "cross_model_state": "CONSENSUS",
            },
            "usage_policy": {
                "research_feature_eligible": True,
                "forecast_adjustment_eligible": False,
                "market_input": False,
                "action_authority": "OFF",
            },
        }

    def test_taxonomy_is_league_specific(self):
        self.assertIn("STARTER_PITCH_LIMIT", allowed_event_types("MLB"))
        self.assertIn("QB_OUT", allowed_event_types("NFL"))
        self.assertIn("QB_OUT", allowed_event_types("CFB"))
        self.assertIn("MINUTES_RESTRICTION", allowed_event_types("NBA"))
        self.assertIn("GOALIE_CONFIRMED", allowed_event_types("NHL"))
        self.assertIn("STARTING_XI_CONFIRMED", allowed_event_types("MLS"))
        with self.assertRaises(ValueError):
            validate_event_type_for_league("NFL", "STARTER_PITCH_LIMIT")
        with self.assertRaises(ValueError):
            validate_event_type_for_league("MLB", "QB_OUT")

    def test_information_event_rejects_wrong_league_extension(self):
        with self.assertRaisesRegex(ValueError, "not registered"):
            validate_information_event(self.event("NFL", "STARTER_PITCH_LIMIT"))

    def test_taxonomy_versions_are_explicit(self):
        self.assertEqual(taxonomy_for_league("MLB")["extension_taxonomy_version"], "mlb_event_taxonomy.v1")
        self.assertEqual(taxonomy_for_league("NFL")["extension_taxonomy_version"], "football_event_taxonomy.v1")
        self.assertEqual(taxonomy_for_league("WNBA")["extension_taxonomy_version"], "basketball_event_taxonomy.v1")

    def test_time_bounded_registry_tracks_trade_state(self):
        registry = CanonicalSportsEntityRegistry({
            "schema_version": "sports_entity_registry.v1",
            "generated_at_utc": "2026-09-08T00:00:00Z",
            "teams": [
                {"canonical_team_id": "SEA", "league": "NBA", "official_provider_id": "1",
                 "name": "Seattle", "aliases": [], "valid_from_utc": None, "valid_to_utc": None},
                {"canonical_team_id": "LAL", "league": "NBA", "official_provider_id": "2",
                 "name": "Los Angeles", "aliases": ["LA"], "valid_from_utc": None, "valid_to_utc": None},
                {"canonical_team_id": "BOS", "league": "NBA", "official_provider_id": "3",
                 "name": "Boston", "aliases": [], "valid_from_utc": None, "valid_to_utc": None},
            ],
            "players": [{
                "canonical_player_id": "P1", "league": "NBA", "official_provider_id": "9",
                "name": "Alex Guard",
                "aliases": [{"value": "A. Guard", "valid_from_utc": "2026-01-01T00:00:00Z", "valid_to_utc": None}],
                "team_assignments": [
                    {"team_id": "SEA", "valid_from_utc": "2026-01-01T00:00:00Z", "valid_to_utc": "2026-07-01T00:00:00Z"},
                    {"team_id": "LAL", "valid_from_utc": "2026-07-01T00:00:00Z", "valid_to_utc": None},
                ],
                "valid_from_utc": "2026-01-01T00:00:00Z", "valid_to_utc": None,
            }],
            "events": [{
                "canonical_event_id": "G1", "league": "NBA", "official_provider_event_id": "OFF-G1",
                "home_team_id": "LAL", "away_team_id": "BOS", "start_time_utc": "2026-09-08T23:00:00Z",
            }],
        })
        self.assertEqual(registry.resolve_player("A. Guard", league="NBA", at_utc="2026-06-01T00:00:00Z", team_id="SEA").entity_id, "P1")
        self.assertEqual(registry.resolve_player("A. Guard", league="NBA", at_utc="2026-08-01T00:00:00Z", team_id="SEA").status, "UNRESOLVED")
        self.assertEqual(registry.resolve_player("A. Guard", league="NBA", at_utc="2026-08-01T00:00:00Z", team_id="LAL").entity_id, "P1")
        self.assertEqual(registry.resolve_event("OFF-G1", league="NBA").entity_id, "G1")
        self.assertEqual(registry.validate_event_assignment(
            canonical_event_id="G1", league="NBA", at_utc="2026-08-01T00:00:00Z", player_id="P1").status, "RESOLVED")

    def test_source_adapters_keep_tier_and_market_boundaries(self):
        official = source_adapter("NFL").capture(
            event_id="G1", anchor_kind="OFFICIAL_INJURY_REPORT", raw_source=self.raw())
        self.assertEqual(official["usage_disposition"], "TIER_1_OFFICIAL_CANDIDATE")
        self.assertFalse(official["forecast_adjustment_eligible"])
        beat = normalize_source_capture(
            league="NFL", event_id="G1", anchor_kind=UNSTRUCTURED_REPORT,
            raw_source=self.raw(tier=2, source_type="BEAT_REPORTER"))
        self.assertEqual(beat["usage_disposition"], "RESEARCH_REQUIRES_CORROBORATION")
        market = normalize_source_capture(
            league="NFL", event_id="G1", anchor_kind=UNSTRUCTURED_REPORT,
            raw_source=self.raw(tier=3, source_type="NEWS_OUTLET"), market_facing=True)
        self.assertEqual(market["usage_disposition"], "EXCLUDED_MARKET_FACING_SOURCE")
        self.assertFalse(market["market_input"])

    def test_all_seven_leagues_have_distinct_profiles(self):
        for league in ("MLB", "NFL", "NBA", "WNBA", "NHL", "CFB", "MLS"):
            profile = source_profile(league)
            self.assertTrue(profile.required_official_anchors)
            self.assertTrue(profile.high_value_states)
            self.assertTrue(profile.first_research_target)

    def test_league_transforms_emit_state_not_probability_adjustment(self):
        fixtures = {
            "MLB": self.event("MLB", "STARTER_PITCH_LIMIT", status="LIMITED", restriction=75),
            "NFL": self.event("NFL", "QB_OUT", status="OUT"),
            "CFB": self.event("CFB", "NEUTRAL_SITE_STATUS", status="NEUTRAL"),
            "NBA": self.event("NBA", "MINUTES_RESTRICTION", status="LIMITED", restriction=24),
            "WNBA": self.event("WNBA", "MINUTES_RESTRICTION", status="LIMITED", restriction=22),
            "NHL": self.event("NHL", "GOALIE_CONFIRMED", status="CONFIRMED"),
            "MLS": self.event("MLS", "STARTING_XI_CONFIRMED", status="CONFIRMED"),
        }
        versions = set()
        for league, event in fixtures.items():
            state = build_league_information_state(
                league=league, event_id="G1", cutoff_utc="2026-09-08T16:00:00Z", events=[event])
            versions.add(state["impact_transform_version"])
            serialized = json.dumps(state)
            self.assertFalse(state["forecast_adjustment_eligible"])
            self.assertEqual(state["impact_transform_status"], "UNVALIDATED_SHADOW_STATE_ONLY")
            self.assertNotIn("probability_delta", serialized)
            self.assertNotIn("expected_run_delta", serialized)
            self.assertNotIn("expected_goal_delta", serialized)
        self.assertEqual(len(versions), 7)

    def test_full_slate_retains_games_and_exposes_coverage(self):
        mlb_caps = [
            source_adapter("MLB").capture(event_id="M1", anchor_kind=anchor, raw_source=self.raw())
            for anchor in source_profile("MLB").required_official_anchors
        ]
        nfl_caps = [source_adapter("NFL").capture(event_id="N1", anchor_kind="SCHEDULE", raw_source=self.raw())]
        rows = build_full_slate_diagnostics(
            games=[
                {"event_id": "M1", "league": "MLB", "forecast_status": "SHADOW_ONLY"},
                {"event_id": "N1", "league": "NFL", "forecast_status": "SHADOW_ONLY"},
                {"event_id": "B1", "league": "NBA", "forecast_status": "SHADOW_ONLY"},
                {"event_id": "S1", "league": "MLS", "forecast_status": "SHADOW_ONLY", "event_identity_status": "MISMATCH"},
            ],
            source_captures=mlb_caps + nfl_caps,
            information_events=[],
        )
        self.assertEqual(len(rows), 4)
        by = {r["event_id"]: r for r in rows}
        self.assertEqual(by["M1"]["information_completeness"], "HIGH")
        self.assertEqual(by["N1"]["information_completeness"], "MEDIUM")
        self.assertEqual(by["B1"]["information_completeness"], "LOW")
        self.assertEqual(by["S1"]["information_completeness"], "INVALID")
        self.assertEqual(by["S1"]["forecast_status"], "BLOCKED")

    def test_multisport_benchmark_is_stratified_and_tracks_destructive_false_positive(self):
        gold = [
            {"league": "MLB", "example_id": "1", "event_type": "PLAYER_ACTIVE", "subject_id": "P1", "event_id": "M1"},
            {"league": "NFL", "example_id": "2", "event_type": "QB_STATUS", "subject_id": "Q1", "event_id": "N1"},
        ]
        pred = [
            {"league": "MLB", "example_id": "1", "event_type": "PLAYER_ACTIVE", "subject_id": "P1", "event_id": "M1"},
            {"league": "NFL", "example_id": "2", "event_type": "QB_STATUS", "subject_id": "Q1", "event_id": "N1"},
            {"league": "NFL", "example_id": "3", "event_type": "QB_OUT", "subject_id": "Q2", "event_id": "N2"},
        ]
        report = score_multisport_extraction(gold, pred)
        self.assertIn("MLB", report["by_league"])
        self.assertIn("NFL", report["by_league"])
        self.assertEqual(report["by_league"]["NFL"]["destructive_false_positive_count"], 1)
        self.assertFalse(report["global_only_metric_for_promotion"])
        self.assertTrue(report["promotion_requires_league_stratified_review"])


if __name__ == "__main__":
    unittest.main()
