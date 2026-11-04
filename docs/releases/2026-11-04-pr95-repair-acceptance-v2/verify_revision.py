#!/usr/bin/env python3
"""Independent, read-only readback of the PR 95 successor acceptance packet.

Re-derives every hash referenced by the packet, receipt and delivery record
from the working tree; recounts the JUnit document; and checks that files
present at the original PR head were not modified outside the declared repair
scope. It never reruns tests and writes only its own result file. Local
software evidence only: no hosted, predictive, promotion or wagering claims.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
ORIGINAL_HEAD = "5acf5972bc448b4e5c03b65ee69ecd38033765c0"
EXPECTED_MODIFIED_ORIGINAL_PATHS = sorted([
    ".github/workflows/daily-operations-preflight.yml",
    ".github/workflows/research-overhaul.yml",
    "scripts/capture_operational_inputs.py",
])
PROTECTED = ["data/**", "models/**", "forecasts/**", "artifacts/**", "state.json",
             "AUTHORIZATIONS.md", "docs/progress.md",
             "docs/releases/2026-10-24-remaining-prs/**",
             "docs/research/overhaul_2026_10_23/**"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_ref(ref, seen, problems):
    path = ROOT / ref["path"]
    key = (ref["path"], ref["sha256"])
    if key in seen:
        return
    seen.add(key)
    if not path.is_file():
        problems.append("MISSING:" + ref["path"])
    elif sha(path) != ref["sha256"]:
        problems.append("HASH_MISMATCH:" + ref["path"])


def walk_refs(value, seen, problems):
    if isinstance(value, dict):
        if set(value) >= {"path", "sha256"} and isinstance(value.get("path"), str):
            check_ref(value, seen, problems)
        for item in value.values():
            walk_refs(item, seen, problems)
    elif isinstance(value, list):
        for item in value:
            walk_refs(item, seen, problems)


def junit(path: Path):
    doc = ET.parse(path).getroot()
    cases = list(doc.iter("testcase"))
    return {"tests": len(cases),
            "failures": len(list(doc.iter("failure"))),
            "errors": len(list(doc.iter("error"))),
            "skipped": len(list(doc.iter("skipped")))}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True)


def main() -> int:
    problems = []
    seen = set()
    receipt = json.loads((OUT / "acceptance.json").read_text())
    packet = json.loads((OUT / "finding-evidence.json").read_text())
    delivery = json.loads((OUT / "delivery.json").read_text())

    for document in (receipt, packet, delivery):
        walk_refs(document, seen, problems)
    if delivery["acceptance_receipt"]["sha256"] != sha(OUT / "acceptance.json"):
        problems.append("DELIVERY_RECEIPT_HASH_MISMATCH")
    if delivery["packet"]["sha256"] != sha(OUT / "finding-evidence.json"):
        problems.append("DELIVERY_PACKET_HASH_MISMATCH")

    counts = junit(OUT / "tests.xml")
    if counts != receipt["pytest_counts"]:
        problems.append("JUNIT_COUNT_MISMATCH")
    pytest_exec = json.loads((OUT / "pytest-tests.json").read_text())
    if pytest_exec["collected"] != counts["tests"] or pytest_exec["deselected"] or pytest_exec["exit_code"]:
        problems.append("PYTEST_EXECUTION_RECEIPT_MISMATCH")
    research = json.loads((OUT / "research-tests.json").read_text())
    if research["counts"] != receipt["research_unittest_counts"] or research["exit_code"]:
        problems.append("RESEARCH_RECEIPT_MISMATCH")
    if receipt["exit_code"] != 0 or receipt["failure"] is not None:
        problems.append("RECEIPT_NOT_CLEAN")
    if receipt["sources"] != json.loads((OUT / "sources-before.json").read_text()):
        problems.append("SOURCES_BEFORE_MISMATCH")
    if (OUT / "sources-before.json").read_bytes() != (OUT / "sources-after.json").read_bytes():
        problems.append("SOURCES_CHANGED_DURING_ACCEPTANCE")

    receipt_ref = {"path": (OUT / "acceptance.json").relative_to(ROOT).as_posix(),
                   "sha256": sha(OUT / "acceptance.json")}
    parent_path = "docs/research/overhaul_2026_10_23/FINDING_EVIDENCE_remaining_prs_v1.json"
    parent_sha = sha(ROOT / parent_path)
    for row in packet:
        if row["acceptance_test"]["execution_receipt"] != receipt_ref:
            problems.append("ROW_RECEIPT_MISMATCH:" + row["finding_id"])
        if row["supersedes"] != {"path": parent_path, "sha256": parent_sha,
                                 "finding_id": row["finding_id"]}:
            problems.append("ROW_SUPERSEDES_MISMATCH:" + row["finding_id"])
        for key in ("predictive_validation_granted", "model_promotion_granted",
                    "publication_allowed", "action_authority"):
            if row.get(key) is not False:
                problems.append("AUTHORITY_NOT_FALSE:" + key + ":" + row["finding_id"])
        if row.get("wagering_authority") != "OFF":
            problems.append("WAGERING_NOT_OFF:" + row["finding_id"])

    # Original-head preservation: every blob at ORIGINAL_HEAD must be unchanged
    # unless it is in the declared repair scope; protected paths never change.
    original = {}
    for line in git("ls-tree", "-r", ORIGINAL_HEAD).splitlines():
        meta, path = line.split("\t", 1)
        original[path] = meta.split()[2]
    modified, deleted, protected_violations = [], [], []
    for path, blob in original.items():
        file = ROOT / path
        if not file.is_file():
            deleted.append(path)
            continue
        current = hashlib.sha1(b"blob %d\0" % file.stat().st_size + file.read_bytes()).hexdigest()
        if current != blob:
            modified.append(path)
            if any(fnmatch.fnmatch(path, pattern) for pattern in PROTECTED):
                protected_violations.append(path)
    if sorted(modified) != EXPECTED_MODIFIED_ORIGINAL_PATHS:
        problems.append("UNEXPECTED_ORIGINAL_MODIFICATIONS:" + json.dumps(sorted(modified)))
    if deleted:
        problems.append("ORIGINAL_FILES_DELETED:" + json.dumps(deleted))
    if protected_violations:
        problems.append("PROTECTED_PATH_MODIFIED:" + json.dumps(protected_violations))

    env = receipt["environment"]
    pins = {d["name"].lower(): d["version"] for d in env["installed_distributions"]}
    result = {
        "schema": "pr95-independent-acceptance-readback-v1",
        "status": ("VERIFIED_LOCAL_SOFTWARE_ACCEPTANCE_HOSTED_PENDING" if not problems
                   else "READBACK_FAILED"),
        "problems": problems,
        "source_commit": receipt["source_commit"],
        "original_head": ORIGINAL_HEAD,
        "helper_sha256": sha(ROOT / "scripts/record_finding_successor.py"),
        "test_file_sha256": sha(ROOT / "tests/test_finding_successor.py"),
        "pytest_tests": counts["tests"],
        "research_unittest_tests": receipt["research_unittest_counts"]["tests"],
        "failures": counts["failures"], "errors": counts["errors"], "skips": counts["skipped"],
        "deselected": pytest_exec["deselected"],
        "all_reference_paths_verified": len(seen),
        "source_files_in_manifest": len(receipt["sources"]),
        "retained_history_files_verified": len(receipt["historical_evidence"]),
        "finding_successors": len(packet),
        "original_blob_files_checked": len(original),
        "original_blob_files_unchanged": len(original) - len(modified) - len(deleted),
        "expected_repair_modified_original_paths": EXPECTED_MODIFIED_ORIGINAL_PATHS,
        "protected_path_scope": PROTECTED,
        "protected_violations": protected_violations,
        "receipt_sha256": receipt_ref["sha256"],
        "packet_sha256": sha(OUT / "finding-evidence.json"),
        "delivery_sha256": sha(OUT / "delivery.json"),
        "delivery_status": delivery["status"],
        "python_version": env["python_version"].split()[0],
        "key_distributions": {k: pins.get(k) for k in ("numpy", "pandas", "scipy", "scikit-learn", "pytest")},
        "dependency_pin_source": "requirements-consolidated.txt (as installed by research-overhaul.yml)",
        "dependency_pin_conformance": "NOT_ASSESSED",
        "executed_at_utc": receipt["executed_at_utc"],
        "completed_at_utc": receipt["completed_at_utc"],
        "readback_at_utc": datetime.now(timezone.utc).isoformat(),
        "hosted_verification": "PENDING",
        "durable_archive_verified": False,
        "predictive_validation_granted": False,
        "model_promotion_granted": False,
        "publication_allowed": False,
        "action_authority": False,
        "wagering_authority": "OFF",
        "reviewer_reran_tests": False,
        "reviewer_repository_writes": False,
        "remote_writes": False,
    }
    (OUT / "full_acceptance_readback.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "problems", "pytest_tests",
          "research_unittest_tests", "all_reference_paths_verified",
          "original_blob_files_unchanged", "original_blob_files_checked")}, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
