"""Paired evaluation for the MLB fixed-Poisson vs Gamma-Poisson workload experiment.

Consumes canonical evaluation rows emitted by research.evaluate_frozen_forecasts.
It does not generate forecasts, mutate grades, access markets, select an arm post hoc,
or grant promotion/action authority.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import math
import re
import statistics as S
from pathlib import Path

from research import offline_benchmark as B

SCHEMA_VERSION = "mlb_distribution_experiment_report.v2"
EXPERIMENT_ID = "mlb.fixed_poisson_vs_gamma_poisson_workload.v1"
ARM_FIXED = "analytic"
ARM_OVERDISPERSED = "monte_carlo"
ARM_CONTRACTS = {
    ARM_FIXED: "fixed_poisson.v1",
    ARM_OVERDISPERSED: "gamma_poisson_workload_mc.v1",
}
CALIBRATION_EDGES = tuple(i / 10 for i in range(11))
FAVORITE_STRENGTH_EDGES = (0.50, 0.60, 0.70, 0.80, 1.0000000001)
FORBIDDEN_INPUT_RE = re.compile(r"odds|moneyline|spread|price|vig|market|closing|result|outcome|label", re.I)
POSTHOC_FIELDS = {
    "selected_arm", "chosen_arm", "selection_basis", "selection_source",
    "posthoc_selected_arm", "winner_arm", "recommended_arm",
}
SHARED_PAIR_FIELDS = (
    "paired_game_universe_hash", "event_orientation_hash", "expected_run_input_hash",
    "feature_contract_version", "source_input_hash_set_hash", "model_code_identity",
    "predictive_input_field_names", "market_input_used",
)
HASH_PAIR_FIELDS = {
    "paired_game_universe_hash", "event_orientation_hash", "expected_run_input_hash",
    "source_input_hash_set_hash", "arm_context_hash",
}


class DistributionExperimentError(ValueError):
    pass


def _default_registry_path():
    return Path(__file__).with_name("mlb_distribution_arms_v1.json")


def load_registry(path: Path | None = None):
    p = path or _default_registry_path()
    try:
        registry = json.loads(p.read_text())
    except Exception as exc:
        raise DistributionExperimentError(f"invalid experiment registry: {p}: {exc}") from exc
    if registry.get("schema_version") != "mlb_distribution_arm_registry.v1":
        raise DistributionExperimentError("unexpected experiment registry schema")
    if registry.get("experiment_id") != EXPERIMENT_ID:
        raise DistributionExperimentError("experiment registry id mismatch")
    return registry


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


def _pairing(row):
    value = row.get("pairing")
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise DistributionExperimentError("pairing metadata must be object/null")
    return value


def _has_value(value):
    return value not in (None, "", [], {})


def _is_sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _check_posthoc(row):
    for container_name, container in (("row", row), ("pairing", _pairing(row))):
        for key in POSTHOC_FIELDS:
            if key in container and _has_value(container.get(key)):
                raise DistributionExperimentError(
                    f"POSTHOC_ARM_SELECTION_FORBIDDEN:{container_name}.{key}"
                )


def _check_market(row):
    pair = _pairing(row)
    if pair.get("market_input_used") is True:
        raise DistributionExperimentError("MARKET_INPUT_FORBIDDEN")
    names = pair.get("predictive_input_field_names")
    if names is not None:
        if not isinstance(names, list) or any(not isinstance(x, str) for x in names):
            raise DistributionExperimentError("predictive_input_field_names must be string list")
        bad = [x for x in names if FORBIDDEN_INPUT_RE.search(x)]
        if bad:
            raise DistributionExperimentError(f"MARKET_INPUT_FORBIDDEN:{bad[0]}")


def _metadata_missing(row, required):
    pair = _pairing(row)
    missing = []
    for field in required:
        value = pair.get(field)
        if not _has_value(value) and not (field == "market_input_used" and value is False):
            missing.append(field)
            continue
        if field in HASH_PAIR_FIELDS and not _is_sha256(value):
            missing.append(field + ":invalid_sha256")
    names = pair.get("predictive_input_field_names")
    if names is not None and not isinstance(names, list):
        missing.append("predictive_input_field_names:invalid_type")
    if pair.get("market_input_used") is not False:
        missing.append("market_input_used:not_explicit_false")
    expected = ARM_CONTRACTS.get(row.get("model_arm_id"))
    if pair.get("distribution_contract_id") != expected:
        missing.append("distribution_contract_id:mismatch")
    return sorted(set(missing))


def _single_brier(row):
    y = int(row["outcome_value"])
    p = float(row["probabilities"]["home_win"])
    return (p - y) ** 2


def _log_loss(row):
    y = int(row["outcome_value"])
    p = float(row["probabilities"]["home_win"] if y else row["probabilities"]["away_win"])
    if not 0.0 < p <= 1.0:
        raise DistributionExperimentError("realized-class probability must be in (0,1]")
    return -math.log(p)


def _calibration(rows):
    bins = []
    weighted_gap = 0.0
    n_total = len(rows)
    if not rows:
        return {"n": 0, "calibration_in_the_large_home_probability_minus_outcome_rate": None,
                "fixed_10_bin_ece": None, "bins": []}
    for i, (lo, hi) in enumerate(zip(CALIBRATION_EDGES[:-1], CALIBRATION_EDGES[1:])):
        selected = []
        for row in rows:
            p = float(row["probabilities"]["home_win"])
            if lo <= p < hi or (i == 9 and p == 1.0):
                selected.append(row)
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
            S.mean(float(r["probabilities"]["home_win"]) for r in rows)
            - S.mean(int(r["outcome_value"]) for r in rows),
        "fixed_10_bin_ece": weighted_gap / n_total,
        "bins": bins,
    }


def _arm_summary(rows):
    if not rows:
        return {"n": 0, "log_loss_mean": None, "brier_single_class_mean": None,
                "calibration": _calibration([])}
    y = [int(r["outcome_value"]) for r in rows]
    ps = [[float(r["probabilities"]["away_win"]), float(r["probabilities"]["home_win"])] for r in rows]
    scores = B.probability_scores(y, ps)
    return {
        "n": len(rows),
        "log_loss_mean": scores["log_loss"],
        "brier_single_class_mean": S.mean(_single_brier(r) for r in rows),
        "calibration": _calibration(rows),
    }


def _key(row):
    return "|".join([
        str(row["event_id"]), str(row["forecast_cutoff_utc"]),
        str(row["evidence_scope"]), B.digest(row["target_contract"]),
    ])


def _complete_pairs(rows, registry):
    rows = [r for r in rows if str(r.get("league", "")).upper() == "MLB"]
    if not rows:
        raise DistributionExperimentError("no MLB evaluation rows")
    by_arm = {ARM_FIXED: {}, ARM_OVERDISPERSED: {}}
    model_ids = set()
    for row in rows:
        if row.get("experiment_id") != EXPERIMENT_ID:
            raise DistributionExperimentError("unexpected/missing experiment_id")
        if row.get("outcome_type") != "BINARY_HOME_WIN":
            raise DistributionExperimentError("MLB distribution experiment requires binary winner rows")
        arm = row.get("model_arm_id")
        if arm not in by_arm:
            raise DistributionExperimentError(f"unexpected MLB model arm: {arm}")
        _check_posthoc(row)
        _check_market(row)
        event = str(row.get("event_id") or "")
        if not event:
            raise DistributionExperimentError("missing event_id")
        if event in by_arm[arm]:
            raise DistributionExperimentError(f"DUPLICATE_ARM_EVENT:{event}:{arm}")
        by_arm[arm][event] = row
        model_ids.add(row.get("model_id"))
    if len(model_ids) != 1:
        raise DistributionExperimentError("distribution comparison requires one shared model_id")
    if set(by_arm[ARM_FIXED]) != set(by_arm[ARM_OVERDISPERSED]):
        raise DistributionExperimentError("INCOMPLETE_PAIRED_POPULATION")

    required = tuple(registry.get("required_pair_metadata") or ())
    universe_hashes = set()
    pairs = []
    for event in sorted(by_arm[ARM_FIXED]):
        fixed = by_arm[ARM_FIXED][event]
        gamma = by_arm[ARM_OVERDISPERSED][event]
        for field, token in (
            ("event_date_local", "PAIR_DATE_MISMATCH"),
            ("forecast_cutoff_utc", "PAIR_CUTOFF_MISMATCH"),
            ("scheduled_start_utc", "PAIR_START_MISMATCH"),
            ("evidence_scope", "PAIR_SCOPE_MISMATCH"),
            ("outcome_value", "PAIR_OUTCOME_MISMATCH"),
            ("grade_record_hash", "PAIR_GRADE_MISMATCH"),
        ):
            if fixed.get(field) != gamma.get(field):
                raise DistributionExperimentError(f"{token}:{event}")
        if B.digest(fixed.get("target_contract")) != B.digest(gamma.get("target_contract")):
            raise DistributionExperimentError(f"PAIR_TARGET_CONTRACT_MISMATCH:{event}")
        fp, gp = _pairing(fixed), _pairing(gamma)
        for field in SHARED_PAIR_FIELDS:
            if fp.get(field) != gp.get(field):
                tokens = {
                    "event_orientation_hash": "PAIR_ORIENTATION_MISMATCH",
                    "expected_run_input_hash": "PAIR_EXPECTED_RUN_INPUT_HASH_MISMATCH",
                    "paired_game_universe_hash": "PAIR_UNIVERSE_MISMATCH",
                }
                raise DistributionExperimentError(f"{tokens.get(field, 'PAIR_SHARED_METADATA_MISMATCH')}:{field}:{event}")
        if fp.get("distribution_contract_id") not in (None, ARM_CONTRACTS[ARM_FIXED]):
            raise DistributionExperimentError(f"ARM_CONTRACT_MISMATCH:{event}:{ARM_FIXED}")
        if gp.get("distribution_contract_id") not in (None, ARM_CONTRACTS[ARM_OVERDISPERSED]):
            raise DistributionExperimentError(f"ARM_CONTRACT_MISMATCH:{event}:{ARM_OVERDISPERSED}")
        if fp.get("paired_game_universe_hash"):
            universe_hashes.add(fp["paired_game_universe_hash"])
        missing_fixed = _metadata_missing(fixed, required)
        missing_gamma = _metadata_missing(gamma, required)
        promotion_eligible = (
            fixed.get("evidence_scope") == "REMOTE_DURABLE_PROSPECTIVE"
            and gamma.get("evidence_scope") == "REMOTE_DURABLE_PROSPECTIVE"
            and fixed.get("canonical_prospective_eligible") is True
            and gamma.get("canonical_prospective_eligible") is True
            and not missing_fixed and not missing_gamma
        )
        reasons = []
        if fixed.get("evidence_scope") != "REMOTE_DURABLE_PROSPECTIVE":
            reasons.append("LOCAL_OR_NONCANONICAL_EVIDENCE_SCOPE")
        if fixed.get("canonical_prospective_eligible") is not True or gamma.get("canonical_prospective_eligible") is not True:
            reasons.append("CANONICAL_PROSPECTIVE_ELIGIBILITY_FALSE")
        if missing_fixed or missing_gamma:
            reasons.append("CONTRACT_METADATA_INCOMPLETE")
        pairs.append({
            "event_id": event, "key": _key(fixed), "fixed": fixed, "gamma": gamma,
            "promotion_sample_eligible": promotion_eligible,
            "promotion_exclusion_reasons": sorted(set(reasons)),
            "missing_contract_metadata": {"analytic": missing_fixed, "monte_carlo": missing_gamma},
        })
    if len(universe_hashes) > 1:
        raise DistributionExperimentError("PAIR_UNIVERSE_MISMATCH:multiple universe hashes")
    return pairs, next(iter(model_ids))


def _metric_maps(pairs):
    keys = [p["key"] for p in pairs]
    fixed = {p["key"]: p["fixed"] for p in pairs}
    gamma = {p["key"]: p["gamma"] for p in pairs}
    dates = {p["key"]: p["fixed"]["event_date_local"] for p in pairs}
    return keys, fixed, gamma, dates


def _bootstrap(keys, dates, baseline, challenger, seed, draws):
    n_dates = len(set(dates[k] for k in keys)) if keys else 0
    if len(keys) == 0:
        return {"status": "NOT_RUN_EMPTY_POPULATION", "n_date_clusters": 0}
    if n_dates < 2:
        return {"status": "NOT_RUN_INSUFFICIENT_DATE_CLUSTERS", "n_date_clusters": n_dates}
    return {"status": "AVAILABLE", **B.paired_day_bootstrap(
        keys, {k: dates[k] for k in keys}, {k: baseline[k] for k in keys},
        {k: challenger[k] for k in keys}, seed, draws=draws)}


def _paired_delta_report(pairs, seed, draws):
    if not pairs:
        return {
            "paired_event_count": 0, "date_cluster_count": 0,
            "log_loss_mean_gamma_minus_fixed": None,
            "brier_single_class_mean_gamma_minus_fixed": None,
            "log_loss_date_cluster_bootstrap": {"status": "NOT_RUN_EMPTY_POPULATION", "n_date_clusters": 0},
            "brier_date_cluster_bootstrap": {"status": "NOT_RUN_EMPTY_POPULATION", "n_date_clusters": 0},
        }
    keys, fixed, gamma, dates = _metric_maps(pairs)
    base_ll = {k: _log_loss(fixed[k]) for k in keys}
    alt_ll = {k: _log_loss(gamma[k]) for k in keys}
    base_br = {k: _single_brier(fixed[k]) for k in keys}
    alt_br = {k: _single_brier(gamma[k]) for k in keys}
    return {
        "paired_event_count": len(keys),
        "date_cluster_count": len(set(dates.values())),
        "log_loss_mean_gamma_minus_fixed": S.mean(alt_ll[k] - base_ll[k] for k in keys),
        "brier_single_class_mean_gamma_minus_fixed": S.mean(alt_br[k] - base_br[k] for k in keys),
        "log_loss_date_cluster_bootstrap": _bootstrap(keys, dates, base_ll, alt_ll, seed, draws),
        "brier_date_cluster_bootstrap": _bootstrap(keys, dates, base_br, alt_br, seed + 1, draws),
    }


def _ci_direction(bootstrap):
    if bootstrap.get("status") != "AVAILABLE":
        return None
    lo, hi = bootstrap["ci95"]
    if hi < 0:
        return "gamma_poisson_workload_mc"
    if lo > 0:
        return "fixed_poisson"
    return None


def _strength_strata(pairs, minimum_n, seed, draws):
    out = []
    for index, (lo, hi) in enumerate(zip(FAVORITE_STRENGTH_EDGES[:-1], FAVORITE_STRENGTH_EDGES[1:])):
        selected = []
        for pair in pairs:
            p = float(pair["fixed"]["probabilities"]["home_win"])
            strength = max(p, 1.0 - p)
            if lo <= strength < hi:
                selected.append(pair)
        display_hi = min(hi, 1.0)
        if not selected:
            out.append({
                "reference_fixed_poisson_favorite_probability_band": [lo, display_hi],
                "n": 0, "status": "INSUFFICIENT_STRATUM_N", "minimum_n": minimum_n,
                "fixed_poisson": None, "gamma_poisson_workload_mc": None,
                "observed_home_win_rate": None, "mean_absolute_arm_probability_difference": None,
                "direction_flip_count": 0, "paired_deltas": None,
            })
            continue
        fixed_rows = [p["fixed"] for p in selected]
        gamma_rows = [p["gamma"] for p in selected]
        obs = S.mean(int(r["outcome_value"]) for r in fixed_rows)
        fixed_mean_p = S.mean(float(r["probabilities"]["home_win"]) for r in fixed_rows)
        gamma_mean_p = S.mean(float(r["probabilities"]["home_win"]) for r in gamma_rows)
        delta = _paired_delta_report(selected, seed + 10 + index * 2, draws)
        out.append({
            "reference_fixed_poisson_favorite_probability_band": [lo, display_hi],
            "n": len(selected),
            "status": "AVAILABLE_FOR_REGIME_CHECK" if len(selected) >= minimum_n else "INSUFFICIENT_STRATUM_N",
            "minimum_n": minimum_n,
            "fixed_poisson": {
                "mean_home_win_probability": fixed_mean_p,
                "observed_home_win_rate": obs,
                "calibration_gap_probability_minus_observed": fixed_mean_p - obs,
                "log_loss_mean": _arm_summary(fixed_rows)["log_loss_mean"],
                "brier_single_class_mean": _arm_summary(fixed_rows)["brier_single_class_mean"],
            },
            "gamma_poisson_workload_mc": {
                "mean_home_win_probability": gamma_mean_p,
                "observed_home_win_rate": obs,
                "calibration_gap_probability_minus_observed": gamma_mean_p - obs,
                "log_loss_mean": _arm_summary(gamma_rows)["log_loss_mean"],
                "brier_single_class_mean": _arm_summary(gamma_rows)["brier_single_class_mean"],
            },
            "observed_home_win_rate": obs,
            "mean_absolute_arm_probability_difference": S.mean(
                abs(float(a["probabilities"]["home_win"]) - float(b["probabilities"]["home_win"]))
                for a, b in zip(fixed_rows, gamma_rows)),
            "direction_flip_count": sum(
                (float(a["probabilities"]["home_win"]) >= .5)
                != (float(b["probabilities"]["home_win"]) >= .5)
                for a, b in zip(fixed_rows, gamma_rows)),
            "paired_deltas": delta,
        })
    return out


def _decision(*, development_pairs, holdout_pairs, holdout_start, strata, registry, seed, draws):
    gate = registry["evaluation_contract"]["minimum_decision_gate"]
    dev = _paired_delta_report(development_pairs, seed + 100, draws)
    hold = _paired_delta_report(holdout_pairs, seed + 200, draws)
    result = {
        "status": None,
        "favored_arm": None,
        "promotion_authority": False,
        "automatic_promotion": False,
        "action_authority": False,
        "development": dev,
        "final_holdout": {"start_date": holdout_start, **hold},
        "gates": {
            "minimum_paired_events": gate["paired_events"],
            "minimum_date_clusters": gate["independent_date_clusters"],
            "minimum_stratum_n": gate["strong_favorite_stratum_minimum_events"],
        },
    }
    if dev["paired_event_count"] < gate["paired_events"] or dev["date_cluster_count"] < gate["independent_date_clusters"]:
        result["status"] = "INSUFFICIENT_PROMOTION_SAMPLE"
        return result
    if holdout_start is None:
        result["status"] = "FINAL_HOLDOUT_NOT_PREDECLARED"
        return result
    primary_direction = _ci_direction(dev["log_loss_date_cluster_bootstrap"])
    if primary_direction is None:
        result["status"] = "NO_CLEAR_WINNER"
        return result
    secondary_direction = _ci_direction(dev["brier_date_cluster_bootstrap"])
    if secondary_direction is not None and secondary_direction != primary_direction:
        result["status"] = "NO_CLEAR_WINNER_SECONDARY_CONTRADICTION"
        result["favored_arm"] = primary_direction
        return result
    for stratum in strata:
        if stratum["status"] != "AVAILABLE_FOR_REGIME_CHECK":
            continue
        direction = _ci_direction(stratum["paired_deltas"]["log_loss_date_cluster_bootstrap"])
        if direction is not None and direction != primary_direction:
            result["status"] = "REGIME_DEPENDENCE_RESEARCH_REQUIRED"
            result["favored_arm"] = primary_direction
            result["contradictory_stratum"] = stratum["reference_fixed_poisson_favorite_probability_band"]
            return result
    if hold["date_cluster_count"] < 2:
        result["status"] = "HOLDOUT_INSUFFICIENT_DATE_CLUSTERS"
        result["favored_arm"] = primary_direction
        return result
    holdout_direction = _ci_direction(hold["log_loss_date_cluster_bootstrap"])
    if holdout_direction != primary_direction:
        result["status"] = "HOLDOUT_DID_NOT_CONFIRM"
        result["favored_arm"] = primary_direction
        result["holdout_direction"] = holdout_direction
        return result
    result["favored_arm"] = primary_direction
    result["status"] = (
        "EVIDENCE_SUPPORTS_GAMMA_POISSON_RESEARCH_ONLY"
        if primary_direction == "gamma_poisson_workload_mc"
        else "EVIDENCE_SUPPORTS_FIXED_POISSON_RESEARCH_ONLY"
    )
    return result


def evaluate(rows, *, registry=None, bootstrap_seed=9172026, bootstrap_draws=2000):
    registry = copy.deepcopy(registry) if registry is not None else load_registry()
    if registry.get("experiment_id") != EXPERIMENT_ID:
        raise DistributionExperimentError("experiment registry id mismatch")
    pairs, model_id = _complete_pairs(rows, registry)
    fixed_rows = [p["fixed"] for p in pairs]
    gamma_rows = [p["gamma"] for p in pairs]
    descriptive = _paired_delta_report(pairs, bootstrap_seed, bootstrap_draws)
    promotion_pairs = [p for p in pairs if p["promotion_sample_eligible"]]
    excluded = [p for p in pairs if not p["promotion_sample_eligible"]]

    holdout = registry.get("evaluation_contract", {}).get("final_holdout", {})
    holdout_start = holdout.get("start_date")
    if holdout_start is not None:
        try:
            dt.date.fromisoformat(holdout_start)
        except Exception as exc:
            raise DistributionExperimentError("final holdout start_date must be ISO date or null") from exc
        development_pairs = [p for p in promotion_pairs if p["fixed"]["event_date_local"] < holdout_start]
        holdout_pairs = [p for p in promotion_pairs if p["fixed"]["event_date_local"] >= holdout_start]
    else:
        development_pairs = promotion_pairs
        holdout_pairs = []

    minimum_n = registry["evaluation_contract"]["minimum_decision_gate"]["strong_favorite_stratum_minimum_events"]
    descriptive_strata = _strength_strata(pairs, minimum_n, bootstrap_seed + 300, bootstrap_draws)
    decision_strata = _strength_strata(development_pairs, minimum_n, bootstrap_seed + 500, bootstrap_draws)
    decision = _decision(
        development_pairs=development_pairs, holdout_pairs=holdout_pairs,
        holdout_start=holdout_start, strata=decision_strata, registry=registry,
        seed=bootstrap_seed, draws=bootstrap_draws,
    )
    pair_keys = sorted(p["key"] for p in pairs)
    core = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": EXPERIMENT_ID,
        "experiment_registry_sha256": B.digest(registry),
        "model_id": model_id,
        "arm_contracts": ARM_CONTRACTS,
        "population": {
            "descriptive_paired_event_count": len(pairs),
            "descriptive_date_cluster_count": len({p["fixed"]["event_date_local"] for p in pairs}),
            "pair_key_set_sha256": B.digest(pair_keys),
            "evidence_scopes": sorted({p["fixed"]["evidence_scope"] for p in pairs}),
            "promotion_sample_eligible_pair_count": len(promotion_pairs),
            "promotion_sample_excluded_pair_count": len(excluded),
            "promotion_exclusion_reasons": {
                reason: sum(reason in p["promotion_exclusion_reasons"] for p in excluded)
                for reason in sorted({r for p in excluded for r in p["promotion_exclusion_reasons"]})
            },
        },
        "arm_metrics_descriptive": {
            "fixed_poisson": _arm_summary(fixed_rows),
            "gamma_poisson_workload_mc": _arm_summary(gamma_rows),
        },
        "paired_deltas_descriptive_gamma_minus_fixed": descriptive,
        "favorite_strength_strata_descriptive": descriptive_strata,
        "favorite_strength_strata_decision_sample": decision_strata,
        "decision": decision,
        "interpretation_contract": {
            "negative_delta_favors": "gamma_poisson_workload_mc",
            "positive_delta_favors": "fixed_poisson",
            "primary_metric": "paired_log_loss_delta_gamma_minus_fixed",
            "secondary_metric": "paired_brier_single_class_delta_gamma_minus_fixed",
            "favorite_strength_reference_arm": "fixed_poisson",
            "local_diagnostic_counts_toward_decision": False,
            "final_holdout_same_arm_confirmation_required": True,
            "opposite_high_volume_stratum_disposition": "REGIME_DEPENDENCE_RESEARCH_REQUIRED",
            "regime_specific_selector_requires_new_preregistered_experiment": True,
            "market_inputs_used": False,
            "posthoc_arm_selection_permitted": False,
            "promotion_authority": False,
            "automatic_promotion": False,
            "action_authority": False,
        },
    }
    return {**core, "report_hash": B.digest(core)}


def _md(report):
    d = report["paired_deltas_descriptive_gamma_minus_fixed"]
    decision = report["decision"]
    return (
        "# MLB Distribution-Arm Evaluation\n\n"
        f"- Experiment: `{report['experiment_id']}`\n"
        f"- Descriptive paired events: `{report['population']['descriptive_paired_event_count']}`\n"
        f"- Promotion-eligible pairs: `{report['population']['promotion_sample_eligible_pair_count']}`\n"
        f"- Gamma - fixed descriptive log-loss delta: `{d['log_loss_mean_gamma_minus_fixed']}`\n"
        f"- Gamma - fixed descriptive Brier delta: `{d['brier_single_class_mean_gamma_minus_fixed']}`\n"
        f"- Decision status: `{decision['status']}`\n"
        f"- Report hash: `{report['report_hash']}`\n\n"
        "Local-diagnostic rows are descriptive only. A research-favored arm requires the predeclared "
        "development gate, no material opposite predeclared stratum, and confirmation on the separately "
        "preregistered untouched final time block. No promotion or action authority is granted.\n"
    )


def write_report(report, output_dir: Path):
    dataset = report["population"]["pair_key_set_sha256"]
    dest = output_dir / dataset / report["report_hash"]
    dest.mkdir(parents=True, exist_ok=True)
    files = {
        "distribution_experiment_report.json":
            (json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode(),
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
    p.add_argument("--registry", type=Path, default=_default_registry_path())
    p.add_argument("--bootstrap-seed", type=int, default=9172026)
    p.add_argument("--bootstrap-draws", type=int, default=2000)
    return p


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        rows, _ = _load_jsonl(a.evaluation_rows)
        registry = load_registry(a.registry)
        report = evaluate(rows, registry=registry, bootstrap_seed=a.bootstrap_seed,
                          bootstrap_draws=a.bootstrap_draws)
        dest = write_report(report, a.output_dir)
    except DistributionExperimentError as exc:
        print(f"DISTRIBUTION_EXPERIMENT_FAILED: {exc}")
        return 2
    print(json.dumps({"status": "PASS", "output_dir": str(dest),
                      "report_hash": report["report_hash"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
