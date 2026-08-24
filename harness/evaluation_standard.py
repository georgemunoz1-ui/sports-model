#!/usr/bin/env python3
"""EVALUATION STANDARD — a good record is not evidence. Skill against the expanding prior is.

OWNER SPECIFICATION 2026-08-23:
    Report separately by sport, model arm, estimand and information dose: winner record, Brier and
    log loss, Brier skill versus the expanding base-rate prior, calibration intercept and slope,
    reliability by probability bucket, probability spread and discrimination, margin and total MAE,
    signed bias, ATS diagnostic record, and performance by all-CAP / partial / full information class.

    "A good record without improvement over the expanding prior does not qualify as predictive
     progress."

THE VERDICT IS GOVERNED BY SKILL, NOT BY RECORD. This is the whole point and it is enforced in code:
verdict() reads the Brier skill score and will return NOT_PREDICTIVE_PROGRESS for a cohort that went
14-1 if its probabilities did not beat the expanding prior. The 2026-08-21 slate is the worked
example — v2 went 10-5 while a trivial always-pick-home heuristic went 14-1, and the record was the
most misleading number available.

BRIER SKILL SCORE = 1 - Brier_model / Brier_prior. Positive means the model added information over
the base rate. Zero means it added nothing. NEGATIVE MEANS IT SUBTRACTED — and a negative skill
score with a winning record is the exact combination this standard exists to surface.

NEVER POOLED. Sport, arm, estimand and information dose are four separate keys and every cut is
reported independently. Pooling a WNBA winner head with an MLB winner head, or an all-CAP cohort
with a full-information one, produces a number that describes no configuration.

RELIABILITY BY BUCKET carries its own trap: with 30 games most buckets hold two or three rows, and a
bucket of three is not a calibration measurement. Every bucket therefore reports its n, and buckets
below a floor are marked INSUFFICIENT rather than being quietly averaged into a curve.
"""
from __future__ import annotations

import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paired_eval as PE

BUCKETS = ((0.0, 0.4), (0.4, 0.45), (0.45, 0.5), (0.5, 0.55), (0.55, 0.6), (0.6, 0.7), (0.7, 1.01))
BUCKET_MIN_N = 5

PREDICTIVE_PROGRESS = "PREDICTIVE_PROGRESS"
NO_PREDICTIVE_PROGRESS = "NO_PREDICTIVE_PROGRESS"
NEGATIVE_SKILL = "NEGATIVE_SKILL_WORSE_THAN_THE_PRIOR"
INSUFFICIENT = "INSUFFICIENT_SAMPLE"
SKILL_MIN_N = 30

# ---------------------------------------------------------------------------------------------
# CONSTANT-FORECAST GUARD — PREREGISTERED 2026-08-23, DERIVED, NOT TUNED.
#
# The first version of this guard was a spread threshold that I set to 1e-6, watched miss the
# expanding-prior arm on real data, and then widened to 1e-3. That is a threshold adjusted after
# seeing results, which is the thing this repository exists to refuse. The owner named it.
#
# The replacement is a CONDITIONING rule with no free parameter to tune. The logistic recalibration
# solves a 2x2 Newton system with Hessian H = [[S_w, S_wx], [S_wx, S_wxx]]. That solve is estimable
# only when H is well conditioned. The standard numerical-analysis rule is that a linear solve
# retains about half the available significant digits when the reciprocal condition number falls to
# sqrt(machine epsilon); below that the solution is dominated by rounding. For float64,
#
#     sqrt(eps) = sqrt(2.220446049250313e-16) = 1.4901161193847656e-08
#
# so the rule is: report the calibration line only when rcond(H) > sqrt(eps), and when the regressor
# takes at least two distinct values at all. Both conditions come from the arithmetic, not from any
# dataset. Changing either is a SLOW-layer act at a formal model release.
# ---------------------------------------------------------------------------------------------
CONDITIONING_RULE_REGISTERED_UTC = "2026-08-23T00:00:00Z"
FLOAT64_EPS = sys.float_info.epsilon
RCOND_FLOOR = math.sqrt(FLOAT64_EPS)
MIN_DISTINCT_FORECASTS = 2


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _sd(xs):
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def brier_skill(model_brier, prior_brier):
    """1 - B_model / B_prior. None when the reference is degenerate."""
    if model_brier is None or prior_brier is None or prior_brier <= 0:
        return None
    return 1.0 - (model_brier / prior_brier)


def reliability(rows, p_key="p_model", y_key="home_win", buckets=BUCKETS, min_n=BUCKET_MIN_N):
    """Observed frequency against mean forecast probability, per bucket, WITH its n.

    A bucket below min_n is reported as INSUFFICIENT and carries no observed frequency: three games
    in a bucket is not a calibration measurement, and averaging it into a curve makes the curve look
    populated when it is not."""
    out = []
    for lo, hi in buckets:
        sel = [r for r in rows if lo <= float(r[p_key]) < hi]
        n = len(sel)
        entry = {"bucket": f"[{lo:.2f},{hi:.2f})", "n": n}
        if n < min_n:
            entry.update({"status": INSUFFICIENT, "mean_forecast": _mean([float(r[p_key]) for r in sel]),
                          "observed_frequency": None,
                          "why": f"n={n} is below the floor of {min_n}; a bucket this small is not "
                                 f"a calibration measurement"})
        else:
            mf = _mean([float(r[p_key]) for r in sel])
            of = _mean([float(r[y_key]) for r in sel])
            entry.update({"status": "MEASURED", "mean_forecast": mf, "observed_frequency": of,
                          "gap": (of - mf) if (of is not None and mf is not None) else None})
        out.append(entry)
    return out


# OWNER RULING 2026-08-23: "The Hessian rule is acceptable as a numerical estimability guard, but
# passing it must not mean calibration is acceptable. It only means fitting the calibration line is
# numerically possible."
#
# These are two different questions and were being conflated by proximity: the estimability guard
# sits immediately above the calibration fields, so a reader — and the promotion gate — could take
# "we printed a slope" as "the slope is fine". ESTIMABLE means the arithmetic is solvable. ACCEPTABLE
# means the slope and intercept sit inside the promotion bands. A model can be perfectly estimable
# and catastrophically miscalibrated; that is the normal case, not an edge case.
ESTIMABLE = "NUMERICALLY_ESTIMABLE"
NOT_ESTIMABLE = "NOT_NUMERICALLY_ESTIMABLE"


def calibration_acceptable(slope, intercept, slope_band=(0.80, 1.25), intercept_abs_max=0.50):
    """(acceptable, reason). SEPARATE from estimability, and never implied by it.

    An UNDEFINED calibration is NOT acceptable: a line that could not be fitted has not been shown
    to be fine, and defaulting it to acceptable would let the least measurable arm clear the
    strictest condition."""
    if slope is None or intercept is None:
        return False, ("calibration is UNDEFINED (the line was not estimable), which is not the "
                       "same as acceptable and must never be read as it")
    bad = []
    if not (slope_band[0] <= slope <= slope_band[1]):
        bad.append(f"slope {slope:.3f} outside {slope_band}")
    if abs(intercept) > intercept_abs_max:
        bad.append(f"|intercept| {abs(intercept):.3f} above {intercept_abs_max}")
    if bad:
        return False, "; ".join(bad)
    return True, f"slope {slope:.3f} in {slope_band}, |intercept| {abs(intercept):.3f} within band"


def calibration_estimable(ps):
    """(estimable, reason) under the PREREGISTERED conditioning rule. No tunable threshold.

    THIS IS A NUMERICAL GUARD ONLY. Passing it means the 2x2 solve is well conditioned. It says
    NOTHING about whether the resulting slope and intercept are acceptable — see
    calibration_acceptable, which is a separate question with separate bands.

    Builds the same Hessian the recalibration fit would use, at the null point (a=0, b=1) where the
    weights are the forecast's own p(1-p), and asks whether that 2x2 system is solvable in float64.
    A near-constant forecast makes the regressor column nearly collinear with the intercept column,
    the determinant collapses, and the fit returns whatever rounding produces — which on real data
    was an intercept of +189 and a slope of -2139."""
    if len(ps) < 3:
        return False, (f"n={len(ps)}: a calibration line through fewer than three games is not a "
                       f"calibration")
    if len({round(float(p), 12) for p in ps}) < MIN_DISTINCT_FORECASTS:
        return False, ("the forecast takes a single value across every game, so the regressor has "
                       "no variation; this is undefined, not miscalibrated")
    xs = []
    for p in ps:
        q = min(max(float(p), 1e-9), 1 - 1e-9)
        xs.append(math.log(q / (1 - q)))
    h00 = h01 = h11 = 0.0
    for p, x in zip(ps, xs):
        q = min(max(float(p), 1e-9), 1 - 1e-9)
        w = q * (1 - q)
        h00 += w; h01 += w * x; h11 += w * x * x
    det = h00 * h11 - h01 * h01
    # rcond of a symmetric 2x2 via its eigenvalues
    tr = h00 + h11
    disc = max(tr * tr - 4.0 * det, 0.0)
    lam_max = 0.5 * (tr + math.sqrt(disc))
    lam_min = 0.5 * (tr - math.sqrt(disc))
    rcond = (lam_min / lam_max) if lam_max > 0 else 0.0
    if rcond <= RCOND_FLOOR:
        return False, (f"the recalibration Hessian has reciprocal condition number {rcond:.3e}, at "
                       f"or below the preregistered float64 floor sqrt(eps)={RCOND_FLOOR:.3e}: the "
                       f"solve is dominated by rounding, so this is undefined, not miscalibrated")
    return True, f"rcond {rcond:.3e} above the preregistered floor {RCOND_FLOOR:.3e}"


# =================================================================================================
# EXACT NULLS FOR SMALL SAMPLES (2026-08-23, owner correction 1)
#
# I reported that the WNBA champion's perfect AUC on four games "happens about 4% of the time under
# a coin flip". That number was 1/24 — the probability of ONE SPECIFIC ORDERING of four items — and
# it is not the test. With ONE positive among four observations, a perfect AUC needs only that the
# single positive outrank all three negatives, which under exchangeable random scores happens with
# probability 1/C(4,1) = 25%. The claim was six times too impressive.
#
# The lesson is not "check the arithmetic". It is that a null quoted from memory is a fabricated
# number under R1, exactly like a fabricated result. So the null is computed here, exactly, from the
# subgroup's own shape, and a small-sample claim cites it rather than asserting it.
# =================================================================================================
def auc_null_probability(n_pos, n_neg):
    """P(AUC = 1) under exchangeable random scores: the positives must occupy the top n_pos ranks.

    Exactly 1 / C(n_pos+n_neg, n_pos). Returns None when the statistic is undefined (a subgroup with
    no positives or no negatives has no AUC at all) rather than a number that looks like evidence.
    """
    if not isinstance(n_pos, int) or not isinstance(n_neg, int) or n_pos < 1 or n_neg < 1:
        return None
    return 1.0 / math.comb(n_pos + n_neg, n_pos)


def directional_null_probability(n_correct, n):
    """P(at least n_correct of n correct) under a fair coin — the record-based null, not the AUC one.

    These are DIFFERENT tests and answer different questions; quoting one for the other is how the
    4% error happened. A 4-0 record is 1/16 = 6.25%; a perfect AUC with one positive among four is
    25%. Both can be true of the same four games.
    """
    if not isinstance(n, int) or not isinstance(n_correct, int) or n < 1 or not (0 <= n_correct <= n):
        return None
    return sum(math.comb(n, k) for k in range(n_correct, n + 1)) / (2.0 ** n)


def small_sample_null(n_pos, n_neg, n_correct=None):
    """Both nulls plus the honest reading, so a perfect subgroup cannot be reported bare."""
    n = (n_pos or 0) + (n_neg or 0)
    return {
        "n": n, "n_positive": n_pos, "n_negative": n_neg,
        "p_perfect_auc_under_random_scores": auc_null_probability(n_pos, n_neg),
        "p_record_under_fair_coin": (directional_null_probability(n_correct, n)
                                     if n_correct is not None else None),
        "reading": "these are different tests of different statistics on the same games; neither is "
                   "a p-value for a model and neither becomes one by being small",
    }


def winner_metrics(rows, p_key="p_model", prior_key="p_prior", y_key="home_win"):
    """Everything the standard requires for a winner estimand, on ONE cut."""
    n = len(rows)
    if n == 0:
        return {"n": 0, "status": INSUFFICIENT}
    ps = [float(r[p_key]) for r in rows]
    ys = [int(r[y_key]) for r in rows]
    correct = [int((p >= .5) == (y == 1)) for p, y in zip(ps, ys)]
    b = _mean([(p - y) ** 2 for p, y in zip(ps, ys)])
    ll = _mean([PE.logloss(p, y) for p, y in zip(ps, ys)])
    pri = [float(r[prior_key]) for r in rows if r.get(prior_key) is not None]
    pb = _mean([(p - y) ** 2 for p, y in zip(pri, ys)]) if len(pri) == n else None
    pll = _mean([PE.logloss(p, y) for p, y in zip(pri, ys)]) if len(pri) == n else None
    # A CONSTANT forecast has no variation to calibrate. Fitting a logistic recalibration to it
    # produced an intercept of +189 and a slope of -2139 on the expanding-prior arm — numbers that
    # look like catastrophic miscalibration and are actually a degenerate fit. Report UNDEFINED.
    spread = _sd(ps)
    est, why = calibration_estimable(ps)
    if not est:
        cal = {"intercept": None, "slope": None, "reason": why}
    else:
        cal = PE.calibration([{"p_home_challenger": p, "home_result": y} for p, y in zip(ps, ys)])
    return {
        "n": n,
        "record": f"{sum(correct)}-{n - sum(correct)}",
        "accuracy": _mean([float(c) for c in correct]),
        "brier": b,
        "logloss": ll,
        "prior_brier": pb,
        "prior_logloss": pll,
        "brier_skill_score": brier_skill(b, pb),
        "logloss_improvement_over_prior": (pll - ll) if (pll is not None and ll is not None) else None,
        "calibration_intercept": cal.get("intercept"),
        "calibration_slope": cal.get("slope"),
        "calibration_undefined_reason": cal.get("reason"),
        # TWO SEPARATE VERDICTS, never collapsed into one.
        "calibration_estimability": ESTIMABLE if est else NOT_ESTIMABLE,
        "calibration_estimability_reason": why,
        "calibration_acceptable": calibration_acceptable(cal.get("slope"), cal.get("intercept"))[0],
        "calibration_acceptability_reason": calibration_acceptable(cal.get("slope"),
                                                                   cal.get("intercept"))[1],
        "probability_spread_pp": (_sd(ps) * 100.0) if _sd(ps) is not None else None,
        "discrimination_auc": PE.auc([{"p_home_challenger": p, "home_result": y}
                                      for p, y in zip(ps, ys)]).get("auc"),
        "reliability": reliability([{"p_model": p, "home_win": y} for p, y in zip(ps, ys)]),
        "skill_ci": _skill_ci(rows, p_key, prior_key, y_key),
    }


def _skill_ci(rows, p_key, prior_key, y_key, reps=2000, seed=20260823):
    """Slate-clustered interval on the per-game Brier DIFFERENCE (model minus prior).

    Clustered on the slate for the same reason the paired evaluation is: the night is the unit of
    independence. Returns None when the rows carry no slate labels or fewer than two slates."""
    sel = [r for r in rows if r.get(prior_key) is not None and r.get("slate_date")]
    if len(sel) != len(rows) or len({r["slate_date"] for r in sel}) < 2:
        return None
    diffs = [{"slate_date": r["slate_date"],
              "delta_brier": (float(r[p_key]) - int(r[y_key])) ** 2
                             - (float(r[prior_key]) - int(r[y_key])) ** 2}
             for r in sel]
    bs = PE.slate_bootstrap(diffs, "delta_brier", reps=reps, seed=seed)
    pb = _mean([(float(r[prior_key]) - int(r[y_key])) ** 2 for r in sel])
    if bs.get("lo") is None or not pb:
        return None
    # skill = 1 - Bm/Bp = -(Bm - Bp)/Bp, so the interval flips sign and scales by the prior Brier
    return {"lo": -bs["hi"] / pb, "hi": -bs["lo"] / pb, "n_slates": bs["n_slates"],
            "cluster_unit": "slate_date"}


def continuous_metrics(rows, pred_key, actual_key):
    """MAE and SIGNED bias for margin or total. Signed convention: predicted minus actual."""
    sel = [r for r in rows if r.get(pred_key) is not None and r.get(actual_key) is not None]
    if not sel:
        return {"n": 0, "status": INSUFFICIENT}
    errs = [float(r[pred_key]) - float(r[actual_key]) for r in sel]
    a = sorted(abs(e) for e in errs)
    return {"n": len(sel), "mae": _mean([abs(e) for e in errs]),
            "median_abs_error": a[len(a) // 2],
            "signed_bias": _mean(errs),
            "largest_miss": max(a),
            "convention": "predicted minus actual; positive means the model projected too high"}


def ats_diagnostic(rows):
    """ATS is a DIAGNOSTIC record. It is reported and never presented as a wagering result."""
    sel = [r for r in rows if r.get("ats_result") in ("WIN", "LOSS", "PUSH")]
    if not sel:
        return {"n": 0, "status": INSUFFICIENT}
    w = sum(1 for r in sel if r["ats_result"] == "WIN")
    l = sum(1 for r in sel if r["ats_result"] == "LOSS")
    p = sum(1 for r in sel if r["ats_result"] == "PUSH")
    dec = w + l
    return {"n": len(sel), "record": f"{w}-{l}-{p}",
            "cover_rate_excluding_pushes": (w / dec) if dec else None,
            "classification": "DIAGNOSTIC — not a wagering result and never presented as one"}


def verdict(m):
    """THE RULE: a good record without skill over the expanding prior is not predictive progress.

    ORDER MATTERS. The interval is consulted BEFORE the point estimate's sign. A point skill of
    -0.038 whose slate-clustered interval spans zero is NOT evidence the model is worse than the
    prior — it is evidence of nothing, and calling it NEGATIVE_SKILL overclaims in the same way that
    calling +0.0009 progress overclaims. NEGATIVE_SKILL is reserved for an interval lying entirely
    below zero, or for a negative point estimate with no interval available at all."""
    n = m.get("n", 0)
    bss = m.get("brier_skill_score")
    rec = m.get("record")
    if n < SKILL_MIN_N:
        return {"verdict": INSUFFICIENT, "n": n, "required": SKILL_MIN_N,
                "note": f"{n} games is below the {SKILL_MIN_N}-game floor for a skill claim; the "
                        f"record is descriptive only"}
    if bss is None:
        return {"verdict": INSUFFICIENT, "n": n,
                "note": "no expanding-prior reference was supplied for every row, so skill cannot "
                        "be computed and no progress claim is available"}
    ci = m.get("skill_ci")
    if ci and ci.get("lo") is not None:
        lo, hi = ci["lo"], ci["hi"]
        span = f"slate-clustered interval [{lo:+.5f}, {hi:+.5f}] over {ci.get('n_slates')} slates"
        if hi < 0:
            return {"verdict": NEGATIVE_SKILL, "brier_skill_score": bss, "skill_ci": [lo, hi],
                    "record": rec,
                    "note": (f"record {rec} but the ENTIRE skill interval lies below zero ({span}): "
                             f"the probabilities SUBTRACTED information relative to the expanding "
                             f"prior. A winning record with negative skill is the combination this "
                             f"standard exists to surface.")}
        if lo > 0:
            return {"verdict": PREDICTIVE_PROGRESS, "brier_skill_score": bss, "skill_ci": [lo, hi],
                    "record": rec,
                    "note": f"Brier skill {bss:+.5f} over the expanding prior on {n} games, {span}"}
        return {"verdict": NO_PREDICTIVE_PROGRESS, "brier_skill_score": bss, "skill_ci": [lo, hi],
                "record": rec,
                "note": (f"Brier skill {bss:+.5f} but its {span} contains zero. A skill score whose "
                         f"interval spans zero is not evidence in either direction — it is not "
                         f"progress, and it is not proof the model is worse than the prior either.")}
    # NO INTERVAL AVAILABLE: fall back to the point estimate and say the magnitude is unqualified.
    if bss < 0:
        return {"verdict": NEGATIVE_SKILL, "brier_skill_score": bss, "record": rec,
                "note": (f"record {rec} but Brier skill {bss:+.5f}: the probabilities SUBTRACTED "
                         f"information relative to the expanding prior. NO INTERVAL SUPPLIED (one "
                         f"slate, or no slate labels), so the magnitude is unqualified.")}
    if bss == 0:
        return {"verdict": NO_PREDICTIVE_PROGRESS, "brier_skill_score": bss, "record": rec,
                "note": "skill is exactly zero; the model reproduced the prior"}
    return {"verdict": PREDICTIVE_PROGRESS, "brier_skill_score": bss, "record": rec,
            "note": (f"Brier skill {bss:+.5f} over the expanding prior on {n} games; "
                     f"NO INTERVAL SUPPLIED, so the magnitude is unqualified")}


CUT_KEYS = ("sport", "arm", "estimand", "information_class")


def report(rows):
    """The full standard. Never pools: every cut is keyed by sport / arm / estimand / dose."""
    cuts = {}
    for r in rows:
        key = tuple(str(r.get(k)) for k in CUT_KEYS)
        cuts.setdefault(key, []).append(r)
    out = {"cuts": {}, "never_pooled": list(CUT_KEYS),
           "pooling_note": ("Sport, arm, estimand and information class are four independent keys. "
                            "No total across them is computed, because a number pooled across them "
                            "describes no configuration.")}
    for key, sel in sorted(cuts.items()):
        label = " / ".join(key)
        est = key[2]
        block = {"n": len(sel), **dict(zip(CUT_KEYS, key))}
        if est == "winner":
            m = winner_metrics(sel)
            block.update(m)
            block["verdict"] = verdict(m)
        elif est in ("margin", "total"):
            block.update(continuous_metrics(sel, "predicted", "actual"))
        elif est == "ats":
            block.update(ats_diagnostic(sel))
        else:
            block["status"] = f"unrecognised estimand {est!r}"
        out["cuts"][label] = block
    return out


def paired_postgame(rows_a, rows_b, label_a="CHAMPION", label_b="CHALLENGER"):
    """WHERE the challenger gained or lost, game by game and then grouped.

    The owner asked for exactly this: not whether the challenger is better on average, but which
    games it won its advantage on and which it gave it back on."""
    by_a = {r["game_id"]: r for r in rows_a}
    by_b = {r["game_id"]: r for r in rows_b}
    common = sorted(set(by_a) & set(by_b))
    only_a, only_b = sorted(set(by_a) - set(by_b)), sorted(set(by_b) - set(by_a))
    per = []
    for g in common:
        a, b = by_a[g], by_b[g]
        y = int(a["home_win"])
        pa, pb = float(a["p_model"]), float(b["p_model"])
        ba, bb = (pa - y) ** 2, (pb - y) ** 2
        per.append({
            "game_id": g, "slate_date": a.get("slate_date"),
            "home_win": y,
            f"p_{label_a.lower()}": pa, f"p_{label_b.lower()}": pb,
            "brier_" + label_a.lower(): ba, "brier_" + label_b.lower(): bb,
            "delta_brier": bb - ba,
            "delta_logloss": PE.logloss(pb, y) - PE.logloss(pa, y),
            "direction": PE.move_direction(pa, pb),
            "winner_flip": (pa >= .5) != (pb >= .5),
            "gained": bb < ba,
            "information_class": b.get("information_class"),
            "information_fraction": b.get("information_fraction"),
        })
    gains = sorted([p for p in per if p["gained"]], key=lambda p: p["delta_brier"])
    losses = sorted([p for p in per if not p["gained"]], key=lambda p: -p["delta_brier"])
    return {
        "n_paired": len(per),
        "unpaired": {f"{label_a}_only": only_a, f"{label_b}_only": only_b,
                     "note": ("unpaired games are LISTED, never dropped silently — a comparison "
                              "that quietly narrows its own population reports a slate difference "
                              "as a model difference")},
        "mean_delta_brier": _mean([p["delta_brier"] for p in per]),
        "mean_delta_logloss": _mean([p["delta_logloss"] for p in per]),
        "n_gained": len(gains), "n_lost": len(losses),
        "total_brier_gained": -sum(p["delta_brier"] for p in gains),
        "total_brier_lost": sum(p["delta_brier"] for p in losses),
        "largest_gains": gains[:5],
        "largest_losses": losses[:5],
        "by_direction": _group(per, "direction"),
        "by_information_class": _group(per, "information_class"),
        "by_slate": _group(per, "slate_date"),
        "on_winner_flips": _group(per, lambda p: "FLIP" if p["winner_flip"] else "NO_FLIP"),
        "per_game": per,
    }


def _group(per, key):
    kf = key if callable(key) else (lambda p: p.get(key))
    g = {}
    for p in per:
        g.setdefault(str(kf(p)), []).append(p)
    return {k: {"n": len(v),
                "mean_delta_brier": _mean([x["delta_brier"] for x in v]),
                "mean_delta_logloss": _mean([x["delta_logloss"] for x in v]),
                "n_gained": sum(1 for x in v if x["gained"]),
                "n_lost": sum(1 for x in v if not x["gained"]),
                "net_brier": -sum(x["delta_brier"] for x in v)}
            for k, v in sorted(g.items())}


def selftest():
    f = []

    # --- BRIER SKILL ------------------------------------------------------------------------------
    if brier_skill(0.20, 0.25) != 1 - 0.8:
        f.append("brier_skill arithmetic wrong")
    if brier_skill(0.25, 0.25) != 0.0:
        f.append("a model reproducing the prior did not score exactly zero skill")
    if brier_skill(0.30, 0.25) >= 0:
        f.append("a model WORSE than the prior did not score negative skill")
    for a, b in ((None, 0.25), (0.2, None), (0.2, 0.0), (0.2, -1.0)):
        if brier_skill(a, b) is not None:
            f.append(f"brier_skill({a},{b}) returned a value instead of None")

    # --- THE CENTRAL RULE: A GOOD RECORD WITHOUT SKILL IS NOT PROGRESS -------------------------------
    # The 2026-08-21 shape: a strong record on a slate the prior called better.
    rows = []
    for i in range(40):
        y = 1 if i % 40 < 34 else 0            # a very home-heavy slate
        rows.append({"p_model": 0.56 if y else 0.56, "p_prior": 0.75, "home_win": y})
    m = winner_metrics(rows)
    v = verdict(m)
    if v["verdict"] != NEGATIVE_SKILL:
        f.append(f"a 34-6 record whose probabilities lost to the prior was graded {v['verdict']}")
    if "SUBTRACTED information" not in v.get("note", ""):
        f.append("the negative-skill verdict does not say the model subtracted information")
    if m["record"] != "34-6":
        f.append(f"record wrong: {m['record']}")
    # ...and a model that genuinely beats the prior IS progress
    good = [{"p_model": 0.85 if y else 0.15, "p_prior": 0.527, "home_win": y}
            for y in [1] * 30 + [0] * 15]
    vg = verdict(winner_metrics(good))
    if vg["verdict"] != PREDICTIVE_PROGRESS:
        f.append(f"a model clearly beating the prior was graded {vg['verdict']}")
    # exact zero skill is NOT progress
    same = [{"p_model": 0.6, "p_prior": 0.6, "home_win": y} for y in ([1] * 20 + [0] * 15)]
    if verdict(winner_metrics(same))["verdict"] != NO_PREDICTIVE_PROGRESS:
        f.append("a model exactly reproducing the prior was called progress")
    # a small sample cannot claim skill at all, however good it looks
    # HARD-CODED at 29 and 30. An earlier version sized this fixture as SKILL_MIN_N - 1, so it moved
    # with the constant and a mutant that dropped the floor to 1 sailed through: the fixture built
    # an EMPTY cohort and still saw INSUFFICIENT. A fixture defined in terms of the thing it is
    # testing cannot test it.
    if SKILL_MIN_N != 30:
        f.append(f"this block assumes a 30-game floor and SKILL_MIN_N is {SKILL_MIN_N}")
    tiny = [{"p_model": 0.9, "p_prior": 0.5, "home_win": 1} for _ in range(29)]
    if verdict(winner_metrics(tiny))["verdict"] != INSUFFICIENT:
        f.append("a 29-game sample was allowed a skill claim")
    if verdict(winner_metrics(tiny + [{"p_model": 0.9, "p_prior": 0.5, "home_win": 1}]))["verdict"] \
            == INSUFFICIENT:
        f.append("a sample at exactly 30 was still called insufficient")
    # no prior supplied -> no progress claim, not a default pass
    nopri = [{"p_model": 0.8, "p_prior": None, "home_win": 1} for _ in range(40)]
    if verdict(winner_metrics(nopri))["verdict"] != INSUFFICIENT:
        f.append("a cohort with no expanding-prior reference was still given a progress verdict")
    # ISOLATION: a PARTIAL reference set. The prior must cover EVERY row or skill is not computed —
    # a skill score built from the subset that happened to carry a reference is a comparison against
    # a different game population. Only the all-or-nothing check catches this.
    mixed_ref = ([{"p_model": 0.8, "p_prior": 0.527, "home_win": 1} for _ in range(20)] +
                 [{"p_model": 0.8, "p_prior": None, "home_win": 0} for _ in range(20)])
    mm = winner_metrics(mixed_ref)
    if mm["prior_brier"] is not None or mm["brier_skill_score"] is not None:
        f.append(f"skill was computed from a PARTIAL prior reference (20 of 40 rows): "
                 f"prior_brier={mm['prior_brier']}, bss={mm['brier_skill_score']}")
    if verdict(mm)["verdict"] != INSUFFICIENT:
        f.append("a cohort whose prior covered only half its rows was given a progress verdict")

    # --- NEGATIVE SKILL THROUGH THE INTERVAL BRANCH ------------------------------------------------
    # The 2026-08-21 shape WITH slate labels: a strong record on home-heavy nights whose
    # probabilities lost to the prior on BOTH slates, so the whole interval sits below zero. The
    # earlier version of this fixture carried no slate labels and therefore only ever exercised the
    # no-interval fallback, leaving the interval branch — the one that governs — unproven.
    # the two slates must differ, or the bootstrap returns a zero-width interval and cannot
    # distinguish slate clustering from game clustering
    neg = []
    for d, pm in (("2026-08-19", 0.52), ("2026-08-21", 0.58)):
        for i in range(20):
            y = 1 if i % 20 < 17 else 0        # home-heavy
            neg.append({"slate_date": d, "p_model": pm, "p_prior": 0.80, "home_win": y})
    nm = winner_metrics(neg)
    nv = verdict(nm)
    if nm.get("skill_ci") is None:
        f.append("no skill interval was computed for a labelled two-slate cohort")
    else:
        lo, hi = nm["skill_ci"]["lo"], nm["skill_ci"]["hi"]
        if hi >= 0:
            f.append(f"a model clearly worse than the prior on both slates gave an interval "
                     f"[{lo:+.5f}, {hi:+.5f}] that reaches zero")
        if lo >= hi:
            f.append(f"the two-slate interval has no width [{lo:+.5f}, {hi:+.5f}] — the slates are "
                     f"identical, so nothing here can tell slate clustering from game clustering")
        # THE RESAMPLING UNIT IS THE SLATE. 40 games across 2 nights must resample 2 blocks, not 40
        # rows. Interval WIDTH cannot prove this — with high within-slate variance and close slate
        # means, game resampling is actually WIDER here — so the unit itself is asserted.
        if nm["skill_ci"].get("n_slates") != 2:
            f.append(f"the skill interval resampled {nm['skill_ci'].get('n_slates')} units over 40 "
                     f"games on 2 nights; the unit of independence is the slate")
        if nm["skill_ci"].get("cluster_unit") != "slate_date":
            f.append("the skill interval does not declare the slate as its clustering unit")
        if nm["brier_skill_score"] is not None and not (lo - 1e-9 <= nm["brier_skill_score"] <= hi + 1e-9):
            f.append("the point skill lies outside its interval — the Brier difference was not "
                     "converted into a skill score with its sign flipped")
    if nv["verdict"] != NEGATIVE_SKILL:
        f.append(f"a cohort whose whole skill interval sits below zero was graded {nv['verdict']}")
    if "SUBTRACTED information" not in nv.get("note", ""):
        f.append("the interval-branch negative verdict does not say the model subtracted information")
    if "combination this standard exists to surface" not in nv.get("note", ""):
        f.append("the negative verdict does not name why a winning record with negative skill matters")
    if nm["accuracy"] is None or nm["accuracy"] <= 0.5:
        f.append("the negative-skill fixture does not actually carry a WINNING record, so it cannot "
                 "prove the verdict is driven by skill rather than by the record")

    # --- MATERIALITY: a positive SIGN with no distance from zero is not progress ------------------
    # The real case: a challenger scored +0.00094 skill on 30 games across two slates.
    # The two slates must DISAGREE, or the slate bootstrap resamples identical blocks and returns a
    # zero-width interval that cannot span zero — which is how the first version of this fixture
    # passed while proving nothing. Slate A favours the model, slate B favours the prior.
    thin = []
    for i in range(15):
        y = 1 if i % 3 else 0
        thin.append({"slate_date": "2026-08-19", "p_model": 0.560 if y else 0.500,
                     "p_prior": 0.527, "home_win": y})
    for i in range(15):
        y = 1 if i % 3 else 0
        thin.append({"slate_date": "2026-08-21", "p_model": 0.500 if y else 0.560,
                     "p_prior": 0.527, "home_win": y})
    tm = winner_metrics(thin)
    tv = verdict(tm)
    if tm.get("skill_ci") is None:
        f.append("no slate-clustered skill interval was computed for a two-slate cohort")
    else:
        lo, hi = tm["skill_ci"]["lo"], tm["skill_ci"]["hi"]
        if not (lo < 0 < hi):
            f.append(f"two disagreeing slates did not produce an interval spanning zero "
                     f"[{lo:+.5f}, {hi:+.5f}] — the bootstrap is not resampling the slates as blocks")
        if tv["verdict"] != NO_PREDICTIVE_PROGRESS:
            f.append(f"a skill interval spanning zero was still graded {tv['verdict']}")
        if "contains zero" not in tv.get("note", ""):
            f.append("the refusal does not say the interval contains zero")
        # the interval must be oriented as SKILL: positive means better than the prior
        if tm["brier_skill_score"] is not None and not (lo - 1e-9 <= tm["brier_skill_score"] <= hi + 1e-9):
            f.append(f"the point skill {tm['brier_skill_score']:+.5f} lies outside its own "
                     f"interval [{lo:+.5f}, {hi:+.5f}] — the sign was not flipped when converting "
                     f"a Brier difference into a skill score")
    if tv["verdict"] == PREDICTIVE_PROGRESS and "interval" not in tv.get("note", ""):
        f.append("a progress verdict was issued without qualifying its magnitude")
    # a cohort with ONE slate cannot produce an interval, and must say the magnitude is unqualified
    one = [dict(r, slate_date="2026-08-21") for r in good]
    ov = verdict(winner_metrics(one))
    if ov["verdict"] == PREDICTIVE_PROGRESS and "NO INTERVAL SUPPLIED" not in ov["note"]:
        f.append("a single-slate progress claim did not say its magnitude is unqualified")

    # --- CALIBRATION IS UNDEFINED ON A CONSTANT FORECAST -------------------------------------------
    # The expanding prior emits the same probability every game. Fitting a recalibration line to it
    # produced intercept +189 / slope -2139 on real data, which reads as catastrophic
    # miscalibration and is a degenerate fit.
    # NEARLY constant, not exactly: this is the real expanding-prior arm, whose value drifts a hair
    # between slate dates. An exact-equality guard missed it and it drew a slope of -2139.
    const = [{"p_model": 0.527 + (0.00002 if i % 2 else 0.0), "p_prior": 0.527, "home_win": y}
             for i, y in enumerate([1] * 22 + [0] * 8)]
    cm = winner_metrics(const)
    if cm["calibration_slope"] is not None or cm["calibration_intercept"] is not None:
        f.append(f"a CONSTANT forecast was given a calibration line: intercept "
                 f"{cm['calibration_intercept']} slope {cm['calibration_slope']}")
    if not cm.get("calibration_undefined_reason"):
        f.append("a constant forecast reported no reason for its undefined calibration")
    if "undefined, not miscalibrated" not in (cm.get("calibration_undefined_reason") or ""):
        f.append("the undefined-calibration reason does not distinguish it from miscalibration")
    # THE RULE IS DERIVED, NOT TUNED. It must have NO free parameter: the floor is sqrt(float64 eps)
    # and is reconstructable from the arithmetic alone.
    if abs(RCOND_FLOOR - math.sqrt(sys.float_info.epsilon)) > 0:
        f.append("the conditioning floor is not exactly sqrt(float64 epsilon)")
    if CONDITIONING_RULE_REGISTERED_UTC != "2026-08-23T00:00:00Z":
        f.append("the conditioning rule carries no frozen registration date")
    # a truly CONSTANT forecast is refused on the distinct-value rule
    est, why = calibration_estimable([0.527] * 30)
    if est or "single value" not in why:
        f.append(f"a constant forecast was called estimable: {why}")
    # the REAL near-constant prior arm is refused on the CONDITIONING rule, not on a spread threshold
    near = [0.527 + (0.00002 if i % 2 else 0.0) for i in range(30)]
    est, why = calibration_estimable(near)
    if est:
        f.append("the near-constant expanding-prior arm was called estimable — this is the case the "
                 "tuned threshold had to be widened for, and the derived rule must catch it")
    if "condition number" not in why or "sqrt(eps)" not in why:
        f.append(f"the refusal does not cite the conditioning rule: {why}")
    # a forecast with REAL spread keeps its calibration line
    for ps in ([0.50 + 0.03 * (i % 3) for i in range(30)], [0.35, 0.45, 0.55, 0.65] * 8):
        if not calibration_estimable(ps)[0]:
            f.append(f"a forecast with real spread was refused a calibration line: "
                     f"{calibration_estimable(ps)[1]}")
    # fewer than three games is refused whatever the spread
    if calibration_estimable([0.3, 0.7])[0]:
        f.append("a two-game cohort was given a calibration line")

    # --- ESTIMABLE IS NOT ACCEPTABLE ---------------------------------------------------------------
    # A forecast can be perfectly estimable and catastrophically miscalibrated. That is the normal
    # case, and conflating the two would let the arithmetic vouch for the statistics.
    wide = [0.35, 0.45, 0.55, 0.65] * 8
    if not calibration_estimable(wide)[0]:
        f.append("the estimability fixture is not actually estimable")
    if calibration_acceptable(-0.574, 1.028)[0]:
        f.append("the real all-CAP arm (slope -0.574, intercept 1.028) was called acceptable "
                 "despite being perfectly estimable")
    if calibration_acceptable(1.109, 0.954)[0]:
        f.append("the real challenger arm (slope 1.109, intercept 0.954) was called acceptable; "
                 "its intercept is far outside the band")
    if not calibration_acceptable(1.05, 0.10)[0]:
        f.append("a genuinely well-calibrated arm was refused")
    # UNDEFINED IS NOT ACCEPTABLE
    ok_a, why_a = calibration_acceptable(None, None)
    if ok_a:
        f.append("an UNDEFINED calibration was called acceptable — the least measurable arm would "
                 "clear the strictest condition")
    if "not the same as acceptable" not in why_a:
        f.append("the undefined-calibration refusal does not distinguish undefined from acceptable")
    # the boundaries
    for sl, ic, want in ((0.80, 0.0, True), (0.79, 0.0, False), (1.25, 0.0, True),
                         (1.26, 0.0, False), (1.0, 0.50, True), (1.0, 0.51, False),
                         (1.0, -0.51, False)):
        if calibration_acceptable(sl, ic)[0] != want:
            f.append(f"calibration_acceptable({sl}, {ic}) = {calibration_acceptable(sl, ic)[0]}, "
                     f"expected {want}")
    # the two verdicts are carried SEPARATELY on every metrics block
    m2 = winner_metrics([{"p_model": p, "p_prior": 0.527, "home_win": i % 2}
                         for i, p in enumerate(wide)])
    for k in ("calibration_estimability", "calibration_acceptable",
              "calibration_estimability_reason", "calibration_acceptability_reason"):
        if k not in m2:
            f.append(f"the metrics block does not carry {k}")
    if m2["calibration_estimability"] != ESTIMABLE:
        f.append("a well-conditioned arm was not marked estimable")
    # ISOLATION: an arm that is ESTIMABLE and NOT ACCEPTABLE. Only a case where the two verdicts
    # DISAGREE can prove they are computed separately; where they happen to agree, substituting one
    # for the other is invisible.
    badcal = ([{"p_model": 0.95, "p_prior": 0.527, "home_win": 1} for _ in range(14)] +
              [{"p_model": 0.95, "p_prior": 0.527, "home_win": 0} for _ in range(6)] +
              [{"p_model": 0.05, "p_prior": 0.527, "home_win": 0} for _ in range(14)] +
              [{"p_model": 0.05, "p_prior": 0.527, "home_win": 1} for _ in range(6)])
    mb = winner_metrics(badcal)
    if mb["calibration_estimability"] != ESTIMABLE:
        f.append("a widely-spread overconfident arm was not numerically estimable")
    if mb["calibration_acceptable"] is not False:
        f.append(f"an arm with slope {mb['calibration_slope']:.3f} was called calibration-ACCEPTABLE "
                 f"merely because its fit was numerically estimable — the two verdicts are being "
                 f"conflated")
    # a VARYING forecast still gets its calibration line
    if winner_metrics(good)["calibration_slope"] is None:
        f.append("a varying forecast lost its calibration line")

    # --- RELIABILITY BY BUCKET -----------------------------------------------------------------------
    rel = reliability([{"p_model": 0.62, "home_win": 1} for _ in range(10)] +
                      [{"p_model": 0.62, "home_win": 0} for _ in range(5)] +
                      [{"p_model": 0.47, "home_win": 0} for _ in range(2)])
    b60 = next(b for b in rel if b["bucket"] == "[0.60,0.70)")
    if b60["status"] != "MEASURED" or abs(b60["observed_frequency"] - 10 / 15) > 1e-9:
        f.append(f"a populated bucket was mismeasured: {b60}")
    if abs(b60["gap"] - (10 / 15 - 0.62)) > 1e-9:
        f.append("the reliability gap is not observed minus forecast")
    b45 = next(b for b in rel if b["bucket"] == "[0.45,0.50)")
    if b45["status"] != INSUFFICIENT or b45["observed_frequency"] is not None:
        f.append(f"a 2-row bucket reported an observed frequency: {b45}")
    if b45["n"] != 2:
        f.append("an insufficient bucket did not report its n")
    if sum(b["n"] for b in rel) != 17:
        f.append("the reliability buckets do not partition the rows")

    # --- CONTINUOUS -----------------------------------------------------------------------------------
    c = continuous_metrics([{"predicted": 9.0, "actual": 7.0}, {"predicted": 8.0, "actual": 9.0},
                            {"predicted": 10.0, "actual": 4.0}], "predicted", "actual")
    if abs(c["mae"] - 3.0) > 1e-9 or abs(c["signed_bias"] - 7 / 3) > 1e-9:
        f.append(f"continuous metrics wrong: {c}")
    if c["largest_miss"] != 6.0:
        f.append("largest miss wrong")
    if "predicted minus actual" not in c["convention"]:
        f.append("the signed-error convention is not stated")

    # --- ATS IS A DIAGNOSTIC --------------------------------------------------------------------------
    a = ats_diagnostic([{"ats_result": "WIN"}, {"ats_result": "WIN"}, {"ats_result": "LOSS"},
                        {"ats_result": "PUSH"}])
    if a["record"] != "2-1-1" or abs(a["cover_rate_excluding_pushes"] - 2 / 3) > 1e-9:
        f.append(f"ATS record wrong: {a}")
    if "DIAGNOSTIC" not in a["classification"]:
        f.append("the ATS block is not labelled a diagnostic")

    # --- NEVER POOLED ----------------------------------------------------------------------------------
    mixed = ([{"sport": "mlb", "arm": "CHALLENGER", "estimand": "winner",
               "information_class": "ALL_CAP_BASELINE", "p_model": 0.6, "p_prior": 0.527,
               "home_win": 1} for _ in range(5)] +
             [{"sport": "wnba", "arm": "CHALLENGER", "estimand": "winner",
               "information_class": "FULL_STARTER_INFORMATION", "p_model": 0.7, "p_prior": 0.55,
               "home_win": 0} for _ in range(5)])
    rep = report(mixed)
    if len(rep["cuts"]) != 2:
        f.append(f"two different sports/classes collapsed into {len(rep['cuts'])} cut(s)")
    if any(k in rep for k in ("total", "overall", "pooled")):
        f.append("the report emits a pooled total across cuts")
    if set(rep["never_pooled"]) != set(CUT_KEYS):
        f.append("the report does not declare its four non-pooled keys")
    for label, blk in rep["cuts"].items():
        if blk["n"] != 5:
            f.append(f"cut {label} has n={blk['n']}, expected 5")

    # --- PAIRED POSTGAME --------------------------------------------------------------------------------
    A = [{"game_id": f"g{i}", "slate_date": "2026-08-21", "p_model": 0.50, "home_win": i % 2}
         for i in range(6)]
    B = [{"game_id": f"g{i}", "slate_date": "2026-08-21",
          "p_model": 0.70 if i % 2 else 0.55, "home_win": i % 2,
          "information_class": "PARTIAL_STARTER_INFORMATION"} for i in range(6)]
    pg = paired_postgame(A, B)
    if pg["n_paired"] != 6:
        f.append(f"paired postgame covered {pg['n_paired']} games, expected 6")
    if pg["n_gained"] != 3 or pg["n_lost"] != 3:
        f.append(f"gain/loss split wrong: {pg['n_gained']} gained, {pg['n_lost']} lost")
    if pg["mean_delta_brier"] is None:
        f.append("no mean delta was reported")
    if not pg["largest_gains"] or pg["largest_gains"][0]["delta_brier"] > 0:
        f.append("the largest gain is not a negative delta")
    if not pg["largest_losses"] or pg["largest_losses"][0]["delta_brier"] < 0:
        f.append("the largest loss is not a positive delta")
    if abs(pg["total_brier_gained"] + sum(p["delta_brier"] for p in pg["largest_gains"])) > 1e-9:
        f.append("total gained does not reconcile with the per-game gains")
    for k in ("by_direction", "by_information_class", "by_slate", "on_winner_flips"):
        if k not in pg:
            f.append(f"the paired postgame omits {k}")
    # UNPAIRED GAMES ARE LISTED, NEVER DROPPED
    pg2 = paired_postgame(A + [{"game_id": "extra", "p_model": 0.5, "home_win": 1}], B)
    if pg2["n_paired"] != 6:
        f.append("an unpaired game was silently included")
    if pg2["unpaired"]["CHAMPION_only"] != ["extra"]:
        f.append(f"an unpaired game was not listed: {pg2['unpaired']}")
    if "never dropped silently" not in pg2["unpaired"]["note"]:
        f.append("the unpaired block does not state that games are never dropped silently")

    # --- exact small-sample nulls (owner correction 1, 2026-08-23) -------------------------------
    # the WNBA subgroup that produced the error: one home win, three away wins, perfect AUC
    if auc_null_probability(1, 3) != 0.25:
        f.append(f"P(perfect AUC | 1 pos, 3 neg) must be 1/4, got {auc_null_probability(1, 3)}")
    if abs(directional_null_probability(4, 4) - 0.0625) > 1e-12:
        f.append("P(4 of 4 under a fair coin) must be 1/16")
    # the two nulls are DIFFERENT numbers on the same four games — quoting one for the other is the bug
    if auc_null_probability(1, 3) == directional_null_probability(4, 4):
        f.append("the AUC null and the record null must not coincide on this shape")
    # 1/24 is the probability of one specific ordering of four items and is NOT either test
    if abs(auc_null_probability(1, 3) - 1.0 / 24) < 1e-9:
        f.append("the AUC null must not equal 1/24, the wrong figure that motivated this function")
    if auc_null_probability(2, 2) != 1.0 / 6:
        f.append("P(perfect AUC | 2 pos, 2 neg) must be 1/6")
    if auc_null_probability(1, 99) >= auc_null_probability(1, 3):
        f.append("a perfect AUC must get rarer as the negatives grow")
    # undefined shapes return null, never a number that reads as evidence
    for bad in ((0, 4), (4, 0), (-1, 3), (1.5, 3), (None, 3)):
        if auc_null_probability(*bad) is not None:
            f.append(f"auc_null_probability{bad} must be undefined, got a number")
    if directional_null_probability(5, 4) is not None:
        f.append("more correct than played must be undefined")
    if abs(directional_null_probability(0, 4) - 1.0) > 1e-12:
        f.append("at least 0 of 4 is certain")
    blk = small_sample_null(1, 3, n_correct=4)
    if blk["p_perfect_auc_under_random_scores"] != 0.25 or abs(blk["p_record_under_fair_coin"] - 0.0625) > 1e-12:
        f.append("small_sample_null must carry BOTH nulls")

    print("evaluation_standard selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("the AUC null uses the wrong combinatorial base, reproducing the 1/24 error",
     "    return 1.0 / math.comb(n_pos + n_neg, n_pos)",
     "    return 1.0 / math.factorial(n_pos + n_neg)"),
    ("the AUC null stops shrinking as the negatives grow",
     "    return 1.0 / math.comb(n_pos + n_neg, n_pos)", "    return 0.25"),
    ("the record null is returned for the AUC question",
     "    return 1.0 / math.comb(n_pos + n_neg, n_pos)", "    return 0.5 ** (n_pos + n_neg)"),
    ("a degenerate subgroup with no positives gets a null anyway",
     "    if not isinstance(n_pos, int) or not isinstance(n_neg, int) or n_pos < 1 or n_neg < 1:",
     "    if False:"),
    ("the record null drops its upper tail, so it stops being 'at least'",
     "    return sum(math.comb(n, k) for k in range(n_correct, n + 1)) / (2.0 ** n)",
     "    return math.comb(n, n_correct) / (2.0 ** n)"),
    ("more correct than played is accepted",
     "    if not isinstance(n, int) or not isinstance(n_correct, int) or n < 1 or not (0 <= n_correct <= n):",
     "    if False:"),
    ("Brier skill inverted, so a worse model reads as skilled",
     "    return 1.0 - (model_brier / prior_brier)", "    return (model_brier / prior_brier) - 1.0"),
    ("skill compares against a fixed .25 instead of the expanding prior",
     "    return 1.0 - (model_brier / prior_brier)", "    return 1.0 - (model_brier / 0.25)"),
    ("a degenerate reference still yields a skill number",
     "    if model_brier is None or prior_brier is None or prior_brier <= 0:", "    if False:"),
    ("NEGATIVE SKILL is graded as progress — the rule this module exists for",
     "        if hi < 0:", "        if False:"),
    ("a negative point skill with no interval is graded as progress",
     "    if bss < 0:\n        return {\"verdict\": NEGATIVE_SKILL, \"brier_skill_score\": bss, \"record\": rec,",
     "    if False:\n        return {\"verdict\": NEGATIVE_SKILL, \"brier_skill_score\": bss, \"record\": rec,"),
    ("zero skill counts as progress", "    if bss == 0:", "    if False:"),
    ("the verdict is driven by the RECORD instead of by skill",
     "        if hi < 0:", '        if m.get("accuracy", 1) < 0.5:'),
    ("a small sample may claim skill", "    if n < SKILL_MIN_N:", "    if False:"),
    ("the skill sample floor drops to nothing", "SKILL_MIN_N = 30", "SKILL_MIN_N = 1"),
    ("a skill interval spanning zero is graded as progress",
     "        if lo > 0:", "        if lo >= 0 or True:"),
    ("the interval is consulted AFTER the point sign, so a spanning interval reads as negative",
     '    ci = m.get("skill_ci")\n    if ci and ci.get("lo") is not None:',
     '    ci = None\n    if ci and ci.get("lo") is not None:'),
    ("the materiality interval is never computed",
     '        "skill_ci": _skill_ci(rows, p_key, prior_key, y_key),', '        "skill_ci": None,'),
    ("the skill interval is clustered on games instead of slates",
     '    bs = PE.slate_bootstrap(diffs, "delta_brier", reps=reps, seed=seed)',
     '    bs = PE.slate_bootstrap([dict(d, slate_date=str(i)) for i, d in enumerate(diffs)], "delta_brier", reps=reps, seed=seed)'),
    ("the skill interval keeps the sign of the Brier difference instead of flipping it",
     '    return {"lo": -bs["hi"] / pb, "hi": -bs["lo"] / pb,',
     '    return {"lo": bs["lo"] / pb, "hi": bs["hi"] / pb,'),
    ("an UNDEFINED calibration is treated as acceptable",
     "    if slope is None or intercept is None:", "    if False:"),
    ("estimability is allowed to stand in for acceptability",
     '        "calibration_acceptable": calibration_acceptable(cal.get("slope"), cal.get("intercept"))[0],',
     '        "calibration_acceptable": est,'),
    ("the calibration slope band is removed",
     "def calibration_acceptable(slope, intercept, slope_band=(0.80, 1.25), intercept_abs_max=0.50):",
     "def calibration_acceptable(slope, intercept, slope_band=(-99, 99), intercept_abs_max=99):"),
    ("the intercept band is removed",
     "    if abs(intercept) > intercept_abs_max:", "    if False:"),
    ("the undefined refusal stops distinguishing undefined from acceptable",
     '"same as acceptable and must never be read as it")',
     '"and that is fine.")'),
    ("a near-constant forecast is given a calibration line anyway",
     "    if rcond <= RCOND_FLOOR:", "    if False:"),
    ("the conditioning floor is tightened below the float64 rule, missing a near-constant arm",
     "RCOND_FLOOR = math.sqrt(FLOAT64_EPS)", "RCOND_FLOOR = FLOAT64_EPS * 1e-6"),
    ("the conditioning floor is widened until real forecasts lose their calibration",
     "RCOND_FLOOR = math.sqrt(FLOAT64_EPS)", "RCOND_FLOOR = 0.5"),
    ("the distinct-value rule is dropped, so an exactly constant forecast is fitted",
     "    if len({round(float(p), 12) for p in ps}) < MIN_DISTINCT_FORECASTS:", "    if False:"),
    ("the three-game floor on a calibration line is dropped",
     "    if len(ps) < 3:", "    if False:"),
    ("the conditioning refusal stops citing the rule",
     'f"or below the preregistered float64 floor sqrt(eps)={RCOND_FLOOR:.3e}: the "',
     'f"or below a floor: the "'),
    ("an undefined calibration stops being distinguished from miscalibration",
     'f"solve is dominated by rounding, so this is undefined, not miscalibrated")',
     'f"solve is dominated by rounding.")'),
    ("a cohort with no prior reference gets a progress verdict by default",
     "    if bss is None:", "    if False:"),
    ("the negative-skill verdict stops saying the model subtracted information",
     '                             f"prior. A winning record with negative skill is the combination this "',
     '                             f"prior. Fine. "'),
    ("prior metrics are computed from a partial reference set",
     "    pb = _mean([(p - y) ** 2 for p, y in zip(pri, ys)]) if len(pri) == n else None",
     "    pb = _mean([(p - y) ** 2 for p, y in zip(pri, ys)]) if pri else None"),
    ("thin reliability buckets report an observed frequency anyway",
     "        if n < min_n:", "        if False:"),
    ("the reliability floor drops to one row", "BUCKET_MIN_N = 5", "BUCKET_MIN_N = 1"),
    ("the reliability gap is forecast minus observed, flipping every sign",
     '                          "gap": (of - mf) if (of is not None and mf is not None) else None})',
     '                          "gap": (mf - of) if (of is not None and mf is not None) else None})'),
    ("signed bias becomes actual minus predicted",
     "    errs = [float(r[pred_key]) - float(r[actual_key]) for r in sel]",
     "    errs = [float(r[actual_key]) - float(r[pred_key]) for r in sel]"),
    ("MAE is computed on signed errors, so misses cancel",
     '    return {"n": len(sel), "mae": _mean([abs(e) for e in errs]),',
     '    return {"n": len(sel), "mae": _mean([e for e in errs]),'),
    ("ATS pushes are counted as covers",
     '    return {"n": len(sel), "record": f"{w}-{l}-{p}",\n            "cover_rate_excluding_pushes": (w / dec) if dec else None,',
     '    return {"n": len(sel), "record": f"{w}-{l}-{p}",\n            "cover_rate_excluding_pushes": ((w + p) / len(sel)) if sel else None,'),
    ("ATS stops being labelled a diagnostic",
     '            "classification": "DIAGNOSTIC — not a wagering result and never presented as one"}',
     '            "classification": "wagering record"}'),
    ("the report pools across sport and information class",
     "        key = tuple(str(r.get(k)) for k in CUT_KEYS)", '        key = ("all",)'),
    ("the report stops declaring which keys are never pooled",
     '    out = {"cuts": {}, "never_pooled": list(CUT_KEYS),', '    out = {"cuts": {}, "never_pooled": [],'),
    ("the paired postgame silently drops unpaired games instead of listing them",
     "    only_a, only_b = sorted(set(by_a) - set(by_b)), sorted(set(by_b) - set(by_a))",
     "    only_a, only_b = [], []"),
    ("gains and losses are partitioned on the wrong side",
     '            "gained": bb < ba,', '            "gained": bb > ba,'),
    ("the paired delta is baseline minus challenger, flipping the sign",
     '            "delta_brier": bb - ba,', '            "delta_brier": ba - bb,'),
    ("the winner-flip split is dropped from the postgame report",
     '        "on_winner_flips": _group(per, lambda p: "FLIP" if p["winner_flip"] else "NO_FLIP"),', ""),
    ("the information-class split is dropped from the postgame report",
     '        "by_information_class": _group(per, "information_class"),', ""),
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
            pr = _sp.run([sys.executable, path, "--selftest"], capture_output=True, text=True, timeout=180)
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
