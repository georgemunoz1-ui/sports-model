#!/usr/bin/env python3
"""Grade registered immutable MLB forecast-card artifacts and verify grading invariants."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import accumulate_mlb_calibration as accumulator
from scripts.register_mlb_calibration import atomic_json, registry_lock, validate_registration

GRADER_VERSION = accumulator.GRADER_VERSION


def utcnow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def dt(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_registry(path):
    if not path.exists():
        return {"schema_version": "mlb_calibration_registry_v1", "cards": {}}
    return json.loads(path.read_text())


def load_ledger(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


home_probability = accumulator.home_probability

def calibration_bin(probability):
    low = min(0.9, math.floor(float(probability) * 10.0) / 10.0)
    high = min(1.0, low + 0.1)
    return f"{low:.1f}-{high:.1f}"


def forecast_output_hash(row):
    output_hash = (row.get("provenance") or {}).get("output_hash")
    if output_hash:
        return output_hash
    payload = {
        "event_id": row.get("event_id"),
        "input_snapshot_hash": row.get("input_snapshot_hash"),
        "model_state_config_hash": row.get("model_state_config_hash"),
        "simulation": row.get("simulation"),
        "analytic_p": row.get("analytic_p"),
        "stochastic_sim_p": row.get("stochastic_sim_p"),
    }
    return "fallback:" + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify_invariants(card_path, pre_digest, ledger_path):
    post_digest = sha256_file(card_path)
    card = json.loads(card_path.read_text())
    forecasts = [row for row in card.get("forecasts", []) if row.get("forecast_status") == "FORECAST_GENERATED"]
    by_hash = {forecast_output_hash(row): row for row in forecasts}
    hashes = [forecast_output_hash(row) for row in forecasts]
    ledger = load_ledger(ledger_path)
    relevant = [row for row in ledger if row.get("forecast_output_hash") in by_hash and row.get("grader_version") == GRADER_VERSION]
    grade_ids = [row.get("grade_id") for row in ledger]
    failures = []

    if pre_digest != post_digest:
        failures.append("FROZEN_CARD_MUTATED")
    if len(hashes) != len(set(hashes)):
        failures.append("FORECAST_OUTPUT_HASH_NOT_UNIQUE")
    if len(grade_ids) != len(set(grade_ids)):
        failures.append("DUPLICATE_GRADE_ID_IN_LEDGER")

    for row in relevant:
        frozen = by_hash[row["forecast_output_hash"]]
        analytic = home_probability(frozen, "analytic_p_home", "analytic_p")
        sim = home_probability(frozen, "stochastic_sim_p_home", "stochastic_sim_p")
        if analytic is None or sim is None:
            failures.append(f"HOME_PROBABILITY_UNAVAILABLE:{row.get('event_id')}")
            continue
        if abs(float(row["analytic_p_home"]) - analytic) > 1e-15:
            failures.append(f"ANALYTIC_PROBABILITY_MUTATED:{row.get('event_id')}")
        if abs(float(row["stochastic_sim_p_home"]) - sim) > 1e-15:
            failures.append(f"SIM_PROBABILITY_MUTATED:{row.get('event_id')}")
        if row.get("calibration_bin_analytic") != calibration_bin(analytic):
            failures.append(f"ANALYTIC_BIN_TEMPORAL_FIREWALL_FAIL:{row.get('event_id')}")
        if row.get("calibration_bin_sim") != calibration_bin(sim):
            failures.append(f"SIM_BIN_TEMPORAL_FIREWALL_FAIL:{row.get('event_id')}")
        graded_at = dt(row["graded_at_utc"])
        if graded_at <= dt(frozen["start_time_utc"]):
            failures.append(f"GRADE_TIMESTAMP_NOT_AFTER_START:{row.get('event_id')}")
        if row.get("result_observed_at_utc") and graded_at < dt(row["result_observed_at_utc"]):
            failures.append(f"GRADE_TIMESTAMP_PRECEDES_RESULT_OBSERVATION:{row.get('event_id')}")
        if card.get("generated_at_utc") and graded_at <= dt(card["generated_at_utc"]):
            failures.append(f"GRADE_TIMESTAMP_NOT_AFTER_FORECAST:{row.get('event_id')}")
        if row.get("market_features_used") is not False or row.get("action_authority") is not False:
            failures.append(f"MARKET_ACTION_FIREWALL_FAIL:{row.get('event_id')}")

    return {
        "status": "PASS" if not failures else "FAIL",
        "forecast_payload_mutations": 0 if pre_digest == post_digest else 1,
        "forecast_count": len(forecasts),
        "unique_forecast_output_hashes": len(set(hashes)),
        "graded_rows_for_card_current_version": len(relevant),
        "global_unique_grade_ids": len(set(grade_ids)),
        "global_ledger_rows": len(grade_ids),
        "temporal_firewall_checked_rows": len(relevant),
        "failures": failures,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default="data/grading/mlb/registry.json")
    parser.add_argument("--ledger", default="data/grading/mlb/calibration_ledger.jsonl")
    parser.add_argument("--summary", default="data/grading/mlb/calibration_summary.json")
    parser.add_argument("--output-dir", default="output/mlb_grading")
    parser.add_argument("--grade-date")
    parser.add_argument("--include-graded", action="store_true")
    parser.add_argument("--results-json", help="Retained official schedule bytes; requires --grade-date")
    parser.add_argument("--card", help="Assert an exact match to the registered frozen card")
    parser.add_argument("--report-out", help="Compatibility path for a single-card grading report")
    args = parser.parse_args(argv)
    if (args.results_json or args.card or args.report_out) and not args.grade_date:
        parser.error("single-card arguments require --grade-date")
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    registry_path, ledger_path = Path(args.registry), Path(args.ledger)
    with registry_lock(registry_path):
        registry = load_registry(registry_path)
        original_registry = json.loads(json.dumps(registry))
        cards = registry.get("cards", {})
        selected = [(date, entry) for date, entry in sorted(cards.items())
                    if (not args.grade_date or date == args.grade_date)
                    and (args.include_graded or entry.get("status") != "GRADED")]
        errors, results = [], []
        if args.grade_date and args.grade_date not in cards:
            errors.append("UNREGISTERED_CARD_DATE:" + args.grade_date)
        ledger = load_ledger(ledger_path)
        ids = [r["grade_id"] for r in ledger]
        if len(ids) != len(set(ids)):
            errors.append("DUPLICATE_GRADE_ID_IN_LEDGER")
        snapshots = output / "result_snapshots"
        with tempfile.TemporaryDirectory(dir=output) as staging:
            staged_ledger = Path(staging) / "ledger.jsonl"
            for card_date, entry in selected:
                try:
                    card_path = Path(entry["card_path"])
                    if args.card and sha256_file(Path(args.card)) != entry.get("card_sha256"):
                        raise ValueError("ASSERTED_CARD_HASH_MISMATCH")
                    card, eligible_ids = validate_registration(card_path, entry, card_date)
                    pre_digest = sha256_file(card_path)
                    outcomes = accumulator.outcome_map(card_date, args.results_json, snapshots)
                    added, pending, skipped, duplicates = accumulator.grade(card, ledger, outcomes, eligible_ids)
                    for row in added:
                        row["forecast_card_sha256"] = pre_digest
                        row["forecast_run_id"] = entry["run_id"]
                        row["registration_at_utc"] = entry["registered_at_utc"]
                    # Verify candidates before changing the durable ledger or registry.
                    staged_ledger.write_text("".join(json.dumps(r) + "\n" for r in ledger))
                    invariants = verify_invariants(card_path, pre_digest, staged_ledger)
                    if invariants["status"] != "PASS":
                        raise ValueError("GRADE_INVARIANT_FAILURE:" + ",".join(invariants["failures"]))
                    if skipped:
                        raise ValueError("FORECASTS_SKIPPED:" + json.dumps(skipped, sort_keys=True))
                    graded = invariants["graded_rows_for_card_current_version"]
                    if graded + len(pending) != len(eligible_ids):
                        raise ValueError("GRADE_COVERAGE_MISMATCH")
                    status = "PARTIALLY_GRADED" if pending and graded else "AWAITING_OUTCOMES" if pending else "GRADED"
                    last_report = {"graded_count": graded, "pending_count": len(pending), "skipped_count": 0,
                                   "invariant_status": "PASS"}
                    if entry.get("status") != status or any(entry.get("last_report", {}).get(k) != v for k, v in last_report.items()):
                        entry["status"] = status
                        entry["last_grade_attempt_utc"] = utcnow()
                        entry["last_report"] = {**last_report, "added_count": len(added), "existing_grade_count": len(duplicates)}
                        if status == "GRADED":
                            entry["graded_at_utc"] = utcnow()
                    report = {"card_date": card_date, "run_id": entry["run_id"], "status": status,
                              "added_count": len(added), "duplicate_grades": duplicates,
                              "pending_event_ids": pending, "skipped": skipped, "invariants": invariants}
                    results.append(report)
                except (ValueError, KeyError, OSError, TypeError) as exc:
                    errors.append(f"{card_date}:{exc}")
                    results.append({"card_date": card_date, "status": "ERROR", "reason": str(exc)})
            metrics = accumulator.aggregate(ledger)
            if not errors and selected:
                # The append is the recovery point: a retry reconstructs derived state from it.
                result_dir = registry_path.parent / "results"
                if snapshots.exists():
                    result_dir.mkdir(parents=True, exist_ok=True)
                    for source in snapshots.iterdir():
                        target = result_dir / source.name
                        if target.exists() and not source.name.endswith(".receipt.json") and target.read_bytes() != source.read_bytes():
                            raise ValueError("RESULT_SNAPSHOT_CONFLICT:" + source.name)
                        if not target.exists():
                            shutil.copyfile(source, target)
                accumulator.save_ledger(ledger_path, ledger)
                summary_path = Path(args.summary)
                prior_summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
                if prior_summary.get("metrics") != metrics:
                    atomic_json(summary_path, {"artifact_type": "mlb_probability_calibration_summary_v2",
                                "generated_at_utc": utcnow(), "grader_version": GRADER_VERSION,
                                "market_overlay_enabled": False, "action_authority": False, "metrics": metrics})
                if registry != original_registry:
                    registry["updated_at_utc"] = utcnow()
                    atomic_json(registry_path, registry)
        for report in results:
            report["persisted"] = not errors
            atomic_json(output / ("grade_report_" + report["card_date"] + ".json"), report)
            if args.report_out:
                atomic_json(Path(args.report_out), report)
        status = "FAILED" if errors else "COMPLETED" if selected else "ALREADY_GRADED" if args.grade_date else "NO_PENDING_CARDS"
        combined = {"artifact_type": "mlb_calibration_registry_grade_run_v2", "grader_version": GRADER_VERSION,
                    "generated_at_utc": utcnow(), "status": status, "selected_count": len(selected),
                    "added_count": sum(r.get("added_count", 0) for r in results) if not errors else 0,
                    "durable_ledger_count": len(load_ledger(ledger_path)), "errors": errors, "results": results,
                    "market_overlay_enabled": False, "action_authority": False}
        atomic_json(output / "registry_grade_run.json", combined)
        print(json.dumps(combined, indent=2, sort_keys=True))
        return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
