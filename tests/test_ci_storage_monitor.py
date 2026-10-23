"""Threshold state-machine and persistent adapter tests; no external messages."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from scripts.ci_evidence_archive import ArchiveError, PinnedAdapter
from scripts.ci_storage_monitor import (METRIC_SCOPE, inventory, persist_transition, transition)
from tests.test_ci_storage_archive import fake_adapter


ROOT = Path(__file__).resolve().parents[1]
POLICY = {"schema": "ci-storage-monitor-v1", "repository": "TEST_ONLY/repo",
          "metric_scope": METRIC_SCOPE, "threshold_bytes": 100,
          "initial_below_policy": "baseline_only", "state_key": "TEST_ONLY-storage-state"}


def measurement(value):
    return {"repository": POLICY["repository"], "metric_scope": METRIC_SCOPE,
            "value_bytes": value, "inventory_sha256": "a" * 64}


def test_above_to_below_emits_once_and_repeated_below_suppresses(tmp_path):
    adapter, config = fake_adapter(tmp_path)
    first = persist_transition(adapter, POLICY, measurement(101), "2026-10-23T00:00:00Z")
    assert first["transition_event"] is None
    second = persist_transition(adapter, POLICY, measurement(99), "2026-10-23T01:00:00Z")
    assert second["transition_event"]["kind"] == "CROSSED_BELOW"
    # Reconstruct adapter in a separate invocation-equivalent instance: state is remote,
    # not an in-memory singleton or GitHub artifact that depends on free quota.
    third = persist_transition(PinnedAdapter(config), POLICY, measurement(98), "2026-10-23T02:00:00Z")
    assert third["transition_event"] is None
    assert third["pending_event_count"] == 1
    assert second["transition_event"]["notification_sent"] is False


@pytest.mark.parametrize("policy,expected", [("baseline_only", None), ("record_event", "INITIAL_BELOW")])
def test_initial_below_policy_is_explicit_and_tested(policy, expected):
    state, event = transition(dict(POLICY, initial_below_policy=policy), None, measurement(99), "2026-10-23T00:00:00Z")
    assert (event["kind"] if event else None) == expected
    _, repeated = transition(dict(POLICY, initial_below_policy=policy), state, measurement(90), "2026-10-23T01:00:00Z")
    assert repeated is None


def test_boundary_recrossing_and_stale_observation():
    first, _ = transition(POLICY, None, measurement(100), "2026-10-23T00:00:00Z")
    assert first["band"] == "AT_OR_ABOVE"
    below, event = transition(POLICY, first, measurement(99), "2026-10-23T01:00:00Z")
    above, _ = transition(POLICY, below, measurement(100), "2026-10-23T02:00:00Z")
    final, recross = transition(POLICY, above, measurement(0), "2026-10-23T03:00:00Z")
    assert event["event_id"] != recross["event_id"]
    assert len(final["pending_events"]) == 2
    with pytest.raises(ArchiveError, match="NONINCREASING"):
        transition(POLICY, final, measurement(0), "2026-10-23T03:00:00Z")


def test_threshold_change_cannot_reuse_old_state_or_invent_a_transition():
    state, _ = transition(POLICY, None, measurement(101), "2026-10-23T00:00:00Z")
    with pytest.raises(ArchiveError, match="STATE_CONFIG_MISMATCH"):
        transition(dict(POLICY, threshold_bytes=200), state, measurement(101), "2026-10-23T01:00:00Z")


@pytest.mark.parametrize("mode,error", [("conflict", "ADAPTER_OPERATION_FAILED"), ("state_corrupt", "READBACK_MISMATCH")])
def test_persistent_state_conflicts_and_corruption_fail_closed(tmp_path, mode, error):
    adapter, _ = fake_adapter(tmp_path, mode)
    with pytest.raises(ArchiveError, match=error):
        persist_transition(adapter, POLICY, measurement(101), "2026-10-23T00:00:00Z")


def test_complete_repository_inventory_is_not_account_quota():
    pages = [{"total_count": 2, "artifacts": [{"id": 1, "size_in_bytes": 100, "expired": False}]},
             {"total_count": 2, "artifacts": [{"id": 2, "size_in_bytes": 500, "expired": True}]}]
    result = inventory(pages, POLICY["repository"])
    assert result["value_bytes"] == 100
    assert result["visible_artifact_bytes"] == 600
    assert result["visible_active_artifact_bytes"] == 100
    assert result["pagination_page_count"] == 2
    assert result["declared_total_count"] == 2
    assert result["visible_artifact_count"] == 2
    assert result["account_quota_status"] == "UNKNOWN_NOT_MEASURED"
    with pytest.raises(ArchiveError, match="INCOMPLETE"):
        inventory(pages[:1], POLICY["repository"])
    with pytest.raises(ArchiveError, match="DUPLICATE"):
        inventory([pages[0], pages[0]], POLICY["repository"])


def test_unconfigured_monitor_does_not_create_state_or_notify(tmp_path):
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps([{"total_count": 0, "artifacts": []}]))
    result = subprocess.run([sys.executable, str(ROOT / "scripts/ci_storage_monitor.py"),
        "--inventory", str(path), "--repository", POLICY["repository"], "--output", str(tmp_path / "report.json")],
        env={**os.environ, "CI_STORAGE_CONFIG_JSON": "", "CI_STORAGE_MONITOR_CONFIG_JSON": ""},
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["status"] == "BLOCKED_UNCONFIGURED"
    assert report["notification_sent"] is False
    assert report["notification_status"] == "DISABLED_UNCONFIGURED"
    assert report["artifacts_deleted"] == 0
    assert report["measurement"]["account_quota_status"] == "UNKNOWN_NOT_MEASURED"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["inventory.json", "report.json"]


def test_real_subprocesses_persist_and_suppress_repeated_below_events(tmp_path):
    _, config = fake_adapter(tmp_path)
    path = tmp_path / "inventory.json"
    reports = []
    for index, size in enumerate((101, 99, 98)):
        path.write_text(json.dumps([{"total_count": 1, "artifacts": [
            {"id": 1, "size_in_bytes": size, "expired": False}]}]))
        output = tmp_path / f"report-{index}.json"
        result = subprocess.run([sys.executable, str(ROOT / "scripts/ci_storage_monitor.py"),
            "--inventory", str(path), "--repository", POLICY["repository"], "--output", str(output)],
            env={**os.environ, "CI_STORAGE_CONFIG_JSON": json.dumps(config),
                 "CI_STORAGE_MONITOR_CONFIG_JSON": json.dumps(POLICY)}, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        reports.append(json.loads(output.read_text()))
    assert [r["status"] for r in reports] == ["PERSISTED"] * 3
    assert reports[0]["transition_event"] is None
    assert reports[1]["transition_event"]["kind"] == "CROSSED_BELOW"
    assert reports[2]["transition_event"] is None
    assert reports[2]["pending_event_count"] == 1
    assert all(r["notification_sent"] is False for r in reports)


def test_monitor_workflow_has_no_schedule_notification_or_deletion():
    text = (ROOT / ".github/workflows/storage-monitor.yml").read_text()
    doc = yaml.safe_load(text)
    trigger = doc.get("on", doc.get(True))
    assert "schedule" not in trigger
    assert doc["permissions"] == {"contents": "read", "actions": "read"}
    assert doc["concurrency"]["cancel-in-progress"] is False
    assert "--paginate --slurp" in text
    assert "continue-on-error" not in text
    assert "DELETE" not in text
    assert "send-mail" not in text
