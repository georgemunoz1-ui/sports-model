#!/usr/bin/env python3
"""Evaluate preserved selection receipts against an explicit, hash-pinned population.

This offline reader does not fetch finals, edit forecasts or certify a procedure.
Run --help for the manifest contract; outcomes remain source assertions until an
independent reviewer authenticates their provenance and settlement mapping.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipelines.cards.research_selection import (
    seal_forecast, target_id, target_family, verify_selection_record, content_hash,
)
from research.selection_evaluation import evaluate_decisions


def build_sidecar_evaluation(sidecar_path, settlement_update_path, *, bootstrap_samples=2000, seed=0, executed_at=None):
    """Exercise retained actual forecasts against corrected retained final records.

    This path is DISCOVERY only. It recomputes settlement arithmetic from scores,
    never copies a reported pick grade, and never writes a canonical ledger.
    Separate exact procedure/family/side/line groups prevent accidental pooling.
    """
    from pipelines.cards.selection_integration import verify_sidecar, settle_target
    paths = [Path(sidecar_path).resolve(), Path(settlement_update_path).resolve()]
    raw = [path.read_bytes() for path in paths]
    board, update = map(_decode, raw)
    verify_sidecar(board)
    if update.get("schema") != "oct22_diagnostic_postgame_comparison_v1":
        raise ValueError("EXPLICIT_RETAINED_SETTLEMENT_ADAPTER_REQUIRED")
    if update.get("forecast_file_sha256") != board["source_card"]["sha256"]:
        raise ValueError("SETTLEMENT_SOURCE_FORECAST_VERSION_MISMATCH")
    executed = executed_at or datetime.now(timezone.utc)
    observed = _utc(update["as_of_utc"])
    if observed > executed:
        raise ValueError("SETTLEMENT_OBSERVATION_FROM_FUTURE")
    observations = _by_event(update["events"], "SETTLEMENT_EVENTS")
    forecasts = {r["forecast_id"]: r for r in board["forecasts"]}
    groups, exclusions, settlements = defaultdict(list), [], []
    seen = set()
    for decision in board["decisions"]:
        event, target = decision["target"]["event_id"], decision["target"]
        if decision["target_id"] in seen:
            raise ValueError("DUPLICATE_SIDECAR_OPPORTUNITY")
        seen.add(decision["target_id"])
        if event not in observations:
            raise ValueError("SETTLEMENT_POPULATION_EVENT_MISSING")
        item = observations[event]
        if _utc(item["start_time_utc"]) != _utc(target["starts_at_utc"]) or item["league"].lower() != target["league"]:
            raise ValueError("SETTLEMENT_EVENT_IDENTITY_MISMATCH")
        outcome = "MISSING"
        observation = item["observation"]
        if observation.get("final") is True:
            if observation.get("status") not in {"FINAL", "FINAL_OT", "FINAL_SO"} or observed < _utc(target["starts_at_utc"]):
                raise ValueError("FINAL_STATUS_OR_OBSERVATION_CHRONOLOGY_INVALID")
            if observation.get("source_key") not in update.get("sources", {}):
                raise ValueError("SETTLEMENT_SOURCE_REFERENCE_MISSING")
            if target["settlement_rules_id"] == "UNFORECASTED_HOME_WIN_OPPORTUNITY_v1":
                exclusions.append({"target_id": decision["target_id"], "reason": "NO_FORECAST_TARGET_TO_SETTLE"})
            else:
                outcome = settle_target(target, observation["home_score"], observation["away_score"],
                                        score_period=observation.get("score_period"))
        elif observation.get("status") in {"LIVE", "IN_PROGRESS"}:
            outcome = "LIVE"
        p = decision["raw_probability"]
        if decision.get("raw_probability_basis", "unconditional_win") != "unconditional_win":
            p = None
            exclusions.append({"target_id": decision["target_id"], "reason": "NON_UNCONDITIONAL_PROBABILITY_NOT_SCORED"})
        forecast = forecasts[decision["forecast_id"]]
        if _utc(forecast["forecast_created_at_utc"]) >= _utc(target["starts_at_utc"]) or _utc(decision["decision_at_utc"]) >= _utc(target["starts_at_utc"]):
            p = None
            exclusions.append({"target_id": decision["target_id"], "reason": "POST_START_FORECAST_OR_DECISION_NOT_SCORED"})
        row = {"event_id": event, "target_id": decision["target_id"], "slate_id": update["date"],
            "procedure_id": decision["procedure_id"], "selector_config_id": decision["selector_config_id"],
            "control_procedure_id": None, "target_family_id": content_hash(target_family(target)),
            "decision_class": decision["decision_class"], "outcome": outcome,
            "raw_probability": p, "control_probability": None, "control_target_id": None,
            "control_predicted_outcome": None}
        grouping = (row["procedure_id"], row["selector_config_id"], row["target_family_id"], target["side"], target["line"])
        groups[grouping].append(row)
        settlements.append({"event_id": event, "target_id": decision["target_id"], "decision_id": decision["decision_id"],
            "outcome": outcome, "decision_class": decision["decision_class"],
            "selected_outcome": outcome if decision["decision_class"] == "SHADOW_SELECTED" else None,
            "source_observation": observation, "observed_at_utc": update["as_of_utc"],
            "settlement_time_basis": "FINAL_KNOWN_BY_CAPTURE; ACTUAL_END_TIME_NOT_ASSERTED"})
    reports = []
    for identity, rows in sorted(groups.items(), key=lambda item: str(item[0])):
        population = [{key: row[key] for key in ("event_id", "target_id", "slate_id")} for row in rows]
        report = evaluate_decisions(rows, population=population, evidence_scope="DISCOVERY", bootstrap_samples=bootstrap_samples, seed=seed)
        reports.append({"group_id": content_hash(identity), "procedure_id": identity[0],
                        "selector_config_id": identity[1], "target_family_id": identity[2],
                        "side": identity[3], "line": identity[4], "evaluation": report})
    return {"schema": "actual-sidecar-settlement-evaluation-v1", "created_at_utc": executed.isoformat(),
        "evidence_scope": "DISCOVERY", "execution_mode": "RETROSPECTIVE_DIAGNOSTIC",
        "source_receipts": [{"path": str(path), "sha256": hashlib.sha256(data).hexdigest()} for path, data in zip(paths, raw)],
        "source_card_sha256": board["source_card"]["sha256"], "sidecar_id": board["sidecar_id"],
        "event_count": len({s["event_id"] for s in settlements}), "opportunity_count": len(settlements),
        "outcome_counts": dict(Counter(s["outcome"] for s in settlements)),
        "decision_counts": dict(Counter(s["decision_class"] for s in settlements)),
        "settlements": settlements, "scoring_exclusions": exclusions, "groups": reports,
        "outcome_authenticity": "RETAINED_SOURCE_ASSERTIONS_NOT_INDEPENDENTLY_AUTHENTICATED",
        "canonical_ledger_writes": 0, "publication_allowed": False, "wagering_status": "OFF"}


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


def load_walk_forward(config_path):
    """Resolve externally trusted plan and realized fit receipts read-only."""
    from scripts.run_research_selection import Sources, ReadOnlyReceiptStore, exact_keys, identifiers
    from research.validation_registry import Ed25519Verifier
    from research.procedure_lineage import FrozenWalkForwardPlan
    path = Path(config_path).resolve(strict=True)
    sources = Sources()
    spec = sources.json(path, "walk_forward_runtime_configuration")
    exact_keys(spec, {"schema", "store_directory", "trust_file", "plan_id", "registration_receipt_id", "realized_fit_receipt_ids"},
               {"state_trust_file"})
    if spec["schema"] != "research-walk-forward-runtime-v1":
        raise ValueError("WALK_FORWARD_RUNTIME_SCHEMA_REQUIRED")
    identifiers([spec["plan_id"], spec["registration_receipt_id"]])
    identifiers(spec["realized_fit_receipt_ids"])
    directory = (path.parent / spec["store_directory"]).resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("EXISTING_READ_ONLY_WALK_FORWARD_STORE_REQUIRED")
    def verifier(filename):
        trust = sources.json(path.parent / filename, "explicit_walk_forward_trust")
        exact_keys(trust, {"schema", "public_keys_b64"})
        if trust["schema"] != "research-validation-trust-v1" or not isinstance(trust["public_keys_b64"], dict):
            raise ValueError("INVALID_WALK_FORWARD_TRUST_SCHEMA")
        keys = {name: base64.b64decode(value, validate=True) for name, value in trust["public_keys_b64"].items()}
        if any(not isinstance(name, str) or not name.strip() or len(value) != 32 for name, value in keys.items()):
            raise ValueError("INVALID_WALK_FORWARD_TRUST_KEY")
        return Ed25519Verifier(keys)
    trusted = verifier(spec["trust_file"])
    state = verifier(spec["state_trust_file"]) if "state_trust_file" in spec else trusted
    plan = FrozenWalkForwardPlan(ReadOnlyReceiptStore(directory, sources), spec["plan_id"],
        spec["registration_receipt_id"], trusted,
        realized_fit_receipt_ids=spec["realized_fit_receipt_ids"], state_verifier=state)
    return plan, sources


def build_evaluation(manifest_path, *, bootstrap_samples=2000, seed=0, executed_at=None, walk_forward_config=None):
    """Read-only validation and computation. Caller writes a new child artifact."""
    manifest_path = Path(manifest_path).resolve()
    raw = manifest_path.read_bytes()
    manifest = _decode(raw)
    required = {"schema", "evidence_scope", "population", "decisions", "outcomes"}
    if not isinstance(manifest, dict) or set(manifest) - required - {"controls", "forecast_states"} or not required <= set(manifest):
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
    plan, plan_sources = load_walk_forward(walk_forward_config) if walk_forward_config else (None, None)
    states = {}
    if (plan is None) != ("forecast_states" not in manifest):
        raise ValueError("WALK_FORWARD_REQUIRES_EXACT_FORECAST_STATE_RECEIPTS")
    if plan is not None:
        states = _by_event(_read_ref(root, manifest["forecast_states"], receipts), "FORECAST_STATES")
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
    if len(control_ids) > 1 and plan is None:
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
        if decision.get("raw_probability_basis", "unconditional_win") != "unconditional_win":
            raw_probability = None
            scoring_exclusions.append({"event_id": event, "reason": "NON_UNCONDITIONAL_PROBABILITY_NOT_SCORED"})
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
                     "control_procedure_id": control["procedure_id"] if control else None,
                     "target_family_id": content_hash(target_family(decision["target"])),
                     "decision_class": decision["decision_class"], "outcome": outcome,
                     "raw_probability": raw_probability, "control_probability": p,
                     "control_target_id": decision["target_id"] if control else None,
                     "control_predicted_outcome": direction})
        if plan is not None:
            state = states.get(event)
            if not isinstance(state, dict):
                raise ValueError("FORECAST_STATE_EVENT_MISSING")
            original = state["forecast"]
            forecast = seal_forecast({k: v for k, v in original.items() if k != "forecast_id"})
            if forecast != original or forecast["forecast_id"] != decision["forecast_id"]:
                raise ValueError("WALK_FORWARD_FORECAST_RECEIPT_MISMATCH")
            training = state["training_data_cutoff_utc"]
            if _utc(training) > _utc(forecast["forecast_cutoff_utc"]):
                raise ValueError("WALK_FORWARD_TRAINING_AFTER_INFORMATION_CUTOFF")
            rows[-1].update(fitted_state_id=state["fitted_state_id"],
                control_fitted_state_id=state.get("control_fitted_state_id"),
                training_data_cutoff_utc=training,
                forecast_created_at_utc=forecast["forecast_created_at_utc"],
                decision_at_utc=decision["decision_at_utc"], starts_at_utc=decision["target"]["starts_at_utc"])
            if control:
                rows[-1].update(control_training_data_cutoff_utc=state["control_training_data_cutoff_utc"],
                                control_forecast_created_at_utc=control["forecast_created_at_utc"])
        decision_ids.append(decision["decision_id"])
    if plan is not None and set(states) != set(population_index):
        raise ValueError("FORECAST_STATE_POPULATION_MISMATCH")
    report = evaluate_decisions(rows, population=population, evidence_scope=manifest["evidence_scope"],
                                bootstrap_samples=bootstrap_samples, seed=seed, walk_forward_plan=plan)
    if plan_sources:
        plan_sources.verify()
        receipts.extend(plan_sources.list())
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
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path)
    source.add_argument("--selection-sidecar", type=Path, help="Actual automatic sidecar; paired with explicit retained --settlement-update")
    parser.add_argument("--settlement-update", type=Path, help="Version-bound retained Oct22 corrected interim update; discovery only")
    parser.add_argument("--walk-forward-config", type=Path, help="External trust/store/plan/fit receipt configuration; manifest must bind exact forecast_states")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        if args.output_dir.exists():
            raise ValueError("OUTPUT_DIRECTORY_ALREADY_EXISTS")
        if args.selection_sidecar:
            if args.walk_forward_config:
                raise ValueError("RETAINED_DISCOVERY_SIDECAR_HAS_NO_WALK_FORWARD_REGISTRATION")
            if not args.settlement_update:
                raise ValueError("SELECTION_SIDECAR_REQUIRES_SETTLEMENT_UPDATE")
            result = build_sidecar_evaluation(args.selection_sidecar, args.settlement_update,
                                              bootstrap_samples=args.bootstrap_samples, seed=args.seed)
        else:
            if args.settlement_update:
                raise ValueError("SETTLEMENT_UPDATE_REQUIRES_SELECTION_SIDECAR")
            result = build_evaluation(args.manifest, bootstrap_samples=args.bootstrap_samples, seed=args.seed,
                                      walk_forward_config=args.walk_forward_config)
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
