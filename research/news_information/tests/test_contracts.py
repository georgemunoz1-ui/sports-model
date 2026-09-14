from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from research.news_information.archive import RawArchive
from research.news_information.contracts import RawSourceRecord, validate_information_event
from research.news_information.entity_resolution import OfficialEntityIndex
from research.news_information.feature_store import ResearchFeatureStore
from research.news_information.model_registry import candidates, load_lock
from research.news_information.rules import extract_rule_claims


class NewsInformationContractTests(unittest.TestCase):
    def source(self, *, retrieved="2026-09-08T15:00:00Z"):
        return RawSourceRecord.from_bytes(
            raw=b"starter will be limited to 75 pitches", source_id="fixture.team.official",
            source_tier=1, source_type="TEAM_OFFICIAL", published_at_utc="2026-09-08T14:50:00Z",
            retrieved_at_utc=retrieved, forecast_cutoff_utc="2026-09-08T16:00:00Z",
            game_start_utc="2026-09-08T23:00:00Z")

    def event(self):
        s=self.source()
        return {
            "schema_version":"sports_information_event.v1","information_event_id":None,"event_id":"GAME1","league":"MLB",
            "source":{"source_id":s.source_id,"source_tier":1,"source_type":s.source_type,"source_url":None,"post_id":None,
                      "published_at_utc":s.published_at_utc,"retrieved_at_utc":s.retrieved_at_utc,"raw_bytes_sha256":s.raw_bytes_sha256},
            "forecast_timing":{"forecast_cutoff_utc":s.forecast_cutoff_utc,"game_start_utc":s.game_start_utc,
                               "known_before_cutoff":True,"pit_status":"PASS"},
            "claim":{"subject_type":"PLAYER","subject_id":"P1","team_id":"SEA","event_type":"STARTER_PITCH_LIMIT",
                     "status":"LIMITED","restriction_value":75,"effective_game_id":"GAME1","certainty":"EXPECTED"},
            "extraction":{"fixture":True},
            "resolution":{"player_resolution_confidence":1.0,"team_resolution_confidence":1.0,"game_resolution_confidence":1.0,
                          "source_verification_state":"FIXTURE","cross_model_state":"CONSENSUS"},
            "usage_policy":{"research_feature_eligible":True,"forecast_adjustment_eligible":False,"market_input":False,"action_authority":"OFF"},
        }

    def test_all_nine_candidates_are_pinned_research_only_and_disabled(self):
        reg=candidates(); self.assertEqual(len(reg),9)
        for c in reg.values():
            self.assertEqual(len(c.revision),40); self.assertTrue(c.research_only); self.assertFalse(c.trusted)
            self.assertFalse(c.enabled_by_default); self.assertFalse(c.forecast_adjustment_eligible); self.assertTrue(c.download_enabled)

    def test_unresolved_upstream_licenses_are_not_falsely_verified(self):
        lock=load_lock(); by={x["id"]:x for x in lock["candidates"]}
        self.assertEqual(by["sportsbert"]["license_status"],"REQUIRES_LICENSE_REVIEW")
        self.assertEqual(by["finbert_control"]["license_status"],"REQUIRES_LICENSE_REVIEW")

    def test_retrieval_after_cutoff_fails_pit(self):
        s=self.source(retrieved="2026-09-08T16:00:01Z"); self.assertFalse(s.known_before_cutoff); self.assertEqual(s.pit_status,"FAIL_POST_CUTOFF")

    def test_subjective_effort_language_produces_no_rule_claim(self):
        self.assertEqual(extract_rule_claims("The club looks checked out and has no heart tonight."),[])

    def test_pitch_limit_rule_is_structured(self):
        c=extract_rule_claims("Manager says the starter will be limited to 75 pitches tonight.")
        self.assertEqual(c[0]["event_type"],"STARTER_PITCH_LIMIT"); self.assertEqual(c[0]["restriction_value"],75)

    def test_usage_policy_cannot_enable_forecast_or_market(self):
        e=self.event(); e["usage_policy"]["forecast_adjustment_eligible"]=True
        with self.assertRaisesRegex(ValueError,"forecast-adjustment"): validate_information_event(e)
        e=self.event(); e["usage_policy"]["market_input"]=True
        with self.assertRaisesRegex(ValueError,"market_input"): validate_information_event(e)

    def test_official_entity_index_exact_and_ambiguous_fail_closed(self):
        idx=OfficialEntityIndex({"schema_version":"sports_official_entity_index.v1","players":[
            {"player_id":"P1","name":"Alex Smith","aliases":["A. Smith"],"team_id":"SEA","league":"MLB"},
            {"player_id":"P2","name":"Alex Smith","team_id":"BOS","league":"MLB"}],"teams":[],"events":[]})
        self.assertEqual(idx.resolve_player("A. Smith",league="MLB").entity_id,"P1")
        self.assertEqual(idx.resolve_player("Alex Smith",league="MLB").status,"AMBIGUOUS")
        self.assertEqual(idx.resolve_player("Alex Smith",league="MLB",team_id="SEA").entity_id,"P1")

    def test_archive_and_feature_store_are_content_addressed(self):
        s=self.source(); raw=b"starter will be limited to 75 pitches"
        with tempfile.TemporaryDirectory() as td:
            a=RawArchive(Path(td)/"raw"); one=a.put(raw,s); two=a.put(raw,s); self.assertEqual(one,two)
            store=ResearchFeatureStore(Path(td)/"features"); e=validate_information_event(self.event()); p1=store.put_event(e); p2=store.put_event(copy.deepcopy(e)); self.assertEqual(p1,p2)
            snap=store.snapshot(event_id="GAME1",cutoff_utc=s.forecast_cutoff_utc,events=[e]); self.assertFalse(snap["forecast_adjustment_enabled"]); self.assertFalse(snap["market_input"])

if __name__=="__main__": unittest.main()
