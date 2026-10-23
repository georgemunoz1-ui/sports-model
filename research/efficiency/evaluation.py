"""Paired, read-only forecast evaluation for the independent efficiency trials.

Rows are exact events with home-oriented forecasts and final-score outcomes.
The caller owns the complete population census and source/forecast provenance;
this module validates the supplied pairs, but does not authenticate sports data.
Historical metrics and block intervals never confer promotion or wagering rights.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from numbers import Real

import numpy as np


class EvaluationError(ValueError):
    """A purported same-event comparison violates its declared contract."""


def _number(value, name, *, optional=False):
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise EvaluationError("FINITE_NUMBER_REQUIRED:" + name)
    return float(value)


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError("NONEMPTY_IDENTIFIER_REQUIRED:" + name)
    return value


def _timestamp(value, name):
    if not isinstance(value, str):
        raise EvaluationError("TIMESTAMP_REQUIRED:" + name)
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvaluationError("INVALID_TIMESTAMP:" + name) from exc
    if stamp.tzinfo is None:
        raise EvaluationError("TIMEZONE_REQUIRED:" + name)
    return stamp.astimezone(timezone.utc)


def _forecast(value, name, row):
    if not isinstance(value, dict):
        raise EvaluationError("FORECAST_OBJECT_REQUIRED:" + name)
    for key in ("orientation", "probability_orientation", "margin_orientation"):
        if value.get(key, "home") != "home":
            raise EvaluationError("HOME_ORIENTATION_REQUIRED:" + name + "." + key)
    if value.get("event_id", row["event_id"]) != row["event_id"]:
        raise EvaluationError("FORECAST_EVENT_MISMATCH:" + name)
    result = {}
    for key in ("p_home", "home_margin", "total"):
        result[key] = _number(value.get(key), name + "." + key, optional=True)
    if result["p_home"] is not None and not 0 <= result["p_home"] <= 1:
        raise EvaluationError("PROBABILITY_OUT_OF_RANGE:" + name)
    if result["total"] is not None and result["total"] < 0:
        raise EvaluationError("NEGATIVE_FORECAST_TOTAL:" + name)
    # Independent winner, margin and total heads need not imply a coherent score
    # distribution. Never reject an opposite p/mean sign merely for disagreement.
    for key in ("model_id", "stage_id", "procedure_id", "config_sha256"):
        result[key] = None if value.get(key) is None else _text(value[key], name + "." + key)
    cutoff = value.get("forecast_cutoff_utc", row.get("forecast_cutoff_utc"))
    if cutoff is not None:
        at = _timestamp(cutoff, "forecast_cutoff_utc")
        if at >= row["_start"]:
            raise EvaluationError("POST_START_FORECAST:" + name)
        for key in ("training_max_available_at_utc", "feature_max_available_at_utc"):
            observed = value.get(key, row.get(key))
            if observed is not None and _timestamp(observed, key) > at:
                raise EvaluationError("FUTURE_INPUT:" + name + "." + key)
    return result


def _rows(rows):
    clean, seen, block_seasons = [], set(), {}
    identities = {arm: {key: set() for key in ("model_id", "stage_id", "procedure_id", "config_sha256")}
                  for arm in ("baseline", "challenger")}
    for original in rows:
        if not isinstance(original, dict):
            raise EvaluationError("ROW_OBJECT_REQUIRED")
        row = dict(original)
        event_id = _text(row.get("event_id"), "event_id")
        if event_id in seen:
            raise EvaluationError("DUPLICATE_EVENT:" + event_id)
        seen.add(event_id)
        season = row.get("season")
        if type(season) is not int:
            raise EvaluationError("INTEGER_SEASON_REQUIRED")
        block = _text(row.get("block_id"), "block_id")
        if block in block_seasons and block_seasons[block] != season:
            raise EvaluationError("BLOCK_SPANS_SEASONS:" + block)
        block_seasons[block] = season
        row["_start"] = _timestamp(row.get("start_time_utc"), "start_time_utc")
        y = row.get("actual_home_win")
        if type(y) is not int or y not in (0, 1):
            raise EvaluationError("BINARY_INTEGER_OUTCOME_REQUIRED")
        margin = _number(row.get("actual_home_margin"), "actual_home_margin")
        total = _number(row.get("actual_total"), "actual_total")
        if not margin.is_integer() or not total.is_integer():
            raise EvaluationError("INTEGER_FINAL_SCORE_REQUIRED")
        if margin == 0 or int(margin > 0) != y:
            raise EvaluationError("HOME_OUTCOME_MARGIN_CONFLICT")
        if total < abs(margin) or (int(total) - int(margin)) % 2:
            raise EvaluationError("FINAL_SCORE_TOTAL_MARGIN_CONFLICT")
        row.update(actual_home_margin=margin, actual_total=total)
        for arm in ("baseline", "challenger"):
            row[arm] = _forecast(row.get(arm), arm, row)
            for key in identities[arm]:
                identities[arm][key].add(row[arm][key])
        clean.append(row)
    for arm, keys in identities.items():
        for key, values in keys.items():
            if len(values) > 1:
                raise EvaluationError("MIXED_ARM_IDENTITY:" + arm + "." + key)
    clean.sort(key=lambda row: (row["_start"], row["event_id"]))
    return clean, {arm: {key: next(iter(values)) if values else None for key, values in keys.items()}
                   for arm, keys in identities.items()}


def _bootstrap_delta(rows, baseline, challenger, *, bootstrap_count, seed, root=False):
    """Resample supplied whole blocks, retaining paired events and event weights.

    root=True calculates the difference of RMSEs in every resample, not the root
    of the difference in MSEs. Inputs are per-event losses (squared for RMSE).
    """
    blocks = defaultdict(list)
    for i, row in enumerate(rows):
        blocks[row["block_id"]].append(i)
    result = {
        "estimate": None, "ci_lower": None, "ci_upper": None,
        "n_events": len(rows), "n_blocks": len(blocks),
        "status": "NO_PAIRED_EVENTS", "confidence": 0.95,
        "method": "paired_whole_chronological_block_percentile_bootstrap",
        "bootstrap_count": bootstrap_count, "seed": seed,
        "assumption": "Supplied season-week/ISO-week blocks are independent sampling units; temporal dependence between blocks is not repaired.",
    }
    if not rows:
        return result
    b, c = np.asarray(baseline, dtype=float), np.asarray(challenger, dtype=float)
    if not np.isfinite(b).all() or not np.isfinite(c).all():
        result.update(status="UNAVAILABLE_INFINITE_LOG_LOSS",
                      baseline_nonfinite_count=int((~np.isfinite(b)).sum()),
                      challenger_nonfinite_count=int((~np.isfinite(c)).sum()))
        return result
    bmean, cmean = float(np.mean(b)), float(np.mean(c))
    result["estimate"] = math.sqrt(cmean) - math.sqrt(bmean) if root else cmean - bmean
    if len(blocks) < 2:
        result["status"] = "INSUFFICIENT_BLOCKS"
        return result
    # Order blocks by earliest event; rows were already put into UTC order.
    groups = list(blocks.values())
    counts = np.asarray([len(g) for g in groups])
    sums_b = np.asarray([b[g].sum() for g in groups])
    sums_c = np.asarray([c[g].sum() for g in groups])
    rng = np.random.default_rng(seed)
    # Limit temporary memory for a long historical population.
    samples = []
    for offset in range(0, bootstrap_count, 128):
        sampled = rng.integers(0, len(groups), size=(min(128, bootstrap_count-offset), len(groups)))
        n = counts[sampled].sum(axis=1)
        bm = sums_b[sampled].sum(axis=1) / n
        cm = sums_c[sampled].sum(axis=1) / n
        samples.extend((np.sqrt(cm)-np.sqrt(bm) if root else cm-bm).tolist())
    result.update(status="AVAILABLE", ci_lower=float(np.quantile(samples, 0.025)),
                  ci_upper=float(np.quantile(samples, 0.975)))
    return result


def _product(rows, product, *, bootstrap_count, seed):
    key = {"winner": "p_home", "home_margin": "home_margin", "total": "total"}[product]
    paired, excluded = [], []
    for row in rows:
        absent = [arm for arm in ("baseline", "challenger") if row[arm][key] is None]
        if absent:
            excluded.append({"event_id": row["event_id"], "reasons": [arm.upper()+"_HEAD_UNAVAILABLE" for arm in absent]})
        else:
            paired.append(row)
    result = {"n_population": len(rows), "n_paired": len(paired), "n_excluded": len(excluded),
              "paired_event_ids": [row["event_id"] for row in paired],
              "excluded_event_ids": [row["event_id"] for row in excluded],
              "exclusions": excluded, "baseline": {}, "challenger": {}, "delta": {},
              "delta_orientation": "challenger_minus_baseline",
              "status": "AVAILABLE" if paired else "NO_PAIRED_EVENTS"}
    values = {"baseline": {}, "challenger": {}}
    for arm in values:
        if product == "winner":
            probabilities = [r[arm][key] for r in paired]
            truth = [r["actual_home_win"] for r in paired]
            values[arm]["brier"] = [(p-y)**2 for p, y in zip(probabilities, truth)]
            mass = [p if y else 1-p for p, y in zip(probabilities, truth)]
            values[arm]["log_loss"] = [-math.log(p) if p > 0 else math.inf for p in mass]
            values[arm]["accuracy"] = [float(int(p >= .5) == y) for p, y in zip(probabilities, truth)]
            for metric, vector in values[arm].items():
                result[arm][metric] = float(np.mean(vector)) if vector and all(math.isfinite(x) for x in vector) else None
            result[arm].update(infinite_log_loss_count=sum(not math.isfinite(x) for x in values[arm]["log_loss"]),
                               brier_convention="binary_single_class_mean", tie_probability_decision="home_at_p_0.5")
        else:
            target = "actual_home_margin" if product == "home_margin" else "actual_total"
            errors = [r[arm][key]-r[target] for r in paired]
            values[arm]["mae"] = [abs(e) for e in errors]
            values[arm]["rmse"] = [e*e for e in errors]
            result[arm] = {"mae": float(np.mean(values[arm]["mae"])) if errors else None,
                           "rmse": math.sqrt(float(np.mean(values[arm]["rmse"]))) if errors else None,
                           "bias_forecast_minus_actual": float(np.mean(errors)) if errors else None}
    for metric in values["baseline"]:
        result["delta"][metric] = _bootstrap_delta(
            paired, values["baseline"][metric], values["challenger"][metric],
            bootstrap_count=bootstrap_count, seed=seed, root=metric == "rmse")
        result["delta"][metric]["better_direction"] = "positive" if metric == "accuracy" else "negative"
    return result


def evaluate(rows, *, bootstrap_count=2000, seed=2302026):
    """Score one frozen challenger/control pair on exact home-oriented events.

    Each row requires event_id, integer season, block_id, start_time_utc,
    actual_home_win (integer 0/1), actual_home_margin, actual_total, and baseline
    and challenger dictionaries with p_home, home_margin and total (null denotes
    an unavailable head). Forecast dictionaries may include model/stage/procedure
    IDs, checked for arm consistency, and optional chronology fields. Unmatched
    products remain in the coverage census. Rows may arrive out of order.

    Intervals condition on the supplied fixed forecasts and observed sample;
    they exclude parameter-fitting uncertainty and candidate-selection effects.
    """
    if type(bootstrap_count) is not int or bootstrap_count < 1:
        raise EvaluationError("POSITIVE_BOOTSTRAP_COUNT_REQUIRED")
    if type(seed) is not int or seed < 0:
        raise EvaluationError("NONNEGATIVE_INTEGER_SEED_REQUIRED")
    clean, identities = _rows(rows)
    product_names = ("winner", "home_margin", "total")
    by_season = defaultdict(list)
    for row in clean:
        by_season[row["season"]].append(row)
    digest_rows = [{key: value for key, value in row.items() if key != "_start"} for row in clean]
    # Hash only the validated, numerically scored fields, not arbitrary caller
    # metadata that this module cannot certify.
    digest_rows = [{key: row[key] for key in ("event_id", "season", "block_id", "start_time_utc",
                   "actual_home_win", "actual_home_margin", "actual_total", "baseline", "challenger")}
                   for row in digest_rows]
    digest = hashlib.sha256(json.dumps(digest_rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {
        "schema": "efficiency-paired-evaluation.v1", "n_events": len(clean),
        "n_blocks": len({r["block_id"] for r in clean}),
        "population_scope": "All supplied exact-event rows; full source/acquisition population must be reported separately by runner.",
        "period": {"first_start_time_utc": clean[0]["_start"].isoformat() if clean else None,
                   "last_start_time_utc": clean[-1]["_start"].isoformat() if clean else None},
        "identities": identities, "scored_rows_sha256": digest,
        "products": {p: _product(clean, p, bootstrap_count=bootstrap_count, seed=seed) for p in product_names},
        "seasons": {str(s): {"n_events": len(group), "n_blocks": len({r["block_id"] for r in group}),
                    "products": {p: _product(group, p, bootstrap_count=bootstrap_count, seed=seed) for p in product_names}}
                    for s, group in sorted(by_season.items())},
        "historical_pit_authenticated": False, "provider_authenticity_proven": False,
        "uncertainty_limitations": ["Independent supplied blocks assumed", "No parameter-fitting uncertainty",
                                    "No correction for model/feature selection after inspecting prior outcomes"],
        "promotion": False, "publication_eligibility": "NOT_EVALUATED", "action_authority": False,
    }
