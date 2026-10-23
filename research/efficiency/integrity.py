"""Source reconciliation and component receipts for efficiency experiments.

These receipts prove byte bindings and locally observed chronology. They do not
authenticate a provider, grant canonical grading, or manufacture a trusted
timestamp. The existing canonical registry and its requirements are unchanged.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from research.validation_registry import ArtifactStore, canonical_bytes, content_id
from scripts.register_mlb_calibration import registry_lock

SCHEMA = "efficiency.component_forecast_receipt.v1"
SHADOW_SCHEMA = "efficiency.local_shadow_registration.v1"


class IntegrityError(ValueError):
    """A malformed or contradictory evidence contract."""


def _now() -> datetime:
    # Intentionally not a caller-controlled CLI timestamp.
    return datetime.now(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise IntegrityError("AWARE_TIMESTAMP_REQUIRED")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntegrityError("INVALID_TIMESTAMP") from exc
    if parsed.tzinfo is None:
        raise IntegrityError("NAIVE_TIMESTAMP")
    return parsed.astimezone(timezone.utc)


def _number(value: Any, *, nonnegative=False, integral=False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise IntegrityError("FINITE_NUMBER_REQUIRED")
    if nonnegative and value < 0:
        raise IntegrityError("NEGATIVE_COUNT")
    if integral and (type(value) is not int or value < 0):
        raise IntegrityError("INTEGER_COUNT_REQUIRED")
    return float(value)


def _sha(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise IntegrityError("SHA256_REQUIRED")
    return value


def _label(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntegrityError("NONEMPTY_ID_REQUIRED")
    return value


def _json_value(value: Any):
    if isinstance(value, float) and not math.isfinite(value):
        raise IntegrityError("NONFINITE_VALUE")
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise IntegrityError("STRING_KEYS_REQUIRED")
        for key, item in value.items():
            if key in {"action_authority", "market_features_used", "market_overlay_enabled", "publication_allowed"} and item not in (False, None, "OFF"):
                raise IntegrityError("MARKET_ACTION_FIREWALL")
            _json_value(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _json_value(item)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise IntegrityError("JSON_VALUE_REQUIRED")


def _report(issues, **extra):
    return {"status": "QUARANTINED" if issues else "PASS", "issues": sorted(set(issues)), **extra}


def reconcile_rate(numerator: Any, denominator: Any, *, reported_rate=None,
                   scale=1.0, bounded=True, tolerance=1e-8) -> dict:
    """Check a measured rate without inventing a zero for an absent denominator."""
    issues = []
    try:
        n, d, s = _number(numerator), _number(denominator), _number(scale)
        if d <= 0 or s <= 0:
            issues.append("NONPOSITIVE_DENOMINATOR_OR_SCALE")
        if bounded and not 0 <= n <= d:
            issues.append("NUMERATOR_OUTSIDE_DENOMINATOR")
        value = n / d * s if not issues else None
        if reported_rate is not None and value is not None and abs(_number(reported_rate) - value) > tolerance:
            issues.append("REPORTED_RATE_MISMATCH")
    except IntegrityError as exc:
        issues.append(str(exc)); value = None
    return _report(issues, rate=value)


def resolve_event_identity(*, provider_id: str | None, name: str | None,
                           participants: Sequence[Mapping]) -> dict:
    """Resolve only the two event participants by stable ID or verified alias.

    participants: [{id, name, verified_aliases: [str, ...]}, ...]. No fuzzy,
    nickname stripping, or global name matching is performed.
    """
    if len(participants) != 2:
        return _report(["TWO_EVENT_PARTICIPANTS_REQUIRED"], resolved_id=None)
    if any(p.get("id") is None or isinstance(p.get("id"), bool) for p in participants):
        return _report(["MISSING_PARTICIPANT_IDS"], resolved_id=None)
    ids = [str(p.get("id", "")) for p in participants]
    if len(set(ids)) != 2 or any(not p for p in ids):
        return _report(["AMBIGUOUS_PARTICIPANT_IDS"], resolved_id=None)
    def norm(x):
        return " ".join(str(x).casefold().split())
    names = []
    if name is not None:
        for participant in participants:
            aliases = [participant.get("name", "")] + list(participant.get("verified_aliases", []))
            if norm(name) in {norm(a) for a in aliases if a}:
                names.append(str(participant["id"]))
    if provider_id is not None:
        candidate = str(provider_id)
        if candidate not in ids:
            return _report(["PROVIDER_ID_OUTSIDE_EVENT"], resolved_id=None)
        if len(names) > 1:
            return _report(["AMBIGUOUS_ALIAS"], resolved_id=None)
        if names and names != [candidate]:
            return _report(["PROVIDER_ID_NAME_CONFLICT"], resolved_id=None)
        return _report([], resolved_id=candidate, method="PROVIDER_ID")
    if len(names) != 1:
        return _report(["AMBIGUOUS_ALIAS" if names else "UNRESOLVED_IDENTITY"], resolved_id=None)
    return _report([], resolved_id=names[0], method="VERIFIED_EVENT_ALIAS")


def reconcile_sources(records: Sequence[Mapping], *, identity_fields=("event_id", "team_id"),
                      value_fields=("points",)) -> dict:
    """Quarantine contradictory records; provider priority never resolves them."""
    if not records:
        return _report(["SOURCE_RECORDS_REQUIRED"], record_count=0)
    issues, seen = [], {}
    for row in records:
        try:
            _json_value(dict(row))
            key = tuple(_label(row.get(field)) for field in identity_fields)
            values = {field: row[field] for field in value_fields}
            if any(value is None for value in values.values()):
                raise IntegrityError("MISSING_SOURCE_VALUE")
            if key in seen and seen[key] != values:
                issues.append("CONTRADICTORY_SOURCE_VALUES:" + ":".join(key))
            seen[key] = values
        except (IntegrityError, KeyError) as exc:
            issues.append(str(exc))
    return _report(issues, record_count=len(records), unique_identities=len(seen), selected_source=None)


def reconcile_team_boxscore(team: Mapping, players: Sequence[Mapping] | None = None, *,
                            regulation_minutes=240, overtime_periods=0, minutes_decimal_places=1) -> dict:
    """Reconcile NBA numeric totals with explicit player/team rebound semantics.

    Team fields: points, fgm,fga,fg3m,ftm,fta,orb,drb,tov; optional fg3a,
    rebounds, team_orb, team_drb. orb/drb are PLAYER rebounds; uncredited team
    rebounds belong only in team_orb/team_drb. No silent addition is performed.
    Player fields: player_id, minutes, points, status and optional rebound totals.
    A provided player table is treated as complete and must reconcile.
    """
    issues = []
    try:
        _json_value(dict(team))
        counts = {key: _number(team[key], nonnegative=True, integral=True)
                  for key in ("points", "fgm", "fga", "fg3m", "ftm", "fta", "orb", "drb", "tov")}
        for made, attempted in (("fgm", "fga"), ("ftm", "fta")):
            if counts[made] > counts[attempted]:
                issues.append("MAKES_EXCEED_ATTEMPTS:" + made)
        if counts["fg3m"] > counts["fgm"]:
            issues.append("THREES_EXCEED_FIELD_GOALS")
        if "fg3a" in team:
            threes = _number(team["fg3a"], nonnegative=True, integral=True)
            if not counts["fg3m"] <= threes <= counts["fga"]:
                issues.append("INVALID_THREE_POINT_ATTEMPTS")
        if 2 * counts["fgm"] + counts["fg3m"] + counts["ftm"] != counts["points"]:
            issues.append("SHOOTING_POINTS_MISMATCH")
        if "rebounds" in team and _number(team["rebounds"], nonnegative=True, integral=True) != counts["orb"] + counts["drb"]:
            issues.append("PLAYER_REBOUND_TOTAL_MISMATCH")
        for field in ("team_orb", "team_drb"):
            if field in team:
                _number(team[field], nonnegative=True, integral=True)
        if team.get("rebound_scope", "PLAYER") != "PLAYER":
            issues.append("AMBIGUOUS_REBOUND_SCOPE")
    except (IntegrityError, KeyError) as exc:
        issues.append(str(exc)); counts = {}
    minutes_total = points_total = None
    if players is not None:
        ids, minutes_total, points_total = set(), 0.0, 0
        try:
            if not players:
                raise IntegrityError("EMPTY_PLAYER_TABLE")
            if type(overtime_periods) is not int or overtime_periods < 0:
                raise IntegrityError("INVALID_OVERTIME_COUNT")
            if type(minutes_decimal_places) is not int or not 0 <= minutes_decimal_places <= 3:
                raise IntegrityError("INVALID_MINUTES_PRECISION")
            expected_minutes = _number(regulation_minutes, nonnegative=True) + 25 * overtime_periods
            for player in players:
                _json_value(dict(player))
                player_id = _label(player.get("player_id"))
                if player_id in ids:
                    issues.append("DUPLICATE_PLAYER_ID")
                ids.add(player_id)
                points = _number(player.get("points"), nonnegative=True, integral=True)
                minutes = _number(player.get("minutes"), nonnegative=True)
                if minutes > 48 + 5 * overtime_periods:
                    issues.append("PLAYER_MINUTES_EXCEED_GAME_DURATION")
                if player.get("status") in {"DNP", "INACTIVE", "OUT"} and (points or minutes):
                    issues.append("DNP_WITH_PRODUCTION")
                points_total += points; minutes_total += minutes
            if "points" in counts and points_total != counts["points"]:
                issues.append("PLAYER_POINTS_SUM_MISMATCH")
            rounding_tolerance = 0.5 * 10 ** (-minutes_decimal_places) * len(players) + 1e-8
            if abs(minutes_total - expected_minutes) > rounding_tolerance:
                issues.append("PLAYER_MINUTES_SUM_MISMATCH")
            for field in ("orb", "drb"):
                if field in counts and all(field in player for player in players):
                    total = sum(_number(player[field], nonnegative=True, integral=True) for player in players)
                    if total != counts[field]:
                        issues.append("PLAYER_REBOUND_SUM_MISMATCH:" + field)
        except IntegrityError as exc:
            issues.append(str(exc))
    return _report(issues, player_table_checked=players is not None,
                   player_points_sum=points_total, player_minutes_sum=minutes_total,
                   minutes_decimal_places=minutes_decimal_places,
                   rebound_convention="PLAYER_ORB_DRB_EXCLUDE_UNCREDITED_TEAM_REBOUNDS")


def reconcile_nba_game(game: Mapping) -> dict:
    """Convenience adapter for the NBA efficiency normalized-game schema."""
    issues, reports = [], {}
    if not game.get("event_id") or not game.get("home_id") or not game.get("away_id"):
        issues.append("EVENT_AND_TEAM_IDS_REQUIRED")
    if game.get("home_id") == game.get("away_id"):
        issues.append("IDENTICAL_OPPONENT_IDS")
    for side in ("home", "away"):
        stats = dict(game.get(side + "_stats") or {})
        stats["points"] = game.get(side + "_score")
        reports[side] = reconcile_team_boxscore(stats, game.get(side + "_players"),
                                              overtime_periods=game.get("overtime_periods", 0),
                                              minutes_decimal_places=game.get("minutes_decimal_places", 1))
        issues.extend(side + ":" + issue for issue in reports[side]["issues"])
    return _report(issues, sides=reports)


def _lookup(inputs, path):
    value = inputs
    for key in path.split("."):
        if isinstance(value, list):
            try:
                value = value[int(key)]
            except (ValueError, IndexError):
                raise IntegrityError("COMPONENT_INPUT_PATH_MISSING:" + path) from None
        elif isinstance(value, dict) and key in value:
            value = value[key]
        else:
            raise IntegrityError("COMPONENT_INPUT_PATH_MISSING:" + path)
    return value


def _source(source: Mapping, cutoff: datetime, mode: str) -> dict:
    row = copy.deepcopy(dict(source))
    _label(row.get("source")); _sha(row.get("sha256"))
    retrieved = _time(row.get("retrieved_at_utc"))
    observed = _time(row["observed_at_utc"]) if row.get("observed_at_utc") else None
    if observed and observed > retrieved:
        raise IntegrityError("SOURCE_OBSERVED_AFTER_RETRIEVAL")
    if row.get("path"):
        path = Path(row["path"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise IntegrityError("SOURCE_BYTES_HASH_MISMATCH")
        row["bytes_verified"] = True
    else:
        row["bytes_verified"] = False
    if mode == "SHADOW" and (retrieved > cutoff or (observed and observed > cutoff)):
        raise IntegrityError("SHADOW_SOURCE_AFTER_CUTOFF")
    available = row.get("historical_available_at_utc")
    if available:
        if _time(available) > cutoff:
            raise IntegrityError("SOURCE_AVAILABLE_AFTER_CUTOFF")
        _sha(row.get("historical_availability_evidence_sha256"))
        row["historical_availability_status"] = "ASOF_EVIDENCE_DECLARED_NOT_INDEPENDENTLY_AUTHENTICATED"
    elif retrieved <= cutoff:
        row["historical_availability_status"] = "RETRIEVAL_BEFORE_CUTOFF"
    else:
        row["historical_availability_status"] = "UNVERIFIED_LATER_RECONSTRUCTION"
    return row


def _simulation(simulation: Mapping | None):
    if simulation is None:
        return None
    sim = copy.deepcopy(dict(simulation))
    if type(sim.get("count")) is not int or sim["count"] < 1:
        raise IntegrityError("SIMULATION_COUNT_REQUIRED")
    if type(sim.get("seed")) is not int or sim["seed"] < 0:
        raise IntegrityError("SIMULATION_SEED_REQUIRED")
    for field in ("rng", "distribution_id", "draws_encoding"):
        _label(sim.get(field))
    _sha(sim.get("draws_sha256"))
    if sim.get("draws_path"):
        import numpy as np
        path = Path(sim["draws_path"])
        if not path.is_file():
            raise IntegrityError("SIMULATION_DRAW_FILE_MISSING")
        if hashlib.sha256(path.read_bytes()).hexdigest() != _sha(sim.get("draws_file_sha256")):
            raise IntegrityError("SIMULATION_DRAW_FILE_HASH_MISMATCH")
        draws = np.load(path, allow_pickle=False)
        if draws.ndim not in (1, 2) or len(draws) != sim["count"] or not np.isfinite(draws).all():
            raise IntegrityError("SIMULATION_DRAW_COUNT_OR_SUPPORT_MISMATCH")
        if hashlib.sha256(draws.tobytes(order="C")).hexdigest() != sim["draws_sha256"]:
            raise IntegrityError("SIMULATION_DRAW_ARRAY_HASH_MISMATCH")
        sim["draws_verification"] = "ARRAY_COUNT_AND_HASH_VERIFIED"
    else:
        sim["draws_verification"] = "METADATA_ONLY_NO_DRAW_FILE"
    _json_value(sim)
    return sim


def _validate_forecast(forecast):
    unsupported = []
    for key in ("p_home", "p_away", "home_win_probability", "away_win_probability"):
        if key in forecast and not 0 <= _number(forecast[key]) <= 1:
            raise IntegrityError("PROBABILITY_OUT_OF_RANGE")
    for key in ("home_score", "away_score", "total", "expected_possessions"):
        if key in forecast:
            if forecast[key] is None:
                unsupported.append(key)
            else:
                _number(forecast[key], nonnegative=True)
    return sorted(unsupported)


def _validate_identity_bindings(*, model_id, stage_id, event_id, cutoff_utc,
                                start_utc, inputs, state, forecast):
    """Bind the envelope to identities actually retained for inference.

    Hash consistency alone cannot stop a caller from re-signing an envelope
    for a different event while retaining another event's inference payload.
    Optional payload fields remain optional for legacy generic receipts, but
    any identity or timestamp supplied in the payload must agree.
    """
    event = inputs.get("event", {})
    if not isinstance(event, Mapping):
        raise IntegrityError("INPUT_EVENT_OBJECT_REQUIRED")
    for payload in (inputs, event, forecast):
        if "event_id" in payload and payload["event_id"] != event_id:
            raise IntegrityError("COMPONENT_EVENT_IDENTITY_MISMATCH")
        for key in ("start_utc", "start_time_utc"):
            if key in payload and _time(payload[key]) != _time(start_utc):
                raise IntegrityError("COMPONENT_EVENT_START_MISMATCH")
        for key in ("cutoff_utc", "forecast_cutoff_utc"):
            if key in payload and _time(payload[key]) != _time(cutoff_utc):
                raise IntegrityError("COMPONENT_EVENT_CUTOFF_MISMATCH")
    # Backend stage labels have two established aliases in the CFB runner.
    aliases = {"matchup_efficiency": "efficiency", "joint_distribution": "joint"}
    def stage(value):
        value = _label(value).lower()
        return aliases.get(value, value)
    for payload in (state, forecast):
        if "model_id" in payload and payload["model_id"] != model_id:
            raise IntegrityError("COMPONENT_MODEL_IDENTITY_MISMATCH")
        for key in ("stage", "stage_id"):
            if key in payload and stage(payload[key]) != stage(stage_id):
                raise IntegrityError("COMPONENT_STAGE_IDENTITY_MISMATCH")
    if "model_state_sha256" in forecast:
        if forecast["model_state_sha256"] != state.get("state_sha256"):
            raise IntegrityError("COMPONENT_FORECAST_STATE_MISMATCH")


def build_component_receipt(*, model_id: str, stage_id: str, event_id: str,
                            cutoff_utc: str, start_utc: str, inputs: Mapping,
                            state: Mapping, config: Mapping, code_files: Sequence[str | Path] | Mapping,
                            sources: Sequence[Mapping], components: Mapping, forecast: Mapping,
                            mode="HISTORICAL_REPLAY", simulation=None, parent_model_id=None,
                            history_max_event_time_utc=None, input_max_available_at_utc=None) -> dict:
    """Seal actual inference components, preserving inputs/state for verification.

    Components may be plain numeric values or {value, unit, input_paths,
    source_sha256, max_available_at_utc}. Plain components bind the entire input
    snapshot. This is runner-reported consumption, not an external execution proof.
    """
    if mode not in {"HISTORICAL_REPLAY", "SHADOW"}:
        raise IntegrityError("INVALID_EXECUTION_MODE")
    for value in (model_id, stage_id, event_id):
        _label(value)
    if parent_model_id is not None and parent_model_id == model_id:
        raise IntegrityError("CHILD_MUST_HAVE_DISTINCT_IDENTITY")
    cutoff, start, created = _time(cutoff_utc), _time(start_utc), _now()
    if cutoff >= start or cutoff > created:
        raise IntegrityError("INVALID_FORECAST_CHRONOLOGY")
    if mode == "SHADOW" and created >= start:
        raise IntegrityError("SHADOW_CREATED_AT_OR_AFTER_START")
    for stamp in (history_max_event_time_utc, input_max_available_at_utc):
        if stamp is not None and _time(stamp) > cutoff:
            raise IntegrityError("FEATURE_OR_LABEL_AFTER_CUTOFF")
    for value in (inputs, state, config, forecast):
        if not isinstance(value, Mapping):
            raise IntegrityError("OBJECT_REQUIRED")
        _json_value(dict(value))
    _validate_identity_bindings(model_id=model_id, stage_id=stage_id,
        event_id=event_id, cutoff_utc=cutoff_utc, start_utc=start_utc,
        inputs=inputs, state=state, forecast=forecast)
    unsupported_heads = _validate_forecast(forecast)
    if not sources or not components or not code_files:
        raise IntegrityError("SOURCES_COMPONENTS_CODE_REQUIRED")
    source_rows = [_source(row, cutoff, mode) for row in sources]
    if any(_time(source["retrieved_at_utc"]) > created for source in source_rows):
        raise IntegrityError("SOURCE_RETRIEVED_AFTER_CREATION")
    source_hashes = {row["sha256"] for row in source_rows}
    code = {}
    paths = code_files.items() if isinstance(code_files, Mapping) else ((str(path), path) for path in code_files)
    for label, path in paths:
        p = Path(path)
        if not p.is_file():
            raise IntegrityError("CODE_FILE_MISSING:" + str(p))
        code[str(label)] = hashlib.sha256(p.read_bytes()).hexdigest()
    retained = {"inputs": copy.deepcopy(dict(inputs)), "state": copy.deepcopy(dict(state)),
                "config": copy.deepcopy(dict(config)), "forecast": copy.deepcopy(dict(forecast))}
    hashes = {key + "_sha256": content_id(value) for key, value in retained.items()}
    component_rows = {}
    for name, value in components.items():
        _label(name)
        component = copy.deepcopy(dict(value)) if isinstance(value, Mapping) else {"value": value}
        numeric = component.get("value")
        if isinstance(numeric, list):
            if not numeric:
                raise IntegrityError("EMPTY_COMPONENT")
            for number in numeric:
                _number(number)
        else:
            _number(numeric)
        for path in component.get("input_paths", []):
            _lookup(retained["inputs"], _label(path))
        bound_sources = component.get("source_sha256", sorted(source_hashes))
        if not isinstance(bound_sources, list) or not bound_sources or not set(bound_sources) <= source_hashes:
            raise IntegrityError("COMPONENT_SOURCE_NOT_BOUND")
        if component.get("max_available_at_utc") and _time(component["max_available_at_utc"]) > cutoff:
            raise IntegrityError("COMPONENT_AFTER_CUTOFF")
        component.update(status="USED", input_snapshot_sha256=hashes["inputs_sha256"],
                         fitted_state_sha256=hashes["state_sha256"], source_sha256=bound_sources)
        _json_value(component)
        component_rows[name] = component
    receipt = {"schema": SCHEMA, "model_id": model_id, "stage_id": stage_id,
               "parent_model_id": parent_model_id, "event_id": event_id, "mode": mode,
               "cutoff_utc": cutoff_utc, "start_utc": start_utc, "created_at_utc": _stamp(created),
               "history_max_event_time_utc": history_max_event_time_utc,
               "input_max_available_at_utc": input_max_available_at_utc,
               **retained, **hashes, "code_sha256": code, "sources": source_rows,
               "components": component_rows, "simulation": _simulation(simulation),
               "unsupported_forecast_fields": unsupported_heads,
               "consumption_evidence": "RUNNER_REPORTED_HASH_BOUND_COMPONENTS",
               "canonical_prospective_eligible": False, "external_timestamp_verified": False,
               "predictive_validation": "NOT_ASSESSED", "publication_allowed": False,
               "action_authority": False, "market_features_used": False}
    receipt["inference_trace_sha256"] = content_id({"inputs": hashes["inputs_sha256"],
        "state": hashes["state_sha256"], "config": hashes["config_sha256"], "code": code,
        "components": component_rows, "forecast": hashes["forecast_sha256"]})
    receipt["receipt_sha256"] = content_id(receipt)
    return receipt


def verify_component_receipt(receipt: Mapping) -> dict:
    value = copy.deepcopy(dict(receipt))
    expected = _sha(value.pop("receipt_sha256", None))
    if value.get("schema") != SCHEMA or content_id(value) != expected:
        raise IntegrityError("COMPONENT_RECEIPT_HASH_MISMATCH")
    for key in ("inputs", "state", "config", "forecast"):
        if content_id(value[key]) != value[key + "_sha256"]:
            raise IntegrityError("RETAINED_SNAPSHOT_HASH_MISMATCH")
    _json_value(value)
    if value.get("canonical_prospective_eligible") is not False or value.get("external_timestamp_verified") is not False:
        raise IntegrityError("RECEIPT_CANNOT_GRANT_TRUST")
    for field in ("model_id", "stage_id", "event_id"):
        _label(value.get(field))
    _validate_identity_bindings(**{field: value[field] for field in
        ("model_id", "stage_id", "event_id", "cutoff_utc", "start_utc",
         "inputs", "state", "forecast")})
    if value.get("mode") not in {"SHADOW", "HISTORICAL_REPLAY"}:
        raise IntegrityError("INVALID_EXECUTION_MODE")
    if value.get("parent_model_id") == value["model_id"]:
        raise IntegrityError("CHILD_MUST_HAVE_DISTINCT_IDENTITY")
    cutoff, start, created = (_time(value[field]) for field in ("cutoff_utc", "start_utc", "created_at_utc"))
    if cutoff >= start or cutoff > created:
        raise IntegrityError("INVALID_FORECAST_CHRONOLOGY")
    if value["mode"] == "SHADOW" and created >= start:
        raise IntegrityError("SHADOW_CREATED_AT_OR_AFTER_START")
    for field in ("history_max_event_time_utc", "input_max_available_at_utc"):
        if value.get(field) and _time(value[field]) > cutoff:
            raise IntegrityError("FEATURE_OR_LABEL_AFTER_CUTOFF")
    if not value.get("sources") or not value.get("components") or not value.get("code_sha256"):
        raise IntegrityError("SOURCES_COMPONENTS_CODE_REQUIRED")
    sources = [_source(source, cutoff, value["mode"]) for source in value["sources"]]
    if any(_time(source["retrieved_at_utc"]) > created for source in sources):
        raise IntegrityError("SOURCE_RETRIEVED_AFTER_CREATION")
    source_hashes = {source["sha256"] for source in sources}
    for label, digest in value["code_sha256"].items():
        _label(label); _sha(digest)
    for name, component in value["components"].items():
        _label(name)
        numeric = component["value"]
        if isinstance(numeric, list):
            if not numeric:
                raise IntegrityError("EMPTY_COMPONENT")
            for number in numeric:
                _number(number)
        else:
            _number(numeric)
        if component.get("status") != "USED" or component.get("input_snapshot_sha256") != value["inputs_sha256"] or component.get("fitted_state_sha256") != value["state_sha256"]:
            raise IntegrityError("COMPONENT_INPUT_STATE_BINDING_MISMATCH")
        refs = component.get("source_sha256")
        if not isinstance(refs, list) or not refs or not set(refs) <= source_hashes:
            raise IntegrityError("COMPONENT_SOURCE_NOT_BOUND")
        for path in component.get("input_paths", []):
            _lookup(value["inputs"], _label(path))
        if component.get("max_available_at_utc") and _time(component["max_available_at_utc"]) > cutoff:
            raise IntegrityError("COMPONENT_AFTER_CUTOFF")
    trace = content_id({"inputs": value["inputs_sha256"], "state": value["state_sha256"],
        "config": value["config_sha256"], "code": value["code_sha256"],
        "components": value["components"], "forecast": value["forecast_sha256"]})
    if trace != value.get("inference_trace_sha256"):
        raise IntegrityError("INFERENCE_TRACE_HASH_MISMATCH")
    if _simulation(value.get("simulation")) != value.get("simulation"):
        raise IntegrityError("SIMULATION_VERIFICATION_DISCLOSURE_MISMATCH")
    if _validate_forecast(value["forecast"]) != value.get("unsupported_forecast_fields"):
        raise IntegrityError("UNSUPPORTED_FORECAST_FIELD_DISCLOSURE_MISMATCH")
    return dict(receipt)


def write_shadow_receipt(receipt: Mapping, output_root: str | Path) -> dict:
    """First-write local prospective SHADOW registration, never canonical grading.

    Both source validation and actual clock checks occur before any artifact is
    written. A repeated event/model/stage cannot replace the first forecast.
    External anchoring can be supplied separately by the enclosing GitHub run.
    """
    value = verify_component_receipt(receipt)
    if value["mode"] != "SHADOW":
        raise IntegrityError("REPLAY_CANNOT_REGISTER_AS_SHADOW")
    root = Path(output_root).resolve()
    def check_storage_paths():
        for name in ("shadow.lock", "components", "registrations"):
            path = root / name
            if path.is_symlink() or path.resolve().parent != root:
                raise IntegrityError("SHADOW_STORAGE_PATH_ESCAPE")
    check_storage_paths()
    key = content_id({"event_id": value["event_id"], "model_id": value["model_id"],
                      "stage_id": value["stage_id"]})
    with registry_lock(root / "shadow.lock"):
        check_storage_paths()
        target = root / "registrations" / (key + ".json")
        if target.exists() or target.is_symlink():
            raise IntegrityError("SHADOW_ALREADY_REGISTERED")
        registered = _now()
        cutoff, created, start = (_time(value[k]) for k in ("cutoff_utc", "created_at_utc", "start_utc"))
        if not cutoff <= created <= registered < start:
            raise IntegrityError("SHADOW_REGISTRATION_NOT_PREGAME")
        for source in value["sources"]:
            _source(source, cutoff, "SHADOW")
        artifact_id = ArtifactStore(root / "components").put(value)
        registration = {"schema": SHADOW_SCHEMA, "registration_id": key,
            "component_artifact_id": artifact_id, "component_receipt_sha256": value["receipt_sha256"],
            "event_id": value["event_id"], "model_id": value["model_id"], "stage_id": value["stage_id"],
            "registered_at_utc": _stamp(registered), "start_utc": value["start_utc"],
            "status": "LOCAL_PROSPECTIVE_SHADOW_LOGGED", "external_timestamp_verified": False,
            "source_authenticity_independently_verified": False, "canonical_prospective_eligible": False,
            "predictive_validation": "NOT_ASSESSED", "publication_allowed": False, "action_authority": False}
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(canonical_bytes(registration)); stream.flush(); os.fsync(stream.fileno())
        return {**registration, "registration_path": str(target)}
