#!/usr/bin/env python3
"""Acquire live finals and grade only immutable canonical research registrations.

No imported-result or retrospective-registration option exists. HTTPS capture
from approved provider URLs is trusted-execution evidence, not a provider-signed
attestation. Certified calibration, official release and wagering remain OFF.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import canonical_forecasts as forecasts
from scripts import canonical_results as results
from scripts.canonical_grading_preflight import read_json
from scripts.ci_evidence_archive import digest, write_new
from scripts.daily_research_archive import seal_directory

SCHEMA = "daily.research.postgame.v1"


class PrerequisiteUnavailable(ValueError):
    """An expected empty/not-due state, not evidence of a defective grader."""


def retain_result_source(row, root):
    """Freeze provider bytes under canonical state before any grade is appended.

    Changing the storage reference does not alter source bytes, source timestamps,
    scores, or their evidentiary status. A provider-signed attestation is absent.
    """
    results.verify_result_source(row)
    source = Path(row["raw_path"])
    raw = source.read_bytes()
    relative = Path("result_sources") / (row["source_sha256"] + ".json")
    destination = Path(root) / relative
    if any(p.is_symlink() for p in (destination, destination.parent, Path(root), *Path(root).parents)):
        raise ValueError("RESULT_SOURCE_SYMLINK_REFUSED")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != raw:
            raise ValueError("FROZEN_RESULT_SOURCE_CONFLICT")
    else:
        with destination.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    retained = {**row, "raw_path": relative.as_posix(), "raw_path_base": "CANONICAL_REGISTRY"}
    results.verify_result_source(retained, base_dir=root)
    return retained


def run_postgame(registry_root, output, through_date, *, fetcher=None):
    root, output = Path(registry_root), Path(output)
    cutoff_date = date.fromisoformat(through_date)
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema": SCHEMA, "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "through_date": through_date, "status": "FAILED", "registered_count": 0,
              "selected_count": 0, "existing_grade_count": 0, "new_grade_count": 0,
              "settlement_performed": False, "failures": [], "pending": [], "exclusions": [],
              "canonical_source_retention": "CONTENT_HASH_ADDRESSED_REGISTRY_RELATIVE",
              "transport": "APPROVED_ORIGIN_HTTPS" if fetcher is None else "TEST_INJECTED_FETCHER",
              "provider_signed_attestation": False, "independent_source_authentication": False,
              "evaluation_cohort": "PROSPECTIVE_RESEARCH_SOURCE_UNVERIFIED",
              "predictive_validation": "NOT_ASSESSED", "official_release": False,
              "action_authority": False, "wagering_authority": "OFF"}
    try:
        if root.is_symlink() or (root / "registry.json").is_symlink():
            raise ValueError("CANONICAL_STATE_SYMLINK_REFUSED")
        registry_path = root / "registry.json"
        if not registry_path.is_file():
            raise PrerequisiteUnavailable("AWAITING_FIRST_PROSPECTIVE_REGISTRATION")
        registry = read_json(registry_path)
        rows = registry.get("forecasts")
        if registry.get("schema") != forecasts.SCHEMA or not isinstance(rows, dict):
            raise ValueError("CANONICAL_REGISTRY_SCHEMA_INVALID")
        if not rows:
            raise PrerequisiteUnavailable("AWAITING_FIRST_PROSPECTIVE_REGISTRATION")
        report["registry_sha256"] = digest(registry_path)
        report["registered_count"] = len(rows)
        selected = []
        for key, receipt in rows.items():
            if key != receipt.get("receipt_id"):
                raise ValueError("RECEIPT_KEY_MISMATCH")
            forecasts.verify_receipt(root, receipt)
            if date.fromisoformat(receipt["card_date"]) <= cutoff_date:
                selected.append(receipt)
        report["selected_count"] = len(selected)
        if not selected:
            raise PrerequisiteUnavailable("NO_REGISTRATIONS_THROUGH_REQUESTED_DATE")
        existing = forecasts.load_ledger(root / "ledger.jsonl")
        existing_ids = {r["receipt_id"] for r in existing}
        if len(existing_ids) != len(existing):
            raise ValueError("DUPLICATE_EXISTING_GRADE")
        if any(r["receipt_id"] not in rows or r.get("grade_id") != r["receipt_id"] for r in existing):
            raise ValueError("EXISTING_GRADE_IDENTITY_MISMATCH")
        selection_ledger = forecasts.load_ledger(root / "selection_ledger.jsonl")
        selection_ids = {r["grade_id"] for r in selection_ledger}
        if len(selection_ids) != len(selection_ledger):
            raise ValueError("DUPLICATE_EXISTING_SELECTION_GRADE")
        if any(r["forecast_receipt_id"] not in rows or r["grade_id"] != forecasts.identity({
                "receipt_id": r["forecast_receipt_id"], "decision_id": r["decision_id"]}) for r in selection_ledger):
            raise ValueError("EXISTING_SELECTION_GRADE_IDENTITY_MISMATCH")
        if any(rows[r["forecast_receipt_id"]].get("selection_decision_id") != r["decision_id"] or
               not r.get("selection_sidecar_sha256") or
               rows[r["forecast_receipt_id"]].get("selection_sidecar_sha256") != r["selection_sidecar_sha256"]
               for r in selection_ledger):
            raise ValueError("EXISTING_SELECTION_GRADE_RECEIPT_MISMATCH")
        report["existing_grade_count"] = sum(r["receipt_id"] in existing_ids for r in selected)
        pending_receipts = [r for r in selected if r["receipt_id"] not in existing_ids]
        report["expected_receipt_ids"] = sorted(r["receipt_id"] for r in selected)
        retained_results = {}
        for old in [*existing, *selection_ledger]:
            retained = old["result_source"]
            forecasts.verify_retained_result(retained, root)
            receipt = rows[old.get("receipt_id") or old["forecast_receipt_id"]]
            if retained.get("status") != "FINAL" or any(retained[k] != receipt[k] for k in
                    ("league", "event_id", "home_team", "away_team")) or \
                    results.stamp(retained["start_time_utc"]) != results.stamp(receipt["start_time_utc"]):
                raise ValueError("EXISTING_GRADE_RESULT_BINDING_MISMATCH")
            result_key = (retained["league"], retained["event_id"])
            prior = retained_results.get(result_key)
            identity_fields = ("home_team", "away_team", "start_time_utc", "home_score", "away_score", "status")
            if prior and any(prior[k] != retained[k] for k in identity_fields):
                raise ValueError("CONFLICTING_RETAINED_FINAL_RESULTS")
            retained_results[result_key] = retained
        if not pending_receipts:
            forecasts.grade(root, list(retained_results.values()))
            report["status"] = "ALREADY_GRADED"
            report["reason"] = "NO_NEW_SETTLEMENT_PERFORMED"
        else:
            captured = results.acquire_results(pending_receipts, output / "sources", fetcher=fetcher)
            # The collector's original receipts stay in this immutable run.
            # Ledger references point to canonical copies so grading can replay
            # after the old runner workspace and run directory disappear.
            captured = [retain_result_source(row, root) if row["status"] != "BLOCKED" else row for row in captured]
            failures = [{"event_id": r["event_id"], "reason": r["reason"]} for r in captured if r["status"] == "BLOCKED"]
            pending = [{"event_id": r["event_id"], "reason": r.get("reason", "NOT_FINAL")} for r in captured if r["status"] == "PENDING"]
            report.update(failures=failures, pending=pending,
                          acquired_event_count=len(captured),
                          approved_endpoint_final_count=sum(r["status"] == "FINAL" for r in captured))
            if digest(registry_path) != report["registry_sha256"]:
                raise ValueError("REGISTRY_CHANGED_DURING_ACQUISITION")
            for captured_row in captured:
                retained_results[(captured_row["league"], captured_row["event_id"])] = captured_row
            graded = forecasts.grade(root, list(retained_results.values()))
            write_new(output / "grade.json", graded)
            report.update(new_grade_count=graded["added_count"], settlement_performed=graded["added_count"] > 0,
                          exclusions=graded["excluded"], selection_new_grade_count=graded["selection_added_count"])
            report["status"] = "INCOMPLETE" if failures or pending else "COMPLETED"
            if failures or pending:
                report["reason"] = "ACQUISITION_FAILURE_OR_UNSETTLED_REGISTERED_EVENTS"
    except PrerequisiteUnavailable as exc:
        report["status"] = str(exc)
        report["reason"] = str(exc)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        report["status"] = "FAILED"
        report["failures"].append({"reason": str(exc)})
    write_new(output / "report.json", report)
    seal_directory(output)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/grading/canonical"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--through-date", default=(datetime.now(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=1)).isoformat())
    args = parser.parse_args(argv)
    report = run_postgame(args.root, args.output, args.through_date)
    print(json.dumps(report, sort_keys=True))
    # Waiting is explicit, has no settlement, and must not count as a completed
    # grading cycle. It is not an operational failure needing a nightly alert.
    return 0 if report["status"] in {"COMPLETED", "ALREADY_GRADED",
        "AWAITING_FIRST_PROSPECTIVE_REGISTRATION", "NO_REGISTRATIONS_THROUGH_REQUESTED_DATE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
