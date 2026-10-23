"""Operational bootstrap and current-attempt guards; synthetic fixtures only."""
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from scripts.canonical_grading_preflight import assess, AWAITING, REGISTRY_SCHEMA

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/canonical_grading_preflight.py"


def run(root, name, *extra):
    report = root / "operations" / (name + ".json")
    result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), "--report", str(report),
                             *extra], capture_output=True, text=True)
    return result, json.loads(report.read_text()) if report.exists() else None


def registry(root):
    root.mkdir(exist_ok=True)
    (root / "registry.json").write_text(json.dumps({"schema": REGISTRY_SCHEMA,
        "forecasts": {"TEST_ONLY": {"event_id": "TEST_ONLY_NOT_A_REAL_FORECAST"}}}))


def test_bootstrap_is_explicit_no_work_and_never_creates_registry_or_grades(tmp_path):
    root = tmp_path / "canonical"
    first, report = run(root, "one", "--github-output", str(tmp_path / "output"))
    assert first.returncode == 0 and report["status"] == AWAITING
    assert report["registered_count"] == 0 and report["settlement_performed"] is False
    assert (tmp_path / "output").read_text() == "state=" + AWAITING + "\n"
    before = (root / "operations/one.json").read_bytes()
    again, second = run(root, "two")
    assert again.returncode == 0 and second["status"] == AWAITING
    assert (root / "operations/one.json").read_bytes() == before
    assert sorted(p.name for p in root.iterdir()) == ["operations"]
    assert not list(root.rglob("registry.json")) and not list(root.rglob("*ledger*"))


@pytest.mark.parametrize("relative", ["cards/frozen.json", "draws/frozen.npy", "selections/frozen.json",
    "receipts/registered.json", "ledger.jsonl", "selection_ledger.jsonl", "summary.json", "cards/not-a-real-lock.lock"])
def test_missing_registry_with_prior_evidence_is_integrity_failure(tmp_path, relative):
    path = tmp_path / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text("{}")
    before = path.read_bytes()
    result, report = run(tmp_path, "failure")
    assert result.returncode == 2 and report["status"] == "INTEGRITY_FAILURE"
    assert report["reason"] == "REGISTRY_MISSING_WITH_PRIOR_EVIDENCE"
    assert relative in report["registration_evidence"]
    assert path.read_bytes() == before and not (tmp_path / "registry.json").exists()


def test_failed_registration_attempt_and_lock_are_not_successful_registration(tmp_path):
    path = tmp_path / "attempts/rejected.json"; path.parent.mkdir()
    path.write_text(json.dumps({"status": "BLOCKED", "reason": "UPLOAD_FAILED", "action_authority": False}))
    (tmp_path / "registry.json.lock").write_text("")
    assert assess(tmp_path)["status"] == AWAITING
    path.write_text(json.dumps({"status": "REGISTERED", "added": ["TEST_ONLY"]}))
    assert assess(tmp_path)["status"] == "INTEGRITY_FAILURE"


def test_operational_ready_receipt_remembers_lost_registry(tmp_path):
    registry(tmp_path)
    ready, report = run(tmp_path, "ready")
    assert ready.returncode == 0 and report["status"] == "READY_TO_ACQUIRE"
    (tmp_path / "registry.json").unlink()
    assert assess(tmp_path)["status"] == "INTEGRITY_FAILURE"


@pytest.mark.parametrize("value", ["not-json", '{"schema":"x","forecasts":{}}',
    '{"schema":"canonical.prospective_research.v1","forecasts":{}}',
    '{"schema":"canonical.prospective_research.v1","forecasts":{"x":null}}'])
def test_invalid_or_dummy_registry_cannot_be_treated_as_bootstrap(tmp_path, value):
    path = tmp_path / "registry.json"; path.write_text(value)
    result, report = run(tmp_path, "failure")
    assert result.returncode == 2 and report["status"] == "INTEGRITY_FAILURE"
    assert path.read_text() == value


def test_only_current_attempt_result_allows_grading(tmp_path):
    registry(tmp_path)
    old = tmp_path / "results/100-1/results.json"; old.parent.mkdir(parents=True); old.write_text("[]")
    result, report = run(tmp_path, "missing-current", "--check-current-results", "101", "2")
    assert result.returncode == 2 and report["reason"] == "CURRENT_ATTEMPT_RESULTS_MISSING"
    current = tmp_path / "results/101-2/results.json"; current.parent.mkdir(parents=True); current.write_text("[]")
    result, report = run(tmp_path, "current", "--check-current-results", "101", "2")
    assert result.returncode == 0 and report["status"] == "CURRENT_ATTEMPT_RESULTS_READY"
    assert report["current_results_path"] == str(current) and not report["settlement_performed"]
    current.write_text('{"error":"capture failed"}')
    assert assess(tmp_path, current_attempt=("101", "2"))["status"] == "INTEGRITY_FAILURE"


@pytest.mark.parametrize("linked_component", ["results_root", "attempt_directory", "result_file"])
def test_current_attempt_cannot_follow_symlinks_to_prior_results(tmp_path, linked_component):
    root = tmp_path / "canonical"; registry(root)
    old = tmp_path / "old-results/100-1/results.json"; old.parent.mkdir(parents=True); old.write_text("[]")
    if linked_component == "results_root":
        (old.parent.parent / "101-2").mkdir()
        (old.parent.parent / "101-2/results.json").write_text("[]")
        (root / "results").symlink_to(old.parent.parent, target_is_directory=True)
    else:
        (root / "results").mkdir()
        if linked_component == "attempt_directory":
            (root / "results/101-2").symlink_to(old.parent, target_is_directory=True)
        else:
            (root / "results/101-2").mkdir()
            (root / "results/101-2/results.json").symlink_to(old)
    result = assess(root, current_attempt=("101", "2"))
    assert result["status"] == "INTEGRITY_FAILURE"
    assert result["reason"] == "CURRENT_ATTEMPT_RESULTS_SYMLINK_REFUSED"


def test_workflow_has_separate_bootstrap_acquisition_current_results_and_failure_gates():
    text = (ROOT / ".github/workflows/canonical-research-grading.yml").read_text()
    workflow = yaml.safe_load(text)
    steps = {s.get("id"): s for s in workflow["jobs"]["grade"]["steps"] if s.get("id")}
    assert "canonical_grading_preflight.py" in steps["preflight"]["run"]
    assert "steps.preflight.outputs.state == 'READY_TO_ACQUIRE'" in steps["acquire"]["if"]
    assert '--check-current-results "$GITHUB_RUN_ID" "$GITHUB_RUN_ATTEMPT"' in steps["current_results"]["run"]
    assert "steps.current_results.outputs.state == 'CURRENT_ATTEMPT_RESULTS_READY'" in steps["grade"]["if"]
    assert "hashFiles(" not in text
    last = workflow["jobs"]["grade"]["steps"][-1]
    for step in ("preflight", "acquire", "current_results", "grade"):
        assert f"steps.{step}.outcome == 'failure'" in last["if"]
    assert "steps.preflight.outputs.state == 'READY_TO_ACQUIRE' && steps.grade.outcome == 'skipped'" in last["if"]
    assert "registry.json" not in steps["preflight"]["run"]


def test_report_replay_cannot_overwrite_existing_report(tmp_path):
    first, _ = run(tmp_path, "one")
    before = (tmp_path / "operations/one.json").read_bytes()
    second, _ = run(tmp_path, "one")
    assert first.returncode == 0 and second.returncode != 0
    assert (tmp_path / "operations/one.json").read_bytes() == before
