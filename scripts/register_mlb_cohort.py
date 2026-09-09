#!/usr/bin/env python3
"""Register immutable prospective MLB forecast cohorts from frozen diagnostic cards.

This registry is additive to the legacy date-level calibration registry. It exists
because one run/date cannot represent multiple pregame cutoff cohorts safely.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "mlb_calibration_cohort_registry_v2"
REGISTRAR_VERSION = "mlb.cohort_registrar.v1"


def dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def hash_json(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(payload)


def load_registry(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "dates": {}}
    registry = json.loads(path.read_text())
    if registry.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit(f"REGISTRY_SCHEMA_MISMATCH:{registry.get('schema_version')}")
    return registry


def save_registry(path: Path, registry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--card", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--grade-date", required=True)
    parser.add_argument("--cohort-id", required=True)
    parser.add_argument("--event-id", action="append", dest="event_ids", required=True)
    parser.add_argument("--registered-at-utc")
    args = parser.parse_args()

    registry_path = Path(args.registry)
    card_path = Path(args.card)
    manifest_path = Path(args.manifest) if args.manifest else None
    card = json.loads(card_path.read_text())
    manifest = json.loads(manifest_path.read_text()) if manifest_path and manifest_path.exists() else {}

    if card.get("league") != "MLB":
        raise SystemExit(f"LEAGUE_MISMATCH:{card.get('league')}")
    if card.get("card_date") != args.grade_date:
        raise SystemExit(f"CARD_DATE_MISMATCH:{card.get('card_date')}:{args.grade_date}")
    if card.get("authority") != "SHADOW_ONLY" or card.get("actionable") is not False:
        raise SystemExit("AUTHORITY_FIREWALL_FAIL")
    pit = card.get("pit_provenance") or {}
    if pit.get("pit_gate") != "PASS":
        raise SystemExit(f"PIT_GATE_NOT_PASS:{pit.get('pit_gate')}")
    if pit.get("action_authority") is not False:
        raise SystemExit("PIT_ACTION_AUTHORITY_FAIL")

    requested_cutoff = dt(card["requested_as_of_utc"])
    generated_at = dt(card["generated_at_utc"])
    actual_data_vintage = dt(pit["actual_data_vintage_utc"])
    registered_at = dt(args.registered_at_utc) if args.registered_at_utc else utcnow()

    if requested_cutoff > generated_at:
        raise SystemExit("FORECAST_GENERATED_BEFORE_REQUESTED_CUTOFF_INCONSISTENT")
    if actual_data_vintage > generated_at:
        raise SystemExit("DATA_VINTAGE_AFTER_CARD_GENERATION")
    if generated_at >= registered_at:
        raise SystemExit("REGISTRATION_NOT_AFTER_CARD_GENERATION")

    forecasts = {
        str(row["event_id"]): row
        for row in card.get("forecasts", [])
        if row.get("forecast_status") == "FORECAST_GENERATED"
    }
    selected_ids = sorted(set(str(x) for x in args.event_ids))
    if len(selected_ids) != len(args.event_ids):
        raise SystemExit("DUPLICATE_EVENT_ID_REQUEST")
    missing = [event_id for event_id in selected_ids if event_id not in forecasts]
    if missing:
        raise SystemExit("EVENT_NOT_IN_FROZEN_FORECAST:" + ",".join(missing))

    starts = {}
    output_hashes = {}
    for event_id in selected_ids:
        row = forecasts[event_id]
        start = dt(row["start_time_utc"])
        if registered_at >= start:
            raise SystemExit(f"REGISTRATION_NOT_PREGAME:{event_id}:{iso(start)}")
        starts[event_id] = iso(start)
        grading = row.get("grading") or {}
        if grading.get("eligible_for_prospective_grading") is not True:
            raise SystemExit(f"FORECAST_NOT_PROSPECTIVE_GRADE_ELIGIBLE:{event_id}")
        output_hash = (row.get("provenance") or {}).get("output_hash")
        if not output_hash:
            raise SystemExit(f"FORECAST_OUTPUT_HASH_MISSING:{event_id}")
        output_hashes[event_id] = output_hash

    event_universe_hash = hash_json(selected_ids)
    forecast_output_set_hash = hash_json([[eid, output_hashes[eid]] for eid in selected_ids])
    card_sha = sha256_file(card_path)
    manifest_sha = sha256_file(manifest_path) if manifest_path and manifest_path.exists() else None
    identity_payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": args.run_id,
        "grade_date": args.grade_date,
        "cohort_id": args.cohort_id,
        "requested_cutoff_utc": iso(requested_cutoff),
        "card_sha256": card_sha,
        "manifest_sha256": manifest_sha,
        "event_universe_hash": event_universe_hash,
        "forecast_output_set_hash": forecast_output_set_hash,
    }
    cohort_identity_hash = hash_json(identity_payload)

    entry = {
        "cohort_id": args.cohort_id,
        "run_id": args.run_id,
        "grade_date": args.grade_date,
        "registered_at_utc": iso(registered_at),
        "registration_basis": "Writer-clock prospective cohort registration from frozen remote artifact",
        "registration_state": "REMOTE_DURABLE_PROSPECTIVE",
        "registrar_version": REGISTRAR_VERSION,
        "requested_cutoff_utc": iso(requested_cutoff),
        "actual_data_vintage_utc": iso(actual_data_vintage),
        "card_generated_at_utc": iso(generated_at),
        "pit_status": pit.get("pit_status"),
        "pit_gate": pit.get("pit_gate"),
        "pit_reconstruction_supported": pit.get("pit_reconstruction_supported"),
        "card_sha256": card_sha,
        "manifest_sha256": manifest_sha,
        "event_ids": selected_ids,
        "event_start_times_utc": starts,
        "event_universe_hash": event_universe_hash,
        "forecast_output_hashes": output_hashes,
        "forecast_output_set_hash": forecast_output_set_hash,
        "cohort_identity_hash": cohort_identity_hash,
        "market_input_used": False,
        "market_overlay_enabled": False,
        "action_authority": False,
        "status": "REGISTERED_AWAITING_OUTCOMES",
    }

    registry = load_registry(registry_path)
    date_entry = registry.setdefault("dates", {}).setdefault(args.grade_date, {"cohorts": {}})
    cohorts = date_entry.setdefault("cohorts", {})
    existing = cohorts.get(args.cohort_id)
    if existing:
        if existing.get("cohort_identity_hash") != cohort_identity_hash:
            raise SystemExit(
                "REGISTERED_COHORT_IMMUTABLE:"
                f"{args.grade_date}:{args.cohort_id}:"
                f"{existing.get('cohort_identity_hash')}!={cohort_identity_hash}"
            )
        print(json.dumps({"status": "IDEMPOTENT", "entry": existing}, indent=2, sort_keys=True))
        return

    for other_id, other in cohorts.items():
        if other.get("run_id") == args.run_id and other.get("requested_cutoff_utc") == iso(requested_cutoff):
            overlap = sorted(set(other.get("event_ids", [])) & set(selected_ids))
            if overlap:
                raise SystemExit(
                    "DUPLICATE_EVENT_REGISTRATION_SAME_RUN_CUTOFF:"
                    f"{other_id}:{','.join(overlap)}"
                )

    cohorts[args.cohort_id] = entry
    registry["updated_at_utc"] = iso(registered_at)
    save_registry(registry_path, registry)
    print(json.dumps({"status": "REGISTERED", "entry": entry}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
