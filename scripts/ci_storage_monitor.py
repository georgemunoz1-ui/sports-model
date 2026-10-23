#!/usr/bin/env python3
"""Measure visible repository artifacts and persist threshold transitions.

This is not an account billing/quota monitor. It never sends notifications or
deletes artifacts. An explicit threshold and persistent adapter are required.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.ci_evidence_archive import ArchiveError, PinnedAdapter, canonical, config_from_environment, decode, now, write_new

METRIC_SCOPE = "repository_visible_active_artifacts_bytes"


def content_id(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def instant(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset().total_seconds() != 0:
        raise ArchiveError("UTC_TIMESTAMP_REQUIRED")
    return result


def inventory(pages, repository):
    if not isinstance(pages, list) or not pages:
        raise ArchiveError("PAGINATED_INVENTORY_REQUIRED")
    artifacts = {}
    totals = set()
    for page in pages:
        if not isinstance(page, dict) or type(page.get("total_count")) is not int or page["total_count"] < 0 or not isinstance(page.get("artifacts"), list):
            raise ArchiveError("INVALID_INVENTORY_PAGE")
        totals.add(page["total_count"])
        for item in page["artifacts"]:
            if not isinstance(item, dict) or type(item.get("id")) is not int or type(item.get("size_in_bytes")) is not int or item["size_in_bytes"] < 0 or type(item.get("expired")) is not bool:
                raise ArchiveError("INVALID_ARTIFACT_METADATA")
            if item["id"] in artifacts:
                raise ArchiveError("DUPLICATE_ARTIFACT_ID")
            artifacts[item["id"]] = item
    if len(totals) != 1 or totals != {len(artifacts)}:
        raise ArchiveError("INCOMPLETE_OR_CHANGING_INVENTORY")
    active = [item for item in artifacts.values() if not item["expired"]]
    return {"repository": repository, "metric_scope": METRIC_SCOPE,
            "pagination_page_count": len(pages), "declared_total_count": next(iter(totals)),
            "visible_artifact_count": len(artifacts), "visible_active_artifact_count": len(active),
            "visible_artifact_bytes": sum(item["size_in_bytes"] for item in artifacts.values()),
            "visible_active_artifact_bytes": sum(item["size_in_bytes"] for item in active),
            "value_bytes": sum(item["size_in_bytes"] for item in active),
            "account_quota_status": "UNKNOWN_NOT_MEASURED",
            "inventory_sha256": content_id(pages)}


def monitor_policy(config):
    if not isinstance(config, dict) or config.get("schema") != "ci-storage-monitor-v1":
        raise ArchiveError("INVALID_MONITOR_CONFIG")
    required = {"schema", "repository", "metric_scope", "threshold_bytes", "initial_below_policy", "state_key"}
    if set(config) != required or config["metric_scope"] != METRIC_SCOPE:
        raise ArchiveError("EXPLICIT_REPOSITORY_METRIC_SCOPE_REQUIRED")
    if type(config["threshold_bytes"]) is not int or config["threshold_bytes"] <= 0:
        raise ArchiveError("POSITIVE_EXPLICIT_THRESHOLD_REQUIRED")
    if config["initial_below_policy"] not in {"baseline_only", "record_event"}:
        raise ArchiveError("INITIAL_BELOW_POLICY_REQUIRED")
    if any(not isinstance(config[key], str) or not config[key].strip() for key in ("repository", "state_key")):
        raise ArchiveError("REPOSITORY_AND_PERSISTENT_STATE_KEY_REQUIRED")
    return config


def validate_state(state):
    if not isinstance(state, dict) or state.get("schema") != "ci-storage-state-v1":
        raise ArchiveError("INVALID_PERSISTED_STATE")
    if state.get("state_id") != content_id({k: v for k, v in state.items() if k != "state_id"}):
        raise ArchiveError("PERSISTED_STATE_HASH_MISMATCH")
    if state.get("band") not in {"AT_OR_ABOVE", "BELOW"} or not isinstance(state.get("pending_events"), list):
        raise ArchiveError("INVALID_PERSISTED_STATE_CONTENT")
    return state


def transition(config, previous, measurement, observed_at):
    config = monitor_policy(config)
    config_id = content_id(config)
    if measurement.get("repository") != config["repository"] or measurement.get("metric_scope") != config["metric_scope"]:
        raise ArchiveError("MEASUREMENT_SCOPE_MISMATCH")
    value = measurement.get("value_bytes")
    if type(value) is not int or value < 0:
        raise ArchiveError("INVALID_STORAGE_MEASUREMENT")
    instant(observed_at)
    if previous is not None:
        validate_state(previous)
        if previous["config_id"] != config_id:
            raise ArchiveError("STATE_CONFIG_MISMATCH_USE_EXPLICIT_NEW_STATE_KEY")
        if instant(observed_at) <= instant(previous["observed_at_utc"]):
            raise ArchiveError("NONINCREASING_OBSERVATION_TIME")
    band = "BELOW" if value < config["threshold_bytes"] else "AT_OR_ABOVE"
    kind = None
    if band == "BELOW" and previous is None and config["initial_below_policy"] == "record_event":
        kind = "INITIAL_BELOW"
    elif band == "BELOW" and previous is not None and previous["band"] == "AT_OR_ABOVE":
        kind = "CROSSED_BELOW"
    event = None
    if kind:
        event = {"kind": kind, "config_id": config_id, "observed_at_utc": observed_at,
                 "value_bytes": value, "threshold_bytes": config["threshold_bytes"],
                 "metric_scope": config["metric_scope"], "repository": config["repository"],
                 "notification_sent": False}
        event["event_id"] = content_id(event)
    state = {"schema": "ci-storage-state-v1", "config_id": config_id,
             "parent_state_id": previous["state_id"] if previous else None,
             "observed_at_utc": observed_at, "band": band, "value_bytes": value,
             "inventory_sha256": measurement["inventory_sha256"],
             "pending_events": (previous["pending_events"] if previous else []) + ([event] if event else [])}
    state["state_id"] = content_id(state)
    return state, event


def persist_transition(adapter, policy, measurement, observed_at):
    policy = monitor_policy(policy)
    adapter.capabilities({"state_get", "state_compare_and_swap"})
    key = {"destination_id": adapter.destination, "state_key": policy["state_key"]}
    current = adapter.call("state_get", key)
    if "state" not in current or "revision" not in current or (current["state"] is None) != (current["revision"] is None) or (current["revision"] is not None and not isinstance(current["revision"], str)):
        raise ArchiveError("INVALID_REMOTE_STATE_ENVELOPE")
    state, event = transition(policy, current["state"], measurement, observed_at)
    saved = adapter.call("state_compare_and_swap", {**key, "expected_revision": current["revision"], "state": state})
    if not isinstance(saved.get("revision"), str) or not saved["revision"] or saved.get("state_sha256") != content_id(state):
        raise ArchiveError("STATE_PERSISTENCE_ACK_MISMATCH")
    readback = adapter.call("state_get", key)
    if readback.get("revision") != saved["revision"] or readback.get("state") != state:
        raise ArchiveError("PERSISTENT_STATE_READBACK_MISMATCH")
    validate_state(readback["state"])
    return {"status": "PERSISTED", "state_id": state["state_id"], "revision": saved["revision"],
            "band": state["band"], "transition_event": event, "pending_event_count": len(state["pending_events"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, help="Complete gh api --paginate --slurp artifact pages.")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", required=True, help="Fresh local report file.")
    parser.add_argument("--storage-config-env", default="CI_STORAGE_CONFIG_JSON")
    parser.add_argument("--monitor-config-env", default="CI_STORAGE_MONITOR_CONFIG_JSON")
    args = parser.parse_args(argv)
    report = {"schema": "ci-storage-monitor-report-v1", "created_at_utc": now(),
              "status": "FAILED", "notification_status": "DISABLED_UNCONFIGURED",
              "notification_sent": False, "artifacts_deleted": 0}
    exit_code = 0
    try:
        report["measurement"] = inventory(decode(Path(args.inventory).read_bytes()), args.repository)
        storage = config_from_environment(args.storage_config_env)
        policy = config_from_environment(args.monitor_config_env)
        if storage is None or policy is None:
            report.update(status="BLOCKED_UNCONFIGURED", reason="THRESHOLD_AND_PERSISTENT_STORAGE_CONFIGURATION_REQUIRED")
        else:
            report.update(persist_transition(PinnedAdapter(storage), policy, report["measurement"], report["created_at_utc"]))
    except (ArchiveError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        report.update(status="FAILED", reason=str(exc))
        exit_code = 1
    write_new(args.output, report)
    print(json.dumps(report, sort_keys=True))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write(f"\nStorage monitor: **{report['status']}**. Account quota is UNKNOWN. "
                          "Notifications disabled; no artifacts deleted.\n")
            measured = report.get("measurement")
            if measured:
                summary.write(f"\nEnumerated {measured['pagination_page_count']} pages: "
                    f"{measured['visible_artifact_count']} visible artifacts / {measured['visible_artifact_bytes']} bytes; "
                    f"{measured['visible_active_artifact_count']} nonexpired artifacts / {measured['visible_active_artifact_bytes']} bytes. "
                    f"Canonical inventory SHA-256: `{measured['inventory_sha256']}`.\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
