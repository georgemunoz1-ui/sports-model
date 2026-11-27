"""One native feature-access view per event/cutoff, independent of selected arm.

Only native constructors are used. This initial adapter exposes diagnostic
reconstructions; it deliberately cannot certify original PIT field availability.
Do not feed its diagnostic values to a prospective or promotion-grade runner.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
from numbers import Real

from research.efficiency import runner
from scripts.audit_nfl_feature_access import (
    _read_pinned, _strict_json, replay_feature_access,
)
from scripts.source_attestation import instant, sha256

SCHEMA = "sports.native_feature_access.v1"
PIT_UNVERIFIED = "FIELD_LEVEL_PIT_LINEAGE_NOT_ESTABLISHED"
LEAGUES = ("nfl", "nba", "cfb", "cbb", "nhl", "mlb", "wnba", "mls")
ROOT = Path(__file__).resolve().parents[1]


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("NATIVE_FEATURE_IDENTITY_REQUIRED")
    return value


def _value(v):
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(float(v)):
        raise ValueError("INVALID_NATIVE_FEATURE_VALUE")
    return float(v)


def _sources(rows, cutoff):
    """Retain declared dependency claims, not proof of raw source truth."""
    out = {}
    for r in rows:
        uri = _text(r.get("source", r.get("url")))
        digest = _text(r.get("sha256"))
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("INVALID_SOURCE_DIGEST")
        retrieved = r.get("retrieved_at_utc", r.get("fetched_at_utc"))
        available = r.get("available_at_utc", r.get("historical_available_at_utc"))
        timing = ("RETRIEVAL_UNVERIFIED" if retrieved is None else
                  "LATER_RECONSTRUCTION" if instant(retrieved) > cutoff else
                  "RECORDED_RETRIEVAL_BY_CUTOFF")
        row = {"source": uri, "sha256": digest, "retrieved_at_utc": retrieved,
               "declared_available_at_utc": available, "timing": timing,
               "field_binding_verified": False}
        if available is not None and instant(available) > cutoff:
            row["timing"] = "DECLARED_AVAILABILITY_AFTER_CUTOFF"
        out[runner.digest(row)] = row
    return [out[k] for k in sorted(out)]


def _field(name, value, family, unit, locator, transform, group, *, blocked=False):
    return {"feature_id": name, "native_name": name, "family": family,
            "unit": unit, "value": _value(value),
            "value_status": ("NATIVE_GATE_BLOCKED" if blocked else
                             "MISSING" if value is None else "NATIVE_NUMERIC_CONSTRUCTED"),
            "provenance": {"native_locator": locator, "transform": transform,
                           "dependency_group": group, "status": PIT_UNVERIFIED},
            "verified_pit_eligible": False}


def _snapshot(league, event, cutoff, fields, groups, bindings, reasons):
    if league not in LEAGUES:
        raise ValueError("UNKNOWN_LEAGUE")
    start = instant(event["start_time_utc"])
    cut = instant(cutoff)
    if cut >= start:
        raise ValueError("CUTOFF_NOT_PRESTART")
    identity = {k: _text(event[k]) for k in ("event_id", "home_id", "away_id")}
    if identity["home_id"] == identity["away_id"]:
        raise ValueError("SELF_MATCH")
    if len({f["feature_id"] for f in fields}) != len(fields):
        raise ValueError("DUPLICATE_FEATURE_ID")
    if any(f["provenance"]["dependency_group"] not in groups for f in fields):
        raise ValueError("MISSING_DEPENDENCY_GROUP")
    if any(f["verified_pit_eligible"] is not False for f in fields):
        raise ValueError("UNVERIFIED_FIELD_CANNOT_BE_ADMITTED")
    core = {"schema": SCHEMA, "league": league, "event": identity,
            "event_start_utc": start.isoformat(), "cutoff_utc": cut.isoformat(),
            "fields": fields, "dependency_groups": groups, "bindings": bindings,
            "native_gate_reasons": sorted(set(reasons)),
            "execution_scope": "RETROSPECTIVE_NATIVE_FEATURE_DIAGNOSTIC",
            "field_level_pit_verified": False, "training_ready": False,
            "market_input": False, "action_authority": False,
            "qualification": "NO_PICK", "official_units": 0.0}
    return {**core, "snapshot_sha256": runner.digest(core)}


def _nba_family_unit(name):
    if name.endswith("_possessions"):
        return "PACE", "ESTIMATED_POSSESSIONS_PER_FULL_GAME"
    if name.endswith("_efficiency") or name.endswith("_impact_per100"):
        return ("PERSONNEL" if name.endswith("_impact_per100") else "EFFICIENCY",
                "POINTS_PER_100_ESTIMATED_POSSESSIONS")
    if name.endswith(("_efg", "_tov", "_orb", "_ftr")):
        return "FOUR_FACTORS", "RATIO"
    if name.endswith("_rest"):
        return "REST", "DAYS_SINCE_LAST_EMBARGO_ELIGIBLE_GAME"
    if name.endswith("_games"):
        return "TEAM_HISTORY", "GAME_COUNT"
    if name == "neutral":
        return "VENUE", "INDICATOR"
    raise ValueError("UNKNOWN_NBA_NATIVE_FEATURE:" + name)


def _cfb_family_unit(name):
    if name.endswith("_epa_success"):
        return "EFFICIENCY", "RATE_0_TO_1"
    if name.endswith("_epa"):
        return "EFFICIENCY", "EXPECTED_POINTS_PER_PLAY"
    if name == "elo_diff_with_home_advantage":
        return "TEAM_HISTORY", "ELO_POINTS"
    if "_ewma_" in name:
        return "TEAM_HISTORY", "POINTS"
    if name == "rest_days_diff":
        return "REST", "DAYS"
    if name in ("neutral_site", "conference_game"):
        return "VENUE_SCOPE", "INDICATOR"
    if name.endswith(("_qb_availability", "_snap_share")):
        return "PERSONNEL", "RATE_0_TO_1"
    raise ValueError("UNKNOWN_CFB_NATIVE_FEATURE:" + name)


def replay_efficiency_access(league, history_path, history_sha, event_id):
    """Rebuild one event from a pinned native normalized archive, no refit.

    Native history policies are preserved. Later archive retrieval, declared
    availability and coarse dependency groups are not field-level PIT evidence.
    """
    raw = _read_pinned(history_path, history_sha)
    history = _strict_json(raw)
    module = runner.backend(league)
    examples = runner.prepare(league, history)
    matches = [e for e in examples if e["event_id"] == event_id]
    if len(matches) != 1:
        raise ValueError("NATIVE_EVENT_NOT_UNIQUE_OR_MISSING")
    ex = matches[0]
    event = ex["event"]
    cut = instant(ex["cutoff_utc"])
    if event_id != event["event_id"] or cut >= instant(event["start_time_utc"]):
        raise ValueError("NATIVE_EVENT_CUTOFF_MISMATCH")
    used = ex.get("history_event_ids", [])
    if len(set(used)) != len(used) or event_id in used:
        raise ValueError("TARGET_OR_DUPLICATE_IN_NATIVE_HISTORY")
    maximum = ex.get("history_max_available_at_utc")
    if maximum and instant(maximum) > cut:
        raise ValueError("NATIVE_HISTORY_AFTER_CUTOFF")
    reasons = list(runner.reasons(ex))
    code = runner.code_snapshot(league)
    transform = "models.experiments." + league + "_efficiency.prepare_examples"
    refs = ex.get("sources", ex.get("source_bindings", []))
    groups = {"history": {"history_event_ids": used, "history_max_available_at_utc": maximum,
                           "sources": _sources(refs, cut),
                           "dependency_scope": "NATIVE_EVENT_HISTORY_SUPERSET_NOT_FIELD_ATTESTED"},
              "event": {"sources": _sources(ex.get("target_sources", []) + history.get("schedule_sources", []), cut),
                        "dependency_scope": "EVENT_SOURCE_CENSUS_MAY_INCLUDE_LATER_RESULT_BYTES"},
              "personnel": {"sources": [], "dependency_scope": "MISSING_SOURCE_BOUND_PERSONNEL"}}
    base_names = list(module.FEATURE_NAMES if league == "nba" else module.FEATURES)
    personnel_names = list(module.PERSONNEL_FEATURES)
    values = ex.get("features") or {}
    if set(values) - set(base_names):
        raise ValueError("UNDECLARED_NATIVE_FEATURES")
    blocked = ex["eligible"] is not True
    fields = []
    for name in base_names:
        family, unit = (_nba_family_unit(name) if league == "nba" else _cfb_family_unit(name))
        group = "event" if family in ("VENUE", "VENUE_SCOPE") else "history"
        fields.append(_field(name, values.get(name), family, unit, "features." + name,
                             transform, group, blocked=blocked))
    # Optional personnel does not erase the base feature view. It uses the
    # native personnel validator, not an invented zero adjustment.
    pv = {}
    if league == "nba":
        p = ex.get("personnel")
        if p is not None:
            try:
                alt = module.prepare_examples(history["history"], {"stage": "personnel"})
                candidates = [r for r in alt if r["event_id"] == event_id]
                if len(candidates) != 1 or candidates[0]["cutoff_utc"] != ex["cutoff_utc"]:
                    raise ValueError("PERSONNEL_NATIVE_CUTOFF_MISMATCH")
                a = candidates[0]
                if a["eligible"]:
                    if any(a["features"][n] != values[n] for n in base_names):
                        raise ValueError("PERSONNEL_BASE_FEATURE_DRIFT")
                    pv = {n: a["features"][n] for n in personnel_names}
                else:
                    reasons.extend(runner.reasons(a))
                groups["personnel"]["sources"] = _sources(p.get("sources", []), cut)
            except (KeyError, TypeError, ValueError) as exc:
                reasons.append("PERSONNEL_NATIVE_GATE:" + str(exc))
                pv = {}
        else:
            reasons.append("NBA_AUTHENTIC_PERSONNEL_INPUTS_REQUIRED")
    else:
        # The native CFB builder does not synthesize these feature values;
        # a separately bound personnel packet is required by personnel_values.
        reasons.append("CFB_PERSONNEL_SOURCE_BOUND_INPUTS_REQUIRED")
    if pv:
        groups["personnel"]["dependency_scope"] = "NATIVE_PERSONNEL_DEPENDENCY_CLAIMS_NOT_FIELD_ATTESTED"
    for name in personnel_names:
        family, unit = (_nba_family_unit(name) if league == "nba" else _cfb_family_unit(name))
        fields.append(_field(name, pv.get(name), family, unit, "personnel." + name,
                             transform, "personnel", blocked=name not in pv))
    return _snapshot(league, event, ex["cutoff_utc"], fields, groups,
                     {"history_artifact_sha256": history_sha, "native_code_sha256": code,
                      "feature_config": ex.get("feature_config"),
                      "feature_config_sha256": ex.get("feature_config_sha256") or runner.digest(ex.get("feature_config")),
                      "native_state_sha256": ex.get("component_state_sha256"),
                      "source_proof": "NORMALIZED_ARCHIVE_BYTES_PINNED_RAW_FIELD_DEPENDENCIES_UNVERIFIED"},
                     reasons)


def replay_nfl_access(package_path, package_sha, model_path, model_sha,
                      recovered_path, recovered_sha, event_id, cutoff, *, source_roots=()):
    """Adapt the previous native NFL replay to the common event/field schema."""
    native = replay_feature_access(package_path, package_sha, model_path, model_sha,
                                   recovered_path, recovered_sha, event_id, cutoff,
                                   source_roots=source_roots)
    package = _strict_json(_read_pinned(package_path, package_sha))
    event = next(e for e in package["events"] if e["event_id"] == event_id)
    cut = instant(cutoff)
    packet = package["event_inputs"][event_id]
    claims = _sources(package["source_fetches"], cut)
    group = {"package": {"sources": claims,
                         "dependency_scope": "NATIVE_PACKAGE_SOURCE_SUPERSET_NOT_FIELD_ATTESTED",
                         "retention_attestation": native["source_evidence"]}}
    from models.nfl.contextual import base_features, features, runtime, recovered_inference
    code = {str(Path(m.__file__).resolve().relative_to(ROOT)): sha256(Path(m.__file__).read_bytes())
            for m in (base_features, features, runtime, recovered_inference)}
    fields = []
    for row in native["feature_rows"]:
        f = _field(row["feature"], row["value"], row["family"], "NATIVE_TRANSFORM_UNITS",
                   "bindings.native_features." + row["feature"],
                   "models.nfl.contextual.runtime.live_features", "package")
        f["native_arm_usage"] = copy.deepcopy(row["arms"])
        fields.append(f)
    return _snapshot("nfl", {**event, "home_id": event["home_team"], "away_id": event["away_team"]},
                     cutoff, fields, group,
                     {"native_feature_snapshot_sha256": native["feature_snapshot_sha256"],
                      "native_code_sha256": code, "package_sha256": package_sha,
                      "model_artifact_sha256": model_sha, "recovered_parameters_sha256": recovered_sha,
                      "native_model_digest": native["bindings"]["native_model_digest"],
                      "team_identity_namespace": "NATIVE_NFL_TEAM_CODE",
                      "native_context_roles": sorted(packet["context"])},
                     ["FIELD_LEVEL_PIT_LINEAGE_NOT_ESTABLISHED"])


def diagnostic_values(snapshot):
    """Return constructible values only; NOT a training admission method."""
    core = {k: v for k, v in snapshot.items() if k != "snapshot_sha256"}
    if snapshot.get("schema") != SCHEMA or runner.digest(core) != snapshot.get("snapshot_sha256"):
        raise ValueError("NATIVE_FEATURE_SNAPSHOT_DIGEST_MISMATCH")
    return {r["feature_id"]: r["value"] for r in snapshot["fields"]
            if r["value_status"] == "NATIVE_NUMERIC_CONSTRUCTED"}


def verified_pit_values(snapshot):
    """No current native replay adapter has field-level PIT admission."""
    diagnostic_values(snapshot)  # verify integrity first
    raise ValueError("FIELD_LEVEL_PIT_ADMISSION_NOT_IMPLEMENTED")
