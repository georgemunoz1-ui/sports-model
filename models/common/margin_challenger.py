"""Chronologically tuned, integer-margin challenger; never a selected default.

An empirical residual distribution is mixed with an integrated Student-t density.
The latter gives every legal integer positive mass. Train-estimated dispersion
and optional lattice corrections retain sport-specific key-margin structure.
The final finite representation reports its omitted tails explicitly. No winner
probability is inverted into a margin and no market line is a training feature.

Input provenance is checked for consistency, not independently attested. An
internally held-out tuning block is NOT an external performance evaluation.
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

import numpy as np
import scipy
from scipy.stats import t

from models.common.discrete_research import (
    SETTLEMENTS, digest, finite, fit_residuals, identity, make_distribution,
    source_hash, stamp, writer_clock,
)

SCHEMA = "sports.margin_full_support_challenger.research.v1"
MIN_TRAINING = 60
MIN_INNER_FIT = 30
MIN_INNER_TUNE = 20
TAIL_TOLERANCE = 1e-6
MAX_ABSOLUTE_SUPPORT = 10000
MINIMUM_ABSOLUTE_SUPPORT = 256
DF_GRID = (3., 5., 10., 30.)
TAIL_WEIGHT_GRID = (.1, .25, .5, 1.)
SCALE_MULTIPLIER_GRID = (.75, 1., 1.25)
LATTICE_STRENGTH_GRID = (0., .5, 1.)
LATTICE_PSEUDOCOUNT = 5.
MAX_LATTICE_FACTOR = 4.
EVIDENCE_FIELDS = ("event_id", "league", "product", "settlement", "parent_model_id",
                   "information_set", "market_input", "prediction_kind",
                   "parent_fit_cutoff", "forecast_cutoff", "start_time_utc",
                   "result_available_at", "forecast_sha256", "result_source_sha256")


def code_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _scale_parameters(rows, features, ridge):
    errors = np.asarray([r["observed"] - r["predicted_mean"] for r in rows], float)
    if not features:
        scales = np.ones(len(rows))
        scaling = None
    else:
        x = np.asarray([[r["scale_features"][k] for k in features] for r in rows], float)
        mean, sd = x.mean(0), x.std(0)
        sd[sd == 0] = 1.
        design = np.column_stack([np.ones(len(x)), (x - mean) / sd])
        penalty = np.eye(design.shape[1]) * ridge
        penalty[0, 0] = 0.
        beta = np.linalg.solve(design.T @ design + penalty,
                               design.T @ np.log1p(errors ** 2))
        scales = np.exp(np.clip(design @ beta, -8., 16.) / 2.)
        scaling = {"features": list(features), "mean": mean.tolist(), "sd": sd.tolist(),
                   "beta": beta.tolist(), "ridge": ridge,
                   "log_squared_error_link": "log1p", "log_scale_clip": [-4., 8.]}
    residuals = errors / scales
    return {"residuals": residuals.tolist(), "scaling": scaling,
            "student_location": float(residuals.mean()),
            "student_standard_deviation": max(float(residuals.std()), .25),
            "minimum_standard_deviation": .25}


def _conditional_scale(state, features):
    s = state["scaling"]
    if s is None:
        if features:
            raise ValueError("UNUSED_SCALE_FEATURES")
        return 1., {}
    used = {k: finite((features or {})[k]) for k in s["features"]}
    if set(features or {}) != set(s["features"]):
        raise ValueError("SCALE_FEATURE_SCOPE_MISMATCH")
    x = (np.asarray(list(used.values())) - s["mean"]) / s["sd"]
    return float(np.exp(np.clip(np.r_[1., x] @ s["beta"], -8., 16.) / 2.)), used


def _student_parameters(state, mean, scale, parameters):
    df = parameters["degrees_of_freedom"]
    location = mean + state["student_location"] * scale
    width = (state["student_standard_deviation"] * scale *
             parameters["scale_multiplier"] * math.sqrt((df - 2.) / df))
    return location, width, df


def _raw_mass(grid, state, mean, scale, parameters):
    """Exact integer bins; survival subtraction prevents upper-tail cancellation."""
    grid = np.asarray(grid, dtype=np.int64)
    location, width, df = _student_parameters(state, mean, scale, parameters)
    lo, hi = (grid - .5 - location) / width, (grid + .5 - location) / width
    smooth = np.where(lo >= 0., t.sf(lo, df) - t.sf(hi, df),
                      t.cdf(hi, df) - t.cdf(lo, df))
    centers = mean + np.asarray(state["residuals"]) * scale
    lower = np.floor(centers).astype(np.int64)
    fractions = centers - lower
    empirical = np.zeros(len(grid))
    for points, mass in ((lower, 1. - fractions), (lower + 1, fractions)):
        positions = np.searchsorted(grid, points)
        valid = positions < len(grid)
        valid[valid] &= grid[positions[valid]] == points[valid]
        np.add.at(empirical, positions[valid], mass[valid] / len(centers))
    weight = parameters["student_weight"]
    return weight * smooth + (1. - weight) * empirical


def _lattice_factors(grid, lattice):
    factors = np.ones(len(grid))
    if lattice is not None:
        index = np.asarray(grid, int) - lattice["minimum_margin"]
        inside = (index >= 0) & (index < len(lattice["factors"]))
        factors[inside] = np.asarray(lattice["factors"])[index[inside]] ** lattice["strength"]
    return factors


def _normalization(state, mean, scale, parameters, ties, lattice):
    zero = float(_raw_mass([0], state, mean, scale, parameters)[0]) if not ties else 0.
    adjustment = 0.
    if lattice is not None and lattice["strength"]:
        grid = np.arange(lattice["minimum_margin"],
                         lattice["minimum_margin"] + len(lattice["factors"]))
        raw = _raw_mass(grid, state, mean, scale, parameters)
        if not ties:
            raw[grid == 0] = 0.
        adjustment = float(np.sum(raw * (_lattice_factors(grid, lattice) - 1.)))
    normalization = 1. - zero + adjustment
    if not math.isfinite(normalization) or normalization <= 0:
        raise ValueError("NO_LEGAL_SCORE_SUPPORT")
    return normalization, zero


def _negative_log_loss(rows, state, parameters, ties, lattice=None):
    losses = []
    for row in rows:
        features = {k: row["scale_features"][k] for k in state["scaling"]["features"]} if state["scaling"] else None
        scale, _ = _conditional_scale(state, features)
        y = int(row["observed"])
        probability = float(_raw_mass([y], state, row["predicted_mean"], scale, parameters)[0])
        probability *= float(_lattice_factors([y], lattice)[0])
        norm, _ = _normalization(state, row["predicted_mean"], scale, parameters, ties, lattice)
        if probability <= 0:
            raise ValueError("NONPOSITIVE_INTEGER_MASS")
        losses.append(-math.log(probability / norm))
    return float(np.mean(losses))


def _fit_lattice(rows, state, parameters, ties, strength):
    observed = np.asarray([r["observed"] for r in rows], int)
    lower, upper = int(observed.min()), int(observed.max())
    grid = np.arange(lower, upper + 1)
    expected = np.zeros(len(grid))
    for row in rows:
        features = {k: row["scale_features"][k] for k in state["scaling"]["features"]} if state["scaling"] else None
        scale, _ = _conditional_scale(state, features)
        norm, _ = _normalization(state, row["predicted_mean"], scale, parameters, ties, None)
        expected += _raw_mass(grid, state, row["predicted_mean"], scale, parameters) / norm
    actual = np.bincount(observed - lower, minlength=len(grid))
    factors = np.clip((actual + LATTICE_PSEUDOCOUNT) / (expected + LATTICE_PSEUDOCOUNT),
                      1. / MAX_LATTICE_FACTOR, MAX_LATTICE_FACTOR)
    if not ties and lower <= 0 <= upper:
        factors[-lower] = 1.
    return {"minimum_margin": lower, "factors": factors.tolist(), "strength": strength,
            "pseudocount": LATTICE_PSEUDOCOUNT, "factor_bounds": [1. / MAX_LATTICE_FACTOR, MAX_LATTICE_FACTOR],
            "outside_training_range_factor": 1., "basis": "OBSERVED_TO_EXPECTED_INTEGER_FREQUENCY"}


def fit(rows, *, league, settlement, parent_model_id, information_set, fitted_at,
        scale_features=(), ridge=10., market_input=False):
    """Fit from chronological OOF parent point forecasts, never from win odds.

    At least 60 rows are required. Hyperparameters use a later 30% tuning block;
    rows whose outcomes were unavailable at its first cutoff are purged from the
    inner fitting block. Final coefficients refit all supplied training rows.
    External evaluation must use later events absent from this complete cohort.
    """
    rows = list(rows)
    if len(rows) < MIN_TRAINING:
        raise ValueError("AT_LEAST_60_TRAINING_ROWS_REQUIRED_NOT_VALIDATION")
    if market_input is not False:
        raise ValueError("MARKET_BLIND_MARGIN_CHALLENGER_ONLY")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("TRAINING_ROW_OBJECT_REQUIRED")
        # Optional aliases must agree with the mandatory positive OOT claim.
        # Their absence is not a substitute for prediction_kind + chronology.
        if (("label_in_sample" in row and row["label_in_sample"] is not False) or
                ("oof" in row and row["oof"] is not True)):
            raise ValueError("CONTRADICTORY_OUT_OF_TIME_PROVENANCE")
    # Preserve the established chronology, settlement, source-hash and parent
    # checks. The returned artifact is not used or substituted for this model.
    try:
        checked = fit_residuals(rows, league=league, product="margin", settlement=settlement,
                                parent_model_id=parent_model_id, fitted_at=fitted_at,
                                information_set=information_set, market_input=False,
                                method="conditional_scale" if scale_features else "empirical",
                                scale_features=scale_features, ridge=ridge)
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError) as exc:
        raise ValueError("TRAINING_ROW_STRUCTURE_INVALID") from exc
    for row in rows:
        # Provenance fields are retained below; missing attestation never becomes
        # historical availability merely because chronology is consistent.
        for feature in scale_features:
            if re.search(r"(^|_)(observed|result|final|outcome)($|_)", feature, re.I):
                raise ValueError("OUTCOME_FEATURE_NOT_ALLOWED")
        if abs(row["observed"]) > MAX_ABSOLUTE_SUPPORT or abs(row["predicted_mean"]) > MAX_ABSOLUTE_SUPPORT:
            raise ValueError("MARGIN_OUTSIDE_NUMERICAL_CONTRACT")
    ordered = sorted(rows, key=lambda r: (stamp(r["forecast_cutoff"]), r["event_id"]))
    split = max(MIN_INNER_FIT, int(len(ordered) * .7))
    tune = ordered[split:]
    if len(tune) < MIN_INNER_TUNE:
        tune = ordered[-MIN_INNER_TUNE:]
    first_cutoff = min(stamp(r["forecast_cutoff"]) for r in tune)
    tune_ids = {r["event_id"] for r in tune}
    inner = [r for r in ordered if r["event_id"] not in tune_ids and stamp(r["result_available_at"]) < first_cutoff]
    if len(inner) < MIN_INNER_FIT or len(tune) < MIN_INNER_TUNE:
        raise ValueError("INSUFFICIENT_PURGED_CHRONOLOGICAL_TUNING_ROWS")
    state = _scale_parameters(inner, scale_features, float(ridge))
    ties = SETTLEMENTS[league][settlement]
    trials = []
    for df in DF_GRID:
        for weight in TAIL_WEIGHT_GRID:
            for multiplier in SCALE_MULTIPLIER_GRID:
                parameters = {"degrees_of_freedom": df, "student_weight": weight,
                              "scale_multiplier": multiplier}
                trials.append({**parameters, "tuning_log_loss": _negative_log_loss(tune, state, parameters, ties)})
    best = min(trials, key=lambda x: x["tuning_log_loss"])
    parameters = {k: best[k] for k in ("degrees_of_freedom", "student_weight", "scale_multiplier")}
    lattice = _fit_lattice(inner, state, parameters, ties, 0.)
    lattice_trials = []
    for strength in LATTICE_STRENGTH_GRID:
        lattice["strength"] = strength
        lattice_trials.append({"strength": strength,
                               "tuning_log_loss": _negative_log_loss(tune, state, parameters, ties, lattice)})
    selected_strength = min(lattice_trials, key=lambda x: x["tuning_log_loss"])["strength"]
    final_state = _scale_parameters(ordered, scale_features, float(ridge))
    final_lattice = _fit_lattice(ordered, final_state, parameters, ties, selected_strength)
    provenance = {k: sorted({str(r.get(k, "UNATTESTED")) for r in rows})
                  for k in ("source_capture_kind", "timestamp_basis", "historical_availability_proven")}
    model = {"schema": SCHEMA, "league": league, "product": "margin", "settlement": settlement,
             "orientation": "HOME_MINUS_AWAY", "parent_model_id": parent_model_id,
             "information_set": information_set, "fit_as_of_utc": fitted_at,
             "created_at_utc": writer_clock(), "code_sha256": code_hash(),
             "numpy_version": np.__version__, "scipy_version": scipy.__version__,
             "market_input": False, "training_n": len(rows), "training_sha256": digest(ordered),
             "training_event_ids": sorted(checked["training_event_ids"]),
             "training_evidence": [{k: r[k] for k in EVIDENCE_FIELDS} for r in ordered],
             "last_result_available_at": checked["last_result_available_at"],
             "source_provenance": provenance,
             "historical_availability_proven": all(r.get("historical_availability_proven") is True for r in rows),
             "state": final_state, "parameters": parameters, "lattice": final_lattice,
             "selection": {"objective": "LATER_INTERNAL_BLOCK_DISCRETE_LOG_LOSS",
                           "inner_training_n": len(inner), "tuning_n": len(tune),
                           "purged_n": len(rows) - len(inner) - len(tune),
                           "inner_training_event_ids": [r["event_id"] for r in inner],
                           "tuning_event_ids": [r["event_id"] for r in tune],
                           "first_tuning_forecast_cutoff": min((r["forecast_cutoff"] for r in tune), key=stamp),
                           "tail_trials": trials, "lattice_trials": lattice_trials,
                           "external_performance_evidence": False},
             "support_policy": {"tail_tolerance": TAIL_TOLERANCE,
                                "minimum_absolute_support": MINIMUM_ABSOLUTE_SUPPORT,
                                "max_absolute_support": MAX_ABSOLUTE_SUPPORT,
                                "zero_margin": "RETAIN" if ties else "CONDITION_OUT_EXPLICITLY",
                                "outside_represented_support": "OMITTED_TAIL_NOT_IMPOSSIBLE"},
             "status": "FITTED_RESEARCH_NOT_VALIDATED", "action_authority": False,
             "prospective_grade_eligible": False, "selected_default": False}
    model["model_id"] = f"{league}.margin.full_support.research." + digest(model)[:16]
    model["artifact_sha256"] = digest(model)
    validate_model(model)
    return model


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _positive_count(value, minimum=0):
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _numbers(values, length):
    _require(isinstance(values, list) and len(values) == length, "FITTED_VECTOR_LENGTH_INVALID")
    return np.asarray([finite(v) for v in values], dtype=float)


def _validate_fitted_fields(model):
    """Verify retained fitting evidence, not independent historical authenticity."""
    league, settlement = model["league"], model["settlement"]
    _require(league in SETTLEMENTS and settlement in SETTLEMENTS[league], "UNSUPPORTED_SETTLEMENT")
    _require(model["product"] == "margin" and model["orientation"] == "HOME_MINUS_AWAY",
             "MARGIN_CHALLENGER_SCOPE_INVALID")
    _require(model["status"] == "FITTED_RESEARCH_NOT_VALIDATED", "RESEARCH_ONLY")
    for field in ("parent_model_id", "information_set", "numpy_version", "scipy_version"):
        identity(model[field], field.upper())
    source_hash(model["training_sha256"])
    fitted_at = stamp(model["fit_as_of_utc"])
    stamp(model["created_at_utc"])
    last_result = stamp(model["last_result_available_at"])
    _require(last_result < fitted_at, "TRAINING_CHRONOLOGY_INVALID")
    n, ids, evidence = model["training_n"], model["training_event_ids"], model["training_evidence"]
    _require(_positive_count(n, MIN_TRAINING), "FITTED_TRAINING_COUNT_INVALID")
    _require(isinstance(ids, list) and len(ids) == n and
             all(isinstance(e, str) and e.strip() for e in ids) and ids == sorted(set(ids)),
             "FITTED_TRAINING_IDS_INVALID")
    _require(isinstance(evidence, list) and len(evidence) == n, "OUT_OF_TIME_EVIDENCE_REQUIRED")
    expected_scope = {k: model[k] for k in
                      ("league", "product", "settlement", "parent_model_id", "information_set")}
    rows = {}
    for row in evidence:
        _require(isinstance(row, dict), "TRAINING_ROW_OBJECT_REQUIRED")
        event = identity(row["event_id"], "EVENT_ID")
        _require(event not in rows, "DUPLICATE_TRAINING_EVENT")
        _require(all(row[k] == value for k, value in expected_scope.items()), "TRAINING_SCOPE_MISMATCH")
        _require(row["market_input"] is False, "TRAINING_MARKET_ROLE_MISMATCH")
        _require(row["prediction_kind"] == "CHRONOLOGICAL_OUT_OF_TIME", "OUT_OF_TIME_FORECASTS_REQUIRED")
        _require(("label_in_sample" not in row or row["label_in_sample"] is False) and
                 ("oof" not in row or row["oof"] is True), "CONTRADICTORY_OUT_OF_TIME_PROVENANCE")
        for field in ("forecast_sha256", "result_source_sha256"):
            source_hash(row[field])
        _require(stamp(row["parent_fit_cutoff"]) <= stamp(row["forecast_cutoff"]) <
                 stamp(row["start_time_utc"]) <= stamp(row["result_available_at"]) < fitted_at,
                 "TRAINING_CHRONOLOGY_INVALID")
        rows[event] = row
    _require(sorted(rows) == ids, "FITTED_TRAINING_IDS_INVALID")
    _require(max(stamp(row["result_available_at"]) for row in evidence) == last_result,
             "FITTED_RESULT_WINDOW_MISMATCH")
    selection = model["selection"]
    _require(selection["external_performance_evidence"] is False and
             selection["objective"] == "LATER_INTERNAL_BLOCK_DISCRETE_LOG_LOSS", "RESEARCH_ONLY")
    partitions = []
    for field, minimum in (("inner_training", MIN_INNER_FIT), ("tuning", MIN_INNER_TUNE)):
        count, events = selection[field + "_n"], selection[field + "_event_ids"]
        _require(_positive_count(count, minimum) and isinstance(events, list) and
                 len(events) == count and len(set(events)) == count and set(events) <= set(ids),
                 "FITTED_TUNING_PARTITION_INVALID")
        partitions.append(set(events))
    _require(not partitions[0] & partitions[1] and _positive_count(selection["purged_n"]) and
             sum(len(p) for p in partitions) + selection["purged_n"] == n,
             "FITTED_TUNING_PARTITION_INVALID")
    first_tune = stamp(selection["first_tuning_forecast_cutoff"])
    _require(first_tune == min(stamp(rows[e]["forecast_cutoff"]) for e in partitions[1]) and
             all(stamp(rows[e]["result_available_at"]) < first_tune for e in partitions[0]),
             "FITTED_TUNING_CHRONOLOGY_INVALID")

    state, parameters, lattice = model["state"], model["parameters"], model["lattice"]
    residuals = _numbers(state["residuals"], n)
    _require(finite(state["minimum_standard_deviation"]) == .25 and
             math.isclose(finite(state["student_location"]), float(residuals.mean()), rel_tol=1e-10, abs_tol=1e-12) and
             math.isclose(finite(state["student_standard_deviation"]), max(float(residuals.std()), .25), rel_tol=1e-10, abs_tol=1e-12),
             "FITTED_RESIDUAL_STATE_INVALID")
    scaling = state["scaling"]
    if scaling is not None:
        features = scaling["features"]
        _require(isinstance(features, list) and features and all(isinstance(k, str) and k for k in features) and
                 len(set(features)) == len(features), "SCALE_FEATURE_NAMES_INVALID")
        _require(not any(re.search(r"(^|_)(odds|spread|price|market|closing|moneyline|line|observed|result|final|outcome)($|_)",
                                   k, re.I) for k in features), "FORBIDDEN_SCALE_FEATURE")
        _numbers(scaling["mean"], len(features))
        _require(np.all(_numbers(scaling["sd"], len(features)) > 0), "FITTED_SCALE_INVALID")
        _numbers(scaling["beta"], len(features) + 1)
        _require(finite(scaling["ridge"]) > 0 and scaling["log_squared_error_link"] == "log1p" and
                 scaling["log_scale_clip"] == [-4., 8.], "FITTED_SCALE_INVALID")
    grids = {"degrees_of_freedom": DF_GRID, "student_weight": TAIL_WEIGHT_GRID,
             "scale_multiplier": SCALE_MULTIPLIER_GRID}
    _require(all(finite(parameters[k]) in values for k, values in grids.items()), "FITTED_TAIL_PARAMETERS_INVALID")
    trials = selection["tail_trials"]
    _require(isinstance(trials, list) and len(trials) == len(DF_GRID) * len(TAIL_WEIGHT_GRID) * len(SCALE_MULTIPLIER_GRID),
             "FITTED_TAIL_TRIALS_INVALID")
    combinations = []
    for trial in trials:
        _require(all(finite(trial[k]) in values for k, values in grids.items()), "FITTED_TAIL_TRIALS_INVALID")
        finite(trial["tuning_log_loss"])
        combinations.append(tuple(trial[k] for k in grids))
    _require(len(set(combinations)) == len(trials), "FITTED_TAIL_TRIALS_INVALID")
    selected = min(trials, key=lambda trial: trial["tuning_log_loss"])
    _require(all(parameters[k] == selected[k] for k in grids), "FITTED_SELECTION_MISMATCH")
    _require(isinstance(lattice["minimum_margin"], int) and not isinstance(lattice["minimum_margin"], bool) and
             -MAX_ABSOLUTE_SUPPORT <= lattice["minimum_margin"] <= MAX_ABSOLUTE_SUPPORT,
             "FITTED_LATTICE_INVALID")
    factors = _numbers(lattice["factors"], len(lattice["factors"]))
    _require(len(factors) > 0 and lattice["minimum_margin"] + len(factors) - 1 <= MAX_ABSOLUTE_SUPPORT and
             np.all((factors >= 1. / MAX_LATTICE_FACTOR) & (factors <= MAX_LATTICE_FACTOR)) and
             finite(lattice["strength"]) in LATTICE_STRENGTH_GRID and
             lattice["pseudocount"] == LATTICE_PSEUDOCOUNT and
             lattice["factor_bounds"] == [1. / MAX_LATTICE_FACTOR, MAX_LATTICE_FACTOR] and
             lattice["outside_training_range_factor"] == 1. and
             lattice["basis"] == "OBSERVED_TO_EXPECTED_INTEGER_FREQUENCY", "FITTED_LATTICE_INVALID")
    lattice_trials = selection["lattice_trials"]
    _require(isinstance(lattice_trials, list) and len(lattice_trials) == len(LATTICE_STRENGTH_GRID) and
             {finite(trial["strength"]) for trial in lattice_trials} == set(LATTICE_STRENGTH_GRID),
             "FITTED_LATTICE_TRIALS_INVALID")
    for trial in lattice_trials:
        finite(trial["tuning_log_loss"])
    _require(lattice["strength"] == min(lattice_trials, key=lambda trial: trial["tuning_log_loss"])["strength"],
             "FITTED_SELECTION_MISMATCH")
    _require(model["support_policy"] == {"tail_tolerance": TAIL_TOLERANCE,
             "minimum_absolute_support": MINIMUM_ABSOLUTE_SUPPORT, "max_absolute_support": MAX_ABSOLUTE_SUPPORT,
             "zero_margin": "RETAIN" if SETTLEMENTS[league][settlement] else "CONDITION_OUT_EXPLICITLY",
             "outside_represented_support": "OMITTED_TAIL_NOT_IMPOSSIBLE"}, "FITTED_SUPPORT_POLICY_INVALID")
    _require(isinstance(model["historical_availability_proven"], bool) and isinstance(model["source_provenance"], dict),
             "SOURCE_PROVENANCE_REQUIRED")
    for key in ("source_capture_kind", "timestamp_basis", "historical_availability_proven"):
        values = model["source_provenance"][key]
        _require(isinstance(values, list) and values and all(isinstance(v, str) and v for v in values),
                 "SOURCE_PROVENANCE_REQUIRED")
    _require(model["historical_availability_proven"] ==
             (model["source_provenance"]["historical_availability_proven"] == ["True"]),
             "SOURCE_ATTESTATION_CONTRADICTION")


def validate_model(model):
    if not isinstance(model, dict):
        raise ValueError("MARGIN_CHALLENGER_OBJECT_REQUIRED")
    material = dict(model)
    checksum = material.pop("artifact_sha256", None)
    try:
        matches = material.get("schema") == SCHEMA and digest(material) == checksum
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("MARGIN_CHALLENGER_SERIALIZATION_INVALID") from exc
    if not matches:
        raise ValueError("MARGIN_CHALLENGER_HASH_MISMATCH")
    if model.get("code_sha256") != code_hash():
        raise ValueError("MARGIN_CHALLENGER_CODE_DRIFT")
    if any(model.get(k) is not False for k in ("action_authority", "prospective_grade_eligible", "selected_default", "market_input")):
        raise ValueError("RESEARCH_ONLY")
    try:
        _validate_fitted_fields(model)
        model_id = material.pop("model_id")
        _require(model_id == f"{model['league']}.margin.full_support.research." + digest(material)[:16],
                 "MARGIN_CHALLENGER_ID_MISMATCH")
    except (KeyError, TypeError, AttributeError, IndexError, OverflowError) as exc:
        raise ValueError("MARGIN_CHALLENGER_STRUCTURE_INVALID") from exc
    return checksum


def predict(model, *, mean, event_id, cutoff, start_time_utc, parent_model_id,
            information_set, parent_forecast_sha256, scale_features=None):
    """Return a standard discrete distribution usable by shared pricing/MC APIs."""
    checksum = validate_model(model)
    identity(event_id, "EVENT_ID")
    source_hash(parent_forecast_sha256)
    if parent_model_id != model["parent_model_id"] or information_set != model["information_set"]:
        raise ValueError("PARENT_SCOPE_MISMATCH")
    if event_id in model["training_event_ids"]:
        raise ValueError("TRAINING_EVENT_REUSED")
    if not stamp(model["fit_as_of_utc"]) <= stamp(cutoff) < stamp(start_time_utc):
        raise ValueError("FORECAST_CHRONOLOGY_INVALID")
    mean = finite(mean)
    if abs(mean) > MAX_ABSOLUTE_SUPPORT:
        raise ValueError("MARGIN_OUTSIDE_NUMERICAL_CONTRACT")
    state, parameters, lattice = model["state"], model["parameters"], model["lattice"]
    scale, used = _conditional_scale(state, scale_features)
    location, width, df = _student_parameters(state, mean, scale, parameters)
    ties = SETTLEMENTS[model["league"]][model["settlement"]]
    normalization, removed_zero = _normalization(state, mean, scale, parameters, ties, lattice)
    # Account conservatively for the largest lattice factor and legal-support
    # normalization when setting the untruncated Student-t quantiles.
    q = min(.01, TAIL_TOLERANCE * normalization /
            (2. * parameters["student_weight"] * MAX_LATTICE_FACTOR))
    centers = mean + np.asarray(state["residuals"]) * scale
    low = math.floor(min(location + width * t.ppf(q, df), float(centers.min()))) - 1
    high = math.ceil(max(location + width * t.isf(q, df), float(centers.max()))) + 1
    # This numerical envelope is not a fitted statistical coefficient. Even a
    # narrow training sample retains common sporting extremes (e.g. +52 CFB)
    # instead of dropping tiny yet positive probabilities at its tail cutoff.
    low = max(min(low, -MINIMUM_ABSOLUTE_SUPPORT), -MAX_ABSOLUTE_SUPPORT)
    high = min(max(high, MINIMUM_ABSOLUTE_SUPPORT), MAX_ABSOLUTE_SUPPORT)
    if low >= high:
        raise ValueError("NO_REPRESENTABLE_MARGIN_SUPPORT")
    grid = np.arange(low, high + 1)
    raw = _raw_mass(grid, state, mean, scale, parameters)
    weighted = raw * _lattice_factors(grid, lattice)
    if not ties:
        weighted[grid == 0] = 0.
    tail = max(0., 1. - float(weighted.sum()) / normalization)
    if tail > TAIL_TOLERANCE * 1.01:
        raise ValueError("TAIL_TRUNCATION_EXCEEDS_CONTRACT")
    legal = grid != 0 if not ties else np.ones(len(grid), bool)
    if np.any(weighted[legal] <= 0):
        raise ValueError("NONPOSITIVE_INTEGER_MASS")
    return make_distribution(grid[legal].tolist(), weighted[legal].tolist(),
                             league=model["league"], product="margin", settlement=model["settlement"],
                             model_id=model["model_id"], provenance={
                                 "event_id": event_id, "cutoff": cutoff, "start_time_utc": start_time_utc,
                                 "orientation": "HOME_MINUS_AWAY", "parent_model_id": parent_model_id,
                                 "parent_forecast_sha256": parent_forecast_sha256,
                                 "fitted_artifact_sha256": checksum, "information_set": information_set,
                                 "artifact_existed_at_forecast_cutoff": stamp(model["created_at_utc"]) <= stamp(cutoff),
                                 "historical_availability_proven": model["historical_availability_proven"],
                                 "mean_input": mean, "scale_features_used": used, "conditional_scale": scale,
                                 "market_input": False, "joint_score_distribution": False,
                                 "removed_zero_margin_mass_before_conditioning": removed_zero,
                                 "no_tie_conditioning_is_mechanistic_overtime_model": False,
                                 "support_policy": "CONTIGUOUS_LEGAL_INTEGERS_WITH_REPORTED_TAIL_TRUNCATION",
                                 "represented_minimum": low, "represented_maximum": high,
                                 "omitted_tail_probability_before_finite_renormalization": tail,
                                 "tail_tolerance": TAIL_TOLERANCE,
                                 "outside_represented_support": "OMITTED_TAIL_NOT_IMPOSSIBLE"})
