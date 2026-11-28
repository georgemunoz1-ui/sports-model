"""Additive, reporting-supported NFL research execution.

The predecessor runtime is immutable. Its feature constructor and numerical
helpers are reused, but its all-arm ``run`` is never invoked here. Admission
precedes every contextual-arm prediction. Fitted model identity is unchanged; execution and
observed numerical procedure identities bind this successor and the gate.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from .runtime import live_features
from .model import simulate_joint
from .operating import RESEARCH_MODE, coverage, select
from .recovered_inference import bernoulli_simulation, digest, predict, utc
from .report_support import report_support, require_selected_support
from pipelines.cards import semantic_identity as numeric

PROCEDURE_ID = "nfl.integrated_context.reporting_support.v1"
PREDECESSOR_SHA256 = "8951577d6edd2e2e37b370cafe9f90c205b9de8b6b59d9c1aba961f15760c15d"
_HERE = Path(__file__).resolve().parent
_FROZEN_SOURCES = (
    "runtime.py", "personnel.py", "model.py", "features.py",
    "recovered_inference.py", "operating.py", "capabilities.py", "settlement.py",
    "forecast_stream.py", "week2.py", "joint_distribution.py",
    "qb_assimilation.py", "weekly_state.py", "assimilation.py",
)


def _code_hashes():
    hashes = {name: hashlib.sha256((_HERE / name).read_bytes()).hexdigest()
              for name in (*_FROZEN_SOURCES, "report_support.py", Path(__file__).name)}
    if hashes["runtime.py"] != PREDECESSOR_SHA256:
        raise ValueError("REPORTING_SUPPORT_PREDECESSOR_SOURCE_MISMATCH")
    hashes["pipelines/cards/semantic_identity.py"] = hashlib.sha256(
        Path(numeric.__file__).read_bytes()).hexdigest()
    return hashes


def _numeric_identity(artifact, selected, event, cutoff, features, n):
    """Use the existing v2 schema with truthful successor procedure components.

    No predecessor forecast is executed or fabricated. Unconsumed feature and
    presentation metadata remain outside the numerical RNG identity.
    """
    params = artifact["arms"][selected]
    consumed = numeric._pick(features, params["feature_names"])
    model = {
        "feature_names": copy.deepcopy(params["feature_names"]),
        "heads": {target: numeric._pick(head, numeric._NFL_HEAD)
                  for target, head in params["heads"].items()},
        "engine_code": numeric._code([
            "models/nfl/contextual/recovered_inference.py",
            "models/nfl/contextual/model.py",
        ]),
    }
    if selected == "combined":
        model.update(residual_pairs=copy.deepcopy(artifact["final_score_residuals"]),
                     tie_rate=artifact["simulation_v2"]["tie_rate"])
    components = numeric._components(
        "nfl", params["model_id"], consumed,
        feature_configuration={"selected_arm": selected})
    calibration = components["calibration"]
    calibration.pop("procedure_id")
    calibration["observed_prediction_code_sha256"].pop("models/nfl/contextual/runtime.py")
    calibration["observed_prediction_code_sha256"].update(numeric._code([
        "models/nfl/contextual/runtime_reporting_support_v1.py",
        "models/nfl/contextual/report_support.py",
    ]))
    calibration["procedure_id"] = digest(calibration)
    engine = ("NFL_BINARY_AND_COMBINED_JOINT_KERNEL" if selected == "combined"
              else "BERNOULLI_WINNER_DIAGNOSTIC")
    identity = numeric._identity(
        "nfl", event, cutoff, params["model_id"], consumed, model, n, engine, components)
    return identity, components


def run(artifact, recovered, base, context, event, cutoff, n=100000, *,
        model_id=None, mode=RESEARCH_MODE, mode_artifact=None, market=None,
        live_state=None):
    if mode != RESEARCH_MODE or mode_artifact is not None:
        raise ValueError("REPORTING_SUPPORT_RESEARCH_PREGAME_ONLY")
    if market is not None or live_state is not None:
        raise ValueError("MARKET_OR_LIVE_INPUT_IN_FOOTBALL_ONLY")
    if model_id is None:
        raise ValueError("REPORTING_SUPPORT_EXPLICIT_MODEL_ID_REQUIRED")
    if type(n) is not int or not 1 <= n <= 1000000:
        raise ValueError("DRAW_COUNT_RANGE")
    code_hashes = _code_hashes()
    # Take one owned input snapshot; no prediction uses caller-owned mappings.
    artifact, recovered, base, context, event = copy.deepcopy(
        (artifact, recovered, base, context, event))
    input_hash = digest({"artifact": artifact, "recovered": recovered, "base": base,
                         "context": context, "event": event, "cutoff_utc": cutoff})
    from .week2 import applies, coherence, require_assimilation, selection
    if int(base["week"]) >= 3 or context.get("weekly_state"):
        from .weekly_state import for_event, require_features
        weekly = for_event(context, artifact, event, cutoff)
        state_flow = require_features(base, weekly, event)
        state_flow["state_id"] = context["weekly_state"]["state_id"]
    else:
        state_flow = (require_assimilation(base, context, event, cutoff)
                      if applies(base, event) else None)
    selected = select(artifact, model_id, mode)
    if utc(cutoff) >= utc(event["start_time_utc"]):
        raise ValueError("NOT_PREGAME")
    features, audit = live_features(artifact, recovered, base, context, event, cutoff)
    features, audit = copy.deepcopy((features, audit))
    reporting = report_support(artifact, features)
    require_selected_support(reporting, selected, event["event_id"], cutoff)
    snapshot = {
        "event_id": event["event_id"], "cutoff_utc": cutoff,
        "model_artifact_sha256": digest(artifact),
        "feature_sha256": digest(features), "input_snapshot_sha256": input_hash,
    }
    arms = {}
    for name, params in artifact["arms"].items():
        support = reporting["arms"][name]
        if not support["admitted"]:
            arms[name] = {"model_id": params["model_id"], "prediction": None,
                          "contribution_trace": None, "status": support["status"],
                          "action_authority": False}
            continue
        arms[name] = predict(params, {key: features[key] for key in params["feature_names"]})
    from .capabilities import describe_run_capabilities
    capabilities = describe_run_capabilities(
        artifact["arms"][selected], features, context, base, cutoff, event,
        digest(artifact), arms[selected]["contribution_trace"])
    identity, components = _numeric_identity(artifact, selected, event, cutoff, features, n)
    execution_material = {
        "runtime_procedure_id": PROCEDURE_ID, "code_hashes": code_hashes,
        "feature_snapshot": snapshot, "reporting_support_sha256": digest(reporting),
        "numerical_identity_sha256": identity["identity_sha256"],
    }
    execution_identity = digest(execution_material)
    p = arms[selected]["prediction"]
    winner, win_info = bernoulli_simulation(p["home_win"], identity["identity_sha256"], n)
    scores = None
    score_info = {"status": "UNAVAILABLE_FOR_SELECTED_ARM",
                  "reason": "FROZEN_JOINT_RESIDUAL_POOL_IS_COMBINED_SPECIFIC"}
    exact = None
    if selected == "combined":
        scores, score_info = simulate_joint(
            p["home_margin"], p["total_points"], p["home_win"],
            artifact["final_score_residuals"], artifact["simulation_v2"]["tie_rate"],
            identity["identity_sha256"], n)
        from .joint_distribution import kernel, summary
        support, weights = kernel(
            p["home_margin"], p["total_points"], p["home_win"],
            artifact["final_score_residuals"], artifact["simulation_v2"]["tie_rate"])
        exact = summary(support, weights)
    provenance = {
        "runtime_procedure_id": PROCEDURE_ID, "execution_identity": execution_identity,
        "execution_material": execution_material, "identity_components": components,
        "source_lineage": {"predecessor_runtime_sha256": PREDECESSOR_SHA256,
                           "predecessor_run_executed": False},
        "interpretation": "Frozen feature/numerical helpers reused; successor admission and orchestration executed.",
        "predictive_validation": "NOT_ASSESSED", "action_authority": False,
    }
    warnings = [
        "NEW_FIT_NOT_PROSPECTIVELY_VALIDATED", "HISTORICAL_REPORT_AND_STARTER_PIT_LIMITATIONS",
        "FINAL_INACTIVES_PENDING", "PRIOR_SNAP_SHARE_IS_NOT_PROMISED_WORKLOAD",
        "TRAVEL_IS_AIRPORT_PROXY", "EMPIRICAL_SCORE_SETTLEMENT_UNVALIDATED",
        "REPORTING_SUPPORT_SUCCESSOR_NO_PREDICTIVE_PROMOTION",
    ]
    if audit["final_inactives"] == "VERIFIED":
        warnings.remove("FINAL_INACTIVES_PENDING")
        warnings.append("FINAL_INACTIVES_VERIFIED; NON_INJURY_SCRATCH_IMPACT_UNFITTED")
    refused = [name for name, row in reporting["arms"].items() if not row["admitted"]]
    if refused:
        warnings.append("REPORTING_SUPPORT_REFUSED_SIBLING_ARMS:" + ",".join(refused))
    policy = selection(model_id)
    consistent = coherence(p, exact)
    warnings.append(policy["presentation_role"] + ":" + policy["screen_status"])
    if consistent["cross_head_direction_disagreement"]:
        warnings.append("CROSS_HEAD_DIRECTION_DISAGREEMENT; RIDGE_CENTERS_ARE_NOT_JOINT_EXPECTATIONS")
    used = {
        "base": ["WEATHER", "REST"],
        "qb": ["WEATHER", "REST", "QB_PRIOR_AND_CHANGE"],
        "availability": ["WEATHER", "REST", "INJURY_POSITION_GROUPS", "PRACTICE", "PRIOR_SNAP_WORKLOAD"],
        "travel": ["WEATHER", "REST", "AIRPORT_TRAVEL_PROXY"],
        "combined": ["QB_PRIOR_AND_CHANGE", "INJURY_POSITION_GROUPS", "PRACTICE",
                     "PRIOR_SNAP_WORKLOAD", "AIRPORT_TRAVEL_PROXY", "WEATHER", "REST"],
    }
    result = {
        "schema": "nfl.integrated_context_forecast.v1", "model_id": model_id,
        "runtime_procedure_id": PROCEDURE_ID, "execution_identity": execution_identity,
        "event": event, "cutoff_utc": cutoff, "identity": identity["identity_sha256"],
        "identity_semantics": numeric.SEMANTIC, "numerical_identity": identity,
        "forecast_procedure_id": model_id + ":" + numeric.SEMANTIC,
        "feature_procedure_id": identity["feature_procedure_id"],
        "calibration_procedure_id": identity["calibration_procedure_id"],
        "identity_provenance": provenance, "diagnostics": {"identity_provenance": copy.deepcopy(provenance)},
        "model_artifact_sha256": digest(artifact), "features": features,
        "feature_snapshot": snapshot, "reporting_support": reporting,
        "audit": audit, "arms": arms, "prediction": p,
        "score_centers": {"home": (p["total_points"] + p["home_margin"]) / 2,
                          "away": (p["total_points"] - p["home_margin"]) / 2},
        "winner_simulation": win_info, "score_simulation": score_info,
        "contribution_trace": {target: arms[selected]["contribution_trace"][target]["features"] for target in p},
        "current_context_numerically_applied": used[selected],
        "coverage_label": "FITTED_RESEARCH_FEATURES_WITH_UNRESOLVED_CURRENT_STATE",
        "research_only": True, "canonical_prospective_eligible": False,
        "market_input": False, "action_authority": False, "warnings": warnings,
        "selection_policy": policy, "coherence": consistent, "joint_distribution": exact,
        "assimilation": state_flow, "code_hashes": code_hashes, "capability_report": capabilities,
        "mode": mode, "selected_arm": selected,
        "feature_coverage": coverage(artifact["arms"][selected], features, audit),
    }
    return result, winner, scores
