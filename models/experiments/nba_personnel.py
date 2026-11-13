"""Source-bound projected-minutes residual challenger; margin only, research only.

The reference rotation must describe the retained baseline's participation
assumption. Coefficients are learned from earlier out-of-sample baseline errors;
no player receives a hand-assigned point impact. Source byte binding is not
provider authentication or proof that normalized inputs were correctly extracted.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from numbers import Real
from pathlib import Path
import re

import numpy as np

MODEL_ID = "nba.projected_minutes.residual_margin.research.v1"
SCHEMA = "nba-projected-minutes-fit.v1"
FEATURE_POLICY = "signed_projected_minus_reference_minutes_div48.no_intercept.v1"
ALPHA = 1.0
MIN_TRAINING_EVENTS = 20  # Engineering floor only; never a qualification threshold.
SHA = re.compile(r"^[0-9a-f]{64}$")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def utc(value):
    if not isinstance(value, str):
        raise ValueError("NBA_PERSONNEL_AWARE_TIMESTAMP_REQUIRED")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("NBA_PERSONNEL_AWARE_TIMESTAMP_REQUIRED") from exc
    if result.tzinfo is None:
        raise ValueError("NBA_PERSONNEL_AWARE_TIMESTAMP_REQUIRED")
    return result.astimezone(timezone.utc)


def number(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or not math.isfinite(float(value)):
        raise ValueError("NBA_PERSONNEL_INVALID_NUMBER:" + name)
    return float(value)


def observed_margin(value):
    result = number(value, "observed_home_margin")
    if not result.is_integer() or result == 0:
        raise ValueError("NBA_PERSONNEL_FINAL_MARGIN_MUST_BE_NONZERO_INTEGER")
    return result


def identity(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("NBA_PERSONNEL_IDENTITY_REQUIRED:" + name)
    return value


def source(reference, base, cutoff, *, expected=None, expected_sha256=None):
    """Bind exact normalized consumed values, bytes and declared chronology.

    The envelope is normalized evidence, not an authentication claim about its
    upstream provider. Exactly one semantic object or content digest is required.
    """
    required = {"path", "sha256", "retrieved_at_utc", "provider", "source_uri", "data_pointer"}
    if not isinstance(reference, dict) or not required <= set(reference):
        raise ValueError("NBA_PERSONNEL_SOURCE_REFERENCE_REQUIRED")
    if (expected is None) == (expected_sha256 is None):
        raise ValueError("NBA_PERSONNEL_SOURCE_SEMANTIC_BINDING_REQUIRED")
    identity(reference["provider"], "source_provider")
    identity(reference["source_uri"], "source_uri")
    if not isinstance(reference["sha256"], str) or not SHA.fullmatch(reference["sha256"]):
        raise ValueError("NBA_PERSONNEL_SOURCE_HASH_REQUIRED")
    raw = (Path(base) / reference["path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("NBA_PERSONNEL_SOURCE_BYTES_MISMATCH")
    envelope = json.loads(raw)
    if envelope.get("schema") != "nba-personnel-normalized-evidence.v1":
        raise ValueError("NBA_PERSONNEL_SOURCE_ENVELOPE_REQUIRED")
    for key in ("provider", "source_uri", "retrieved_at_utc", "provider_updated_at_utc"):
        if envelope.get(key) != reference.get(key):
            raise ValueError("NBA_PERSONNEL_SOURCE_METADATA_MISMATCH:" + key)
    retrieved = utc(reference["retrieved_at_utc"])
    if retrieved > cutoff:
        raise ValueError("NBA_PERSONNEL_SOURCE_RETRIEVED_AFTER_CUTOFF")
    if reference.get("provider_updated_at_utc") is not None:
        if utc(reference["provider_updated_at_utc"]) > retrieved:
            raise ValueError("NBA_PERSONNEL_PROVIDER_TIME_AFTER_RETRIEVAL")
    pointer = reference["data_pointer"]
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("NBA_PERSONNEL_SOURCE_JSON_POINTER_REQUIRED")
    selected = envelope
    try:
        for key in pointer[1:].split("/"):
            key = key.replace("~1", "/").replace("~0", "~")
            selected = selected[int(key)] if isinstance(selected, list) else selected[key]
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("NBA_PERSONNEL_SOURCE_JSON_POINTER_INVALID") from exc
    target_hash = digest(expected) if expected is not None else expected_sha256
    if digest(selected) != target_hash:
        raise ValueError("NBA_PERSONNEL_SOURCE_VALUE_BINDING_MISMATCH")
    return {"provider": reference["provider"], "source_uri": reference["source_uri"],
            "sha256": reference["sha256"], "retrieved_at_utc": reference["retrieved_at_utc"],
            "provider_updated_at_utc": reference.get("provider_updated_at_utc"),
            "data_pointer": pointer, "selected_value_sha256": target_hash,
            "provider_authenticity": "NOT_ASSESSED", "bytes_verified": True,
            "normalized_values_verified": True}


def binding(role, event, values):
    return {"role": role, "event": {k: event[k] for k in
            ("event_id", "home_id", "away_id", "start_time_utc", "cutoff_utc")}, "values": values}


def parent_training(parent):
    return {k: parent[k] for k in ("model_id", "state_sha256", "training_event_ids",
            "training_max_available_at_utc", "personnel_adjustment_included", "reference_rotation_policy")}


def features(row, base):
    event = row["event"]
    eid = identity(event["event_id"], "event_id")
    home, away = (identity(event[s + "_id"], s) for s in ("home", "away"))
    if home == away:
        raise ValueError("NBA_PERSONNEL_SELF_MATCH")
    cutoff, start = utc(event["cutoff_utc"]), utc(event["start_time_utc"])
    if cutoff >= start:
        raise ValueError("NBA_PERSONNEL_CUTOFF_NOT_PRESTART")
    parent = row["baseline"]
    identity(parent["model_id"], "parent_model_id")
    if not isinstance(parent.get("state_sha256"), str) or not SHA.fullmatch(parent["state_sha256"]):
        raise ValueError("NBA_PERSONNEL_PARENT_STATE_HASH_REQUIRED")
    if parent.get("personnel_adjustment_included") is not False:
        raise ValueError("NBA_PERSONNEL_DOUBLE_COUNT_OR_UNKNOWN_BASELINE")
    if parent.get("reference_rotation_policy") != "BASELINE_PARTICIPATION_REFERENCE":
        raise ValueError("NBA_PERSONNEL_REFERENCE_ROTATION_BINDING_REQUIRED")
    ids = parent.get("training_event_ids")
    if (not isinstance(ids, list) or not ids
            or any(not isinstance(i, str) or not i.strip() for i in ids)
            or len(set(ids)) != len(ids) or eid in ids):
        raise ValueError("NBA_PERSONNEL_BASELINE_NOT_OUT_OF_SAMPLE")
    if utc(parent["training_max_available_at_utc"]) >= cutoff:
        raise ValueError("NBA_PERSONNEL_BASELINE_TRAINING_AFTER_CUTOFF")
    parent_margin = number(parent["home_margin"], "baseline_home_margin")
    training = parent_training(parent)
    receipts = [source(parent["source"], base, cutoff,
                       expected=binding("baseline_forecast", event, {**training, "home_margin": parent["home_margin"]})),
                source(parent["state_source"], base, cutoff, expected_sha256=parent["state_sha256"]),
                source(parent["training_source"], base, cutoff,
                       expected={"role": "parent_training", "values": training})]
    packet = row["personnel"]
    roster = packet["roster_by_team"]
    if set(roster) != {home, away}:
        raise ValueError("NBA_PERSONNEL_ROSTER_TEAM_CONFLICT")
    for team in (home, away):
        if (not isinstance(roster[team], list) or len(roster[team]) < 5
                or len(set(roster[team])) != len(roster[team])
                or any(not isinstance(p, str) or not p.strip() for p in roster[team])):
            raise ValueError("NBA_PERSONNEL_ROSTER_INVALID")
    if set(roster[home]) & set(roster[away]):
        raise ValueError("NBA_PERSONNEL_PLAYER_ON_BOTH_TEAMS")
    receipts.append(source(packet["roster_source"], base, cutoff, expected=binding("roster", event, roster)))
    seen, values, conditional = set(), {}, []
    totals = {team: [0., 0.] for team in (home, away)}
    for player in packet["players"]:
        tid, pid = player["team_id"], identity(player["player_id"], "player_id")
        if tid not in roster or pid not in roster[tid] or pid in seen:
            raise ValueError("NBA_PERSONNEL_PLAYER_IDENTITY_CONFLICT")
        seen.add(pid)
        status = player["status"]
        if status not in {"AVAILABLE", "OUT", "LIMITED", "QUESTIONABLE", "DOUBTFUL", "UNKNOWN"}:
            raise ValueError("NBA_PERSONNEL_STATUS_INVALID")
        if status == "UNKNOWN":
            raise ValueError("NBA_PERSONNEL_UNKNOWN_AVAILABILITY")
        expected = number(player["expected_minutes"], "expected_minutes")
        reference = number(player["reference_minutes"], "reference_minutes")
        if not 0 <= expected <= 48 or not 0 <= reference <= 48:
            raise ValueError("NBA_PERSONNEL_MINUTES_OUT_OF_RANGE")
        if status == "OUT" and expected != 0:
            raise ValueError("NBA_PERSONNEL_OUT_WITH_POSITIVE_MINUTES")
        for field in ("minutes_method", "reference_minutes_method"):
            identity(player[field], field)
        assumptions = player["scenario_assumptions"]
        if not isinstance(assumptions, list) or any(not isinstance(x, str) or not x.strip() for x in assumptions):
            raise ValueError("NBA_PERSONNEL_SCENARIO_ASSUMPTIONS_INVALID")
        if status in {"LIMITED", "QUESTIONABLE", "DOUBTFUL"}:
            scenario = player.get("conditional_on")
            if not assumptions or scenario not in {"ACTIVE", "OUT"} or (scenario == "OUT" and expected != 0):
                raise ValueError("NBA_PERSONNEL_UNRESOLVED_SCENARIO")
            conditional.append({"player_id": pid, "conditional_on": scenario, "assumptions": assumptions})
        status_values = {k: player[k] for k in ("team_id", "player_id", "status")}
        minutes_values = {k: player[k] for k in ("team_id", "player_id", "expected_minutes", "reference_minutes",
                                               "minutes_method", "reference_minutes_method", "scenario_assumptions")}
        minutes_values["conditional_on"] = player.get("conditional_on")
        receipts.append(source(player["status_source"], base, cutoff, expected=binding("status", event, status_values)))
        receipts.append(source(player["minutes_source"], base, cutoff, expected=binding("minutes", event, minutes_values)))
        totals[tid][0] += expected
        totals[tid][1] += reference
        values[pid] = (1 if tid == home else -1) * (expected - reference) / 48.
    if seen != set(roster[home]) | set(roster[away]):
        raise ValueError("NBA_PERSONNEL_ROTATION_COVERAGE_INCOMPLETE")
    if any(abs(value - 240.) > 1e-8 for pair in totals.values() for value in pair):
        raise ValueError("NBA_PERSONNEL_ROTATION_MINUTES_NOT_240")
    return {"event_id": eid, "cutoff_utc": event["cutoff_utc"], "start_time_utc": event["start_time_utc"],
            "parent_model_id": parent["model_id"], "parent_state_sha256": parent["state_sha256"],
            "parent_home_margin": parent_margin, "features": values, "conditional_scenarios": conditional,
            "source_receipts": sorted({digest(r): r for r in receipts}.values(), key=digest),
            "input_sha256": digest({k: row[k] for k in ("event", "baseline", "personnel")})}


def fit(rows, *, base, fit_cutoff_utc):
    if len(rows) < MIN_TRAINING_EVENTS:
        raise ValueError("NBA_PERSONNEL_TRAINING_POPULATION_INSUFFICIENT")
    cutoff = utc(fit_cutoff_utc)
    prepared, targets, evidence = [], [], []
    ids = set()
    for row in sorted(rows, key=lambda r: (utc(r["event"]["start_time_utc"]), r["event"]["event_id"])):
        f = features(row, base)
        if f["event_id"] in ids:
            raise ValueError("NBA_PERSONNEL_DUPLICATE_TRAINING_EVENT")
        ids.add(f["event_id"])
        result = row["result"]
        available = utc(result["available_at_utc"])
        if not utc(f["start_time_utc"]) < available <= cutoff:
            raise ValueError("NBA_PERSONNEL_TRAINING_RESULT_CHRONOLOGY")
        if f["conditional_scenarios"]:
            # Observed outcomes cannot silently validate an unverified hypothetical lineup.
            raise ValueError("NBA_PERSONNEL_CONDITIONAL_TRAINING_NOT_SUPPORTED")
        if utc(result["source"]["retrieved_at_utc"]) < available:
            raise ValueError("NBA_PERSONNEL_RESULT_SOURCE_PREDATES_AVAILABILITY")
        evidence.append(source(result["source"], base, cutoff, expected=binding("result", row["event"], {k: result[k] for k in ("home_margin", "available_at_utc")})))
        target = observed_margin(result["home_margin"]) - f["parent_home_margin"]
        if not math.isfinite(target):
            raise ValueError("NBA_PERSONNEL_NONFINITE_RESIDUAL")
        prepared.append(f)
        targets.append(target)
    if len({f["parent_model_id"] for f in prepared}) != 1:
        raise ValueError("NBA_PERSONNEL_MIXED_PARENT_PROCEDURES")
    players = sorted(set().union(*(set(f["features"]) for f in prepared)))
    x = np.array([[f["features"].get(p, 0.) for p in players] for f in prepared], dtype=float)
    if not np.any(x):
        raise ValueError("NBA_PERSONNEL_NO_ROTATION_VARIATION")
    beta = np.linalg.solve(x.T @ x + ALPHA * np.eye(len(players)), x.T @ np.asarray(targets))
    if not np.isfinite(beta).all():
        raise ValueError("NBA_PERSONNEL_NONFINITE_FIT")
    state = {"schema": SCHEMA, "model_id": MODEL_ID, "parent_model_id": prepared[0]["parent_model_id"],
             "feature_policy": FEATURE_POLICY, "ridge_alpha": ALPHA, "intercept": 0.,
             "players": players, "coefficient": beta.tolist(), "fit_cutoff_utc": fit_cutoff_utc,
             "training_event_ids": sorted(ids), "training_n": len(ids),
             "training_input_sha256": digest(prepared), "training_result_sha256": digest({"y": targets, "sources": evidence}),
             "training_max_result_available_at_utc": max((r["result"]["available_at_utc"] for r in rows), key=utc),
             "source_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             "provider_authenticity": "NOT_ASSESSED", "pit_eligibility": "NOT_ASSESSED",
             "predictive_validation": "UNVALIDATED", "market_features_used": False, "action_authority": False}
    state["state_sha256"] = digest(state)
    return state


def predict(state, row, *, base):
    if state.get("state_sha256") != digest({k: v for k, v in state.items() if k != "state_sha256"}):
        raise ValueError("NBA_PERSONNEL_STATE_HASH_MISMATCH")
    if state.get("schema") != SCHEMA or state.get("model_id") != MODEL_ID or state.get("feature_policy") != FEATURE_POLICY:
        raise ValueError("NBA_PERSONNEL_STATE_IDENTITY_CONFLICT")
    if state.get("source_code_sha256") != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError("NBA_PERSONNEL_FITTED_CODE_CHANGED")
    if (state.get("ridge_alpha") != ALPHA or state.get("intercept") != 0
            or len(state.get("coefficient", [])) != len(state.get("players", []))
            or not state.get("players") or len(set(state["players"])) != len(state["players"])):
        raise ValueError("NBA_PERSONNEL_STATE_STRUCTURE_INVALID")
    for value in state["coefficient"]:
        number(value, "coefficient")
    if utc(state["training_max_result_available_at_utc"]) > utc(state["fit_cutoff_utc"]):
        raise ValueError("NBA_PERSONNEL_STATE_TRAINING_CHRONOLOGY")
    f = features(row, base)
    if f["parent_model_id"] != state["parent_model_id"]:
        raise ValueError("NBA_PERSONNEL_PARENT_MODEL_MISMATCH")
    if f["event_id"] in state["training_event_ids"] or utc(state["fit_cutoff_utc"]) >= utc(f["cutoff_utc"]):
        raise ValueError("NBA_PERSONNEL_EVALUATION_NOT_AFTER_TRAINING")
    unknown = set(f["features"]) - set(state["players"])
    if any(f["features"][p] != 0 for p in unknown):
        raise ValueError("NBA_PERSONNEL_UNSEEN_PLAYER_EFFECT_REQUIRED:" + ",".join(sorted(unknown)))
    vector = np.array([f["features"].get(p, 0.) for p in state["players"]])
    delta = float(np.dot(vector, state["coefficient"]))
    mean = f["parent_home_margin"] + delta
    if not math.isfinite(delta) or not math.isfinite(mean):
        raise ValueError("NBA_PERSONNEL_NONFINITE_FORECAST")
    result = {"schema": "nba-personnel-forecast.v1", "model_id": MODEL_ID, "event_id": f["event_id"],
              "parent_model_id": f["parent_model_id"], "parent_state_sha256": f["parent_state_sha256"],
              "state_sha256": state["state_sha256"], "input_sha256": f["input_sha256"],
              "cutoff_utc": f["cutoff_utc"], "start_time_utc": f["start_time_utc"],
              "home_margin": mean, "parent_home_margin": f["parent_home_margin"], "personnel_margin_delta": delta,
              "components": {p: float(vector[i] * state["coefficient"][i]) for i, p in enumerate(state["players"])},
              "features_used": f["features"], "source_receipts": f["source_receipts"],
              "conditional_scenarios": f["conditional_scenarios"],
              "forecast_semantics": "CONDITIONAL_MARGIN_POINT_ESTIMATE" if f["conditional_scenarios"] else "MARGIN_POINT_ESTIMATE",
              "p_home": None, "cover_probability": None, "total": None,
              "input_status": "USED", "predictive_validation": "UNVALIDATED",
              "provider_authenticity": "NOT_ASSESSED", "pit_eligibility": "NOT_ASSESSED",
              "publication_allowed": False, "action_authority": False,
              "limitations": ["NORMALIZED_SOURCE_EXTRACTION_NOT_AUTHENTICATED", "NO_FITTED_PROBABILITY_OR_TOTAL_HEAD",
                              "REFERENCE_ROTATION_POLICY_REQUIRES_BASELINE_RECONCILIATION"]}
    result["forecast_sha256"] = digest(result)
    return result
