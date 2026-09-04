#!/usr/bin/env python3
"""Grade registered immutable MLB forecast-card artifacts.

Registry entries bind a card date to one GitHub Actions run ID before outcomes are
used for model comparison. This prevents post-hoc selection among multiple same-day
forecast runs. Exact reproduction cards are not registered separately.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_registry(path):
    if not path.exists():
        return {"schema_version": "mlb_calibration_registry_v1", "cards": {}}
    return json.loads(path.read_text())


def save_registry(path, registry):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default="data/grading/mlb/registry.json")
    parser.add_argument("--ledger", default="data/grading/mlb/calibration_ledger.jsonl")
    parser.add_argument("--summary", default="data/grading/mlb/calibration_summary.json")
    parser.add_argument("--output-dir", default="output/mlb_grading")
    parser.add_argument("--grade-date")
    parser.add_argument("--include-graded", action="store_true")
    args = parser.parse_args()

    registry_path = Path(args.registry)
    registry = load_registry(registry_path)
    cards = registry.setdefault("cards", {})
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    results = []

    selected = []
    for card_date, entry in sorted(cards.items()):
        if args.grade_date and card_date != args.grade_date:
            continue
        if entry.get("status") == "GRADED" and not args.include_graded:
            continue
        selected.append((card_date, entry))

    for card_date, entry in selected:
        run_id = entry.get("run_id")
        if not run_id:
            results.append({"card_date": card_date, "status": "ERROR", "reason": "RUN_ID_MISSING"})
            continue

        work = output / f"run-{run_id}"
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        try:
            subprocess.run(["gh", "run", "download", str(run_id), "--dir", str(work)], check=True)
        except subprocess.CalledProcessError as exc:
            results.append({"card_date": card_date, "run_id": run_id, "status": "ERROR", "reason": f"ARTIFACT_DOWNLOAD_FAILED:{exc.returncode}"})
            continue

        candidates = sorted(work.rglob("diagnostic_card.json"))
        if not candidates:
            results.append({"card_date": card_date, "run_id": run_id, "status": "ERROR", "reason": "DIAGNOSTIC_CARD_NOT_FOUND"})
            continue
        if len(candidates) > 1:
            # One Actions run should publish one diagnostic-card artifact. Refuse ambiguity.
            results.append({"card_date": card_date, "run_id": run_id, "status": "ERROR", "reason": "MULTIPLE_DIAGNOSTIC_CARDS_FOUND"})
            continue

        card_path = candidates[0]
        report_path = output / f"grade_report_{card_date}.json"
        cmd = [
            sys.executable,
            "scripts/accumulate_mlb_calibration.py",
            "--card", str(card_path),
            "--ledger", args.ledger,
            "--summary-out", args.summary,
            "--report-out", str(report_path),
        ]
        subprocess.run(cmd, check=True)
        report = json.loads(report_path.read_text())
        pending = report.get("pending_event_ids", [])
        skipped = report.get("skipped", [])
        complete = not pending and not skipped
        entry["last_grade_attempt_utc"] = utcnow()
        entry["last_report"] = {
            "added_count": report.get("added_count"),
            "pending_count": len(pending),
            "skipped_count": len(skipped),
        }
        if complete:
            entry["status"] = "GRADED"
            entry["graded_at_utc"] = utcnow()
        else:
            entry["status"] = "AWAITING_OUTCOMES" if pending else "REVIEW_REQUIRED"
        results.append({
            "card_date": card_date,
            "run_id": run_id,
            "status": entry["status"],
            "added_count": report.get("added_count"),
            "pending_event_ids": pending,
            "skipped": skipped,
        })

    registry["updated_at_utc"] = utcnow()
    save_registry(registry_path, registry)
    combined = {
        "artifact_type": "mlb_calibration_registry_grade_run_v1",
        "generated_at_utc": utcnow(),
        "selected_count": len(selected),
        "results": results,
        "market_overlay_enabled": False,
        "action_authority": False,
    }
    (output / "registry_grade_run.json").write_text(json.dumps(combined, indent=2, sort_keys=True) + "\n")
    print(json.dumps(combined, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
