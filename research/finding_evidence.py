"""Validate version-bound defect evidence without conferring model approval.

The supplied contract calls this a nine-field packet but enumerates ten fields.
All ten are required. File hashes prove identity, not scientific truth or time.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

FIELDS = frozenset({
    "finding_id", "observed", "expected", "evidence", "scope", "classification",
    "change", "acceptance_test", "remaining_limitation", "publication_impact",
})
CLASSIFICATIONS = frozenset({"implementation_bug", "predictive_change", "evaluation_bug",
                             "obsolete_policy", "unsupported_hypothesis", "deployment_failure"})
STATES = frozenset({"open", "located_pending_eval", "implemented_pending_verification",
                    "verified_implementation", "predictive_eval_pending", "blocked", "not_applicable"})
STAGES = ("Proposed", "Implemented", "Tested", "Merged", "Enabled", "Exercised", "Verified")


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("NONEMPTY_TEXT_REQUIRED:" + name)


def _ref(root, ref):
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise ValueError("EXACT_FILE_REFERENCE_REQUIRED")
    relative = Path(ref["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("EVIDENCE_PATH_ESCAPE")
    path = root / relative
    if not path.resolve().is_relative_to(root) or path.is_symlink() or not path.is_file():
        raise ValueError("MISSING_OR_ESCAPING_EVIDENCE")
    if hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
        raise ValueError("EVIDENCE_HASH_MISMATCH:" + ref["path"])


def _json_ref(root, ref):
    _ref(root, ref)
    value = json.loads((root / ref["path"]).read_text())
    if not isinstance(value, dict):
        raise ValueError("OBJECT_RECEIPT_REQUIRED")
    return value


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("AWARE_TIMESTAMP_REQUIRED")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("AWARE_TIMESTAMP_REQUIRED") from exc
    if stamp.tzinfo is None:
        raise ValueError("AWARE_TIMESTAMP_REQUIRED")


def validate_packet(packet, *, root):
    """Read-only acceptance of the packet schema and referenced bytes.

    'verified_implementation' requires an executed acceptance receipt, not a
    bare passing claim. Deployment completion remains a separate evidence axis.
    """
    root = Path(root).resolve()
    if not isinstance(packet, dict) or not FIELDS <= packet.keys():
        raise ValueError("ALL_TEN_EVIDENCE_FIELDS_REQUIRED")
    if packet.get("schema") != "finding-evidence-v1" or packet.get("status") not in STATES:
        raise ValueError("INVALID_PACKET_SCHEMA_OR_CLOSURE_STATE")
    if packet["classification"] not in CLASSIFICATIONS:
        raise ValueError("INVALID_FINDING_CLASSIFICATION")
    for field in FIELDS - {"evidence", "acceptance_test"}:
        _text(packet[field], field)
    _text(packet.get("owner"), "owner")
    if not isinstance(packet["evidence"], list) or not packet["evidence"]:
        raise ValueError("EVIDENCE_REFERENCES_REQUIRED")
    for ref in packet["evidence"]:
        _ref(root, ref)
    acceptance = packet["acceptance_test"]
    if not isinstance(acceptance, dict):
        raise ValueError("ACCEPTANCE_TEST_REQUIRED")
    _text(acceptance.get("command"), "acceptance_test.command")
    if packet["status"] == "verified_implementation":
        receipt_ref = acceptance.get("execution_receipt")
        _ref(root, receipt_ref)
        receipt = json.loads((root / receipt_ref["path"]).read_text())
        if receipt.get("schema") != "acceptance-execution-v1" or type(receipt.get("exit_code")) is not int or receipt["exit_code"] != 0:
            raise ValueError("SUCCESSFUL_EXECUTION_RECEIPT_REQUIRED")
        if receipt.get("command") != acceptance["command"]:
            raise ValueError("ACCEPTANCE_COMMAND_MISMATCH")
        _timestamp(receipt.get("executed_at_utc"))
        for source in receipt.get("sources", []):
            _ref(root, source)
        if not receipt.get("sources"):
            raise ValueError("VERSION_BOUND_EXECUTION_REQUIRED")
        _ref(root, receipt.get("log"))
    delivery = packet.get("delivery", {})
    if not isinstance(delivery, dict) or delivery.get("stage", "Proposed") not in STAGES:
        raise ValueError("INVALID_DELIVERY_STAGE")
    stage = delivery.get("stage", "Proposed")
    if STAGES.index(stage) >= STAGES.index("Merged"):
        commit = delivery.get("merge_commit")
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("MERGE_EVIDENCE_REQUIRED")
        merge = _json_ref(root, delivery.get("merge_receipt"))
        if merge.get("merged") is not True or merge.get("sha") != commit:
            raise ValueError("MERGE_RECEIPT_BINDING_MISMATCH")
    if STAGES.index(stage) >= STAGES.index("Enabled"):
        _ref(root, delivery.get("configuration_ref"))
    if STAGES.index(stage) >= STAGES.index("Exercised"):
        url = delivery.get("run_url")
        if not isinstance(url, str) or not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/[1-9][0-9]*(?:/attempts/[1-9][0-9]*)?", url):
            raise ValueError("ACTUAL_RUN_EVIDENCE_REQUIRED")
        run = _json_ref(root, delivery.get("run_receipt"))
        if run.get("html_url") != url or run.get("head_sha") != commit or run.get("status") != "completed":
            raise ValueError("RUN_RECEIPT_BINDING_MISMATCH")
    if stage == "Verified":
        verification = _json_ref(root, delivery.get("verification_receipt"))
        if (verification.get("schema") != "delivery-verification-v1"
                or verification.get("merge_commit") != commit
                or verification.get("run_receipt") != delivery["run_receipt"]
                or verification.get("configuration_ref") != delivery["configuration_ref"]
                or verification.get("verified") is not True or run.get("conclusion") != "success"):
            raise ValueError("DELIVERY_VERIFICATION_RECEIPT_REQUIRED")
        _timestamp(verification.get("verified_at_utc"))
    if packet["status"] in {"blocked", "located_pending_eval", "predictive_eval_pending"}:
        _text(packet.get("next_action"), "next_action")
    return {"finding_id": packet["finding_id"], "packet_valid": True,
            "status": packet["status"], "delivery_stage": stage,
            "predictive_validation_granted": False, "publication_allowed": False}


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("packet", type=Path)
    p.add_argument("--root", type=Path, default=Path.cwd())
    args = p.parse_args()
    document = json.loads(args.packet.read_text())
    rows = document if isinstance(document, list) else [document]
    print(json.dumps([validate_packet(row, root=args.root) for row in rows], indent=2))


if __name__ == "__main__":
    main()
