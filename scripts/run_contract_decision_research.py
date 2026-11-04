#!/usr/bin/env python3
"""Opt-in immutable contract-decision sidecar; never invokes a model or order API."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models.common.decision_research.compatibility import assess, canonical, decode
from models.common.decision_research.repository import SQLiteRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New immutable output directory")
    args = parser.parse_args()
    raw = args.request.read_bytes()
    request = decode(raw)
    # Refuse overwrites before any durable mutation.
    args.output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc)
    def git(*items):
        return subprocess.check_output(["git", "-C", str(ROOT), *items], text=True).strip()
    code = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "models/common/decision_research").rglob("*"))
            if p.is_file() and p.suffix in (".py", ".sql")}
    code[str(Path(__file__).relative_to(ROOT))] = sha256(Path(__file__).read_bytes()).hexdigest()
    identity = sha256(canonical(code).encode()).hexdigest()
    decision = assess(request, args.evidence_root, now=started)
    comparison_id = request.get("comparison_id", "INVALID_INPUT") if isinstance(request, dict) else "INVALID_INPUT"
    if not isinstance(comparison_id, str) or not comparison_id.strip():
        comparison_id = "INVALID_INPUT"
    with closing(sqlite3.connect(args.output / "research.sqlite")) as conn:
        repository = SQLiteRepository(conn)
        repository.migrate()
        repository.add_comparison(comparison_id, request if isinstance(request, dict) else {"invalid_request": request})
        saved = repository.evaluate(comparison_id, lambda _: decision, "evaluation-001", evaluator_id=identity)
        assert saved == decision
        if not repository.verify_audit():
            raise RuntimeError("AUDIT_INTEGRITY_FAILURE")
        checkpoint = repository.checkpoint()
    # Retain exact bound source bytes; recheck so a concurrent change cannot be
    # archived under the earlier hash. A failed copy leaves an incomplete run.
    for binding in decision["bindings"].values():
        source = args.evidence_root / binding["path"]
        content = source.read_bytes()
        if sha256(content).hexdigest() != binding["sha256"]:
            raise RuntimeError("EVIDENCE_CHANGED_DURING_EXECUTION")
        dest = args.output / "evidence" / binding["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    report = {"schema": "research.contract_decision_execution.v1", "started_at_utc": started.isoformat(),
              "completed_at_utc": datetime.now(timezone.utc).isoformat(), "observed_checkout": git("rev-parse", "HEAD"),
              "working_tree_status": git("status", "--porcelain"), "argv": sys.argv,
              "request_sha256": sha256(raw).hexdigest(), "code_sha256": code,
              "evaluator_id": identity, "decision": decision, "audit_checkpoint": checkpoint,
              "postgresql_integration": "NOT_RUN", "order_authorized": False, "action": "OFF", "dose": 0}
    (args.output / "request.json").write_bytes(raw)
    (args.output / "decision.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    manifest = {str(p.relative_to(args.output)): sha256(p.read_bytes()).hexdigest()
                for p in sorted(args.output.rglob("*")) if p.is_file()}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"disposition": decision["disposition"], "output": str(args.output), "order_authorized": False}))
    return 2 if decision["disposition"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
