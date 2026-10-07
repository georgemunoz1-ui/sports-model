"""Separate monotone CDF calibration; chronology and model identity stay explicit."""
import math
import hashlib
from pathlib import Path
import scipy
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logit
from models.common.discrete_research import (digest, stamp, validate, make_distribution,
                                            finite, identity, source_hash, score, writer_clock)


def transformed_masses(masses, intercept, log_slope):
    cdf = np.cumsum(masses); cdf[-1] = 1.
    if intercept == 0 and log_slope == 0:
        return np.asarray(masses).copy()
    transformed = expit(intercept + math.exp(log_slope) * logit(np.clip(cdf, 1e-15, 1-1e-15)))
    transformed = np.where(cdf >= 1, 1., np.where(cdf <= 0, 0., transformed))
    return np.maximum(0., np.diff(np.r_[0., transformed]))


def fit(rows, *, fitted_at):
    if len(rows) < 30:
        raise ValueError("AT_LEAST_30_CALIBRATION_ROWS_REQUIRED_NOT_VALIDATION")
    scope = None; samples = []; ids = set()
    for r in rows:
        d = r["distribution"]; x, p = validate(d); provenance = d["provenance"]
        key = tuple(d[k] for k in ("league", "product", "settlement", "model_id"))
        if scope is not None and key != scope:
            raise ValueError("CALIBRATION_SCOPE_MISMATCH")
        scope = key
        eid = identity(provenance["event_id"], "EVENT_ID")
        if eid in ids:
            raise ValueError("DUPLICATE_CALIBRATION_EVENT")
        ids.add(eid)
        if not stamp(provenance["cutoff"]) < stamp(r["start_time_utc"]) <= stamp(r["result_available_at"]) < stamp(fitted_at):
            raise ValueError("CALIBRATION_CHRONOLOGY_INVALID")
        source_hash(r["result_source_sha256"])
        y = finite(r["observed"])
        if y != round(y):
            raise ValueError("INTEGER_OUTCOME_REQUIRED")
        score(d, y)
        samples.append((p, x == y))
    if any(not mask.any() for _, mask in samples):
        raise ValueError("CALIBRATION_CANNOT_REPAIR_MISSING_SUPPORT")

    def objective(parameters):
        values = [float(transformed_masses(p, *parameters)[mask].sum()) for p, mask in samples]
        if min(values) <= 0:
            return 1e100
        return -sum(math.log(x) for x in values) / len(values)

    fit_result = minimize(objective, [0., 0.], method="L-BFGS-B", bounds=[(-3., 3.), (-2., 2.)])
    if not fit_result.success or not np.isfinite(fit_result.x).all():
        raise ValueError("CALIBRATION_OPTIMIZER_FAILED")
    model = {"schema": "sports.discrete_cdf_calibration.research.v1", "league": scope[0],
             "product": scope[1], "settlement": scope[2], "reference_model_id": scope[3],
             "fit_as_of_utc": fitted_at, "created_at_utc": writer_clock(), "intercept": float(fit_result.x[0]),
             "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             "scipy_version": scipy.__version__, "numpy_version": np.__version__,
             "log_slope": float(fit_result.x[1]), "training_event_ids": sorted(ids),
             "training_n": len(rows), "training_sha256": digest(rows),
             "objective": "DISCRETE_DISTRIBUTION_LOG_LOSS", "optimizer_bounds": [[-3, 3], [-2, 2]],
             "status": "FITTED_RESEARCH_NOT_VALIDATED", "action_authority": False}
    model["model_id"] = scope[3] + ".cdf." + digest(model)[:16]
    model["artifact_sha256"] = digest(model)
    return model


def apply(distribution, model):
    x, p = validate(distribution)
    material = dict(model); h = material.pop("artifact_sha256", None)
    if material.get("schema") != "sports.discrete_cdf_calibration.research.v1" or digest(material) != h:
        raise ValueError("CALIBRATION_HASH_MISMATCH")
    if model.get("code_sha256") != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError("CALIBRATION_CODE_DRIFT")
    if model.get("action_authority") is not False:
        raise ValueError("RESEARCH_ONLY")
    if any(distribution[k] != model[k] for k in ("league", "product", "settlement")) or distribution["model_id"] != model["reference_model_id"]:
        raise ValueError("CALIBRATION_SCOPE_MISMATCH")
    provenance = distribution["provenance"]
    if provenance["event_id"] in model["training_event_ids"]:
        raise ValueError("CALIBRATION_EVENT_REUSED")
    if stamp(model["fit_as_of_utc"]) > stamp(provenance["cutoff"]):
        raise ValueError("FUTURE_CALIBRATION")
    a, b = finite(model["intercept"]), finite(model["log_slope"])
    if not -3 <= a <= 3 or not -2 <= b <= 2:
        raise ValueError("CALIBRATION_PARAMETER_RANGE")
    masses = transformed_masses(p, a, b)
    return make_distribution(x.tolist(), masses.tolist(), league=model["league"], product=model["product"],
                             settlement=model["settlement"], model_id=model["model_id"],
                             provenance={**provenance, "uncalibrated_distribution_sha256": distribution["distribution_sha256"],
                                         "calibrator_existed_at_forecast_cutoff": stamp(model["created_at_utc"]) <= stamp(provenance["cutoff"]),
                                         "calibration_artifact_sha256": h})
