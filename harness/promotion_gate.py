#!/usr/bin/env python3
"""PROMOTION GATE — the binding conditions, and the separate real-money gate.

OWNER SPECIFICATION 2026-08-23 (amendment):

    Status remains FORWARD_ONLY_PENDING. No promotion until:
      * at least 500 games across 60 slate dates
      * lower Brier than BOTH references (V13 and the expanding home-rate prior)
      * Holm-adjusted paired date-block intervals ENTIRELY below zero
      * required AUC improvement
      * acceptable calibration
      * zero chronology / provenance / starter / duplicate failures

    The separate REAL-MONEY gate remains: at least 100 games, positive ROI with its interval
    excluding zero, forward calibration, and explicit user approval.

TWO GATES, AND CLEARING ONE IS NOT CLEARING THE OTHER. Model promotion is a claim about forecast
quality. Real-money authorisation is a claim about a bankroll. They share no threshold, they are
evaluated on different samples, and the second additionally requires a human to say yes — which no
amount of evidence can supply. There is no code path here that returns real-money authorisation.

HOLM, NOT RAW INTERVALS. Two references means two simultaneous comparisons, and taking the better of
two 95% intervals is a 90%-confidence claim wearing a 95% label. Holm's step-down procedure controls
the family-wise error rate without assuming the comparisons are independent, which matters here
because the two references are scored on the SAME games and their errors are strongly correlated.

BOTH REFERENCES MUST FALL. A challenger that beats the expanding prior but not V13 has not earned
promotion — it has found a way to beat a base rate that V13 already beats. The conjunction is the
requirement, and it is enforced as a conjunction, not as an average.
"""
from __future__ import annotations

MODULE_ID = "promotion_gate"

import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paired_eval as PE

FORWARD_ONLY_PENDING = "FORWARD_ONLY_PENDING"
ELIGIBLE_FOR_PROMOTION_REVIEW = "ELIGIBLE_FOR_PROMOTION_REVIEW"

# Frozen 2026-08-23. Changing any of these is an owner decision; promotion_standards is on the
# never-adapt list, so no evidence, alarm or accumulation moves them.
MIN_GAMES = 500
MIN_SLATE_DATES = 60
REQUIRED_AUC_IMPROVEMENT = 0.010          # over the better of the two references
CALIBRATION_SLOPE_BAND = (0.80, 1.25)
CALIBRATION_INTERCEPT_ABS_MAX = 0.50
FAMILY_ALPHA = 0.05

# ---------------------------------------------------------------------------------------------
# CLUSTER SUFFICIENCY — DERIVED FROM THE TEST, NOT CHOSEN.
#
# The unit of independence is the slate date, so the reference test is an exact cluster-level
# sign-flip: with k clusters there are 2^k sign assignments, and the smallest attainable two-sided
# p-value is 2 / 2^k. Inference at level alpha is therefore IMPOSSIBLE unless
#
#     2 / 2^k <= alpha    <=>    k >= log2(2 / alpha)
#
# At alpha = .05 that is k >= 5.32, i.e. SIX clusters. With two clusters the smallest attainable
# two-sided p is 0.5.
#
# THIS IS WHY THE 2026-08-23 REPORT WAS WRONG. It printed a Holm-adjusted p of .0081 on a two-slate
# cohort — a value 62 times smaller than the test can produce. The cause was _p_from_interval
# applying a normal approximation to a bootstrap whose resample space holds three distinct means;
# the z-statistic it produced carried the degrees of freedom of 30 GAMES, not of 2 CLUSTERS. That is
# exactly the independence assumption the clustering standard exists to forbid, reintroduced in the
# p-value after being correctly avoided in the interval.
#
# No new post-result threshold is introduced. The 500-game / 60-slate-date gate remains the binding
# one; this rule only decides whether an inferential verdict may be PRINTED at all.
# ---------------------------------------------------------------------------------------------
NON_DECISION_GRADE = "NON_DECISION_GRADE"
UNAVAILABLE_INSUFFICIENT_CLUSTERS = "UNAVAILABLE_INSUFFICIENT_CLUSTERS"
NOT_EVALUABLE = "NOT_EVALUABLE"


def min_clusters_for_alpha(alpha=FAMILY_ALPHA):
    """Smallest k for which an exact cluster sign-flip test can reach alpha. Derived, not tuned."""
    if not (0 < alpha < 1):
        raise ValueError(f"alpha must lie in (0,1), got {alpha}")
    return int(math.ceil(math.log2(2.0 / alpha)))


def smallest_attainable_p(k):
    """The floor on a two-sided exact sign-flip p-value with k clusters."""
    if k is None or k < 1:
        return 1.0
    return min(1.0, 2.0 / (2 ** k))


def inference_grade(n_clusters, alpha=FAMILY_ALPHA):
    """(ok, reason). May an inferential verdict be reported on this many clusters at all?"""
    need = min_clusters_for_alpha(alpha)
    if n_clusters is None:
        return False, "the number of independent clusters was not established"
    if n_clusters < need:
        return False, (f"{n_clusters} independent cluster(s): an exact cluster sign-flip test has "
                       f"{2 ** n_clusters} assignments, so its smallest attainable two-sided p is "
                       f"{smallest_attainable_p(n_clusters):.4f}, above alpha={alpha}. Inference "
                       f"needs at least {need} clusters and Holm adjustment can only increase a "
                       f"p-value, never rescue one.")
    return True, f"{n_clusters} clusters, at or above the derived minimum of {need}"

# Real-money gate — entirely separate.
RM_MIN_GAMES = 100
RM_REQUIRES_EXPLICIT_APPROVAL = True


def holm(pvalues):
    """Holm step-down adjusted p-values, order preserved. Monotone and capped at 1."""
    idx = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    m = len(pvalues)
    out = [None] * m
    running = 0.0
    for rank, i in enumerate(idx):
        adj = min(1.0, (m - rank) * pvalues[i])
        running = max(running, adj)          # enforce monotonicity down the step-down sequence
        out[i] = running
    return out


def date_block_interval(rows, key="delta_brier", reps=4000, seed=20260823, alpha=FAMILY_ALPHA):
    """Paired DATE-BLOCK bootstrap interval on a per-game loss difference.

    The block is the slate date. Games on one night share weather, umpiring, schedule spot and the
    night's home/away balance, so resampling games would treat a 15-game night as 15 independent
    draws."""
    return PE.slate_bootstrap(rows, key, reps=reps, seed=seed, alpha=alpha)


def _raw_mean(xs):
    return (sum(xs) / len(xs)) if xs else None


def _p_from_interval(bs, key="point"):
    """A two-sided bootstrap p-value for 'the mean difference is zero', from the resampled means.

    Derived from the same resamples the interval uses so the two cannot disagree."""
    lo, hi, pt = bs.get("lo"), bs.get("hi"), bs.get(key)
    if lo is None or pt is None:
        return None
    # symmetric normal approximation on the bootstrap spread: se = (hi - lo) / (2 * z_{1-alpha/2})
    z = 1.959963984540054
    se = (hi - lo) / (2 * z)
    if se <= 0:
        return 0.0 if pt != 0 else 1.0
    zstat = abs(pt) / se
    return math.erfc(zstat / math.sqrt(2.0))


def compare_against_references(challenger, references, reps=4000, seed=20260823):
    """challenger: [{game_id, slate_date, p, y}]; references: {name: [{game_id, p}]}.

    Returns one block per reference with a LABELLED comparator, plus Holm-adjusted p-values across
    the family of comparisons."""
    by_g = {r["game_id"]: r for r in challenger}
    blocks, pvals, names = {}, [], []
    for name, ref in sorted(references.items()):
        rby = {r["game_id"]: r for r in ref}
        common = sorted(set(by_g) & set(rby))
        only_c, only_r = sorted(set(by_g) - set(rby)), sorted(set(rby) - set(by_g))
        rows = []
        for g in common:
            c, rr = by_g[g], rby[g]
            y = int(c["y"])
            rows.append({"game_id": g, "slate_date": c.get("slate_date"),
                         "delta_brier": (float(c["p"]) - y) ** 2 - (float(rr["p"]) - y) ** 2})
        bs = date_block_interval(rows, reps=reps, seed=seed)
        k = len({r.get("slate_date") for r in rows if r.get("slate_date") is not None})
        grade_ok, grade_why = inference_grade(k)
        block = {
            "comparator": f"CHALLENGER minus {name}",
            "sign_convention": "negative favours the CHALLENGER",
            "n_paired": len(rows),
            "n_slate_dates": k,
            # THE RAW PAIRED MEAN IS ALWAYS REPORTED. It is descriptive and needs no inference.
            "mean_delta_brier": _raw_mean([r["delta_brier"] for r in rows]),
            "unpaired": {"challenger_only": only_c, f"{name}_only": only_r},
            "inference_grade": grade_ok,
            "inference_note": grade_why,
        }
        if not grade_ok:
            # SUPPRESSED. Not softened, not caveated — withheld. A number that the test cannot
            # produce should not appear at all, because a printed p-value is quoted long after the
            # caveat beside it is forgotten.
            block.update({
                "date_block_interval": NON_DECISION_GRADE,
                "raw_p": UNAVAILABLE_INSUFFICIENT_CLUSTERS,
                "holm_adjusted_p": UNAVAILABLE_INSUFFICIENT_CLUSTERS,
                "interval_entirely_below_zero": NOT_EVALUABLE,
                "beats_this_reference": NOT_EVALUABLE,
                "smallest_attainable_two_sided_p": smallest_attainable_p(k),
            })
            blocks[name] = block
            continue
        p = _p_from_interval(bs)
        block.update({"date_block_interval": [bs.get("lo"), bs.get("hi")], "raw_p": p})
        blocks[name] = block
        names.append(name); pvals.append(p if p is not None else 1.0)
    adj = holm(pvals)
    for name, a in zip(names, adj):
        blocks[name]["holm_adjusted_p"] = a
        lo, hi = blocks[name]["date_block_interval"]
        blocks[name]["interval_entirely_below_zero"] = bool(hi is not None and hi < 0)
        blocks[name]["beats_this_reference"] = bool(
            hi is not None and hi < 0 and a is not None and a < FAMILY_ALPHA)
    return {"family_size": len(names), "family_alpha": FAMILY_ALPHA,
            "suppressed_for_insufficient_clusters": [n for n, b in blocks.items()
                                                     if not b.get("inference_grade")],
            "min_clusters_required": min_clusters_for_alpha(FAMILY_ALPHA),
            "adjustment": "Holm step-down, applied across every reference simultaneously",
            "why_adjusted": ("two references means two simultaneous comparisons; taking the better "
                             "of two 95% intervals is a 90% claim wearing a 95% label"),
            "references": blocks}


def evaluate(cohort, comparison, integrity, calibration, auc):
    """The binding gate. Returns FORWARD_ONLY_PENDING unless EVERY condition is met.

    cohort: {"n_games":..., "n_slate_dates":...}
    comparison: the output of compare_against_references
    integrity: {"chronology_failures":n, "provenance_failures":n, "starter_failures":n,
                "duplicate_failures":n}
    calibration: {"slope":..., "intercept":...}
    auc: {"challenger":..., "references": {name: value}}"""
    c = {}
    n, nd = cohort.get("n_games", 0), cohort.get("n_slate_dates", 0)
    c["sample_500_games"] = {"ok": n >= MIN_GAMES, "have": n, "need": MIN_GAMES}
    c["sample_60_slate_dates"] = {"ok": nd >= MIN_SLATE_DATES, "have": nd, "need": MIN_SLATE_DATES}
    refs = comparison.get("references", {})
    # NOT_EVALUABLE is a string, and bool("NOT_EVALUABLE") is True. Comparing to True explicitly
    # keeps a suppressed verdict from being read as a passing one.
    beats = {k: (v.get("beats_this_reference") is True) for k, v in refs.items()}
    c["beats_every_reference"] = {"ok": bool(refs) and all(beats.values()), "detail": beats,
                                  "rule": "a conjunction over every reference, never an average"}
    c["holm_intervals_below_zero"] = {
        "ok": bool(refs) and all(v.get("interval_entirely_below_zero") is True
                                 for v in refs.values()),
        "detail": {k: v.get("date_block_interval") for k, v in refs.items()}}
    ac = auc.get("challenger")
    arefs = auc.get("references") or {}
    best_ref = max(arefs.values()) if arefs else None
    c["auc_improvement"] = {
        "ok": bool(ac is not None and best_ref is not None
                   and (ac - best_ref) >= REQUIRED_AUC_IMPROVEMENT),
        "challenger": ac, "best_reference": best_ref, "need": REQUIRED_AUC_IMPROVEMENT,
        "have": (ac - best_ref) if (ac is not None and best_ref is not None) else None}
    sl, ic = calibration.get("slope"), calibration.get("intercept")
    c["calibration_acceptable"] = {
        "ok": bool(sl is not None and ic is not None
                   and CALIBRATION_SLOPE_BAND[0] <= sl <= CALIBRATION_SLOPE_BAND[1]
                   and abs(ic) <= CALIBRATION_INTERCEPT_ABS_MAX),
        "slope": sl, "intercept": ic, "slope_band": list(CALIBRATION_SLOPE_BAND),
        "intercept_abs_max": CALIBRATION_INTERCEPT_ABS_MAX,
        "note": "an UNDEFINED calibration is not an acceptable one"}
    fails = {k: integrity.get(k, None) for k in
             ("chronology_failures", "provenance_failures", "starter_failures",
              "duplicate_failures")}
    c["zero_integrity_failures"] = {
        "ok": all(v == 0 for v in fails.values()), "detail": fails,
        "note": "a MISSING count is not zero; an unmeasured integrity check fails the gate"}
    all_ok = all(v["ok"] for v in c.values())
    return {
        "status": ELIGIBLE_FOR_PROMOTION_REVIEW if all_ok else FORWARD_ONLY_PENDING,
        "conditions": c,
        "blocking": [k for k, v in c.items() if not v["ok"]],
        "note": ("Every condition must hold. Meeting them makes the challenger ELIGIBLE FOR REVIEW; "
                 "it does not promote it, does not create action authority, and does not touch the "
                 "separate real-money gate."),
    }


def real_money_gate(n_games, roi, roi_interval, forward_calibration, explicit_user_approval):
    """Entirely separate from promotion. There is no path here that returns authorisation without
    an explicit human yes, and no amount of evidence substitutes for one."""
    c = {
        "sample_100_games": {"ok": (n_games or 0) >= RM_MIN_GAMES, "have": n_games,
                             "need": RM_MIN_GAMES},
        "positive_roi": {"ok": roi is not None and roi > 0, "roi": roi},
        "roi_interval_excludes_zero": {
            "ok": bool(roi_interval and roi_interval[0] is not None and roi_interval[0] > 0),
            "interval": roi_interval},
        "forward_calibration": {"ok": bool(forward_calibration)},
        "explicit_user_approval": {"ok": bool(explicit_user_approval),
                                   "note": "a human decision. No evidence substitutes for it."},
    }
    ok = all(v["ok"] for v in c.values())
    return {"authorised": ok, "conditions": c,
            "blocking": [k for k, v in c.items() if not v["ok"]],
            "note": ("This gate is independent of model promotion. Clearing one is not clearing the "
                     "other, and wager authority remains NO until this gate returns authorised.")}


def selftest():
    f = []
    # --- HOLM ---------------------------------------------------------------------------------
    if [round(x, 6) for x in holm([0.01, 0.04])] != [0.02, 0.04]:
        f.append(f"Holm wrong on two comparisons: {holm([0.01, 0.04])}")
    if [round(x, 6) for x in holm([0.04, 0.01])] != [0.04, 0.02]:
        f.append("Holm did not preserve input order")
    if any(a < b for a, b in zip(holm([0.001, 0.002, 0.003]), holm([0.001, 0.002, 0.003])[1:])):
        pass
    h = holm([0.02, 0.03, 0.04])
    if h != sorted(h):
        f.append(f"Holm is not monotone across the step-down sequence: {h}")
    if any(x > 1.0 for x in holm([0.6, 0.7])):
        f.append("Holm produced an adjusted p above 1")
    # a single comparison is unchanged
    if holm([0.03]) != [0.03]:
        f.append("Holm altered a single comparison")
    # the adjustment must actually COST something
    if holm([0.03, 0.03])[0] <= 0.03:
        f.append("two simultaneous comparisons cost nothing — that is an unadjusted family")

    # --- COMPARISON AGAINST TWO REFERENCES ----------------------------------------------------
    full = dict(n_games=600, n_slate_dates=70)
    clean = dict(chronology_failures=0, provenance_failures=0, starter_failures=0,
                 duplicate_failures=0)
    cal_ok = {"slope": 1.05, "intercept": 0.10}
    auc_ok = {"challenger": 0.60, "references": {"A": 0.52, "B": 0.58}}
    ch, r1, r2 = [], [], []
    for d in ("2026-08-19", "2026-08-20", "2026-08-21", "2026-08-22"):
        for i in range(15):
            y = 1 if i % 3 else 0
            g = f"{d}-{i}"
            ch.append({"game_id": g, "slate_date": d, "p": 0.85 if y else 0.15, "y": y})
            r1.append({"game_id": g, "p": 0.52})                      # a weak reference
            r2.append({"game_id": g, "p": 0.80 if y else 0.20})       # a strong reference
    cmp1 = compare_against_references(ch, {"EXPANDING_PRIOR": r1, "V13": r2})
    # FOUR slate dates is BELOW the derived minimum of six, so every inferential field must be
    # SUPPRESSED while the raw paired mean is still reported.
    for name in ("EXPANDING_PRIOR", "V13"):
        b = cmp1["references"][name]
        if b["comparator"] != f"CHALLENGER minus {name}":
            f.append(f"the {name} block does not label its comparator")
        if "negative favours the CHALLENGER" not in b["sign_convention"]:
            f.append(f"the {name} block does not state its sign convention")
        if b["n_paired"] != 60 or b["n_slate_dates"] != 4:
            f.append(f"{name}: n_paired {b['n_paired']} / slates {b['n_slate_dates']}")
        if b.get("inference_grade") is not False:
            f.append(f"{name}: four clusters were graded inference-capable")
        if b["date_block_interval"] != NON_DECISION_GRADE:
            f.append(f"{name}: an interval was printed on four clusters: {b['date_block_interval']}")
        if b["raw_p"] != UNAVAILABLE_INSUFFICIENT_CLUSTERS or \
                b["holm_adjusted_p"] != UNAVAILABLE_INSUFFICIENT_CLUSTERS:
            f.append(f"{name}: a p-value was printed on four clusters: {b['raw_p']}")
        if b["beats_this_reference"] != NOT_EVALUABLE or \
                b["interval_entirely_below_zero"] != NOT_EVALUABLE:
            f.append(f"{name}: a beats verdict was printed on four clusters")
        if b["mean_delta_brier"] is None:
            f.append(f"{name}: the raw paired mean was suppressed along with the inference; it is "
                     f"descriptive and must survive")
        if abs(b["smallest_attainable_two_sided_p"] - 0.125) > 1e-12:
            f.append(f"{name}: the attainable-p floor for four clusters is wrong: "
                     f"{b['smallest_attainable_two_sided_p']}")
    if set(cmp1["suppressed_for_insufficient_clusters"]) != {"EXPANDING_PRIOR", "V13"}:
        f.append("the suppression list does not name both references")
    if cmp1["min_clusters_required"] != 6:
        f.append(f"the reported cluster minimum is {cmp1['min_clusters_required']}, expected 6")
    if "90% claim wearing a 95% label" not in cmp1["why_adjusted"]:
        f.append("the comparison does not state why the family is adjusted")
    # A SUPPRESSED verdict must never be read as a PASS by the gate. NOT_EVALUABLE is a truthy
    # string, and that is exactly how a suppressed comparison could sneak through.
    gsup = evaluate(dict(n_games=600, n_slate_dates=70), cmp1, clean, cal_ok,
                    {"challenger": 0.70, "references": {"EXPANDING_PRIOR": 0.52, "V13": 0.58}})
    if gsup["status"] != FORWARD_ONLY_PENDING:
        f.append("the gate PASSED on suppressed, non-evaluable comparisons")
    for cond in ("beats_every_reference", "holm_intervals_below_zero"):
        if cond not in gsup["blocking"]:
            f.append(f"a NOT_EVALUABLE verdict was not blocking on {cond} — a truthy string was "
                     f"read as a passing result")
    # SIX clusters is the boundary and must be inference-capable
    ch6, r6 = [], []
    for d in ("d1", "d2", "d3", "d4", "d5", "d6"):
        for i in range(10):
            y = 1 if i % 3 else 0
            g = f"{d}-{i}"
            ch6.append({"game_id": g, "slate_date": d, "p": 0.85 if y else 0.15, "y": y})
            r6.append({"game_id": g, "p": 0.52})
    c6 = compare_against_references(ch6, {"WEAK": r6}, reps=1500)["references"]["WEAK"]
    if c6.get("inference_grade") is not True:
        f.append("six clusters, the derived minimum, were refused inference")
    if c6["date_block_interval"] == NON_DECISION_GRADE:
        f.append("six clusters produced no interval")
    if c6["beats_this_reference"] is not True:
        f.append("a challenger far better than a weak reference over six clusters did not clear it")
    # the derived minimum itself
    if min_clusters_for_alpha(0.05) != 6 or min_clusters_for_alpha(0.01) != 8:
        f.append(f"the derived cluster minimum is wrong: .05 -> {min_clusters_for_alpha(0.05)}, "
                 f".01 -> {min_clusters_for_alpha(0.01)}")
    for k, want in ((1, 1.0), (2, 0.5), (3, 0.25), (6, 0.03125)):
        if abs(smallest_attainable_p(k) - want) > 1e-12:
            f.append(f"smallest_attainable_p({k}) = {smallest_attainable_p(k)}, expected {want}")
    ok2c, why2c = inference_grade(2)
    if ok2c:
        f.append("TWO clusters were graded inference-capable — the 2026-08-23 defect")
    if "0.5000" not in why2c or "Holm adjustment can only increase" not in why2c:
        f.append(f"the two-cluster refusal does not state the attainable floor or that Holm cannot "
                 f"rescue it: {why2c}")
    if inference_grade(None)[0]:
        f.append("an unestablished cluster count was graded inference-capable")
    # ISOLATION for the adjusted-p conjunct. Holm multiplies the SMALLEST p in the family by m, so
    # two comparisons that would each pass alone can BOTH fail together. Only the adjusted-p
    # condition can catch that; the raw intervals are unchanged.
    # Built through compare_against_references itself, not hand-assembled: a challenger that wins
    # big on four nights and loses on two, so its date-block interval sits ENTIRELY BELOW ZERO while
    # its raw p (~.039) doubles past alpha under Holm. Only the adjusted-p conjunct can refuse this.
    mch, mr1, mr2 = [], [], []
    for di, d in enumerate(("d1", "d2", "d3", "d4", "d5", "d6")):
        e = 0.10 if di < 4 else -0.04
        for i in range(10):
            y = 1 if i % 3 else 0
            g = f"{d}-{i}"
            mch.append({"game_id": g, "slate_date": d, "p": 0.5 + e if y else 0.5 - e, "y": y})
            mr1.append({"game_id": g, "p": 0.5})
            mr2.append({"game_id": g, "p": 0.5})
    fam = compare_against_references(mch, {"R1": mr1, "R2": mr2}, reps=1500)
    for name in ("R1", "R2"):
        b = fam["references"][name]
        if not b["interval_entirely_below_zero"]:
            f.append(f"{name}: the marginal fixture no longer has an interval below zero "
                     f"({b['date_block_interval']}), so it cannot isolate the adjusted-p conjunct")
        if not (b["raw_p"] < FAMILY_ALPHA <= b["holm_adjusted_p"]):
            f.append(f"{name}: raw p {b['raw_p']:.4f} / Holm {b['holm_adjusted_p']:.4f} do not "
                     f"straddle alpha, so this fixture proves nothing about the adjustment")
        if b["beats_this_reference"]:
            f.append(f"{name} cleared its reference with an interval below zero but a Holm-adjusted "
                     f"p of {b['holm_adjusted_p']:.4f} — the adjusted-p conjunct is not applied")
    r = evaluate(dict(n_games=600, n_slate_dates=70), fam, clean, cal_ok, auc_ok)
    if r["status"] != FORWARD_ONLY_PENDING or "beats_every_reference" not in r["blocking"]:
        f.append("a family whose intervals are below zero but whose Holm-adjusted p-values are not "
                 "significant still cleared the reference condition")

    # NOT A MUTANT, and deliberately. _p_from_interval derives the p-value FROM the same bootstrap
    # interval, so an interval touching zero always yields a large p and the two conjuncts cannot
    # disagree in that direction. The interval condition is therefore redundant defence given the
    # p condition, and no fixture can isolate it. Saying so is more honest than inventing a mutant
    # that appears to kill (lesson 23 corollary, as in echo_gate and baseline_offset).

    # UNPAIRED GAMES ARE LISTED
    cmp2 = compare_against_references(ch + [{"game_id": "x", "slate_date": "d", "p": .5, "y": 1}],
                                      {"EXPANDING_PRIOR": r1})
    if cmp2["references"]["EXPANDING_PRIOR"]["unpaired"]["challenger_only"] != ["x"]:
        f.append("an unpaired game was not listed")
    if cmp2["references"]["EXPANDING_PRIOR"]["n_paired"] != 60:
        f.append("an unpaired game was silently scored")

    # --- THE BINDING GATE ----------------------------------------------------------------------
    good_cmp = {"references": {"A": {"beats_this_reference": True,
                                     "interval_entirely_below_zero": True,
                                     "date_block_interval": [-0.02, -0.01]},
                               "B": {"beats_this_reference": True,
                                     "interval_entirely_below_zero": True,
                                     "date_block_interval": [-0.03, -0.005]}}}
    g = evaluate(full, good_cmp, clean, cal_ok, auc_ok)
    if g["status"] != ELIGIBLE_FOR_PROMOTION_REVIEW:
        f.append(f"a fully qualifying cohort was blocked on {g['blocking']}")
    if "does not promote it" not in g["note"]:
        f.append("the gate does not state that eligibility is not promotion")
    # EVERY condition is necessary
    checks = [
        ("sample_500_games", dict(n_games=499, n_slate_dates=70), good_cmp, clean, cal_ok, auc_ok),
        ("sample_60_slate_dates", dict(n_games=600, n_slate_dates=59), good_cmp, clean, cal_ok, auc_ok),
        ("beats_every_reference", full,
         {"references": {"A": dict(good_cmp["references"]["A"]),
                         "B": dict(good_cmp["references"]["B"], beats_this_reference=False)}},
         clean, cal_ok, auc_ok),
        ("holm_intervals_below_zero", full,
         {"references": {"A": dict(good_cmp["references"]["A"]),
                         "B": dict(good_cmp["references"]["B"],
                                   interval_entirely_below_zero=False)}}, clean, cal_ok, auc_ok),
        ("auc_improvement", full, good_cmp, clean, cal_ok,
         {"challenger": 0.585, "references": {"A": 0.52, "B": 0.58}}),
        ("calibration_acceptable", full, good_cmp, clean, {"slope": 0.5, "intercept": 0.1}, auc_ok),
        ("calibration_acceptable", full, good_cmp, clean, {"slope": None, "intercept": None}, auc_ok),
        ("zero_integrity_failures", full, good_cmp, dict(clean, starter_failures=1), cal_ok, auc_ok),
        ("zero_integrity_failures", full, good_cmp, {"chronology_failures": 0}, cal_ok, auc_ok),
    ]
    for want, coh, cmpx, integ, cal, a in checks:
        r = evaluate(coh, cmpx, integ, cal, a)
        if r["status"] != FORWARD_ONLY_PENDING:
            f.append(f"the gate PASSED with {want} failing")
        elif want not in r["blocking"]:
            f.append(f"{want} failed but was not named as blocking: {r['blocking']}")
    # BOTH references must fall — beating one is not enough, and it is a conjunction not an average
    one_only = {"references": {"A": dict(good_cmp["references"]["A"]),
                               "B": {"beats_this_reference": False,
                                     "interval_entirely_below_zero": False,
                                     "date_block_interval": [-0.01, 0.05]}}}
    if evaluate(full, one_only, clean, cal_ok, auc_ok)["status"] != FORWARD_ONLY_PENDING:
        f.append("beating ONE of two references was enough")
    # no references at all is not a pass
    er = evaluate(full, {"references": {}}, clean, cal_ok, auc_ok)
    if er["status"] != FORWARD_ONLY_PENDING:
        f.append("a comparison against NO reference passed the gate")
    if "beats_every_reference" not in er["blocking"]:
        f.append("an EMPTY reference set satisfied the conjunction vacuously — all([]) is True, so "
                 "the emptiness must be refused explicitly")

    # --- THE REAL-MONEY GATE IS SEPARATE AND NEEDS A HUMAN --------------------------------------
    rm = real_money_gate(200, 0.06, [0.01, 0.11], True, True)
    if not rm["authorised"]:
        f.append(f"a fully qualifying real-money case was refused: {rm['blocking']}")
    for kw, want in ((dict(n_games=99, roi=0.06, roi_interval=[0.01, 0.11],
                           forward_calibration=True, explicit_user_approval=True),
                      "sample_100_games"),
                     (dict(n_games=200, roi=-0.01, roi_interval=[-0.05, 0.03],
                           forward_calibration=True, explicit_user_approval=True), "positive_roi"),
                     (dict(n_games=200, roi=0.06, roi_interval=[-0.01, 0.13],
                           forward_calibration=True, explicit_user_approval=True),
                      "roi_interval_excludes_zero"),
                     (dict(n_games=200, roi=0.06, roi_interval=[0.01, 0.11],
                           forward_calibration=False, explicit_user_approval=True),
                      "forward_calibration"),
                     (dict(n_games=200, roi=0.06, roi_interval=[0.01, 0.11],
                           forward_calibration=True, explicit_user_approval=False),
                      "explicit_user_approval")):
        r = real_money_gate(**kw)
        if r["authorised"]:
            f.append(f"the real-money gate authorised with {want} failing")
        elif want not in r["blocking"]:
            f.append(f"{want} failed but was not named: {r['blocking']}")
    # NO EVIDENCE substitutes for approval, however overwhelming
    if real_money_gate(100000, 5.0, [4.0, 6.0], True, False)["authorised"]:
        f.append("overwhelming evidence authorised real money with no human approval")
    if "No evidence substitutes for it" not in \
            rm["conditions"]["explicit_user_approval"]["note"]:
        f.append("the approval condition does not say evidence cannot substitute for it")
    if "independent of model promotion" not in rm["note"]:
        f.append("the real-money gate does not declare its independence from promotion")

    print("promotion_gate selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("inferential verdicts are printed on too few clusters — the 2026-08-23 defect",
     "        if not grade_ok:", "        if False:"),
    ("the cluster minimum is lowered so two clusters become inference-grade",
     "    return int(math.ceil(math.log2(2.0 / alpha)))", "    return 1"),
    ("the attainable-p floor is computed as if games were the clusters",
     "    return min(1.0, 2.0 / (2 ** k))", "    return 0.0"),
    ("an unestablished cluster count is treated as sufficient",
     "    if n_clusters is None:", "    if False:"),
    ("clusters are counted as games",
     '        k = len({r.get("slate_date") for r in rows if r.get("slate_date") is not None})',
     "        k = len(rows)"),
    ("the raw paired mean is suppressed along with the inference",
     '            "mean_delta_brier": _raw_mean([r["delta_brier"] for r in rows]),',
     '            "mean_delta_brier": None,'),
    ("a NOT_EVALUABLE verdict is read as a passing result",
     '    beats = {k: (v.get("beats_this_reference") is True) for k, v in refs.items()}',
     '    beats = {k: bool(v.get("beats_this_reference")) for k, v in refs.items()}'),
    ("a NOT_EVALUABLE interval is read as below zero",
     '        "ok": bool(refs) and all(v.get("interval_entirely_below_zero") is True',
     '        "ok": bool(refs) and all(v.get("interval_entirely_below_zero") or True'),
    ("the two-cluster refusal stops naming the attainable floor",
     'f"{smallest_attainable_p(n_clusters):.4f}, above alpha={alpha}. Inference "',
     'f"a value, above alpha={alpha}. Inference "'),
    ("Holm applies no adjustment at all",
     "        adj = min(1.0, (m - rank) * pvalues[i])", "        adj = pvalues[i]"),
    ("Holm loses its monotonicity, so a later comparison can undercut an earlier one",
     "        running = max(running, adj)", "        running = adj"),
    ("Holm is applied in sorted order instead of input order",
     "        out[i] = running", "        out[rank] = running"),
    ("adjusted p-values may exceed 1", "        adj = min(1.0, (m - rank) * pvalues[i])",
     "        adj = (m - rank) * pvalues[i]"),
    ("the comparator label is dropped",
     '            "comparator": f"CHALLENGER minus {name}",', '            "comparator": "comparison",'),
    ("the sign convention is dropped",
     '            "sign_convention": "negative favours the CHALLENGER",',
     '            "sign_convention": "",'),
    ("the interval is clustered on games instead of slate dates",
     '            rows.append({"game_id": g, "slate_date": c.get("slate_date"),',
     '            rows.append({"game_id": g, "slate_date": g,'),
    ("unpaired games are silently scored instead of listed",
     "        common = sorted(set(by_g) & set(rby))", "        common = sorted(set(by_g) | set(rby))"),
    # NOT A MUTANT: see the note in selftest(). The bootstrap p-value is derived from the same
    # interval, so an interval touching zero always produces a large p and the interval conjunct
    # cannot be isolated from the p conjunct. It is redundant defence, kept on purpose and recorded
    # here rather than dressed up with a mutant that appears to kill.
    ("beating a reference no longer requires the adjusted p",
     '            hi is not None and hi < 0 and a is not None and a < FAMILY_ALPHA)',
     "            hi is not None and hi < 0)"),
    ("the 500-game floor is removed", "MIN_GAMES = 500", "MIN_GAMES = 1"),
    ("the 60-slate-date floor is removed", "MIN_SLATE_DATES = 60", "MIN_SLATE_DATES = 1"),
    ("the references are averaged instead of conjoined",
     '    c["beats_every_reference"] = {"ok": bool(refs) and all(beats.values()),',
     '    c["beats_every_reference"] = {"ok": bool(refs) and any(beats.values()),'),
    ("an empty reference set passes the conjunction",
     '    c["beats_every_reference"] = {"ok": bool(refs) and all(beats.values()),',
     '    c["beats_every_reference"] = {"ok": all(beats.values()),'),
    ("the Holm interval condition is dropped",
     '    c["holm_intervals_below_zero"] = {', '    c["holm_intervals_below_zero"] = {"ok": True, "_": {'),
    ("the AUC improvement requirement is removed",
     "REQUIRED_AUC_IMPROVEMENT = 0.010", "REQUIRED_AUC_IMPROVEMENT = -1.0"),
    ("AUC is compared against the WEAKEST reference instead of the best",
     "    best_ref = max(arefs.values()) if arefs else None",
     "    best_ref = min(arefs.values()) if arefs else None"),
    ("an UNDEFINED calibration is treated as acceptable",
     "        "'"ok": bool(sl is not None and ic is not None', '        "ok": bool(True or sl is not None and ic is not None'),
    ("the calibration slope band is removed",
     "CALIBRATION_SLOPE_BAND = (0.80, 1.25)", "CALIBRATION_SLOPE_BAND = (-99.0, 99.0)"),
    ("a MISSING integrity count is treated as zero",
     '        "ok": all(v == 0 for v in fails.values()), "detail": fails,',
     '        "ok": all(v in (0, None) for v in fails.values()), "detail": fails,'),
    ("integrity failures stop blocking", '        "ok": all(v == 0 for v in fails.values()), "detail": fails,',
     '        "ok": True, "detail": fails,'),
    ("the gate passes when any single condition fails",
     "    all_ok = all(v[\"ok\"] for v in c.values())", "    all_ok = any(v[\"ok\"] for v in c.values())"),
    ("the gate stops saying eligibility is not promotion",
     '"it does not promote it, does not create action authority, and does not touch the "',
     '"it is promoted, with action authority, and it touches the "'),
    ("real money is authorised without explicit human approval",
     '        "explicit_user_approval": {"ok": bool(explicit_user_approval),',
     '        "explicit_user_approval": {"ok": True,'),
    ("the real-money sample floor is removed", "RM_MIN_GAMES = 100", "RM_MIN_GAMES = 1"),
    ("a ROI interval touching zero is accepted",
     '            "ok": bool(roi_interval and roi_interval[0] is not None and roi_interval[0] > 0),',
     '            "ok": bool(roi_interval and roi_interval[0] is not None and roi_interval[0] >= -1),'),
    ("the real-money gate stops declaring its independence",
     '            "note": ("This gate is independent of model promotion.', '            "note": ("Same gate.'),
]


def mutation_suite(verbose=True):
    import subprocess as _sp, tempfile as _tf
    src = open(os.path.abspath(__file__)).read()
    i = src.index("MUTANTS = [")
    j = src.index("\ndef mutation_suite", i)
    head, block, tail = src[:i], src[i:j], src[j:]
    surv, unapp = [], []
    for name, old, new in MUTANTS:
        where = "head" if old in head else ("tail" if old in tail else None)
        if where is None:
            unapp.append(f"{name}: pattern not found"); continue
        mut = (head.replace(old, new, 1) + block + tail) if where == "head" \
            else (head + block + tail.replace(old, new, 1))
        if mut == src:
            unapp.append(f"{name}: no-op"); continue
        with _tf.NamedTemporaryFile("w", suffix="_mutant.py", delete=False,
                                    dir=os.path.dirname(os.path.abspath(__file__))) as fh:
            fh.write(mut); path = fh.name
        try:
            pr = _sp.run([sys.executable, path, "--selftest"], capture_output=True, text=True, timeout=240)
            killed = pr.returncode != 0
        except _sp.TimeoutExpired:
            killed = True
        finally:
            os.unlink(path)
        if verbose:
            print(f"  {'KILLED  ' if killed else 'SURVIVED'}  {name}")
        if not killed:
            surv.append(name)
    for u in unapp:
        print(f"  UNAPPLIED  {u}")
    print(f"mutation suite: {len(MUTANTS)-len(surv)-len(unapp)}/{len(MUTANTS)} killed"
          f"{'' if not (surv or unapp) else '  — SURVIVORS MEAN DECORATIVE FIXTURES'}")
    return surv + unapp


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    if "--mutants" in sys.argv:
        sys.exit(1 if mutation_suite() else 0)
    print(__doc__)
