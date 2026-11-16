"""Sidecars for direct Monte Carlo diagnostic CLIs; native math stays unchanged."""
from __future__ import annotations

import hashlib
import csv
import json
import math
import os
from pathlib import Path

from .missingness import seal_audit, verify_audit
from .shared_missingness import check_source_inputs


def _pair_state(output):
    """Classify the forecast/sidecar pair as (forecast_exists, sidecar_exists)."""
    output = Path(output)
    return output.exists(), Path(str(output) + ".missingness.json").exists()


def cfb_schedule_preflight(path, event_id):
    with Path(path).open(newline="") as stream:
        matches = [row for row in csv.DictReader(stream) if str(row.get("game_id")) == str(event_id)]
    if len(matches) > 1:
        raise ValueError("DIAGNOSTIC_DUPLICATE_EVENT_ID")
    if not matches:
        raise ValueError("DIAGNOSTIC_EVENT_NOT_IN_SOURCE")


def preflight(snapshot, state, output):
    """A failed source cannot silently enter an otherwise permissive old kernel."""
    if not isinstance(snapshot, dict) or not isinstance(state, dict):
        raise ValueError("DIAGNOSTIC_INPUT_OBJECTS_REQUIRED")
    event_id = snapshot.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("DIAGNOSTIC_EVENT_ID_REQUIRED")
    check_source_inputs(snapshot)
    check_source_inputs(state)
    output = Path(output)
    forecast_exists, sidecar_exists = _pair_state(output)
    if sidecar_exists:
        # A complete pair is immutable; a receipt without its forecast can
        # never become verifiable, so refuse rather than re-bind it.
        raise FileExistsError("DIAGNOSTIC_OUTPUT_ALREADY_EXISTS")
    # A lone forecast is an interrupted earlier attempt: persist() completes it
    # by binding the receipt to the existing bytes instead of overwriting.


def _field(value, default):
    try:
        numeric = float(value)
        finite = math.isfinite(numeric)
    except (ValueError, TypeError, OverflowError):
        finite = False
        numeric = None
    return {"raw_value": value, "consumed_value": numeric if finite else default,
            "fallback_applied": not finite, "fallback_value": default,
            "source_state": "UNRESOLVED_IDENTITY_OR_COVERAGE",
            "value_status": "NUMERIC_VALUE_WITHOUT_SOURCE_ATTESTATION" if finite else "LEGACY_PRIOR_FALLBACK",
            "boolean_numeric_coercion": isinstance(value, bool)}


def input_details(league, snapshot, state, source_inputs=None):
    """Describe the existing transformations; never call these source verification."""
    if league == "mlb":
        fields = {name: _field(snapshot.get(name), default) for name, default in [
            ("away_rf_pg", 4.45), ("away_ra_pg", 4.45), ("home_rf_pg", 4.45),
            ("home_ra_pg", 4.45), ("park_factor", 1.0)]}
        for side in ("home", "away"):
            starter = snapshot.get(side + "_sp") or {}
            for name, default in [("era", 4.2), ("gs", 0), ("k", 22.), ("bb", 8.5)]:
                fields[side + "_sp." + name] = _field(starter.get(name), default)
        return {"features": fields,
                "unreviewed_fallbacks": [name for name, row in fields.items() if row["fallback_applied"]],
                "settlement_limitations": ["TIE_WINNER_CORRECTION_IS_NOT_EXTRA_INNING_SCORE_SIMULATION",
                                            "RUN_LINE_AND_TOTAL_NOT_QUALIFIED"],
                "starter_workload_prior": {"mean_innings": 5.4, "sd_innings": 1.3, "clip": [2, 8]}}
    if league != "cfb":
        raise ValueError("DIAGNOSTIC_LEAGUE_UNSUPPORTED")
    row = (source_inputs or {}).get("schedule_row", {})
    return {"rating_source_home": snapshot.get("rating_source_home"),
            "rating_source_away": snapshot.get("rating_source_away"),
            "schedule_boolean_defaults": {
                name: {"raw_value": row.get(name), "consumed_value": snapshot.get(name),
                       "missing_source_value": name not in row or row[name] in (None, ""),
                       "source_state": "UNRESOLVED_IDENTITY_OR_COVERAGE"}
                for name in ("neutral_site", "conference_game")},
            "global_sigma_fallback": str(snapshot["week"]) not in state["residual_model"].get("segment_sigma_by_week", {}),
            "population": snapshot["population"],
            "settlement_limitations": ["CONTINUOUS_MARGIN_LAW_DOES_NOT_MODEL_WHOLE_POINT_PUSH_MASS",
                                        "NO_TOTAL_HEAD", "CROSS_DIVISION_EXTRAPOLATION_UNVALIDATED"]}


def persist(output, forecast, *, league, snapshot, state, source_inputs=None):
    """Write an immutable original payload and a separately bound review sidecar."""
    preflight(snapshot, state, output)
    output = Path(output)
    sidecar = Path(str(output) + ".missingness.json")
    model_id = forecast.get("model", {}).get("model_id") or forecast.get("simulation_engine")
    if not model_id:
        model_id = "mlb.v13_1.gamma_poisson_monte_carlo.v1" if league == "mlb" else None
    products = ["winner", "margin"] + (["total"] if league == "mlb" else [])
    binding = dict(league=league, event_id=snapshot["event_id"], model_id=model_id,
                   products=products, forecast=forecast)
    details = input_details(league, snapshot, state, source_inputs)
    details.update({"status": "DIAGNOSTIC_CLI_INPUTS_RECORDED",
                    "input_snapshot": snapshot, "model_state": state, "source_inputs": source_inputs,
                    "source_observation_state": "UNRESOLVED_IDENTITY_OR_COVERAGE",
                    "source_verification": "VALUES_SUPPLIED_TO_CLI_ARE_NOT_AUTHENTICATED_OBSERVATIONS",
                    "change_attribution": {"sporting": None, "missingness_imputation": None,
                                           "model_version": None, "simulation_variation": None,
                                           "interactions": None, "status": "PAIRED_PARENT_AND_STUDY_REQUIRED"},
                    "sensitivity_validation": "MODEL_AND_PRODUCT_SPECIFIC_REVIEW_PENDING",
                    "native_output_hash": forecast.get("output_hash"),
                    "native_math_and_seed_unchanged": True})
    receipt_inputs = dict(binding)
    output.parent.mkdir(parents=True, exist_ok=True)
    forecast_exists, _ = _pair_state(output)
    if forecast_exists:
        # Recovery from an interrupted earlier attempt: keep the existing
        # forecast bytes authoritative; never overwrite them on retry.
        raw = output.read_bytes()
        recovered = json.loads(raw)
        receipt_inputs["forecast"] = recovered
        details["native_output_hash"] = recovered.get("output_hash")
    else:
        raw = (json.dumps(forecast, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
        # Exclusive write preserves earlier diagnostic editions as well as forecasts.
        with output.open("xb") as stream:
            stream.write(raw)
    # Seal after the forecast bytes exist so an interruption here leaves at
    # most an unpaired forecast that a later retry can complete, never a
    # receipt stranded without its forecast.
    receipt = seal_audit(**receipt_inputs, details=details)
    record = {"schema": "sports.diagnostic_cli_missingness.v1", "league": league,
              "event_id": snapshot["event_id"], "model_id": model_id, "products": products,
              "forecast_file_sha256": hashlib.sha256(raw).hexdigest(),
              "missingness_audit": receipt, "official_release_eligible": False, "action_authority": False}
    # Atomic receipt publication: a failure mid-write leaves no partial sidecar.
    temporary = output.parent / (sidecar.name + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    os.replace(temporary, sidecar)
    verify(output)
    return sidecar


def verify(output):
    output = Path(output)
    raw = output.read_bytes()
    record = json.loads(Path(str(output) + ".missingness.json").read_bytes())
    forecast = json.loads(raw)
    binding = {key: record[key] for key in ("league", "event_id", "model_id", "products")}
    if (hashlib.sha256(raw).hexdigest() != record["forecast_file_sha256"]
            or record.get("official_release_eligible") is not False or record.get("action_authority") is not False
            or not verify_audit(record.get("missingness_audit"), forecast=forecast, **binding)):
        raise ValueError("DIAGNOSTIC_CLI_MISSINGNESS_READBACK_FAILED")
    return record
