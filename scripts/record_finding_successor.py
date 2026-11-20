#!/usr/bin/env python3
"""Run full local acceptance and append a version-bound finding successor.

Historical packets and execution receipts are checked as retained bytes, never
rehashed in place or claimed to have tested today's source. The output directory
must be new and is excluded from its own source manifest to avoid hash cycles.
This records local software evidence only, not hosted delivery or qualification.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.finding_evidence import FIELDS, validate_packet

CACHE_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv"}


def now():
    return datetime.now(timezone.utc).isoformat()


def file_ref(root, path):
    path = Path(path)
    relative = path.relative_to(root)
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("EVIDENCE_PATH_ESCAPE")
    return {"path": relative.as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def checked_ref(root, ref):
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise ValueError("EXACT_FILE_REFERENCE_REQUIRED")
    relative = Path(ref["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("EVIDENCE_PATH_ESCAPE")
    if file_ref(root, root / relative) != ref:
        raise ValueError("HISTORICAL_EVIDENCE_HASH_MISMATCH:" + ref["path"])


def source_manifest(root, output):
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others"],
        cwd=root).decode().split("\0")
    # Include ignored inputs too; only declared caches/environments/output are excluded.
    return [file_ref(root, root / name) for name in sorted(set(filter(None, paths)))
            if not (root / name).is_relative_to(output)
            and not CACHE_PARTS.intersection(Path(name).parts)]


def environment_fingerprint(root, python):
    command = """import importlib.metadata, json, platform, sys
print(json.dumps({
    "python_version": sys.version,
    "executable": sys.executable,
    "implementation": platform.python_implementation(),
    "platform": platform.platform(),
    "installed_distributions": sorted(
        [{"name": d.metadata["Name"], "version": d.version}
         for d in importlib.metadata.distributions()],
        key=lambda d: (d["name"].lower(), d["version"]))
}, sort_keys=True))
"""
    value = json.loads(subprocess.check_output([python, "-c", command], cwd=root,
                                               text=True))
    value["requirements"] = [file_ref(root, path)
                             for path in sorted(root.glob("requirements*.txt"))]
    value["pin_conformance"] = "NOT_ASSESSED"
    value["test_environment"] = {key: os.environ.get(key) for key in
        ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONPATH", "PYTHONHOME")}
    return value


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def run_command(args, root, log):
    # Children never hold the final evidence-log descriptor. Retain their
    # complete combined output only after the pipe reaches EOF and they exit.
    completed = subprocess.run(args, cwd=root, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, check=False)
    with log.open("ab") as stream:
        stream.write(("\n$ " + shlex.join(args) + "\n").encode())
        stream.write(completed.stdout)
        stream.flush()
        os.fsync(stream.fileno())
    return completed.returncode


def run_unittest_receipt(path):
    """Execute the imported research suite and record actual runner counts."""
    import unittest
    started = now()
    suite = unittest.defaultTestLoader.discover("research", pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    counts = {"tests": result.testsRun, "failures": len(result.failures),
              "errors": len(result.errors), "skipped": len(result.skipped),
              "expected_failures": len(result.expectedFailures),
              "unexpected_successes": len(result.unexpectedSuccesses)}
    passed = counts["tests"] > 0 and not any(v for k, v in counts.items() if k != "tests")
    write_json(Path(path), {"schema": "research-unittest-execution-v1",
               "start_directory": "research", "pattern": "test_*.py",
               "executed_at_utc": started, "completed_at_utc": now(),
               "counts": counts, "exit_code": 0 if passed else 1,
               "predictive_validation_granted": False})
    return 0 if passed else 1


def run_pytest_receipt(path, junit):
    import pytest
    started = now()
    class Counts:
        deselected = 0
        collected = 0
        def pytest_deselected(self, items):
            self.deselected += len(items)
        def pytest_collection_finish(self, session):
            self.collected = len(session.items)
    plugin = Counts()
    result = int(pytest.main(["tests", "research/tests",
        "research/cfb_binary_isotonic_proposal/test_binary_isotonic_repair.py",
        "-q", "-o", "addopts=", "--junitxml=" + str(junit)], plugins=[plugin]))
    passed = result == 0 and plugin.collected > 0 and plugin.deselected == 0
    write_json(Path(path), {"schema": "pytest-acceptance-execution-v1",
        "executed_at_utc": started, "completed_at_utc": now(),
        "pytest_exit_code": result, "collected": plugin.collected,
        "deselected": plugin.deselected, "exit_code": 0 if passed else 1})
    return 0 if passed else 1


def junit_counts(path):
    document = ET.parse(path).getroot()
    if document.tag not in {"testsuites", "testsuite"}:
        raise ValueError("JUNIT_SCHEMA_INVALID")
    cases = list(document.iter("testcase"))
    if not cases or any(list(document.iter(tag)) for tag in ("failure", "error", "skipped")):
        raise ValueError("JUNIT_NOT_COMPLETE_PASS")
    fields = {"tests": "testcase", "failures": "failure", "errors": "error", "skipped": "skipped"}
    for suite in document.iter():
        if suite.tag not in {"testsuites", "testsuite"}:
            continue
        for field, tag in fields.items():
            value = suite.get(field)
            if value is None and suite.tag == "testsuites":
                continue
            if value is None or not re.fullmatch(r"0|[1-9][0-9]*", value):
                raise ValueError("JUNIT_COUNTER_INVALID:" + field)
            if int(value) != len(list(suite.iter(tag))):
                raise ValueError("JUNIT_COUNTER_MISMATCH:" + field)
    return {"tests": len(cases), "failures": 0, "errors": 0, "skipped": 0}


def research_counts(path):
    value = json.loads(path.read_text())
    if (value.get("schema") != "research-unittest-execution-v1"
            or value.get("start_directory") != "research" or value.get("pattern") != "test_*.py"):
        raise ValueError("RESEARCH_TEST_RECEIPT_INVALID")
    counts = value.get("counts", {})
    fields = {"tests", "failures", "errors", "skipped", "expected_failures", "unexpected_successes"}
    if (set(counts) != fields or any(type(v) is not int or v < 0 for v in counts.values())
            or counts["tests"] == 0 or any(v for k, v in counts.items() if k != "tests")
            or type(value.get("exit_code")) is not int or value["exit_code"] != 0):
        raise ValueError("RESEARCH_TESTS_NOT_COMPLETE_PASS")
    return counts


def record_successor(root, parent, expected_parent_sha256, output, *,
                     python=sys.executable, runner=run_command):
    root = Path(root).resolve()
    if os.environ.get("PYTEST_ADDOPTS", "").strip():
        raise ValueError("PYTEST_ADDOPTS_MUST_BE_EMPTY")
    parent = Path(parent)
    output = Path(output)
    if not parent.is_absolute():
        parent = root / parent
    if not output.is_absolute():
        output = root / output
    if (not output.resolve().is_relative_to(root) or output == root
            or output.exists() or output.is_symlink()):
        raise ValueError("NEW_REPOSITORY_OUTPUT_DIRECTORY_REQUIRED")
    parent_ref = file_ref(root, parent)
    if parent_ref["sha256"] != expected_parent_sha256:
        raise ValueError("PARENT_PACKET_HASH_MISMATCH")
    rows = json.loads(parent.read_text())
    if not isinstance(rows, list) or not rows:
        raise ValueError("NONEMPTY_PARENT_PACKET_REQUIRED")
    ids = [row.get("finding_id") for row in rows]
    if len(ids) != len(set(ids)) or not all(isinstance(x, str) and x for x in ids):
        raise ValueError("UNIQUE_PARENT_FINDINGS_REQUIRED")
    historical = {parent_ref["path"]: parent_ref}
    def historical_row(row, packet_ref, visiting):
        key = (packet_ref["path"], packet_ref["sha256"], row["finding_id"])
        if key in visiting:
            raise ValueError("HISTORICAL_SUPERSEDES_CYCLE")
        if row.get("status") != "verified_implementation":
            raise ValueError("PARENT_SCOPE_MUST_BE_VERIFIED_IMPLEMENTATION")
        ref = row["acceptance_test"]["execution_receipt"]
        checked_ref(root, ref)
        historical[ref["path"]] = ref
        receipt = json.loads((root / ref["path"]).read_text())
        for field in ("log", "junit"):
            if field in receipt:
                checked_ref(root, receipt[field])
                historical[receipt[field]["path"]] = receipt[field]
        previous = row.get("supersedes")
        if previous is not None:
            if not isinstance(previous, dict) or set(previous) != {"path", "sha256", "finding_id"}:
                raise ValueError("EXACT_SUPERSEDES_REFERENCE_REQUIRED")
            ref = {k: previous[k] for k in ("path", "sha256")}
            checked_ref(root, ref)
            historical[ref["path"]] = ref
            document = json.loads((root / ref["path"]).read_text())
            candidates = document if isinstance(document, list) else [document]
            matches = [p for p in candidates if p.get("finding_id") == row["finding_id"]]
            if previous["finding_id"] != row["finding_id"] or len(matches) != 1:
                raise ValueError("HISTORICAL_FINDING_IDENTITY_MISMATCH")
            historical_row(matches[0], ref, visiting | {key})
    for row in rows:
        historical_row(row, parent_ref, set())

    output.mkdir(parents=True, exist_ok=False)
    before = source_manifest(root, output)
    write_json(output / "sources-before.json", before)
    environment_before = environment_fingerprint(root, python)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root,
                                     text=True).strip()
    junit = output / "tests.xml"
    pytest_receipt = output / "pytest-tests.json"
    research_receipt = output / "research-tests.json"
    commands = [[python, str(root / "scripts/record_finding_successor.py"),
                 "--pytest-receipt", str(pytest_receipt), str(junit)],
                [python, str(root / "scripts/record_finding_successor.py"),
                 "--unittest-receipt", str(research_receipt)]]
    log = output / "acceptance.log"
    log.touch(exist_ok=False)
    started = now()
    results = []
    for command in commands:
        result = runner(command, root, log)
        results.append(result)
        if result:
            break
    after = source_manifest(root, output)
    write_json(output / "sources-after.json", after)
    environment_after = environment_fingerprint(root, python)
    failure = None
    pytest_counts, unittest_counts = None, None
    if any(results) or len(results) != len(commands):
        failure = "ACCEPTANCE_TEST_FAILED"
    elif before != after:
        failure = "SOURCE_CHANGED_DURING_ACCEPTANCE"
    elif environment_before != environment_after:
        failure = "DEPENDENCY_ENVIRONMENT_CHANGED_DURING_ACCEPTANCE"
    elif not junit.is_file():
        failure = "JUNIT_EVIDENCE_MISSING"
    elif not research_receipt.is_file():
        failure = "RESEARCH_TEST_RECEIPT_MISSING"
    elif not pytest_receipt.is_file():
        failure = "PYTEST_EXECUTION_RECEIPT_MISSING"
    else:
        try:
            pytest_counts = junit_counts(junit)
            unittest_counts = research_counts(research_receipt)
            execution = json.loads(pytest_receipt.read_text())
            if (execution.get("schema") != "pytest-acceptance-execution-v1"
                    or any(type(execution.get(k)) is not int for k in
                           ("collected", "deselected", "exit_code", "pytest_exit_code"))
                    or execution["collected"] != pytest_counts["tests"]
                    or any(execution[k] != 0 for k in ("deselected", "exit_code", "pytest_exit_code"))):
                raise ValueError("PYTEST_COLLECTION_NOT_COMPLETE_PASS")
        except (ValueError, TypeError, AttributeError, ET.ParseError) as exc:
            failure = str(exc)
    # Recheck retained history before writing any success receipt. Historical
    # sources are intentionally not compared with today's repaired sources.
    try:
        for ref in historical.values():
            checked_ref(root, ref)
    except (ValueError, OSError) as exc:
        failure = str(exc)
    receipt = {"schema": "acceptance-execution-v1", "command": " && ".join(
                   shlex.join(command) for command in commands),
               "commands": commands, "command_exit_codes": results,
               "executed_at_utc": started, "completed_at_utc": now(),
               "source_commit": commit, "sources": before,
               "source_manifest_scope": "ALL_REPOSITORY_FILES_EXCEPT_DECLARED_EXCLUSIONS",
               "source_manifest_exclusions": {"directory_parts": sorted(CACHE_PARTS),
                                              "output_directory": str(output.relative_to(root))},
               "source_manifest_before": file_ref(root, output / "sources-before.json"),
               "source_manifest_after": file_ref(root, output / "sources-after.json"),
               "environment": environment_before, "environment_after": environment_after,
               "pytest_counts": pytest_counts, "research_unittest_counts": unittest_counts,
               "historical_evidence": list(historical.values()),
               "log": file_ref(root, log), "exit_code": 1 if failure else 0,
               "failure": failure, "scope": "LOCAL_SOFTWARE_ACCEPTANCE_ONLY",
               "successor_delivery_status": "PENDING",
               "hosted_verification": "PENDING", "durable_archive_verified": False,
               "predictive_validation_granted": False, "model_promotion_granted": False,
               "publication_allowed": False, "action_authority": False,
               "wagering_authority": "OFF"}
    if junit.is_file():
        receipt["junit"] = file_ref(root, junit)
    if research_receipt.is_file():
        receipt["research_unittest_receipt"] = file_ref(root, research_receipt)
    if pytest_receipt.is_file():
        receipt["pytest_execution_receipt"] = file_ref(root, pytest_receipt)
    write_json(output / "acceptance.json", receipt)
    if failure:
        raise ValueError(failure)
    receipt_ref = file_ref(root, output / "acceptance.json")
    # Historical extra fields remain preserved in the parent; they cannot grant
    # authority to the new software-only successor.
    packet_path = output / "finding-evidence.json"
    delivery_path = output / "delivery.json"
    try:
        successors = [{k: deepcopy(row[k]) for k in FIELDS | {"schema", "owner", "status"}}
                      for row in rows]
        for row in successors:
            row["evidence"] = [file_ref(root, root / ref["path"]) for ref in row["evidence"]]
            if parent_ref not in row["evidence"]:
                row["evidence"].append(parent_ref)
            row["evidence"].extend(list(historical.values()))
            row["evidence"].extend([receipt["junit"], receipt["research_unittest_receipt"],
                                    receipt["pytest_execution_receipt"]])
            row["supersedes"] = dict(parent_ref, finding_id=row["finding_id"])
            row["acceptance_test"] = {"command": receipt["command"],
                                      "execution_receipt": receipt_ref}
            row["delivery"] = {"stage": "Tested"}
            row.update(predictive_validation_granted=False, model_promotion_granted=False,
                       publication_allowed=False, action_authority=False, wagering_authority="OFF")
            row["scope"] += " Re-exercised against the retained current source manifest; local software acceptance only, hosted delivery pending."
            validate_packet(row, root=root)
        write_json(packet_path, successors)
    except Exception as exc:
        write_json(delivery_path, {
            "schema": "finding-successor-delivery-v1", "status": "FAILED",
            "failure": type(exc).__name__ + ":" + str(exc),
            "recorded_at_utc": now(), "acceptance_receipt": receipt_ref,
            "packet_created": packet_path.exists(), "evidence_delivery_complete": False,
            "predictive_validation_granted": False, "publication_allowed": False,
            "action_authority": False, "wagering_authority": "OFF"})
        raise
    write_json(delivery_path, {
        "schema": "finding-successor-delivery-v1", "status": "LOCAL_COMPLETE",
        "recorded_at_utc": now(), "acceptance_receipt": receipt_ref,
        "packet": file_ref(root, packet_path), "evidence_delivery_complete": True,
        "hosted_verification": "PENDING", "durable_archive_verified": False,
        "predictive_validation_granted": False, "publication_allowed": False,
        "action_authority": False, "wagering_authority": "OFF"})
    return {"packet": file_ref(root, packet_path), "receipt": receipt_ref,
            "delivery": file_ref(root, delivery_path),
            "findings": len(successors), "hosted_verification": "PENDING",
            "predictive_validation_granted": False, "publication_allowed": False,
            "wagering_authority": "OFF"}


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--unittest-receipt":
        raise SystemExit(run_unittest_receipt(sys.argv[2]))
    if len(sys.argv) == 4 and sys.argv[1] == "--pytest-receipt":
        if os.environ.get("PYTEST_ADDOPTS", "").strip():
            raise ValueError("PYTEST_ADDOPTS_MUST_BE_EMPTY")
        raise SystemExit(run_pytest_receipt(sys.argv[2], sys.argv[3]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--expected-parent-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(record_successor(ROOT, args.parent, args.expected_parent_sha256,
                                      args.output), indent=2))


if __name__ == "__main__":
    main()
