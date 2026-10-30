"""Immutable runner for the separately identified NBA projected-minutes arm."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

from models.experiments import nba_personnel as model


def read_bound(reference, base):
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        raise ValueError("NBA_PERSONNEL_EXACT_FILE_REFERENCE_REQUIRED")
    p = (Path(base) / reference["path"]).resolve(strict=True)
    raw = p.read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("NBA_PERSONNEL_INPUT_BYTES_MISMATCH")
    return json.loads(raw), p


def write(path, value):
    with Path(path).open("x") as f:
        json.dump(value, f, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")


def common_report(mode):
    return {"schema": "nba-personnel-execution.v1", "run_id": "nba-personnel-" + uuid.uuid4().hex,
            "created_at_utc": datetime.now(timezone.utc).isoformat(), "mode": mode,
            "model_id": model.MODEL_ID, "predictive_validation": "UNVALIDATED",
            "provider_authenticity": "NOT_ASSESSED", "pit_eligibility": "NOT_ASSESSED",
            "canonical_prospective_eligible": False, "publication_allowed": False, "action_authority": False,
            "code_sha256": {str(p.relative_to(Path(__file__).resolve().parents[2])): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in (Path(model.__file__).resolve(), Path(__file__).resolve())}}


def experiment(input_path, output):
    """Fit an explicit earlier split, then score the exact later paired events.

    Input schema is nba-personnel-experiment.v1; training/evaluation are row
    lists. Scope is TEST_ONLY or HISTORICAL_RECONSTRUCTED, never prospective.
    A refused fit is retained as a named BLOCKED result, not a zero effect.
    """
    p, out = Path(input_path).resolve(strict=True), Path(output)
    raw = p.read_bytes()
    packet = json.loads(raw)
    if packet.get("schema") != "nba-personnel-experiment.v1" or packet.get("evidence_scope") not in {"TEST_ONLY", "HISTORICAL_RECONSTRUCTED"}:
        raise ValueError("NBA_PERSONNEL_EXPERIMENT_SCHEMA")
    out.mkdir(parents=True, exist_ok=False)
    report = {**common_report("HISTORICAL_DIAGNOSTIC"), "evidence_scope": packet["evidence_scope"],
              "input_sha256": hashlib.sha256(raw).hexdigest(), "fit_cutoff_utc": packet["fit_cutoff_utc"],
              "training_opportunities": len(packet["training"]), "evaluation_opportunities": len(packet["evaluation"])}
    try:
        state = model.fit(packet["training"], base=p.parent, fit_cutoff_utc=packet["fit_cutoff_utc"])
    except (ValueError, KeyError, TypeError, OSError) as exc:
        report.update(status="BLOCKED", reason=str(exc), n_paired=0)
        write(out / "report.json", report)
        return report
    write(out / "state.json", state)
    ids, forecasts, paired, excluded = set(), [], [], []
    for row in packet["evaluation"]:
        eid = row.get("event", {}).get("event_id")
        try:
            if eid in ids:
                raise ValueError("NBA_PERSONNEL_DUPLICATE_EVALUATION_EVENT")
            ids.add(eid)
            forecast = model.predict(state, row, base=p.parent)
            forecasts.append(forecast)
            if forecast["conditional_scenarios"]:
                raise ValueError("NBA_PERSONNEL_CONDITIONAL_OUTCOME_MATCH_NOT_ESTABLISHED")
            result = row["result"]
            now = model.utc(report["created_at_utc"])
            model.source(result["source"], p.parent, now, expected=model.binding("result", row["event"], {k: result[k] for k in ("home_margin", "available_at_utc")}))
            if not model.utc(row["event"]["start_time_utc"]) < model.utc(result["available_at_utc"]) <= now:
                raise ValueError("NBA_PERSONNEL_EVALUATION_RESULT_CHRONOLOGY")
            if model.utc(result["source"]["retrieved_at_utc"]) < model.utc(result["available_at_utc"]):
                raise ValueError("NBA_PERSONNEL_RESULT_SOURCE_PREDATES_AVAILABILITY")
            actual = model.observed_margin(result["home_margin"])
            paired.append({"event_id": eid, "parent_home_margin": forecast["parent_home_margin"],
                           "challenger_home_margin": forecast["home_margin"], "actual_home_margin": actual,
                           "parent_absolute_error": abs(actual - forecast["parent_home_margin"]),
                           "challenger_absolute_error": abs(actual - forecast["home_margin"]),
                           "forecast_sha256": forecast["forecast_sha256"]})
        except (ValueError, KeyError, TypeError, OSError) as exc:
            excluded.append({"event_id": eid, "reason": str(exc)})
    report.update(status="COMPLETED" if paired and not excluded else "PARTIAL" if paired else "BLOCKED",
                  state_sha256=state["state_sha256"], n_paired=len(paired), n_excluded=len(excluded),
                  baseline_mae=sum(r["parent_absolute_error"] for r in paired) / len(paired) if paired else None,
                  challenger_mae=sum(r["challenger_absolute_error"] for r in paired) / len(paired) if paired else None,
                  uncertainty="NOT_ESTIMATED; exploratory point summary is not qualification", exclusions=excluded)
    if p.read_bytes() != raw:
        raise ValueError("NBA_PERSONNEL_INPUT_CHANGED_DURING_RUN")
    write(out / "forecasts.json", forecasts)
    write(out / "paired.json", paired)
    write(out / "report.json", report)
    return report


def shadow_from_card(card_path, config_path, output):
    """Opt-in shared-card sidecar; parent forecasts are read-only.

    No fitting, baseline replacement, probability borrowing, simulation or
    canonical registration occurs here. Missing event packets remain visible.
    """
    card_path, config_path, out = Path(card_path).resolve(strict=True), Path(config_path).resolve(strict=True), Path(output)
    card_raw, config_raw = card_path.read_bytes(), config_path.read_bytes()
    card, config = json.loads(card_raw), json.loads(config_raw)
    if config.get("schema") != "nba-personnel-shadow.v1" or card.get("league", "").lower() != "nba":
        raise ValueError("NBA_PERSONNEL_CARD_CONFIG_SCHEMA")
    state, _ = read_bound(config["state"], config_path.parent)
    inputs, inputs_path = read_bound(config["inputs"], config_path.parent)
    if inputs.get("schema") != "nba-personnel-inputs.v1":
        raise ValueError("NBA_PERSONNEL_INPUT_SCHEMA")
    rows = inputs["rows"]
    lookup = {r["event"]["event_id"]: r for r in rows}
    if len(lookup) != len(rows):
        raise ValueError("NBA_PERSONNEL_DUPLICATE_EVENT")
    cutoff = card.get("as_of_utc", card.get("requested_as_of_utc")) or card.get("pit", {}).get("requested_as_of_utc")
    model.utc(cutoff)
    out.mkdir(parents=True, exist_ok=False)
    coverage = []
    for parent in card["forecasts"]:
        eid = parent["event_id"]
        try:
            if eid not in lookup:
                raise ValueError("NBA_PERSONNEL_EVENT_INPUT_MISSING")
            row = lookup[eid]
            event, baseline = row["event"], row["baseline"]
            if model.utc(event["cutoff_utc"]) != model.utc(cutoff) or model.utc(event["start_time_utc"]) != model.utc(parent["start_time_utc"]):
                raise ValueError("NBA_PERSONNEL_PARENT_EVENT_TIME_MISMATCH")
            if baseline.get("parent_forecast_sha256") != model.digest(parent) or baseline["model_id"] != parent["model_id"]:
                raise ValueError("NBA_PERSONNEL_PARENT_FORECAST_BINDING_MISMATCH")
            if parent.get("numerical_identity", {}).get("fitted_state_sha256") != baseline["state_sha256"]:
                raise ValueError("NBA_PERSONNEL_PARENT_FITTED_STATE_MISMATCH")
            for side in ("home", "away"):
                if event.get(side + "_team") != parent.get(side + "_team"):
                    raise ValueError("NBA_PERSONNEL_PARENT_TEAM_MISMATCH")
            diagnostics = parent.get("diagnostics", {})
            margin = diagnostics.get("home_margin", diagnostics.get("prediction", {}).get("home_margin"))
            if model.number(margin, "parent_margin") != model.number(baseline["home_margin"], "supplied_parent_margin"):
                raise ValueError("NBA_PERSONNEL_PARENT_MARGIN_MISMATCH")
            forecast = model.predict(state, row, base=inputs_path.parent)
            coverage.append({"event_id": eid, "status": "DIAGNOSTIC", "forecast": forecast})
        except (ValueError, KeyError, TypeError, OSError) as exc:
            coverage.append({"event_id": eid, "status": "BLOCKED", "reason": str(exc)})
    if card_path.read_bytes() != card_raw or config_path.read_bytes() != config_raw:
        raise ValueError("NBA_PERSONNEL_PARENT_OR_CONFIG_CHANGED")
    report = {**common_report("CARD_DIAGNOSTIC"), "parent_card_sha256": hashlib.sha256(card_raw).hexdigest(),
              "config_sha256": hashlib.sha256(config_raw).hexdigest(), "coverage": coverage,
              "completed_count": sum(r["status"] == "DIAGNOSTIC" for r in coverage),
              "blocked_count": sum(r["status"] == "BLOCKED" for r in coverage),
              "state_sha256": state["state_sha256"], "inputs_sha256": config["inputs"]["sha256"]}
    write(out / "report.json", report)
    return report
