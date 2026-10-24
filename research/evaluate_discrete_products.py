"""Paired, contract-matched diagnostic scoring across seven sports.

No registration or canonical grading writes. Zero-probability outcomes are
reported, never silently clipped. Alternative lines are clustered by game.
"""
from collections import defaultdict
import math
import numpy as np
from models.common.discrete_research import (STATES, digest, finite, identity,
                                            outcome, price, score, stamp, validate, source_hash)


def _mean(values):
    return float(np.mean(values)) if values and all(v is not None for v in values) else None


def _score_row(row):
    d = row["distribution"]; validate(d)
    c = row["contract"]
    cutoff = d["provenance"]["cutoff"]
    if not stamp(cutoff) < stamp(row["start_time_utc"]) <= stamp(row["result_available_at"]):
        raise ValueError("EVALUATION_CHRONOLOGY_INVALID")
    source_hash(row["result_source_sha256"])
    identity(row["block_id"], "BLOCK_ID")
    y = outcome(row["observed"], league=d["league"], product=d["product"], settlement=d["settlement"],
                line=c["line"], side=c["side"])
    probabilities = price(d, c["line"], c["side"])
    brier = sum((probabilities[k] - int(k == y)) ** 2 for k in STATES)
    loss = -math.log(probabilities[y]) if probabilities[y] > 0 else None
    result = {"brier_category_sum": brier, "log_loss": loss, "outcome": y,
              "distribution_crps": score(d, row["observed"])["crps"],
              "probabilities": probabilities, "market_brier_conditional": None,
              "model_brier_conditional": None, "flat_stake_return": None}
    if c.get("quote"):
        q = c["quote"]
        source_hash(q["source_sha256"]); identity(q["book"], "BOOK")
        if q["event_id"] != d["provenance"]["event_id"]:
            raise ValueError("QUOTE_EVENT_MISMATCH")
        if stamp(q["observed_at_utc"]) > stamp(cutoff) or stamp(q["retrieved_at_utc"]) > stamp(cutoff):
            raise ValueError("FUTURE_QUOTE")
        if q["line"] != c["line"] or q["side"] != c["side"] or q["settlement"] != d["settlement"]:
            raise ValueError("QUOTE_CONTRACT_MISMATCH")
        a, b = finite(q["decimal_odds"]), finite(q["opposing_decimal_odds"])
        if min(a, b) <= 1:
            raise ValueError("DECIMAL_ODDS_INVALID")
        result["flat_stake_return"] = {"win": a-1, "half_win": (a-1)/2, "push": 0., "half_loss": -.5, "loss": -1.}[y]
        # Normalized opposing prices target the non-push event. Quarter-line
        # payoffs do not identify a single binary probability; do not invent one.
        if c["line"] * 2 == round(c["line"] * 2) and y != "push":
            market = (1/a) / (1/a + 1/b)
            den = probabilities["win"] + probabilities["loss"]
            if den > 0:
                result["model_brier_conditional"] = (probabilities["win"]/den-int(y == "win"))**2
            result["market_brier_conditional"] = (market-int(y == "win"))**2
    return result


def evaluate(rows, *, baseline_id, challenger_id, bootstrap=2000, seed=7):
    if baseline_id == challenger_id:
        raise ValueError("DISTINCT_MODELS_REQUIRED")
    if isinstance(bootstrap, bool) or not isinstance(bootstrap, int) or not 100 <= bootstrap <= 10000:
        raise ValueError("BOOTSTRAP_COUNT_INVALID")
    by_model = {baseline_id: {}, challenger_id: {}}
    universe = None
    event_blocks = {}
    for r in rows:
        d = r["distribution"]; mid = d["model_id"]
        if mid not in by_model:
            raise ValueError("UNDECLARED_MODEL")
        this_scope = tuple(d[k] for k in ("league", "product", "settlement"))
        if universe is not None and universe != this_scope:
            raise ValueError("SEPARATE_LEAGUE_PRODUCT_REPORTS_REQUIRED")
        universe = this_scope
        eid = d["provenance"]["event_id"]
        key = (eid, stamp(d["provenance"]["cutoff"]).isoformat(), digest(r["contract"]))
        if key in by_model[mid]:
            raise ValueError("DUPLICATE_EVENT_CONTRACT_MODEL")
        scored = _score_row(r)
        if eid in event_blocks and event_blocks[eid] != r["block_id"]:
            raise ValueError("EVENT_BLOCK_MISMATCH")
        event_blocks[eid] = r["block_id"]
        by_model[mid][key] = (r, scored)
    common = sorted(set(by_model[baseline_id]) & set(by_model[challenger_id]))
    if not common:
        raise ValueError("NO_MATCHED_CONTRACTS")
    for key in common:
        a, b = by_model[baseline_id][key][0], by_model[challenger_id][key][0]
        if any(a[k] != b[k] for k in ("observed", "result_source_sha256", "start_time_utc", "block_id")):
            raise ValueError("RESULT_BINDING_MISMATCH")
    summaries = {}
    for mid in by_model:
        s = [by_model[mid][k][1] for k in common]
        counts = {k: sum(r["outcome"] == k for r in s) for k in STATES}
        # Calibration of full-win events, with denominators visible; quarter-line
        # half wins remain separate outcomes rather than being counted as wins.
        reliability = []
        for lo in np.arange(0., 1., .1):
            group = [r for r in s if lo <= r["probabilities"]["win"] < lo+.1+1e-12 and
                     min(9, int(r["probabilities"]["win"]*10)) == int(round(lo*10))]
            if group:
                reliability.append({"lower": round(float(lo), 1), "n": len(group),
                                    "mean_probability": _mean([r["probabilities"]["win"] for r in group]),
                                    "observed_full_win_rate": _mean([int(r["outcome"] == "win") for r in group])})
        summaries[mid] = {"contract_n": len(s), "settlements": counts,
                          "brier_category_sum": _mean([r["brier_category_sum"] for r in s]),
                          "log_loss": _mean([r["log_loss"] for r in s]),
                          "zero_probability_outcomes": sum(r["log_loss"] is None for r in s),
                          "distribution_crps": _mean([r["distribution_crps"] for r in s]),
                          "market_nonpush_n": sum(r["market_brier_conditional"] is not None for r in s),
                          "model_conditional_brier": _mean([r["model_brier_conditional"] for r in s if r["market_brier_conditional"] is not None]),
                          "market_conditional_brier": _mean([r["market_brier_conditional"] for r in s if r["market_brier_conditional"] is not None]),
                          "quoted_contract_n": sum(r["flat_stake_return"] is not None for r in s),
                          "mean_flat_stake_return": _mean([r["flat_stake_return"] for r in s if r["flat_stake_return"] is not None]),
                          "full_win_reliability_descriptive": reliability}
    rng = np.random.Generator(np.random.PCG64(seed)); paired = {}
    for metric in ("brier_category_sum", "log_loss", "distribution_crps"):
        games = defaultdict(list)
        for key in common:
            a, b = by_model[baseline_id][key][1][metric], by_model[challenger_id][key][1][metric]
            games[key[0]].append(None if a is None or b is None else b-a)
        if any(any(v is None for v in values) for values in games.values()):
            paired[metric] = {"delta": None, "ci95": None, "reason": "ZERO_PROBABILITY_OUTCOME"}
            continue
        game_values = {eid: float(np.mean(v)) for eid, v in games.items()}
        blocks = defaultdict(list)
        for eid, v in game_values.items():
            blocks[event_blocks[eid]].append(v)
        groups = list(blocks.values()); draws = []
        if len(groups) >= 5:
            for _ in range(bootstrap):
                chosen = rng.integers(0, len(groups), len(groups))
                draws.append(float(np.mean([v for i in chosen for v in groups[i]])))
        paired[metric] = {"delta": float(np.mean(list(game_values.values()))),
                          "ci95": np.quantile(draws, [.025, .975]).tolist() if draws else None,
                          "block_n": len(groups), "game_n": len(games),
                          "reason": None if draws else "INSUFFICIENT_BLOCKS_FOR_INTERVAL"}
    return {"schema": "sports.paired_distribution_evaluation.research.v1", "scope": universe,
            "input_sha256": digest(rows), "baseline_id": baseline_id, "challenger_id": challenger_id,
            "matched_contract_n": len(common), "matched_game_n": len({k[0] for k in common}),
            "unmatched_contract_n": {mid: len(v)-len(common) for mid, v in by_model.items()},
            "summaries": summaries, "paired_challenger_minus_baseline": paired,
            "bootstrap": {"count": bootstrap, "seed": seed, "unit": "GAME_MEAN_WITHIN_DECLARED_TIME_BLOCK"},
            "limitations": ["CALLER_PROVENANCE_NOT_INDEPENDENTLY_ATTESTED", "NOT_CANONICAL_GRADING",
                            "RELIABILITY_BINS_DESCRIPTIVE_NOT_PROMOTION", "NO_MULTIPLE_TESTING_ADJUSTMENT",
                            "NO_AUTOMATIC_PROMOTION"],
            "predictive_validation": "NOT_ESTABLISHED_BY_THIS_REPORT", "action_authority": False}
