"""Strict input controls for the separately identified CFB personnel v2 arm.

This module constructs features from supplied, byte-bound evidence. It does not
infer a starter, turn a status into a probability, or authenticate a provider.
Historical original-time evidence remains a separate experiment classification.
"""
from __future__ import annotations

import hashlib
import json
import math
from numbers import Real
from pathlib import Path
import re


SCHEMA = "cfb.personnel-input.v2"
TRANSFORM_ID = "cfb.explicit_qb_participation_and_returning_snap_ratios.v2"
SOURCED_FIELDS = {"event_id", "team_id", "quarterback.player_id", "quarterback.status", "quarterback.prior_pass_attempt_share",
                  "returning_snaps.offense", "returning_snaps.defense"}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("CFB_PERSONNEL_IDENTIFIER_REQUIRED:" + name)
    return value


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("CFB_PERSONNEL_FINITE_NUMBER_REQUIRED:" + name)
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("CFB_PERSONNEL_FINITE_NUMBER_REQUIRED:" + name) from exc
    if not math.isfinite(result):
        raise ValueError("CFB_PERSONNEL_FINITE_NUMBER_REQUIRED:" + name)
    return result


def _share(record, name):
    if not isinstance(record, dict):
        raise ValueError("CFB_PERSONNEL_PARTICIPATION_REQUIRED:" + name)
    numerator = _number(record.get("numerator"), name + ".numerator")
    denominator = _number(record.get("denominator"), name + ".denominator")
    if not numerator.is_integer() or not denominator.is_integer() or not 0 <= numerator <= denominator or denominator <= 0:
        raise ValueError("CFB_PERSONNEL_PARTICIPATION_COUNTS_INVALID:" + name)
    _text(record.get("population_definition"), name + ".population_definition")
    return numerator / denominator


def _read_json(reference):
    sha = reference.get("sha256")
    if not isinstance(sha, str) or re.fullmatch("[0-9a-f]{64}", sha) is None:
        raise ValueError("CFB_PERSONNEL_SOURCE_SHA256_REQUIRED")
    try:
        raw = Path(_text(reference.get("path"), "path")).read_bytes()
    except OSError as exc:
        raise ValueError("CFB_PERSONNEL_SOURCE_BYTES_UNAVAILABLE") from exc
    if hashlib.sha256(raw).hexdigest() != sha:
        raise ValueError("CFB_PERSONNEL_SOURCE_BYTES_MISMATCH")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("CFB_PERSONNEL_DUPLICATE_SOURCE_JSON_KEY")
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError("CFB_PERSONNEL_NONFINITE_SOURCE_JSON")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("CFB_PERSONNEL_STRUCTURED_SOURCE_REQUIRED") from exc


def _pointer(value, pointer):
    """Resolve an RFC 6901 JSON pointer without evaluating arbitrary code."""
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        raise ValueError("CFB_PERSONNEL_JSON_POINTER_REQUIRED")
    if pointer == "":
        return value
    for token in pointer[1:].split("/"):
        if re.search(r"~(?![01])", token):
            raise ValueError("CFB_PERSONNEL_JSON_POINTER_INVALID_ESCAPE")
        token = token.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(value, list):
                if not re.fullmatch(r"0|[1-9][0-9]*", token):
                    raise ValueError("CFB_PERSONNEL_JSON_POINTER_INVALID_INDEX")
                value = value[int(token)]
            elif isinstance(value, dict):
                value = value[token]
            else:
                raise KeyError(token)
        except (KeyError, IndexError) as exc:
            raise ValueError("CFB_PERSONNEL_SOURCE_FIELD_MISSING:" + pointer) from exc
    return value


def schedule_coverage(games, records, event, cutoff, *, history_seasons=3, label_lag_hours=24):
    """Census within the supplied schedule, not a provider-completeness claim.

    Both team rows must exist for every eligible FBS/FBS event in the efficiency
    fit window. FCS history is disclosed separately and never reclassified FBS.
    """
    from models.experiments.cfb_efficiency import utc
    import pandas as pd

    cutoff = utc(cutoff)
    lower_season = event["season"] - history_seasons
    relevant = [g for g in games if lower_season < g["season"] <= event["season"]
                and g.get("completed")
                and utc(g["start_time_utc"]) + pd.Timedelta(hours=label_lag_hours) < cutoff]
    expected = sorted((g["event_id"], str(g[side + "_id"])) for g in relevant
                      if g.get("home_division") == "fbs" and g.get("away_division") == "fbs"
                      for side in ("home", "away"))
    by_event = {g["event_id"]: g for g in games}
    conflicts = []
    for record in records:
        game = by_event.get(record["event_id"])
        if game is None or any(type(record.get(key)) is not int or record[key] != game[key] for key in ("season", "week")):
            conflicts.append([record["event_id"], str(record["team_id"])])
    present = {(r["event_id"], str(r["team_id"])) for r in records
               if utc(r["available_at_utc"]) < cutoff
               and [r["event_id"], str(r["team_id"])] not in conflicts
               and lower_season < r["season"] <= event["season"]}
    missing = [list(pair) for pair in expected if pair not in present]
    outside = sorted(g["event_id"] for g in relevant
                     if g.get("home_division") != "fbs" or g.get("away_division") != "fbs")
    matchup_supported = event.get("home_division") == "fbs" and event.get("away_division") == "fbs"
    report = {"schema": "cfb.supplied-schedule-coverage.v1", "event_id": event["event_id"],
              "cutoff_utc": cutoff.isoformat(), "scope": "FBS_VS_FBS",
              "expected_team_game_rows": len(expected), "missing_team_game_rows": missing,
              "metric_schedule_conflicts": conflicts,
              "out_of_scope_history_event_ids": outside, "matchup_supported": matchup_supported,
              "status": "COMPLETE_WITHIN_SUPPLIED_SCHEDULE" if not missing and not conflicts else "INCOMPLETE",
              "provider_schedule_completeness": "NOT_ESTABLISHED", "cross_population_validation": "NOT_ASSESSED"}
    report["receipt_sha256"] = _digest(report)
    return report


def values(example):
    """Validate explicit QB/participation evidence and return the six v2 values."""
    from models.experiments.cfb_efficiency import utc

    evidence = example.get("personnel_evidence")
    if not isinstance(evidence, dict) or evidence.get("schema") != SCHEMA:
        raise ValueError("CFB_PERSONNEL_SOURCE_BOUND_INPUTS_REQUIRED")
    if evidence.get("event_id") != example["event_id"]:
        raise ValueError("CFB_PERSONNEL_EVENT_MISMATCH")
    event, cutoff = example["event"], utc(example["cutoff_utc"])
    coverage = example.get("personnel_schedule_coverage")
    if not isinstance(coverage, dict):
        raise ValueError("CFB_PERSONNEL_SCHEDULE_COVERAGE_REQUIRED")
    if coverage.get("receipt_sha256") != _digest({k: v for k, v in coverage.items() if k != "receipt_sha256"}):
        raise ValueError("CFB_PERSONNEL_COVERAGE_HASH_MISMATCH")
    if coverage.get("event_id") != example["event_id"] or utc(coverage["cutoff_utc"]) != cutoff:
        raise ValueError("CFB_PERSONNEL_COVERAGE_IDENTITY_MISMATCH")
    if not coverage.get("matchup_supported"):
        raise ValueError("CFB_PERSONNEL_FBS_VS_FBS_REQUIRED")
    if coverage.get("metric_schedule_conflicts"):
        raise ValueError("CFB_PERSONNEL_METRIC_SCHEDULE_SEASON_WEEK_MISMATCH")
    if coverage.get("missing_team_game_rows") or coverage.get("status") != "COMPLETE_WITHIN_SUPPLIED_SCHEDULE":
        raise ValueError("CFB_PERSONNEL_INCOMPLETE_SCHEDULE_HISTORY")

    features = {}
    for side in ("home", "away"):
        record = evidence.get(side)
        if not isinstance(record, dict) or record.get("team_id") != event[side + "_id"]:
            raise ValueError("CFB_PERSONNEL_TEAM_MISMATCH:" + side)
        qb = record.get("quarterback")
        if not isinstance(qb, dict):
            raise ValueError("CFB_EXPECTED_QUARTERBACK_REQUIRED:" + side)
        _text(qb.get("player_id"), side + ".quarterback.player_id")
        if qb.get("status") not in {"CONFIRMED", "PROJECTED"}:
            raise ValueError("CFB_EXPECTED_QUARTERBACK_UNKNOWN:" + side)
        probability = _number(qb.get("expected_participation_probability"), side + ".participation_probability")
        if not 0 <= probability <= 1:
            raise ValueError("CFB_PERSONNEL_PROBABILITY_RANGE")
        _text(qb.get("participation_method"), side + ".participation_method")
        if not isinstance(qb.get("workload_limitations"), list):
            raise ValueError("CFB_QB_WORKLOAD_ASSUMPTIONS_REQUIRED")
        _share(qb.get("prior_pass_attempt_share"), side + ".prior_pass_attempt_share")
        features[side + "_qb_availability"] = probability
        if not isinstance(record.get("returning_snaps"), dict):
            raise ValueError("CFB_PERSONNEL_PARTICIPATION_REQUIRED:" + side)
        for unit in ("offense", "defense"):
            features[side + "_" + unit + "_returning_snap_share"] = _share(
                record.get("returning_snaps", {}).get(unit), side + "." + unit + ".returning_snaps")
        sources = record.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ValueError("CFB_PERSONNEL_AVAILABILITY_PROOF_REQUIRED")
        covered = set()
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError("CFB_PERSONNEL_SOURCE_OBJECT_REQUIRED")
            _text(source.get("source"), "source")
            if source.get("event_id") != example["event_id"] or source.get("team_id") != event[side + "_id"]:
                raise ValueError("CFB_PERSONNEL_SOURCE_IDENTITY_MISMATCH")
            try:
                observed, retrieved = utc(source["observed_at_utc"]), utc(source["retrieved_at_utc"])
                available = utc(source["available_at_utc"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("CFB_PERSONNEL_AWARE_SOURCE_TIMES_REQUIRED") from exc
            if observed > retrieved or available < observed or max(retrieved, available) >= cutoff:
                raise ValueError("CFB_PERSONNEL_AFTER_CUTOFF")
            raw = _read_json(source)
            fields = source.get("field_bindings")
            if not isinstance(fields, dict) or not fields or not set(fields) <= SOURCED_FIELDS:
                raise ValueError("CFB_PERSONNEL_SOURCE_FIELD_BINDINGS_REQUIRED")
            for field, pointer in fields.items():
                expected = {**record, "event_id": evidence["event_id"]}
                for part in field.split("."):
                    expected = expected[part]
                if _digest(_pointer(raw, pointer)) != _digest(expected):
                    raise ValueError("CFB_PERSONNEL_SOURCE_VALUE_MISMATCH:" + field)
                covered.add(field)
        if not SOURCED_FIELDS <= covered:
            raise ValueError("CFB_PERSONNEL_SOURCE_FIELD_COVERAGE_INCOMPLETE")
        assumption = record.get("participation_assumption")
        if not isinstance(assumption, dict):
            raise ValueError("CFB_PERSONNEL_PARTICIPATION_ASSUMPTION_REQUIRED")
        declared = _read_json(assumption)
        if not isinstance(declared, dict) or declared.get("schema") != "cfb.qb-participation-assumption.v1":
            raise ValueError("CFB_PERSONNEL_PARTICIPATION_ASSUMPTION_SCHEMA")
        if declared.get("event_id") != example["event_id"] or declared.get("team_id") != event[side + "_id"]:
            raise ValueError("CFB_PERSONNEL_ASSUMPTION_IDENTITY_MISMATCH")
        assumption_time = utc(declared.get("created_at_utc"))
        if assumption_time >= cutoff or assumption_time < max(utc(s["retrieved_at_utc"]) for s in sources):
            raise ValueError("CFB_PERSONNEL_ASSUMPTION_AFTER_CUTOFF")
        expected_assumption = {key: qb[key] for key in (
            "player_id", "expected_participation_probability", "participation_method", "workload_limitations")}
        if _digest(declared.get("assumptions")) != _digest(expected_assumption):
            raise ValueError("CFB_PERSONNEL_ASSUMPTION_VALUE_MISMATCH")
        if declared.get("evidence_source_sha256") != sorted({s["sha256"] for s in sources}):
            raise ValueError("CFB_PERSONNEL_ASSUMPTION_SOURCE_BINDING_MISMATCH")
    return features


def sources(example):
    """Raw source references, retained separately from the feature values."""
    evidence = example.get("personnel_evidence", {})
    result = [s for side in ("home", "away") for s in evidence.get(side, {}).get("sources", [])]
    for side in ("home", "away"):
        reference = evidence.get(side, {}).get("participation_assumption")
        if reference:
            record = _read_json(reference)
            result.append({**reference, "source": "declared-assumption:cfb.qb-participation-assumption.v1",
                "evidence_type": "ASSUMPTION_NOT_PROVIDER_REPORT", "event_id": record["event_id"],
                "team_id": record["team_id"], "retrieved_at_utc": record["created_at_utc"],
                "observed_at_utc": record["created_at_utc"]})
    return result
