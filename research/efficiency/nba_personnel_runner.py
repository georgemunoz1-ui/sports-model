"""Immutable runner for the separately identified NBA projected-minutes arm."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from collections import Counter
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


def _audited_prediction(state,row,base):
    from pipelines.cards.missingness import seal_audit
    forecast=model.predict(state,row,base=base)
    packet=row["personnel"]
    f=model.features(row,base)
    players=packet["players"]
    probes={}
    for label, changed in (("missing_rotation_member",players[:-1]),("duplicate_rotation_member",players+[players[0]])):
        try:
            model.features({**row,"personnel":{**packet,"players":changed}},base)
        except ValueError as exc:
            probes[label]=str(exc)
        else:
            raise ValueError("NBA_MISSINGNESS_PROBE_ACCEPTED:"+label)
    reordered=model.predict(state,{**row,"personnel":{**packet,"players":list(reversed(players))}},base=base)
    if abs(reordered["home_margin"]-forecast["home_margin"])>1e-10:
        raise ValueError("NBA_PERSONNEL_ORDER_CHANGES_MARGIN")
    details={"status":"ROTATION_COVERAGE_PROBED","probes":probes,
             "counts_by_status":{k:sum(p["status"]==k for p in players) for k in sorted({p["status"] for p in players})},
             "player_feature_values":f["features"],
             "unseen_with_zero_minute_delta":sorted(set(f["features"])-set(state["players"])),
             "absent_fit_columns_zero_filled":sorted(set(state["players"])-set(f["features"])),
             "withheld_source_status":"Missing or conflicting role/rotation evidence refuses; unseen nonzero effects cannot be imputed.",
             "historical_support":"UNMEASURED","limits":"UNREVIEWED","refresh":{"status":"NO_PAIRED_PARENT"}}
    # The fitted source hash covers only native forecast bytes. Seal the outer pair separately.
    return forecast, seal_audit(league="nba",model_id=forecast["model_id"],event_id=forecast["event_id"],
                                products=["home_margin_points"],forecast=forecast,details=details)


def _audit_check(forecast,receipt):
    from pipelines.cards.missingness import verify_audit
    if not verify_audit(receipt,league="nba",model_id=forecast["model_id"],event_id=forecast["event_id"],
                        products=["home_margin_points"],forecast=forecast):
        raise ValueError("NBA_PERSONNEL_MISSINGNESS_READBACK_FAILED")


def _evaluation_inputs(rows):
    """Inventory original JSON rows without assuming their containers are valid."""
    from pipelines.cards.missingness import content_digest
    if not isinstance(rows, list):
        raise ValueError("NBA_PERSONNEL_EVALUATION_LIST_REQUIRED")
    out = []
    for index, row in enumerate(rows):
        event = row.get("event") if isinstance(row, dict) else None
        out.append({"input_row_index": index, "input_row_sha256": content_digest(row),
                    "declared_event_id": event.get("event_id") if isinstance(event, dict) else None,
                    "row_container": type(row).__name__, "event_container": type(event).__name__})
    return out


def _exclusion_binding(report, exclusion, row_index):
    eid = exclusion.get("event_id")
    supplied = isinstance(eid, str) and bool(eid.strip())
    scope_id = eid if supplied else f"UNRESOLVED_EVALUATION_ROW:{report['run_id']}:{row_index}"
    context = {key: report[key] for key in ("run_id", "created_at_utc", "model_id", "mode", "evidence_scope",
                                           "input_sha256", "fit_cutoff_utc", "state_sha256", "code_sha256")}
    return dict(league="nba", model_id=model.MODEL_ID, event_id=scope_id, products=["coverage"],
                forecast={"exclusion": {k:v for k,v in exclusion.items() if k != "missingness_audit"},
                          "input_row_index": row_index, "run_context": context,
                          "input_inventory_row": report["evaluation_inventory"][row_index]})


def verify_experiment_report(report, *, input_path=None):
    """Check the whole retained inventory; a supplied input independently rebuilds it.

    The writer always supplies the original input path. Receipt integrity alone
    does not establish provider authenticity if a caller regenerates all bytes.
    """
    from pipelines.cards.missingness import content_digest, verify_audit
    if not verify_audit(report.get("missingness_audit"), league="nba", model_id=model.MODEL_ID,
            event_id=report["run_id"], products=["coverage"],
            forecast={k:v for k,v in report.items() if k != "missingness_audit"}):
        raise ValueError("NBA_PERSONNEL_EXCLUSION_READBACK_RUN_BINDING")
    inventory = report["evaluation_inventory"]
    count = report["evaluation_opportunities"]
    if (type(count) is not int or count < 0 or not isinstance(inventory, list) or len(inventory) != count
            or any(not isinstance(entry, dict) or type(entry.get("input_row_index")) is not int for entry in inventory)
            or [entry.get("input_row_index") for entry in inventory] != list(range(count))):
        raise ValueError("NBA_PERSONNEL_EVALUATION_INVENTORY_READBACK")
    if input_path is not None:
        raw = Path(input_path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != report["input_sha256"]:
            raise ValueError("NBA_PERSONNEL_INPUT_READBACK")
        packet = json.loads(raw)
        original = _evaluation_inputs(packet["evaluation"])
        actual = [{key: entry[key] for key in source} for entry, source in zip(inventory, original, strict=True)]
        if (content_digest(original) != content_digest(actual)
                or len(packet["training"]) != report["training_opportunities"]
                or packet["fit_cutoff_utc"] != report["fit_cutoff_utc"]
                or packet["evidence_scope"] != report["evidence_scope"]):
            raise ValueError("NBA_PERSONNEL_SOURCE_INVENTORY_READBACK")
    if "state_sha256" not in report:
        if (report["status"] != "BLOCKED" or report["n_paired"] != 0
                or any(entry["disposition"] != "FIT_BLOCKED" or entry["forecast_emitted"] is not False
                       or entry["forecast_sha256"] is not None or entry["reason"] != report["reason"]
                       for entry in inventory)):
            raise ValueError("NBA_PERSONNEL_FIT_REFUSAL_READBACK")
        return {"input_reconstructed": input_path is not None, "evaluation_rows": count}
    excluded = report["exclusions"]
    expected = {entry["input_row_index"]: entry for entry in inventory if entry["disposition"] == "EXCLUDED"}
    paired = [entry for entry in inventory if entry["disposition"] == "PAIRED"]
    paired_count, excluded_count = report["n_paired"], report["n_excluded"]
    if (type(paired_count) is not int or type(excluded_count) is not int
            or len(excluded) != excluded_count or len(expected) != excluded_count or len(paired) != paired_count
            or paired_count + excluded_count != count):
        raise ValueError("NBA_PERSONNEL_EXCLUSION_READBACK")
    status = "COMPLETED" if paired_count and not excluded_count else "PARTIAL" if paired_count else "BLOCKED"
    if report["status"] != status or any(entry["forecast_emitted"] is not True or not entry["forecast_sha256"] for entry in paired):
        raise ValueError("NBA_PERSONNEL_EVALUATION_DISPOSITION_READBACK")
    indices = set()
    for exclusion in excluded:
        receipt = exclusion.get("missingness_audit")
        index = (receipt or {}).get("details", {}).get("input_row_index")
        if (type(index) is not int or index in indices or index not in expected
                or content_digest(exclusion.get("event_id")) != content_digest(expected[index]["declared_event_id"])
                or exclusion["reason"] != expected[index]["reason"]
                or receipt["details"]["forecast_emitted"] is not expected[index]["forecast_emitted"]
                or not verify_audit(receipt, **_exclusion_binding(report, exclusion, index))):
            raise ValueError("NBA_PERSONNEL_EXCLUSION_READBACK")
        indices.add(index)
    if indices != set(expected):
        raise ValueError("NBA_PERSONNEL_EXCLUSION_READBACK")
    return {"input_reconstructed": input_path is not None, "evaluation_rows": count}


def _write_experiment_report(path, report, input_path):
    from pipelines.cards.missingness import seal_audit
    if hashlib.sha256(Path(input_path).read_bytes()).hexdigest() != report["input_sha256"]:
        raise ValueError("NBA_PERSONNEL_INPUT_READBACK")
    if "missingness_audit" not in report:
        report["missingness_audit"] = seal_audit(league="nba", model_id=model.MODEL_ID,
            event_id=report["run_id"], products=["coverage"], forecast=dict(report), details={
                "scope": "RUN_WITH_FITTED_STATE", "input_sha256": report["input_sha256"],
                "inventory_basis": "ORIGINAL_EVALUATION_ROWS_IN_INPUT_ORDER",
                "feature_values": None, "provider_authenticity": "NOT_ASSESSED"})
    write(path, report)
    stored = json.loads(Path(path).read_bytes())
    if stored != report:
        raise ValueError("NBA_PERSONNEL_EXPERIMENT_REPORT_READBACK")
    verify_experiment_report(stored, input_path=input_path)


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
    inventory = _evaluation_inputs(packet["evaluation"])
    report["evaluation_inventory"] = inventory
    try:
        state = model.fit(packet["training"], base=p.parent, fit_cutoff_utc=packet["fit_cutoff_utc"])
    except (ValueError, KeyError, TypeError, OSError) as exc:
        from pipelines.cards.missingness import seal_audit
        report.update(status="BLOCKED", reason=str(exc), n_paired=0)
        for entry in inventory:
            entry.update(disposition="FIT_BLOCKED", forecast_emitted=False, forecast_sha256=None, reason=str(exc))
        report["missingness_audit"] = seal_audit(league="nba", model_id=model.MODEL_ID,
            event_id=report["run_id"], products=["coverage"], forecast=dict(report), details={
                "scope": "RUN_WITHOUT_FITTED_STATE", "failed_stage": "FIT", "reason": str(exc),
                "observation_state": "ACQUISITION_FAILURE" if isinstance(exc, OSError) else "UNRESOLVED_IDENTITY_OR_COVERAGE",
                "forecast_emitted": False, "feature_values": None, "historical_support": "NOT_ASSESSED",
                "evaluation_opportunities_unforecasted": report["evaluation_opportunities"]})
        _write_experiment_report(out / "report.json", report, p)
        return report
    write(out / "state.json", state)
    ids, forecasts, paired, excluded = set(), [], [], []
    audit_by_event={}
    exclusion_context = []
    for index, row in enumerate(packet["evaluation"]):
        eid = None
        stage, emitted = "IDENTITY", False
        forecast = None
        try:
            if not isinstance(row, dict):
                raise ValueError("NBA_PERSONNEL_EVALUATION_ROW_OBJECT_REQUIRED")
            event = row.get("event")
            if not isinstance(event, dict):
                raise ValueError("NBA_PERSONNEL_EVALUATION_EVENT_OBJECT_REQUIRED")
            eid = event.get("event_id")
            if not isinstance(eid, str) or not eid.strip():
                raise ValueError("NBA_PERSONNEL_EVALUATION_EVENT_ID_REQUIRED")
            if eid in ids:
                raise ValueError("NBA_PERSONNEL_DUPLICATE_EVALUATION_EVENT")
            ids.add(eid)
            stage = "PREDICTION"
            forecast,receipt = _audited_prediction(state,row,p.parent)
            audit_by_event[eid]=receipt
            forecasts.append(forecast)
            stage, emitted = "RESULT_RECONCILIATION", True
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
            inventory[index].update(disposition="PAIRED", forecast_emitted=True,
                                    forecast_sha256=forecast["forecast_sha256"], reason=None)
        except (ValueError, KeyError, TypeError, OSError, AttributeError) as exc:
            excluded.append({"event_id": eid, "reason": str(exc)})
            inventory[index].update(disposition="EXCLUDED", forecast_emitted=emitted,
                forecast_sha256=forecast["forecast_sha256"] if emitted else None, reason=str(exc))
            exclusion_context.append({"input_row_index": index, "failed_stage": stage,
                "forecast_emitted": emitted, "feature_values": None,
                "declared_event_id_present": isinstance(eid, str) and bool(eid.strip()),
                "identity_validation": "NATIVE_PREDICTION_COMPLETED" if emitted else "NOT_ESTABLISHED_BY_THIS_RECEIPT",
                "observation_state": "ACQUISITION_FAILURE" if isinstance(exc, OSError) else "UNRESOLVED_IDENTITY_OR_COVERAGE",
                "interpretation": "Evaluation coverage only; no numerical replacement or missingness-effect estimate."})
    report.update(status="COMPLETED" if paired and not excluded else "PARTIAL" if paired else "BLOCKED",
                  state_sha256=state["state_sha256"], n_paired=len(paired), n_excluded=len(excluded),
                  baseline_mae=sum(r["parent_absolute_error"] for r in paired) / len(paired) if paired else None,
                  challenger_mae=sum(r["challenger_absolute_error"] for r in paired) / len(paired) if paired else None,
                  uncertainty="NOT_ESTIMATED; exploratory point summary is not qualification", exclusions=excluded)
    from pipelines.cards.missingness import seal_audit
    for exclusion, details in zip(excluded, exclusion_context, strict=True):
        exclusion["missingness_audit"] = seal_audit(
            **_exclusion_binding(report, exclusion, details["input_row_index"]), details=details)
    if p.read_bytes() != raw:
        raise ValueError("NBA_PERSONNEL_INPUT_CHANGED_DURING_RUN")
    write(out / "forecasts.json", forecasts)
    write(out / "missingness.json", audit_by_event)
    stored=json.loads((out/"missingness.json").read_bytes())
    for f in json.loads((out/"forecasts.json").read_bytes()):
        _audit_check(f,stored[f["event_id"]])
    write(out / "paired.json", paired)
    _write_experiment_report(out / "report.json", report, p)
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
    counts=Counter(r["event"]["event_id"] for r in rows)
    parent_counts=Counter(parent["event_id"] for parent in card["forecasts"])
    cutoff = card.get("as_of_utc", card.get("requested_as_of_utc")) or card.get("pit", {}).get("requested_as_of_utc")
    model.utc(cutoff)
    out.mkdir(parents=True, exist_ok=False)
    coverage = []
    for parent in card["forecasts"]:
        eid = parent["event_id"]
        try:
            if counts[eid]>1 or parent_counts[eid]>1:
                raise ValueError("NBA_PERSONNEL_DUPLICATE_EVENT")
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
            forecast,receipt = _audited_prediction(state,row,inputs_path.parent)
            coverage.append({"event_id": eid, "status": "DIAGNOSTIC", "forecast": forecast, "missingness_audit":receipt})
        except (ValueError, KeyError, TypeError, OSError) as exc:
            from pipelines.cards.missingness import seal_audit
            blocked={"event_id":eid,"status":"BLOCKED","reason":str(exc),"cutoff_utc":cutoff}
            blocked["missingness_audit"]=seal_audit(league="nba",event_id=eid,model_id=model.MODEL_ID,
                products=["coverage"],forecast=dict(blocked),details={"status":"UNRESOLVED_IDENTITY_OR_COVERAGE",
                "reason":str(exc),"source_review":"REQUIRED"})
            coverage.append(blocked)
    if card_path.read_bytes() != card_raw or config_path.read_bytes() != config_raw:
        raise ValueError("NBA_PERSONNEL_PARENT_OR_CONFIG_CHANGED")
    report = {**common_report("CARD_DIAGNOSTIC"), "parent_card_sha256": hashlib.sha256(card_raw).hexdigest(),
              "config_sha256": hashlib.sha256(config_raw).hexdigest(), "coverage": coverage,
              "completed_count": sum(r["status"] == "DIAGNOSTIC" for r in coverage),
              "blocked_count": sum(r["status"] == "BLOCKED" for r in coverage),
              "state_sha256": state["state_sha256"], "inputs_sha256": config["inputs"]["sha256"]}
    write(out / "report.json", report)
    stored=json.loads((out/"report.json").read_bytes())
    if stored!=report:
        raise ValueError("NBA_PERSONNEL_REPORT_READBACK_MISMATCH")
    for c in stored["coverage"]:
        if c["status"]=="DIAGNOSTIC":
            _audit_check(c["forecast"],c["missingness_audit"])
        else:
            from pipelines.cards.missingness import verify_audit
            if not verify_audit(c.get("missingness_audit"),league="nba",event_id=c["event_id"],
                                model_id=model.MODEL_ID,products=["coverage"],
                                forecast={k:v for k,v in c.items() if k!="missingness_audit"}):
                raise ValueError("NBA_PERSONNEL_REFUSAL_READBACK")
    return report
