"""Frozen-grid diagnostics separate from forecast fitting and operational gates.

The input forecasts are retained historical research outputs. Nothing in this
module fits a predictor, selects an optimum threshold, authenticates a historical
source, or grants eligibility. Continuous intervals are not integer contracts.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import math

import numpy as np
from scipy.special import ndtr, ndtri

from research.efficiency.evaluation import _rows, evaluate, EvaluationError
from research.selection_evaluation import evaluate_decisions
from research.validation_registry import content_id

THRESHOLDS = (.5, .55, .6, .65, .7, .75, .8, .85, .9, .95)
INTERVAL_LEVELS = (.5, .8, .9, .95)


def probability_diagnostics(rows, arm):
    probabilities = np.asarray([r[arm]["p_home"] for r in rows], dtype=float)
    truth = np.asarray([r["actual_home_win"] for r in rows], dtype=int)
    confidence = np.maximum(probabilities, 1-probabilities)
    correct = (probabilities >= .5) == truth
    bins = []
    for index in range(10):
        lower, upper = index/10, (index+1)/10
        mask = (probabilities >= lower) & ((probabilities < upper) if index < 9 else (probabilities <= upper))
        n = int(mask.sum())
        bins.append({"lower": lower, "upper": upper, "upper_inclusive": index == 9,
                     "n": n, "mean_probability": float(probabilities[mask].mean()) if n else None,
                     "observed_home_win_rate": float(truth[mask].mean()) if n else None})
    high = confidence >= .8
    return {"n": len(rows), "reliability_bins": bins,
            "binning": "fixed ten equal-width home-probability bins; p=1 included in last",
            "ece_descriptive": sum(b["n"]*abs(b["mean_probability"]-b["observed_home_win_rate"]) for b in bins if b["n"])/len(rows) if rows else None,
            "mean_confidence": float(confidence.mean()) if rows else None,
            "mean_absolute_distance_from_half": float(np.abs(probabilities-.5).mean()) if rows else None,
            "probability_standard_deviation": float(probabilities.std()) if rows else None,
            "high_confidence": {"threshold": .8, "n": int(high.sum()),
                "errors": int((~correct[high]).sum()),
                "risk": float((~correct[high]).mean()) if high.any() else None},
            "fitted_calibrator": None, "reliability_diagnostics_are_not_calibration_approval": True}


def _population(population, rows, excluded, discovery_ids):
    ids = [r["event_id"] for r in population]
    if len(ids) != len(set(ids)):
        raise EvaluationError("DUPLICATE_FULL_POPULATION_EVENT")
    if set(ids) & set(discovery_ids):
        raise EvaluationError("DISCOVERY_EVENT_IN_EVALUATION_POPULATION")
    predicted = {r["event_id"] for r in rows}
    excluded_ids = [r["event_id"] for r in excluded]
    if len(excluded_ids) != len(set(excluded_ids)):
        raise EvaluationError("DUPLICATE_STAGE_EXCLUSION")
    if predicted & set(excluded_ids):
        raise EvaluationError("PREDICTED_EVENT_ALSO_EXCLUDED")
    if predicted | set(excluded_ids) != set(ids):
        raise EvaluationError("STAGE_POPULATION_DOES_NOT_RECONCILE")
    by_id = {r["event_id"]: r for r in population}
    for row in rows:
        if by_id[row["event_id"]]["block_id"] != row["block_id"]:
            raise EvaluationError("POPULATION_BLOCK_CONFLICT")
    if any(not isinstance(r.get("block_id"), str) or not r["block_id"] for r in population):
        raise EvaluationError("POPULATION_BLOCK_REQUIRED")
    return by_id


def fixed_grid_curve(rows, population, arm, *, thresholds=THRESHOLDS, bootstrap_count=2000, seed=2302026):
    """Resample all declared blocks, retaining blocks with no selected forecasts.

    Coverage uses both declared opportunities and retained common forecasts.
    Risk is directional LOSS/(WIN+LOSS); this dataset has no ties or voids.
    Empty selections have undefined risk, never zero or perfect accuracy.
    """
    if tuple(thresholds) != THRESHOLDS:
        raise EvaluationError("FROZEN_THRESHOLD_GRID_REQUIRED")
    if type(bootstrap_count) is not int or bootstrap_count < 1:
        raise EvaluationError("POSITIVE_BOOTSTRAP_COUNT_REQUIRED")
    blocks = sorted({r["block_id"] for r in population})
    indices = {b: i for i, b in enumerate(blocks)}
    census = np.zeros(len(blocks), dtype=np.int64)
    for row in population:
        census[indices[row["block_id"]]] += 1
    forecastable = np.zeros(len(blocks), dtype=np.int64)
    for row in rows:
        forecastable[indices[row["block_id"]]] += 1
    rng = np.random.default_rng(seed)
    sampled = rng.integers(0, len(blocks), size=(bootstrap_count, len(blocks))) if blocks else np.empty((0, 0), dtype=int)
    result = []
    for threshold in thresholds:
        chosen = [r for r in rows if max(r[arm]["p_home"], 1-r[arm]["p_home"]) >= threshold]
        selected = np.zeros(len(blocks), dtype=np.int64)
        losses = np.zeros(len(blocks), dtype=np.int64)
        for row in chosen:
            index = indices[row["block_id"]]
            selected[index] += 1
            losses[index] += int(int(row[arm]["p_home"] >= .5) != row["actual_home_win"])
        n, n_loss = len(chosen), int(losses.sum())
        bootstrap = {"method": "full_population_chronological_block_percentile",
                     "resamples": bootstrap_count, "seed": seed, "n_blocks": len(blocks),
                     "risk_ci": None, "total_coverage_ci": None, "common_forecast_coverage_ci": None,
                     "empty_selection_resamples": None,
                     "assumption": "declared chronological blocks are independent; fitted predictors fixed"}
        if len(blocks) >= 2:
            counts = selected[sampled].sum(axis=1)
            failures = losses[sampled].sum(axis=1)
            denominators = census[sampled].sum(axis=1)
            common = forecastable[sampled].sum(axis=1)
            valid = counts > 0
            bootstrap["empty_selection_resamples"] = int((~valid).sum())
            if valid.any():
                bootstrap["risk_ci"] = np.quantile(failures[valid]/counts[valid], [.025, .975]).tolist()
            if (denominators > 0).any():
                valid_pop = denominators > 0
                bootstrap["total_coverage_ci"] = np.quantile(counts[valid_pop]/denominators[valid_pop], [.025, .975]).tolist()
            if (common > 0).any():
                valid_common = common > 0
                bootstrap["common_forecast_coverage_ci"] = np.quantile(counts[valid_common]/common[valid_common], [.025, .975]).tolist()
        result.append({"threshold": threshold, "n_selected": n, "wins": n-n_loss,
                       "losses": n_loss, "pushes": 0, "voids": 0, "risk": n_loss/n if n else None,
                       "accuracy": (n-n_loss)/n if n else None,
                       "coverage_all_opportunities": n/len(population) if population else None,
                       "coverage_common_forecasts": n/len(rows) if rows else None,
                       "n_abstained_or_unavailable": len(population)-n,
                       "bootstrap": bootstrap})
    return {"forecaster_arm": arm, "policy_id": content_id({"score": "max(p,1-p)", "thresholds": thresholds, "tie_side": "home"}),
            "context": "HYPOTHETICAL_HISTORICAL_CONFIDENCE_POLICY",
            "n_full_population": len(population), "n_common_forecasts": len(rows),
            "n_unavailable_forecasts": len(population)-len(rows),
            "settlement": "binary final-game winner; selected direction; non-tie WIN/LOSS population",
            "risk_denominator": "selected WIN+LOSS; zero selected => null risk",
            "threshold_selection": "NONE; every predeclared threshold reported",
            "curve": result, "operational_eligibility_granted": False, "promotion": False}


def operational_gate_report(rows, population, league, *, bootstrap_count=2000, seed=2302026):
    """Exercise the real evaluator with every policy row explicitly BLOCKED.

    Existing historical probabilities are retained and scored despite failed
    operational qualification. This is not the hypothetical confidence policy.
    """
    by_event = {r["event_id"]: r for r in rows}
    decision_rows, declared = [], []
    candidate_id = content_id({"model_ids": sorted({r["challenger"]["model_id"] for r in rows})})
    control_id = content_id({"model_ids": sorted({r["baseline"]["model_id"] for r in rows})})
    selector_id = content_id({"name": "unqualified_research_BLOCKED", "version": 1})
    family_id = content_id({"league": league, "product": "full_game_non_tie_winner", "price": None})
    for item in population:
        row = by_event.get(item["event_id"])
        choose_home = row is None or row["challenger"]["p_home"] >= .5
        target = item["event_id"] + (":HOME_WIN" if choose_home else ":AWAY_WIN")
        y = row["actual_home_win"] if row else item.get("actual_home_win")
        outcome = "MISSING" if y is None else ("WIN" if bool(y) == choose_home else "LOSS")
        p = (row["challenger"]["p_home"] if choose_home else 1-row["challenger"]["p_home"]) if row else None
        cp = (row["baseline"]["p_home"] if choose_home else 1-row["baseline"]["p_home"]) if row else None
        control_predicts_selected_side = row is not None and (row["baseline"]["p_home"] >= .5) == choose_home
        decision_rows.append({"event_id": item["event_id"], "target_id": target, "slate_id": item["block_id"],
            "procedure_id": candidate_id, "selector_config_id": selector_id, "control_procedure_id": control_id,
            "target_family_id": family_id, "decision_class": "BLOCKED", "outcome": outcome,
            "raw_probability": p, "control_probability": cp, "control_target_id": target,
            "control_predicted_outcome": "WIN" if control_predicts_selected_side else "LOSS"})
        declared.append({"event_id": item["event_id"], "target_id": target, "slate_id": item["block_id"]})
    report = evaluate_decisions(decision_rows, population=declared, evidence_scope="DISCOVERY",
                                bootstrap_samples=bootstrap_count, seed=seed)
    report.update(context="ACTUAL_QUALIFICATION_STATE_APPLIED_TO_RETAINED_RESEARCH_FORECASTS",
                  all_blocked_reason="NO_PROSPECTIVE_VALIDATION_AND_SCOPE_APPROVAL",
                  raw_predictions_preserved=len(rows), no_pick_is_not_success=True)
    return report


def normal_crps(mean, sd, actual):
    if not math.isfinite(sd) or sd <= 0:
        raise EvaluationError("POSITIVE_FINITE_JOINT_SD_REQUIRED")
    z = (actual-mean)/sd
    return sd*(z*(2*float(ndtr(z))-1) + 2*math.exp(-z*z/2)/math.sqrt(2*math.pi) - 1/math.sqrt(math.pi))


def joint_diagnostics(rows, *, league):
    products = {}
    for product, actual_name in (("home_margin", "actual_home_margin"), ("total", "actual_total")):
        entries = []
        for row in rows:
            forecast = row["challenger"]
            if league == "cfb":
                key = "margin_variance" if product == "home_margin" else "total_variance"
                variance = forecast.get("components", {}).get(key)
                sd = math.sqrt(variance) if variance is not None and variance > 0 else None
            else:
                sd = forecast.get("margin_sd" if product == "home_margin" else "total_sd")
            mean = forecast.get(product)
            if sd is not None and mean is not None:
                entries.append((float(mean), float(sd), row[actual_name]))
        if not entries:
            products[product] = {"status": "UNAVAILABLE", "n": 0}
            continue
        intervals = []
        for level in INTERVAL_LEVELS:
            critical = float(ndtri((1+level)/2))
            covered = [abs(actual-mean) <= critical*sd for mean, sd, actual in entries]
            intervals.append({"nominal": level, "n": len(entries), "covered": int(sum(covered)),
                              "empirical_coverage": float(np.mean(covered)),
                              "mean_width": float(np.mean([2*critical*sd for _, sd, _ in entries]))})
        residuals = np.asarray([(actual-mean)/sd for mean, sd, actual in entries])
        products[product] = {"status": "AVAILABLE_CONTINUOUS_DIAGNOSTIC", "n": len(entries),
            "crps": float(np.mean([normal_crps(mean, sd, actual) for mean, sd, actual in entries])),
            "standardized_residual_mean": float(residuals.mean()),
            "standardized_residual_sd": float(residuals.std()), "intervals": intervals}
    return {"scope": "candidate continuous distribution; not exact integer score/push/OT settlement",
            "baseline_comparison": "UNAVAILABLE_ORIGINAL_CONTROL_HAS_NO_JOINT_DISTRIBUTION",
            "products": products, "exact_ats_validation": False}


def analyze(rows, population, excluded, *, league, discovery_ids=(), bootstrap_count=2000, seed=2302026):
    clean, _ = _rows(rows)
    _population(population, clean, excluded, discovery_ids)
    score = evaluate(rows, bootstrap_count=bootstrap_count, seed=seed)
    return {"schema": "efficiency-selection-diagnostics.v1", "league": league,
        "scope": "RETROSPECTIVE_RECONSTRUCTED_DIAGNOSTIC", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_population": len(population), "n_common_forecasts": len(clean), "n_excluded": len(excluded),
        "forecast_metrics": score,
        "probability_quality": {arm: probability_diagnostics(clean, arm) for arm in ("baseline", "challenger")},
        "selectors": {arm: fixed_grid_curve(clean, population, arm, bootstrap_count=bootstrap_count, seed=seed) for arm in ("baseline", "challenger")},
        "operational_eligibility": operational_gate_report(clean, population, league, bootstrap_count=bootstrap_count, seed=seed),
        "joint_distribution": joint_diagnostics(rows, league=league),
        "ats_selector": {"status": "BLOCKED", "dependency": "authentic historical market targets and exact discrete settlement distributions"},
        "best_selector_threshold": None, "confirmation_claim": False, "promotion": False,
        "publication_allowed": False, "wagering_authority": "OFF"}
