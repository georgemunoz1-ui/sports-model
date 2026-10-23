"""Synthetic signatures test verification mechanics, never real qualification."""
import base64
import copy
import json
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from research.validation_registry import (ArtifactStore, Ed25519Verifier, RegistryError,
                                          LifecycleLog, TrialLog, ValidationRegistry, canonical_bytes, content_id)
from research.procedure_lineage import create_procedure


def make_registry_fixture(root, *, protocol_overrides=None, evidence_overrides=None,
                          config_artifact=None, target=None, registration_at=None,
                          reviewer="TEST_ONLY_reviewer", dataset_scope="CONFIRMATION", legacy=False):
    """Entirely fabricated TEST_ONLY evidence; not production trust or results.

    Returns registry, procedure_id, config_id, target, at_utc, store, keys, sign,
    record_id, protocol, evidence. Override fields before signing to test exact
    failure modes. Keys are ephemeral and never written to a production config.
    """
    store = ArtifactStore(root)
    keys = {name: Ed25519PrivateKey.generate() for name in
            ("TEST_ONLY_author", "TEST_ONLY_reviewer", "TEST_ONLY_witness")}
    verifier = Ed25519Verifier({name: key.public_key().public_bytes(serialization.Encoding.Raw,
                           serialization.PublicFormat.Raw) for name, key in keys.items()})
    def sign(artifact_id, purpose, signer, timestamp):
        payload = {"artifact_id": artifact_id, "purpose": purpose,
                   "signer_id": signer, "witnessed_at_utc": timestamp}
        return store.put({"payload": payload, "signature_b64": base64.b64encode(
            keys[signer].sign(canonical_bytes(payload))).decode()})
    def procedure(name):
        return create_procedure(store, parent_ids=[], owner="TEST_ONLY_author", created_utc="2025-12-31T00:00:00Z",
                                change_hypothesis="TEST_ONLY mechanics fixture", definition={"name": name,
                                 "model_id": name, "model_state_id": content_id({"synthetic_state": name}),
                                 "feature_semantics_id": content_id({"synthetic_features": name}),
                                 "calibration_id": content_id({"synthetic_calibration": name})})
    procedure_id, control_id = procedure("TEST_ONLY candidate"), procedure("TEST_ONLY control")
    config_id = store.put(config_artifact or {"objective": "unconditional_win", "threshold": .6})
    population_id = store.put({"kind": "TEST_ONLY external population", "event_ids": ["a", "b", "c", "d"]})
    target = target or {"league": "nfl", "product": "spread", "period": "full_game",
                        "settlement_rules_id": "full-game-ot-push-refund-v1"}
    protocol = {"candidate_id": procedure_id, "control_id": control_id, "population_id": population_id,
                "target": target, "selector_config_id": config_id, "objective": "unconditional_win",
                "author_id": "TEST_ONLY_author", "development_end_utc": "2026-01-01T00:00:00Z",
                "evaluation_start_utc": "2026-01-02T00:00:00Z", "evaluation_end_utc": "2026-01-10T00:00:00Z",
                "primary_metric": "brier", "valid_for_days": 365,
                "criteria": {"minimum_events": 4, "minimum_slates": 2, "minimum_selected": 2,
                             "minimum_total_coverage": .4, "maximum_total_coverage": .6,
                             "maximum_primary_delta_ci_upper": -.001, "minimum_power": .8}}
    if not legacy:
        basis_id = store.put({"schema": "validation-design-basis-v1", "kind": "TEST_ONLY synthetic mechanics",
                              "minimum_useful_improvement": .5, "paired_loss_sd": .1,
                              "dependence_assumption": "TEST_ONLY independent synthetic blocks", "power_target": .8})
        protocol.update(schema="validation-protocol-v2", inspection_budget=4,
                        power_assumptions={"minimum_useful_improvement": .5, "paired_loss_sd": .1,
                                           "design_effect": 1., "alpha": .05,
                                           "total_trials": (protocol_overrides or {}).get("inspection_budget", 4),
                                           "target_power": .8, "dependence": "TEST_ONLY independent synthetic blocks"},
                        criteria_justification={key: {"rationale": "TEST_ONLY fixture; no empirical scientific claim",
                                                      "basis_artifact_id": basis_id}
                                                for key in ("minimum_events", "minimum_slates", "minimum_selected",
                                                            "minimum_total_coverage", "minimum_power")})
    protocol.update(protocol_overrides or {})
    protocol_id = store.put(protocol)
    registration_id = sign(protocol_id, "preregistration", "TEST_ONLY_witness",
                           registration_at or "2026-01-01T12:00:00Z")
    authorship_id = sign(protocol_id, "protocol_authorship", "TEST_ONLY_author", "2026-01-01T10:00:00Z")
    dataset_id = store.put({"kind": "TEST_ONLY fabricated fixture", "evidence_scope": dataset_scope})
    evidence = {key: protocol[key] for key in ("candidate_id", "control_id", "population_id", "target",
                 "selector_config_id", "objective", "primary_metric", "evaluation_start_utc", "evaluation_end_utc")}
    evidence.update(protocol_id=protocol_id, computed_at_utc="2026-01-11T00:00:00Z", n_events=4,
                    n_slates=2, n_selected=2, total_coverage=.5, primary_delta_ci_upper=-.01,
                    power_at_declared_effect=.85, paired_dataset_id=dataset_id)
    if not legacy:
        evidence["inspected_configurations"] = 1
    evidence.update(evidence_overrides or {})
    evidence_id = store.put(evidence)
    review_id = store.put({"protocol_id": protocol_id, "evidence_id": evidence_id,
                           "registration_receipt_id": registration_id, "authorship_receipt_id": authorship_id})
    review_receipt_id = sign(review_id, "validation_review", reviewer, "2026-01-12T00:00:00Z")
    record_id = store.put({"review_payload_id": review_id, "review_receipt_id": review_receipt_id})
    extra = {}
    if not legacy:
        unique = uuid.uuid4().hex
        trial_log = TrialLog(Path(root) / ("trials-" + unique + ".jsonl"),
                             clock=lambda: datetime(2026, 1, 1, 9, tzinfo=timezone.utc))
        tip = trial_log.append({"kind": "INSPECTED", "trial_id": "TEST_ONLY trial", "family_id": "TEST_ONLY family",
                                "configuration_id": config_id, "procedure_id": procedure_id})["record_id"]
        lifecycle = LifecycleLog(store, Path(root) / ("lifecycle-" + unique + ".jsonl"), verifier,
                                 clock=lambda: datetime(2026, 1, 12, 1, tzinfo=timezone.utc))
        event_id = store.put({"schema": "procedure-lifecycle-event-v1", "action": "QUALIFY", "record_id": record_id,
                              "procedure_id": procedure_id, "selector_config_id": config_id, "target": target,
                              "created_utc": "2026-01-12T01:00:00Z", "reason": "TEST_ONLY synthetic test qualification"})
        event_receipt = sign(event_id, "procedure_lifecycle", "TEST_ONLY_reviewer", "2026-01-12T01:00:00Z")
        life_tip = lifecycle.append(event_id, event_receipt)["record_id"]
        extra = {"trial_log": trial_log, "trial_tip": tip, "lifecycle_log": lifecycle, "lifecycle_tip": life_tip}
    return {"registry": ValidationRegistry(store, [record_id], verifier, **extra), "procedure_id": procedure_id,
            "config_id": config_id, "target": target, "at_utc": "2026-10-22T21:00:00Z", "store": store,
            "keys": keys, "sign": sign, "record_id": record_id, "protocol": protocol, "evidence": evidence,
            "protocol_id": protocol_id, "evidence_id": evidence_id, "verifier": verifier, **extra}


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def make(self, **kw):
        return make_registry_fixture(self.temp.name, **kw)

    def assess(self, fixture, **kw):
        args = {"procedure_id": fixture["procedure_id"], "target": fixture["target"],
                "at_utc": fixture["at_utc"], "selector_config_id": fixture["config_id"]}
        args.update(kw)
        return fixture["registry"].assess(**args)

    def test_real_signature_path_is_research_only(self):
        f = self.make()
        result = self.assess(f)
        self.assertTrue(result.eligible, result.reasons)
        self.assertFalse(result.publication_allowed)
        self.assertEqual(result.evidence_id, f["evidence_id"])

    def test_untrusted_signer_and_missing_record_fail_closed(self):
        f = self.make()
        f["registry"] = ValidationRegistry(f["store"], [f["record_id"]])
        self.assertFalse(self.assess(f).eligible)
        f["registry"] = ValidationRegistry(f["store"])
        self.assertIn("NO_QUALIFYING_VALIDATION", self.assess(f).reasons)

    def test_artifact_mutation_and_put_never_overwrite(self):
        f = self.make()
        path = Path(self.temp.name) / (f["protocol_id"] + ".json")
        mutated = dict(f["protocol"], valid_for_days=999)
        path.write_text(json.dumps(mutated))
        self.assertFalse(self.assess(f).eligible)
        with self.assertRaises(RegistryError):
            f["store"].put(f["protocol"])
        self.assertEqual(json.loads(path.read_text()), mutated)

    def test_scope_config_and_child_do_not_inherit(self):
        f = self.make()
        child = f["store"].put({"parent_ids": [f["procedure_id"]], "kind": "child"})
        self.assertFalse(self.assess(f, procedure_id=child).eligible)
        self.assertFalse(self.assess(f, selector_config_id=f["store"].put({"threshold": .7})).eligible)
        self.assertFalse(self.assess(f, target=dict(f["target"], period="first_half")).eligible)

    def test_authored_and_reviewed_by_same_identity_rejected(self):
        f = self.make(reviewer="TEST_ONLY_author")
        self.assertIn("AUTHOR_REVIEWER_NOT_SEPARATE", self.assess(f).reasons)

    def test_authorship_cannot_be_relabelled(self):
        f = self.make(protocol_overrides={"author_id": "made_up_other_person"})
        self.assertIn("AUTHORSHIP_IDENTITY_MISMATCH", self.assess(f).reasons)

    def test_chronology_and_expiration(self):
        cases = [dict(registration_at="2026-01-02T00:00:00Z"),
                 dict(protocol_overrides={"development_end_utc": "2026-01-02T00:00:00Z"}),
                 dict(evidence_overrides={"computed_at_utc": "2026-01-13T00:00:00Z"}),
                 dict(protocol_overrides={"valid_for_days": 2}),
                 dict(protocol_overrides={"valid_for_days": 1e300})]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs):
                self.assertFalse(self.assess(self.make(**kwargs)).eligible)
        self.assertFalse(self.assess(self.make(), at_utc="2026-01-11T00:00:00Z").eligible)

    def test_failed_evidence_and_discovery_never_qualify(self):
        for kwargs in (dict(evidence_overrides={"total_coverage": .55}),
                       dict(evidence_overrides={"n_events": True}),
                       dict(evidence_overrides={"primary_delta_ci_upper": .01}),
                       dict(evidence_overrides={"power_at_declared_effect": .7}),
                       dict(dataset_scope="DISCOVERY"), dict(dataset_scope="SHADOW")):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(self.assess(self.make(**kwargs)).eligible)

    def test_signed_revocation_is_effective_only_after_witness_time(self):
        f = self.make()
        payload_id = f["store"].put({"record_id": f["record_id"], "reason": "TEST_ONLY drift"})
        receipt_id = f["sign"](payload_id, "validation_revocation", "TEST_ONLY_reviewer", "2026-10-22T22:00:00Z")
        revoke_id = f["store"].put({"revocation_payload_id": payload_id, "revocation_receipt_id": receipt_id})
        f["registry"] = ValidationRegistry(f["store"], [f["record_id"]], f["verifier"], revocation_ids=[revoke_id],
                                           **{k: f[k] for k in ("trial_log", "trial_tip", "lifecycle_log", "lifecycle_tip")})
        self.assertTrue(self.assess(f).eligible)
        self.assertIn("VALIDATION_REVOKED", self.assess(f, at_utc="2026-10-23T00:00:00Z").reasons)

    def test_receipt_signature_tamper_rejected(self):
        f = self.make()
        record = f["store"].read(f["record_id"])
        receipt = f["store"].read(record["review_receipt_id"])
        receipt["payload"]["witnessed_at_utc"] = "2026-01-11T12:00:00Z"
        record["review_receipt_id"] = f["store"].put(receipt)
        f["registry"] = ValidationRegistry(f["store"], [f["store"].put(record)], f["verifier"])
        self.assertIn("INVALID_ATTESTATION_SIGNATURE", self.assess(f).reasons)


class TrialLogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "trials.jsonl"
        self.log = TrialLog(self.path, clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))

    def payload(self, name):
        return {"kind": "INSPECTED", "trial_id": name, "family_id": "f", "configuration_id": content_id({"name": name})}

    def test_append_count_duplicate_and_retained_tip(self):
        a, b = self.log.append(self.payload("a")), self.log.append(self.payload("b"))
        self.assertEqual(self.log.inspected_count("f"), 2)
        self.assertEqual(self.log.inspected_count(expected_tip=b["record_id"]), 2)
        self.assertEqual(self.log.read(expected_tip=b["record_id"])[0], a)
        before = self.path.read_bytes()
        with self.assertRaises(RegistryError):
            self.log.append(self.payload("a"))
        self.assertEqual(before, self.path.read_bytes())
        self.path.write_bytes(before.splitlines(keepends=True)[0])
        self.assertEqual(len(self.log.read()), 1)  # No dishonest claim of unanchored truncation detection.
        with self.assertRaises(RegistryError):
            self.log.read(expected_tip=b["record_id"])
        with self.assertRaises(RegistryError):
            self.log.append(self.payload("c"), expected_tip=b["record_id"])

    def test_internal_mutation_and_clock_reversal(self):
        self.log.append(self.payload("a"))
        backwards = TrialLog(self.path, clock=lambda: datetime(2025, 1, 1, tzinfo=timezone.utc))
        with self.assertRaises(RegistryError):
            backwards.append(self.payload("b"))
        raw = self.path.read_text().replace('"family_id":"f"', '"family_id":"g"')
        self.path.write_text(raw)
        with self.assertRaises(RegistryError):
            self.log.read()


if __name__ == "__main__":
    unittest.main()
