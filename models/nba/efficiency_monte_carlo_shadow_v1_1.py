"""NBA possession/efficiency Monte Carlo diagnostic engine.

Market-free. This engine is intentionally fail-closed: every numerical model parameter
must come from an explicitly fitted model state. There are no plausible/default parameter
fallbacks. Availability adjustments must also be present explicitly in the frozen PIT
snapshot, even when their fitted/scenario-weighted value is zero.
"""
from __future__ import annotations

import hashlib
import json
import math

import numpy as np

ENGINE_ID = "nba.efficiency_monte_carlo.v1_1.defense_direction_fix.shadow"
ENGINE_VERSION = "1.1.0"
MIN_SIMS = 50000

REQUIRED_SNAPSHOT = (
    "event_id",
    "home_team",
    "away_team",
    "home_adj_ortg",
    "home_adj_drtg",
    "away_adj_ortg",
    "away_adj_drtg",
    "home_pace",
    "away_pace",
    "home_availability_epm_per100",
    "away_availability_epm_per100",
)
REQUIRED_PARAMETERS = (
    "league_ortg",
    "home_court_points_per100",
    "pace_sd",
    "shared_eff_sd",
    "team_eff_sd",
    "margin_logistic_scale",
)


def _canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return "sha256:" + hashlib.sha256(_canon(value).encode()).hexdigest()


def _seed(event_id, input_hash, state_hash, n_sims):
    payload = f"{event_id}|{input_hash}|{state_hash}|{ENGINE_VERSION}|{int(n_sims)}"
    return int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big", signed=False)


def _logistic(value):
    return 1.0 / (1.0 + math.exp(-value))


def _finite_number(value, field):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"NBA_PARAMETER_NOT_FITTED:{field}") from exc
    if not math.isfinite(number):
        raise ValueError(f"NBA_PARAMETER_NOT_FITTED:{field}")
    return number


def _require_state(config):
    if bool(config.get("fit_required", True)):
        raise ValueError("NBA_MODEL_STATE_PARAMETER_ESTIMATION_REQUIRED")
    parameters = config.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError("NBA_MODEL_STATE_PARAMETERS_MISSING")
    fitted = {name: _finite_number(parameters.get(name), name) for name in REQUIRED_PARAMETERS}
    if fitted["pace_sd"] <= 0 or fitted["shared_eff_sd"] < 0 or fitted["team_eff_sd"] <= 0:
        raise ValueError("NBA_FITTED_VARIANCE_PARAMETER_INVALID")
    if fitted["margin_logistic_scale"] <= 0:
        raise ValueError("NBA_FITTED_MODEL_P_SCALE_INVALID")
    return fitted


def run(snapshot, config, n_sims=100000):
    n_sims = int(n_sims)
    if n_sims < MIN_SIMS:
        raise ValueError("SIMULATION_COUNT_BELOW_MINIMUM")
    for key in REQUIRED_SNAPSHOT:
        if snapshot.get(key) is None:
            raise ValueError(f"INPUTS_INCOMPLETE:{key}")

    if snapshot.get("defensive_rating_semantics") != "POINTS_ALLOWED_PER_100_POSSESSIONS":
        raise ValueError("NBA_DEFENSIVE_RATING_SEMANTICS_REQUIRED")
    params = _require_state(config)
    input_hash = _hash(snapshot)
    state_hash = _hash(config)
    seed = _seed(snapshot["event_id"], input_hash, state_hash, n_sims)
    rng = np.random.Generator(np.random.PCG64(seed))

    league_ortg = params["league_ortg"]
    hca = params["home_court_points_per100"]
    home_pace = _finite_number(snapshot["home_pace"], "home_pace")
    away_pace = _finite_number(snapshot["away_pace"], "away_pace")
    if home_pace <= 0 or away_pace <= 0:
        raise ValueError("NBA_PACE_INVALID")
    pace = 2.0 / (1.0 / home_pace + 1.0 / away_pace)

    home_availability = _finite_number(snapshot["home_availability_epm_per100"], "home_availability_epm_per100")
    away_availability = _finite_number(snapshot["away_availability_epm_per100"], "away_availability_epm_per100")
    home_eff = (
        league_ortg
        + (_finite_number(snapshot["home_adj_ortg"], "home_adj_ortg") - league_ortg)
        + (_finite_number(snapshot["away_adj_drtg"], "away_adj_drtg") - league_ortg)
        + hca
        + home_availability
    )
    away_eff = (
        league_ortg
        + (_finite_number(snapshot["away_adj_ortg"], "away_adj_ortg") - league_ortg)
        + (_finite_number(snapshot["home_adj_drtg"], "home_adj_drtg") - league_ortg)
        + away_availability
    )

    possessions = rng.normal(pace, params["pace_sd"], n_sims)
    shared = rng.normal(0.0, params["shared_eff_sd"], n_sims)
    home_path_eff = home_eff + shared + rng.normal(0.0, params["team_eff_sd"], n_sims)
    away_path_eff = away_eff + shared + rng.normal(0.0, params["team_eff_sd"], n_sims)
    home_points = np.maximum(0, np.rint(possessions * home_path_eff / 100.0))
    away_points = np.maximum(0, np.rint(possessions * away_path_eff / 100.0))

    tied = home_points == away_points
    if tied.any():
        home_ot = rng.binomial(1, 0.5, int(tied.sum()))
        home_points[tied] += home_ot
        away_points[tied] += 1 - home_ot

    margin = home_points - away_points
    total = home_points + away_points
    sim_p = float(np.mean(margin > 0))
    projected_margin = float(np.mean(margin))
    projected_total = float(np.mean(total))

    # Diagnostic analytic estimator. It remains separately labeled from the full
    # stochastic path probability and its scale must be fitted, never defaulted.
    expected_margin = pace * (home_eff - away_eff) / 100.0
    model_p = _logistic(expected_margin / params["margin_logistic_scale"])

    output = {
        "model_id": ENGINE_ID,
        "model_version": ENGINE_VERSION,
        "model_p": model_p,
        "sim_p": sim_p,
        "projected_margin": projected_margin,
        "projected_total": projected_total,
        "home_score_mean": float(home_points.mean()),
        "away_score_mean": float(away_points.mean()),
        "input_snapshot_hash": input_hash,
        "model_state_config_hash": state_hash,
        "simulation": {
            "engine": ENGINE_ID,
            "version": ENGINE_VERSION,
            "rng": "numpy.random.Generator(PCG64)",
            "count": n_sims,
            "seed": seed,
            "margin_quantiles": {str(q): float(np.quantile(margin, q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
            "total_quantiles": {str(q): float(np.quantile(total, q)) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
        },
        "provenance": {
            "fit_required": False,
            "market_features_used": False,
            "action_authority": False,
        },
    }
    output["output_hash"] = _hash(output)
    return output

