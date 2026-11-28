"""Versioned joint home/away forecast-error volatility research.

The parent point forecast is retained. Bias, outcome dispersion, conditional
scale, and Monte Carlo precision are separate quantities. Nothing in this
module selects a model, rewrites a forecast, or authorizes a wager.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np

from models.common import discrete_research as D

SCHEMA = "sports.joint_score_distribution.research.v1"
FIT_SCHEMA = "sports.volatility_matrix.research.v1"
LUCK_SCHEMA = "sports.luck_accounting.research.v1"
EVALUATION_SCHEMA = "sports.volatility_evaluation.research.v1"
SETTLEMENTS = D.SETTLEMENTS
SPORT_LIMITATIONS = {
    "nfl": ["INTEGER_EMPIRICAL_SCORE_CELLS", "NO_DRIVE_LEVEL_OT_BRANCH", "KEY_NUMBERS_ONLY_IF_PRESENT_IN_TRAINING_RESIDUALS"],
    "cfb": ["INTEGER_EMPIRICAL_SCORE_CELLS", "NO_DRIVE_LEVEL_OT_BRANCH", "KEY_NUMBERS_ONLY_IF_PRESENT_IN_TRAINING_RESIDUALS"],
    "nba": ["INTEGER_EMPIRICAL_SCORE_CELLS", "NO_EXPLICIT_OT_OR_ENDGAME_FOULING_BRANCH"],
    "wnba": ["INTEGER_EMPIRICAL_SCORE_CELLS", "NO_EXPLICIT_OT_OR_AVAILABILITY_MIXTURE_BRANCH"],
    "mlb": ["PAIRED_FINAL_SCORE_RESIDUALS_ONLY", "NO_INNING_HOME_SCORE_CENSORING_OR_EXTRA_INNING_BRANCH"],
    "nhl": ["PAIRED_FINAL_SCORE_RESIDUALS_ONLY", "NO_EXPLICIT_EMPTY_NET_OR_OT_SO_BRANCH"],
    "mls": ["PAIRED_REGULATION_SCORE_RESIDUALS_ONLY", "NO_DIXON_COLES_LOW_SCORE_CORRECTION"],
}


def code_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def copy_safe_json(value):
    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))


def _scope(league, settlement):
    if league not in SETTLEMENTS or settlement not in SETTLEMENTS[league]:
        raise ValueError("UNSUPPORTED_SETTLEMENT")


def _score(value, label):
    value = D.finite(value)
    if value < 0:
        raise ValueError("NEGATIVE_SCORE")
    return value


def _observed_score(value):
    value = _score(value, "OBSERVED")
    if value != round(value):
        raise ValueError("INTEGER_OBSERVED_SCORE_REQUIRED")
    return int(value)


def _check_final(home, away, league, settlement):
    _scope(league, settlement)
    if home == away and not SETTLEMENTS[league][settlement]:
        raise ValueError("FINAL_TIE_UNSUPPORTED")


def _matrix_psd(matrix):
    a = np.asarray(matrix, dtype=float)
    if a.shape != (2, 2) or not np.isfinite(a).all():
        raise ValueError("COVARIANCE_MATRIX_INVALID")
    if not np.allclose(a, a.T, rtol=0, atol=1e-12):
        raise ValueError("COVARIANCE_NOT_SYMMETRIC")
    if np.linalg.eigvalsh(a).min() < -1e-10:
        raise ValueError("COVARIANCE_NOT_POSITIVE_SEMIDEFINITE")
    return a


def _sqrt_psd(a):
    values, vectors = np.linalg.eigh(_matrix_psd(a))
    if values.min() <= 0:
        raise ValueError("SINGULAR_RESIDUAL_COVARIANCE")
    return (vectors * np.sqrt(values)) @ vectors.T


def _inv_sqrt_psd(a):
    values, vectors = np.linalg.eigh(_matrix_psd(a))
    if values.min() <= 0:
        raise ValueError("SINGULAR_RESIDUAL_COVARIANCE")
    return (vectors * (1 / np.sqrt(values))) @ vectors.T


def _ledoit_wolf(x):
    """Ledoit-Wolf shrinkage toward a spherical target, using population S."""
    n, p = x.shape
    s = x.T @ x / n
    mu = float(np.trace(s) / p)
    if not math.isfinite(mu) or mu <= 0:
        raise ValueError("ZERO_RESIDUAL_VARIANCE")
    delta = float(np.sum((s - mu * np.eye(p)) ** 2) / p)
    beta_bar = float(sum(np.sum((np.outer(row, row) - s) ** 2) for row in x) / (n * n * p))
    shrinkage = 0.0 if delta <= 1e-20 else min(1.0, max(0.0, beta_bar / delta))
    target = (1 - shrinkage) * s + shrinkage * mu * np.eye(p)
    return target, {"name": "LEDOIT_WOLF_SPHERICAL", "shrinkage": shrinkage,
                    "target_mean_variance": mu, "sample_estimator": "POPULATION_COVARIANCE"}


def _scale_fit(errors, features, names, ridge):
    x = np.asarray(features, dtype=float)
    mean = x.mean(axis=0)
    sd = x.std(axis=0)
    sd[sd == 0] = 1.0
    design = np.column_stack([np.ones(len(x)), (x - mean) / sd])
    penalty = np.eye(design.shape[1]) * ridge
    penalty[0, 0] = 0.0
    target = np.log1p(np.mean(errors ** 2, axis=1))
    beta = np.linalg.solve(design.T @ design + penalty, design.T @ target)
    scales = np.exp(np.clip(design @ beta, -8, 16) / 2)
    model = {"features": list(names), "mean": mean.tolist(), "sd": sd.tolist(),
             "beta": beta.tolist(), "ridge": ridge,
             "target": "LOG1P_MEAN_SQUARED_CENTERED_HOME_AWAY_ERROR",
             "convention": "SQRT_1_PLUS_RIDGE_ESTIMATED_CENTERED_MSE_FLOORED_AT_ONE",
             "fit_and_scale_estimated_on_same_training_rows_not_predictive_validation": True}
    return model, scales


def _scale(model, values):
    if model is None:
        # Parent snapshots may contain many features unrelated to this fit.
        return 1.0, {}
    try:
        used = {k: D.finite((values or {})[k]) for k in model["features"]}
    except KeyError as exc:
        raise ValueError("MISSING_SCALE_FEATURE") from exc
    x = (np.asarray(list(used.values())) - np.asarray(model["mean"])) / np.asarray(model["sd"])
    scale = float(np.exp(np.clip(np.r_[1.0, x] @ np.asarray(model["beta"]), -8, 16) / 2))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("CONDITIONAL_SCALE_INVALID")
    return scale, used


def fit(rows, *, league, settlement, parent_model_id, information_set, fitted_at,
        method="empirical", scale_features=(), ridge=10.0, market_input=False,
        source_provenance=None):
    """Fit paired OOF score errors; at least 30 rows is a software floor only."""
    _scope(league, settlement)
    if isinstance(scale_features, (str, bytes)):
        raise ValueError("SCALE_FEATURE_NAMES_INVALID")
    scale_features = tuple(scale_features)
    source_provenance = source_provenance or {}
    if not isinstance(source_provenance, dict):
        raise ValueError("SOURCE_PROVENANCE_OBJECT_REQUIRED")
    D.digest(source_provenance)  # JSON-safe, finite values only.
    D.identity(parent_model_id, "PARENT_MODEL_ID")
    D.identity(information_set, "INFORMATION_SET")
    if method not in {"empirical", "ledoit_wolf"}:
        raise ValueError("METHOD_INVALID")
    if len(rows) < 30:
        raise ValueError("AT_LEAST_30_TRAINING_ROWS_REQUIRED_NOT_VALIDATION")
    if not isinstance(market_input, bool):
        raise ValueError("MARKET_INPUT_ROLE_REQUIRED")
    if len(set(scale_features)) != len(scale_features) or any(not isinstance(k, str) or not k for k in scale_features):
        raise ValueError("SCALE_FEATURE_NAMES_INVALID")
    if not market_input and any(re.search(r"(^|_)(odds|spread|price|market|closing|moneyline|line)($|_)", k, re.I)
                                for k in scale_features):
        raise ValueError("MARKET_FEATURE_IN_MARKET_BLIND_ARM")
    if D.finite(ridge) <= 0:
        raise ValueError("POSITIVE_RIDGE_REQUIRED")
    raw, features, ids, bounds = [], [], set(), []
    for row in rows:
        event_id = D.identity(row["event_id"], "EVENT_ID")
        if event_id in ids:
            raise ValueError("DUPLICATE_TRAINING_EVENT")
        ids.add(event_id)
        expected = {"league": league, "settlement": settlement,
                    "parent_model_id": parent_model_id, "information_set": information_set}
        if any(row.get(k) != v for k, v in expected.items()):
            raise ValueError("TRAINING_SCOPE_MISMATCH")
        if row.get("market_input") is not market_input:
            raise ValueError("TRAINING_MARKET_ROLE_MISMATCH")
        for key in ("forecast_sha256", "result_source_sha256"):
            D.source_hash(row[key])
        if row.get("prediction_kind") != "CHRONOLOGICAL_OUT_OF_TIME":
            raise ValueError("OUT_OF_TIME_FORECASTS_REQUIRED")
        if not (D.stamp(row["parent_fit_cutoff"]) <= D.stamp(row["forecast_cutoff"])
                < D.stamp(row["start_time_utc"]) <= D.stamp(row["result_available_at"])
                < D.stamp(fitted_at)):
            raise ValueError("TRAINING_CHRONOLOGY_INVALID")
        actual_home = _observed_score(row["actual_home"])
        actual_away = _observed_score(row["actual_away"])
        _check_final(actual_home, actual_away, league, settlement)
        predicted_home = _score(row["predicted_home"], "PREDICTED")
        predicted_away = _score(row["predicted_away"], "PREDICTED")
        raw.append([actual_home - predicted_home, actual_away - predicted_away])
        try:
            features.append([D.finite(row["scale_features"][k]) for k in scale_features])
        except KeyError as exc:
            raise ValueError("MISSING_SCALE_FEATURE") from exc
        bounds.append(row["result_available_at"])
    raw = np.asarray(raw, dtype=float)
    bias = raw.mean(axis=0)
    scaling, scales = (_scale_fit(raw - bias, features, scale_features, ridge)
                       if scale_features else (None, np.ones(len(raw))))
    scaled = (raw - bias) / scales[:, None]
    centered = scaled - scaled.mean(axis=0)
    sample_cov = np.cov(centered, rowvar=False, ddof=1)
    _matrix_psd(sample_cov)
    if method == "ledoit_wolf":
        covariance, shrinkage = _ledoit_wolf(centered)
        transform = _sqrt_psd(covariance) @ _inv_sqrt_psd(sample_cov)
        retained = centered @ transform.T
        covariance = np.cov(retained, rowvar=False, ddof=1)
    else:
        shrinkage = {"name": "NONE", "shrinkage": 0.0}
        transform = np.eye(2)
        retained = centered
        covariance = sample_cov
    covariance = _matrix_psd(covariance)
    model = {
        "schema": FIT_SCHEMA, "league": league, "settlement": settlement,
        "parent_model_id": parent_model_id, "information_set": information_set,
        "method": method, "fit_as_of_utc": fitted_at, "created_at_utc": D.writer_clock(),
        "training_n": len(rows), "training_event_ids": sorted(ids),
        "training_sha256": D.digest(rows), "last_result_available_at": max(bounds, key=D.stamp),
        "market_input": market_input, "source_provenance": source_provenance,
        "mean_bias_actual_minus_predicted": bias.tolist(),
        "bias_policy": "REPORT_SEPARATELY_RETAIN_PARENT_POINT_MEAN",
        "covariance_home_away": covariance.tolist(), "shrinkage": shrinkage,
        "residual_center": scaled.mean(axis=0).tolist(), "residual_transform": transform.tolist(),
        "residuals_centered_transformed": retained.tolist(), "scaling": scaling,
        "limitations": SPORT_LIMITATIONS[league],
        "code_sha256": code_hash(), "discrete_research_code_sha256": D.code_hash(),
        "numpy_version": np.__version__, "status": "FITTED_RESEARCH_NOT_VALIDATED",
        "prospective_grade_eligible": False, "action_authority": False,
    }
    model["model_id"] = f"{league}.joint_score.{method}.research." + D.digest(model)[:16]
    model["artifact_sha256"] = D.digest(model)
    return model


def _validate_fit(model):
    material = dict(model)
    artifact_hash = material.pop("artifact_sha256", None)
    if material.get("schema") != FIT_SCHEMA or D.digest(material) != artifact_hash:
        raise ValueError("FITTED_ARTIFACT_HASH_MISMATCH")
    if model.get("code_sha256") != code_hash() or model.get("discrete_research_code_sha256") != D.code_hash():
        raise ValueError("FITTED_CODE_DRIFT")
    if model.get("action_authority") is not False or model.get("prospective_grade_eligible") is not False:
        raise ValueError("RESEARCH_ONLY")
    _scope(model["league"], model["settlement"])
    _matrix_psd(model["covariance_home_away"])
    return artifact_hash


def volatility(model, *, scale_features=None):
    """Return analytic predictive dispersion; bias is deliberately not added."""
    _validate_fit(model)
    scale, used = _scale(model["scaling"], scale_features or {})
    covariance = _matrix_psd(model["covariance_home_away"]) * scale * scale
    home_var, away_var = float(covariance[0, 0]), float(covariance[1, 1])
    shared = float(covariance[0, 1])
    correlation = shared / math.sqrt(home_var * away_var) if home_var > 0 and away_var > 0 else None
    pool_scale = (model["training_n"] - 1) / model["training_n"]
    return {"home_score_variance": home_var, "away_score_variance": away_var,
            "covariance_estimator": "SAMPLE_COVARIANCE_DDOF_1",
            "empirical_residual_pool_population_scale": pool_scale,
            "empirical_margin_variance_before_discretization": (home_var + away_var - 2*shared) * pool_scale,
            "empirical_total_variance_before_discretization": (home_var + away_var + 2*shared) * pool_scale,
            "home_away_covariance": shared, "home_away_correlation": correlation,
            "home_score_sd": math.sqrt(home_var), "away_score_sd": math.sqrt(away_var),
            "margin_variance": home_var + away_var - 2 * shared,
            "total_variance": home_var + away_var + 2 * shared,
            "margin_sd": math.sqrt(max(0.0, home_var + away_var - 2 * shared)),
            "total_sd": math.sqrt(max(0.0, home_var + away_var + 2 * shared)),
            "conditional_scale": scale, "scale_features_used": used,
            "mean_bias_actual_minus_predicted": list(model["mean_bias_actual_minus_predicted"]),
            "bias_applied_to_point_forecast": False,
            "predictive_sd_not_monte_carlo_se": True}


def make_joint(home_scores, away_scores, masses, *, league, settlement, model_id, provenance):
    _scope(league, settlement)
    D.identity(model_id, "MODEL_ID")
    home, away, weights = D.vector(home_scores), D.vector(away_scores), D.vector(masses)
    if home.shape != away.shape or home.shape != weights.shape or np.any(weights < 0) or weights.sum() <= 0:
        raise ValueError("WEIGHTS_INVALID")
    if not np.equal(home, np.rint(home)).all() or not np.equal(away, np.rint(away)).all():
        raise ValueError("INTEGER_SUPPORT_REQUIRED")
    if np.any(home < 0) or np.any(away < 0):
        raise ValueError("NEGATIVE_SCORE")
    if not SETTLEMENTS[league][settlement] and np.any((home == away) & (weights > 0)):
        raise ValueError("FINAL_TIE_UNSUPPORTED")
    pairs = np.column_stack([home, away]).astype(np.int64)
    unique, inverse = np.unique(pairs, axis=0, return_inverse=True)
    mass = np.bincount(inverse, weights=weights, minlength=len(unique))
    keep = mass > 0
    unique, mass = unique[keep], mass[keep]
    mass = mass / mass.sum()
    out = {"schema": SCHEMA, "league": league, "settlement": settlement, "model_id": model_id,
           "home_scores": unique[:, 0].tolist(), "away_scores": unique[:, 1].tolist(),
           "masses": mass.tolist(), "provenance": provenance, "status": "DIAGNOSTIC",
           "joint_score_distribution": True, "prospective_grade_eligible": False,
           "action_authority": False}
    out["distribution_sha256"] = D.digest(out)
    return out


def validate(distribution):
    material = dict(distribution)
    h = material.pop("distribution_sha256", None)
    if material.get("schema") != SCHEMA or D.digest(material) != h:
        raise ValueError("DISTRIBUTION_HASH_MISMATCH")
    if distribution.get("action_authority") is not False or distribution.get("prospective_grade_eligible") is not False:
        raise ValueError("RESEARCH_ONLY")
    rebuilt = make_joint(distribution["home_scores"], distribution["away_scores"], distribution["masses"],
                         league=distribution["league"], settlement=distribution["settlement"],
                         model_id=distribution["model_id"], provenance=distribution["provenance"])
    if not math.isclose(sum(distribution["masses"]), 1.0, abs_tol=1e-10):
        raise ValueError("PROBABILITY_MASS_INVALID")
    for key in ("home_scores", "away_scores"):
        if distribution[key] != rebuilt[key]:
            raise ValueError("CANONICAL_SUPPORT_REQUIRED")
    if len(distribution["masses"]) != len(rebuilt["masses"]):
        raise ValueError("CANONICAL_SUPPORT_REQUIRED")
    return (np.asarray(distribution["home_scores"], dtype=np.int64),
            np.asarray(distribution["away_scores"], dtype=np.int64),
            np.asarray(distribution["masses"], dtype=float))


def predict(model, *, home_mean, away_mean, event_id, cutoff, parent_model_id,
            information_set, parent_forecast_sha256, scale_features=None, start_time_utc=None):
    artifact_hash = _validate_fit(model)
    D.identity(event_id, "EVENT_ID")
    D.source_hash(parent_forecast_sha256)
    if event_id in model["training_event_ids"]:
        raise ValueError("TRAINING_EVENT_REUSED")
    if parent_model_id != model["parent_model_id"] or information_set != model["information_set"]:
        raise ValueError("PARENT_SCOPE_MISMATCH")
    if D.stamp(model["fit_as_of_utc"]) > D.stamp(cutoff):
        raise ValueError("FUTURE_FITTED_ARTIFACT")
    home_mean, away_mean = _score(home_mean, "HOME"), _score(away_mean, "AWAY")
    if start_time_utc is not None and not D.stamp(cutoff) < D.stamp(start_time_utc):
        raise ValueError("PARENT_CUTOFF_NOT_PREGAME")
    scale, used = _scale(model["scaling"], scale_features or {})
    residuals = np.asarray(model["residuals_centered_transformed"], dtype=float) * scale
    home_values = home_mean + residuals[:, 0]
    away_values = away_mean + residuals[:, 1]
    # Independent linear fractional allocation preserves each cell's pre-legal-
    # conditioning home/away means while retaining paired residual identity.
    home_lo = np.floor(home_values); home_frac = home_values - home_lo
    away_lo = np.floor(away_values); away_frac = away_values - away_lo
    # Create all four combinations per residual.
    home = np.column_stack([home_lo, home_lo, home_lo + 1, home_lo + 1]).ravel()
    away = np.column_stack([away_lo, away_lo + 1, away_lo, away_lo + 1]).ravel()
    mass = np.column_stack([(1-home_frac)*(1-away_frac), (1-home_frac)*away_frac,
                            home_frac*(1-away_frac), home_frac*away_frac]).ravel()
    legal = (home >= 0) & (away >= 0)
    if not SETTLEMENTS[model["league"]][model["settlement"]]:
        legal &= home != away
    removed = float(mass[~legal].sum() / mass.sum())
    # Bilinear allocation preserves means and pre-conditioning score covariance,
    # but adds rounding variance to each marginal and therefore margin/total.
    home_rounding_variance = float(np.mean(home_frac * (1-home_frac)))
    away_rounding_variance = float(np.mean(away_frac * (1-away_frac)))
    if not np.any(mass[legal] > 0):
        raise ValueError("NO_LEGAL_SCORE_SUPPORT")
    provenance = {"event_id": event_id, "cutoff": cutoff,
                  "parent_model_id": parent_model_id, "information_set": information_set,
                  "parent_forecast_sha256": parent_forecast_sha256,
                  "fit_source_provenance": copy_safe_json(model["source_provenance"]),
                  "fitted_artifact_sha256": artifact_hash,
                  "artifact_existed_at_forecast_cutoff": D.stamp(model["created_at_utc"]) <= D.stamp(cutoff),
                  "parent_home_mean": home_mean, "parent_away_mean": away_mean,
                  "start_time_utc": start_time_utc,
                  "parent_point_mean_policy": "RETAINED_BEFORE_LEGAL_SUPPORT_CONDITIONING",
                  "mean_bias_not_applied": True, "conditional_scale": scale,
                  "scale_features_used": used, "market_input": model["market_input"],
                  "removed_illegal_support_mass": removed,
                  "support_policy": "CONDITION_ON_LEGAL_SUPPORT",
                  "volatility": volatility(model, scale_features=used),
                  "analytic_volatility_excludes_discretization_and_legal_conditioning": True,
                  "emitted_support_moments_are_authoritative_for_distribution": True,
                  "discretization_policy": "BILINEAR_LINEAR_FRACTIONAL_CELLS_ADD_ROUNDING_VARIANCE",
                  "pre_conditioning_rounding_variance": {
                      "home": home_rounding_variance, "away": away_rounding_variance,
                      "margin_and_total": home_rounding_variance + away_rounding_variance},
                  "limitations": list(model["limitations"]),
                  "monte_carlo_draws_are_not_predictive_evidence": True}
    return make_joint(home[legal].tolist(), away[legal].tolist(), mass[legal].tolist(),
                      league=model["league"], settlement=model["settlement"],
                      model_id=model["model_id"], provenance=provenance)


def moments(distribution):
    home, away, mass = validate(distribution)
    hm, am = float(home @ mass), float(away @ mass)
    centered = np.column_stack([home - hm, away - am])
    covariance = centered.T @ (centered * mass[:, None])
    margin = home - away; total = home + away
    mm, tm = float(margin @ mass), float(total @ mass)
    return {"home_mean": hm, "away_mean": am, "margin_mean": mm, "total_mean": tm,
            "home_score_sd": math.sqrt(max(0.0, float(covariance[0, 0]))),
            "away_score_sd": math.sqrt(max(0.0, float(covariance[1, 1]))),
            "home_away_covariance": float(covariance[0, 1]),
            "margin_sd": math.sqrt(max(0.0, float(((margin-mm)**2) @ mass))),
            "total_sd": math.sqrt(max(0.0, float(((total-tm)**2) @ mass)))}


def derive(distribution, product):
    if product not in {"margin", "total"}:
        raise ValueError("UNSUPPORTED_PRODUCT")
    home, away, mass = validate(distribution)
    values = home - away if product == "margin" else home + away
    provenance = {"parent_joint_distribution_sha256": distribution["distribution_sha256"],
                  "event_id": distribution["provenance"].get("event_id"),
                  "cutoff": distribution["provenance"].get("cutoff"),
                  "derivation": "EXACT_PAIRED_SCORE_MARGINAL",
                  "joint_score_distribution": True}
    return D.make_distribution(values.tolist(), mass.tolist(), league=distribution["league"],
                               product=product, settlement=distribution["settlement"],
                               model_id=distribution["model_id"] + "." + product,
                               provenance=provenance)


def energy_score(distribution, actual_home, actual_away):
    """Multivariate proper score on predictive-SD-standardized paired scores."""
    actual_home, actual_away = _observed_score(actual_home), _observed_score(actual_away)
    home, away, mass = validate(distribution)
    m = moments(distribution)
    scales = np.array([m["home_score_sd"] or 1.0, m["away_score_sd"] or 1.0])
    points = np.column_stack([home, away]) / scales
    observed = np.array([actual_home, actual_away]) / scales
    first = float(np.linalg.norm(points - observed, axis=1) @ mass)
    distances = np.linalg.norm(points[:, None, :] - points[None, :, :], axis=2)
    second = .5 * float(np.sum(distances * mass[:, None] * mass[None, :]))
    return {"energy_score": first-second, "component_scale": scales.tolist(),
            "standardization": "PREDICTIVE_SCORE_SD_WITH_UNIT_FALLBACK"}


def outcome_probabilities(distribution):
    home, away, mass = validate(distribution)
    return {"home": float(mass[home > away].sum()), "draw": float(mass[home == away].sum()),
            "away": float(mass[home < away].sum()),
            "identity": "JOINT_SCORE_DERIVATIVE_NOT_DIRECT_WINNER_HEAD"}


def simulate(distribution, *, draws=100000):
    if isinstance(draws, bool) or not isinstance(draws, int) or not 1 <= draws <= 1000000:
        raise ValueError("DRAW_COUNT_INVALID")
    home, away, mass = validate(distribution)
    seed = int(D.digest({"joint_distribution": distribution["distribution_sha256"], "n": draws})[:16], 16)
    rng = np.random.Generator(np.random.PCG64(seed))
    indices = rng.choice(len(mass), size=draws, p=mass)
    h = home[indices].astype("<i8"); a = away[indices].astype("<i8")
    payload = h.tobytes() + a.tobytes()
    return h, a, {"count": draws, "seed": seed, "rng": "numpy.PCG64",
                  "numpy_version": np.__version__, "simulation_code_sha256": code_hash(),
                  "encoding": "little_endian_int64_home_then_away",
                  "draw_sha256": hashlib.sha256(payload).hexdigest(),
                  "worst_case_mc_se_pp": 100 * math.sqrt(.25 / draws),
                  "mc_se_is_not_predictive_sd": True}


def _mid_pit(distribution, observed):
    support, mass = D.validate(distribution)
    below = float(mass[support < observed].sum())
    at = float(mass[support == observed].sum())
    return below + .5 * at


def _central_coverage(distribution, observed, level):
    support, mass = D.validate(distribution)
    cdf = np.cumsum(mass)
    alpha = (1-level)/2
    low = int(support[np.searchsorted(cdf, alpha, side="left")])
    high = int(support[np.searchsorted(cdf, 1-alpha, side="left")])
    return bool(low <= observed <= high), [low, high]


def account_result(distribution, *, actual_home, actual_away, result_source_sha256, result_available_at):
    """Append-only outcome residual diagnostic; never edits the parent forecast."""
    home, away, mass = validate(distribution)
    actual_home, actual_away = _observed_score(actual_home), _observed_score(actual_away)
    _check_final(actual_home, actual_away, distribution["league"], distribution["settlement"])
    D.source_hash(result_source_sha256)
    cutoff = distribution["provenance"]["cutoff"]
    if D.stamp(result_available_at) < D.stamp(cutoff):
        raise ValueError("RESULT_PRECEDES_FORECAST")
    start_time = distribution["provenance"].get("start_time_utc")
    if start_time is not None and not D.stamp(cutoff) < D.stamp(start_time) <= D.stamp(result_available_at):
        raise ValueError("RESULT_CHRONOLOGY_INVALID")
    actual_margin, actual_total = actual_home - actual_away, actual_home + actual_away
    margin, total = derive(distribution, "margin"), derive(distribution, "total")
    m = moments(distribution)
    margin_z = ((actual_margin-m["margin_mean"])/m["margin_sd"] if m["margin_sd"] > 0 else None)
    total_z = ((actual_total-m["total_mean"])/m["total_sd"] if m["total_sd"] > 0 else None)
    margin_pit, total_pit = _mid_pit(margin, actual_margin), _mid_pit(total, actual_total)
    coverage = {}
    for level in (.5, .8, .95):
        mc, mi = _central_coverage(margin, actual_margin, level)
        tc, ti = _central_coverage(total, actual_total, level)
        coverage[str(int(level*100))] = {"margin": mc, "margin_interval": mi,
                                         "total": tc, "total_interval": ti}
    out = {"schema": LUCK_SCHEMA, "event_id": distribution["provenance"].get("event_id"),
           "parent_joint_distribution_sha256": distribution["distribution_sha256"],
           "parent_forecast_sha256": distribution["provenance"].get("parent_forecast_sha256"),
           "forecast_cutoff": cutoff, "start_time_utc": start_time,
           "start_time_lineage_retained": start_time is not None,
           "result_source_sha256": result_source_sha256, "result_available_at": result_available_at,
           "actual_home": actual_home, "actual_away": actual_away,
           "predictive_moments": m,
           "actual_minus_predictive_mean": {"home": actual_home-m["home_mean"],
                                             "away": actual_away-m["away_mean"],
                                             "margin": actual_margin-m["margin_mean"],
                                             "total": actual_total-m["total_mean"]},
           "standardized_residual": {"margin": margin_z, "total": total_z},
           "mid_pit": {"margin": margin_pit, "total": total_pit},
           "two_sided_mid_pit_tail": {"margin": min(1., 2*min(margin_pit, 1-margin_pit)),
                                       "total": min(1., 2*min(total_pit, 1-total_pit))},
           "central_interval_coverage": coverage,
           "margin_score": D.score(margin, actual_margin), "total_score": D.score(total, actual_total),
           "joint_energy_score": energy_score(distribution, actual_home, actual_away),
           "mid_pit_not_randomized_calibration_pit": True,
           "operational_definition": "REALIZED_RESIDUAL_UNDER_FROZEN_PREGAME_DISTRIBUTION",
           "causal_luck_identified": False, "single_game_model_bias_estimated": False,
           "forecast_unchanged": True, "status": "DIAGNOSTIC_NOT_VALIDATION",
           "prospective_grade_eligible": False, "action_authority": False}
    out["artifact_sha256"] = D.digest(out)
    return out


def _mean_or_none(values):
    values = list(values)
    return float(np.mean(values)) if values else None


def evaluate(records, *, evaluated_at):
    """Aggregate frozen-outcome diagnostics; this does not supply walk-forward design."""
    if len(records) < 2:
        raise ValueError("AT_LEAST_2_EVALUATION_RECORDS_REQUIRED")
    D.stamp(evaluated_at)
    event_ids = [r["event_id"] for r in records]
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("DUPLICATE_EVALUATION_EVENT")
    for r in records:
        material = dict(r); h = material.pop("artifact_sha256", None)
        if r.get("schema") != LUCK_SCHEMA or D.digest(material) != h:
            raise ValueError("LUCK_ARTIFACT_HASH_MISMATCH")
        if r.get("action_authority") is not False or r.get("prospective_grade_eligible") is not False:
            raise ValueError("RESEARCH_ONLY")
        if D.stamp(r["result_available_at"]) >= D.stamp(evaluated_at):
            raise ValueError("EVALUATION_CHRONOLOGY_INVALID")
    out = {"schema": EVALUATION_SCHEMA, "evaluated_at": evaluated_at, "n": len(records),
           "event_ids": sorted(event_ids),
           "mean_actual_minus_predictive_mean": {
               key: float(np.mean([r["actual_minus_predictive_mean"][key] for r in records]))
               for key in ("home", "away", "margin", "total")},
           "mean_standardized_residual": {
               key: _mean_or_none(r["standardized_residual"][key] for r in records
                                  if r["standardized_residual"][key] is not None)
               for key in ("margin", "total")},
           "mean_crps": {key: float(np.mean([r[key+"_score"]["crps"] for r in records]))
                         for key in ("margin", "total")},
           "mean_joint_energy_score": float(np.mean([r["joint_energy_score"]["energy_score"] for r in records])),
           "zero_probability_outcomes": {key: sum(r[key+"_score"]["zero_probability_outcome"] for r in records)
                                         for key in ("margin", "total")},
           "central_interval_coverage": {
               level: {key: float(np.mean([r["central_interval_coverage"][level][key] for r in records]))
                       for key in ("margin", "total")} for level in ("50", "80", "95")},
           "records_sha256": D.digest(records),
           "status": "DIAGNOSTIC_NOT_WALK_FORWARD_VALIDATION",
           "required_next_evidence": "PRE_REGISTERED_PAIRED_CHRONOLOGICAL_BASELINE_CHALLENGER_EVALUATION",
           "prospective_grade_eligible": False, "action_authority": False}
    out["artifact_sha256"] = D.digest(out)
    return out
