"""Read-only selection evaluation with explicit population and settlement rules.

Reports are descriptive evidence, never qualification or publication authority.
The primary accuracy objective is unconditional WIN: PUSH and VOID are not wins;
decisive-only accuracy is a separately labelled diagnostic. Bootstrap intervals
assume the supplied slate blocks are independent and do not repair drift.
"""
from __future__ import annotations

import math
import random
import statistics
from collections import Counter, defaultdict
from typing import Mapping, Sequence

from research.validation_registry import content_id


class EvaluationError(ValueError):
    pass


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EvaluationError(f"{name} must be finite")
    return float(value)


def _positive_int(value, name):
    if type(value) is not int or value <= 0:
        raise EvaluationError(f"{name} must be a positive integer")
    return value


def _prob(value, name):
    if value is None:
        return None
    value = _finite(value, name)
    if not 0 <= value <= 1:
        raise EvaluationError(f"{name} outside [0,1]")
    return value


def _id(row, key):
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise EvaluationError(f"missing {key}")
    return value


def _quantile(values, q):
    values = sorted(values)
    x = (len(values) - 1) * q
    lo, hi = math.floor(x), math.ceil(x)
    return values[lo] + (values[hi] - values[lo]) * (x - lo)


def paired_block_comparison(records: Sequence[Mapping], *, samples=2000, seed=0, confidence=.95):
    """Paired candidate-minus-control losses; resample whole supplied blocks.

    Each input row is one event with event_id, block_id, candidate_loss and
    control_loss. Pairing must already refer to the exact same settlement target.
    Fewer than two blocks emits no uncertainty interval or significance claim.
    """
    _positive_int(samples, "samples")
    if type(seed) is not int:
        raise EvaluationError("seed must be an integer")
    confidence = _finite(confidence, "confidence")
    if not 0 < confidence < 1:
        raise EvaluationError("confidence outside (0,1)")
    blocks, seen = defaultdict(list), set()
    for row in records:
        event_id, block = _id(row, "event_id"), _id(row, "block_id")
        if event_id in seen:
            raise EvaluationError("duplicate paired event")
        seen.add(event_id)
        blocks[block].append(_finite(row.get("candidate_loss"), "candidate_loss") -
                             _finite(row.get("control_loss"), "control_loss"))
    keys = sorted(blocks)
    values = [d for key in keys for d in blocks[key]]
    result = {"n_events": len(values), "n_blocks": len(keys),
              "mean_delta": statistics.mean(values) if values else None,
              "confidence": confidence, "ci_lower": None, "ci_upper": None,
              "method": "percentile_whole_block_bootstrap", "seed": seed,
              "samples": samples, "assumption": "independent supplied blocks; paired events within blocks"}
    if len(keys) < 2:
        result["status"] = "INSUFFICIENT_BLOCKS"
        return result
    rng, means = random.Random(seed), []
    for _ in range(samples):
        sampled = [d for key in rng.choices(keys, k=len(keys)) for d in blocks[key]]
        means.append(statistics.mean(sampled))
    tail = (1 - confidence) / 2
    result.update(status="AVAILABLE", ci_lower=_quantile(means, tail), ci_upper=_quantile(means, 1-tail))
    return result


def _scores(rows, key):
    pairs = [(r[key], int(r["outcome"] == "WIN")) for r in rows if r[key] is not None]
    losses = [-math.log(p if y else 1-p) if (p if y else 1-p) > 0 else math.inf for p, y in pairs]
    infinite = sum(not math.isfinite(x) for x in losses)
    return {"n": len(pairs), "brier": statistics.mean((p-y)**2 for p, y in pairs) if pairs else None,
            "log_loss": statistics.mean(losses) if losses and not infinite else None,
            "infinite_log_loss_count": infinite,
            "brier_convention": "binary_single_class_mean", "probability_basis": "unconditional_win"}


def _settlement(rows):
    counts = Counter(r["outcome"] for r in rows)
    n = counts["WIN"] + counts["LOSS"] + counts["PUSH"] + counts["VOID"]
    decisive = counts["WIN"] + counts["LOSS"]
    return {"wins": counts["WIN"], "losses": counts["LOSS"], "pushes": counts["PUSH"], "voids": counts["VOID"],
            "n_settled": n, "unconditional_win_accuracy": counts["WIN"]/n if n else None,
            "non_win_risk": 1-counts["WIN"]/n if n else None,
            "decisive_only_accuracy_diagnostic": counts["WIN"]/decisive if decisive else None}


def evaluate_decisions(rows: Sequence[Mapping], *, population: Sequence[Mapping], evidence_scope: str,
                       bootstrap_samples=2000, seed=0):
    """Evaluate one frozen procedure/configuration and target family.

    population externally declares every opportunity, including blocked rows.
    Each population row has event_id, target_id and slate_id; a corresponding
    decision row must exist. Different targets/procedures require separate calls.
    The upstream caller must bind these rows to immutable pre-event receipts;
    this function cannot authenticate a caller-supplied outcome or timestamp.
    """
    if evidence_scope not in {"DISCOVERY", "SHADOW", "CONFIRMATION"}:
        raise EvaluationError("explicit evidence_scope required")
    universe = {}
    for item in population:
        event = _id(item, "event_id")
        if event in universe:
            raise EvaluationError("duplicate population event")
        universe[event] = (_id(item, "target_id"), _id(item, "slate_id"))
    decisions, seen, identity = [], set(), None
    for item in rows:
        row = dict(item)
        event = _id(row, "event_id")
        if "control_procedure_id" not in row:
            raise EvaluationError("explicit control_procedure_id required (null if absent)")
        binding = (_id(row, "procedure_id"), _id(row, "selector_config_id"), row["control_procedure_id"], _id(row, "target_family_id"))
        if any(not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
               for value in binding if value is not None):
            raise EvaluationError("procedure/config/control/family identity must be SHA256")
        if identity is not None and identity != binding:
            raise EvaluationError("mixed procedure/config/control/target-family identities")
        identity = binding
        if event in seen:
            raise EvaluationError("duplicate decision event")
        seen.add(event)
        if event not in universe or universe[event] != (_id(row, "target_id"), _id(row, "slate_id")):
            raise EvaluationError("decision outside exact population/target/slate")
        if row.get("decision_class") not in {"BLOCKED", "ELIGIBLE_NOT_SELECTED", "SHADOW_SELECTED"}:
            raise EvaluationError("unsupported decision_class")
        if row.get("outcome") not in {"WIN", "LOSS", "PUSH", "VOID", "LIVE", "MISSING"}:
            raise EvaluationError("unsupported outcome")
        for key in ("raw_probability", "control_probability"):
            if key not in row:
                raise EvaluationError(f"missing {key}")
            row[key] = _prob(row[key], key)
        if row["decision_class"] == "SHADOW_SELECTED" and row["raw_probability"] is None:
            raise EvaluationError("selected row lacks probability")
        if row["control_probability"] is not None:
            if row["control_procedure_id"] is None:
                raise EvaluationError("control probability lacks procedure identity")
            if row.get("control_target_id") != row["target_id"]:
                raise EvaluationError("control target mismatch")
            if row.get("control_predicted_outcome") not in {"WIN", "LOSS"}:
                raise EvaluationError("explicit control direction required")
        decisions.append(row)
    if seen != set(universe):
        raise EvaluationError("missing population decisions (including blocked)")
    decisions.sort(key=lambda r: r["event_id"])
    selected = [r for r in decisions if r["decision_class"] == "SHADOW_SELECTED"]
    settled = [r for r in decisions if r["outcome"] in {"WIN", "LOSS", "PUSH", "VOID"}]
    selected_settled = [r for r in selected if r["outcome"] in {"WIN", "LOSS", "PUSH", "VOID"}]
    n, eligible = len(decisions), sum(r["decision_class"] != "BLOCKED" for r in decisions)
    report = {"schema_version": "research_selection_evaluation.v1", "evidence_scope": evidence_scope,
              "qualification_granted": False, "publication_allowed": False,
              "objective": "unconditional_win", "push_convention": "push_is_non_win; decisive_only_diagnostic_separate",
              "void_convention": "void_is_resolved_non_win; refunds_are_not_accuracy_wins",
              "procedure_id": identity[0] if identity else None, "selector_config_id": identity[1] if identity else None,
              "control_procedure_id": identity[2] if identity else None, "target_family_id": identity[3] if identity else None,
              "population_id": content_id(sorted([dict(r) for r in population], key=lambda r: r["event_id"])),
              "decision_dataset_id": content_id(decisions),
              "n_events": n, "n_slates": len({r["slate_id"] for r in decisions}), "n_eligible": eligible,
              "n_blocked": n-eligible, "n_selected": len(selected),
              "total_coverage": len(selected)/n if n else None,
              "eligible_coverage": len(selected)/eligible if eligible else None,
              "blocked_rate": (n-eligible)/n if n else None,
              "outcome_counts": dict(sorted(Counter(r["outcome"] for r in decisions).items())),
              "decision_class_counts": dict(sorted(Counter(r["decision_class"] for r in decisions).items())),
              "selected_settlement": _settlement(selected_settled),
              "selected_unsettled": len(selected)-len(selected_settled),
              "full_slate_raw_forecast_scores": _scores(settled, "raw_probability"),
              "selected_forecast_scores": _scores(selected_settled, "raw_probability")}
    for scope, subset in (("full_slate", settled), ("selected", selected_settled)):
        paired = [r for r in subset if r["raw_probability"] is not None and r["control_probability"] is not None]
        comparison = [{"event_id": r["event_id"], "block_id": r["slate_id"],
                       "candidate_loss": (r["raw_probability"]-int(r["outcome"] == "WIN"))**2,
                       "control_loss": (r["control_probability"]-int(r["outcome"] == "WIN"))**2} for r in paired]
        report[scope+"_same_event_control"] = {
            "n": len(paired), "unpaired_settled_count": len(subset)-len(paired),
            "candidate_scores": _scores(paired, "raw_probability"),
            "control_scores": _scores(paired, "control_probability"),
            "control_unconditional_win_accuracy": statistics.mean(r["outcome"] == r["control_predicted_outcome"] for r in paired) if paired else None,
            "paired_brier": paired_block_comparison(comparison, samples=bootstrap_samples, seed=seed)}
    # A descriptive curve only; operational decisions above are never refitted.
    ranked = sorted([r for r in decisions if r["decision_class"] != "BLOCKED" and r["raw_probability"] is not None],
                    key=lambda r: (-r["raw_probability"], r["event_id"]))
    curve = []
    for i, row in enumerate(ranked, 1):
        if i < len(ranked) and ranked[i]["raw_probability"] == row["raw_probability"]:
            continue  # Never select a favorable subset inside a tied threshold.
        prefix = ranked[:i]
        finished = [r for r in prefix if r["outcome"] in {"WIN", "LOSS", "PUSH", "VOID"}]
        curve.append({"threshold": row["raw_probability"], "n_selected": i,
                      "total_coverage": i/n if n else None, "eligible_coverage": i/eligible if eligible else None,
                      **_settlement(finished)})
    report["risk_coverage_diagnostic_only"] = curve
    return report


def holm_adjust(p_values: Mapping[str, float], *, alpha=.05, total_trials=None):
    """Holm control including inspected but unreported trials in family size.

    Unreported p-values are conservatively treated as one. The caller must supply
    a complete inspected-configuration count from the independently anchored log.
    """
    alpha = _finite(alpha, "alpha")
    if not 0 < alpha < 1:
        raise EvaluationError("alpha outside (0,1)")
    if total_trials is None:
        raise EvaluationError("explicit inspected total_trials required")
    count = total_trials
    if type(count) is not int or count < len(p_values) or count < 0:
        raise EvaluationError("total_trials cannot omit inspected tests")
    items = []
    for name, value in p_values.items():
        if not isinstance(name, str) or not name:
            raise EvaluationError("test identity required")
        p = _prob(value, name)
        if p is None:
            raise EvaluationError("missing p value")
        items.append((p, name))
    adjusted, previous = {}, 0.0
    for index, (p, name) in enumerate(sorted(items)):
        previous = max(previous, min(1.0, (count-index)*p))
        adjusted[name] = {"p_value": p, "adjusted_p_value": previous, "reject": previous <= alpha}
    return {"method": "Holm", "alpha": alpha, "inspected_trials": count,
            "unreported_trials": count-len(items), "tests": adjusted}


def power_curve(sample_sizes: Sequence[int], *, minimum_useful_improvement: float,
                paired_loss_sd: float, design_effect: float, alpha: float,
                total_trials: int, target_power: float):
    """Planning approximation for a one-sided paired loss improvement test.

    design_effect is a declared dependence/ESS assumption, not estimated here.
    Bonferroni alpha is conservative for planning Holm-controlled tests. These
    normal-approximation curves are not a promotion test or observed posthoc power.
    """
    effect = _finite(minimum_useful_improvement, "minimum_useful_improvement")
    sd = _finite(paired_loss_sd, "paired_loss_sd")
    dependence = _finite(design_effect, "design_effect")
    alpha, target = _finite(alpha, "alpha"), _finite(target_power, "target_power")
    trials = _positive_int(total_trials, "total_trials")
    if effect <= 0 or sd <= 0 or dependence < 1 or not 0 < alpha < 1 or not .5 < target < 1:
        raise EvaluationError("invalid declared planning assumptions")
    normal = statistics.NormalDist()
    adjusted_alpha = alpha/trials
    if 1-adjusted_alpha == 1:
        raise EvaluationError("multiplicity too large for numeric precision")
    z = normal.inv_cdf(1-adjusted_alpha)
    required = math.ceil(((z+normal.inv_cdf(target))*sd/effect)**2*dependence)
    curve = []
    for n in sample_sizes:
        _positive_int(n, "sample size")
        ess = n/dependence
        curve.append({"n_events": n, "effective_sample_size": ess,
                      "power": normal.cdf(effect*math.sqrt(ess)/sd-z)})
    return {"method": "one_sided_normal_paired_loss_planning", "minimum_useful_improvement": effect,
            "paired_loss_sd": sd, "design_effect": dependence, "alpha": alpha,
            "inspected_trials": trials, "planning_alpha": adjusted_alpha,
            "target_power": target, "required_events_approximation": required,
            "curve": curve, "qualification_granted": False}
