from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _dt(value: str) -> datetime:
    if not value or not value.endswith("Z"):
        raise ValueError("UTC_Z_TIMESTAMP_REQUIRED")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def canonical_hash(obj: dict) -> str:
    b = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(b).hexdigest()


def validate_remote_receipt(receipt: dict, scheduled_start_utc: str) -> None:
    required = [
        "remote_repository", "remote_branch", "remote_commit_sha",
        "remote_commit_received_at_utc", "remote_protection_status",
        "artifact_manifest_sha256",
    ]
    for key in required:
        if receipt.get(key) in (None, ""):
            raise ValueError(f"REMOTE_RECEIPT_MISSING:{key}")
    if not SHA40.fullmatch(receipt["remote_commit_sha"]):
        raise ValueError("REMOTE_COMMIT_SHA_INVALID")
    if not SHA256.fullmatch(receipt["artifact_manifest_sha256"]):
        raise ValueError("ARTIFACT_MANIFEST_SHA256_INVALID")
    if receipt["remote_protection_status"] != "PROTECTED_BRANCH":
        raise ValueError("REMOTE_BRANCH_NOT_PROTECTED")
    if _dt(receipt["remote_commit_received_at_utc"]) >= _dt(scheduled_start_utc):
        raise ValueError("REMOTE_RECEIPT_NOT_PREGAME")


def build_remote_registration_event(*, forecast: dict, receipt: dict, previous_record_hash: str | None) -> dict:
    """Create a REMOTE_DURABLE journal row only after a verified pregame remote receipt exists."""
    if forecast.get("forecast_status") != "SHADOW_ONLY" or forecast.get("action_authority") != "OFF":
        raise ValueError("FORECAST_GOVERNANCE_STATE_INVALID")
    if forecast.get("artifact_manifest_sha256") != receipt.get("artifact_manifest_sha256"):
        raise ValueError("RECEIPT_MANIFEST_MISMATCH")
    validate_remote_receipt(receipt, forecast["scheduled_start_utc"])
    row = {
        "journal_version": "1",
        "event_type": "FORECAST_REGISTRATION",
        "event_id": forecast["event_id"],
        "forecast_output_hash": forecast["forecast_output_hash"],
        "forecast_status": "SHADOW_ONLY",
        "prospective_eligible": True,
        "registration_scope": "REMOTE_DURABLE",
        "model_code_commit": forecast["model_code_commit"],
        "model_source_sha256": forecast["model_source_sha256"],
        "dependency_lock_sha256": forecast["dependency_lock_sha256"],
        "forecast_cutoff_utc": forecast["forecast_cutoff_utc"],
        "scheduled_start_utc": forecast["scheduled_start_utc"],
        "remote_repository": receipt["remote_repository"],
        "remote_branch": receipt["remote_branch"],
        "remote_commit_sha": receipt["remote_commit_sha"],
        "remote_commit_received_at_utc": receipt["remote_commit_received_at_utc"],
        "remote_protection_status": receipt["remote_protection_status"],
        "artifact_manifest_sha256": receipt["artifact_manifest_sha256"],
        "previous_journal_record_hash": previous_record_hash,
        "action_authority": "OFF",
    }
    row["record_hash"] = canonical_hash(row)
    return row


def build_late_import_event(*, event_id: str, artifact_manifest_sha256: str, imported_at_utc: str,
                            original_local_registration_timestamp_claimed: str | None,
                            remote_import_commit: str | None = None) -> dict:
    if not SHA256.fullmatch(artifact_manifest_sha256):
        raise ValueError("ARTIFACT_MANIFEST_SHA256_INVALID")
    row = {
        "journal_version": "1",
        "event_type": "LATE_DURABILITY_IMPORT",
        "event_id": event_id,
        "imported_at_utc": imported_at_utc,
        "artifact_manifest_sha256": artifact_manifest_sha256,
        "original_local_registration_timestamp_claimed": original_local_registration_timestamp_claimed,
        "remote_registration_timestamp": None,
        "remote_import_commit": remote_import_commit,
        "registration_scope": "LOCAL_ONLY",
        "remote_durability_at_event_time": "NOT_ESTABLISHED",
        "prospective_grade_eligible": False,
        "retroactive_registration_permitted": False,
        "action_authority": "OFF",
    }
    row["record_hash"] = canonical_hash(row)
    return row


def append_hash_chained_record(path: Path, row: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() and not path.read_bytes().endswith(b"\n"):
        raise ValueError("JOURNAL_APPEND_BOUNDARY_INVALID")
    payload = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(payload)
    return row["record_hash"]
