"""Independent operational follow-up tests; all state here is synthetic.

Assertions were chosen before reading the implementation owner's focused tests.
No network, hosted execution, forecast registration, or settlement is performed.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

from scripts.canonical_grading_preflight import AWAITING, SCHEMA, assess


REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github/workflows/canonical-research-grading.yml"


def write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))
    return path


def registry(root):
    # Preflight only checks structure. This is not a valid forecast receipt.
    return write(root, "registry.json", {
        "schema": "canonical.prospective_research.v1",
        "forecasts": {"synthetic": {"event_id": "not-a-real-event"}},
    })


def byte_snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("history", ["none", "empty", "directories", "lock", "awaiting", "failed_attempt"])
def test_clean_first_run_reports_waiting_without_state_mutation(tmp_path, history):
    root = tmp_path / "canonical"
    if history != "none":
        root.mkdir()
    if history == "directories":
        for name in ("cards", "draws", "selections", "operations"):
            (root / name).mkdir()
    if history == "lock":
        write(root, "registry.json.lock", "")
    if history == "awaiting":
        write(root, "operations/earlier.json", {
            "schema": SCHEMA, "status": AWAITING, "registered_count": 0,
            "registration_evidence": [], "registry_present": False,
            "settlement_performed": False,
        })
    if history == "failed_attempt":
        write(root, "attempts/failed-registration.json", {
            "status": "BLOCKED", "reason": "UPLOAD_BINDING_UNAVAILABLE",
            "action_authority": False,
        })
    before = byte_snapshot(root)
    result = assess(root)
    assert result["status"] == AWAITING
    assert result["registered_count"] == 0
    assert result["registration_evidence"] == []
    assert result["settlement_performed"] is False
    assert result["publication_allowed"] is False
    assert result["action_authority"] is False
    assert result["wagering_status"] == "OFF"
    assert byte_snapshot(root) == before
    assert not (root / "registry.json").exists()
    if history == "none":
        assert not root.exists()


@pytest.mark.parametrize("name", [
    "cards/frozen.json", "draws/frozen.npy", "selections/frozen.json",
    "ledger.jsonl", "selection_ledger.jsonl", "summary.json",
    "attempts/prior-registration.json",
])
def test_missing_registry_with_any_prior_canonical_evidence_fails(tmp_path, name):
    write(tmp_path, name, '{"status":"REGISTERED"}')
    before = byte_snapshot(tmp_path)
    result = assess(tmp_path)
    assert result["status"] == "INTEGRITY_FAILURE"
    assert result["reason"] == "REGISTRY_MISSING_WITH_PRIOR_EVIDENCE"
    assert name in result["registration_evidence"]
    assert byte_snapshot(tmp_path) == before


@pytest.mark.parametrize("raw", [
    "[]", "{", "{}",
    '{"schema":"canonical.prospective_research.v1","forecasts":{}}',
    '{"schema":"canonical.prospective_research.v1","forecasts":{"x":{}}}',
    '{"schema":"canonical.prospective_research.v1","forecasts":{"x":{"n":NaN}}}',
    '{"schema":"canonical.prospective_research.v1","forecasts":{"x":{"a":1,"a":2}}}',
])
def test_malformed_existing_registry_never_becomes_first_run(tmp_path, raw):
    write(tmp_path, "registry.json", raw)
    assert assess(tmp_path)["status"] == "INTEGRITY_FAILURE"


def test_existing_nonempty_registry_is_only_ready_for_acquisition(tmp_path):
    registry(tmp_path)
    result = assess(tmp_path)
    assert result["status"] == "READY_TO_ACQUIRE"
    assert result["registered_count"] == 1
    assert result["settlement_performed"] is False
    assert result["action_authority"] is False


def test_old_attempt_does_not_satisfy_current_attempt_and_check_is_read_only(tmp_path):
    registry(tmp_path)
    write(tmp_path, "results/321-1/results.json", [])
    before = byte_snapshot(tmp_path)
    rejected = assess(tmp_path, current_attempt=("321", "2"))
    assert rejected["status"] == "INTEGRITY_FAILURE"
    assert byte_snapshot(tmp_path) == before
    current = write(tmp_path, "results/321-2/results.json", [])
    accepted = assess(tmp_path, current_attempt=("321", "2"))
    assert accepted["status"] == "CURRENT_ATTEMPT_RESULTS_READY"
    assert accepted["current_results_sha256"] == hashlib.sha256(current.read_bytes()).hexdigest()


@pytest.mark.parametrize("raw", ["{}", "[", '[{"x":NaN}]', '[{"x":1,"x":2}]'])
def test_current_result_must_be_finite_unambiguous_json_list(tmp_path, raw):
    registry(tmp_path)
    write(tmp_path, "results/321-2/results.json", raw)
    assert assess(tmp_path, current_attempt=("321", "2"))["status"] == "INTEGRITY_FAILURE"


@pytest.mark.parametrize("link_location", ["attempt", "results", "leaf"])
def test_old_results_cannot_be_smuggled_through_symlink_ancestors(tmp_path, link_location):
    root = tmp_path / "canonical"
    registry(root)
    old = write(tmp_path, "old-attempt/results.json", [])
    if link_location == "attempt":
        (root / "results").mkdir()
        (root / "results/321-2").symlink_to(old.parent, target_is_directory=True)
    elif link_location == "results":
        external = tmp_path / "external-results"
        write(external, "321-2/results.json", [])
        (root / "results").symlink_to(external, target_is_directory=True)
    else:
        (root / "results/321-2").mkdir(parents=True)
        (root / "results/321-2/results.json").symlink_to(old)
    assert assess(root, current_attempt=("321", "2"))["status"] == "INTEGRITY_FAILURE"


def workflow_step(identifier):
    for block in re.split(r"\n      - ", WORKFLOW.read_text()):
        if re.search(r"\n        id: " + re.escape(identifier) + r"\n", block):
            return block
    raise AssertionError("Workflow step missing: " + identifier)


def evaluate_condition(expression, *, state, outcomes):
    expression = re.sub(r"steps\.preflight\.outputs\.state", repr(state), expression)
    expression = re.sub(r"steps\.(\w+)\.outcome", lambda m: repr(outcomes[m[1]]), expression)
    expression = expression.replace("&&", " and ").replace("||", " or ")
    node = ast.parse(expression.strip(), mode="eval").body

    def evaluate(n):
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.BoolOp):
            values = [evaluate(v) for v in n.values]
            return all(values) if isinstance(n.op, ast.And) else any(values)
        if isinstance(n, ast.Compare) and len(n.ops) == 1 and isinstance(n.ops[0], ast.Eq):
            return evaluate(n.left) == evaluate(n.comparators[0])
        raise AssertionError("Unexpected workflow condition syntax")
    return evaluate(node)


@pytest.mark.parametrize("state,preflight,acquire,current_results,grade,should_fail", [
    (AWAITING, "success", "skipped", "skipped", "skipped", False),
    ("INTEGRITY_FAILURE", "failure", "skipped", "skipped", "skipped", True),
    ("READY_TO_ACQUIRE", "success", "success", "success", "success", False),
    ("READY_TO_ACQUIRE", "success", "failure", "success", "success", True),
    ("READY_TO_ACQUIRE", "success", "success", "success", "failure", True),
    ("READY_TO_ACQUIRE", "success", "success", "failure", "skipped", True),
    ("READY_TO_ACQUIRE", "success", "success", "success", "skipped", True),
])
def test_actual_workflow_failure_expression_preserves_errors(
        state, preflight, acquire, current_results, grade, should_fail):
    workflow = WORKFLOW.read_text()
    tail = workflow.split("- name: Fail incomplete acquisition or rejected grades", 1)[1]
    expression = re.search(r"if: \$\{\{(.*?)\}\}", tail)[1]
    assert evaluate_condition(expression, state=state, outcomes={
        "preflight": preflight, "acquire": acquire,
        "current_results": current_results, "grade": grade,
    }) is should_fail


def test_workflow_gates_grade_on_exact_run_and_attempt():
    assert "steps.preflight.outputs.state == 'READY_TO_ACQUIRE'" in workflow_step("acquire")
    assert '--check-current-results "$GITHUB_RUN_ID" "$GITHUB_RUN_ATTEMPT"' in workflow_step("current_results")
    grade = workflow_step("grade")
    assert "steps.current_results.outputs.state == 'CURRENT_ATTEMPT_RESULTS_READY'" in grade
    assert '--results "data/grading/canonical/results/$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT/results.json"' in grade
    assert "hashFiles" not in grade


def call_cli(root, report, github_output):
    return subprocess.run([
        sys.executable, str(REPO / "scripts/canonical_grading_preflight.py"),
        "--root", str(root), "--report", str(report),
        "--github-output", str(github_output),
    ], capture_output=True, text=True, cwd=REPO)


def test_cli_repeated_clean_first_run_writes_only_explicit_status(tmp_path):
    root = tmp_path / "canonical"
    output = tmp_path / "github-output"
    for attempt in ("1", "2"):
        report = root / "operations" / ("preflight-321-" + attempt + ".json")
        process = call_cli(root, report, output)
        assert process.returncode == 0, process.stderr
        document = json.loads(report.read_text())
        assert document["status"] == AWAITING
        assert document["settlement_performed"] is False
    assert output.read_text().splitlines() == ["state=" + AWAITING] * 2
    assert set(byte_snapshot(root)) == {
        "operations/preflight-321-1.json", "operations/preflight-321-2.json",
    }


def test_cli_missing_registry_with_frozen_draw_fails_without_touching_draw(tmp_path):
    root = tmp_path / "canonical"
    draw = write(root, "draws/frozen.npy", "synthetic-bytes")
    report = root / "operations/preflight-321-1.json"
    process = call_cli(root, report, tmp_path / "github-output")
    assert process.returncode != 0
    assert json.loads(report.read_text())["status"] == "INTEGRITY_FAILURE"
    assert draw.read_text() == "synthetic-bytes"
    assert not (root / "registry.json").exists()
