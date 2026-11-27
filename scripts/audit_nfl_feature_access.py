"""Read-only feature-access companion for the existing NFL contextual runtime.

This is a historical research replay, not a new fit, freeze, feature-source
attestation, or registration. It exposes one native feature vector and exact
per-arm/head usage without changing the model or its numerical identity.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from models.nfl.contextual.base_features import MODEL_FEATURES
from models.nfl.contextual.features import QB_FEATURES, AVAIL_FEATURES, TRAVEL_FEATURES
from models.nfl.contextual.model import FAMILIES, TARGETS, load_artifact
from models.nfl.contextual.recovered_inference import digest, predict, utc
from models.nfl.contextual.runtime import live_features
from scripts.source_attestation import attest_sources, sha256

SCHEMA = "sports.feature_access.nfl.v1"
WEATHER = {"temperature_f", "wind_mph", "weather_missing"}
REST_VENUE = {"rest_days_diff", "rest_missing", "neutral_site", "roof_indoor",
              "location_missing", "roof_missing"}


def _read_pinned(path, pin):
    raw = Path(path).read_bytes()
    if not isinstance(pin, str) or not re.fullmatch("[0-9a-f]{64}", pin):
        raise ValueError("INDEPENDENT_SHA256_PIN_REQUIRED")
    if sha256(raw) != pin:
        raise ValueError("FEATURE_ACCESS_ARTIFACT_HASH_MISMATCH")
    return raw


def _strict_json(raw):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError("DUPLICATE_JSON_KEY")
            out[k] = v
        return out
    def bad(_):
        raise ValueError("NONFINITE_JSON")
    obj = json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)
    if not isinstance(obj, dict):
        raise ValueError("JSON_OBJECT_REQUIRED")
    return obj


def _family(name):
    for keys, family in ((QB_FEATURES, "QB"), (AVAIL_FEATURES, "AVAILABILITY"),
                         (TRAVEL_FEATURES, "TRAVEL"), (WEATHER, "WEATHER"),
                         (REST_VENUE, "REST_VENUE"), (MODEL_FEATURES, "TEAM_HISTORY")):
        if name in keys:
            return family
    raise ValueError("UNDECLARED_NATIVE_FEATURE")


def inspect_native_vector(artifact, vector):
    """Expose the exact native matrix; no invented zeros or feature weights."""
    if set(artifact["arms"]) != set(FAMILIES):
        raise ValueError("NATIVE_ARM_SET_MISMATCH")
    names = list(MODEL_FEATURES) + FAMILIES["combined"]
    if len(names) != len(set(names)) or set(vector) != set(names):
        raise ValueError("NATIVE_FEATURE_SCHEMA_MISMATCH")
    for name, val in vector.items():
        if val is not None and (type(val) not in (float, int) or not math.isfinite(val)):
            raise ValueError("INVALID_NATIVE_FEATURE:" + name)
    arms = {}
    for arm, params in artifact["arms"].items():
        expected = list(MODEL_FEATURES) + FAMILIES[arm]
        if (params["feature_names"] != expected
                or params.get("market_input") is not False
                or params["model_id"] != f"nfl.integrated_context.{arm}.v1.research"
                or set(params["heads"]) != set(TARGETS)):
            raise ValueError("NATIVE_ARM_BINDING_MISMATCH:" + arm)
        for head in params["heads"].values():
            for key in ("impute", "center", "scale", "coefficient"):
                values = head[key]
                if len(values) != len(expected) or not all(
                    type(v) in (int, float) and math.isfinite(v) for v in values
                ):
                    raise ValueError("INVALID_NATIVE_HEAD:" + arm)
            if any(v <= 0 for v in head["scale"]):
                raise ValueError("INVALID_NATIVE_SCALE")
        prediction = predict(params, {k: vector[k] for k in expected})
        arms[arm] = {
            "model_id": params["model_id"],
            "matrix_columns": len(expected),
            "finite_matrix_columns": sum(vector[k] is not None for k in expected),
            "imputed_columns": [k for k in expected if vector[k] is None],
            "head_diagnostics": prediction["prediction"],
            "point_estimates_not_joint_means": True,
            "joint_score_support": ("EXISTING_COMBINED_SPECIFIC_RESEARCH_KERNEL"
                                    if arm == "combined" else "UNAVAILABLE_FOR_SELECTED_ARM"),
            "nonzero_coefficients_by_head": {
                k: sum(v != 0 for v in h["coefficient"]) for k, h in params["heads"].items()
            },
        }
    rows = []
    for name in names:
        usage = {}
        for arm, params in artifact["arms"].items():
            if name not in params["feature_names"]:
                usage[arm] = {"matrix_member": False, "heads": {}}
                continue
            i = params["feature_names"].index(name)
            usage[arm] = {"matrix_member": True, "heads": {
                target: {"coefficient_nonzero": head["coefficient"][i] != 0,
                         "fitted_imputation_used": vector[name] is None}
                for target, head in params["heads"].items()
            }}
        rows.append({"feature": name, "family": _family(name), "value": vector[name],
                     "value_status": "MISSING_RAW_MATRIX_VALUE" if vector[name] is None else "NUMERIC_CONSTRUCTED",
                     "source_status": "FIELD_LEVEL_PIT_LINEAGE_NOT_ESTABLISHED",
                     "arms": usage})
    return rows, arms


def replay_feature_access(package_path, package_sha, model_path, model_sha,
                          recovered_path, recovered_sha, event_id, cutoff,
                          *, source_roots=()):
    """Use the native builder on a pinned retained package, strictly retrospective."""
    package = _strict_json(_read_pinned(package_path, package_sha))
    model_raw = _read_pinned(model_path, model_sha)
    artifact = load_artifact(model_path)
    if Path(model_path).read_bytes() != model_raw:
        raise ValueError("MODEL_BYTES_CHANGED_DURING_READ")
    recovered = _strict_json(_read_pinned(recovered_path, recovered_sha))
    if (artifact.get("schema") != "nfl.integrated_context.v1"
            or digest(artifact) != package["model_digest"]):
        raise ValueError("NATIVE_MODEL_PACKAGE_MISMATCH")
    events = [e for e in package["events"] if e["event_id"] == event_id]
    if len(events) != 1:
        raise ValueError("EVENT_NOT_UNIQUE")
    event = events[0]
    cut, start = utc(cutoff), utc(event["start_time_utc"])
    now = datetime.now(timezone.utc)
    if not utc(package["captured_at_utc"]) <= cut < start <= now:
        raise ValueError("RETAINED_REPLAY_CHRONOLOGY_INVALID")
    packet = package["event_inputs"][event_id]
    if any(packet["base"].get(t) is not None for t in TARGETS):
        raise ValueError("TARGET_RESULT_IN_FEATURE_INPUT")
    vector, audit = live_features(artifact, recovered, packet["base"], packet["context"], event, cutoff)
    rows, arms = inspect_native_vector(artifact, vector)
    # Source-level byte retention is not proof of field extraction or original
    # historical availability. Keep those assertions false even on success.
    source_evidence = {"status": "RAW_SOURCE_ROOTS_NOT_SUPPLIED"}
    if source_roots:
        try:
            source_evidence = attest_sources(package["source_fetches"], source_roots, cutoff)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            source_evidence = {"status": "SOURCE_RETENTION_UNVERIFIED", "reason": str(exc)}
    shared = {"event_id": event_id, "cutoff_utc": cut.isoformat(),
              "native_features": vector, "package_sha256": package_sha,
              "model_artifact_sha256": model_sha, "recovered_parameters_sha256": recovered_sha,
              "native_model_digest": digest(artifact)}
    families = {}
    for row in rows:
        family = families.setdefault(row["family"], {"constructed": 0, "finite": 0, "qb_matrix": 0,
                                                     "combined_matrix": 0, "field_pit_verified": 0})
        family["constructed"] += 1
        family["finite"] += row["value"] is not None
        family["qb_matrix"] += row["arms"]["qb"]["matrix_member"]
        family["combined_matrix"] += row["arms"]["combined"]["matrix_member"]
    return {"schema": SCHEMA, "execution_mode": "RETROSPECTIVE_FEATURE_ACCESS_DIAGNOSTIC",
            "executed_at_utc": now.isoformat(), "event_id": event_id,
            "cutoff_utc": cut.isoformat(), "event_start_utc": start.isoformat(),
            "feature_snapshot_sha256": digest(shared), "bindings": shared,
            "feature_families": families, "feature_rows": rows, "arms": arms,
            "native_context_audit": {"final_inactives": audit["final_inactives"],
                                     "workload": audit["workload"], "travel": audit["travel"]},
            "source_evidence": source_evidence,
            "field_level_pit_verified": False, "training_ready": False,
            "prospective_registration_verified": False, "market_input": False,
            "action_authority": False, "qualification": "NO_PICK", "official_units": 0.0}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ("package", "model", "recovered", "output"):
        p.add_argument("--" + arg, required=True, type=Path)
    for arg in ("package-sha", "model-sha", "recovered-sha", "event-id", "cutoff"):
        p.add_argument("--" + arg, required=True)
    p.add_argument("--source-root", type=Path, action="append", default=[])
    a = p.parse_args()
    result = replay_feature_access(a.package, a.package_sha, a.model, a.model_sha,
                                   a.recovered, a.recovered_sha, a.event_id, a.cutoff,
                                   source_roots=a.source_root)
    raw = (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with a.output.open("xb") as f:
        f.write(raw)
    print("NFL_FEATURE_ACCESS_RECEIPT_SHA256=" + sha256(raw))
    print(json.dumps(result["feature_families"], sort_keys=True))


if __name__ == "__main__":
    main()
