"""Paired evaluation for the MLB fixed-Poisson vs Gamma-Poisson workload experiment.

Consumes canonical evaluation rows emitted by research.evaluate_frozen_forecasts.
It does not generate forecasts, mutate grades, access markets, or grant promotion/action authority.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics as S
from pathlib import Path

from research import offline_benchmark as B

SCHEMA_VERSION = "mlb_distribution_experiment_report.v1"
EXPERIMENT_ID = "mlb.fixed_poisson_vs_gamma_poisson_workload.v1"
ARM_FIXED = "analytic"
ARM_OVERDISPERSED = "monte_carlo"
ARM_CONTRACTS = {
    ARM_FIXED: "fixed_poisson.v1",
    ARM_OVERDISPERSED: "gamma_poisson_workload_mc.v1",
}
CALIBRATION_EDGES = tuple(i / 10 for i in range(11))
FAVORITE_STRENGTH_EDGES = (0.50, 0.60, 0.70, 0.80, 1.0000000001)


class DistributionExperimentError(ValueError):
    pass


def _load_jsonl(path: Path):
    data = path.read_bytes()
    rows = []
    for line_no, raw in enumerate(data.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except Exception as exc:
            raise DistributionExperimentError(f"invalid JSONL line {line_no}: {exc}") from exc
        if not isinstance(row, dict):
            raise DistributionExperimentError(f"JSONL line {line_no} is not an object")
        rows.append(row)
    return rows, B.digest(rows)


def _key(r):
    return "|".join([
        str(r["event_id"]),
        str(r["forecast_cutoff_utc"]),
        str(r["evidence_scope"]),
        B.digest(r["target_contract"]),
    ])


def _single_brier(r):
    y = int(r["outcome_value"])
    p = float(r["probabilities"]["home_win"])
    return (p - y) ** 2


def _log_loss(r):
    y = int(r["outcome_value"])
    p = float(r["probabilities"]["home_win"] if y else r["probabilities"]["away_win"])
    if not 0.0 < p <= 1.0:
        raise DistributionExperimentError("realized-class probability must be in (0,1]")
    return -math.log(p)


def _calibration(rows):
    bins = []
    weighted_gap = 0.0
    n_total = len(rows)
    for i, (lo, hi) in enumerate(zip(CALIBRATION_EDGES[:-1], CALIBRATION_EDGES[1:])):
        selected = []
        for r in rows:
            p = float(r["probabilities"]["home_win"])
            if lo <= p < hi or (i == 9 and p == 1.0):
                selected.append(r)
        if not selected:
            bins.append({"lo": lo, "hi": hi, "n": 0, "mean_probability": None,
                         "observed_home_win_rate": None, "absolute_gap": None})
            continue
        mean_p = S.mean(float(r["probabilities"]["home_win"]) for r in selected)
        obs = S.mean(int(r["outcome_value"]) for r in selected)
        gap = abs(mean_p - obs)
        weighted_gap += len(selected) * gap
        bins.append({"lo": lo, "hi": hi, "n": len(selected), "mean_probability": mean_p,
                     "observed_home_win_rate": obs, "absolute_gap": gap})
    return {
        "n": n_total,
        "calibration_in_the_large_home_probability_minus_outcome_rate":
            S.mean(float(r["probabilities"]["home_win"]) for r in rows) - S.mean(int(r["outcome_value"]) for r in rows),
        "fixed_10_bin_ece": weighted_gap / n_total,
        "bins": bins,
    }


def _arm_summary(rows):
    y = [int(r["outcome_value"]) for r in rows]
    ps = [[float(r["probabilities"]["away_win"]), float(r["probabilities"]["home_win"])] for r in rows]
    scores = B.probability_scores(y, ps)
    return {
        "n": len(rows),
        "log_loss_mean": scores["log_loss"],
        "brier_single_class_mean": S.mean(_single_brier(r) for r in rows),
        "calibration": _calibration(rows),
    }


def _strength_strata(fixed_map, over_map, keys):
    out = []
    for lo, hi in zip(FAVORITE_STRENGTH_EDGES[:-1], FAVORITE_STRENGTH_EDGES[1:]):
        selected = []
        for k in keys:
            p = float(fixed_map[k]["probabilities"]["home_win"])
            strength = max(p, 1.0 - p)
            if lo <= strength < hi:
                selected.append(k)
        if not selected:
            out.append({"reference_fixed_poisson_favorite_probability_band": [lo, min(hi, 1.0)],
                        "n": 0, "fixed_poisson": None, "gamma_poisson_workload_mc": None,
                        "delta_gamma_minus_fixed": None})
            continue
        a = [fixed_map[k] for k in selected]
        b = [over_map[k] for k in selected]
        sa = _arm_summary(a)
        sb = _arm_summary(b)
        out.append({
            "reference_fixed_poisson_favorite_probability_band": [lo, min(hi, 1.0)],
            "n": len(selected),
            "fixed_poisson": {"log_loss_mean": sa["log_loss_mean"], "brier_single_class_mean": sa["brier_single_class_mean"]},
            "gamma_poisson_workload_mc": {"log_loss_mean": sb["log_loss_mean"], "brier_single_class_mean": sb["brier_single_class_mean"]},
            "delta_gamma_minus_fixed": {
                "log_loss": sb["log_loss_mean"] - sa["log_loss_mean"],
                "brier_single_class": sb["brier_single_class_mean"] - sa["brier_single_class_mean"],
            },
        })
    return out


def evaluate(rows, *, bootstrap_seed=9172026, bootstrap_draws=2000):
    rows = [r for r in rows if str(r.get("league", "")).upper() == "MLB"]
    if not rows:
        raise DistributionExperimentError("no MLB evaluation rows")
    if any(r.get("outcome_type") != "BINARY_HOME_WIN" for r in rows):
        raise DistributionExperimentError("MLB distribution experiment requires binary winner rows")
    arms = {ARM_FIXED: {}, ARM_OVERDISPERSED: {}}
    unknown = sorted({r.get("model_arm_id") for r in rows} - set(arms))
    if unknown:
        raise DistributionExperimentError(f"unexpected MLB model arms: {unknown}")
    model_ids = set()
    for r in rows:
        model_ids.add(r.get("model_id"))
        k = _key(r)
        bucket = arms[r["model_arm_id"]]
        if k in bucket:
            raise DistributionExperimentError(f"duplicate arm/event row: {r['model_arm_id']} {k}")
        bucket[k] = r
    if len(model_ids) != 1:
        raise DistributionExperimentError("distribution comparison requires one shared model_id")
    if set(arms[ARM_FIXED]) != set(arms[ARM_OVERDISPERSED]):
        raise DistributionExperimentError("identical complete arm populations required")
    keys = sorted(arms[ARM_FIXED])
    fixed_map, over_map = arms[ARM_FIXED], arms[ARM_OVERDISPERSED]
    for k in keys:
        a, b = fixed_map[k], over_map[k]
        for field in ("event_id", "event_date_local", "forecast_cutoff_utc", "evidence_scope", "outcome_value"):
            if a.get(field) != b.get(field):
                raise DistributionExperimentError(f"paired row mismatch on {field}: {k}")
        if a.get("grade_record_hash") != b.get("grade_record_hash"):
            raise DistributionExperimentError(f"paired arms must share outcome grade: {k}")
    fixed_rows = [fixed_map[k] for k in keys]
    over_rows = [over_map[k] for k in keys]
    fixed = _arm_summary(fixed_rows)
    over = _arm_summary(over_rows)
    base_ll = {k: _log_loss(fixed_map[k]) for k in keys}
    alt_ll = {k: _log_loss(over_map[k]) for k in keys}
    base_br = {k: _single_brier(fixed_map[k]) for k in keys}
    alt_br = {k: _single_brier(over_map[k]) for k in keys}
    dates = {k: fixed_map[k]["event_date_local"] for k in keys}
    n_dates = len(set(dates.values()))
    ll_boot = ({"status": "NOT_RUN_INSUFFICIENT_DATE_CLUSTERS", "n_date_clusters": n_dates}
               if n_dates < 2 else {"status": "AVAILABLE", **B.paired_day_bootstrap(keys, dates, base_ll, alt_ll, bootstrap_seed, draws=bootstrap_draws)})
    br_boot = ({"status": "NOT_RUN_INSUFFICIENT_DATE_CLUSTERS", "n_date_clusters": n_dates}
               if n_dates < 2 else {"status": "AVAILABLE", **B.paired_day_bootstrap(keys, dates, base_br, alt_br, bootstrap_seed + 1, draws=bootstrap_draws)})
    core = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": EXPERIMENT_ID,
        "model_id": next(iter(model_ids)),
        "arm_contracts": ARM_CONTRACTS,
        "population": {
            "paired_event_count": len(keys),
            "date_cluster_count": n_dates,
            "pair_key_set_sha256": B.digest(keys),
            "evidence_scopes": sorted({r["evidence_scope"] for r in rows}),
        },
        "arm_metrics": {
            "fixed_poisson": fixed,
            "gamma_poisson_workload_mc": over,
        },
        "paired_deltas_gamma_minus_fixed": {
            "log_loss_mean": S.mean(alt_ll[k] - base_ll[k] for k in keys),
            "brier_single_class_mean": S.mean(alt_br[k] - base_br[k] for k in keys),
            "log_loss_date_cluster_bootstrap": ll_boot,
            "brier_date_cluster_bootstrap": br_boot,
        },
        "favorite_strength_strata": _strength_strata(fixed_map, over_map, keys),
        "interpretation_contract": {
            "negative_delta_favors": "gamma_poisson_workload_mc",
            "positive_delta_favors": "fixed_poisson",
            "primary_metric": "paired_log_loss_delta_gamma_minus_fixed",
            "secondary_metric": "paired_brier_single_class_delta_gamma_minus_fixed",
            "calibration_diagnostics": ["calibration_in_the_large", "fixed_10_bin_ece", "fixed_10_bin_reliability_table"],
            "favorite_strength_reference_arm": "fixed_poisson",
            "market_inputs_used": False,
            "posthoc_arm_selection_permitted": False,
            "promotion_authority": False,
            "action_authority": False,
        },
    }
    return {**core, "report_hash": B.digest(core)}


def _md(report):
    d = report["paired_deltas_gamma_minus_fixed"]
    return (
        "# MLB Distribution-Arm Evaluation\n\n"
        f"- Experiment: `{report['experiment_id']}`\n"
        f"- Paired events: `{report['population']['paired_event_count']}`\n"
        f"- Date clusters: `{report['population']['date_cluster_count']}`\n"
        f"- Gamma − fixed log-loss delta: `{d['log_loss_mean']:.8f}`\n"
        f"- Gamma − fixed Brier delta: `{d['brier_single_class_mean']:.8f}`\n"
        f"- Report hash: `{report['report_hash']}`\n\n"
        "Negative paired deltas favor the Gamma-Poisson workload arm; positive deltas favor the fixed-Poisson arm. "
        "No promotion or action authority is granted by this report.\n"
    )


def write_report(report, output_dir: Path):
    dataset = report["population"]["pair_key_set_sha256"]
    dest = output_dir / dataset / report["report_hash"]
    dest.mkdir(parents=True, exist_ok=True)
    files = {
        "distribution_experiment_report.json": (json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode(),
        "distribution_experiment_report.md": _md(report).encode(),
    }
    for name, data in files.items():
        path = dest / name
        if path.exists() and path.read_bytes() != data:
            raise DistributionExperimentError(f"immutable output collision: {path}")
        if not path.exists():
            path.write_bytes(data)
    return dest


def parser():
    p = argparse.ArgumentParser()
    p.add_argument("--evaluation-rows", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--bootstrap-seed", type=int, default=9172026)
    p.add_argument("--bootstrap-draws", type=int, default=2000)
    return p


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        rows, _ = _load_jsonl(a.evaluation_rows)
        report = evaluate(rows, bootstrap_seed=a.bootstrap_seed, bootstrap_draws=a.bootstrap_draws)
        dest = write_report(report, a.output_dir)
    except DistributionExperimentError as exc:
        print(f"DISTRIBUTION_EXPERIMENT_FAILED: {exc}")
        return 2
    print(json.dumps({"status": "PASS", "output_dir": str(dest), "report_hash": report["report_hash"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
