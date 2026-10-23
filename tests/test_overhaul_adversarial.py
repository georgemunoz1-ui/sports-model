"""Independent hostile-input checks for the 2026-10-23 research overhaul.

All signing keys and observations below are synthetic test material. Passing
these checks grants no predictive qualification or publication authority.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pipelines.cards.research_selection import (
    SELECTOR_SPEC_ID, ResearchSelectionError, seal_forecast, seal_quality_receipt,
    select_research, selector_config_id, target_id,
)
from research.validation_registry import (
    ArtifactStore, Ed25519Verifier, RegistryError, TrialLog, ValidationRegistry,
    canonical_bytes,
)
from models.current.freshness import (
    normalize_captured_schedule, operational_rest, state_freshness_receipt,
)
from research.selection_evaluation import (
    EvaluationError, evaluate_decisions, holm_adjust, paired_block_comparison, power_curve,
)
from scripts.nba_history_scope import BASE as NBA_BASE, current_season, verify_current_events
from scripts.evaluate_research_selections import build_evaluation


CONFIG = {"schema": "research-selector-config-v1", "objective": "unconditional_win",
          "threshold": .6, "require_quality_receipt": False}
FAMILY = {"league": "nfl", "product": "spread", "period": "full_game",
          "settlement_rules_id": "full-game-ot-push-refund-v1"}
DECISION = "2026-10-22T21:00:00Z"


def signed_fixture(root, *, protocol_changes=None, evidence_changes=None,
                   registration_time="2026-08-31T12:00:00Z",
                   review_time="2026-10-20T12:00:00Z", reviewer="independent-test-reviewer",
                   same_signing_credential=False, dataset_scope="CONFIRMATION"):
    """Construct signed TEST ONLY evidence independently of builder fixtures."""
    store = ArtifactStore(root)
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw,
                                          serialization.PublicFormat.Raw)
    author_key = key if same_signing_credential else Ed25519PrivateKey.generate()
    author_public = author_key.public_key().public_bytes(serialization.Encoding.Raw,
                                                        serialization.PublicFormat.Raw)
    trusted_keys = {"synthetic-author": author_public, reviewer: public}
    verifier = Ed25519Verifier(trusted_keys)

    def receipt(artifact, purpose, when, signer=None):
        signer = reviewer if signer is None else signer
        signing_key = author_key if signer == "synthetic-author" and reviewer != signer else key
        payload = {"artifact_id": artifact, "purpose": purpose, "signer_id": signer,
                   "witnessed_at_utc": when}
        return store.put({"payload": payload,
                          "signature_b64": base64.b64encode(signing_key.sign(canonical_bytes(payload))).decode()})

    procedure_id = store.put({"schema": "synthetic-procedure", "version": 1})
    control_id = store.put({"schema": "synthetic-control", "version": 1})
    population_id = store.put({"schema": "synthetic-population", "league": "nfl"})
    config_id = store.put({"selector_spec_id": SELECTOR_SPEC_ID, "config": CONFIG})
    assert config_id == selector_config_id(CONFIG)
    protocol = {"candidate_id": procedure_id, "control_id": control_id,
                "population_id": population_id, "target": FAMILY,
                "selector_config_id": config_id, "objective": "unconditional_win",
                "primary_metric": "brier", "author_id": "synthetic-author",
                "development_end_utc": "2026-08-30T00:00:00Z",
                "evaluation_start_utc": "2026-09-01T00:00:00Z",
                "evaluation_end_utc": "2026-10-19T00:00:00Z", "valid_for_days": 30,
                "criteria": {"minimum_events": 2, "minimum_slates": 2,
                             "minimum_selected": 1, "minimum_total_coverage": .4,
                             "maximum_total_coverage": .6,
                             "maximum_primary_delta_ci_upper": 0,
                             "minimum_power": .8}}
    protocol.update(protocol_changes or {})
    protocol_id = store.put(protocol)
    evidence = {k: protocol[k] for k in ("candidate_id", "control_id", "population_id", "target",
                "selector_config_id", "objective", "primary_metric", "evaluation_start_utc", "evaluation_end_utc")}
    evidence.update({"protocol_id": protocol_id, "computed_at_utc": "2026-10-20T00:00:00Z",
                     "n_events": 2, "n_slates": 2, "n_selected": 1, "total_coverage": .5,
                     "primary_delta_ci_upper": -.01, "power_at_declared_effect": .85,
                     "paired_dataset_id": store.put({"schema": "synthetic-paired-reference", "fixture_only": True,
                                                       "evidence_scope": dataset_scope})})
    evidence.update(evidence_changes or {})
    evidence_id = store.put(evidence)
    registration_id = receipt(protocol_id, "preregistration", registration_time)
    authorship_id = receipt(protocol_id, "protocol_authorship", "2026-08-31T11:00:00Z", signer="synthetic-author")
    review_id = store.put({"protocol_id": protocol_id, "evidence_id": evidence_id,
                           "registration_receipt_id": registration_id, "authorship_receipt_id": authorship_id})
    review_receipt_id = receipt(review_id, "validation_review", review_time)
    record_id = store.put({"review_payload_id": review_id, "review_receipt_id": review_receipt_id})
    registry = ValidationRegistry(store, [record_id], verifier)
    payload = {"schema": "research-forecast-v1", "procedure_id": procedure_id,
               "input_snapshot_sha256": "b" * 64,
               "target": {**FAMILY, "event_id": "test-event-1", "side": "away", "line": 3.0,
                          "starts_at_utc": "2026-10-22T23:00:00Z"},
               "probabilities": {"win": .6, "loss": .3, "push": .1, "void": 0.0},
               "forecast_cutoff_utc": "2026-10-22T19:00:00Z",
               "forecast_created_at_utc": "2026-10-22T20:00:00Z"}
    return {"store": store, "registry": registry, "payload": payload,
            "forecast": seal_forecast(payload), "procedure_id": procedure_id,
            "config_id": config_id, "record_id": record_id, "review_receipt_id": review_receipt_id,
            "sign_test_receipt": receipt}


class AdversarialSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = signed_fixture(self.temp.name)

    def select(self, **kwargs):
        return select_research(self.fixture["forecast"], CONFIG, decision_at_utc=DECISION,
                               registry=self.fixture["registry"], **kwargs)

    def test_positive_path_remains_shadow_and_no_publication(self):
        result = self.select()
        self.assertEqual(result["decision_class"], "SHADOW_SELECTED")
        self.assertFalse(result["publication_allowed"])
        self.assertFalse(result["action_authority"])
        self.assertFalse(result["prospective_registration_verified"])
        self.assertEqual(result["wagering_status"], "OFF")

    def test_price_changes_missing_or_invalid_quote_cannot_change_selection(self):
        baseline = self.select()
        for odds in (1.01, 2.0, 99.0, True, float("nan"), float("inf"), 0):
            with self.subTest(odds=odds):
                result = self.select(price={"target_id": target_id(self.fixture["forecast"]["target"]),
                                            "decimal_odds": odds, "quoted_at_utc": DECISION})
                self.assertEqual(result["decision_id"], baseline["decision_id"])
                self.assertEqual(result["selection_probability"], .6)
        result = self.select(price={"target_id": "c" * 64, "decimal_odds": 2, "quoted_at_utc": DECISION})
        self.assertEqual(result["decision_id"], baseline["decision_id"])
        self.assertEqual(result["price_status"], "INVALID_PRICE")

    def test_push_aware_ev_uses_unconditional_mass_and_decisive_break_even(self):
        result = self.select(price={"target_id": target_id(self.fixture["forecast"]["target"]),
                                    "decimal_odds": 2, "quoted_at_utc": DECISION})
        self.assertAlmostEqual(result["estimated_value"], .3)
        self.assertAlmostEqual(result["decisive_probability"], 2 / 3)
        self.assertEqual(result["price_break_even"]["probability_basis"], "conditional_decisive")
        self.assertEqual(result["selection_probability"], .6)

    def test_forged_caller_qualification_is_rejected(self):
        with self.assertRaisesRegex(ResearchSelectionError, "VERIFIED_VALIDATION_REGISTRY_REQUIRED"):
            select_research(self.fixture["forecast"], CONFIG, decision_at_utc=DECISION,
                            registry={"eligible": True, "status": "ACTIVE"})

    def test_plain_names_without_trusted_signature_cannot_qualify(self):
        untrusted = ValidationRegistry(self.fixture["store"], [self.fixture["record_id"]])
        result = select_research(self.fixture["forecast"], CONFIG, decision_at_utc=DECISION, registry=untrusted)
        self.assertEqual(result["decision_class"], "BLOCKED")
        self.assertIsNone(result["selection_probability"])
        self.assertEqual(result["raw_probability"], .6)

    def test_mutated_line_or_probability_breaks_forecast_identity(self):
        for key, value in (("line", 2.5), ("side", "home"), ("period", "first_half")):
            changed = copy.deepcopy(self.fixture["forecast"])
            changed["target"][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ResearchSelectionError, "FORECAST_ID_MISMATCH"):
                select_research(changed, CONFIG, decision_at_utc=DECISION)

    def test_missing_line_rejected_while_missing_price_was_selectable(self):
        payload = copy.deepcopy(self.fixture["payload"])
        payload["target"]["line"] = None
        with self.assertRaisesRegex(ResearchSelectionError, "TARGET_LINE"):
            seal_forecast(payload)

    def test_nonfinite_boolean_or_out_of_range_probabilities_rejected(self):
        for value in (True, False, float("nan"), float("inf"), -float("inf"), -.1, 1.1):
            payload = copy.deepcopy(self.fixture["payload"])
            payload["probabilities"]["win"] = value
            with self.subTest(value=value), self.assertRaises(ResearchSelectionError):
                seal_forecast(payload)

    def test_incomplete_distribution_preserves_raw_probability_but_blocks(self):
        payload = copy.deepcopy(self.fixture["payload"])
        payload["probabilities"]["push"] = None
        result = select_research(seal_forecast(payload), CONFIG, decision_at_utc=DECISION,
                                 registry=self.fixture["registry"])
        self.assertEqual(result["raw_probability"], .6)
        self.assertIsNone(result["selection_probability"])
        self.assertIn("PROBABILITY_MASS_INCOMPLETE", result["blocking_reasons"])

    def test_live_or_future_forecast_blocked_without_erasing_raw(self):
        live = select_research(self.fixture["forecast"], CONFIG,
                               decision_at_utc="2026-10-22T23:00:00Z", registry=self.fixture["registry"])
        self.assertIn("PREGAME_DECISION_WINDOW_CLOSED", live["blocking_reasons"])
        future = select_research(self.fixture["forecast"], CONFIG,
                                 decision_at_utc="2026-10-22T19:30:00Z", registry=self.fixture["registry"])
        self.assertIn("FORECAST_FROM_FUTURE", future["blocking_reasons"])
        self.assertEqual(live["raw_probability"], future["raw_probability"])

    def test_quality_receipt_swapping_and_future_timestamp_rejected(self):
        for updates in ({"forecast_id": "c" * 64}, {"created_at_utc": "2026-10-23T00:00:00Z"}):
            payload = {"forecast_id": self.fixture["forecast"]["forecast_id"],
                       "input_snapshot_sha256": "b" * 64, "created_at_utc": DECISION,
                       "blocking_reasons": [], "review_notes": []}
            payload.update(updates)
            with self.subTest(updates=updates), self.assertRaises(ResearchSelectionError):
                self.select(quality_receipt=seal_quality_receipt(payload))

    def test_child_procedure_cannot_inherit_parent_approval(self):
        parent = self.fixture["procedure_id"]
        child = self.fixture["store"].put({"parent_procedure_id": parent, "version": 2})
        result = self.fixture["registry"].assess(child, FAMILY, DECISION, self.fixture["config_id"])
        self.assertFalse(result.eligible)
        self.assertIn("PROCEDURE_MISMATCH", result.reasons)

    def test_family_or_config_swap_and_mutable_latest_rejected(self):
        registry = self.fixture["registry"]
        for target, config in (({**FAMILY, "product": "total"}, self.fixture["config_id"]),
                               (FAMILY, "latest"), (FAMILY, "d" * 64)):
            with self.subTest(target=target, config=config):
                self.assertFalse(registry.assess(self.fixture["procedure_id"], target, DECISION, config).eligible)

    def test_selection_does_not_mutate_frozen_input(self):
        before = canonical_bytes(self.fixture["forecast"])
        self.select()
        self.assertEqual(before, canonical_bytes(self.fixture["forecast"]))


class AdversarialRegistryTests(unittest.TestCase):
    def test_two_names_for_one_signing_credential_do_not_establish_independence(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = signed_fixture(tmp, same_signing_credential=True)
            self.assertFalse(fixture["registry"].assess(fixture["procedure_id"], FAMILY, DECISION,
                                                        fixture["config_id"]).eligible)

    def test_discovery_and_shadow_evidence_cannot_qualify(self):
        for scope in ("DISCOVERY", "SHADOW"):
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as tmp:
                fixture = signed_fixture(tmp, dataset_scope=scope)
                self.assertFalse(fixture["registry"].assess(fixture["procedure_id"], FAMILY, DECISION,
                                                            fixture["config_id"]).eligible)

    def test_signed_revocation_demotion_and_malformed_revocation_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = signed_fixture(tmp)
            store, registry = fixture["store"], fixture["registry"]
            payload_id = store.put({"record_id": fixture["record_id"], "reason": "synthetic test drift"})
            receipt_id = fixture["sign_test_receipt"](payload_id, "validation_revocation", "2026-10-22T20:00:00Z")
            item_id = store.put({"revocation_payload_id": payload_id, "revocation_receipt_id": receipt_id})
            registry.revocation_ids = (item_id,)
            revoked = registry.assess(fixture["procedure_id"], FAMILY, DECISION, fixture["config_id"])
            self.assertFalse(revoked.eligible)
            self.assertIn("VALIDATION_REVOKED", revoked.reasons)
            registry.revocation_ids = (store.put({"revocation_payload_id": payload_id}),)
            self.assertFalse(registry.assess(fixture["procedure_id"], FAMILY, DECISION,
                                             fixture["config_id"]).eligible)

    def test_future_review_late_registration_and_self_review_fail(self):
        cases = ({"review_time": "2026-10-23T00:00:00Z"},
                 {"registration_time": "2026-09-02T00:00:00Z"},
                 {"reviewer": "synthetic-author"},
                 {"protocol_changes": {"development_end_utc": "2026-09-02T00:00:00Z"}})
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                fixture = signed_fixture(tmp, **case)
                self.assertFalse(fixture["registry"].assess(fixture["procedure_id"], FAMILY, DECISION,
                                                            fixture["config_id"]).eligible)

    def test_overflowing_expiry_is_ineligible_without_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = signed_fixture(tmp, protocol_changes={"valid_for_days": 1e300})
            self.assertFalse(fixture["registry"].assess(fixture["procedure_id"], FAMILY, DECISION,
                                                        fixture["config_id"]).eligible)

    def test_fabricated_counts_bool_coverage_and_power_are_rejected(self):
        for changes in ({"n_events": True}, {"n_selected": 3}, {"total_coverage": .99},
                        {"power_at_declared_effect": 1.2}, {"primary_delta_ci_upper": .1}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as tmp:
                fixture = signed_fixture(tmp, evidence_changes=changes)
                self.assertFalse(fixture["registry"].assess(fixture["procedure_id"], FAMILY, DECISION,
                                                            fixture["config_id"]).eligible)

    def test_signature_tamper_and_artifact_overwrite_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = signed_fixture(tmp)
            store = fixture["store"]
            receipt = store.read(fixture["review_receipt_id"])
            receipt["signature_b64"] = base64.b64encode(b"x" * 64).decode()
            record = store.read(fixture["record_id"])
            record["review_receipt_id"] = store.put(receipt)
            fixture["registry"].record_ids = (store.put(record),)
            self.assertFalse(fixture["registry"].assess(fixture["procedure_id"], FAMILY, DECISION,
                                                        fixture["config_id"]).eligible)
            original = {"untouched": True}
            artifact_id = store.put(original)
            path = Path(tmp) / (artifact_id + ".json")
            path.write_text('{"untouched":false}')
            with self.assertRaisesRegex(RegistryError, "HASH_MISMATCH"):
                store.put(original)
            self.assertEqual(path.read_text(), '{"untouched":false}')

    def test_concurrent_trials_no_lost_appends_and_duplicate_failure_is_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trials.jsonl"
            log = TrialLog(path)
            def append(i):
                return log.append({"kind": "INSPECTED", "trial_id": str(i), "family_id": "test",
                                   "configuration_id": hashlib.sha256(str(i).encode()).hexdigest()})
            with ThreadPoolExecutor(max_workers=6) as executor:
                list(executor.map(append, range(24)))
            self.assertEqual(log.inspected_count("test"), 24)
            before = path.read_bytes()
            with self.assertRaisesRegex(RegistryError, "DUPLICATE_INSPECTED_TRIAL"):
                append(0)
            self.assertEqual(path.read_bytes(), before)

    def test_hash_chain_truncation_requires_and_obeys_external_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trials.jsonl"
            log = TrialLog(path)
            for i in range(2):
                tip = log.append({"kind": "INSPECTED", "trial_id": str(i), "family_id": "test",
                                  "configuration_id": str(i) * 64})["record_id"]
            path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])
            with self.assertRaisesRegex(RegistryError, "ANCHOR_MISMATCH"):
                log.read(expected_tip=tip)
            # Honest limitation: an unanchored valid prefix is indistinguishable.
            self.assertEqual(len(log.read()), 1)


class AdversarialFreshnessTests(unittest.TestCase):
    @staticmethod
    def fixture():
        event = {"event_id": "NHL:target", "home_id": "H", "away_id": "A",
                 "start_time_utc": "2026-10-22T23:00:00Z"}
        record = {"event_id": "NHL:previous", "home_id": "H", "away_id": "A",
                  "start_time_utc": "2026-10-21T23:00:00Z", "status": "final",
                  "completed_at_utc": "2026-10-22T02:00:00Z",
                  "observed_at_utc": "2026-10-22T20:00:00Z", "source_sha256": "a" * 64}
        coverage = [{"team_id": team, "from_utc": "2026-10-21T00:00:00Z",
                     "through_utc": "2026-10-22T20:00:00Z", "observed_at_utc": "2026-10-22T20:00:00Z",
                     "source_sha256": "a" * 64, "complete": True,
                     "population": "ALL_PLAYED_GAMES"} for team in ("H", "A")]
        return event, record, coverage

    def test_positive_rest_and_postcutoff_or_current_event_exclusion(self):
        event, record, coverage = self.fixture()
        late = {**record, "event_id": "NHL:late-capture", "start_time_utc": "2026-10-22T10:00:00Z",
                "completed_at_utc": "2026-10-22T13:00:00Z", "observed_at_utc": "2026-10-23T00:00:00Z"}
        current = {**record, "event_id": event["event_id"]}
        receipt = operational_rest(event, [record, late, current], cutoff_utc="2026-10-22T20:00:00Z", coverage=coverage)
        for side in ("home", "away"):
            self.assertEqual(receipt["per_side"][side]["status"], "KNOWN")
            self.assertEqual(receipt["per_side"][side]["candidate_feature_value"], 1.0)
        self.assertEqual(receipt["exclusions"]["NOT_AVAILABLE_PREFORECAST"], 1)
        self.assertEqual(receipt["exclusions"]["CURRENT_EVENT_EXCLUDED"], 1)

    def test_real_upcoming_schedule_rows_do_not_poison_valid_prior_rest(self):
        event, record, coverage = self.fixture()
        current = {"event_id": event["event_id"], "home_id": "H", "away_id": "A",
                   "start_time_utc": event["start_time_utc"], "status": "nonfinal",
                   "observed_at_utc": "2026-10-22T20:00:00Z", "source_sha256": "a" * 64}
        future = {**current, "event_id": "NHL:tomorrow", "start_time_utc": "2026-10-23T23:00:00Z"}
        receipt = operational_rest(event, [record, current, future], cutoff_utc="2026-10-22T20:00:00Z", coverage=coverage)
        for side in ("home", "away"):
            self.assertEqual(receipt["per_side"][side]["status"], "KNOWN")
            self.assertEqual(receipt["per_side"][side]["candidate_feature_value"], 1.0)

    def test_missing_or_future_coverage_never_manufactures_rest(self):
        event, record, coverage = self.fixture()
        for receipts in ([], [{**r, "observed_at_utc": "2026-10-23T00:00:00Z"} for r in coverage],
                         [{**r, "population": "REGULAR_SEASON_ONLY"} for r in coverage]):
            with self.subTest(receipts=receipts):
                result = operational_rest(event, [record], cutoff_utc="2026-10-22T20:00:00Z", coverage=receipts)
                self.assertIsNone(result["per_side"]["away"]["candidate_feature_value"])
                self.assertIn("AS_OF_HISTORY_COVERAGE_UNPROVEN", result["per_side"]["away"]["blocking_reasons"])

    def test_nonfinal_and_conflicting_event_identity_fail_closed(self):
        event, record, coverage = self.fixture()
        nonfinal = operational_rest(event, [{**record, "status": "canceled"}],
                                    cutoff_utc="2026-10-22T20:00:00Z", coverage=coverage)
        self.assertIsNone(nonfinal["per_side"]["home"]["candidate_feature_value"])
        conflict = {**record, "start_time_utc": "2026-10-21T22:00:00Z"}
        receipt = operational_rest(event, [record, conflict], cutoff_utc="2026-10-22T20:00:00Z", coverage=coverage)
        self.assertIn("HISTORY_INTEGRITY_UNPROVEN", receipt["per_side"]["home"]["blocking_reasons"])

    def test_fresh_capture_or_current_season_label_cannot_mask_old_consumed_state(self):
        event, _, _ = self.fixture()
        package = {"season": 2026, "captured_at_utc": "2026-10-22T19:59:00Z",
                   "training_cutoff_utc": "2026-04-13T00:30:00Z",
                   "team_state": {team: {"last": "2026-04-13T00:30:00Z"} for team in ("H", "A")}}
        receipt = state_freshness_receipt(package, event, {"home_rest": 14.0, "away_rest": 14.0},
                                          cutoff_utc="2026-10-22T20:00:00Z", max_state_age_hours=48)
        for side in ("home", "away"):
            self.assertIn("CONSUMED_STATE_OLDER_THAN_POLICY", receipt["per_side"][side]["blocking_reasons"])
            self.assertGreater(receipt["per_side"][side]["state_age_at_cutoff_hours"], 4000)

    def test_boolean_nonfinite_feature_values_rejected(self):
        event, _, _ = self.fixture()
        for number in (True, float("nan"), float("inf")):
            with self.subTest(number=number), self.assertRaises(ValueError):
                state_freshness_receipt({}, event, {"home_rest": number, "away_rest": 14},
                                        cutoff_utc="2026-10-22T20:00:00Z")

    def test_raw_source_binding_rejects_changed_bytes_and_discards_scores(self):
        payload = {"events": [{"id": "previous", "date": "2026-10-21T23:00:00Z",
                              "competitions": [{"competitors": [
                                  {"homeAway": "home", "team": {"id": "H"}, "score": "99"},
                                  {"homeAway": "away", "team": {"id": "A"}, "score": "0"}],
                                  "status": {"type": {"completed": True, "state": "post", "name": "STATUS_FINAL"}}}]}]}
        raw = json.dumps(payload).encode()
        sha = hashlib.sha256(raw).hexdigest()
        rows = normalize_captured_schedule(raw, league="nhl", captured_at_utc=DECISION, source_sha256=sha)
        self.assertEqual(rows[0]["status"], "final")
        self.assertNotIn("score", json.dumps(rows))
        with self.assertRaisesRegex(ValueError, "DIGEST_MISMATCH"):
            normalize_captured_schedule(raw + b" ", league="nhl", captured_at_utc=DECISION, source_sha256=sha)

    def test_forfeit_is_not_played_rest_history(self):
        payload = {"events": [{"id": "forfeit", "date": "2026-10-21T23:00:00Z",
                              "competitions": [{"competitors": [
                                  {"homeAway": "home", "team": {"id": "H"}},
                                  {"homeAway": "away", "team": {"id": "A"}}],
                                  "status": {"type": {"completed": True, "state": "post", "name": "STATUS_FINAL_FORFEIT"}}}]}]}
        raw = json.dumps(payload).encode()
        rows = normalize_captured_schedule(raw, league="nhl", captured_at_utc=DECISION,
                                            source_sha256=hashlib.sha256(raw).hexdigest())
        self.assertEqual(rows[0]["status"], "nonfinal")

    def test_old_team_state_cannot_mask_future_model_training_cutoff(self):
        event, _, _ = self.fixture()
        package = {"training_cutoff_utc": "2026-10-23T00:00:00Z",
                   "team_state": {team: {"last": "2026-10-21T23:00:00Z"} for team in ("H", "A")}}
        receipt = state_freshness_receipt(package, event, {"home_rest": 1.0, "away_rest": 1.0},
                                          cutoff_utc="2026-10-22T20:00:00Z")
        self.assertIn("FIT_NOT_AVAILABLE_PREFORECAST", receipt["blocking_reasons"])


class AdversarialEvaluationTests(unittest.TestCase):
    @staticmethod
    def dataset():
        # Four resolved selections, one live selection, one blocked loss and
        # one eligible nonselection: abstaining does not turn the loss into a win.
        outcomes = ["WIN", "LOSS", "PUSH", "VOID", "LIVE", "LOSS", "WIN"]
        classes = ["SHADOW_SELECTED"] * 5 + ["BLOCKED", "ELIGIBLE_NOT_SELECTED"]
        rows = []
        for i, (outcome, decision) in enumerate(zip(outcomes, classes)):
            rows.append({"event_id": f"event-{i}", "target_id": f"target-{i}", "slate_id": f"slate-{i // 2}",
                         "procedure_id": "a" * 64, "selector_config_id": "b" * 64,
                         "control_procedure_id": "c" * 64, "target_family_id": "d" * 64,
                         "decision_class": decision, "outcome": outcome, "raw_probability": .6,
                         "control_probability": .5, "control_target_id": f"target-{i}",
                         "control_predicted_outcome": "WIN"})
        population = [{k: r[k] for k in ("event_id", "target_id", "slate_id")} for r in rows]
        return rows, population

    def evaluate(self, rows, population):
        return evaluate_decisions(rows, population=population, evidence_scope="DISCOVERY", bootstrap_samples=50)

    def test_full_denominators_no_abstention_wins_and_push_void_nonwin(self):
        rows, population = self.dataset()
        result = self.evaluate(rows, population)
        self.assertEqual((result["n_events"], result["n_eligible"], result["n_selected"]), (7, 6, 5))
        self.assertAlmostEqual(result["total_coverage"], 5 / 7)
        self.assertAlmostEqual(result["eligible_coverage"], 5 / 6)
        self.assertEqual(result["selected_settlement"]["wins"], 1)
        self.assertEqual(result["selected_settlement"]["n_settled"], 4)
        self.assertAlmostEqual(result["selected_settlement"]["unconditional_win_accuracy"], .25)
        self.assertAlmostEqual(result["selected_settlement"]["decisive_only_accuracy_diagnostic"], .5)
        self.assertEqual(result["selected_forecast_scores"]["n"], 4)
        self.assertAlmostEqual(result["selected_forecast_scores"]["brier"], (.16 + .36 * 3) / 4)
        self.assertEqual(result["selected_unsettled"], 1)
        self.assertFalse(result["qualification_granted"])

    def test_all_blocked_or_no_selections_means_undefined_selected_accuracy(self):
        for decision in ("BLOCKED", "ELIGIBLE_NOT_SELECTED"):
            rows, population = self.dataset()
            for row in rows:
                row["decision_class"] = decision
            result = self.evaluate(rows, population)
            with self.subTest(decision=decision):
                self.assertEqual(result["n_events"], 7)
                self.assertEqual(result["n_selected"], 0)
                self.assertEqual(result["total_coverage"], 0)
                self.assertIsNone(result["selected_settlement"]["unconditional_win_accuracy"])

    def test_omitted_blocked_opportunity_is_rejected(self):
        rows, population = self.dataset()
        with self.assertRaisesRegex(EvaluationError, "missing population decisions"):
            self.evaluate([r for r in rows if r["decision_class"] != "BLOCKED"], population)

    def test_duplicate_quotes_cannot_inflate_event_count(self):
        rows, population = self.dataset()
        with self.assertRaisesRegex(EvaluationError, "duplicate decision event"):
            self.evaluate(rows + [dict(rows[0])], population)
        with self.assertRaisesRegex(EvaluationError, "duplicate population event"):
            self.evaluate(rows, population + [dict(population[0])])

    def test_mixed_procedure_configuration_family_or_control_rejected(self):
        for key in ("procedure_id", "selector_config_id", "target_family_id", "control_procedure_id"):
            rows, population = self.dataset()
            rows[-1][key] = "e" * 64
            with self.subTest(key=key), self.assertRaisesRegex(EvaluationError, "mixed"):
                self.evaluate(rows, population)

    def test_wrong_target_control_or_population_pairing_rejected(self):
        for key in ("control_target_id", "target_id", "slate_id"):
            rows, population = self.dataset()
            rows[0][key] = "wrong"
            with self.subTest(key=key), self.assertRaises(EvaluationError):
                self.evaluate(rows, population)

    def test_missing_control_exposes_unpaired_count_without_fabricated_comparison(self):
        rows, population = self.dataset()
        rows[0]["control_probability"] = None
        result = self.evaluate(rows, population)
        comparison = result["selected_same_event_control"]
        self.assertEqual(comparison["n"], 3)
        self.assertEqual(comparison["unpaired_settled_count"], 1)
        self.assertEqual(comparison["candidate_scores"]["n"], comparison["control_scores"]["n"])

    def test_risk_coverage_curve_does_not_split_probability_ties_or_modify_decisions(self):
        rows, population = self.dataset()
        before = copy.deepcopy(rows)
        result = self.evaluate(rows, population)
        self.assertEqual(rows, before)
        curve = result["risk_coverage_diagnostic_only"]
        self.assertEqual(len(curve), 1)
        self.assertEqual(curve[0]["n_selected"], 6)
        self.assertEqual(result["n_selected"], 5)

    def test_one_block_cannot_manufacture_uncertainty_interval(self):
        result = paired_block_comparison([
            {"event_id": f"e{i}", "block_id": "same", "candidate_loss": .1, "control_loss": .2}
            for i in range(20)], samples=50)
        self.assertEqual(result["status"], "INSUFFICIENT_BLOCKS")
        self.assertIsNone(result["ci_upper"])

    def test_unreported_trials_increase_multiplicity_penalty(self):
        result = holm_adjust({"shown-best": .01}, total_trials=40)
        self.assertAlmostEqual(result["tests"]["shown-best"]["adjusted_p_value"], .4)
        self.assertFalse(result["tests"]["shown-best"]["reject"])
        self.assertEqual(result["unreported_trials"], 39)

    def test_declared_dependence_and_multiplicity_raise_required_evidence(self):
        args = {"minimum_useful_improvement": .01, "paired_loss_sd": .1,
                "design_effect": 1, "alpha": .05, "total_trials": 1, "target_power": .8}
        independent = power_curve([100, 500], **args)
        adjusted = power_curve([100, 500], **{**args, "design_effect": 2, "total_trials": 40})
        self.assertGreater(adjusted["required_events_approximation"], independent["required_events_approximation"])
        self.assertEqual(adjusted["curve"][0]["effective_sample_size"], 50)
        self.assertFalse(adjusted["qualification_granted"])


class AdversarialNbaAcquisitionTests(unittest.TestCase):
    @staticmethod
    def capture(root, events):
        raw = json.dumps({"events": events}).encode()
        sha = hashlib.sha256(raw).hexdigest()
        (root / "source.json").write_bytes(raw)
        source = {"league": "nba", "kind": "schedule", "url": NBA_BASE + "/scoreboard?dates=20261022",
                  "raw_path": "source.json", "raw_sha256": sha, "status": "CAPTURED", "http_status": 200,
                  "requested_at_utc": "2026-10-22T19:58:00Z", "retrieved_at_utc": "2026-10-22T19:59:00Z"}
        (root / "report.json").write_text(json.dumps({"sources": [source]}))
        return source

    def test_provider_end_year_and_exact_raw_packet_are_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event = {"id": "future-game", "date": "2026-10-22T23:00:00Z",
                     "season": {"year": 2027, "type": 2, "slug": "regular-season"}}
            source = self.capture(root, [event])
            self.assertEqual(current_season(root, "2026-10-22T20:00:00Z")[0], 2027)
            packet = {event["id"]: {"event": event, "source_sha256": source["raw_sha256"],
                                    "retrieved_at_utc": source["retrieved_at_utc"]}}
            cutoff = datetime(2026, 10, 22, 20, tzinfo=timezone.utc)
            verify_current_events(root, packet, cutoff)
            packet[event["id"]]["event"] = {**event, "date": "2026-10-23T23:00:00Z"}
            with self.assertRaisesRegex(ValueError, "SOURCE_BINDING"):
                verify_current_events(root, packet, cutoff)

    def test_current_capture_of_april_events_cannot_establish_october_season(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.capture(root, [{"id": "old", "date": "2026-04-13T00:30:00Z",
                                 "season": {"year": 2026, "type": 2, "slug": "regular-season"}}])
            with self.assertRaisesRegex(ValueError, "UNPROVEN"):
                current_season(root, "2026-10-22T20:00:00Z")


class AdversarialIntegrationTests(unittest.TestCase):
    def fixture(self, root, decision_at=DECISION):
        fixture = signed_fixture(root / "registry")
        decision = select_research(fixture["forecast"], CONFIG, decision_at_utc=decision_at,
                                   registry=fixture["registry"])
        target = decision["target"]
        controls = copy.deepcopy(fixture["payload"])
        controls["procedure_id"] = "c" * 64
        controls["probabilities"] = {"win": .45, "loss": .35, "push": .2, "void": 0}
        population = [{"event_id": target["event_id"], "target_id": decision["target_id"], "slate_id": "synthetic-slate"}]
        outcomes = [{"event_id": target["event_id"], "target_id": decision["target_id"], "outcome": "WIN",
                     "status": "FINAL", "observed_at_utc": "2026-10-23T04:00:00Z",
                     "settled_at_utc": "2026-10-23T03:00:00Z", "source_sha256": "f" * 64,
                     "source_ref": "synthetic-test-only"}]
        manifest = {"schema": "research-selection-evaluation-input-v1", "evidence_scope": "DISCOVERY"}
        for key, value in (("population", population), ("decisions", [decision]),
                           ("outcomes", outcomes), ("controls", [seal_forecast(controls)])):
            data = json.dumps(value).encode()
            (root / (key + ".json")).write_bytes(data)
            manifest[key] = {"path": key + ".json", "sha256": hashlib.sha256(data).hexdigest()}
        path = root / "manifest.json"
        path.write_text(json.dumps(manifest))
        return path

    def test_control_direction_compares_win_and_loss_with_push_mass(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self.fixture(Path(tmp))
            bundle = build_evaluation(manifest, bootstrap_samples=20,
                                      executed_at=datetime(2026, 10, 23, 12, tzinfo=timezone.utc))
            self.assertEqual(bundle["evaluation_rows"][0]["control_predicted_outcome"], "WIN")
            self.assertEqual(bundle["report"]["full_slate_same_event_control"]["control_unconditional_win_accuracy"], 1)

    def test_poststart_decision_cannot_enter_chronological_raw_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = self.fixture(Path(tmp), decision_at="2026-10-23T02:00:00Z")
            bundle = build_evaluation(manifest, bootstrap_samples=20,
                                      executed_at=datetime(2026, 10, 23, 12, tzinfo=timezone.utc))
            self.assertEqual(bundle["report"]["n_events"], 1)
            self.assertEqual(bundle["report"]["full_slate_raw_forecast_scores"]["n"], 0)
            self.assertIsNone(bundle["evaluation_rows"][0]["raw_probability"])
            self.assertTrue(bundle["scoring_exclusions"])


class AdversarialAdditionalNbaAcquisitionTests(unittest.TestCase):
    capture = staticmethod(AdversarialNbaAcquisitionTests.capture)

    def test_conflicting_seasons_or_boolean_year_fail_closed(self):
        for years in ([2026, 2027], [True]):
            with self.subTest(years=years), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.capture(root, [{"id": str(i), "date": "2026-10-22T23:00:00Z",
                                     "season": {"year": year, "type": 2, "slug": "regular-season"}}
                                    for i, year in enumerate(years)])
                with self.assertRaises(ValueError):
                    current_season(root, "2026-10-22T20:00:00Z")

    def test_postcutoff_capture_and_source_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event = {"id": "future-game", "date": "2026-10-22T23:00:00Z",
                     "season": {"year": 2027, "type": 2, "slug": "regular-season"}}
            source = self.capture(root, [event])
            with self.assertRaisesRegex(ValueError, "NOT_AVAILABLE"):
                current_season(root, "2026-10-22T19:00:00Z")
            source["raw_path"] = "../untrusted.json"
            (root / "report.json").write_text(json.dumps({"sources": [source]}))
            with self.assertRaisesRegex(ValueError, "PATH_ESCAPE"):
                current_season(root, "2026-10-22T20:00:00Z")


if __name__ == "__main__":
    unittest.main()
