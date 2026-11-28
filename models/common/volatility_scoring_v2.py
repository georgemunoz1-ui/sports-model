"""Versioned joint-score diagnostics with a forecast-independent energy metric.

The hash-pinned v1 fitter/predictor and historical grades stay unchanged. V1's
forecast-SD-normalized energy diagnostic is not a proper comparison score. This
successor uses raw score coordinates and refuses mixed or legacy aggregates.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import numpy as np

from models.common import discrete_research as D
from models.common import volatility_matrix_v1 as V

SCORE_SCHEMA = "sports.joint_energy_score.research.v2"
RECORD_SCHEMA = "sports.luck_accounting.research.v2"
EVALUATION_SCHEMA = "sports.volatility_evaluation.research.v2"
METRIC_ID = "joint_energy.euclidean_raw_score.v2"


def code_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def metric_contract():
    """Return a new copy of the fixed definition, never forecast-fitted scales."""
    scale_source = {
        "identity": "fixed_unit_score_coordinates.v1",
        "kind": "FIXED_DEFINITION_NOT_ESTIMATED_FROM_FORECAST_OR_OUTCOMES",
        "coordinate_order": ["home_score", "away_score"],
        "component_scale": [1.0, 1.0],
    }
    contract = {
        "metric_id": METRIC_ID,
        "version": 2,
        "formula": "E||X-y||_2 - 0.5 E||X-X_prime||_2",
        "coordinate_order": ["home_score", "away_score"],
        "component_scale": [1.0, 1.0],
        "scale_source": scale_source,
        "scale_source_sha256": D.digest(scale_source),
        "standardization": "NONE_RAW_SCORE_COORDINATES",
        "lower_is_better": True,
        "comparison_scope": "SAME_LEAGUE_SETTLEMENT_EVENT_POPULATION_AND_METRIC",
    }
    contract["metric_contract_sha256"] = D.digest(contract)
    return contract


def energy_score(distribution, actual_home, actual_away):
    """Proper energy score in fixed home/away score coordinates (no SD divisor)."""
    actual_home, actual_away = V._observed_score(actual_home), V._observed_score(actual_away)
    V._check_final(actual_home, actual_away, distribution["league"], distribution["settlement"])
    home, away, mass = V.validate(distribution)
    points = np.column_stack([home, away]).astype(float)
    observed = np.array([actual_home, actual_away], dtype=float)
    first = float(np.linalg.norm(points - observed, axis=1) @ mass)
    # Chunk the pairwise sum: the result is exact for the emitted finite law,
    # without allocating an unbounded support-by-support distance tensor.
    second = 0.0
    for start in range(0, len(points), 256):
        block = points[start:start + 256]
        distances = np.linalg.norm(block[:, None, :] - points[None, :, :], axis=2)
        second += float(np.sum(distances * mass[start:start + 256, None] * mass[None, :]))
    return {"schema": SCORE_SCHEMA, "energy_score": first - 0.5 * second,
            "metric": metric_contract(), "scoring_code_sha256": code_hash()}


def account_result(distribution, *, actual_home, actual_away, result_source_sha256,
                   result_available_at):
    """Create a new v2 diagnostic; v1 source/grade bytes are never modified."""
    # Retain the existing chronology, source and scalar diagnostic checks. The
    # legacy energy field is replaced only in this new, separately typed object.
    out = V.account_result(distribution, actual_home=actual_home, actual_away=actual_away,
                           result_source_sha256=result_source_sha256,
                           result_available_at=result_available_at)
    out.pop("artifact_sha256")
    out["schema"] = RECORD_SCHEMA
    out["league"] = distribution["league"]
    out["settlement"] = distribution["settlement"]
    out["model_id"] = distribution["model_id"]
    D.identity(out["event_id"], "EVENT_ID")
    D.source_hash(out["parent_forecast_sha256"])
    out["joint_energy_score"] = energy_score(distribution, actual_home, actual_away)
    out["created_at_utc"] = D.writer_clock()
    out["derived_rescoring"] = False
    out["artifact_sha256"] = D.digest(out)
    return out


def rescore_legacy(distribution, legacy_record):
    """Explicitly derive a new score with exact parent identity, not a new grade."""
    prior = copy.deepcopy(legacy_record)
    material = dict(prior)
    prior_hash = material.pop("artifact_sha256", None)
    if prior.get("schema") != V.LUCK_SCHEMA or D.digest(material) != prior_hash:
        raise ValueError("LEGACY_GRADE_HASH_MISMATCH")
    if prior.get("action_authority") is not False or prior.get("prospective_grade_eligible") is not False:
        raise ValueError("RESEARCH_ONLY")
    V.validate(distribution)
    expected = {"parent_joint_distribution_sha256": distribution["distribution_sha256"],
                "parent_forecast_sha256": distribution["provenance"].get("parent_forecast_sha256"),
                "event_id": distribution["provenance"].get("event_id"),
                "forecast_cutoff": distribution["provenance"].get("cutoff"),
                "start_time_utc": distribution["provenance"].get("start_time_utc")}
    if any(prior.get(key) != value for key, value in expected.items()):
        raise ValueError("LEGACY_GRADE_PARENT_BINDING_MISMATCH")
    out = account_result(distribution, **{key: prior[key] for key in
        ("actual_home", "actual_away", "result_source_sha256", "result_available_at")})
    out.pop("artifact_sha256")
    out["derived_rescoring"] = True
    out["rescoring_parent"] = {"schema": V.LUCK_SCHEMA, "artifact_sha256": prior_hash,
                               "legacy_metric": "PREDICTIVE_SCORE_SD_WITH_UNIT_FALLBACK",
                               "legacy_score_retained_unchanged": True}
    out["independent_event_evidence_added"] = False
    out["artifact_sha256"] = D.digest(out)
    return out


def evaluate(records, *, evaluated_at):
    """Aggregate one exact v2 metric/procedure; never reinterpret old values."""
    if len(records) < 2:
        raise ValueError("AT_LEAST_2_EVALUATION_RECORDS_REQUIRED")
    D.stamp(evaluated_at)
    events, scores, scopes = [], [], set()
    for record in records:
        material = dict(record)
        record_hash = material.pop("artifact_sha256", None)
        if record.get("schema") != RECORD_SCHEMA:
            raise ValueError("V2_RECORD_REQUIRED_EXPLICIT_RESCORE_LEGACY_FIRST")
        if D.digest(material) != record_hash:
            raise ValueError("SCORE_RECORD_HASH_MISMATCH")
        if record.get("action_authority") is not False or record.get("prospective_grade_eligible") is not False:
            raise ValueError("RESEARCH_ONLY")
        score = record["joint_energy_score"]
        if score.get("schema") != SCORE_SCHEMA or score.get("metric") != metric_contract():
            raise ValueError("EXACT_V2_METRIC_CONTRACT_REQUIRED")
        if score.get("scoring_code_sha256") != code_hash():
            raise ValueError("SCORING_CODE_IDENTITY_MISMATCH")
        if D.stamp(record["result_available_at"]) >= D.stamp(evaluated_at):
            raise ValueError("EVALUATION_CHRONOLOGY_INVALID")
        events.append(D.identity(record["event_id"], "EVENT_ID"))
        scores.append(D.finite(score["energy_score"]))
        scopes.add(tuple(D.identity(record[k], k.upper()) for k in ("league", "settlement", "model_id")))
    if len(set(events)) != len(events):
        raise ValueError("DUPLICATE_EVALUATION_EVENT")
    if len(scopes) != 1:
        raise ValueError("MIXED_EVALUATION_SCOPE")
    league, settlement, model_id = next(iter(scopes))
    out = {"schema": EVALUATION_SCHEMA, "metric": metric_contract(),
           "scoring_code_sha256": code_hash(), "evaluated_at": evaluated_at,
           "created_at_utc": D.writer_clock(), "league": league, "settlement": settlement,
           "model_id": model_id, "n": len(records), "event_ids": sorted(events),
           "mean_joint_energy_score": float(np.mean(scores)), "records_sha256": D.digest(records),
           "status": "DIAGNOSTIC_NOT_WALK_FORWARD_VALIDATION",
           "legacy_values_included": False, "prospective_grade_eligible": False,
           "predictive_validation_granted": False, "action_authority": False,
           "required_next_evidence": "PRE_REGISTERED_PAIRED_CHRONOLOGICAL_BASELINE_CHALLENGER_EVALUATION"}
    out["artifact_sha256"] = D.digest(out)
    return out
