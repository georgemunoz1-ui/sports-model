"""Discrete, market-blind distribution challengers; no default or authority changes.

All state is explicit. Input chronology is checked, not independently attested:
these objects are research artifacts, never canonical prospective registrations.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np

SCHEMA = "sports.discrete_distribution.research.v1"
FIT_SCHEMA = "sports.residual_distribution.research.v1"
SETTLEMENTS = {
    "nfl": {"FULL_GAME_OT_REGULAR": True, "FULL_GAME_OT_POSTSEASON": False},
    "cfb": {"FULL_GAME_OT": False},
    "nba": {"FULL_GAME_OT": False},
    "wnba": {"FULL_GAME_OT": False},
    "mlb": {"COMPLETED_GAME_EXTRA_INNINGS": False},
    "nhl": {"FULL_GAME_OT_SO_PLUS_ONE": False, "REGULATION": True},
    "mls": {"REGULATION_90_STOPPAGE": True},
}
STATES = ("win", "half_win", "push", "half_loss", "loss")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def stamp(value):
    if not isinstance(value, str):
        raise ValueError("TIMESTAMP_REQUIRED")
    value = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return value.astimezone(dt.timezone.utc)


def writer_clock():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def code_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def finite(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)):
        raise ValueError("FINITE_NUMBER_REQUIRED")
    if not math.isfinite(float(value)):
        raise ValueError("FINITE_NUMBER_REQUIRED")
    return float(value)


def identity(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + "_REQUIRED")
    return value


def source_hash(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("SHA256_REQUIRED")
    return value


def scope(league, product, settlement):
    if league not in SETTLEMENTS or settlement not in SETTLEMENTS[league]:
        raise ValueError("UNSUPPORTED_SETTLEMENT")
    if product not in {"margin", "total"}:
        raise ValueError("UNSUPPORTED_PRODUCT")


def vector(values):
    values = list(values)
    for value in values:
        finite(value)
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1 or not len(arr):
        raise ValueError("NONEMPTY_VECTOR_REQUIRED")
    return arr


def make_distribution(values, weights, *, league, product, settlement, model_id, provenance):
    scope(league, product, settlement)
    identity(model_id, "MODEL_ID")
    values, weights = vector(values), vector(weights)
    if values.shape != weights.shape or np.any(weights < 0) or weights.sum() <= 0:
        raise ValueError("WEIGHTS_INVALID")
    if not np.equal(values, np.rint(values)).all():
        raise ValueError("INTEGER_SUPPORT_REQUIRED")
    if product == "total" and np.any(values < 0):
        raise ValueError("NEGATIVE_TOTAL")
    if product == "total" and not SETTLEMENTS[league][settlement] and np.any((values == 0) & (weights > 0)):
        raise ValueError("ZERO_TOTAL_WITH_NO_TIE_SETTLEMENT")
    if product == "margin" and not SETTLEMENTS[league][settlement] and np.any((values == 0) & (weights > 0)):
        raise ValueError("FINAL_TIE_UNSUPPORTED")
    support, inverse = np.unique(values.astype(np.int64), return_inverse=True)
    masses = np.bincount(inverse, weights=weights, minlength=len(support))
    keep = masses > 0
    support, masses = support[keep], masses[keep]
    masses = masses / masses.sum()
    out = {"schema": SCHEMA, "league": league, "product": product,
           "settlement": settlement, "model_id": model_id,
           "support": support.tolist(), "masses": masses.tolist(),
           "provenance": provenance, "status": "DIAGNOSTIC",
           "prospective_grade_eligible": False, "action_authority": False}
    out["distribution_sha256"] = digest(out)
    return out


def validate(distribution):
    d = dict(distribution)
    h = d.pop("distribution_sha256", None)
    if d.get("schema") != SCHEMA or digest(d) != h:
        raise ValueError("DISTRIBUTION_HASH_MISMATCH")
    if d.get("action_authority") is not False or d.get("prospective_grade_eligible") is not False:
        raise ValueError("RESEARCH_ONLY")
    rebuilt = make_distribution(d["support"], d["masses"], league=d["league"],
                                product=d["product"], settlement=d["settlement"],
                                model_id=d["model_id"], provenance=d["provenance"])
    if not math.isclose(sum(d["masses"]), 1.0, abs_tol=1e-10):
        raise ValueError("PROBABILITY_MASS_INVALID")
    if d["support"] != rebuilt["support"] or len(d["masses"]) != len(rebuilt["masses"]):
        raise ValueError("CANONICAL_SUPPORT_REQUIRED")
    return np.asarray(d["support"]), np.asarray(d["masses"])


def _line_parts(line, league):
    line = finite(line)
    if line * 4 != round(line * 4):
        raise ValueError("QUARTER_POINT_INCREMENT_REQUIRED")
    if line * 2 == round(line * 2):
        return [line]
    if league != "mls":
        raise ValueError("QUARTER_LINES_ONLY_MLS")
    return [math.floor(line * 2) / 2, math.ceil(line * 2) / 2]


def outcome(value, *, league, product, settlement, line, side):
    scope(league, product, settlement)
    value = finite(value)
    if value != round(value) or (product == "total" and value < 0):
        raise ValueError("INTEGER_OUTCOME_REQUIRED")
    if product == "margin" and value == 0 and not SETTLEMENTS[league][settlement]:
        raise ValueError("FINAL_TIE_UNSUPPORTED")
    if product == "total" and value == 0 and not SETTLEMENTS[league][settlement]:
        raise ValueError("ZERO_TOTAL_WITH_NO_TIE_SETTLEMENT")
    if side not in ({"HOME", "AWAY"} if product == "margin" else {"OVER", "UNDER"}):
        raise ValueError("CONTRACT_SIDE_INVALID")
    legs = _line_parts(line, league)
    if product == "total" and min(legs) < 0:
        raise ValueError("NEGATIVE_TOTAL_LINE")
    signs = [np.sign(value + x if product == "margin" else value - x) for x in legs]
    signed = float(np.mean(signs)) * (-1 if side in {"AWAY", "UNDER"} else 1)
    return {1.: "win", .5: "half_win", 0.: "push", -.5: "half_loss", -1.: "loss"}[signed]


def price(distribution, line, side):
    support, weights = validate(distribution)
    result = dict.fromkeys(STATES, 0.)
    for value, weight in zip(support, weights):
        result[outcome(int(value), league=distribution["league"], product=distribution["product"],
                       settlement=distribution["settlement"], line=line, side=side)] += float(weight)
    return result


def score(distribution, observed):
    """Discrete CRPS and full-distribution log loss (zero support stays visible)."""
    x, p = validate(distribution)
    observed = finite(observed)
    if observed != round(observed):
        raise ValueError("INTEGER_OUTCOME_REQUIRED")
    outcome(observed, league=distribution["league"], product=distribution["product"],
            settlement=distribution["settlement"], line=0.,
            side="HOME" if distribution["product"] == "margin" else "OVER")
    # E|X-y| - .5 E|X-X'|, using cumulative sums rather than a quadratic matrix.
    previous_p = np.cumsum(p) - p
    previous_xp = np.cumsum(x * p) - x * p
    crps = np.sum(p * np.abs(x - observed)) - np.sum(p * (x * previous_p - previous_xp))
    mass = float(p[x == observed].sum())
    return {"crps": float(crps), "log_loss": -math.log(mass) if mass else None,
            "zero_probability_outcome": mass == 0}


def simulate(distribution, *, draws=100000):
    if isinstance(draws, bool) or not isinstance(draws, int) or not 1 <= draws <= 1000000:
        raise ValueError("DRAW_COUNT_INVALID")
    x, p = validate(distribution)
    seed = int(digest({"distribution": distribution["distribution_sha256"], "n": draws})[:16], 16)
    rng = np.random.Generator(np.random.PCG64(seed))
    values = rng.choice(x, size=draws, p=p).astype("<i8")
    return values, {"count": draws, "seed": seed, "rng": "numpy.PCG64",
                    "numpy_version": np.__version__, "simulation_code_sha256": code_hash(),
                    "encoding": "little_endian_int64", "draw_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
                    "worst_case_mc_se_pp": 100 * math.sqrt(.25 / draws)}


def mix(scenarios, *, cutoff, model_id):
    """Mixture of joint availability states, never an average of mean margins."""
    if not scenarios:
        raise ValueError("SCENARIOS_REQUIRED")
    values, weights, bindings = [], [], []
    signature = None
    total = 0.
    ids = set()
    for s in scenarios:
        sid = identity(s["scenario_id"], "SCENARIO_ID")
        if sid in ids:
            raise ValueError("DUPLICATE_SCENARIO")
        ids.add(sid)
        source_hash(s["source_sha256"])
        if not stamp(s["observed_at_utc"]) <= stamp(s["retrieved_at_utc"]) <= stamp(cutoff):
            raise ValueError("FUTURE_SCENARIO")
        w = finite(s["weight"])
        if not 0 <= w <= 1:
            raise ValueError("SCENARIO_WEIGHT_INVALID")
        d = s["distribution"]
        x, p = validate(d)
        key = tuple(d[k] for k in ("league", "product", "settlement"))
        if signature is not None and key != signature:
            raise ValueError("SCENARIO_SCOPE_MISMATCH")
        # Inference wrapper must bind all scenarios to the same event and cutoff.
        event_key = (d["provenance"].get("event_id"), d["provenance"].get("cutoff"))
        if not event_key[0] or event_key[1] != cutoff:
            raise ValueError("SCENARIO_EVENT_BINDING_REQUIRED")
        if bindings and event_key[0] != bindings[0]["event_id"]:
            raise ValueError("SCENARIO_EVENT_MISMATCH")
        signature = key
        values.extend(x.tolist()); weights.extend((w * p).tolist()); total += w
        bindings.append({"scenario_id": sid, "weight": w, "event_id": event_key[0],
                         "source_sha256": s["source_sha256"], "observed_at_utc": s["observed_at_utc"],
                         "retrieved_at_utc": s["retrieved_at_utc"],
                         "distribution_sha256": d["distribution_sha256"]})
    if not math.isclose(total, 1., abs_tol=1e-10):
        raise ValueError("SCENARIO_WEIGHTS_MUST_SUM_TO_ONE")
    return make_distribution(values, weights, league=signature[0], product=signature[1],
                             settlement=signature[2], model_id=model_id,
                             provenance={"event_id": bindings[0]["event_id"], "cutoff": cutoff,
                                         "scenario_consumption": bindings})


def fit_residuals(rows, *, league, product, settlement, parent_model_id, fitted_at,
                  information_set, method="empirical", scale_features=(), ridge=10., market_input=False):
    """Fit residual uncertainty to explicit earlier out-of-time point forecasts.

    Required row provenance is checked for consistency, not granted historical
    attestation. Observed-score inputs are never consumed by prediction functions.
    """
    scope(league, product, settlement)
    if method not in {"empirical", "conditional_scale"}:
        raise ValueError("METHOD_INVALID")
    identity(parent_model_id, "PARENT_MODEL_ID")
    identity(information_set, "INFORMATION_SET")
    if len(rows) < 30:
        raise ValueError("AT_LEAST_30_TRAINING_ROWS_REQUIRED_NOT_VALIDATION")
    if method == "empirical" and scale_features:
        raise ValueError("UNUSED_SCALE_FEATURES")
    if method == "conditional_scale" and not scale_features:
        raise ValueError("SCALE_FEATURES_REQUIRED")
    if not isinstance(market_input, bool):
        raise ValueError("MARKET_INPUT_ROLE_REQUIRED")
    if not market_input and any(re.search(r"(^|_)(odds|spread|price|market|closing|moneyline|line)($|_)", k, re.I) for k in scale_features):
        raise ValueError("MARKET_FEATURE_IN_MARKET_BLIND_ARM")
    if len(set(scale_features)) != len(scale_features) or any(not isinstance(k, str) or not k for k in scale_features):
        raise ValueError("SCALE_FEATURE_NAMES_INVALID")
    if finite(ridge) <= 0:
        raise ValueError("POSITIVE_RIDGE_REQUIRED")
    residuals, features, ids, bounds = [], [], set(), []
    for r in rows:
        eid = identity(r["event_id"], "EVENT_ID")
        if eid in ids:
            raise ValueError("DUPLICATE_TRAINING_EVENT")
        ids.add(eid)
        if any(r[k] != v for k, v in {"league": league, "product": product,
                                      "settlement": settlement, "parent_model_id": parent_model_id,
                                      "information_set": information_set}.items()):
            raise ValueError("TRAINING_SCOPE_MISMATCH")
        if r.get("market_input") is not market_input:
            raise ValueError("TRAINING_MARKET_ROLE_MISMATCH")
        for k in ("forecast_sha256", "result_source_sha256"):
            source_hash(r[k])
        if r.get("prediction_kind") != "CHRONOLOGICAL_OUT_OF_TIME":
            raise ValueError("OUT_OF_TIME_FORECASTS_REQUIRED")
        if not stamp(r["parent_fit_cutoff"]) <= stamp(r["forecast_cutoff"]) < stamp(r["start_time_utc"]) <= stamp(r["result_available_at"]) < stamp(fitted_at):
            raise ValueError("TRAINING_CHRONOLOGY_INVALID")
        observed = finite(r["observed"])
        outcome(observed, league=league, product=product, settlement=settlement,
                line=0., side="HOME" if product == "margin" else "OVER")
        residuals.append(observed - finite(r["predicted_mean"]))
        features.append([finite(r["scale_features"][k]) for k in scale_features])
        bounds.append(r["result_available_at"])
    errors = np.asarray(residuals)
    scaling = None
    if method == "conditional_scale":
        x = np.asarray(features); mean = x.mean(0); sd = x.std(0); sd[sd == 0] = 1
        design = np.column_stack([np.ones(len(x)), (x - mean) / sd])
        penalty = np.eye(design.shape[1]) * ridge; penalty[0, 0] = 0
        beta = np.linalg.solve(design.T @ design + penalty, design.T @ np.log1p(errors ** 2))
        scales = np.exp(np.clip(design @ beta, -8, 16) / 2)
        errors = errors / scales
        scaling = {"features": list(scale_features), "mean": mean.tolist(), "sd": sd.tolist(),
                   "beta": beta.tolist(), "ridge": ridge}
    model = {"schema": FIT_SCHEMA, "league": league, "product": product, "settlement": settlement,
             "parent_model_id": parent_model_id, "information_set": information_set,
             "method": method, "fit_as_of_utc": fitted_at, "created_at_utc": writer_clock(), "training_n": len(rows),
             "code_sha256": code_hash(), "numpy_version": np.__version__,
             "market_input": market_input,
             "last_result_available_at": max(bounds, key=stamp), "training_event_ids": sorted(ids),
             "training_sha256": digest(rows), "residuals": errors.tolist(), "scaling": scaling,
             "status": "FITTED_RESEARCH_NOT_VALIDATED", "action_authority": False,
             "prospective_grade_eligible": False}
    model["model_id"] = f"{league}.{product}.{method}.research." + digest(model)[:16]
    model["artifact_sha256"] = digest(model)
    return model


def predict(model, *, mean, event_id, cutoff, parent_model_id, information_set,
            parent_forecast_sha256, scale_features=None):
    material = dict(model); h = material.pop("artifact_sha256", None)
    if material.get("schema") != FIT_SCHEMA or digest(material) != h:
        raise ValueError("FITTED_ARTIFACT_HASH_MISMATCH")
    if model.get("code_sha256") != code_hash():
        raise ValueError("FITTED_CODE_DRIFT")
    if model.get("action_authority") is not False or model.get("prospective_grade_eligible") is not False:
        raise ValueError("RESEARCH_ONLY")
    identity(event_id, "EVENT_ID"); source_hash(parent_forecast_sha256)
    if event_id in model["training_event_ids"]:
        raise ValueError("TRAINING_EVENT_REUSED")
    if parent_model_id != model["parent_model_id"] or information_set != model["information_set"]:
        raise ValueError("PARENT_SCOPE_MISMATCH")
    if stamp(model["fit_as_of_utc"]) > stamp(cutoff):
        raise ValueError("FUTURE_FITTED_ARTIFACT")
    mean = finite(mean)
    if model["product"] == "total" and mean < 0:
        raise ValueError("NEGATIVE_TOTAL_MEAN")
    scale = 1.
    s = model["scaling"]
    used = {}
    if s:
        used = {k: finite((scale_features or {})[k]) for k in s["features"]}
        x = (np.asarray(list(used.values())) - s["mean"]) / s["sd"]
        scale = float(np.exp(np.clip(np.r_[1., x] @ s["beta"], -8, 16) / 2))
    values = mean + np.asarray(model["residuals"]) * scale
    # Split fractional centers between adjacent integers instead of banker's rounding.
    lo = np.floor(values); frac = values - lo
    grid = np.r_[lo, lo + 1]; mass = np.r_[1 - frac, frac]
    allowed = grid >= 0 if model["product"] == "total" else np.ones(len(grid), bool)
    if not SETTLEMENTS[model["league"]][model["settlement"]]:
        allowed &= grid != 0
    removed = float(mass[~allowed].sum() / mass.sum())
    if not np.any(mass[allowed] > 0):
        raise ValueError("NO_LEGAL_SCORE_SUPPORT")
    return make_distribution(grid[allowed].tolist(), mass[allowed].tolist(), league=model["league"],
                             product=model["product"], settlement=model["settlement"], model_id=model["model_id"],
                             provenance={"event_id": event_id, "cutoff": cutoff,
                                         "parent_model_id": parent_model_id,
                                         "parent_forecast_sha256": parent_forecast_sha256,
                                         "fitted_artifact_sha256": h, "information_set": information_set,
                                         "artifact_existed_at_forecast_cutoff": stamp(model["created_at_utc"]) <= stamp(cutoff),
                                         "mean_input": mean, "scale_features_used": used,
                                         "conditional_scale": scale,
                                         "market_input": model["market_input"],
                                         "removed_illegal_support_mass": removed,
                                         "support_policy": "CONDITION_ON_LEGAL_SUPPORT",
                                         "joint_score_distribution": False})
