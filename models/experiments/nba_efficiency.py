"""Independent NBA possession/efficiency experiments; no default replacement.

Every feature is accumulated from eligible earlier games.  Box-estimated full-game
possessions are an explicitly versioned measurement, not provider-counted pace.
The first increment has separate fitted probability and component heads.  The
joint increment is an explicitly continuous residual surrogate, not an NBA
overtime simulator or an exact discrete settlement model.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.special import ndtr
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

MODEL_IDS = {
    "efficiency": "nba.possession_efficiency.research.v2",
    "personnel": "nba.possession_efficiency.personnel.research.v2",
    "joint": "nba.possession_efficiency.joint.research.v2",
}
PARENT_MODEL_IDS = {stage: identity[:-1] + "1" for stage, identity in MODEL_IDS.items()}
BASELINE_REFIT_ID = "nba.initial_causal_score.exact_procedure_refit.control.v1"
MATCHED_BASELINE_REFIT_ID = "nba.initial_causal_score.matched_training_population.control.v1"
ALIGNED_BASELINE_REFIT_ID = "nba.initial_causal_score.cutoff_aligned_refit.control.v1"
ALIGNED_MATCHED_BASELINE_REFIT_ID = "nba.initial_causal_score.cutoff_aligned_matched_training_population.control.v1"
HISTORICAL_CUTOFF_POLICY = "START_MINUS_ONE_MICROSECOND"
POSSESSION_ID = "averaged_fga_minus_orb_plus_tov_plus_0.44_fta.full_game.v1"
DEFAULT_CONFIG = {
    "stage": "efficiency", "ewma_old_weight": 0.9, "min_team_games": 5,
    "ridge_alpha": 1.0, "logistic_c": 1.0, "fta_possession_weight": 0.44,
    "embargo": "PREVIOUS_UTC_DAY_EXCLUDED",
    "historical_cutoff_policy": HISTORICAL_CUTOFF_POLICY,
    "joint_calibration_season": 2024, "training_end_season": 2024,
}
RATE_NAMES = ("possessions", "off_efficiency", "def_efficiency", "off_efg",
              "def_efg", "off_tov", "def_tov", "off_orb", "def_orb",
              "off_ftr", "def_ftr")
FEATURE_NAMES = tuple(f"{s}_{f}" for s in ("home", "away") for f in RATE_NAMES) + (
    "home_rest", "away_rest", "home_games", "away_games", "neutral")
PERSONNEL_FEATURES = ("home_personnel_impact_per100", "away_personnel_impact_per100")
PACE_FEATURES = ("home_possessions", "away_possessions", "home_rest", "away_rest", "neutral")
EFF_FEATURES = ("own_efficiency", "opponent_def_efficiency", "own_efg", "opponent_def_efg",
                "own_tov", "opponent_def_tov", "own_orb", "opponent_def_orb",
                "own_ftr", "opponent_def_ftr", "own_rest", "opponent_rest", "home_court")
BOX_COLUMNS = {
    "fgm": "field_goals_made", "fga": "field_goals_attempted",
    "fg3m": "three_point_field_goals_made", "fg3a": "three_point_field_goals_attempted",
    "ftm": "free_throws_made", "fta": "free_throws_attempted",
    "orb": "offensive_rebounds", "drb": "defensive_rebounds", "tov": "total_turnovers",
}
FEATURE_CONFIG_KEYS = ("ewma_old_weight", "min_team_games", "fta_possession_weight", "embargo", "historical_cutoff_policy")


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _utc(value):
    result = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("NBA_TIMEZONE_REQUIRED")
    return result.astimezone(dt.timezone.utc)


def forecast_cutoff(event):
    """Resolve the actual pre-feature cutoff; never retime a finished vector."""
    start = _utc(event["start_time_utc"])
    supplied = event.get("forecast_cutoff_utc")
    cutoff = _utc(supplied) if supplied is not None else start - dt.timedelta(microseconds=1)
    if cutoff >= start:
        raise ValueError("NBA_FORECAST_CUTOFF_NOT_PRESTART")
    return cutoff


def history_boundary(cutoff):
    return _utc(cutoff).replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(days=1)


def _validate_example_cutoff(example):
    cutoff = forecast_cutoff(example["event"])
    if _utc(example["cutoff_utc"]) != cutoff:
        raise ValueError("NBA_FEATURE_CUTOFF_MISMATCH")
    if (example.get("history_max_event_time_utc")
            and _utc(example["history_max_event_time_utc"]) >= history_boundary(cutoff)):
        raise ValueError("NBA_FEATURE_HISTORY_EMBARGO_VIOLATION")
    if (example.get("history_max_available_at_utc")
            and _utc(example["history_max_available_at_utc"]) > cutoff):
        raise ValueError("NBA_FEATURE_HISTORY_AFTER_CUTOFF")
    return cutoff


def _config(config=None):
    if set(config or {}) - set(DEFAULT_CONFIG):
        raise ValueError("NBA_UNDECLARED_CONFIG_FIELDS")
    c = {**DEFAULT_CONFIG, **(config or {})}
    if (c["stage"] not in MODEL_IDS or c["embargo"] != "PREVIOUS_UTC_DAY_EXCLUDED"
            or c["historical_cutoff_policy"] != HISTORICAL_CUTOFF_POLICY):
        raise ValueError("NBA_EXPERIMENT_CONFIG")
    if not 0 <= c["ewma_old_weight"] < 1 or c["min_team_games"] < 1:
        raise ValueError("NBA_HISTORY_CONFIG")
    if c["ridge_alpha"] <= 0 or c["logistic_c"] <= 0 or c["fta_possession_weight"] != 0.44:
        raise ValueError("NBA_FIT_OR_POSSESSION_CONFIG")
    return c


def _number(value, name, integer=False):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("NBA_INVALID_NUMBER:" + name)
    x = float(value)
    if not math.isfinite(x) or x < 0 or (integer and x != int(x)):
        raise ValueError("NBA_INVALID_NUMBER:" + name)
    return int(x) if integer else x


def validate_game(game):
    """Reject ambiguous sides, inconsistent score/box rows, and missing sources."""
    if not game.get("event_id") or not game.get("home_id") or not game.get("away_id"):
        raise ValueError("NBA_EVENT_IDENTITY_REQUIRED")
    if game["home_id"] == game["away_id"]:
        raise ValueError("NBA_SELF_MATCH")
    _utc(game["start_time_utc"])
    if not game.get("sources"):
        raise ValueError("NBA_SOURCE_RECEIPTS_REQUIRED")
    if game.get("final", True) is False:
        return
    for side in ("home", "away"):
        score = _number(game[side + "_score"], side + "_score", True)
        b = game[side + "_stats"]
        values = {k: _number(b[k], side + "_" + k, True) for k in BOX_COLUMNS}
        if values["fgm"] > values["fga"] or values["fg3m"] > values["fg3a"] or values["ftm"] > values["fta"]:
            raise ValueError("NBA_SHOOTING_MAKES_EXCEED_ATTEMPTS")
        if values["fg3m"] > values["fgm"] or values["fg3a"] > values["fga"]:
            raise ValueError("NBA_THREE_POINT_SUBSET_CONFLICT")
        if 2 * values["fgm"] + values["fg3m"] + values["ftm"] != score:
            raise ValueError("NBA_BOX_SCORE_POINTS_CONFLICT")
        if values["fga"] <= 0:
            raise ValueError("NBA_ZERO_FIELD_GOAL_ATTEMPTS")
    if game["home_score"] == game["away_score"]:
        raise ValueError("NBA_TIED_FINAL")


def game_rates(game, config=None):
    c = _config(config)
    validate_game(game)
    if not game.get("final", True):
        raise ValueError("NBA_FINAL_REQUIRED_FOR_STATE")
    h, a = game["home_stats"], game["away_stats"]
    poss = sum(b["fga"] - b["orb"] + b["tov"] + c["fta_possession_weight"] * b["fta"] for b in (h, a)) / 2
    if poss <= 0:
        raise ValueError("NBA_INVALID_ESTIMATED_POSSESSIONS")
    out = {}
    for side, other in (("home", "away"), ("away", "home")):
        b, opp = game[side + "_stats"], game[other + "_stats"]
        if b["orb"] + opp["drb"] <= 0 or opp["orb"] + b["drb"] <= 0:
            raise ValueError("NBA_REBOUND_OPPORTUNITIES_INVALID")
        out[side] = {
            "possessions": poss,
            "off_efficiency": 100 * game[side + "_score"] / poss,
            "def_efficiency": 100 * game[other + "_score"] / poss,
            "off_efg": (b["fgm"] + .5 * b["fg3m"]) / b["fga"],
            "def_efg": (opp["fgm"] + .5 * opp["fg3m"]) / opp["fga"],
            "off_tov": b["tov"] / poss, "def_tov": opp["tov"] / poss,
            "off_orb": b["orb"] / (b["orb"] + opp["drb"]),
            "def_orb": opp["orb"] / (opp["orb"] + b["drb"]),
            "off_ftr": b["fta"] / b["fga"], "def_ftr": opp["fta"] / opp["fga"],
        }
    return out


def _sources(games):
    by_key = {}
    for game in games:
        for source in game.get("sources", []):
            key = (source["source"], source["sha256"])
            if key in by_key and by_key[key] != source:
                raise ValueError("NBA_SOURCE_RECEIPT_CONFLICT")
            by_key[key] = source
    return [by_key[k] for k in sorted(by_key)]


def prepare_examples(history, config=None):
    """Retain the full population; construct features before applying each target.

    Retrospective availability is not fabricated: the start-based embargo is a
    declared reconstruction convention. Authentic result availability, when
    supplied, adds a second eligibility requirement.
    """
    c = _config(config)
    history = sorted(history, key=lambda r: (_utc(r["start_time_utc"]), r["event_id"]))
    if len({r["event_id"] for r in history}) != len(history):
        raise ValueError("NBA_DUPLICATE_EVENT")
    state, pending, examples = {}, [], []
    previous_cutoff = None
    for original_event in history:
        event = copy.deepcopy(original_event)
        start = _utc(event["start_time_utc"])
        cutoff = forecast_cutoff(event)
        if event.get("forecast_cutoff_utc") is None:
            event["forecast_cutoff_utc"] = cutoff.isoformat()
        if previous_cutoff is not None and cutoff < previous_cutoff:
            raise ValueError("NBA_NONMONOTONE_FORECAST_CUTOFF")
        previous_cutoff = cutoff
        boundary = history_boundary(cutoff)
        remaining = []
        for old in pending:
            availability = old.get("result_available_at_utc")
            if _utc(old["start_time_utc"]) >= boundary or (availability and _utc(availability) > cutoff):
                remaining.append(old)
                continue
            rates = game_rates(old, c)
            for side in ("home", "away"):
                tid = old[side + "_id"]
                if tid not in state:
                    state[tid] = {"n": 0, "rates": rates[side], "games": []}
                s = state[tid]
                if s["n"]:
                    s["rates"] = {k: c["ewma_old_weight"] * s["rates"][k] + (1 - c["ewma_old_weight"]) * rates[side][k] for k in RATE_NAMES}
                s["n"] += 1
                s["last"] = old["start_time_utc"]
                s["games"].append(old)
        pending = remaining
        reasons = []
        for side in ("home", "away"):
            if state.get(event[side + "_id"], {}).get("n", 0) < c["min_team_games"]:
                reasons.append(side.upper() + "_INSUFFICIENT_PRIOR_GAMES")
        x, used = {}, []
        if not reasons:
            for side in ("home", "away"):
                s = state[event[side + "_id"]]
                x.update({f"{side}_{k}": s["rates"][k] for k in RATE_NAMES})
                x[side + "_rest"] = min(14., max(0., (start - _utc(s["last"])).total_seconds() / 86400))
                x[side + "_games"] = float(s["n"])
                used.extend(s["games"])
            x["neutral"] = float(event.get("neutral_site", False))
        targets = None
        if event.get("final", True):
            try:
                rates = game_rates(event, c)
                targets = {
                    "possessions": rates["home"]["possessions"],
                    "home_efficiency": rates["home"]["off_efficiency"],
                    "away_efficiency": rates["away"]["off_efficiency"],
                    "home_score": event["home_score"], "away_score": event["away_score"],
                    "home_margin": event["home_score"] - event["away_score"],
                    "total": event["home_score"] + event["away_score"],
                    "home_win": int(event["home_score"] > event["away_score"]),
                }
                pending.append(event)
            except (ValueError, KeyError, TypeError) as exc:
                reasons.append("NBA_INVALID_TARGET_SOURCE:" + str(exc))
        used = sorted({r["event_id"]: r for r in used}.values(), key=lambda r: (r["start_time_utc"], r["event_id"]))
        personnel = event.get("personnel")
        if c["stage"] == "personnel":
            if not personnel or not personnel.get("sources"):
                reasons.append("NBA_AUTHENTIC_PERSONNEL_INPUTS_REQUIRED")
            elif _utc(personnel["available_at_utc"]) > cutoff:
                reasons.append("NBA_PERSONNEL_INPUT_AFTER_CUTOFF")
            else:
                for side in ("home", "away"):
                    value = personnel.get(side + "_impact_per100")
                    if isinstance(value, bool) or value is None or not math.isfinite(float(value)):
                        reasons.append("NBA_PERSONNEL_IMPACT_FEATURES_REQUIRED")
                    else:
                        x[side + "_personnel_impact_per100"] = float(value)
        examples.append({
            "event": copy.deepcopy(event), "event_id": event["event_id"], "season": event["season"],
            "cutoff_utc": event["forecast_cutoff_utc"], "history_boundary_utc": boundary.isoformat(),
            "features": x if not reasons else None, "targets": targets,
            "eligible": not reasons, "exclusion_reasons": reasons,
            "history_event_ids": [r["event_id"] for r in used],
            "history_max_event_time_utc": max((r["start_time_utc"] for r in used), default=None),
            "history_max_available_at_utc": max((r["result_available_at_utc"] for r in used if r.get("result_available_at_utc")), default=None),
            "sources": _sources(used), "target_sources": event.get("sources", []),
            "historical_availability_proven": bool(used) and all(r.get("historical_availability_proven") is True for r in used),
            "feature_config": c, "possession_estimator_id": POSSESSION_ID,
            "personnel": copy.deepcopy(personnel),
        })
    return examples


def _matrix(examples, names):
    x = np.array([[r["features"][k] for k in names] for r in examples], dtype=float)
    if not np.isfinite(x).all():
        raise ValueError("NBA_FEATURES_NONFINITE")
    return x


def _eff_row(x, side, personnel=False):
    other = "away" if side == "home" else "home"
    row = [x[side + "_off_efficiency"], x[other + "_def_efficiency"]]
    for stat in ("efg", "tov", "orb", "ftr"):
        row.extend([x[side + "_off_" + stat], x[other + "_def_" + stat]])
    row += [x[side + "_rest"], x[other + "_rest"], float(side == "home") * (1 - x["neutral"])]
    if personnel:
        row.extend([x[side + "_personnel_impact_per100"], x[other + "_personnel_impact_per100"]])
    return row


def _pack(pipeline, kind):
    scaler, head = pipeline.steps[0][1], pipeline.steps[1][1]
    return {"kind": kind, "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(),
            "coefficient": np.asarray(head.coef_).reshape(-1).tolist(),
            "intercept": float(np.asarray(head.intercept_).reshape(-1)[0])}


def _predict_head(head, x):
    x = np.array(x, dtype=float)
    if len(x) != len(head["coefficient"]) or not np.isfinite(x).all():
        raise ValueError("NBA_FEATURE_VECTOR_INVALID")
    z = float(np.dot((x - head["mean"]) / head["scale"], head["coefficient"]) + head["intercept"])
    if head["kind"] == "logistic":
        return float(__import__("scipy").special.expit(z))
    return z


def _fit_core(examples, c):
    eligible = [r for r in examples if r["eligible"] and r["targets"] is not None]
    if len(eligible) < 20 or len({r["targets"]["home_win"] for r in eligible}) != 2:
        raise ValueError("NBA_TRAINING_POPULATION_INSUFFICIENT")
    for row in eligible:
        if any(row.get("feature_config", {}).get(k) != c[k] for k in FEATURE_CONFIG_KEYS):
            raise ValueError("NBA_FEATURE_CONFIG_MISMATCH")
        _validate_example_cutoff(row)
    personnel = c["stage"] == "personnel"
    names = FEATURE_NAMES + (PERSONNEL_FEATURES if personnel else ())
    if personnel:
        for r in eligible:
            p = r.get("personnel")
            if not p or not p.get("sources") or _utc(p["available_at_utc"]) > forecast_cutoff(r["event"]):
                raise ValueError("NBA_AUTHENTIC_PERSONNEL_INPUTS_REQUIRED")
            if any(k not in r["features"] for k in PERSONNEL_FEATURES):
                raise ValueError("NBA_PERSONNEL_IMPACT_FEATURES_REQUIRED")
    if any(set(row["features"]) != set(names) for row in eligible):
        raise ValueError("NBA_UNDECLARED_OR_MISSING_FEATURES")
    x = _matrix(eligible, names)
    pace = _matrix(eligible, PACE_FEATURES)
    eff_x = np.array([_eff_row(r["features"], s, personnel) for r in eligible for s in ("home", "away")])
    eff_y = np.array([r["targets"][s + "_efficiency"] for r in eligible for s in ("home", "away")])
    heads = {
        "possessions": _pack(make_pipeline(StandardScaler(), Ridge(alpha=c["ridge_alpha"])).fit(pace, [r["targets"]["possessions"] for r in eligible]), "linear"),
        "efficiency": _pack(make_pipeline(StandardScaler(), Ridge(alpha=c["ridge_alpha"])).fit(eff_x, eff_y), "linear"),
        "winner": _pack(make_pipeline(StandardScaler(), LogisticRegression(C=c["logistic_c"], max_iter=2000)).fit(x, [r["targets"]["home_win"] for r in eligible]), "logistic"),
    }
    return {"schema": "nba-possession-efficiency-fit-v2", "model_id": MODEL_IDS[c["stage"]],
            "parent_model_id": PARENT_MODEL_IDS[c["stage"]],
            "stage": c["stage"], "config": c, "feature_names": list(names), "heads": heads,
            "training_event_ids": [r["event_id"] for r in eligible], "training_n": len(eligible),
            "training_max_start_utc": max(r["event"]["start_time_utc"] for r in eligible),
            "training_max_available_at_utc": max((r["event"]["result_available_at_utc"] for r in eligible if r["event"].get("result_available_at_utc")), default=None),
            "training_input_sha256": _hash([{"event_id": r["event_id"], "cutoff_utc": r["cutoff_utc"], "features": r["features"], "targets": r["targets"], "sources": r["sources"], "target_sources": r["target_sources"]} for r in eligible]),
            "possession_estimator_id": POSSESSION_ID, "market_features_used": False,
            "action_authority": False}


def fit(training_examples, config=None):
    c = _config(config)
    if any(r["season"] > c["training_end_season"] for r in training_examples):
        raise ValueError("NBA_HELDOUT_SEASON_IN_TRAINING")
    state = _fit_core(training_examples, c)
    if c["stage"] == "joint":
        season = c["joint_calibration_season"]
        early = [r for r in training_examples if r["season"] < season]
        cal = [r for r in training_examples if r["season"] == season and r["eligible"] and r["targets"]]
        if len(cal) < 20:
            raise ValueError("NBA_JOINT_OOF_CALIBRATION_REQUIRED")
        inner = _fit_core(early, {**c, "stage": "efficiency"})
        inner["state_sha256"] = _hash(inner)
        residuals = []
        for row in cal:
            p = predict(inner, row)
            residuals.append([row["targets"]["home_score"] - p["home_score"], row["targets"]["away_score"] - p["away_score"]])
        covariance = np.cov(np.asarray(residuals), rowvar=False)
        if np.linalg.eigvalsh(covariance).min() <= 0:
            raise ValueError("NBA_JOINT_COVARIANCE_INVALID")
        state["joint"] = {"distribution_id": "nba.continuous_bivariate_final_score_residual.v1",
                          "parent_model_id": MODEL_IDS["efficiency"], "covariance": covariance.tolist(),
                          "residual_mean_diagnostic_only": np.mean(residuals, axis=0).tolist(),
                          "calibration_event_ids": [r["event_id"] for r in cal],
                          "calibration_n": len(cal), "calibration_residual_sha256": _hash(residuals),
                          "inner_fit_sha256": _hash(inner), "calibration_season": season,
                          "exact_discrete_settlement_supported": False}
    state["state_sha256"] = _hash(state)
    return state


def predict(state, example, *, simulations=0):
    if state.get("state_sha256") != _hash({k: v for k, v in state.items() if k != "state_sha256"}):
        raise ValueError("NBA_FITTED_STATE_HASH_MISMATCH")
    if example.get("eligible") is not True or not example.get("features"):
        raise ValueError("NBA_EXAMPLE_INELIGIBLE")
    c = state["config"]
    if any(example.get("feature_config", {}).get(k) != c.get(k) for k in FEATURE_CONFIG_KEYS):
        raise ValueError("NBA_FEATURE_CONFIG_MISMATCH")
    cutoff = _validate_example_cutoff(example)
    if example["event_id"] in state["training_event_ids"]:
        raise ValueError("NBA_TARGET_IN_TRAINING")
    if _utc(state["training_max_start_utc"]) >= cutoff:
        raise ValueError("NBA_TRAINING_AFTER_FORECAST_CUTOFF")
    if state.get("training_max_available_at_utc") and _utc(state["training_max_available_at_utc"]) > cutoff:
        raise ValueError("NBA_TRAINING_LABEL_UNAVAILABLE_AT_CUTOFF")
    x = example["features"]
    if set(x) != set(state["feature_names"]):
        raise ValueError("NBA_UNDECLARED_OR_MISSING_FEATURES")
    personnel = state["stage"] == "personnel"
    if personnel and (not example.get("personnel") or not example["personnel"].get("sources")):
        raise ValueError("NBA_AUTHENTIC_PERSONNEL_INPUTS_REQUIRED")
    if personnel and _utc(example["personnel"]["available_at_utc"]) > cutoff:
        raise ValueError("NBA_PERSONNEL_INPUT_AFTER_CUTOFF")
    poss = _predict_head(state["heads"]["possessions"], [x[k] for k in PACE_FEATURES])
    he = _predict_head(state["heads"]["efficiency"], _eff_row(x, "home", personnel))
    ae = _predict_head(state["heads"]["efficiency"], _eff_row(x, "away", personnel))
    if min(poss, he, ae) <= 0:
        raise ValueError("NBA_COMPONENT_OUT_OF_SUPPORT")
    hs, aws = poss * he / 100, poss * ae / 100
    p = _predict_head(state["heads"]["winner"], [x[k] for k in state["feature_names"]])
    result = {"model_id": state["model_id"], "stage": state["stage"], "event_id": example["event_id"],
              "p_home": p, "home_margin": hs - aws, "total": hs + aws, "home_score": hs, "away_score": aws,
              "components": {"expected_possessions": poss, "home_efficiency_per100": he, "away_efficiency_per100": ae,
                             "home_score": hs, "away_score": aws, "home_margin": hs - aws, "total": hs + aws},
              "probability_semantics": "SEPARATE_LOGISTIC_WINNER_HEAD", "market_features_used": False,
              "action_authority": False, "possession_estimator_id": POSSESSION_ID,
              "limitations": ["BOX_ESTIMATED_FULL_GAME_POSSESSIONS_NOT_OBSERVED_PACE", "NO_AUTHENTIC_PERSONNEL_FEATURES" if not personnel else "PERSONNEL_IMPACT_INPUT_MODEL_EXTERNAL"]}
    if state["stage"] == "joint":
        cov = np.array(state["joint"]["covariance"])
        margin_var = cov[0, 0] + cov[1, 1] - 2 * cov[0, 1]
        total_var = cov[0, 0] + cov[1, 1] + 2 * cov[0, 1]
        result.update(p_home=float(ndtr((hs - aws) / math.sqrt(margin_var))),
                      probability_semantics="CONTINUOUS_JOINT_SCORE_SURROGATE",
                      distribution=state["joint"]["distribution_id"],
                      margin_sd=math.sqrt(margin_var), total_sd=math.sqrt(total_var),
                      exact_discrete_settlement_supported=False)
        result["limitations"].append("CONTINUOUS_SCORE_SUPPORT_NO_DISCRETE_TIES_OR_OVERTIME_MODEL")
        if simulations:
            if isinstance(simulations, bool) or not 1 <= simulations <= 1000000:
                raise ValueError("NBA_SIMULATION_COUNT_INVALID")
            identity = {"model_id": state["model_id"], "state_sha256": state.get("state_sha256", _hash(state)), "event_id": example["event_id"], "features": x, "n": simulations}
            seed = int(_hash(identity)[:16], 16)
            draws = np.random.default_rng(seed).multivariate_normal([hs, aws], cov, int(simulations))
            result["simulation"] = {"n": simulations, "seed": seed, "rng": "numpy.PCG64", "distribution_id": result["distribution"],
                                    "p_home": float(np.mean(draws[:, 0] > draws[:, 1])),
                                    "draw_sha256": hashlib.sha256(draws.astype("<f8").tobytes()).hexdigest(),
                                    "encoding": "little-endian float64 Nx2 home,away", "negative_score_draws": int((draws < 0).any(axis=1).sum())}
            result["joint_draws"] = draws
    return result


def _cutoff_aligned_causal_rows(games, prior, cutoff_utc):
    """Reuse baseline feature/update math with the declared pre-feature cutoff.

    The legacy causal_rows groups by event-start date. That exact procedure is
    retained by prepare_baseline_control's default branch; this separately
    identified comparator changes only the admission boundary and preserves
    authoritative starts for rest features.
    """
    from models.current.baseline import feature, update
    state, pending, rows, used, trace = {}, [], [], [], {}
    previous_cutoff = None
    for event in games:
        cutoff = forecast_cutoff(event)
        if previous_cutoff is not None and cutoff < previous_cutoff:
            raise ValueError("NBA_NONMONOTONE_FORECAST_CUTOFF")
        previous_cutoff = cutoff
        boundary = history_boundary(cutoff)
        remaining = []
        for old in pending:
            available = old.get("result_available_at_utc")
            if _utc(old["start_time_utc"]) >= boundary or (available and _utc(available) > cutoff):
                remaining.append(old)
                continue
            update(state, old)
            used.append(old["event_id"])
        pending = remaining
        rows.append((event, list(feature(state, event, prior).values())))
        trace[event["event_id"]] = {
            "cutoff_utc": event.get("forecast_cutoff_utc") or cutoff.isoformat(),
            "history_boundary_utc": boundary.isoformat(),
            "team_history_counts": {side: state.get(event[side + "_id"], {}).get("n", 0) for side in ("home", "away")},
            "team_history_last_start_utc": {side: state.get(event[side + "_id"], {}).get("last") for side in ("home", "away")},
        }
        pending.append(event)
    cutoff, boundary = _utc(cutoff_utc), history_boundary(cutoff_utc)
    for old in pending:
        available = old.get("result_available_at_utc")
        if _utc(old["start_time_utc"]) < boundary and (not available or _utc(available) <= cutoff):
            update(state, old)
            used.append(old["event_id"])
    return rows, state, used, trace


def prepare_baseline_control(history, *, training_end_season=2024, cutoff_utc=None,
                             training_event_ids=None, align_forecast_cutoff=False):
    """Call the retained baseline procedure with a distinct optional fit population.

    The default remains the complete score-history refit. The optional ablation
    uses an explicit frozen label population while retaining the same causal
    feature procedure and every eligible earlier score observation. The explicit
    aligned branch changes the historical admission cutoff, not the baseline's
    feature formulas or fitting recipe, and receives a different identity.
    """
    from scripts.prepare_initial_baselines import causal_rows, fit as baseline_fit
    rows = [dict(r) for r in history if r.get("final", True) and "home_score" in r and "away_score" in r]
    rows.sort(key=lambda r: (r["start_time_utc"], r["event_id"]))
    train = [r for r in rows if r["season"] <= training_end_season]
    matched = training_event_ids is not None
    if matched:
        if (not isinstance(training_event_ids, (list, tuple, set)) or not training_event_ids
                or any(not isinstance(eid, str) or not eid for eid in training_event_ids)
                or len(set(training_event_ids)) != len(training_event_ids)):
            raise ValueError("NBA_MATCHED_TRAINING_IDS_INVALID")
        requested = set(training_event_ids)
        if requested - {r["event_id"] for r in rows}:
            raise ValueError("NBA_MATCHED_TRAINING_EVENT_ABSENT")
        if requested - {r["event_id"] for r in train}:
            raise ValueError("NBA_MATCHED_TRAINING_EVENT_AFTER_CUTOFF")
        train = [r for r in train if r["event_id"] in requested]
    if not train:
        raise ValueError("NBA_BASELINE_TRAINING_POPULATION_EMPTY")
    prior = float(np.mean([r[s + "_score"] for r in train for s in ("home", "away")]))
    cutoff = cutoff_utc or (forecast_cutoff(rows[-1]).isoformat() if align_forecast_cutoff
                            else max(r["start_time_utc"] for r in rows))
    if align_forecast_cutoff:
        causal, state, used, cutoff_trace = _cutoff_aligned_causal_rows(rows, prior, cutoff)
    else:
        causal, state, used = causal_rows(rows, prior, cutoff)
    fit_ids = {r["event_id"] for r in train}
    fitted = baseline_fit([r for r in causal if r[0]["event_id"] in fit_ids], "nba")
    model_id = (ALIGNED_MATCHED_BASELINE_REFIT_ID if matched else ALIGNED_BASELINE_REFIT_ID) if align_forecast_cutoff else (MATCHED_BASELINE_REFIT_ID if matched else BASELINE_REFIT_ID)
    result = {"model_id": model_id,
            "parent_model_id": "nba.initial_causal_score.research.v1",
            "fitted": fitted, "prior": prior, "rows": {r["event_id"]: x for r, x in causal}, "team_state": state,
            "consumed_game_ids": used, "training_event_ids": [r["event_id"] for r in train],
            "training_max_start_utc": max(r["start_time_utc"] for r in train),
            "fit_sha256": _hash(fitted), "not_original_frozen_fit": True}
    if align_forecast_cutoff:
        result.update(historical_cutoff_policy=HISTORICAL_CUTOFF_POLICY,
                      embargo="PREVIOUS_UTC_DAY_EXCLUDED", cutoff_trace=cutoff_trace,
                      team_state_cutoff_utc=cutoff,
                      legacy_procedure_changed_only_in_history_admission=True,
                      legacy_control_parent_id=MATCHED_BASELINE_REFIT_ID if matched else BASELINE_REFIT_ID)
    return result


def predict_baseline(control, event):
    from models.current.linear import predict as baseline_predict
    from models.current.baseline import feature
    aligned = control.get("historical_cutoff_policy") == HISTORICAL_CUTOFF_POLICY
    cutoff = forecast_cutoff(event) if aligned else _utc(event.get("forecast_cutoff_utc", event["start_time_utc"]))
    if event["event_id"] in control["training_event_ids"] or _utc(control["training_max_start_utc"]) >= cutoff:
        raise ValueError("NBA_BASELINE_TRAINING_AFTER_CUTOFF_OR_TARGET_INCLUDED")
    x = control["rows"].get(event["event_id"])
    if aligned and x is not None and _utc(control["cutoff_trace"][event["event_id"]]["cutoff_utc"]) != cutoff:
        raise ValueError("NBA_BASELINE_FEATURE_CUTOFF_MISMATCH")
    if x is None:
        x = list(feature(control["team_state"], event, control["prior"]).values())
    f = control["fitted"]
    margin, total = baseline_predict(f["margin"], x), baseline_predict(f["total"], x)
    return {"model_id": control["model_id"], "event_id": event["event_id"],
            "p_home": baseline_predict(f["winner"], x), "home_margin": margin, "total": total,
            "home_score": (total + margin) / 2, "away_score": (total - margin) / 2,
            "score_semantics": "DERIVED_FROM_SEPARATE_MARGIN_TOTAL_HEADS", "components": {}, "action_authority": False}


def allstar_schedule_event(row):
    """Provider season_type=2 also contains explicitly marked All-Star events."""
    if str(row.get("type_abbreviation", "")).upper() == "ALLSTAR":
        return True
    try:
        return float(row.get("type_id")) == 4.0
    except (TypeError, ValueError):
        return False


def normalize_sportsdataverse(source_root):
    """Load source-bound schedules/team boxes; preserve conflicts as exclusions.

    The score-only history includes reconciled schedule events even when boxes
    are absent. It is the population for the unchanged baseline procedure.
    Player reconciliation is reported separately and never silently repairs a
    contradictory player row; player data are not used by this first increment.
    """
    import pandas as pd
    root = Path(source_root)
    report = json.loads((root / "report.json").read_text())
    recs = {("nba_schedule" if r["dataset"] == "schedule" else r["dataset"], int(r["season"])): r for r in report["sources"] if r["league"] == "nba" and r["status"] == "CAPTURED"}
    if not any(k[0] == "nba_schedule" for k in recs):
        raise ValueError("NBA_SOURCE_SCHEDULE_COVERAGE_EMPTY")
    tables, receipts = {}, {}
    for key, r in recs.items():
        path = root / r["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != r["sha256"]:
            raise ValueError("NBA_RAW_SOURCE_HASH_MISMATCH:" + r["path"])
        tables[key] = pd.read_parquet(path)
        receipts[key] = {"source": r["url"], "sha256": r["sha256"], "retrieved_at_utc": r["retrieved_at_utc"], "observed_at_utc": r.get("provider_observed_at_utc")}
    history, score_history, future, excluded, player_issues = [], [], [], [], []
    seen = set()
    for (kind, season), schedule in sorted(tables.items()):
        if kind != "nba_schedule":
            continue
        boxes = tables.get(("team_box", season))
        players = tables.get(("player_box", season))
        box_groups = {} if boxes is None else {int(k): v for k, v in boxes.groupby("game_id")}
        player_groups = {} if players is None else {int(k): v for k, v in players.groupby("game_id")}
        for row in schedule.to_dict("records"):
            eid = "NBA:" + str(int(row["id"]))
            if allstar_schedule_event(row):
                excluded.append({"event_id": eid, "reason": "OUTSIDE_REGULAR_SEASON_ALLSTAR_EVENT", "season": season})
                continue
            if int(row["season_type"]) != 2 or str(row.get("type_id")) == "39":
                excluded.append({"event_id": eid, "reason": "OUTSIDE_REGULAR_SEASON_OR_CUP_FINAL", "season": season})
                continue
            if eid in seen:
                raise ValueError("NBA_DUPLICATE_SCHEDULE_EVENT:" + eid)
            seen.add(eid)
            event = {"event_id": eid, "start_time_utc": _utc(row["date"]).isoformat(), "season": season,
                     "home_id": str(int(row["home_id"])), "away_id": str(int(row["away_id"])),
                     "home_team": row["home_display_name"], "away_team": row["away_display_name"],
                     "neutral_site": bool(row["neutral_site"]), "final": bool(row["status_type_completed"]),
                     "sources": [receipts[("nba_schedule", season)]], "historical_availability_proven": False}
            if not event["final"]:
                future.append(event)
                continue
            event.update(home_score=_number(row["home_score"], "home_score", True), away_score=_number(row["away_score"], "away_score", True))
            if event["home_id"] == event["away_id"] or event["home_score"] == event["away_score"]:
                excluded.append({"event_id": eid, "reason": "SCHEDULE_IDENTITY_OR_FINAL_SCORE_INVALID", "season": season})
                continue
            score_history.append(copy.deepcopy(event))
            try:
                group = box_groups.get(int(row["id"]))
                if group is None or len(group) != 2 or set(group["team_home_away"]) != {"home", "away"}:
                    raise ValueError("NBA_TWO_EXACT_BOX_SIDES_REQUIRED")
                event["sources"].append(receipts[("team_box", season)])
                for b in group.to_dict("records"):
                    side = b["team_home_away"]
                    other = "away" if side == "home" else "home"
                    if str(int(b["team_id"])) != event[side + "_id"] or str(int(b["opponent_team_id"])) != event[other + "_id"]:
                        raise ValueError("NBA_SCHEDULE_BOX_TEAM_ID_CONFLICT")
                    if int(b["team_score"]) != event[side + "_score"] or int(b["opponent_team_score"]) != event[other + "_score"]:
                        raise ValueError("NBA_SCHEDULE_BOX_SCORE_CONFLICT")
                    event[side + "_stats"] = {k: _number(b[col], side + "_" + k, True) for k, col in BOX_COLUMNS.items()}
                    if int(b["season"]) != season or int(b["season_type"]) != 2:
                        raise ValueError("NBA_BOX_SEASON_CONFLICT")
                    if int(b["total_turnovers"]) != int(b["turnovers"]) + int(b["team_turnovers"]):
                        raise ValueError("NBA_TEAM_TURNOVER_CONVENTION_CONFLICT")
                validate_game(event)
                game_rates(event)
                history.append(event)
            except (ValueError, KeyError, TypeError) as exc:
                excluded.append({"event_id": eid, "reason": str(exc), "season": season})
                continue
            pg = player_groups.get(int(row["id"]))
            if pg is None:
                player_issues.append({"event_id": eid, "reason": "PLAYER_BOX_ABSENT"})
                continue
            for side in ("home", "away"):
                team = pg[pg["team_id"].astype(str) == event[side + "_id"]]
                if team.empty or team["athlete_id"].duplicated().any():
                    player_issues.append({"event_id": eid, "team_id": event[side + "_id"], "reason": "PLAYER_IDENTITY_OR_COVERAGE_CONFLICT"})
                    continue
                active = team[~team["did_not_play"].astype(bool)]
                player_points = float(active["points"].fillna(0).sum())
                dnp_nonzero = team[team["did_not_play"].astype(bool) & (team["points"].fillna(0) != 0)]
                if player_points != event[side + "_score"] or len(dnp_nonzero):
                    player_issues.append({"event_id": eid, "team_id": event[side + "_id"], "reason": "PLAYER_POINTS_OR_DNP_CONFLICT", "player_points": player_points, "team_points": event[side + "_score"]})
    order = lambda r: (r["start_time_utc"], r["event_id"])
    return {"history": sorted(history, key=order), "score_history": sorted(score_history, key=order),
            "future_events": sorted(future, key=order), "excluded": excluded, "player_reconciliation_issues": player_issues,
            "sources": [receipts[k] for k in sorted(receipts)], "historical_availability_proven": False,
            "evidence_scope": "RETROSPECTIVE_RECONSTRUCTION", "action_authority": False}
