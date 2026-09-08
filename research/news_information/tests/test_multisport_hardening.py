from __future__ import annotations

import unittest

from research.news_information.contracts import RawSourceRecord, digest
from research.news_information.full_slate import build_full_slate_diagnostics
from research.news_information.multisport_benchmark import score_multisport_extraction
from research.news_information.pipeline import ResearchInformationPipeline
from research.news_information.shadow_features import export_shadow_vector


class MultiSportHardeningTests(unittest.TestCase):
    def source(self):
        return RawSourceRecord.from_bytes(
            raw=b"official fixture bytes",
            source_id="fixture.nfl.official",
            source_tier=1,
            source_type="LEAGUE_OFFICIAL",
            published_at_utc="2026-09-08T14:50:00Z",
            retrieved_at_utc="2026-09-08T15:00:00Z",
            forecast_cutoff_utc="2026-09-08T16:00:00Z",
            game_start_utc="2026-09-08T23:00:00Z",
        )

    def test_pipeline_records_league_specific_destructive_gate(self):
        outputs = [
            {"status": "PASS", "candidate_id": "gliner25_base", "payload": [{"event_type": "QB_OUT", "subject_id": "P1"}]},
            {"status": "PASS", "candidate_id": "sports_injury_ner", "payload": [{"event_type": "QB_OUT", "subject_id": "P1"}]},
        ]
        event = ResearchInformationPipeline().build_event(
            league="NFL",
            event_id="G1",
            source=self.source(),
            component_outputs=outputs,
            claim_seed={
                "subject_type": "PLAYER",
                "subject_id": "P1",
                "team_id": "T1",
                "event_type": "QB_OUT",
                "status": "OUT",
                "restriction_value": None,
                "effective_game_id": "G1",
                "certainty": "CONFIRMED",
            },
            resolution={
                "player_resolution_confidence": 1.0,
                "team_resolution_confidence": 1.0,
                "game_resolution_confidence": 1.0,
            },
            nli_label="ENTAILMENT",
        )
        gate = event["extraction"]["research_gate"]
        self.assertEqual(gate["league"], "NFL")
        self.assertTrue(gate["destructive_claim"])
        self.assertIn("DESTRUCTIVE_SOURCE_UNVERIFIED", gate["reasons"])
        self.assertFalse(event["usage_policy"]["research_feature_eligible"])
        self.assertFalse(event["usage_policy"]["forecast_adjustment_eligible"])

    def test_neutral_shadow_vector_does_not_drop_nfl_extension(self):
        core = {
            "schema_version": "sports_information_state_snapshot.v1",
            "feature_contract_version": "sports_information_state.v0_1.research",
            "event_id": "G1",
            "league": "NFL",
            "cutoff_utc": "2026-09-08T16:00:00Z",
            "information_event_ids": [],
            "event_type_counts": {"QB_OUT": 1, "PRACTICE_PARTICIPATION": 2},
            "conflicting_information_event_count": 0,
            "research_only": True,
            "forecast_adjustment_enabled": False,
            "market_input": False,
            "action_authority": "OFF",
        }
        snapshot = {**core, "snapshot_sha256": digest(core)}
        vector = export_shadow_vector(snapshot)
        self.assertEqual(vector["features"]["news_count__qb_out"], 1)
        self.assertEqual(vector["features"]["news_count__practice_participation"], 2)
        self.assertTrue(vector["league_transform_required_for_impact"])
        self.assertNotIn("probability_delta", vector)

    def test_neutral_shadow_vector_rejects_cross_league_event(self):
        core = {
            "schema_version": "sports_information_state_snapshot.v1",
            "feature_contract_version": "sports_information_state.v0_1.research",
            "event_id": "G1",
            "league": "NFL",
            "cutoff_utc": "2026-09-08T16:00:00Z",
            "information_event_ids": [],
            "event_type_counts": {"STARTER_PITCH_LIMIT": 1},
            "conflicting_information_event_count": 0,
            "research_only": True,
            "forecast_adjustment_enabled": False,
            "market_input": False,
            "action_authority": "OFF",
        }
        snapshot = {**core, "snapshot_sha256": digest(core)}
        with self.assertRaisesRegex(ValueError, "unregistered"):
            export_shadow_vector(snapshot)

    def test_full_slate_does_not_promote_noneligible_or_postcutoff_event_to_news_state(self):
        rejected = {
            "event_id": "G1",
            "forecast_timing": {"known_before_cutoff": False},
            "claim": {"event_type": "QB_OUT"},
            "resolution": {"cross_model_state": "CONSENSUS"},
            "usage_policy": {
                "research_feature_eligible": False,
                "forecast_adjustment_eligible": False,
                "market_input": False,
            },
        }
        rows = build_full_slate_diagnostics(
            games=[{"event_id": "G1", "league": "NFL", "forecast_status": "SHADOW_ONLY"}],
            source_captures=[],
            information_events=[rejected],
        )
        self.assertEqual(rows[0]["news_state"], "NO_STRUCTURED_EVENT")
        self.assertEqual(rows[0]["information_event_count"], 1)
        self.assertEqual(rows[0]["research_eligible_information_event_count"], 0)
        self.assertEqual(rows[0]["rejected_or_noneligible_information_event_count"], 1)

    def test_multisport_benchmark_reports_leakage_assignment_and_severity(self):
        gold = [
            {"league": "NFL", "example_id": "1", "event_type": "QB_STATUS", "subject_id": "Q1", "event_id": "N1", "source_tier": 1},
            {"league": "NFL", "example_id": "2", "event_type": "PLAYER_ACTIVE", "subject_id": "P2", "event_id": "N2", "source_tier": 1},
        ]
        pred = [
            {"league": "NFL", "example_id": "1", "event_type": "QB_STATUS", "subject_id": "Q1", "event_id": "WRONG", "source_tier": 1},
            {"league": "NFL", "example_id": "2", "event_type": "PLAYER_ACTIVE", "subject_id": "WRONG", "event_id": "N2", "source_tier": 1},
            {"league": "NFL", "example_id": "3", "event_type": "QB_OUT", "subject_id": "Q3", "event_id": "N3", "source_tier": 2,
             "known_before_cutoff": False, "used_as_prediction": True},
        ]
        report = score_multisport_extraction(gold, pred)
        nfl = report["by_league"]["NFL"]
        self.assertEqual(nfl["destructive_false_positive_count"], 1)
        self.assertEqual(nfl["post_cutoff_leakage_count"], 1)
        self.assertEqual(nfl["wrong_event_assignment_count"], 1)
        self.assertEqual(nfl["wrong_subject_assignment_count"], 1)
        self.assertIn("DESTRUCTIVE", nfl["by_claim_severity"])
        self.assertIn("1", nfl["by_source_tier"])
        self.assertIn("2", nfl["by_source_tier"])


if __name__ == "__main__":
    unittest.main()
