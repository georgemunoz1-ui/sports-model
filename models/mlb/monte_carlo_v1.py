#!/usr/bin/env python3
"""Reproducible MLB V13.1-style diagnostic Monte Carlo engine.

Consumes a frozen JSON input snapshot. No sportsbook price is an input. Missing
starter fields fall back to registered league priors and are recorded explicitly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ENGINE_ID = "mlb.v13_1.gamma_poisson_monte_carlo.v1"
ENGINE_VERSION = "1.0.1"
MIN_SIMS = 50_000
LG_RPG = 4.45
LG_ERA = 4.20
LG_K = 22.0
LG_BB = 8.5
LG_BIP = 1 - (LG_K + LG_BB) / 100


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha_obj(x):
    return "sha256:" + hashlib.sha256(canonical(x)).hexdigest()


def seed_for(event_id, input_hash, config_hash, n_sims):
    payload = f"{event_id}|{input_hash}|{config_hash}|{ENGINE_VERSION}|{int(n_sims)}"
    return int.from_bytes(hashlib.sha256(payload.encode()).digest()[:4], "big")


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "UNKNOWN"


def val(x, default):
    try:
        y = float(x)
        return y if math.isfinite(y) else default
    except Exception:
        return default


def shrunk(era, games_started):
    w = games_started / (games_started + 8.0)
    return w * era + (1 - w) * LG_ERA


def starter_ra9(sp):
    era = val(sp.get("era"), LG_ERA)
    gs = val(sp.get("gs"), 0)
    k = val(sp.get("k"), LG_K)
    bb = val(sp.get("bb"), LG_BB)
    return max(2.2, shrunk(era, gs) - ((k - bb) - 13.5) * 0.03)


def bipf(sp):
    return max(0.45, 1 - (val(sp.get("k"), LG_K) + val(sp.get("bb"), LG_BB)) / 100)


def normalize_sp(sp, side, adjustments):
    sp = dict(sp or {})
    missing = []
    for key, default in (("era", LG_ERA), ("gs", 0), ("k", LG_K), ("bb", LG_BB)):
        if sp.get(key) is None:
            sp[key] = default
            missing.append(key)
    if missing:
        adjustments.append(f"{side}_STARTER_PRIOR_FALLBACK:" + ",".join(missing))
    return sp


def run(snapshot, config, n, runline=None, total_line=None):
    if n < MIN_SIMS:
        raise SystemExit(f"SIMULATION_COUNT_BELOW_MINIMUM:{MIN_SIMS}")

    adjustments = []
    away_sp = normalize_sp(snapshot.get("away_sp"), "AWAY", adjustments)
    home_sp = normalize_sp(snapshot.get("home_sp"), "HOME", adjustments)

    away_rf = val(snapshot.get("away_rf_pg"), LG_RPG)
    away_ra = val(snapshot.get("away_ra_pg"), LG_RPG)
    home_rf = val(snapshot.get("home_rf_pg"), LG_RPG)
    home_ra = val(snapshot.get("home_ra_pg"), LG_RPG)
    park_factor = val(snapshot.get("park_factor"), 1.0)

    away_offense = away_rf / LG_RPG
    home_offense = home_rf / LG_RPG
    away_pen = 0.55 * away_ra + 0.45 * LG_RPG
    home_pen = 0.55 * home_ra + 0.45 * LG_RPG

    home_starter_ra9 = starter_ra9(home_sp)
    away_starter_ra9 = starter_ra9(away_sp)
    away_park = 1 + (park_factor - 1) * (bipf(home_sp) / LG_BIP)
    home_park = 1 + (park_factor - 1) * (bipf(away_sp) / LG_BIP)

    input_hash = sha_obj(snapshot)
    config_hash = sha_obj(config)
    seed = seed_for(snapshot["event_id"], input_hash, config_hash, n)
    rng = np.random.Generator(np.random.PCG64(seed))

    away_starter_ip = np.clip(rng.normal(5.4, 1.3, n), 2, 8)
    home_starter_ip = np.clip(rng.normal(5.4, 1.3, n), 2, 8)

    mu_away = (
        home_starter_ra9 / 9 * away_starter_ip
        + home_pen / 9 * (9 - away_starter_ip)
    ) * away_offense * away_park
    mu_home = (
        away_starter_ra9 / 9 * home_starter_ip
        + away_pen / 9 * (9 - home_starter_ip)
    ) * home_offense * home_park * 1.005

    away_shape = np.clip(1.8 + (val(home_sp.get("k"), LG_K) - LG_K) * 0.16, 1.2, 6)
    home_shape = np.clip(1.8 + (val(away_sp.get("k"), LG_K) - LG_K) * 0.16, 1.2, 6)

    away_runs = rng.poisson(rng.gamma(away_shape, np.maximum(mu_away, 0.3) / away_shape))
    home_runs = rng.poisson(rng.gamma(home_shape, np.maximum(mu_home, 0.3) / home_shape))

    ties = home_runs == away_runs
    # Registered diagnostic extra-inning resolution: fair Bernoulli with a small
    # home-context adjustment inherited from V13.1.
    home_win = (home_runs > away_runs) | (
        ties & (rng.random(n) < (0.5 + 0.04 * np.sign(away_pen - home_pen)))
    )
    margin = home_runs - away_runs
    totals = home_runs + away_runs

    def quantiles(x):
        return dict(
            zip(
                ["p10", "p25", "p50", "p75", "p90"],
                map(float, np.quantile(x, [0.1, 0.25, 0.5, 0.75, 0.9])),
            )
        )

    out = {
        "artifact_type": "mlb_monte_carlo_forecast_bundle_v1",
        "event_id": snapshot["event_id"],
        "forecast_mode": "DIAGNOSTIC_SHADOW",
        "forecast_tier": "BASELINE_DIAGNOSTIC" if adjustments else "PRIMARY_SHADOW",
        "forecast_quality": "LOW" if adjustments else "MEDIUM",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "simulation_engine": ENGINE_ID,
        "simulation_engine_version": ENGINE_VERSION,
        "rng_algorithm": "PCG64",
        "distribution_specification": {
            "starter_innings": "Truncated Normal(5.4,1.3;2,8)",
            "latent_run_rate": "Gamma(shape, mean/shape)",
            "team_runs": "Poisson(latent_run_rate)",
            "mixture": "Gamma-Poisson / Negative-Binomial-equivalent",
        },
        "simulation_count": int(n),
        "random_seed": seed,
        "input_snapshot_hash": input_hash,
        "model_state_config_hash": config_hash,
        "runtime_commit": git_commit(),
        "runtime_numpy_version": np.__version__,
        "projection": {
            "home_win_p_sim": float(np.mean(home_win)),
            "away_win_p_sim": float(1 - np.mean(home_win)),
            "home_runs_mean": float(np.mean(home_runs)),
            "away_runs_mean": float(np.mean(away_runs)),
            "total_mean": float(np.mean(totals)),
            "home_margin_mean": float(np.mean(margin)),
            "home_runs_quantiles": quantiles(home_runs),
            "away_runs_quantiles": quantiles(away_runs),
            "total_quantiles": quantiles(totals),
            "margin_quantiles": quantiles(margin),
        },
        "quality_adjustments": adjustments,
        "market_features_used": False,
        "governance": {"action_authority": False, "action_status": "SHADOW_ONLY"},
    }

    if runline is not None:
        threshold = -float(runline)
        out["runline_evaluation"] = {
            "home_runline": float(runline),
            "home_cover_p_sim": float(np.mean(margin > threshold)),
            "away_cover_p_sim": float(np.mean(margin < threshold)),
            "push_p_sim": float(np.mean(margin == threshold)),
        }

    if total_line is not None:
        total = float(total_line)
        out["total_evaluation"] = {
            "total_line": total,
            "over_p_sim": float(np.mean(totals > total)),
            "under_p_sim": float(np.mean(totals < total)),
            "push_p_sim": float(np.mean(totals == total)),
        }

    # Forecast identity must be invariant to orchestration/request commits and wall
    # clock time. Runtime provenance remains in the artifact but is not part of the
    # numerical forecast payload hash.
    hash_payload = {
        key: value
        for key, value in out.items()
        if key not in (
            "generated_at_utc",
            "output_hash",
            "runtime_commit",
            "runtime_numpy_version",
        )
    }
    out["output_hash"] = sha_obj(hash_payload)
    out["reproduction_command"] = (
        "python models/mlb/monte_carlo_v1.py --snapshot <same.json> "
        "--config <same.json> --output <out.json> --simulations %d" % n
    )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--simulations", type=int, default=100000)
    ap.add_argument("--home-runline", type=float)
    ap.add_argument("--total-line", type=float)
    args = ap.parse_args()

    snapshot = json.load(open(args.snapshot))
    config = json.load(open(args.config))
    out = run(snapshot, config, args.simulations, args.home_runline, args.total_line)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "status": "PASS",
                "event_id": out["event_id"],
                "seed": out["random_seed"],
                "output_hash": out["output_hash"],
                "home_win_p_sim": out["projection"]["home_win_p_sim"],
            }
        )
    )


if __name__ == "__main__":
    main()
