"""Evidence-bound research eligibility. This module never grants publication authority.

Trust anchors are supplied by the application, never by an evaluation artifact.
An authenticated review is an attestation, not proof that its scientific claims
are true. Distinct signing identities do not establish distinct human reviewers.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


class RegistryError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def content_id(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _digest(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise RegistryError("INVALID_CONTENT_ID")
    return value


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise RegistryError("MISSING_AWARE_TIMESTAMP")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RegistryError("INVALID_TIMESTAMP") from exc
    if result.tzinfo is None:
        raise RegistryError("NAIVE_TIMESTAMP")
    return result.astimezone(timezone.utc)


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RegistryError("INVALID_FINITE_NUMBER")
    return float(value)


def _integer(value: Any, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise RegistryError("INVALID_COUNT")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RegistryError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _decode(raw: bytes) -> Any:
    return json.loads(raw, object_pairs_hook=_unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(RegistryError("NONFINITE_JSON")))


class ArtifactStore:
    """Immutable canonical JSON objects; put never replaces an existing object."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def read(self, artifact_id: str) -> dict:
        path = self.root / (_digest(artifact_id) + ".json")
        if path.is_symlink() or path.resolve().parent != self.root:
            raise RegistryError("ARTIFACT_PATH_ESCAPE")
        try:
            value = _decode(path.read_bytes())
        except OSError as exc:
            raise RegistryError("MISSING_ARTIFACT") from exc
        if not isinstance(value, dict) or content_id(value) != artifact_id:
            raise RegistryError("ARTIFACT_HASH_MISMATCH")
        return value

    def put(self, artifact: Mapping[str, Any]) -> str:
        raw = canonical_bytes(dict(artifact))
        artifact_id = hashlib.sha256(raw).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / (artifact_id + ".json")
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            self.read(artifact_id)
            return artifact_id
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return artifact_id


class Ed25519Verifier:
    """Optional cryptography-backed verifier; no signer or key is trusted by default.

    Public keys are raw 32-byte keys, supplied outside the artifact store. Receipt
    payloads bind an artifact, purpose, signer identity and external witness time.
    This library deliberately does not implement or operate a signing authority.
    """

    def __init__(self, trusted_public_keys: Mapping[str, bytes] | None = None):
        self._keys = dict(trusted_public_keys or {})

    def verify(self, receipt: Mapping[str, Any], *, artifact_id: str, purpose: str) -> dict:
        payload = receipt.get("payload")
        if not isinstance(payload, dict) or payload.get("artifact_id") != artifact_id or payload.get("purpose") != purpose:
            raise RegistryError("ATTESTATION_BINDING_MISMATCH")
        signer = payload.get("signer_id")
        if not isinstance(signer, str) or signer not in self._keys:
            raise RegistryError("UNTRUSTED_SIGNER")
        _time(payload.get("witnessed_at_utc"))
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        except ImportError as exc:
            raise RegistryError("SIGNATURE_BACKEND_UNAVAILABLE") from exc
        try:
            signature = base64.b64decode(receipt["signature_b64"], validate=True)
            Ed25519PublicKey.from_public_bytes(self._keys[signer]).verify(signature, canonical_bytes(payload))
        except Exception as exc:
            raise RegistryError("INVALID_ATTESTATION_SIGNATURE") from exc
        return payload

    def same_credential(self, first: str, second: str) -> bool:
        return first in self._keys and second in self._keys and self._keys[first] == self._keys[second]


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    reasons: tuple[str, ...]
    record_id: str | None = None
    protocol_id: str | None = None
    evidence_id: str | None = None
    reviewer_id: str | None = None
    publication_allowed: bool = False
    registry_schema: str = "validation-registry-v2"
    lineage_id: str | None = None
    inspected_configurations: int | None = None
    lifecycle_event_id: str | None = None
    retained_defect_ids: tuple[str, ...] = ()


class ValidationRegistry:
    """Resolve signed, exact-procedure qualification for research selection only.

    record_ids identify review records. A review record refers to its detached
    signed review receipt; to avoid a circular hash, that receipt signs the
    separate review_payload_id. No ancestor's approval is considered.
    """

    TARGET_KEYS = frozenset({"league", "product", "period", "settlement_rules_id"})

    def __init__(self, store: ArtifactStore, record_ids=(), verifier: Ed25519Verifier | None = None, *, revocation_ids=(),
                 trial_log=None, trial_tip=None, lifecycle_log=None, lifecycle_tip=None):
        if not isinstance(store, ArtifactStore) or (verifier is not None and not isinstance(verifier, Ed25519Verifier)):
            raise TypeError("registry requires an artifact store and supported verifier")
        self.store = store
        self.record_ids = tuple(record_ids)
        self.revocation_ids = tuple(revocation_ids)
        self.verifier = verifier or Ed25519Verifier()
        self.trial_log, self.trial_tip = trial_log, trial_tip
        self.lifecycle_log, self.lifecycle_tip = lifecycle_log, lifecycle_tip

    def assess(self, procedure_id: str, target: Mapping[str, Any], at_utc: str,
               selector_config_id: str | None = None) -> Eligibility:
        failures = []
        try:
            _digest(procedure_id)
            _digest(selector_config_id)
            when = _time(at_utc)
            if not isinstance(target, Mapping) or set(target) != self.TARGET_KEYS or any(not isinstance(v, str) or not v for v in target.values()):
                raise RegistryError("INVALID_TARGET_FAMILY")
            revoked = self._revoked(when)
        except (RegistryError, KeyError, TypeError, ValueError, OverflowError) as exc:
            return Eligibility(False, (str(exc),))
        for record_id in self.record_ids:
            try:
                if record_id in revoked:
                    raise RegistryError("VALIDATION_REVOKED")
                result = self._assess_record(record_id, procedure_id, dict(target), when, selector_config_id)
                return result
            except (RegistryError, KeyError, TypeError, ValueError, OverflowError) as exc:
                failures.append(str(exc))
        return Eligibility(False, tuple(sorted(set(failures))) or ("NO_QUALIFYING_VALIDATION",))

    def _revoked(self, when):
        revoked = set()
        for item_id in self.revocation_ids:
            item = self.store.read(item_id)
            payload_id = item["revocation_payload_id"]
            payload = self.store.read(payload_id)
            receipt = self.verifier.verify(self.store.read(item["revocation_receipt_id"]),
                                           artifact_id=payload_id, purpose="validation_revocation")
            if not isinstance(payload.get("reason"), str) or not payload["reason"]:
                raise RegistryError("REVOCATION_REASON_REQUIRED")
            record_id = _digest(payload["record_id"])
            if _time(receipt["witnessed_at_utc"]) <= when:
                revoked.add(record_id)
        return revoked

    def replay_legacy_record(self, record_id, procedure_id, target, at_utc, *, selector_config_id):
        """Reproduce v1 research admission without authorizing a new selection.

        This deliberately separate return type cannot be consumed as Eligibility.
        No old record is rewritten or silently treated as a v2 protocol.
        """
        try:
            when = _time(at_utc)
            if record_id in self._revoked(when):
                raise RegistryError("VALIDATION_REVOKED")
            result = self._assess_record(record_id, procedure_id, dict(target), when,
                                         selector_config_id, require_v2=False)
            reasons, legacy = (), result.eligible
        except (RegistryError, KeyError, TypeError, ValueError, OverflowError) as exc:
            reasons, legacy = (str(exc),), False
        return {"schema": "validation-registry-v1-replay", "legacy_eligible": legacy,
                "selection_eligible": False, "publication_allowed": False, "reasons": reasons,
                "record_id": record_id}

    def _assess_record(self, record_id, procedure_id, target, when, config_id, *, require_v2=True):
        record = self.store.read(record_id)
        review_id = record["review_payload_id"]
        review = self.store.read(review_id)
        signed = self.verifier.verify(self.store.read(record["review_receipt_id"]), artifact_id=review_id, purpose="validation_review")
        reviewed_at = _time(signed["witnessed_at_utc"])
        if reviewed_at > when:
            raise RegistryError("REVIEW_NOT_AVAILABLE_AT_CUTOFF")
        protocol_id, evidence_id = review["protocol_id"], review["evidence_id"]
        protocol, evidence = self.store.read(protocol_id), self.store.read(evidence_id)
        if require_v2 and protocol.get("schema") != "validation-protocol-v2":
            raise RegistryError("LEGACY_VALIDATION_REQUIRES_V2_ADMISSION")
        if not require_v2 and protocol.get("schema") not in (None, "validation-protocol-v1"):
            raise RegistryError("NOT_A_LEGACY_VALIDATION_PROTOCOL")
        self.store.read(procedure_id)
        self.store.read(protocol["control_id"])
        self.store.read(protocol["population_id"])
        if protocol["candidate_id"] != procedure_id or evidence["candidate_id"] != procedure_id:
            raise RegistryError("PROCEDURE_MISMATCH")
        if protocol["target"] != target or evidence["target"] != target:
            raise RegistryError("TARGET_MISMATCH")
        if protocol["selector_config_id"] != config_id or evidence["selector_config_id"] != config_id:
            raise RegistryError("SELECTOR_CONFIG_MISMATCH")
        self.store.read(config_id)
        if protocol["objective"] != "unconditional_win" or evidence["objective"] != protocol["objective"]:
            raise RegistryError("OBJECTIVE_MISMATCH")
        for key in ("control_id", "population_id", "primary_metric", "evaluation_start_utc", "evaluation_end_utc"):
            if evidence[key] != protocol[key]:
                raise RegistryError("EVIDENCE_PROTOCOL_MISMATCH:" + key)
        if evidence["protocol_id"] != protocol_id:
            raise RegistryError("PROTOCOL_ID_MISMATCH")
        author = protocol["author_id"]
        if (not isinstance(author, str) or not author or signed["signer_id"] == author
                or self.verifier.same_credential(author, signed["signer_id"])):
            raise RegistryError("AUTHOR_REVIEWER_NOT_SEPARATE")
        authorship = self.verifier.verify(self.store.read(review["authorship_receipt_id"]), artifact_id=protocol_id, purpose="protocol_authorship")
        if authorship["signer_id"] != author:
            raise RegistryError("AUTHORSHIP_IDENTITY_MISMATCH")
        registration = self.verifier.verify(self.store.read(review["registration_receipt_id"]), artifact_id=protocol_id, purpose="preregistration")
        start, end = _time(protocol["evaluation_start_utc"]), _time(protocol["evaluation_end_utc"])
        if not (_time(protocol["development_end_utc"]) < start < end):
            raise RegistryError("OVERLAPPING_OR_EMPTY_WINDOWS")
        if not _time(authorship["witnessed_at_utc"]) <= _time(registration["witnessed_at_utc"]) < start:
            raise RegistryError("LATE_PREREGISTRATION")
        if not end <= _time(evidence["computed_at_utc"]) <= reviewed_at:
            raise RegistryError("INVALID_EVIDENCE_CHRONOLOGY")
        expiry_days = _number(protocol["valid_for_days"])
        if expiry_days <= 0 or when > reviewed_at + timedelta(days=expiry_days):
            raise RegistryError("VALIDATION_EXPIRED")
        if protocol["primary_metric"] not in {"brier", "log_loss", "non_win_risk"}:
            raise RegistryError("UNSUPPORTED_PRIMARY_METRIC")
        criteria = protocol["criteria"]
        n_events, n_slates, n_selected = (_integer(evidence[k]) for k in ("n_events", "n_slates", "n_selected"))
        if not 0 <= n_selected <= n_events or n_slates > n_events:
            raise RegistryError("INCONSISTENT_EVIDENCE_COUNTS")
        for key, actual in (("minimum_events", n_events), ("minimum_slates", n_slates), ("minimum_selected", n_selected)):
            if actual < _integer(criteria[key], 1):
                raise RegistryError("INSUFFICIENT_EVIDENCE:" + key)
        coverage = _number(evidence["total_coverage"])
        lo, hi = _number(criteria["minimum_total_coverage"]), _number(criteria["maximum_total_coverage"])
        if not 0 <= lo <= hi <= 1 or not lo <= coverage <= hi:
            raise RegistryError("COVERAGE_CRITERION_FAILED")
        if n_events == 0 or not math.isclose(coverage, n_selected / n_events, abs_tol=1e-12, rel_tol=0):
            raise RegistryError("COVERAGE_DENOMINATOR_MISMATCH")
        if _number(evidence["primary_delta_ci_upper"]) > _number(criteria["maximum_primary_delta_ci_upper"]):
            raise RegistryError("PRIMARY_METRIC_CRITERION_FAILED")
        power, min_power = _number(evidence["power_at_declared_effect"]), _number(criteria["minimum_power"])
        if not 0 < min_power < 1 or not min_power <= power <= 1:
            raise RegistryError("POWER_CRITERION_FAILED")
        # The signed reviewer attests scientific claims. Hash binding is not a
        # proof of outcome authenticity, power assumptions or statistical truth.
        dataset = self.store.read(_digest(evidence["paired_dataset_id"]))
        if dataset.get("evidence_scope") != "CONFIRMATION":
            raise RegistryError("DISCOVERY_OR_SHADOW_CANNOT_QUALIFY")
        result = Eligibility(True, (), record_id, protocol_id, evidence_id, signed["signer_id"])
        if require_v2:
            result = self._check_v2(result, protocol, evidence, registration, when, target, config_id)
        return result

    def _check_v2(self, result, protocol, evidence, registration, when, target, config_id):
        from research.procedure_lineage import ProcedureLineage, predictive_identity
        lineage = ProcedureLineage(self.store).resolve(protocol["candidate_id"])
        ProcedureLineage(self.store).resolve(protocol["control_id"])
        node = self.store.read(protocol["candidate_id"])
        identity = predictive_identity(node["definition"])
        for artifact in (protocol, evidence):
            if "predictive_identity" in artifact and artifact["predictive_identity"] != identity:
                raise RegistryError("PREDICTIVE_IDENTITY_BINDING_MISMATCH")
        if node["owner"] != protocol["author_id"] or _time(node["created_utc"]) > _time(registration["witnessed_at_utc"]):
            raise RegistryError("PROCEDURE_OWNER_OR_CHRONOLOGY_MISMATCH")
        justifications = protocol.get("criteria_justification")
        if not isinstance(justifications, dict):
            raise RegistryError("PROTOCOL_MINIMA_JUSTIFICATION_REQUIRED")
        for key in ("minimum_events", "minimum_slates", "minimum_selected", "minimum_total_coverage", "minimum_power"):
            rationale = justifications.get(key)
            if not isinstance(rationale, dict) or not isinstance(rationale.get("rationale"), str) or not rationale["rationale"].strip():
                raise RegistryError("PROTOCOL_MINIMUM_UNJUSTIFIED:" + key)
            basis = self.store.read(_digest(rationale.get("basis_artifact_id")))
            if basis.get("schema") != "validation-design-basis-v1":
                raise RegistryError("DESIGN_BASIS_SCHEMA_REQUIRED")
        budget = _integer(protocol.get("inspection_budget"), 1)
        assumptions = protocol.get("power_assumptions")
        required_power = {"minimum_useful_improvement", "paired_loss_sd", "design_effect", "alpha",
                          "total_trials", "target_power", "dependence"}
        if not isinstance(assumptions, dict) or not required_power <= set(assumptions):
            raise RegistryError("DECLARED_POWER_ASSUMPTIONS_REQUIRED")
        if not isinstance(assumptions["dependence"], str) or not assumptions["dependence"].strip():
            raise RegistryError("DECLARED_DEPENDENCE_ASSUMPTION_REQUIRED")
        if (_integer(assumptions["total_trials"], 1) < budget or
                _number(assumptions["target_power"]) != _number(protocol["criteria"]["minimum_power"])):
            raise RegistryError("POWER_PLAN_PROTOCOL_MISMATCH")
        # Validate the declared numeric domain with the same planning method.
        # This is not observed power and does not certify the empirical SD or
        # dependence claim; those remain bound to the independent review.
        from research.selection_evaluation import power_curve
        power_curve([1], **{key: assumptions[key] for key in required_power - {"dependence"}})
        if type(self.trial_log) is not TrialLog or self.trial_tip is None:
            raise RegistryError("ANCHORED_TRIAL_LOG_REQUIRED")
        exposure = self.trial_log.lineage_exposure(self.store, protocol["candidate_id"],
                                                 expected_tip=_digest(self.trial_tip), as_of_utc=when.isoformat())
        evidence_exposure = self.trial_log.lineage_exposure(self.store, protocol["candidate_id"],
                       expected_tip=self.trial_tip, as_of_utc=evidence["computed_at_utc"])
        if evidence_exposure["inspected_configurations"] != _integer(evidence.get("inspected_configurations"), 1):
            raise RegistryError("ANCESTRY_INSPECTION_COUNT_MISMATCH")
        if exposure["inspected_configurations"] > budget:
            raise RegistryError("ANCESTRY_INSPECTION_BUDGET_EXCEEDED")
        if type(self.lifecycle_log) is not LifecycleLog or self.lifecycle_tip is None:
            raise RegistryError("ANCHORED_LIFECYCLE_LOG_REQUIRED")
        if self.lifecycle_log.store.root != self.store.root or self.lifecycle_log.verifier._keys != self.verifier._keys:
            raise RegistryError("LIFECYCLE_TRUST_CONTEXT_MISMATCH")
        lifecycle = self.lifecycle_log.state(protocol["candidate_id"], target, config_id,
                           when.isoformat(), expected_tip=_digest(self.lifecycle_tip))
        if lifecycle["status"] != "QUALIFY" or lifecycle["record_id"] != result.record_id:
            raise RegistryError("LIFECYCLE_NOT_QUALIFIED:" + lifecycle["status"])
        inherited_defects = self.lifecycle_log.defect_history(protocol["candidate_id"], when.isoformat(), expected_tip=self.lifecycle_tip)
        return replace(result, lineage_id=lineage.lineage_id,
                       inspected_configurations=exposure["inspected_configurations"],
                       lifecycle_event_id=lifecycle["event_id"],
                       retained_defect_ids=tuple(sorted(set(lineage.defect_ids) | set(inherited_defects))))


class TrialLog:
    """Separate append-only research trial journal; never a forecast/grade ledger.

    A hash chain detects edits/reordering but cannot detect truncation without an
    independently retained tip. Pass expected_tip when verifying an anchored log.
    File locks serialize local writers; external durable anchoring remains required.
    Family labels are external governance, not an inferred ancestry graph. Use
    the global inspected count unless a trusted protocol binds the family. This
    journal cannot detect an undeclared inspection or a falsely declared root.
    """

    def __init__(self, path: str | Path, clock=None):
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _verify(raw: str, expected_tip: str | None = None) -> list[dict]:
        records, previous, last_time = [], "0" * 64, None
        trials = {}
        for line in raw.splitlines():
            value = _decode(line.encode("utf-8"))
            digest = value.pop("record_id", None)
            if content_id(value) != digest or value["previous_id"] != previous or value["sequence"] != len(records):
                raise RegistryError("TRIAL_CHAIN_CORRUPT")
            at = _time(value["recorded_at_utc"])
            if last_time is not None and at < last_time:
                raise RegistryError("TRIAL_CLOCK_REVERSED")
            payload = value["payload"]
            if payload.get("kind") == "INSPECTED":
                trial = payload["trial_id"]
                if trial in trials:
                    raise RegistryError("DUPLICATE_INSPECTED_TRIAL")
                trials[trial] = payload["configuration_id"]
            value["record_id"] = digest
            records.append(value)
            previous, last_time = digest, at
        if expected_tip is not None and previous != expected_tip:
            raise RegistryError("TRIAL_ANCHOR_MISMATCH")
        return records

    def read(self, expected_tip: str | None = None) -> list[dict]:
        raw = self.path.read_text() if self.path.exists() else ""
        return self._verify(raw, expected_tip)

    def append(self, payload: Mapping[str, Any], *, expected_tip: str | None = None, _validator=None) -> dict:
        import fcntl
        payload = dict(payload)
        for key in ("kind", "trial_id", "family_id"):
            if not isinstance(payload.get(key), str) or not payload[key]:
                raise RegistryError("INVALID_TRIAL_PAYLOAD")
        if payload["kind"] == "INSPECTED":
            _digest(payload.get("configuration_id"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            stream.seek(0)
            raw = stream.read()
            records = self._verify(raw, expected_tip)
            stamp = self.clock()
            if stamp.tzinfo is None:
                raise RegistryError("NAIVE_WRITER_CLOCK")
            record = {"sequence": len(records), "previous_id": records[-1]["record_id"] if records else "0" * 64,
                      "recorded_at_utc": stamp.astimezone(timezone.utc).isoformat(), "payload": payload}
            record["record_id"] = content_id(record)
            line = canonical_bytes(record).decode("utf-8") + "\n"
            complete = self._verify(raw + line)
            if _validator is not None:
                _validator(complete)
            stream.seek(0, os.SEEK_END)
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
        return record

    def inspected_count(self, family_id: str | None = None, *, expected_tip: str | None = None) -> int:
        return sum(r["payload"].get("kind") == "INSPECTED" and
                   (family_id is None or r["payload"].get("family_id") == family_id)
                   for r in self.read(expected_tip))

    def lineage_exposure(self, store, procedure_id, *, expected_tip, as_of_utc=None):
        """Count inspections across common ancestry, ignoring renameable family labels.

        Siblings sharing any declared root count toward the same exposure. Legacy
        unbound inspections are conservatively included for every lineage. No
        forecast performance or qualification is pooled across these ancestors.
        """
        from research.procedure_lineage import ProcedureLineage
        resolver = ProcedureLineage(store)
        lineage = resolver.resolve(procedure_id)
        roots, included, unbound = set(lineage.root_ids), [], []
        cutoff = _time(as_of_utc) if as_of_utc is not None else None
        for record in self.read(_digest(expected_tip)):
            if cutoff is not None and _time(record["recorded_at_utc"]) > cutoff:
                continue
            payload = record["payload"]
            if payload.get("kind") != "INSPECTED":
                continue
            candidate = payload.get("procedure_id")
            if candidate is None:
                included.append(record["record_id"])
                unbound.append(record["record_id"])
            elif roots.intersection(resolver.resolve(_digest(candidate)).root_ids):
                included.append(record["record_id"])
        return {"lineage_id": lineage.lineage_id, "root_ids": list(lineage.root_ids),
                "inspected_configurations": len(included), "inspection_record_ids": included,
                "legacy_unbound_inspections": unbound, "trial_log_tip": expected_tip,
                "performance_inherited": False}


class LifecycleLog:
    """Signed append-only qualification transitions, resolved at an explicit cutoff.

    An externally retained tip is mandatory for admission. QUALIFY/REVOKE/EXPIRE
    refer to exact procedure, selector, target and review record. DEFECT_RECORDED
    is retained across ancestry without transferring a parent's approval.
    """
    ACTIONS = frozenset({"QUALIFY", "REVOKE", "EXPIRE", "DEFECT_RECORDED"})

    def __init__(self, store: ArtifactStore, path, verifier: Ed25519Verifier, clock=None):
        if not isinstance(store, ArtifactStore) or not isinstance(verifier, Ed25519Verifier):
            raise TypeError("store and external verifier required")
        self.store, self.verifier = store, verifier
        self.journal = TrialLog(path, clock=clock)

    def _validate_records(self, records):
        from research.procedure_lineage import ProcedureLineage
        events, seen, last_time, active = [], set(), {}, {}
        for record in records:
            wrapper = record["payload"]
            if wrapper.get("kind") != "LIFECYCLE":
                raise RegistryError("NON_LIFECYCLE_RECORD")
            event_id = _digest(wrapper.get("event_id"))
            if event_id in seen:
                raise RegistryError("DUPLICATE_LIFECYCLE_EVENT")
            seen.add(event_id)
            event = self.store.read(event_id)
            if event.get("schema") != "procedure-lifecycle-event-v1" or event.get("action") not in self.ACTIONS:
                raise RegistryError("LIFECYCLE_EVENT_SCHEMA_REQUIRED")
            signed = self.verifier.verify(self.store.read(_digest(wrapper.get("receipt_id"))),
                                          artifact_id=event_id, purpose="procedure_lifecycle")
            witnessed, observed = _time(signed["witnessed_at_utc"]), _time(record["recorded_at_utc"])
            if not _time(event.get("created_utc")) <= witnessed <= observed:
                raise RegistryError("LIFECYCLE_EVENT_CHRONOLOGY")
            procedure = _digest(event.get("procedure_id"))
            ProcedureLineage(self.store).resolve(procedure)
            if _time(self.store.read(procedure)["created_utc"]) > _time(event["created_utc"]):
                raise RegistryError("LIFECYCLE_EVENT_PRECEDES_PROCEDURE")
            config = _digest(event.get("selector_config_id"))
            target = event.get("target")
            if not isinstance(target, dict) or set(target) != ValidationRegistry.TARGET_KEYS:
                raise RegistryError("LIFECYCLE_TARGET_REQUIRED")
            scope = (procedure, config, content_id(target))
            if scope in last_time and witnessed < last_time[scope]:
                raise RegistryError("LIFECYCLE_WITNESS_TIME_REVERSED")
            last_time[scope] = witnessed
            if not isinstance(event.get("reason"), str) or not event["reason"].strip():
                raise RegistryError("LIFECYCLE_REASON_REQUIRED")
            if event["action"] == "DEFECT_RECORDED":
                defect = self.store.read(_digest(event.get("defect_id")))
                if defect.get("schema") != "procedure-defect-v1":
                    raise RegistryError("DEFECT_SCHEMA_REQUIRED")
            else:
                review_record = _digest(event.get("record_id"))
                record_body = self.store.read(review_record)
                review = self.store.read(record_body["review_payload_id"])
                protocol = self.store.read(review["protocol_id"])
                if (protocol["candidate_id"], protocol["selector_config_id"], protocol["target"]) != (procedure, config, target):
                    raise RegistryError("LIFECYCLE_REVIEW_BINDING_MISMATCH")
                if event["action"] == "QUALIFY":
                    if signed["signer_id"] == protocol["author_id"] or self.verifier.same_credential(signed["signer_id"], protocol["author_id"]):
                        raise RegistryError("LIFECYCLE_SELF_QUALIFICATION")
                    reviewed = self.verifier.verify(self.store.read(record_body["review_receipt_id"]),
                                                    artifact_id=record_body["review_payload_id"], purpose="validation_review")
                    if _time(reviewed["witnessed_at_utc"]) > witnessed:
                        raise RegistryError("LIFECYCLE_QUALIFIED_BEFORE_REVIEW")
                    active[scope] = review_record
                elif active.get(scope) != review_record:
                    raise RegistryError("LIFECYCLE_DEMOTION_RECORD_MISMATCH")
                else:
                    active.pop(scope)
            events.append({"event_id": event_id, "event": event, "witnessed_at_utc": witnessed,
                           "recorded_at_utc": observed, "signer_id": signed["signer_id"]})
        return events

    def append(self, event_id, receipt_id, *, expected_tip=None):
        payload = {"kind": "LIFECYCLE", "trial_id": _digest(event_id), "family_id": "signed-lifecycle",
                   "event_id": event_id, "receipt_id": _digest(receipt_id)}
        return self.journal.append(payload, expected_tip=expected_tip, _validator=self._validate_records)

    def read(self, *, expected_tip):
        return self._validate_records(self.journal.read(_digest(expected_tip)))

    def state(self, procedure_id, target, selector_config_id, at_utc, *, expected_tip):
        when = _time(at_utc)
        state = {"status": "UNQUALIFIED", "record_id": None, "event_id": None}
        for item in self.read(expected_tip=expected_tip):
            event = item["event"]
            if item["witnessed_at_utc"] > when or item["recorded_at_utc"] > when:
                continue
            if (event["procedure_id"], event["target"], event["selector_config_id"]) != (procedure_id, target, selector_config_id):
                continue
            if event["action"] != "DEFECT_RECORDED":
                state = {"status": event["action"], "record_id": event["record_id"], "event_id": item["event_id"]}
        return state

    def defect_history(self, procedure_id, at_utc, *, expected_tip):
        from research.procedure_lineage import ProcedureLineage
        ancestors = set(ProcedureLineage(self.store).resolve(procedure_id).ancestor_ids)
        when, retained = _time(at_utc), set()
        for item in self.read(expected_tip=expected_tip):
            event = item["event"]
            if (event["action"] == "DEFECT_RECORDED" and event["procedure_id"] in ancestors
                    and item["witnessed_at_utc"] <= when and item["recorded_at_utc"] <= when):
                retained.add(event["defect_id"])
        return tuple(sorted(retained))
