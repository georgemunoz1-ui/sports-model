#!/usr/bin/env python3
"""Operational readiness only: never create a registry, forecast or grade."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

SCHEMA = "canonical.grading_preflight.v1"
REGISTRY_SCHEMA = "canonical.prospective_research.v1"
AWAITING = "AWAITING_FIRST_PROSPECTIVE_REGISTRATION"


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NONFINITE_JSON")))


def prior_evidence(root):
    """Only recognized no-registration reports and lock files are non-evidence."""
    evidence = []
    if not root.exists():
        return evidence
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            evidence.append(str(relative)); continue
        if not path.is_file() or str(relative) == "registry.json.lock":
            continue
        benign = False
        if relative.parts[0] == "operations" and path.suffix == ".json":
            try:
                doc = read_json(path)
                benign = (doc.get("schema") == SCHEMA and doc.get("status") == AWAITING
                    and doc.get("registered_count") == 0 and doc.get("registration_evidence") == []
                    and doc.get("registry_present") is False and doc.get("settlement_performed") is False)
            except (ValueError, OSError, AttributeError):
                pass
        elif relative.parts[0] == "attempts" and path.suffix == ".json":
            # An explicit failed registration attempt is not a forecast receipt.
            try:
                doc = read_json(path)
                benign = (set(doc) == {"status", "reason", "action_authority"}
                          and doc["status"] == "BLOCKED" and doc["action_authority"] is False)
            except (ValueError, OSError, TypeError):
                pass
        if not benign:
            evidence.append(str(relative))
    return evidence


def assess(root, *, current_attempt=None):
    root = Path(root)
    report = {"schema": SCHEMA, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "INTEGRITY_FAILURE", "registry_present": False, "registered_count": 0,
        "registration_evidence": [], "settlement_performed": False,
        "publication_allowed": False, "action_authority": False, "wagering_status": "OFF"}
    registry = root / "registry.json"
    if root.exists() and not root.is_dir():
        return {**report, "reason": "CANONICAL_ROOT_NOT_DIRECTORY"}
    if root.is_symlink() or registry.is_symlink():
        return {**report, "reason": "CANONICAL_STATE_SYMLINK_REFUSED"}
    if not registry.exists():
        evidence = prior_evidence(root)
        return {**report, "status": "INTEGRITY_FAILURE" if evidence else AWAITING,
            "registration_evidence": evidence,
            "reason": "REGISTRY_MISSING_WITH_PRIOR_EVIDENCE" if evidence else "NO_PROSPECTIVE_FORECAST_REGISTERED"}
    report["registry_present"] = True
    try:
        document = read_json(registry)
        forecasts = document.get("forecasts")
        if document.get("schema") != REGISTRY_SCHEMA or not isinstance(forecasts, dict) or not forecasts:
            raise ValueError("NONEMPTY_CANONICAL_REGISTRY_REQUIRED")
        if any(not isinstance(v, dict) or not v for v in forecasts.values()):
            raise ValueError("MALFORMED_REGISTRY_RECORD")
        report.update(status="READY_TO_ACQUIRE", registered_count=len(forecasts),
            registry_sha256=hashlib.sha256(registry.read_bytes()).hexdigest(),
            reason="REGISTRY_PRESENT; WRITER_AND_GRADER_RETAIN_FULL_RECEIPT_VALIDATION")
        if current_attempt is not None:
            run_id, attempt = current_attempt
            if any(not re.fullmatch(r"[1-9][0-9]*", value) for value in (run_id, attempt)):
                raise ValueError("POSITIVE_RUN_AND_ATTEMPT_IDENTITIES_REQUIRED")
            path = root / "results" / (run_id + "-" + attempt) / "results.json"
            report["current_results_path"] = str(path)
            if any(candidate.is_symlink() for candidate in (root / "results", path.parent, path)):
                raise ValueError("CURRENT_ATTEMPT_RESULTS_SYMLINK_REFUSED")
            if not path.is_file():
                raise ValueError("CURRENT_ATTEMPT_RESULTS_MISSING")
            if not isinstance(read_json(path), list):
                raise ValueError("CURRENT_ATTEMPT_RESULTS_LIST_REQUIRED")
            report.update(status="CURRENT_ATTEMPT_RESULTS_READY", current_results_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    except (ValueError, OSError, AttributeError) as exc:
        report.update(status="INTEGRITY_FAILURE", reason=str(exc))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/grading/canonical"))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--check-current-results", nargs=2, metavar=("RUN_ID", "ATTEMPT"))
    args = parser.parse_args(argv)
    report = assess(args.root, current_attempt=args.check_current_results)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x") as stream:
        json.dump(report, stream, sort_keys=True, indent=2); stream.write("\n")
    if args.github_output:
        with args.github_output.open("a") as stream:
            stream.write("state=" + report["status"] + "\n")
    print(json.dumps(report, sort_keys=True))
    return 2 if report["status"] == "INTEGRITY_FAILURE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
