"""Opt-in personnel-v2 inference timing; weekly fitting/state are unchanged.

Hashes establish identity, not time. Historical admission additionally requires
an independently signed snapshot from a repository-pinned clock authority.
No clock authorities ship enabled. Synthetic tests provision temporary keys.
"""
from __future__ import annotations

import base64
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path

from models.experiments import cfb_personnel as personnel
from research.validation_registry import canonical_bytes, _decode
from scripts.register_mlb_calibration import registry_lock

POLICY_ID = "cfb.personnel-event-freshness.v1"
MODEL_ID = "cfb.fbs.matchup_efficiency.personnel.v2.event_refresh.v1.research"
TRUST_ROOTS = Path(__file__).with_name("cfb_personnel_clock_authorities.json")
IDENTITY = ("event_id", "home_id", "away_id", "home_team", "away_team",
            "season", "week", "start_time_utc", "neutral_site")


def now():
    return datetime.now(timezone.utc)


def time(value):
    if not isinstance(value, str):
        raise ValueError("CFB_REFRESH_AWARE_TIMESTAMP_REQUIRED")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("CFB_REFRESH_AWARE_TIMESTAMP_REQUIRED") from exc
    if stamp.tzinfo is None:
        raise ValueError("CFB_REFRESH_AWARE_TIMESTAMP_REQUIRED")
    return stamp.astimezone(timezone.utc)


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def identity(event):
    from models.experiments.cfb_efficiency import canonical_game
    normalized = canonical_game(event)
    if event.get("event_id", normalized["event_id"]) != normalized["event_id"]:
        raise ValueError("CFB_REFRESH_EVENT_ALIAS_CONFLICT")
    return {key: normalized[key] for key in IDENTITY}


def index_events(events):
    result = {}
    for event in events:
        key = identity(event)["event_id"]
        if key in result:
            raise ValueError("CFB_REFRESH_DUPLICATE_EVENT_IDENTITY")
        result[key] = event
    return result


def validate_policy(policy):
    if (not isinstance(policy, dict) or set(policy) != {"policy_id", "lead_seconds"}
            or policy["policy_id"] != POLICY_ID or type(policy["lead_seconds"]) is not int
            or not 1 <= policy["lead_seconds"] <= 86400):
        raise ValueError("CFB_REFRESH_EXPLICIT_POLICY_REQUIRED")
    return policy


def procedure_state(parent, policy):
    validate_policy(policy)
    result = {"model_id": MODEL_ID, "stage_id": "personnel_v2_event_refresh",
              "parent_state": copy.deepcopy(parent), "policy": copy.deepcopy(policy),
              "training_policy": "UNCHANGED_WEEKLY_PERSONNEL_V2_FIT",
              "action_authority": False, "predictive_validation": "UNVALIDATED"}
    result["state_sha256"] = digest(result)
    return result


def cutoff_for(example, request, policy):
    validate_policy(policy)
    if identity(request["event"]) != identity(example["event"]):
        raise ValueError("CFB_REFRESH_EVENT_IDENTITY_CONFLICT")
    requested = time(request["requested_as_of_utc"])
    start = time(example["start_time_utc"])
    # Never clamp a post-start request backwards into a pregame prediction.
    if requested >= start:
        raise ValueError("CFB_REFRESH_POST_START_REQUEST")
    cutoff = min(requested, start - timedelta(seconds=policy["lead_seconds"]))
    if not time(example["cutoff_utc"]) <= cutoff < start:
        raise ValueError("CFB_REFRESH_BEFORE_WEEKLY_CONTROL")
    return cutoff


def source_versions(evidence):
    versions = {}
    for side in ("home", "away"):
        for source in evidence[side]["sources"]:
            raw = personnel._read_json(source)
            stream = digest({"source": source["source"], "team_id": source["team_id"]})
            if stream in versions:
                raise ValueError("CFB_REFRESH_CONFLICTING_SOURCE_REVISIONS")
            version = source.get("version_id")
            if not isinstance(version, str) or not version:
                raise ValueError("CFB_REFRESH_SOURCE_VERSION_REQUIRED")
            pointer = source.get("version_pointer")
            if pointer is None:
                if version != source["sha256"]:
                    raise ValueError("CFB_REFRESH_CONTENT_VERSION_MISMATCH")
            elif personnel._pointer(raw, pointer) != version:
                raise ValueError("CFB_REFRESH_SOURCE_VERSION_MISMATCH")
            observed = time(source["observed_at_utc"])
            if time(personnel._pointer(raw, source.get("observed_time_pointer"))) != observed:
                raise ValueError("CFB_REFRESH_SOURCE_OBSERVATION_TIME_MISMATCH")
            versions[stream] = {key: source.get(key) for key in (
                "source", "team_id", "sha256", "version_id", "supersedes_sha256",
                "observed_at_utc", "retrieved_at_utc", "available_at_utc", "field_bindings")}
    return versions


def chronology(request, cutoff, mode, *, retained_blobs=None):
    anchor = request.get("chronology_anchor")
    if anchor is None:
        if mode == "HISTORICAL_REPLAY":
            raise ValueError("CFB_REFRESH_HISTORICAL_INDEPENDENT_AVAILABILITY_REQUIRED")
        return {"status": "UNVERIFIED", "independent_timestamp_verified": False}
    payload = anchor["payload"]
    expected_keys = {"schema", "authority_id", "event", "evidence_sha256", "recorded_at_utc"}
    if (set(payload) != expected_keys or payload["schema"] != "cfb.personnel-clock-attestation.v1"
            or payload["event"] != identity(request["event"])
            or payload["evidence_sha256"] != digest(request["personnel_evidence"])):
        raise ValueError("CFB_REFRESH_CLOCK_BINDING_MISMATCH")
    roots = _decode(TRUST_ROOTS.read_bytes())
    authority = roots["authorities"].get(payload["authority_id"])
    if authority is None:
        raise ValueError("CFB_REFRESH_UNTRUSTED_CLOCK_AUTHORITY")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(authority["public_key_base64"], validate=True)).verify(
            base64.b64decode(anchor["signature_base64"], validate=True), canonical_bytes(payload))
    except (ValueError, InvalidSignature) as exc:
        raise ValueError("CFB_REFRESH_INVALID_CLOCK_SIGNATURE") from exc
    recorded = time(payload["recorded_at_utc"])
    if not time(authority["valid_from_utc"]) <= recorded < time(authority["valid_until_utc"]):
        raise ValueError("CFB_REFRESH_CLOCK_AUTHORITY_OUTSIDE_VALIDITY")
    times = []
    for side in ("home", "away"):
        record = request["personnel_evidence"][side]
        for source in record["sources"]:
            times.extend(time(source[key]) for key in ("observed_at_utc", "retrieved_at_utc", "available_at_utc"))
        reference = record["participation_assumption"]
        if retained_blobs is not None:
            reference = {**reference, "path": str(Path(retained_blobs) / reference["sha256"])}
        times.append(time(personnel._read_json(reference)["created_at_utc"]))
    if not max(times) <= recorded < cutoff:
        raise ValueError("CFB_REFRESH_CLOCK_AFTER_CUTOFF_OR_BEFORE_CAPTURE")
    return {"status": "SIGNED_SNAPSHOT_TIME_VERIFIED", "independent_timestamp_verified": True,
            "anchor_sha256": digest(anchor), "trust_roots_sha256": digest(roots),
            "authority_id": payload["authority_id"], "recorded_at_utc": recorded.isoformat(),
            "provider_authenticity": "NOT_ESTABLISHED"}


def validate_snapshot(example, snapshot):
    if snapshot.get("schema") != "cfb.personnel-refresh-snapshot.v1":
        raise ValueError("CFB_REFRESH_SNAPSHOT_SCHEMA")
    request, policy, mode = snapshot["request"], snapshot["policy"], snapshot["mode"]
    if mode not in {"SHADOW", "HISTORICAL_REPLAY"}:
        raise ValueError("CFB_REFRESH_MODE_REQUIRED")
    cutoff = cutoff_for(example, request, policy)
    if time(request["requested_as_of_utc"]) > now():
        raise ValueError("CFB_REFRESH_FUTURE_ASOF")
    if mode == "SHADOW" and now() >= time(example["start_time_utc"]):
        raise ValueError("CFB_REFRESH_POST_START_WRITER")
    if digest(example.get("personnel_evidence")) != digest(request["personnel_evidence"]):
        raise ValueError("CFB_REFRESH_EVIDENCE_BINDING_MISMATCH")
    # These are the existing source bytes, pointer, assumption, coverage and
    # strict retrieval/availability < cutoff checks. No timestamps are retimed.
    features = personnel.values(example, personnel_cutoff_utc=cutoff.isoformat())
    for side in ("home", "away"):
        record = request["personnel_evidence"][side]
        declared = personnel._read_json(record["participation_assumption"])
        if time(declared["created_at_utc"]) < max(time(s["available_at_utc"]) for s in record["sources"]):
            raise ValueError("CFB_REFRESH_ASSUMPTION_BEFORE_AVAILABILITY")
    versions = source_versions(request["personnel_evidence"])
    clock = chronology(request, cutoff, mode)
    return {"policy_id": POLICY_ID, "policy_sha256": digest(policy),
            "weekly_cutoff_utc": example["cutoff_utc"], "personnel_cutoff_utc": cutoff.isoformat(),
            "snapshot_sha256": digest(snapshot), "feature_values": features,
            "source_versions": versions, "chronology": clock,
            "current_source_qualified": False, "predictive_validation": "UNVALIDATED",
            "canonical_prospective_eligible": False, "publication_allowed": False,
            "market_features_used": False, "action_authority": False}


def prepare_snapshot(example, request, policy, mode, history):
    from models.experiments.cfb_efficiency import canonical_game, DEFAULT_CONFIG
    candidate = copy.deepcopy(example)
    candidate["personnel_evidence"] = copy.deepcopy(request["personnel_evidence"])
    # Construct the original weekly coverage census if the baseline had no
    # personnel input. It never includes later-week game results.
    candidate["personnel_schedule_coverage"] = personnel.schedule_coverage(
        list(map(canonical_game, history["games"])), history["team_games"], candidate["event"],
        candidate["cutoff_utc"], history_seasons=DEFAULT_CONFIG["history_seasons"],
        label_lag_hours=DEFAULT_CONFIG["label_lag_hours"])
    snapshot = {"schema": "cfb.personnel-refresh-snapshot.v1", "mode": mode,
                "policy": copy.deepcopy(policy), "request": copy.deepcopy(request)}
    validate_snapshot(candidate, snapshot)
    return candidate, snapshot


def _load_receipt(path):
    if path.is_symlink():
        raise ValueError("CFB_REFRESH_STORAGE_SYMLINK")
    value = _decode(path.read_bytes())
    expected = digest({k: v for k, v in value.items() if k != "receipt_sha256"})
    if value.get("receipt_sha256") != expected or path.stem != expected:
        raise ValueError("CFB_REFRESH_RECEIPT_HASH_MISMATCH")
    return value


def _exclusive(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def verify_retained_receipt(receipt_path, store):
    """Read-only source/clock recheck from retained bytes after input paths vanish.

    Parent-model historical PIT and provider authenticity are separate checks.
    This function cannot upgrade either or create a prospective registration.
    """
    receipt = _load_receipt(Path(receipt_path))
    blobs = Path(store) / "blobs"
    for sha in receipt["retained_blob_sha256"]:
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("CFB_REFRESH_RETAINED_BYTES_MISMATCH")
        path = blobs / sha
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError("CFB_REFRESH_RETAINED_BYTES_MISMATCH")
    snapshot = receipt["snapshot"]
    request = snapshot["request"]
    component = receipt["component_receipt"]
    inputs = component["inputs"]
    row = {"event_id": receipt["event"]["event_id"], "event": receipt["event"],
           "start_time_utc": receipt["event"]["start_time_utc"],
           "cutoff_utc": inputs["weekly_cutoff_utc"],
           "personnel_schedule_coverage": inputs["personnel_schedule_coverage"],
           "personnel_evidence": copy.deepcopy(request["personnel_evidence"])}
    cutoff = cutoff_for(row, request, snapshot["policy"])
    if (digest(snapshot) != receipt["freshness"]["snapshot_sha256"]
            or cutoff != time(receipt["freshness"]["personnel_cutoff_utc"])
            or inputs["snapshot"] != snapshot):
        raise ValueError("CFB_REFRESH_EVIDENCE_BINDING_MISMATCH")
    # Resolve only paths in a disposable view. Signed original metadata stays
    # untouched; every replacement is still checked against its original hash.
    for side in ("home", "away"):
        record = row["personnel_evidence"][side]
        for ref in [*record["sources"], record["participation_assumption"]]:
            ref["path"] = str(blobs / ref["sha256"])
    features = personnel.values(row, personnel_cutoff_utc=cutoff.isoformat())
    if (features != receipt["freshness"]["feature_values"]
            or source_versions(row["personnel_evidence"]) != receipt["freshness"]["source_versions"]):
        raise ValueError("CFB_REFRESH_RETAINED_CONSUMPTION_MISMATCH")
    clock = chronology(request, cutoff, snapshot["mode"], retained_blobs=blobs)
    return {"receipt_sha256": receipt["receipt_sha256"], "personnel_bytes_and_values": "PASS",
            "chronology": clock, "provider_authenticity": "NOT_ESTABLISHED",
            "parent_model_historical_pit": "NOT_ESTABLISHED", "action_authority": False}


def write_refresh(store, example, snapshot, forecast, *, parent_state, parent_card_sha256,
                  component_receipt):
    """Append a locally immutable chain; never updates first-forecast registers.

    This is trusted-process filesystem protection, not hostile-host WORM storage
    or an independent registration clock. Completed receipts retain raw bytes.
    """
    from research.efficiency.integrity import verify_component_receipt
    verified_component = verify_component_receipt(component_receipt)
    checked = validate_snapshot(example, snapshot)
    if (forecast.get("personnel_freshness") != checked
            or verified_component["forecast"].get("personnel_freshness") != checked
            or verified_component["model_id"] != MODEL_ID
            or verified_component["forecast"].get("model_state_sha256") != procedure_state(parent_state, snapshot["policy"])["state_sha256"]
            or verified_component["forecast"].get("parent_model_state_sha256") != parent_state["state_sha256"]):
        raise ValueError("CFB_REFRESH_FORECAST_BINDING_MISMATCH")
    root = Path(store).absolute()
    if any(p.is_symlink() for p in [root, *root.parents]):
        raise ValueError("CFB_REFRESH_STORAGE_SYMLINK")
    root.mkdir(parents=True, exist_ok=True)
    key = digest({"event_id": example["event_id"], "policy": snapshot["policy"],
                  "parent_state_sha256": parent_state["state_sha256"], "mode": snapshot["mode"]})
    directory, blobs = root / key, root / "blobs"
    for p in (directory, blobs, root / "refresh.lock"):
        if p.is_symlink():
            raise ValueError("CFB_REFRESH_STORAGE_SYMLINK")
    with registry_lock(root / "refresh.lock"):
        if directory.is_symlink() or blobs.is_symlink():
            raise ValueError("CFB_REFRESH_STORAGE_SYMLINK")
        directory.mkdir(exist_ok=True)
        blobs.mkdir(exist_ok=True)
        receipts = sorted((_load_receipt(p) for p in directory.glob("*.json")), key=lambda r: r["sequence"])
        predecessor = None
        for sequence, prior in enumerate(receipts):
            if prior["sequence"] != sequence or prior["previous_receipt_sha256"] != predecessor:
                raise ValueError("CFB_REFRESH_BROKEN_CHAIN")
            predecessor = prior["receipt_sha256"]
            for sha in prior["retained_blob_sha256"]:
                if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                    raise ValueError("CFB_REFRESH_RETAINED_BYTES_MISMATCH")
                path = blobs / sha
                if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                    raise ValueError("CFB_REFRESH_RETAINED_BYTES_MISMATCH")
        if snapshot["request"].get("previous_receipt_sha256") != predecessor:
            raise ValueError("CFB_REFRESH_PREDECESSOR_CONFLICT")
        if receipts:
            previous = receipts[-1]
            if previous["event"] != identity(example["event"]):
                raise ValueError("CFB_REFRESH_EVENT_IDENTITY_CONFLICT")
            if previous["parent_card_sha256"] != parent_card_sha256:
                raise ValueError("CFB_REFRESH_PARENT_CARD_CONFLICT")
            if time(checked["personnel_cutoff_utc"]) <= time(previous["freshness"]["personnel_cutoff_utc"]):
                raise ValueError("CFB_REFRESH_NONINCREASING_CUTOFF")
            old, new = previous["freshness"]["source_versions"], checked["source_versions"]
            if old.keys() != new.keys():
                raise ValueError("CFB_REFRESH_SOURCE_SET_CHANGED")
            for stream, row in new.items():
                if row == old[stream]:
                    continue
                if (row["sha256"] == old[stream]["sha256"] or row["version_id"] == old[stream]["version_id"]
                        or row["supersedes_sha256"] != old[stream]["sha256"]
                        or time(row["observed_at_utc"]) <= time(old[stream]["observed_at_utc"])
                        or time(row["retrieved_at_utc"]) <= time(old[stream]["retrieved_at_utc"])):
                    raise ValueError("CFB_REFRESH_CONFLICTING_SOURCE_REVISIONS")
        # Recheck actual time under the lock, including completion after kickoff.
        registered = now()
        if snapshot["mode"] == "SHADOW" and registered >= time(example["start_time_utc"]):
            raise ValueError("CFB_REFRESH_POST_START_WRITER")
        references = personnel.sources(example)
        raw_blobs = {}
        for reference in references:
            raw = Path(reference["path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
                raise ValueError("CFB_REFRESH_SOURCE_CHANGED_DURING_RUN")
            raw_blobs[reference["sha256"]] = raw
        for sha, raw in raw_blobs.items():
            path = blobs / sha
            if path.is_symlink():
                raise ValueError("CFB_REFRESH_STORAGE_SYMLINK")
            if path.exists():
                if path.read_bytes() != raw:
                    raise ValueError("CFB_REFRESH_RETAINED_BYTES_MISMATCH")
            else:
                _exclusive(path, raw)
        registered = now()
        if (registered < time(verified_component["created_at_utc"])
                or (snapshot["mode"] == "SHADOW" and registered >= time(example["start_time_utc"]))):
            raise ValueError("CFB_REFRESH_WRITER_COMPLETION_CHRONOLOGY")
        receipt = {"schema": "cfb.personnel-refresh-receipt.v1", "sequence": len(receipts),
            "previous_receipt_sha256": predecessor, "event": identity(example["event"]),
            "registered_at_utc": registered.isoformat(), "snapshot": snapshot,
            "freshness": checked, "parent_card_sha256": parent_card_sha256,
            "parent_state_sha256": parent_state["state_sha256"],
            "baseline_features_sha256": digest(example["features"]),
            "component_receipt": component_receipt, "retained_blob_sha256": sorted(raw_blobs),
            "scoring_policy": "FIRST_ACCEPTED_REFRESH_PER_EVENT_PARENT_POLICY",
            "status": "LOCAL_RESEARCH_REFRESH" if snapshot["mode"] == "SHADOW" else "HISTORICAL_REPLAY",
            "external_registration_timestamp_verified": False,
            "canonical_prospective_eligible": False, "action_authority": False}
        receipt["receipt_sha256"] = digest(receipt)
        _exclusive(directory / (receipt["receipt_sha256"] + ".json"), canonical_bytes(receipt))
        return receipt
