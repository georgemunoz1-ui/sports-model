#!/usr/bin/env python3
"""Investigate MLB Analytic P vs Stochastic Sim P divergence.

The script consumes a diagnostic card JSON and emits JSON/CSV/Markdown reports.
It does not attach sportsbook prices or compute EV. It uses the project's
registered divergence buckets: <4 pp NONE, 4-<8 MODERATE, 8-<12 SEVERE,
>=12 CRITICAL.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np


def category(abs_gap_pp):
    if abs_gap_pp >= 12.0:
        return "CRITICAL"
    if abs_gap_pp >= 8.0:
        return "SEVERE"
    if abs_gap_pp >= 4.0:
        return "MODERATE"
    return "NONE"


def finite(value):
    try:
        number = float(value)
        return math.isfinite(number)
    except Exception:
        return False


def get_prob(row, explicit, legacy):
    value = row.get(explicit)
    if value is None:
        value = row.get(legacy)
    return float(value)


def team_run_means(row):
    home = row.get("projected_home_runs")
    away = row.get("projected_away_runs")
    if finite(home) and finite(away):
        return float(home), float(away)
    total = row.get("projected_total")
    margin = row.get("projected_margin")
    if finite(total) and finite(margin):
        total = float(total)
        margin = float(margin)
        return (total + margin) / 2.0, (total - margin) / 2.0
    return None, None


def corr(x, y):
    if len(x) < 3:
        return None
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if np.std(x) == 0 or np.std(y) == 0:
        return None
    value = float(np.corrcoef(x, y)[0, 1])
    return value if math.isfinite(value) else None


def build_regression(rows):
    names = [
        "projected_total",
        "abs_projected_margin",
        "favorite_analytic_p",
        "gamma_dispersion_mean",
        "bullpen_share_mean",
    ]
    clean = []
    for row in rows:
        values = [row.get(name) for name in names]
        if all(finite(v) for v in values) and finite(row.get("absolute_gap_pp")):
            clean.append(([float(v) for v in values], float(row["absolute_gap_pp"])))
    if len(clean) <= len(names) + 1:
        return {
            "status": "INSUFFICIENT_SAMPLE",
            "n": len(clean),
            "predictors": names,
        }
    x = np.asarray([item[0] for item in clean], dtype=float)
    y = np.asarray([item[1] for item in clean], dtype=float)
    # Standardize predictors so coefficient magnitudes are directly comparable.
    means = x.mean(axis=0)
    stds = x.std(axis=0)
    stds[stds == 0] = 1.0
    z = (x - means) / stds
    design = np.column_stack([np.ones(len(z)), z])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    fitted = design @ beta
    ss_res = float(np.sum((y - fitted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else None
    return {
        "status": "DEBUG_SAMPLE_ONLY" if len(clean) < 100 else "OK",
        "n": len(clean),
        "predictors": names,
        "intercept_pp": float(beta[0]),
        "standardized_coefficients": {
            name: float(value) for name, value in zip(names, beta[1:])
        },
        "r_squared": r2,
        "warning": (
            "Single/small slates are debugging samples, not calibration evidence."
            if len(clean) < 100
            else None
        ),
    }


def build_row(row):
    analytic = get_prob(row, "analytic_p", "model_p")
    stochastic = get_prob(row, "stochastic_sim_p", "sim_p")
    signed_gap = 100.0 * (analytic - stochastic)
    abs_gap = abs(signed_gap)
    diagnostics = row.get("diagnostics") or {}
    home_runs, away_runs = team_run_means(row)
    projected_margin = row.get("projected_margin")
    projected_total = row.get("projected_total")
    model_winner = row.get("model_winner")
    home_team = row.get("home_team")
    favorite_home = model_winner == home_team
    ablation = diagnostics.get("ablation") or {}

    def ablation_home_p(name):
        item = ablation.get(name) or {}
        return item.get("home_win_p")

    def orient_home_probability(home_p):
        if not finite(home_p):
            return None
        home_p = float(home_p)
        return home_p if favorite_home else 1.0 - home_p

    fixed_poisson = orient_home_probability(ablation_home_p("A_FIXED_POISSON"))
    fixed_gamma = orient_home_probability(ablation_home_p("B_FIXED_GAMMA"))
    starter_workload = orient_home_probability(ablation_home_p("D_STARTER_WORKLOAD"))
    full_engine = orient_home_probability(ablation_home_p("E_FULL_CURRENT_ENGINE"))

    bullpen_values = [
        diagnostics.get("bullpen_share_home"),
        diagnostics.get("bullpen_share_away"),
    ]
    bullpen_values = [float(v) for v in bullpen_values if finite(v)]
    bullpen_share_mean = float(np.mean(bullpen_values)) if bullpen_values else None

    result = {
        "event_id": row.get("event_id"),
        "away_team": row.get("away_team"),
        "home_team": home_team,
        "analytic_favorite_team": model_winner,
        "favorite_home_flag": favorite_home,
        "projected_away_runs": away_runs,
        "projected_home_runs": home_runs,
        "projected_total": float(projected_total) if finite(projected_total) else None,
        "projected_margin": float(projected_margin) if finite(projected_margin) else None,
        "abs_projected_margin": abs(float(projected_margin)) if finite(projected_margin) else None,
        "analytic_p": analytic,
        "stochastic_sim_p": stochastic,
        "signed_gap_pp": signed_gap,
        "absolute_gap_pp": abs_gap,
        "divergence_category": category(abs_gap),
        "favorite_analytic_p": analytic,
        "favorite_sim_p": stochastic,
        "favorite_probability_compression_pp": signed_gap,
        "normal_margin_candidate_p": row.get("model_p_candidate_normal_margin"),
        "gamma_shape_home": diagnostics.get("gamma_shape_home"),
        "gamma_shape_away": diagnostics.get("gamma_shape_away"),
        "gamma_scale_home": diagnostics.get("gamma_scale_home_mean"),
        "gamma_scale_away": diagnostics.get("gamma_scale_away_mean"),
        "gamma_dispersion_mean": diagnostics.get("gamma_dispersion_mean"),
        "run_rate_correlation": diagnostics.get("run_rate_correlation"),
        "starter_workload_variance": diagnostics.get("starter_workload_variance"),
        "bullpen_share_home": diagnostics.get("bullpen_share_home"),
        "bullpen_share_away": diagnostics.get("bullpen_share_away"),
        "bullpen_share_mean": bullpen_share_mean,
        "park_factor": diagnostics.get("park_factor"),
        "extra_inning_probability": diagnostics.get("extra_inning_probability"),
        "margin_std": row.get("margin_std"),
        "total_std": row.get("total_std"),
        "ablation_A_fixed_poisson_favorite_p": fixed_poisson,
        "ablation_B_fixed_gamma_favorite_p": fixed_gamma,
        "ablation_C_shared_environment_status": (ablation.get("C_SHARED_ENVIRONMENT") or {}).get("status"),
        "ablation_D_starter_workload_favorite_p": starter_workload,
        "ablation_E_full_engine_favorite_p": full_engine,
        "ablation_gamma_effect_pp": (
            100.0 * (fixed_poisson - fixed_gamma)
            if finite(fixed_poisson) and finite(fixed_gamma)
            else None
        ),
        "ablation_workload_effect_pp": (
            100.0 * (fixed_gamma - starter_workload)
            if finite(fixed_gamma) and finite(starter_workload)
            else None
        ),
    }
    return result


def markdown(report):
    summary = report["summary"]
    lines = [
        f"# MLB Analytic-vs-Simulation Divergence — {report.get('card_date')}",
        "",
        f"Forecasts analyzed: **{summary['n']}**",
        "",
        "| Category | Count |",
        "|---|---:|",
    ]
    for name in ("CRITICAL", "SEVERE", "MODERATE", "NONE"):
        lines.append(f"| {name} | {summary['category_counts'].get(name, 0)} |")
    lines.extend(
        [
            "",
            "## Per-game",
            "",
            "| Game | Analytic P | Stochastic Sim P | Gap | Category | Margin | Total | Normal-margin candidate |",
            "|---|---:|---:|---:|---|---:|---:|---:|",
        ]
    )
    for row in report["games"]:
        game = f"{row['away_team']} @ {row['home_team']}"
        candidate = row.get("normal_margin_candidate_p")
        candidate_text = f"{100*float(candidate):.1f}%" if finite(candidate) else "—"
        margin = f"{row['projected_margin']:.2f}" if finite(row.get("projected_margin")) else "—"
        total = f"{row['projected_total']:.2f}" if finite(row.get("projected_total")) else "—"
        lines.append(
            f"| {game} | {100*row['analytic_p']:.1f}% | {100*row['stochastic_sim_p']:.1f}% | "
            f"{row['signed_gap_pp']:+.2f} pp | {row['divergence_category']} | {margin} | {total} | {candidate_text} |"
        )
    lines.extend(
        [
            "",
            "## Correlations with absolute divergence",
            "",
            "| Feature | Pearson r |",
            "|---|---:|",
        ]
    )
    for key, value in report["correlations"].items():
        text = f"{value:+.3f}" if value is not None else "—"
        lines.append(f"| {key} | {text} |")
    regression = report["regression"]
    lines.extend(
        [
            "",
            "## Multivariable debug regression",
            "",
            f"Status: **{regression.get('status')}** · n={regression.get('n')} · R²={regression.get('r_squared')}",
            "",
            "> This is a debugging sample. Do not treat one slate as calibration evidence.",
            "",
            "## Ablation interpretation",
            "",
            "- A isolates fixed-rate independent Poisson.",
            "- B adds Gamma run-rate overdispersion while holding starter workload fixed.",
            "- C is explicitly unavailable because the current engine has no shared run-environment component.",
            "- D adds starter-workload randomness.",
            "- E is the full current engine; it currently equals D because bullpen sequencing is not modeled.",
            "",
            "**No sportsbook prices or EV calculations are included.**",
        ]
    )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--card", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    card = json.loads(Path(args.card).read_text())
    if str(card.get("league", "")).upper() != "MLB":
        raise SystemExit("MLB_CARD_REQUIRED")

    games = [
        build_row(row)
        for row in card.get("forecasts", [])
        if row.get("forecast_status") == "FORECAST_GENERATED"
    ]
    if not games:
        raise SystemExit("NO_MLB_FORECASTS")

    counts = {name: 0 for name in ("CRITICAL", "SEVERE", "MODERATE", "NONE")}
    for row in games:
        counts[row["divergence_category"]] += 1

    feature_names = [
        "projected_total",
        "abs_projected_margin",
        "favorite_analytic_p",
        "gamma_dispersion_mean",
        "starter_workload_variance",
        "bullpen_share_mean",
        "park_factor",
        "extra_inning_probability",
    ]
    correlations = {}
    y = [row["absolute_gap_pp"] for row in games]
    for feature in feature_names:
        pairs = [
            (row.get(feature), row["absolute_gap_pp"])
            for row in games
            if finite(row.get(feature))
        ]
        correlations[feature] = corr(
            [float(x) for x, _ in pairs],
            [float(v) for _, v in pairs],
        )

    report = {
        "artifact_type": "mlb_model_sim_divergence_report_v1",
        "card_date": card.get("card_date"),
        "requested_as_of_utc": card.get("requested_as_of_utc", card.get("as_of_utc")),
        "pit_status": (card.get("pit_provenance") or {}).get("pit_status"),
        "summary": {
            "n": len(games),
            "mean_absolute_gap_pp": float(np.mean(y)),
            "median_absolute_gap_pp": float(np.median(y)),
            "max_absolute_gap_pp": float(np.max(y)),
            "category_counts": counts,
            "registered_thresholds_pp": {
                "NONE": "<4",
                "MODERATE": "4-<8",
                "SEVERE": "8-<12",
                "CRITICAL": ">=12",
            },
        },
        "correlations": correlations,
        "regression": build_regression(games),
        "games": games,
        "market_overlay_present": False,
        "action_authority": False,
    }

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "divergence_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (out / "divergence_report.md").write_text(markdown(report))

    fieldnames = list(games[0].keys())
    with (out / "divergence_report.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(games)

    print(markdown(report))


if __name__ == "__main__":
    main()
