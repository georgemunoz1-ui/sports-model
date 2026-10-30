"""Opt-in NBA margin challengers. No probability, total, market or selector path.

The input is a normalized, source-bound comparison dataset, not a card. Source
receipts establish local byte identity; they do not certify historical availability
or canonical registration. Unknown availability is rejected for fitting.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import numpy as np

SCHEMA = "nba.forecast_combination.v1"
TARGET = "home_minus_away_full_game_ot_points"
FEATURES = ("shooting_net_difference", "turnover_net_difference", "rebounding_net_difference")
FACTORS = ("oTS", "oTOV", "ORB", "dTS", "dTOV", "DRB")
FACTOR_VERSION = "databallr.nba.six_factor.boxscore.positive_good.v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("MISSING_TIMESTAMP")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("FINITE_NUMBER_REQUIRED")
    return float(value)


def source_errors(source, row, root):
    """Verify a normalized source against retained JSON bytes and raw receipt.

Raw payload extraction must be independently reviewed. A matching hash is not
proof that the parsed semantics or provider's model are correct.
"""
    errors = []
    if not isinstance(source, dict):
        return ["SOURCE_MISSING"]
    try:
        base = Path(root).resolve()
        path = (base / source["artifact_path"]).resolve()
        if not path.is_relative_to(base):
            raise ValueError("PATH_OUTSIDE_DATASET")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["artifact_hash"]:
            errors.append("ARTIFACT_HASH_MISMATCH")
        payload = json.loads(raw)
        if payload != source["payload"]:
            errors.append("PAYLOAD_BINDING_MISMATCH")
        receipt = payload["raw_receipt"]
        raw_path = (base / receipt["path"]).resolve()
        if not raw_path.is_relative_to(base):
            raise ValueError("PATH_OUTSIDE_DATASET")
        if hashlib.sha256(raw_path.read_bytes()).hexdigest() != receipt["sha256"]:
            errors.append("RAW_HASH_MISMATCH")
        if receipt.get("extraction_review") != "REVIEWED":
            errors.append("EXTRACTION_NOT_REVIEWED")
        if row.get("capture_schema") or payload.get("acquisition"):
            try:
                from research.nba_pregame_capture import SCHEMA as CAPTURE_SCHEMA, verify_capture_source
                if row.get("capture_schema") != CAPTURE_SCHEMA:
                    raise ValueError("CAPTURE_SCHEMA_MISMATCH")
                verify_capture_source(payload, row, base)
            except (KeyError, ValueError, TypeError, OSError, StopIteration) as exc:
                errors.append("CAPTURE_PROVENANCE:" + str(exc))
        for key in ("event_id", "league", "home", "away", "target"):
            if payload.get(key) != row.get(key):
                errors.append("IDENTITY_MISMATCH:" + key)
        if timestamp(payload["scheduled_start"]) != timestamp(row["scheduled_start"]):
            errors.append("IDENTITY_MISMATCH:scheduled_start")
        if not payload.get("source_model_version"):
            errors.append("SOURCE_VERSION_UNKNOWN")
        if payload.get("historical_record_type") != "live":
            errors.append("NOT_LIVE_HISTORY")
        if payload.get("availability_basis") != "captured_before_cutoff":
            errors.append("POINT_IN_TIME_UNPROVEN")
        times = {}
        for key, value in (("source_as_of", payload.get("source_as_of")),
                           ("captured_at", payload.get("captured_at")),
                           ("feature_cutoff", row.get("feature_cutoff")),
                           ("scheduled_start", row.get("scheduled_start"))):
            try:
                times[key] = timestamp(value)
            except (ValueError, TypeError):
                errors.append("TIMESTAMP_UNKNOWN_OR_INVALID:" + key)
        for first, second, strict in (("source_as_of", "captured_at", False),
                                      ("captured_at", "feature_cutoff", False),
                                      ("feature_cutoff", "scheduled_start", True)):
            if first in times and second in times:
                if times[first] > times[second] or (strict and times[first] == times[second]):
                    errors.extend(["SOURCE_CHRONOLOGY", "TIMESTAMP_ORDER:" + first + ">=" + second])
    except (KeyError, ValueError, TypeError, OSError) as exc:
        errors.append("INVALID_SOURCE:" + type(exc).__name__)
    return sorted(set(errors))


def factor_features(payload):
    if payload.get("source_model_version") != FACTOR_VERSION:
        raise ValueError("FACTOR_VERSION_MISMATCH")
    if payload.get("units") != "points_per_100_possessions" or payload.get("sign") != "positive_good":
        raise ValueError("FACTOR_SEMANTICS_MISMATCH")
    home, away = payload["values"]["home_factors"], payload["values"]["away_factors"]
    pairs = (("oTS", "dTS"), ("oTOV", "dTOV"), ("ORB", "DRB"))
    return [sum(number(home[k]) - number(away[k]) for k in pair) for pair in pairs]


def audit_row(row, root, stage="C1", train_before=None):
    if stage not in ("C1", "C2"):
        raise ValueError("UNKNOWN_STAGE")
    reasons = []
    if row.get("league") != "NBA" or row.get("target") != TARGET:
        reasons.append("UNSUPPORTED_LEAGUE_OR_TARGET")
    if not row.get("event_id") or not row.get("home") or not row.get("away") or row.get("home") == row.get("away"):
        reasons.append("INVALID_EVENT_IDENTITY")
    if row.get("evidence_population") != "point_in_time_live":
        reasons.append("DIAGNOSTIC_POPULATION")
    keys = ("B0", "B1", "databallr") if stage == "C2" else ("B0", "B1")
    for key in keys:
        source = row.get("sources", {}).get(key)
        reasons.extend(key + ":" + r for r in source_errors(source, row, root))
        try:
            payload = source["payload"]
            if key == "databallr":
                factor_features(payload)
            else:
                number(payload["values"]["home_margin"])
                if not payload.get("forecast_identity"):
                    reasons.append(key + ":FORECAST_IDENTITY_MISSING")
        except (KeyError, TypeError, ValueError):
            reasons.append(key + ":VALUES_INVALID")
    if train_before is not None:
        try:
            end = timestamp(train_before)
            outcome = row["outcome"]
            start = timestamp(row["scheduled_start"])
            if not start < timestamp(outcome["available_at"]) < end:
                reasons.append("OUTCOME_CHRONOLOGY")
            if outcome.get("status") != "FINAL":
                reasons.append("OUTCOME_NOT_FINAL")
            number(outcome["home_margin"])
            base = Path(root).resolve()
            path = (base / outcome["artifact_path"]).resolve()
            if not path.is_relative_to(base):
                raise ValueError("PATH_OUTSIDE_DATASET")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != outcome["artifact_hash"]:
                reasons.append("OUTCOME_HASH_MISMATCH")
            if json.loads(raw) != outcome["payload"]:
                reasons.append("OUTCOME_PAYLOAD_MISMATCH")
            for k in ("event_id", "league", "home", "away", "target"):
                if outcome["payload"].get(k) != row.get(k):
                    reasons.append("OUTCOME_IDENTITY_MISMATCH:" + k)
            for k in ("home_margin", "status", "available_at"):
                if outcome["payload"].get(k) != outcome.get(k):
                    reasons.append("OUTCOME_VALUE_MISMATCH:" + k)
        except (KeyError, ValueError, TypeError, OSError):
            reasons.append("OUTCOME_INVALID")
    return sorted(set(reasons))


def audit(rows, root, stage="C1", train_before=None):
    counts = Counter(row.get("event_id") for row in rows)
    identities = Counter(event_key(row) for row in rows)
    records = []
    for row in rows:
        reasons = audit_row(row, root, stage, train_before)
        if counts[row.get("event_id")] > 1 or identities[event_key(row)] > 1:
            reasons.append("DUPLICATE_EVENT")
        records.append({"event_id": row.get("event_id"), "eligible": not reasons,
                        "exclusions": reasons})
    return {"schema": SCHEMA, "stage": stage, "row_count": len(rows),
            "unique_events": len(identities), "eligible_events": sum(r["eligible"] for r in records),
            "exclusion_counts": dict(Counter(x for r in records for x in r["exclusions"])),
            "records": records}


def event_key(row):
    try:
        start = timestamp(row.get("scheduled_start")).isoformat()
    except (ValueError, TypeError):
        start = "INVALID:" + str(row.get("event_id"))
    return (row.get("league"), row.get("home"), row.get("away"), start)


def stratum(row, stage):
    keys = ("B0", "B1", "databallr") if stage == "C2" else ("B0", "B1")
    return {k: {field: row["sources"][k]["payload"][field]
                for field in ("source_model_version", "historical_record_type")} for k in keys}


def validate_protocol(protocol):
    if protocol.get("schema") != SCHEMA or protocol.get("target") != TARGET:
        raise ValueError("PROTOCOL_SCHEMA_OR_TARGET")
    timestamp(protocol["frozen_at"])
    for k in ("alpha_ridge", "weight_ridge", "factor_ridge"):
        if number(protocol[k]) <= 0:
            raise ValueError("POSITIVE_REGULARIZATION_REQUIRED")
    if type(protocol.get("min_training_events")) is not int or protocol["min_training_events"] < 3:
        raise ValueError("MINIMUM_TRAINING_EVENTS_INVALID")
    if protocol.get("weight_bounds") != [0, 1] or protocol.get("features") != list(FEATURES):
        raise ValueError("UNSUPPORTED_PROCEDURE")


def fit(rows, root, protocol, train_before, stage="C1"):
    """One source-version stratum, fixed ridge penalties, no outcome-driven tuning.

    C2 first fits C1 on the SAME complete-source events, then fits a regularized
    residual increment. This prevents source availability from changing attribution.
    """
    validate_protocol(protocol)
    if timestamp(train_before) <= timestamp(protocol["frozen_at"]):
        raise ValueError("FIT_CUTOFF_PRECEDES_PROTOCOL")
    report = audit(rows, root, stage, train_before)
    eligible = sorted((r for r, a in zip(rows, report["records"]) if a["eligible"]),
                      key=lambda r: (timestamp(r["scheduled_start"]), r["event_id"]))
    if len(eligible) < protocol["min_training_events"]:
        return {"schema": SCHEMA, "stage": stage, "status": "BLOCKED_INSUFFICIENT_ELIGIBLE_EVENTS",
                "fitted": False, "audit": report, "protocol_hash": digest(protocol)}
    strata = {digest(stratum(r, stage)) for r in eligible}
    if len(strata) != 1:
        raise ValueError("MIXED_SOURCE_VERSION_STRATA")
    b = np.array([r["sources"]["B0"]["payload"]["values"]["home_margin"] for r in eligible], dtype=float)
    d = np.array([r["sources"]["B1"]["payload"]["values"]["home_margin"] for r in eligible], dtype=float) - b
    y = np.array([r["outcome"]["home_margin"] for r in eligible], dtype=float) - b
    n = len(y)
    # Solve the two-variable convex quadratic exactly, including bound candidates.
    x = np.column_stack((np.ones(n), d))
    h = x.T @ x / n + np.diag([protocol["alpha_ridge"], protocol["weight_ridge"]])
    g = x.T @ y / n
    unconstrained = np.linalg.solve(h, g)
    candidates = [(float((y - w*d).mean() / (1+protocol["alpha_ridge"])), w) for w in (0., 1.)]
    if 0 <= unconstrained[1] <= 1:
        candidates.append(tuple(unconstrained))
    def objective(pair):
        a, w = pair
        return float(np.mean((y-a-w*d)**2) + protocol["alpha_ridge"]*a*a + protocol["weight_ridge"]*w*w)
    alpha, weight = min(candidates, key=objective)
    scaler, gamma = None, None
    if stage == "C2":
        z = np.array([factor_features(r["sources"]["databallr"]["payload"]) for r in eligible])
        mean, scale = z.mean(axis=0), z.std(axis=0)
        scale = np.where(scale == 0, 1., scale)
        zs = (z-mean)/scale
        gamma = np.linalg.solve(zs.T@zs/n + protocol["factor_ridge"]*np.eye(len(FEATURES)),
                                zs.T@(y-alpha-weight*d)/n).tolist()
        scaler = {"mean": mean.tolist(), "scale": scale.tolist(), "features": list(FEATURES)}
    state = {"schema": SCHEMA, "stage": stage, "status": "FITTED_UNVALIDATED", "fitted": True,
             "created_at": datetime.now(timezone.utc).isoformat(),
             "alpha": float(alpha), "weight": float(weight), "gamma": gamma, "scaler": scaler,
             "train_before": train_before, "trained_events": [r["event_id"] for r in eligible],
             "trained_event_keys": [list(event_key(r)) for r in eligible],
             "training_rows_hash": digest(eligible), "source_stratum": stratum(eligible[0], stage),
             "protocol_hash": digest(protocol), "code_hash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             "uncertainty_model": None, "probabilities": None, "action_authority": False,
             "canonical_registration": False, "audit": report}
    state["state_hash"] = digest(state)
    return state


def predict(row, root, state, protocol):
    validate_protocol(protocol)
    if not state.get("fitted") or state.get("state_hash") != digest({k:v for k,v in state.items() if k != "state_hash"}):
        raise ValueError("INVALID_FITTED_STATE")
    if state["protocol_hash"] != digest(protocol):
        raise ValueError("PROTOCOL_MISMATCH")
    if state["code_hash"] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError("CODE_MISMATCH")
    stage = state["stage"]
    reasons = audit_row(row, root, stage)
    if timestamp(row["feature_cutoff"]) < timestamp(state["train_before"]):
        reasons.append("FIT_AFTER_FORECAST_CUTOFF")
    if row["event_id"] in state["trained_events"] or list(event_key(row)) in state["trained_event_keys"]:
        reasons.append("TRAINING_EVENT_REUSE")
    try:
        if stratum(row, stage) != state["source_stratum"]:
            reasons.append("SOURCE_VERSION_MISMATCH")
    except (KeyError, TypeError):
        reasons.append("SOURCE_VERSION_MISSING")
    if reasons:
        # Report a separately labeled B0 only when its own evidence is admissible.
        b0 = row.get("sources", {}).get("B0")
        b0_ok = not source_errors(b0, row, root) and row.get("league") == "NBA" and row.get("target") == TARGET
        value = None
        try:
            if b0_ok:
                value = number(b0["payload"]["values"]["home_margin"])
        except (KeyError, TypeError, ValueError):
            b0_ok = False
        return {"event_id": row.get("event_id"), "requested_stage": stage,
                "emitted_stage": "B0_FALLBACK" if b0_ok else None,
                "home_margin": value if b0_ok else None, "challenger_emitted": False,
                "reasons": sorted(set(reasons)), "probabilities": None, "action_authority": False}
    b = number(row["sources"]["B0"]["payload"]["values"]["home_margin"])
    d = number(row["sources"]["B1"]["payload"]["values"]["home_margin"])
    value = b + state["alpha"] + state["weight"]*(d-b)
    if stage == "C2":
        scaler = state["scaler"]
        z = (np.array(factor_features(row["sources"]["databallr"]["payload"]))-scaler["mean"])/scaler["scale"]
        value += float(z @ state["gamma"])
    return {"event_id": row["event_id"], "requested_stage": stage, "emitted_stage": stage,
            "home_margin": number(value), "challenger_emitted": True,
            "execution_class": "RECONSTRUCTION_DIAGNOSTIC" if timestamp(state["created_at"]) > timestamp(row["feature_cutoff"]) else "LOCAL_RESEARCH_UNREGISTERED",
            "state_hash": state["state_hash"], "probabilities": None, "action_authority": False}
