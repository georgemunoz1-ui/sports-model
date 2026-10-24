"""Strict, descriptive evaluation of retained discrete margin/total forecasts.

One row represents one model/event/cutoff, with optional ``contracts`` (or one
``contract``). Contract lines without quotes are diagnostic thresholds, never
historical market observations. Each sport/product/settlement/parent/information
set is evaluated separately. Retrospective chronology is not PIT attestation.

Example: python -m research.evaluate_margin_system --retained-directory DIR \
    --product margin --baseline-id ID --challenger-id ID --output NEW.json
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import gzip
import json
import math
from pathlib import Path

import numpy as np

from models.common import discrete_research as D

SCHEMA = "sports.margin_system_evaluation.research.v1"
INTERVAL_LEVELS = (.5, .8, .9, .95)


def _mean(values):
    return float(np.mean(values)) if values else None


def _log(probability):
    return -math.log(probability) if probability > 0 else None


def _log_summary(values):
    zero = sum(v is None for v in values)
    return {"mean": None if zero else _mean(values), "n": len(values),
            "zero_probability_outcomes": zero,
            "status": "INFINITE_ZERO_SUPPORT" if zero else
                      "AVAILABLE" if values else "NO_ROWS"}


def _reliability(pairs):
    bins = []
    for i in range(10):
        chosen = [(p, y) for p, y in pairs if min(9, int(p * 10)) == i]
        bins.append({"lower": i / 10, "upper": (i + 1) / 10,
                     "upper_inclusive": i == 9, "n": len(chosen),
                     "mean_probability": _mean([p for p, _ in chosen]),
                     "observed_rate": _mean([y for _, y in chosen])})
    return bins


def _binary(p, y):
    return {"brier": (p-y)**2, "log_loss": _log(p if y else 1-p)}


def _contract_identity(contract, distribution):
    """Optional descriptive metadata must agree with the scored target."""
    d = distribution
    expected = {"event_id": d["provenance"]["event_id"],
        **{k: d[k] for k in ("league", "product", "settlement")},
        "orientation": "HOME_MINUS_AWAY" if d["product"] == "margin" else "HOME_PLUS_AWAY",
        "line_orientation": "HOME_HANDICAP" if d["product"] == "margin" else "TOTAL_THRESHOLD"}
    if any(key in contract and contract[key] != value for key, value in expected.items()):
        raise ValueError("CONTRACT_TARGET_METADATA_MISMATCH")
    periods = {"REGULATION"} if d["settlement"] == "REGULATION" else {"FULL_GAME"}
    if d["settlement"] == "REGULATION_90_STOPPAGE":
        periods.add("REGULATION")
    if "period" in contract and contract["period"] not in periods:
        raise ValueError("CONTRACT_PERIOD_MISMATCH")


def score_row(row):
    """Validate bindings, then score one frozen distribution without clipping."""
    d = row["distribution"]
    x, p = D.validate(d)
    prov = d["provenance"]
    for name in ("event_id", "parent_model_id", "information_set"):
        D.identity(prov[name], name.upper())
    D.source_hash(prov["parent_forecast_sha256"])
    D.source_hash(row["result_source_sha256"])
    expected_orientation = "HOME_MINUS_AWAY" if d["product"] == "margin" else "HOME_PLUS_AWAY"
    if prov.get("orientation", expected_orientation) != expected_orientation:
        raise ValueError("DISTRIBUTION_ORIENTATION_MISMATCH")
    if not isinstance(prov["market_input"], bool):
        raise ValueError("MARKET_INPUT_ROLE_REQUIRED")
    cutoff, start, result = map(D.stamp, (prov["cutoff"], row["start_time_utc"],
                                        row["result_available_at"]))
    if not D.stamp(row["parent_fit_cutoff"]) <= cutoff < start <= result:
        raise ValueError("EVALUATION_CHRONOLOGY_INVALID")
    for name in ("distribution_fit_cutoff", "calibration_fit_cutoff"):
        if row.get(name) is not None and D.stamp(row[name]) > cutoff:
            raise ValueError("FUTURE_DISTRIBUTION_FIT")
    observed = D.finite(row["observed"])
    proper = D.score(d, observed)
    mean = float(np.dot(x, p))
    cdf = np.cumsum(p)
    intervals = {}
    for level in INTERVAL_LEVELS:
        alpha = (1-level)/2
        lo = int(x[min(np.searchsorted(cdf, alpha, side="left"), len(x)-1)])
        hi = int(x[min(np.searchsorted(cdf, 1-alpha, side="left"), len(x)-1)])
        intervals[str(level)] = {"lower": lo, "upper": hi,
                                 "covered": int(lo <= observed <= hi), "width": hi-lo}
    contracts = row.get("contracts", [])
    if "contract" in row:
        if contracts:
            raise ValueError("AMBIGUOUS_CONTRACT_FIELDS")
        contracts = [row["contract"]]
    scored_contracts = {}
    for contract in contracts:
        _contract_identity(contract, d)
        line, side = D.finite(contract["line"]), contract["side"]
        key = D.digest({"line": line, "side": side})
        if key in scored_contracts:
            raise ValueError("DUPLICATE_CONTRACT")
        probabilities = D.price(d, line, side)
        outcome = D.outcome(observed, league=d["league"], product=d["product"],
                            settlement=d["settlement"], line=line, side=side)
        role = contract.get("line_role", "DIAGNOSTIC_GRID")
        quote = contract.get("quote")
        if role not in {"DIAGNOSTIC_GRID", "OBSERVED_MARKET"}:
            raise ValueError("LINE_ROLE_INVALID")
        if role == "OBSERVED_MARKET" or quote is not None:
            if not quote:
                raise ValueError("OBSERVED_MARKET_REQUIRES_QUOTE")
            D.source_hash(quote["source_sha256"])
            D.identity(quote["book"], "BOOK")
            _contract_identity(quote, d)
            if not D.stamp(quote["observed_at_utc"]) <= D.stamp(quote["retrieved_at_utc"]) <= cutoff:
                raise ValueError("QUOTE_CHRONOLOGY_INVALID")
            if any(quote.get(k) != v for k, v in {
                "event_id": prov["event_id"], "settlement": d["settlement"],
                "line": line, "side": side}.items()):
                raise ValueError("QUOTE_CONTRACT_MISMATCH")
            role = "OBSERVED_MARKET"
        full_win, push = int(outcome == "win"), int(outcome == "push")
        scored_contracts[key] = {"line": line, "side": side, "line_role": role,
            "line_orientation": "HOME_HANDICAP" if d["product"] == "margin" else "TOTAL_THRESHOLD",
            "quote_sha256": D.digest(quote) if quote else None,
            "outcome": outcome, "probabilities": probabilities,
            "brier_category_sum": sum((probabilities[s]-int(outcome == s))**2 for s in D.STATES),
            "category_log_loss": _log(probabilities[outcome]),
            "cover": _binary(probabilities["win"], full_win),
            "push": _binary(probabilities["push"], push)}
    return {"mean": mean, "absolute_error": abs(mean-observed),
            "squared_error": (mean-observed)**2,
            "crps": proper["crps"], "distribution_log_loss": proper["log_loss"],
            "intervals": intervals, "contracts": scored_contracts}


def _scope(row):
    d, p = row["distribution"], row["distribution"]["provenance"]
    return tuple(d[k] for k in ("league", "product", "settlement")) + tuple(
        p[k] for k in ("parent_model_id", "information_set", "market_input"))


def _key(row):
    p = row["distribution"]["provenance"]
    return p["event_id"], D.stamp(p["cutoff"]).isoformat()


def _contract_summary(contracts):
    return {"n": len(contracts),
        "diagnostic_threshold_n": sum(c["line_role"] == "DIAGNOSTIC_GRID" for c in contracts),
        "observed_market_n": sum(c["line_role"] == "OBSERVED_MARKET" for c in contracts),
        "outcome_counts": {s: sum(c["outcome"] == s for c in contracts) for s in D.STATES},
        "category_brier_sum": _mean([c["brier_category_sum"] for c in contracts]),
        "category_log_loss": _log_summary([c["category_log_loss"] for c in contracts]),
        **{label: {"brier": _mean([c[metric_key]["brier"] for c in contracts]),
                   "log_loss": _log_summary([c[metric_key]["log_loss"] for c in contracts]),
                   "reliability": _reliability([(c["probabilities"][state], int(c["outcome"] == state))
                                                   for c in contracts])}
           for label, metric_key, state in (("cover_full_win", "cover", "win"), ("push", "push", "push"))}}


def _summary(records):
    rows, scores = [r for r, _ in records], [s for _, s in records]
    contracts = [c for s in scores for c in s["contracts"].values()]
    return {"forecast_n": len(rows), "unique_event_n": len({_key(r)[0] for r in rows}),
        "mean_mae": _mean([s["absolute_error"] for s in scores]),
        "mean_rmse": math.sqrt(_mean([s["squared_error"] for s in scores])) if scores else None,
        "crps": _mean([s["crps"] for s in scores]),
        "distribution_log_score": _log_summary([s["distribution_log_loss"] for s in scores]),
        "prediction_intervals": {str(level): {
            "n": len(scores), "coverage": _mean([s["intervals"][str(level)]["covered"] for s in scores]),
            "mean_width": _mean([s["intervals"][str(level)]["width"] for s in scores])}
            for level in INTERVAL_LEVELS},
        "contracts": _contract_summary(contracts),
        "historically_available_artifact_n": sum(r["distribution"]["provenance"].get(
            "artifact_existed_at_forecast_cutoff") is True for r in rows)}


def _block(start, unit):
    stamp = D.stamp(start)
    if unit == "day":
        return stamp.date().isoformat()
    year, week, _ = stamp.isocalendar()
    return f"{year:04d}-W{week:02d}"


def _bootstrap(metric_pairs, *, seed, draws, block_length, block_unit):
    """Moving contiguous time-block bootstrap; equal event weight within sample."""
    by_event = defaultdict(list)
    starts = {}
    for eid, start, a, b in metric_pairs:
        if eid in starts and starts[eid] != D.stamp(start):
            raise ValueError("EVENT_START_MISMATCH")
        starts[eid] = D.stamp(start)
        by_event[eid].append(None if a is None or b is None else b-a)
    if not by_event:
        return {"delta": None, "ci95": None, "event_n": 0, "status": "NO_MATCHED_CONTRACTS"}
    blocks = defaultdict(list)
    for eid, vals in by_event.items():
        if any(v is None for v in vals):
            return {"delta": None, "ci95": None, "event_n": len(by_event),
                    "status": "ZERO_SUPPORT_DELTA_UNDEFINED"}
        blocks[_block(starts[eid].isoformat(), block_unit)].append(float(np.mean(vals)))
    groups = [blocks[k] for k in sorted(blocks)]
    n = len(groups)
    result = {"delta": _mean([v for group in groups for v in group]),
              "ci95": None, "event_n": len(by_event), "time_block_n": n,
              "status": "INSUFFICIENT_TIME_BLOCKS"}
    if n < max(5, 2 * block_length):
        return result
    rng = np.random.Generator(np.random.PCG64(seed))
    sims = []
    for _ in range(draws):
        selected = []
        while len(selected) < n:
            first = int(rng.integers(0, n-block_length+1))
            selected.extend(range(first, first+block_length))
        sims.append(_mean([v for i in selected[:n] for v in groups[i]]))
    result.update(ci95=np.quantile(sims, [.025, .975]).tolist(), status="AVAILABLE")
    return result


def evaluate(rows, *, baseline_id=None, challenger_id=None, bootstrap=2000, seed=7,
             block_length=2, block_unit="week"):
    """Evaluate exactly one comparable scope, optionally with strict paired deltas."""
    rows = list(rows)
    if not rows:
        raise ValueError("ROWS_REQUIRED")
    if isinstance(bootstrap, bool) or not isinstance(bootstrap, int) or not 100 <= bootstrap <= 10000:
        raise ValueError("BOOTSTRAP_COUNT_INVALID")
    if isinstance(block_length, bool) or not isinstance(block_length, int) or block_length < 1:
        raise ValueError("BLOCK_LENGTH_INVALID")
    if block_unit not in {"day", "week"}:
        raise ValueError("BLOCK_UNIT_INVALID")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("SEED_INVALID")
    if bool(baseline_id) != bool(challenger_id) or baseline_id == challenger_id and baseline_id:
        raise ValueError("TWO_DISTINCT_MODELS_REQUIRED")
    scopes = {_scope(r) for r in rows}
    if len(scopes) != 1:
        raise ValueError("SEPARATE_LEAGUE_PRODUCT_SETTLEMENT_PARENT_INFORMATION_REPORTS_REQUIRED")
    by_model = defaultdict(dict)
    event_bindings = {}
    for r in rows:
        scored = score_row(r)
        mid, key = r["distribution"]["model_id"], _key(r)
        if key in by_model[mid]:
            raise ValueError("DUPLICATE_EVENT_CUTOFF_MODEL")
        binding = (r["observed"], r["result_source_sha256"], D.stamp(r["start_time_utc"]),
                   D.stamp(r["result_available_at"]))
        if key[0] in event_bindings and event_bindings[key[0]] != binding:
            raise ValueError("RESULT_BINDING_MISMATCH")
        event_bindings[key[0]] = binding
        by_model[mid][key] = (r, scored)
    output = {"schema": SCHEMA, "scope": list(next(iter(scopes))),
        "input_sha256": D.digest(rows), "input_rows": len(rows),
        "summaries_all_available": {mid: _summary(list(v.values())) for mid, v in sorted(by_model.items())},
        "paired": None, "action_authority": False, "promotion_authority": False,
        "canonical_grading_write": False,
        "limitations": ["STRUCTURAL_CHRONOLOGY_IS_NOT_POINT_IN_TIME_ATTESTATION",
            "NO_AUTOMATIC_PROMOTION", "NO_MULTIPLE_TESTING_ADJUSTMENT",
            "COVER_IS_FULL_WIN_HALF_WINS_REMAIN_SEPARATE", "NO_MARKET_SUPERIORITY_TEST"],
        "bootstrap": {"count": bootstrap, "seed": seed, "block_length": block_length,
                      "time_unit": block_unit, "method": "MOVING_CONTIGUOUS_OBSERVED_TIME_BLOCKS",
                      "weighting": "EQUAL_EVENT_MEANS"}}
    if not baseline_id:
        return output
    if baseline_id not in by_model or challenger_id not in by_model:
        raise ValueError("DECLARED_MODEL_MISSING")
    a, b = by_model[baseline_id], by_model[challenger_id]
    common = sorted(set(a) & set(b))
    metric_pairs = defaultdict(list)
    matched_contracts = 0
    contract_unmatched = {baseline_id: 0, challenger_id: 0}
    for key in common:
        ar, asc = a[key]; br, bsc = b[key]
        if ar["distribution"]["provenance"]["parent_forecast_sha256"] != br["distribution"]["provenance"]["parent_forecast_sha256"]:
            raise ValueError("PAIRED_PARENT_FORECAST_MISMATCH")
        if D.stamp(ar["parent_fit_cutoff"]) != D.stamp(br["parent_fit_cutoff"]):
            raise ValueError("PAIRED_PARENT_FIT_MISMATCH")
        for metric in ("absolute_error", "squared_error", "crps", "distribution_log_loss"):
            metric_pairs[metric].append((key[0], ar["start_time_utc"], asc[metric], bsc[metric]))
        ac, bc = asc["contracts"], bsc["contracts"]
        ck = set(ac) & set(bc)
        contract_unmatched[baseline_id] += len(set(ac)-ck)
        contract_unmatched[challenger_id] += len(set(bc)-ck)
        for ckey in ck:
            ca, cb = ac[ckey], bc[ckey]
            if (ca["line_role"], ca["quote_sha256"]) != (cb["line_role"], cb["quote_sha256"]):
                raise ValueError("PAIRED_CONTRACT_SOURCE_MISMATCH")
            matched_contracts += 1
            for metric in ("brier_category_sum", "category_log_loss"):
                metric_pairs[metric].append((key[0], ar["start_time_utc"], ca[metric], cb[metric]))
            for target in ("cover", "push"):
                for metric in ("brier", "log_loss"):
                    metric_pairs[target+"_"+metric].append((key[0], ar["start_time_utc"],
                                                           ca[target][metric], cb[target][metric]))
    unmatched = {mid: [{"event_id": k[0], "cutoff": k[1],
                      "reason": "CUTOFF_MISMATCH" if k[0] in {x[0] for x in other} else "MISSING_OTHER_MODEL"}
                     for k in sorted(set(values)-set(common))]
                 for mid, values, other in ((baseline_id, a, b), (challenger_id, b, a))}
    for mid, values in ((baseline_id, a), (challenger_id, b)):
        contract_unmatched[mid] += sum(len(values[k][1]["contracts"]) for k in set(values)-set(common))
    output["paired"] = {"baseline_id": baseline_id, "challenger_id": challenger_id,
        "matched_forecast_n": len(common), "matched_event_n": len({k[0] for k in common}),
        "matched_contract_n": matched_contracts, "unmatched_contract_n": contract_unmatched,
        "unmatched_forecasts": unmatched,
        "paired_coverage": {mid: len(common)/len(v) for mid, v in ((baseline_id, a), (challenger_id, b))},
        "summaries_matched": {mid: _summary([v[k] for k in common])
                              for mid, v in ((baseline_id, a), (challenger_id, b))},
        "deltas_challenger_minus_baseline": {metric: _bootstrap(pairs, seed=seed, draws=bootstrap,
             block_length=block_length, block_unit=block_unit) for metric, pairs in metric_pairs.items()},
        "status": "PAIRED_DIAGNOSTIC" if common else "NO_MATCHED_FORECASTS"}
    return output


def _read_json(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt") as handle:
        return json.load(handle)


def load_retained_cohort(directory, product="margin"):
    """Join retained frozen forecast rows to their explicit parent chronology.

    No lines are inferred and no distributions regenerated. Missing or conflicting
    cohort bindings fail. The returned rows remain retrospective research.
    """
    directory = Path(directory)
    cohort = _read_json(directory / f"{product}_cohort.json.gz")
    lookup = {}
    for row in cohort["evaluation"]:
        key = row["event_id"], D.stamp(row["forecast_cutoff"]).isoformat()
        if key in lookup:
            raise ValueError("DUPLICATE_COHORT_EVENT")
        lookup[key] = row
    result = []
    for arm in _read_json(directory / f"{product}_frozen_distributions.json.gz"):
        for row in arm:
            d, key = row["distribution"], _key(row)
            if key not in lookup:
                raise ValueError("MISSING_COHORT_BINDING")
            source = lookup[key]
            if any(source[k] != row[k] for k in ("observed", "result_source_sha256", "start_time_utc", "result_available_at")):
                raise ValueError("COHORT_RESULT_BINDING_MISMATCH")
            prov = d["provenance"]
            if source["forecast_sha256"] != prov["parent_forecast_sha256"] or source["parent_model_id"] != prov["parent_model_id"]:
                raise ValueError("COHORT_PARENT_BINDING_MISMATCH")
            result.append({**row, "parent_fit_cutoff": source["parent_fit_cutoff"],
                "source_capture_kind": source.get("source_capture_kind"),
                "historical_availability_proven": source.get("historical_availability_proven", False)})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--rows", type=Path, help="JSON array of distribution evaluation rows")
    source.add_argument("--retained-directory", type=Path)
    parser.add_argument("--product", choices=["margin", "total"], default="margin")
    parser.add_argument("--baseline-id")
    parser.add_argument("--challenger-id")
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--block-length", type=int, default=2)
    parser.add_argument("--block-unit", choices=["week", "day"], default="week")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    rows = _read_json(args.rows) if args.rows else load_retained_cohort(args.retained_directory, args.product)
    report = evaluate(rows, baseline_id=args.baseline_id, challenger_id=args.challenger_id,
        bootstrap=args.bootstrap, seed=args.seed, block_length=args.block_length, block_unit=args.block_unit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(report, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"status": "DESCRIPTIVE_RESEARCH_ONLY", "output": str(args.output),
                      "input_rows": len(rows), "report_sha256": D.digest(report)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
