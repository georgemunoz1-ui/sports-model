#!/usr/bin/env python3
"""Evaluate preserved selection receipts against an explicit, hash-pinned population.

This offline reader does not fetch finals, edit forecasts or certify a procedure.
Run --help for the manifest contract; outcomes remain source assertions until an
independent reviewer authenticates their provenance and settlement mapping.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipelines.cards.research_selection import (
    seal_forecast, target_id, target_family, verify_selection_record, content_hash,
)
from research.selection_evaluation import evaluate_decisions


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_JSON_KEY:" + key)
        result[key] = value
    return result


def _decode(raw):
    return json.loads(raw, object_pairs_hook=_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("NONFINITE_JSON")))


def _utc(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("AWARE_TIMESTAMP_REQUIRED")
    return stamp.astimezone(timezone.utc)


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("SHA256_REQUIRED")
    return value


def _read_ref(root, spec, receipts):
    if not isinstance(spec, dict) or set(spec) != {"path", "sha256"}:
        raise ValueError("EXACT_PATH_AND_SHA256_REFERENCE_REQUIRED")
    path = (root / spec["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("SOURCE_PATH_OUTSIDE_PACKET_OR_MISSING")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != _sha(spec["sha256"]):
        raise ValueError("SOURCE_HASH_MISMATCH:" + spec["path"])
    receipts.append({"path": spec["path"], "sha256": digest, "bytes": len(raw)})
    return _decode(raw)


def _by_event(rows, name):
    if not isinstance(rows, list):
        raise ValueError(name + "_LIST_REQUIRED")
    result = {}
    for row in rows:
        event = row.get("event_id")
        if not isinstance(event, str) or not event or event in result:
            raise ValueError(name + "_UNIQUE_EVENT_ID_REQUIRED")
        result[event] = row
    return result


def build_evaluation(manifest_path, *, bootstrap_samples=2000, seed=0, executed_at=None):
    """Read-only validation and computation. Caller writes a new child artifact."""
    manifest_path = Path(manifest_path).resolve()
    raw = manifest_path.read_bytes()
    manifest = _decode(raw)
    required = {"schema", "evidence_scope", "population", "decisions", "outcomes"}
    if not isinstance(manifest, dict) or set(manifest) - required - {"controls"} or not required <= set(manifest):
        raise ValueError("INVALID_EVALUATION_MANIFEST_FIELDS")
    if manifest["schema"] != "research-selection-evaluation-input-v1":
        raise ValueError("INVALID_EVALUATION_MANIFEST_SCHEMA")
    if manifest["evidence_scope"] not in {"DISCOVERY", "SHADOW"}:
        raise ValueError("CONFIRMATION_REQUIRES_EXTERNAL_PROSPECTIVE_REGISTRATION_REVIEW")
    executed = executed_at or datetime.now(timezone.utc)
    if executed.tzinfo is None:
        raise ValueError("AWARE_EXECUTION_CLOCK_REQUIRED")
    receipts = []
    root = manifest_path.parent
    population = _read_ref(root, manifest["population"], receipts)
    population_index = _by_event(population, "POPULATION")
    document = _read_ref(root, manifest["decisions"], receipts)
    decisions = document.get("decisions") if isinstance(document, dict) else document
    if not isinstance(decisions, list):
        raise ValueError("DECISIONS_LIST_REQUIRED")
    outcome_rows = _read_ref(root, manifest["outcomes"], receipts)
    outcomes = _by_event(outcome_rows, "OUTCOMES")
    if set(outcomes) != set(population_index):
        raise ValueError("OUTCOMES_MUST_DECLARE_EVERY_POPULATION_EVENT_INCLUDING_MISSING")
    controls = {}
    if "controls" in manifest:
        control_rows = _read_ref(root, manifest["controls"], receipts)
        if not isinstance(control_rows, list):
            raise ValueError("CONTROL_FORECAST_LIST_REQUIRED")
        for original in control_rows:
            sealed = seal_forecast({k: v for k, v in original.items() if k != "forecast_id"})
            if sealed != original:
                raise ValueError("CONTROL_FORECAST_ID_MISMATCH")
            event = sealed["target"]["event_id"]
            if event in controls or event not in population_index:
                raise ValueError("CONTROL_EVENT_OUTSIDE_POPULATION_OR_DUPLICATE")
            controls[event] = sealed
    control_ids = {x["procedure_id"] for x in controls.values()}
    if len(control_ids) > 1:
        raise ValueError("MIXED_CONTROL_PROCEDURES")
    control_id = next(iter(control_ids), None)
    rows = []
    decision_ids = []
    scoring_exclusions = []
    for decision in decisions:
        verify_selection_record(decision)
        event = decision["target"]["event_id"]
        if event not in population_index:
            raise ValueError("DECISION_OUTSIDE_POPULATION")
        at = _utc(decision["decision_at_utc"])
        if at > executed:
            raise ValueError("DECISION_FROM_FUTURE")
        start = _utc(decision["target"]["starts_at_utc"])
        raw_probability = decision["raw_probability"]
        if at >= start:
            # Keep the externally declared opportunity and its blocked status,
            # but never score a late decision as a pregame probability forecast.
            if decision["decision_class"] != "BLOCKED":
                raise ValueError("POST_START_SELECTION_MUST_BE_BLOCKED")
            raw_probability = None
            scoring_exclusions.append({"event_id": event, "reason": "DECISION_NOT_PREGAME"})
        elif "FORECAST_FROM_FUTURE" in decision["blocking_reasons"]:
            raw_probability = None
            scoring_exclusions.append({"event_id": event, "reason": "FORECAST_NOT_AVAILABLE_AT_DECISION"})
        observed = outcomes[event]
        if observed.get("target_id") != decision["target_id"]:
            raise ValueError("OUTCOME_TARGET_MISMATCH")
        outcome = observed.get("outcome")
        observed_at = _utc(observed["observed_at_utc"])
        if observed_at > executed:
            raise ValueError("OUTCOME_OBSERVATION_FROM_FUTURE")
        if outcome in {"WIN", "LOSS", "PUSH", "VOID"}:
            expected_status = "VOID" if outcome == "VOID" else "FINAL"
            if observed.get("status") != expected_status:
                raise ValueError("RESOLVED_OUTCOME_REQUIRES_FINAL_OR_VOID_STATUS")
            completed = _utc(observed["settled_at_utc"])
            if completed > observed_at or (outcome != "VOID" and completed < start):
                raise ValueError("INVALID_SETTLEMENT_CHRONOLOGY")
            _sha(observed.get("source_sha256"))
            if not isinstance(observed.get("source_ref"), str) or not observed["source_ref"].strip():
                raise ValueError("OUTCOME_SOURCE_REFERENCE_REQUIRED")
        elif outcome not in {"LIVE", "MISSING"} or observed.get("status") != outcome:
            raise ValueError("INVALID_UNRESOLVED_STATUS")
        control = controls.get(event)
        if control:
            if target_id(control["target"]) != decision["target_id"]:
                raise ValueError("CONTROL_TARGET_MISMATCH")
            if _utc(control["forecast_created_at_utc"]) > at:
                raise ValueError("CONTROL_NOT_AVAILABLE_AT_DECISION")
            if _utc(control["forecast_created_at_utc"]) >= start:
                raise ValueError("CONTROL_NOT_PREGAME")
            if any(value is None for value in control["probabilities"].values()):
                raise ValueError("CONTROL_DIRECTION_REQUIRES_COMPLETE_SETTLEMENT_MASS")
            p = control["probabilities"]["win"]
            direction = "WIN" if p >= control["probabilities"]["loss"] else "LOSS"
        else:
            p = None
            direction = None
        rows.append({"event_id": event, "target_id": decision["target_id"],
                     "slate_id": population_index[event]["slate_id"],
                     "procedure_id": decision["procedure_id"],
                     "selector_config_id": decision["selector_config_id"],
                     "control_procedure_id": control_id,
                     "target_family_id": content_hash(target_family(decision["target"])),
                     "decision_class": decision["decision_class"], "outcome": outcome,
                     "raw_probability": raw_probability, "control_probability": p,
                     "control_target_id": decision["target_id"] if control else None,
                     "control_predicted_outcome": direction})
        decision_ids.append(decision["decision_id"])
    report = evaluate_decisions(rows, population=population, evidence_scope=manifest["evidence_scope"],
                                bootstrap_samples=bootstrap_samples, seed=seed)
    return {"schema": "research-selection-evaluation-bundle-v1",
            "created_at_utc": executed.astimezone(timezone.utc).isoformat(),
            "source_manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "source_receipts": receipts, "decision_ids": sorted(decision_ids),
            "scoring_exclusions": scoring_exclusions,
            "outcome_authenticity": "SOURCE_ASSERTIONS_NOT_INDEPENDENTLY_AUTHENTICATED",
            "control_direction_rule": "greater unconditional win/loss mass; equal mass retains target side; refunds never win",
            "prospective_registration_verified": False,
            "report": report, "evaluation_rows": rows, "publication_allowed": False,
            "wagering_status": "OFF"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        "Manifest schema research-selection-evaluation-input-v1: evidence_scope DISCOVERY|SHADOW; "
        "population, decisions, outcomes and optional controls are {path,sha256} references beneath "
        "the manifest directory. Population declares event_id,target_id,slate_id. Outcomes declare "
        "event_id,target_id,outcome,status,observed_at_utc; resolved rows also declare settled_at_utc, "
        "source_sha256,source_ref. Controls are sealed forecasts on the exact same target."))
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        if args.output_dir.exists():
            raise ValueError("OUTPUT_DIRECTORY_ALREADY_EXISTS")
        result = build_evaluation(args.manifest, bootstrap_samples=args.bootstrap_samples, seed=args.seed)
        args.output_dir.mkdir(parents=True, exist_ok=False)
        data = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
        with (args.output_dir / "evaluation.json").open("x") as stream:
            stream.write(data)
        receipt = {"evaluation_sha256": hashlib.sha256(data.encode()).hexdigest(),
                   "complete": True, "publication_allowed": False}
        with (args.output_dir / "receipt.json").open("x") as stream:
            json.dump(receipt, stream, sort_keys=True, indent=2)
        print(json.dumps({"output": str(args.output_dir / "evaluation.json"), **receipt}))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f"evaluation refused: {exc}\n")


if __name__ == "__main__":
    main()
