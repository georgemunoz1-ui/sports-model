#!/usr/bin/env python3
"""Reproducible MLB V13.1-style diagnostic Monte Carlo engine.

Consumes a frozen JSON input snapshot. No sportsbook price is an input. Missing
starter fields fall back to registered league priors and are recorded explicitly.

Version 1.0.2 adds diagnostics/ablation evidence only. The action probability is
not redefined here; Analytic P remains a separate adapter-level diagnostic and
Stochastic Sim P remains the empirical Gamma-Poisson result.
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
ENGINE_VERSION = "1.0.2"
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


def variant_seed(event_id, input_hash, config_hash, n_sims, variant):
    payload = (
        f"{event_id}|{input_hash}|{config_hash}|{ENGINE_VERSION}|"
        f"{int(n_sims)}|ablation:{variant}"
    )
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
    weight = games_started / (games_started + 8.0)
    return weight * era + (1 - weight) * LG_ERA


def starter_ra9(sp):
    era = val(sp.get("era"), LG_ERA)
    games_started = val(sp.get("gs"), 0)
    strikeout_rate = val(sp.get("k"), LG_K)
    walk_rate = val(sp.get("bb"), LG_BB)
    return max(
        2.2,
        shrunk(era, games_started) - ((strikeout_rate - walk_rate) - 13.5) * 0.03,
    )


def bipf(sp):
    return max(
        0.45,
        1 - (val(sp.get("k"), LG_K) + val(sp.get("bb"), LG_BB)) / 100,
    )


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


def independent_poisson_home_win(mu_home, mu_away, limit=30, tie_home_share=0.5):
    """Closed-form independent-Poisson home-win probability at fixed rates."""
    home_pmf = [math.exp(-mu_home)]
    away_pmf = [math.exp(-mu_away)]
    for k in range(1, limit + 1):
        home_pmf.append(home_pmf[-1] * mu_home / k)
        away_pmf.append(away_pmf[-1] * mu_away / k)
    probability = 0.0
    for home_runs, p_home_runs in enumerate(home_pmf):
        probability += p_home_runs * (
            sum(away_pmf[:home_runs]) + tie_home_share * away_pmf[home_runs]
        )
    return min(1.0, max(0.0, probability))


def _safe_corr(x, y):
    if len(x) < 2 or float(np.std(x)) == 0 or float(np.std(y)) == 0:
        return 0.0
    value = float(np.corrcoef(x, y)[0, 1])
    return value if math.isfinite(value) else 0.0


def run(snapshot, config, n, runline=None, total_line=None, *, score_sink=None):
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

    away_shape = float(np.clip(1.8 + (val(home_sp.get("k"), LG_K) - LG_K) * 0.16, 1.2, 6))
    home_shape = float(np.clip(1.8 + (val(away_sp.get("k"), LG_K) - LG_K) * 0.16, 1.2, 6))

    # Keep the registered RNG call order stable: away gamma -> away Poisson ->
    # home gamma -> home Poisson -> tie resolution.
    away_latent_rate = rng.gamma(away_shape, np.maximum(mu_away, 0.3) / away_shape)
    away_runs = rng.poisson(away_latent_rate)
    home_latent_rate = rng.gamma(home_shape, np.maximum(mu_home, 0.3) / home_shape)
    home_runs = rng.poisson(home_latent_rate)

    ties = home_runs == away_runs
    tie_home_share = 0.5 + 0.04 * np.sign(away_pen - home_pen)
    home_win = (home_runs > away_runs) | (
        ties & (rng.random(n) < tie_home_share)
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

    home_runs_mean = float(np.mean(home_runs))
    away_runs_mean = float(np.mean(away_runs))
    total_mean = float(np.mean(totals))
    margin_mean = float(np.mean(margin))
    margin_std = float(np.std(margin))
    total_std = float(np.std(totals))
    home_expected_runs_mean = float(np.mean(mu_home))
    away_expected_runs_mean = float(np.mean(mu_away))
    home_win_p_sim = float(np.mean(home_win))

    # Variant A: fixed-rate independent Poisson. This is the structural baseline
    # that should closely track the legacy Analytic P definition.
    ablation_a_home_p = independent_poisson_home_win(
        home_runs_mean,
        away_runs_mean,
        tie_home_share=0.5,
    )

    # Variant B: fixed mean rates + Gamma overdispersion, but no starter-workload
    # uncertainty. A dedicated deterministic stream keeps this diagnostic from
    # perturbing the registered simulation stream.
    b_seed = variant_seed(snapshot["event_id"], input_hash, config_hash, n, "B_FIXED_GAMMA")
    b_rng = np.random.Generator(np.random.PCG64(b_seed))
    b_away_latent = b_rng.gamma(away_shape, max(away_expected_runs_mean, 0.3) / away_shape, n)
    b_away_runs = b_rng.poisson(b_away_latent)
    b_home_latent = b_rng.gamma(home_shape, max(home_expected_runs_mean, 0.3) / home_shape, n)
    b_home_runs = b_rng.poisson(b_home_latent)
    b_ties = b_home_runs == b_away_runs
    b_home_win = (b_home_runs > b_away_runs) | (
        b_ties & (b_rng.random(n) < tie_home_share)
    )
    b_total = b_home_runs + b_away_runs
    ablation_b_home_p = float(np.mean(b_home_win))

    diagnostics = {
        "projected_home_runs_realized_mean": home_runs_mean,
        "projected_away_runs_realized_mean": away_runs_mean,
        "projected_home_runs_latent_mean": home_expected_runs_mean,
        "projected_away_runs_latent_mean": away_expected_runs_mean,
        "gamma_shape_home": home_shape,
        "gamma_shape_away": away_shape,
        "gamma_scale_home_mean": home_expected_runs_mean / home_shape,
        "gamma_scale_away_mean": away_expected_runs_mean / away_shape,
        "gamma_dispersion_mean": 0.5 * ((1.0 / home_shape) + (1.0 / away_shape)),
        "run_rate_correlation": _safe_corr(home_latent_rate, away_latent_rate),
        "shared_environment_component": False,
        "starter_workload_variance": float(
            0.5 * (np.var(home_starter_ip) + np.var(away_starter_ip))
        ),
        "starter_ip_std_home": float(np.std(home_starter_ip)),
        "starter_ip_std_away": float(np.std(away_starter_ip)),
        "bullpen_share_home": float(np.mean((9.0 - home_starter_ip) / 9.0)),
        "bullpen_share_away": float(np.mean((9.0 - away_starter_ip) / 9.0)),
        "bullpen_sequencing_component": False,
        "park_factor": park_factor,
        "extra_inning_probability": float(np.mean(ties)),
        "analytic_home_p_at_realized_means": ablation_a_home_p,
        "analytic_home_p_at_latent_means": independent_poisson_home_win(
            home_expected_runs_mean,
            away_expected_runs_mean,
            tie_home_share=0.5,
        ),
        "normal_margin_home_p_candidate": (
            0.5 * (1.0 + math.erf((margin_mean / margin_std) / math.sqrt(2.0)))
            if margin_std > 0
            else None
        ),
        "ablation": {
            "A_FIXED_POISSON": {
                "latent_gamma_variance": False,
                "shared_environment": False,
                "starter_workload_randomness": False,
                "bullpen_sequencing": False,
                "home_win_p": ablation_a_home_p,
                "total_variance": home_runs_mean + away_runs_mean,
                "regulation_tie_probability": None,
                "method": "closed_form_independent_poisson_at_realized_mean_runs",
            },
            "B_FIXED_GAMMA": {
                "latent_gamma_variance": True,
                "shared_environment": False,
                "starter_workload_randomness": False,
                "bullpen_sequencing": False,
                "home_win_p": ablation_b_home_p,
                "total_variance": float(np.var(b_total)),
                "regulation_tie_probability": float(np.mean(b_ties)),
                "random_seed": b_seed,
            },
            "C_SHARED_ENVIRONMENT": {
                "status": "NOT_APPLICABLE_CURRENT_ENGINE",
                "reason": "CURRENT_ENGINE_HAS_NO_SHARED_RUN_ENVIRONMENT_COMPONENT",
            },
            "D_STARTER_WORKLOAD": {
                "latent_gamma_variance": True,
                "shared_environment": False,
                "starter_workload_randomness": True,
                "bullpen_sequencing": False,
                "home_win_p": home_win_p_sim,
                "total_variance": float(np.var(totals)),
                "regulation_tie_probability": float(np.mean(ties)),
                "note": "Equivalent to full engine because bullpen sequencing is not modeled.",
            },
            "E_FULL_CURRENT_ENGINE": {
                "latent_gamma_variance": True,
                "shared_environment": False,
                "starter_workload_randomness": True,
                "bullpen_sequencing": False,
                "home_win_p": home_win_p_sim,
                "total_variance": float(np.var(totals)),
                "regulation_tie_probability": float(np.mean(ties)),
            },
        },
    }

    # Optional retention hook consumes no randomness and leaves legacy payload
    # and seed identity unchanged. Consumers must label these nine-inning proxy
    # scores: the winner-only tie handler above does not add extra-inning runs.
    if score_sink is not None:
        score_sink(home_runs.copy(), away_runs.copy())

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
            "shared_environment": "NOT_MODELED",
            "bullpen_sequencing": "NOT_MODELED",
        },
        "simulation_count": int(n),
        "random_seed": seed,
        "input_snapshot_hash": input_hash,
        "model_state_config_hash": config_hash,
        "runtime_commit": git_commit(),
        "runtime_numpy_version": np.__version__,
        "projection": {
            "home_win_p_sim": home_win_p_sim,
            "away_win_p_sim": float(1 - home_win_p_sim),
            "home_runs_mean": home_runs_mean,
            "away_runs_mean": away_runs_mean,
            "home_expected_runs_mean": home_expected_runs_mean,
            "away_expected_runs_mean": away_expected_runs_mean,
            "total_mean": total_mean,
            "home_margin_mean": margin_mean,
            "margin_std": margin_std,
            "total_std": total_std,
            "home_runs_quantiles": quantiles(home_runs),
            "away_runs_quantiles": quantiles(away_runs),
            "total_quantiles": quantiles(totals),
            "margin_quantiles": quantiles(margin),
        },
        "diagnostics": diagnostics,
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--simulations", type=int, default=100000)
    parser.add_argument("--home-runline", type=float)
    parser.add_argument("--total-line", type=float)
    args = parser.parse_args()

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
