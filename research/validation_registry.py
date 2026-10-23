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
from dataclasses import dataclass
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


class ValidationRegistry:
    """Resolve signed, exact-procedure qualification for research selection only.

    record_ids identify review records. A review record refers to its detached
    signed review receipt; to avoid a circular hash, that receipt signs the
    separate review_payload_id. No ancestor's approval is considered.
    """

    TARGET_KEYS = frozenset({"league", "product", "period", "settlement_rules_id"})

    def __init__(self, store: ArtifactStore, record_ids=(), verifier: Ed25519Verifier | None = None, *, revocation_ids=()):
        if not isinstance(store, ArtifactStore) or (verifier is not None and not isinstance(verifier, Ed25519Verifier)):
            raise TypeError("registry requires an artifact store and supported verifier")
        self.store = store
        self.record_ids = tuple(record_ids)
        self.revocation_ids = tuple(revocation_ids)
        self.verifier = verifier or Ed25519Verifier()

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

    def _assess_record(self, record_id, procedure_id, target, when, config_id):
        record = self.store.read(record_id)
        review_id = record["review_payload_id"]
        review = self.store.read(review_id)
        signed = self.verifier.verify(self.store.read(record["review_receipt_id"]), artifact_id=review_id, purpose="validation_review")
        reviewed_at = _time(signed["witnessed_at_utc"])
        if reviewed_at > when:
            raise RegistryError("REVIEW_NOT_AVAILABLE_AT_CUTOFF")
        protocol_id, evidence_id = review["protocol_id"], review["evidence_id"]
        protocol, evidence = self.store.read(protocol_id), self.store.read(evidence_id)
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
        return Eligibility(True, (), record_id, protocol_id, evidence_id, signed["signer_id"])


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

    def append(self, payload: Mapping[str, Any], *, expected_tip: str | None = None) -> dict:
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
            self._verify(raw + line)
            stream.seek(0, os.SEEK_END)
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())
        return record

    def inspected_count(self, family_id: str | None = None, *, expected_tip: str | None = None) -> int:
        return sum(r["payload"].get("kind") == "INSPECTED" and
                   (family_id is None or r["payload"].get("family_id") == family_id)
                   for r in self.read(expected_tip))
