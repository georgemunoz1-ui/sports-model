"""Synthetic local receipt fixtures; no model or hosted acceptance claims."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from research.finding_evidence import validate_packet
from scripts import record_finding_successor as successor
from scripts.record_finding_successor import file_ref, record_successor


def fixture(root):
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-c", "user.name=Fixture", "-c",
                    "user.email=fixture@example.invalid", "commit", "-q",
                    "--allow-empty", "-m", "Synthetic fixture"], cwd=root, check=True)
    (root / "source.py").write_text("value = 1\n")
    (root / "old.log").write_text("Synthetic fixture, not an execution claim\n")
    old_receipt = {"schema": "acceptance-execution-v1", "command": "synthetic",
                   "executed_at_utc": "2026-10-24T00:00:00Z", "exit_code": 0,
                   "sources": [file_ref(root, root / "source.py")],
                   "log": file_ref(root, root / "old.log")}
    (root / "old-receipt.json").write_text(json.dumps(old_receipt))
    packet = {"schema": "finding-evidence-v1", "finding_id": "TEST-01",
              "observed": "Incorrect value", "expected": "Correct value",
              "scope": "Synthetic software contract", "classification": "implementation_bug",
              "change": "Correct value", "remaining_limitation": "Not predictive evidence",
              "publication_impact": "OFF", "owner": "fixture", "status": "verified_implementation",
              "delivery": {"stage": "Tested"}, "evidence": old_receipt["sources"],
              "acceptance_test": {"command": "synthetic",
                                  "execution_receipt": file_ref(root, root / "old-receipt.json")}}
    (root / "parent.json").write_text(json.dumps([packet]))
    # Today's changed source cannot reuse the old acceptance receipt.
    (root / "source.py").write_text("value = 2\n")
    return hashlib.sha256((root / "parent.json").read_bytes()).hexdigest()


def passing_runner(args, root, log):
    with log.open("a") as stream:
        stream.write("Synthetic runner fixture, not actual suite execution\n")
    if "--pytest-receipt" in args:
        Path(args[args.index("--pytest-receipt") + 1]).write_text(json.dumps({
            "schema": "pytest-acceptance-execution-v1", "collected": 1,
            "deselected": 0, "pytest_exit_code": 0, "exit_code": 0}))
        path = Path(args[args.index("--pytest-receipt") + 2])
        path.write_text('<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">'
                        '<testcase name="synthetic"/></testsuite></testsuites>')
    if "--unittest-receipt" in args:
        path = Path(args[args.index("--unittest-receipt") + 1])
        path.write_text(json.dumps({"schema": "research-unittest-execution-v1",
            "start_directory": "research", "pattern": "test_*.py", "exit_code": 0,
            "counts": {"tests": 1, "failures": 0, "errors": 0, "skipped": 0,
                       "expected_failures": 0, "unexpected_successes": 0}}))
    return 0


def record(root, sha, runner=passing_runner):
    return record_successor(root, Path("parent.json"), sha, Path("successor"), runner=runner)


def test_successor_reexecutes_current_source_and_preserves_exact_historical_bytes(tmp_path):
    sha = fixture(tmp_path)
    old_paths = ["parent.json", "old-receipt.json", "old.log"]
    old = {p: (tmp_path / p).read_bytes() for p in old_paths}
    parent = json.loads(old["parent.json"])[0]
    with pytest.raises(ValueError, match="EVIDENCE_HASH_MISMATCH"):
        validate_packet(parent, root=tmp_path)
    result = record(tmp_path, sha)
    packet = json.loads((tmp_path / result["packet"]["path"]).read_text())[0]
    assert validate_packet(packet, root=tmp_path)["packet_valid"]
    assert packet["supersedes"] == {"path": "parent.json", "sha256": sha, "finding_id": "TEST-01"}
    assert {p: (tmp_path / p).read_bytes() for p in old_paths} == old
    assert not result["predictive_validation_granted"] and not result["publication_allowed"]
    assert result["wagering_authority"] == "OFF" and result["hosted_verification"] == "PENDING"
    receipt = json.loads((tmp_path / result["receipt"]["path"]).read_text())
    assert receipt["command_exit_codes"] == [0, 0]
    assert receipt["sources"] and all(not r["path"].startswith("successor/") for r in receipt["sources"])
    assert receipt["source_manifest_before"]["sha256"] == receipt["source_manifest_after"]["sha256"]
    assert not receipt["action_authority"] and not receipt["model_promotion_granted"]
    assert receipt["environment"] == receipt["environment_after"]
    assert receipt["environment"]["python_version"]
    assert receipt["environment"]["platform"]
    assert receipt["environment"]["pin_conformance"] == "NOT_ASSESSED"
    assert any(d["name"].lower() == "pytest" for d in receipt["environment"]["installed_distributions"])
    (tmp_path / "old.log").write_text("changed after successor\n")
    with pytest.raises(ValueError, match="EVIDENCE_HASH_MISMATCH"):
        validate_packet(packet, root=tmp_path)


def test_failed_suite_never_creates_closure_packet(tmp_path):
    sha = fixture(tmp_path)
    def fail(args, root, log):
        passing_runner(args, root, log)
        return 1
    with pytest.raises(ValueError, match="ACCEPTANCE_TEST_FAILED"):
        record(tmp_path, sha, fail)
    assert not (tmp_path / "successor/finding-evidence.json").exists()
    receipt = json.loads((tmp_path / "successor/acceptance.json").read_text())
    assert receipt["exit_code"] == 1 and receipt["command_exit_codes"] == [1]


def test_source_change_during_acceptance_is_not_resealed_as_pass(tmp_path):
    sha = fixture(tmp_path)
    def mutate(args, root, log):
        result = passing_runner(args, root, log)
        if "--unittest-receipt" in args:
            (root / "source.py").write_text("value = 999\n")
        return result
    with pytest.raises(ValueError, match="SOURCE_CHANGED_DURING_ACCEPTANCE"):
        record(tmp_path, sha, mutate)
    assert not (tmp_path / "successor/finding-evidence.json").exists()


def test_dependency_drift_during_acceptance_cannot_close(tmp_path, monkeypatch):
    sha = fixture(tmp_path)
    versions = iter([{"numpy": "before"}, {"numpy": "after"}])
    monkeypatch.setattr(successor, "environment_fingerprint", lambda root, python: next(versions))
    with pytest.raises(ValueError, match="DEPENDENCY_ENVIRONMENT_CHANGED_DURING_ACCEPTANCE"):
        record(tmp_path, sha)
    assert not (tmp_path / "successor/finding-evidence.json").exists()


def test_requirements_fingerprint_retains_bytes_without_claiming_pin_conformance(tmp_path):
    fixture(tmp_path)
    requirements = tmp_path / "requirements-consolidated.txt"
    requirements.write_text("numpy==999.0.0\n")
    fingerprint = successor.environment_fingerprint(tmp_path, successor.sys.executable)
    assert fingerprint["requirements"] == [file_ref(tmp_path, requirements)]
    assert fingerprint["pin_conformance"] == "NOT_ASSESSED"


def test_historical_receipt_tampering_fails_before_creating_output(tmp_path):
    sha = fixture(tmp_path)
    (tmp_path / "old-receipt.json").write_text("{}")
    with pytest.raises(ValueError, match="HISTORICAL_EVIDENCE_HASH_MISMATCH"):
        record(tmp_path, sha)
    assert not (tmp_path / "successor").exists()


def test_parent_hash_mismatch_fails_before_any_test_execution(tmp_path):
    fixture(tmp_path)
    with pytest.raises(ValueError, match="PARENT_PACKET_HASH_MISMATCH"):
        record(tmp_path, "0" * 64)
    assert not (tmp_path / "successor").exists()


def test_successor_output_cannot_overwrite_previous_evidence(tmp_path):
    sha = fixture(tmp_path)
    record(tmp_path, sha)
    original = (tmp_path / "successor/finding-evidence.json").read_bytes()
    with pytest.raises(ValueError, match="NEW_REPOSITORY_OUTPUT_DIRECTORY_REQUIRED"):
        record(tmp_path, sha)
    assert (tmp_path / "successor/finding-evidence.json").read_bytes() == original


@pytest.mark.parametrize("case", ["missing", "skipped", "failure", "empty"])
def test_absent_or_nonpassing_junit_cannot_close(tmp_path, case):
    sha = fixture(tmp_path)
    def incomplete(args, root, log):
        result = passing_runner(args, root, log)
        if "--pytest-receipt" in args:
            path = Path(args[args.index("--pytest-receipt") + 2])
            if case == "missing":
                path.unlink()
            else:
                child = "" if case == "empty" else '<testcase name="synthetic"><' + case + '/></testcase>'
                path.write_text("<testsuite>" + child + "</testsuite>")
        return 0
    with pytest.raises(ValueError, match="JUNIT_"):
        record(tmp_path, sha, incomplete)
    assert not (tmp_path / "successor/finding-evidence.json").exists()


def test_junit_counter_disagreement_cannot_close(tmp_path):
    sha = fixture(tmp_path)
    def inconsistent(args, root, log):
        result = passing_runner(args, root, log)
        if "--pytest-receipt" in args:
            path = Path(args[args.index("--pytest-receipt") + 2])
            path.write_text('<testsuite tests="1" failures="1" errors="0" skipped="0">'
                            '<testcase name="synthetic"/></testsuite>')
        return result
    with pytest.raises(ValueError, match="JUNIT_COUNTER_MISMATCH:failures"):
        record(tmp_path, sha, inconsistent)
    assert not (tmp_path / "successor/finding-evidence.json").exists()


@pytest.mark.parametrize("field", ["tests", "failures", "errors", "skipped",
                                   "expected_failures", "unexpected_successes"])
def test_nonpassing_research_counts_cannot_close_even_with_zero_command_exit(tmp_path, field):
    sha = fixture(tmp_path)
    def inconsistent(args, root, log):
        result = passing_runner(args, root, log)
        if "--unittest-receipt" in args:
            path = Path(args[args.index("--unittest-receipt") + 1])
            value = json.loads(path.read_text())
            value["counts"][field] = 0 if field == "tests" else 1
            path.write_text(json.dumps(value))
        return result
    with pytest.raises(ValueError, match="RESEARCH_TESTS_NOT_COMPLETE_PASS"):
        record(tmp_path, sha, inconsistent)
    assert not (tmp_path / "successor/finding-evidence.json").exists()


def test_actual_unittest_skip_returns_failure_and_executed_count_receipt(tmp_path):
    research = tmp_path / "research"
    research.mkdir()
    (research / "test_skipped.py").write_text(
        "import unittest\nclass Skipped(unittest.TestCase):\n"
        "    @unittest.skip('synthetic refusal fixture')\n"
        "    def test_skip(self): pass\n")
    receipt = tmp_path / "result.json"
    result = subprocess.run([successor.sys.executable, str(Path(successor.__file__)),
                             "--unittest-receipt", str(receipt)], cwd=tmp_path,
                            text=True, capture_output=True)
    assert result.returncode == 1, result.stderr
    value = json.loads(receipt.read_text())
    assert value["counts"]["tests"] == 1 and value["counts"]["skipped"] == 1
    assert value["exit_code"] == 1 and not value["predictive_validation_granted"]


def test_pytest_selection_environment_is_refused_before_execution(tmp_path, monkeypatch):
    sha = fixture(tmp_path)
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k test_one")
    with pytest.raises(ValueError, match="PYTEST_ADDOPTS_MUST_BE_EMPTY"):
        record(tmp_path, sha)
    assert not (tmp_path / "successor").exists()


def test_ignored_executable_input_drift_is_detected(tmp_path):
    sha = fixture(tmp_path)
    (tmp_path / ".gitignore").write_text("ignored_input.py\n")
    (tmp_path / "ignored_input.py").write_text("value = 1\n")
    def mutate(args, root, log):
        result = passing_runner(args, root, log)
        (root / "ignored_input.py").write_text("value = 2\n")
        return result
    with pytest.raises(ValueError, match="SOURCE_CHANGED_DURING_ACCEPTANCE"):
        record(tmp_path, sha, mutate)
    assert not (tmp_path / "successor/finding-evidence.json").exists()


def test_historical_log_drift_records_failed_receipt(tmp_path):
    sha = fixture(tmp_path)
    (tmp_path / ".gitignore").write_text("*.log\n")
    def mutate(args, root, log):
        result = passing_runner(args, root, log)
        (root / "old.log").write_text("tampered\n")
        return result
    with pytest.raises(ValueError, match="HISTORICAL_EVIDENCE_HASH_MISMATCH:old.log"):
        record(tmp_path, sha, mutate)
    receipt = json.loads((tmp_path / "successor/acceptance.json").read_text())
    assert receipt["exit_code"] == 1 and receipt["failure"]
    assert not (tmp_path / "successor/finding-evidence.json").exists()


@pytest.mark.parametrize("defect", ["tampered", "wrong-finding"])
def test_historical_ancestor_hash_and_finding_are_verified(tmp_path, defect):
    fixture(tmp_path)
    rows = json.loads((tmp_path / "parent.json").read_text())
    old = deepcopy(rows)
    if defect == "wrong-finding":
        old[0]["finding_id"] = "DIFFERENT"
    (tmp_path / "ancestor.json").write_text(json.dumps(old))
    rows[0]["supersedes"] = dict(file_ref(tmp_path, tmp_path / "ancestor.json"), finding_id="TEST-01")
    (tmp_path / "parent.json").write_text(json.dumps(rows))
    sha = file_ref(tmp_path, tmp_path / "parent.json")["sha256"]
    if defect == "tampered":
        (tmp_path / "ancestor.json").write_text("[]")
    with pytest.raises(ValueError, match="HISTORICAL_"):
        record(tmp_path, sha)
    assert not (tmp_path / "successor").exists()


def test_parent_authority_extras_cannot_authorize_successor(tmp_path):
    fixture(tmp_path)
    rows = json.loads((tmp_path / "parent.json").read_text())
    rows[0].update(model_promotion_granted=True, wagering_authority="ON", unrelated_authority=True)
    (tmp_path / "parent.json").write_text(json.dumps(rows))
    sha = file_ref(tmp_path, tmp_path / "parent.json")["sha256"]
    result = record(tmp_path, sha)
    row = json.loads((tmp_path / result["packet"]["path"]).read_text())[0]
    assert row["model_promotion_granted"] is False and row["wagering_authority"] == "OFF"
    assert "unrelated_authority" not in row


def test_suite_level_junit_error_is_not_hidden_by_passing_case(tmp_path):
    path = tmp_path / "tests.xml"
    path.write_text('<testsuites><testsuite tests="1" failures="0" errors="1" skipped="0">'
                    '<error message="collection failure"/><testcase name="synthetic"/>'
                    '</testsuite></testsuites>')
    with pytest.raises(ValueError, match="JUNIT_NOT_COMPLETE_PASS"):
        successor.junit_counts(path)


def test_deselection_count_cannot_close_even_with_zero_exit(tmp_path):
    sha = fixture(tmp_path)
    def deselect(args, root, log):
        result = passing_runner(args, root, log)
        if "--pytest-receipt" in args:
            path = Path(args[args.index("--pytest-receipt") + 1])
            value = json.loads(path.read_text())
            value["deselected"] = 1
            path.write_text(json.dumps(value))
        return result
    with pytest.raises(ValueError, match="PYTEST_COLLECTION_NOT_COMPLETE_PASS"):
        record(tmp_path, sha, deselect)
    assert not (tmp_path / "successor/finding-evidence.json").exists()
