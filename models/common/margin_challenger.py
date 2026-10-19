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
    # Preserve the established chronology, settlement, source-hash and parent
    # checks. The returned artifact is not used or substituted for this model.
    checked = fit_residuals(rows, league=league, product="margin", settlement=settlement,
                            parent_model_id=parent_model_id, fitted_at=fitted_at,
                            information_set=information_set, market_input=False,
                            method="conditional_scale" if scale_features else "empirical",
                            scale_features=scale_features, ridge=ridge)
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
    return model


def validate_model(model):
    material = dict(model)
    checksum = material.pop("artifact_sha256", None)
    if material.get("schema") != SCHEMA or digest(material) != checksum:
        raise ValueError("MARGIN_CHALLENGER_HASH_MISMATCH")
    if model.get("code_sha256") != code_hash():
        raise ValueError("MARGIN_CHALLENGER_CODE_DRIFT")
    if any(model.get(k) is not False for k in ("action_authority", "prospective_grade_eligible", "selected_default", "market_input")):
        raise ValueError("RESEARCH_ONLY")
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
