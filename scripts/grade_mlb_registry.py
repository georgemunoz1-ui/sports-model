#!/usr/bin/env python3
"""Grade registered immutable MLB forecast-card artifacts and verify grading invariants."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

GRADER_VERSION = "mlb.calibration_grader.v2"


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


def save_registry(path, registry):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")


def load_ledger(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def finite_prob(value):
    try:
        number = float(value)
    except Exception:
        return False
    return math.isfinite(number) and 0.0 <= number <= 1.0


def home_probability(row, explicit_key, legacy_key):
    grading = row.get("grading") or {}
    if finite_prob(grading.get(explicit_key)):
        return float(grading[explicit_key])
    value = row.get(legacy_key)
    if not finite_prob(value):
        return None
    value = float(value)
    if row.get("model_winner") == row.get("home_team"):
        return value
    if row.get("model_winner") == row.get("away_team"):
        return 1.0 - value
    return None


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
    ledger_path = Path(args.ledger)
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
            results.append({"card_date": card_date, "run_id": run_id, "status": "ERROR", "reason": "MULTIPLE_DIAGNOSTIC_CARDS_FOUND"})
            continue

        card_path = candidates[0]
        pre_digest = sha256_file(card_path)
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
        invariant_report = verify_invariants(card_path, pre_digest, ledger_path)
        if invariant_report["status"] != "PASS":
            raise SystemExit("GRADE_INVARIANT_FAILURE:" + ",".join(invariant_report["failures"]))

        pending = report.get("pending_event_ids", [])
        skipped = report.get("skipped", [])
        graded_count = invariant_report["graded_rows_for_card_current_version"]
        entry["last_grade_attempt_utc"] = utcnow()
        entry["last_report"] = {
            "added_count": report.get("added_count"),
            "existing_grade_count": len(report.get("duplicate_grades", [])),
            "graded_count": graded_count,
            "pending_count": len(pending),
            "skipped_count": len(skipped),
            "invariant_status": invariant_report["status"],
        }

        if skipped:
            entry["status"] = "REVIEW_REQUIRED"
        elif pending and graded_count > 0:
            entry["status"] = "PARTIALLY_GRADED"
        elif pending:
            entry["status"] = "AWAITING_OUTCOMES"
        else:
            entry["status"] = "GRADED"
            entry["graded_at_utc"] = utcnow()

        results.append({
            "card_date": card_date,
            "run_id": run_id,
            "status": entry["status"],
            "added_count": report.get("added_count"),
            "existing_grades": report.get("duplicate_grades", []),
            "pending_event_ids": pending,
            "skipped": skipped,
            "invariants": invariant_report,
        })

    registry["updated_at_utc"] = utcnow()
    save_registry(registry_path, registry)
    combined = {
        "artifact_type": "mlb_calibration_registry_grade_run_v2",
        "grader_version": GRADER_VERSION,
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
