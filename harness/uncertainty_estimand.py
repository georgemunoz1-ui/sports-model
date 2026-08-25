"""What "model uncertainty" IS, stated precisely enough that nothing else can wear the name.

THE DEFECT THIS MODULE EXISTS TO PREVENT. A screen that needs a per-game uncertainty and cannot
produce one is under quiet pressure to accept a nearby number that has the right units. Four
candidates are always lying around, all in percentage points, all easy to compute, none of them the
estimand:

  raw Bernoulli residual SD  sqrt(p(1-p)) ~ 50pp at p~0.5. This is OUTCOME noise: how much a single
                             coin flip varies. It does not shrink with more data, it is largest
                             exactly where the model is most honest, and it says NOTHING about how
                             wrong p is. It is the most dangerous impostor because it is the easiest
                             to compute from the forecast alone.
  cross-game dispersion      how much the arm separates games on one slate. A signal-strength
                             statistic, not an error bar.
  prior parameter SD         posterior SD of the expanding prior's parameter. Shrinks as sqrt(1/n)
                             and describes ONE arm's parameter, not the deployed model's error.
  Monte Carlo error          simulation noise at the trial count. Shrinks by running longer, which
                             would make the screen more confident without new evidence.

THE ESTIMAND. Let a DATE BLOCK b hold n_b graded forecasts (p_i, y_i), y_i in {0,1}. Define the
block-mean signed calibration residual

    r_b = (1 / n_b) * sum_i (y_i - p_i)

r_b is an average of Bernoulli residuals, so the coin-flip component shrinks as 1/sqrt(n_b) while
any systematic miscalibration on that date survives. The estimand is the standard deviation of the
distribution the r_b are drawn from:

    sigma_epistemic = SD(r_b)

estimated across k blocks by the ordinary sample SD, ddof=1:

    s_k = sqrt( (1 / (k - 1)) * sum_b (r_b - rbar)^2 )

Date blocks, not games, because forecasts made on one day share a feature vintage, a slate, and a
model state; treating games as independent draws counts one correlated error k_games times.

WHAT k=2 ACTUALLY MEANS — the owner's correction, and it matters. "Two numbers are not a standard
deviation" is FALSE. At k=2 the sample SD is perfectly well defined and equals |r_1 - r_2| / sqrt(2).
The problem is not existence, it is STABILITY: with 1 degree of freedom the sampling distribution of
s is enormous. Under normality the 95% interval for the true sigma given s at k=2 spans roughly
[0.446 s, 31.9 s] — a factor of about 71 end to end. An interval that wide cannot size a bet, cannot
reject a hypothesis, and cannot be reported as an error bar without implying a precision it does not
have. So the refusal is REFUSED_TOO_UNSTABLE_FOR_DECISION_USE, with the computed value shown, and
never "undefined".
"""

MODULE_ID = "uncertainty_estimand"

import math
import sys

ESTIMAND = "SD_OF_BLOCK_MEAN_SIGNED_CALIBRATION_RESIDUAL"
FORMULA = "r_b = mean_i(y_i - p_i) over date block b;  s_k = sqrt(sum_b (r_b - rbar)^2 / (k - 1))"
BLOCK_UNIT = "DATE"
DDOF = 1

#: every quantity that is NOT this estimand, with the reason it cannot stand in
NOT_THE_ESTIMAND = {
    "BERNOULLI_OUTCOME_SD": "sqrt(p(1-p)) — outcome noise, not model error. Does not shrink with "
                            "data and is largest where the model is best calibrated.",
    "CROSS_GAME_P_SD": "dispersion of p across a slate — signal strength, not error.",
    "PRIOR_PARAMETER_SD": "posterior SD of one arm's prior parameter — not the deployed model's "
                          "forecast error.",
    "MONTE_CARLO_SD": "simulation noise at a trial count — shrinks by running longer, which would "
                      "buy confidence without evidence.",
    "REALISED_EDGE_SD": "SD of realised betting edge — a downstream P&L statistic that mixes model "
                        "error with price movement.",
}

REFUSED_NO_BLOCKS = "REFUSED_NO_ADMISSIBLE_BLOCKS"
REFUSED_SINGLE = "REFUSED_SINGLE_BLOCK_SD_UNDEFINED"
REFUSED_UNSTABLE = "REFUSED_TOO_UNSTABLE_FOR_DECISION_USE"
OK = "SIGMA_EPISTEMIC_ESTIMATED"

#: TWO DIFFERENT THRESHOLDS, AND CONFLATING THEM WAS THE DEFECT.
#:
#: MIN_COMPUTABLE_CLUSTERS is the point below which the statistic cannot be FORMED at a useful
#: resolution: ceil(log2(2/alpha)) = 6 at alpha=0.05, because an exact cluster sign-flip test over k
#: clusters has minimum two-sided p = 2/2^k and cannot reach 0.05 below k=6 at ANY effect size. That
#: is a statement about arithmetic. It says nothing about whether the estimate is any good.
#:
#: I previously called this MIN_BLOCKS_FOR_DECISION, which asserted the opposite of what it measures.
#: Clearing it means the number exists. It does not mean the number can size a bet.
MIN_COMPUTABLE_CLUSTERS = 6
MIN_BLOCKS_FOR_DECISION = MIN_COMPUTABLE_CLUSTERS      # retained alias; do not use for decisions

#: DECISION GRADE is a different and much higher bar. Cluster-robust inference is unreliable with
#: few clusters, and the literature on wild-bootstrap cluster inference (Roodman, MacKinnon, Nielsen
#: and Webb, "Fast and wild: bootstrap inference in Stata using boottest", Stata Journal 2019, and
#: the MacKinnon-Webb work it builds on) puts the danger zone well above a handful — roughly 20
#: EFFECTIVE clusters before asymptotic behaviour can be relied on, and worse when cluster sizes are
#: unbalanced or one cluster is influential.
#:
#: EFFECTIVE, not nominal. Unbalanced clusters behave like fewer clusters. The Kish-style effective
#: count, (sum n_b)^2 / sum n_b^2, equals k exactly when every block is the same size and falls
#: below k as they diverge — so a pool of 7 dates with one huge slate is worth less than 7.
DECISION_GRADE_EFFECTIVE_CLUSTERS = 20.0
DECISION_GRADE_BASIS = ("Roodman, MacKinnon, Nielsen and Webb (Stata Journal, 2019) and the "
                        "MacKinnon-Webb few-clusters literature: cluster inference is unreliable "
                        "below roughly 20 effective clusters, and worse under imbalance or a single "
                        "influential cluster")

#: A single cluster must not be able to move the estimate materially. Leave-one-date-out: refit
#: without each date and measure how far s moves, relative to s itself.
MAX_LOO_RELATIVE_SHIFT = 0.25
#: and interval coverage must have been VALIDATED against outcomes, not assumed from a formula
COVERAGE_TOLERANCE_PP = 5.0

GRADE_COMPUTABLE = "COMPUTABLE_NOT_DECISION_GRADE"
GRADE_DECISION = "DECISION_GRADE"
GRADE_NOT_COMPUTABLE = "NOT_COMPUTABLE"
REFUSED_EFFECTIVE = "REFUSED_TOO_FEW_EFFECTIVE_CLUSTERS"
REFUSED_INFLUENTIAL = "REFUSED_INFLUENTIAL_CLUSTER_DOMINATES_THE_ESTIMATE"
REFUSED_COVERAGE = "REFUSED_INTERVAL_COVERAGE_NOT_VALIDATED"


def effective_clusters(sizes):
    """Kish-style effective cluster count: (sum n)^2 / sum n^2. Equals k only under balance."""
    ns = [float(n) for n in (sizes or []) if n and float(n) > 0]
    if not ns:
        return 0.0
    return (sum(ns) ** 2) / sum(n * n for n in ns)


def leave_one_date_out(block_residuals):
    """Refit s without each date. Returns (max_relative_shift, per_date), the influence diagnostic.

    An estimate that moves 40% when one date is dropped is not an estimate of a population
    parameter; it is a description of that date.
    """
    items = sorted((block_residuals or {}).items())
    k = len(items)
    if k < 3:
        return None, {}
    def _sd(vals):
        m = sum(vals) / len(vals)
        return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))
    full = _sd([v for _, v in items])
    per = {}
    for d, _ in items:
        rest = [v for dd, v in items if dd != d]
        per[d] = _sd(rest)
    if full <= 0:
        return None, per
    shifts = {d: abs(per[d] - full) / full for d in per}
    worst = max(shifts.values()) if shifts else 0.0
    return worst, {"full_sd": full, "loo_sd": per, "relative_shifts": shifts,
                   "most_influential": max(shifts, key=shifts.get) if shifts else None}


def grade(k_clusters, cluster_sizes=None, block_residuals=None, coverage=None,
          nominal_coverage=95.0):
    """The tier this estimator has actually reached. Four independent requirements, all needed."""
    eff = effective_clusters(cluster_sizes) if cluster_sizes else float(k_clusters or 0)
    out = {"k_nominal": k_clusters, "k_effective": eff,
           "min_computable": MIN_COMPUTABLE_CLUSTERS,
           "decision_grade_effective_required": DECISION_GRADE_EFFECTIVE_CLUSTERS,
           "basis": DECISION_GRADE_BASIS, "blockers": []}
    if (k_clusters or 0) < MIN_COMPUTABLE_CLUSTERS:
        out.update(grade=GRADE_NOT_COMPUTABLE)
        out["blockers"].append({"code": "BELOW_MIN_COMPUTABLE_CLUSTERS", "k": k_clusters,
                                "required": MIN_COMPUTABLE_CLUSTERS})
        return out
    if eff < DECISION_GRADE_EFFECTIVE_CLUSTERS:
        out["blockers"].append({"code": REFUSED_EFFECTIVE, "effective": eff,
                                "required": DECISION_GRADE_EFFECTIVE_CLUSTERS,
                                "note": "clearing the computable floor means the number exists, "
                                        "not that it can size a bet"})
    loo, detail = leave_one_date_out(block_residuals)
    out["leave_one_date_out"] = detail or None
    if loo is None:
        out["blockers"].append({"code": "LEAVE_ONE_DATE_OUT_NOT_RUN"})
    elif loo > MAX_LOO_RELATIVE_SHIFT:
        out["blockers"].append({"code": REFUSED_INFLUENTIAL, "max_relative_shift": loo,
                                "ceiling": MAX_LOO_RELATIVE_SHIFT,
                                "most_influential": detail.get("most_influential")})
    if coverage is None:
        out["blockers"].append({"code": REFUSED_COVERAGE,
                                "note": "coverage must be measured against realised outcomes, not "
                                        "assumed from the formula that produced the interval"})
    elif abs(float(coverage) - float(nominal_coverage)) > COVERAGE_TOLERANCE_PP:
        out["blockers"].append({"code": REFUSED_COVERAGE, "observed": coverage,
                                "nominal": nominal_coverage, "tolerance_pp": COVERAGE_TOLERANCE_PP})
    out["grade"] = GRADE_DECISION if not out["blockers"] else GRADE_COMPUTABLE
    return out

#: chi-square quantiles with 1..8 df, for the interval that shows HOW unstable a small-k s is.
_CHI2 = {1: (0.000982, 5.023886), 2: (0.050636, 7.377759), 3: (0.215795, 9.348404),
         4: (0.484419, 11.143287), 5: (0.831212, 12.832502), 6: (1.237344, 14.449375),
         7: (1.689869, 16.012764), 8: (2.179731, 17.534546)}


def block_residual(pairs):
    """r_b for one date block: the MEAN signed residual, which is what averages the coin flip away."""
    rows = [(float(p), float(y)) for p, y in (pairs or [])
            if p is not None and y is not None and 0.0 <= float(p) <= 1.0 and float(y) in (0.0, 1.0)]
    if not rows:
        return None, "NO_GRADED_PAIRS_IN_BLOCK"
    return sum(y - p for p, y in rows) / len(rows), None


def sigma_interval(s, k):
    """(lo, hi) 95% interval for the true sigma given s at k blocks — the honest width of a small k."""
    df = k - 1
    if df < 1 or s is None:
        return None, None
    lo_q, hi_q = _CHI2.get(df, (None, None))
    if lo_q is None:
        return None, None
    return s * math.sqrt(df / hi_q), s * math.sqrt(df / lo_q)


def estimate(blocks, min_blocks=MIN_COMPUTABLE_CLUSTERS):
    """blocks: {date: [(p, y), ...]}. Returns the estimate AND whether it may be used to decide."""
    res, skipped = {}, {}
    for date in sorted(blocks or {}):
        r, err = block_residual(blocks[date])
        (skipped if err else res)[date] = err if err else r
    k = len(res)
    out = {"estimand": ESTIMAND, "formula": FORMULA, "block_unit": BLOCK_UNIT, "ddof": DDOF,
           "k_blocks": k, "blocks_used": sorted(res), "blocks_skipped": skipped,
           "block_residuals": {d: res[d] for d in sorted(res)},
           "min_blocks_for_decision": min_blocks,
           "not_the_estimand": sorted(NOT_THE_ESTIMAND)}
    if k == 0:
        out.update(status=REFUSED_NO_BLOCKS, sigma_epistemic_pp=None, decision_admissible=False,
                   why="no date block held a gradable (p, y) pair")
        return out
    if k == 1:
        out.update(status=REFUSED_SINGLE, sigma_epistemic_pp=None, decision_admissible=False,
                   why="a sample SD with ddof=1 needs at least two blocks; at k=1 it is genuinely "
                       "undefined, not merely unstable")
        return out
    vals = [res[d] for d in sorted(res)]
    mean = sum(vals) / k
    s = math.sqrt(sum((v - mean) ** 2 for v in vals) / (k - 1))
    s_pp = 100.0 * s
    lo, hi = sigma_interval(s_pp, k)
    out.update(sigma_epistemic_pp=s_pp, mean_block_residual_pp=100.0 * mean,
               sigma_ci95_pp=[lo, hi],
               sigma_ci95_width_ratio=(hi / lo) if (lo and hi and lo > 0) else None)
    if k < min_blocks:
        # s == 0 is a real case (every block missed by the same amount) and its interval collapses
        # to a point. That is not precision — it is k blocks agreeing by luck — so the ratio is
        # reported as undefined rather than as 1.0, which would read as a perfect estimate.
        width = f"a factor of {hi / lo:.1f} end to end" if (lo and lo > 0) else \
                "an interval that collapses to a point only because s is exactly zero here"
        out.update(status=REFUSED_UNSTABLE, decision_admissible=False,
                   why=(f"s = {s_pp:.4f}pp IS defined at k={k} — this is computed, not undefined. "
                        f"With {k - 1} degree(s) of freedom its 95% interval for the true sigma runs "
                        f"[{lo:.4f}, {hi:.4f}]pp, {width}. That is not an error bar, it is an "
                        f"admission. Decision use requires k >= {min_blocks}."))
        return out
    out.update(status=OK, decision_admissible=True,
               why=f"k={k} blocks clears the floor of {min_blocks}; the interval is still reported "
                   f"beside the point estimate and is not decoration")
    return out


def rejects(name):
    """Why a named lookalike may not be substituted for the estimand."""
    return NOT_THE_ESTIMAND.get(name)


# =================================================================================================
def selftest():
    f = []

    # r_b averages the coin flip away: a perfectly calibrated block of pure noise has r_b near 0
    r, err = block_residual([(0.5, 1), (0.5, 0), (0.5, 1), (0.5, 0)])
    if err or abs(r) > 1e-12:
        f.append(f"a balanced block must give r_b = 0, got {r} {err}")
    # ...and a biased block keeps its bias, which is the whole point of a SIGNED residual
    rb, _ = block_residual([(0.4, 1), (0.4, 1), (0.4, 1), (0.4, 1)])
    if rb is None or abs(rb - 0.6) > 1e-12:
        f.append(f"a block where every 0.40 forecast won must give r_b = +0.60, got {rb}")
    # an UNSIGNED residual would report the same number for over- and under-confidence
    rneg, _ = block_residual([(0.6, 0), (0.6, 0), (0.6, 0), (0.6, 0)])
    if rneg is None or abs(rneg + 0.6) > 1e-12:
        f.append("the residual must be signed: the mirror-image block must give the opposite sign")
    if rb is not None and rneg is not None and abs(rb + rneg) > 1e-12:
        f.append("signed residuals must cancel between mirrored blocks")
    for bad in ([(None, 1)], [(0.5, None)], [(1.4, 1)], [(0.5, 2)], [], None):
        v, e = block_residual(bad)
        if v is not None or not e:
            f.append(f"an ungradable block must refuse, not average: {bad!r} -> {v}")

    # THE OWNER'S CORRECTION: k=2 is DEFINED. It must not be reported as undefined.
    two = estimate({"2026-08-19": [(0.55, 1)], "2026-08-21": [(0.52, 0)]})
    if two["k_blocks"] != 2:
        f.append("fixture is wrong: this must be a two-block estimate")
    if two["sigma_epistemic_pp"] is None:
        f.append("k=2 has a DEFINED sample SD; refusing to compute it repeats the error")
    if two["status"] != REFUSED_UNSTABLE:
        f.append(f"k=2 must refuse for INSTABILITY, not for undefinedness, got {two['status']}")
    if two["decision_admissible"]:
        f.append("k=2 must not be admissible for decisions")
    if "IS defined" not in (two["why"] or ""):
        f.append("the k=2 refusal must say the value is defined")
    # |r1 - r2| / sqrt(2) is the closed form at k=2; the code must reproduce it
    r1, r2 = 1 - 0.55, 0 - 0.52
    if abs(two["sigma_epistemic_pp"] - 100 * abs(r1 - r2) / math.sqrt(2)) > 1e-9:
        f.append("the k=2 SD must equal |r1 - r2| / sqrt(2)")
    # and the interval must be enormous, which is the actual argument
    lo, hi = two["sigma_ci95_pp"]
    if not (lo and hi) or hi / lo < 50:
        f.append(f"the k=2 interval must be reported and must be very wide, got ratio "
                 f"{(hi / lo) if lo else None}")

    one = estimate({"2026-08-19": [(0.55, 1)]})
    if one["status"] != REFUSED_SINGLE or one["sigma_epistemic_pp"] is not None:
        f.append("k=1 IS undefined at ddof=1 and must be refused differently from k=2")
    if one["status"] == two["status"]:
        f.append("undefined (k=1) and unstable (k=2) must be distinguishable refusals")

    # s == 0 is real (two blocks that missed identically) and must not read as a precise estimate
    zero = estimate({"a": [(0.5, 1), (0.5, 0)], "b": [(0.5, 0), (0.5, 1)]})
    if zero["sigma_epistemic_pp"] != 0.0:
        f.append("fixture is wrong: these two balanced blocks must give s exactly 0")
    if zero["status"] != REFUSED_UNSTABLE or zero["decision_admissible"]:
        f.append("a zero SD at k=2 is still inadmissible")
    if "exactly zero" not in (zero["why"] or ""):
        f.append("a collapsed interval must be explained as luck, not reported as precision")
    if zero["sigma_ci95_width_ratio"] is not None:
        f.append("a width ratio of 1.0 must not be published for a zero SD")

    none = estimate({})
    if none["status"] != REFUSED_NO_BLOCKS:
        f.append("no blocks must refuse with its own status")

    # a k above the floor is admissible, and still reports its interval
    many = {f"2026-08-{d:02d}": [(0.50, d % 2)] for d in range(10, 18)}
    ok = estimate(many)
    if ok["status"] != OK or not ok["decision_admissible"]:
        f.append(f"k={ok['k_blocks']} above the floor must be admissible, got {ok['status']}")
    if ok["sigma_ci95_pp"][0] is None:
        f.append("an admissible estimate must still report its interval")
    if ok["sigma_ci95_width_ratio"] >= two["sigma_ci95_width_ratio"]:
        f.append("more blocks must tighten the interval")

    # the impostors must be named and refused BY NAME, including the Bernoulli one
    for name in ("BERNOULLI_OUTCOME_SD", "CROSS_GAME_P_SD", "PRIOR_PARAMETER_SD", "MONTE_CARLO_SD"):
        if not rejects(name):
            f.append(f"{name} must be named as not-the-estimand")
    if "outcome noise" not in (rejects("BERNOULLI_OUTCOME_SD") or ""):
        f.append("the Bernoulli refusal must say why: it is outcome noise, not model error")
    if rejects("SD_OF_BLOCK_MEAN_SIGNED_CALIBRATION_RESIDUAL") is not None:
        f.append("the estimand itself must not appear in the impostor table")
    # a block of pure Bernoulli noise at p=0.5 has ~50pp residual SD per GAME and ~0 per BLOCK.
    # if the two were interchangeable this fixture could not distinguish them.
    per_game = math.sqrt(0.5 * 0.5) * 100
    per_block = abs(estimate({"a": [(0.5, 1), (0.5, 0)], "b": [(0.5, 0), (0.5, 1)]})
                    ["sigma_epistemic_pp"])
    if per_block >= per_game:
        f.append("the block estimand must be far smaller than raw Bernoulli SD on balanced blocks")

    # --- COMPUTABLE IS NOT DECISION GRADE --------------------------------------------------------
    if MIN_COMPUTABLE_CLUSTERS != 6 or DECISION_GRADE_EFFECTIVE_CLUSTERS != 20.0:
        f.append("the two thresholds are 6 computable and 20 effective")
    if DECISION_GRADE_EFFECTIVE_CLUSTERS <= MIN_COMPUTABLE_CLUSTERS:
        f.append("the decision-grade bar must be strictly higher than the computable floor")
    if "Roodman" not in DECISION_GRADE_BASIS:
        f.append("the decision-grade bar must cite its basis")

    # effective clusters: equals k under balance, falls below it under imbalance
    if abs(effective_clusters([10] * 7) - 7.0) > 1e-9:
        f.append("seven equal blocks are seven effective clusters")
    lop = effective_clusters([100, 5, 5, 5, 5, 5, 5])
    if not (1.0 < lop < 3.0):
        f.append(f"one dominant block must collapse the effective count, got {lop}")
    if lop >= 7.0:
        f.append("imbalance must REDUCE the effective count, never leave it at k")
    if effective_clusters([]) != 0.0 or effective_clusters([0, 0]) != 0.0:
        f.append("no blocks means no effective clusters")

    # the repository's ACTUAL position, both now and after a full restore
    now = grade(2, cluster_sizes=[15, 15])
    if now["grade"] != GRADE_NOT_COMPUTABLE:
        f.append(f"k=2 is not even computable, got {now['grade']}")
    after = grade(7, cluster_sizes=[15] * 7,
                  block_residuals={f"d{i}": 0.01 * i for i in range(7)}, coverage=95.0)
    if after["grade"] != GRADE_COMPUTABLE:
        f.append(f"k=7 balanced is computable and NOT decision grade, got {after['grade']}")
    if not any(b["code"] == REFUSED_EFFECTIVE for b in after["blockers"]):
        f.append("7 effective clusters must be refused against the 20 bar")
    if after["grade"] == GRADE_DECISION:
        f.append("restoring provenance does not by itself produce a decision-grade estimator")

    # a genuinely adequate estimator passes all four requirements
    good_res = {f"d{i}": (0.005 if i % 2 else -0.005) for i in range(24)}
    good = grade(24, cluster_sizes=[15] * 24, block_residuals=good_res, coverage=95.0)
    if good["grade"] != GRADE_DECISION:
        f.append(f"24 balanced clusters with stable LOO and validated coverage must pass: "
                 f"{good['blockers']}")

    # ...and each of the four requirements alone must be able to stop it
    if grade(24, cluster_sizes=[500] + [5] * 23, block_residuals=good_res,
             coverage=95.0)["grade"] == GRADE_DECISION:
        f.append("imbalance alone must block decision grade")
    infl = dict(good_res); infl["d0"] = 0.9
    g_infl = grade(24, cluster_sizes=[15] * 24, block_residuals=infl, coverage=95.0)
    if g_infl["grade"] == GRADE_DECISION:
        f.append("one influential date alone must block decision grade")
    if not any(b["code"] == REFUSED_INFLUENTIAL for b in g_infl["blockers"]):
        f.append("the influential-cluster diagnostic must name itself")
    if g_infl["leave_one_date_out"].get("most_influential") != "d0":
        f.append("the influence diagnostic must name WHICH date dominates")
    if grade(24, cluster_sizes=[15] * 24, block_residuals=good_res,
             coverage=None)["grade"] == GRADE_DECISION:
        f.append("unvalidated coverage alone must block decision grade")
    if grade(24, cluster_sizes=[15] * 24, block_residuals=good_res,
             coverage=70.0)["grade"] == GRADE_DECISION:
        f.append("coverage far from nominal must block decision grade")
    if grade(24, cluster_sizes=[15] * 24, block_residuals=None,
             coverage=95.0)["grade"] == GRADE_DECISION:
        f.append("a leave-one-out check that never ran must block decision grade")

    # leave-one-date-out itself
    w, det = leave_one_date_out({f"d{i}": (0.005 if i % 2 else -0.005) for i in range(10)})
    if w is None or w > MAX_LOO_RELATIVE_SHIFT:
        f.append(f"a stable pool must have a small LOO shift, got {w}")
    w2, det2 = leave_one_date_out(dict({f"d{i}": 0.001 for i in range(9)}, d9=0.5))
    if w2 is None or w2 <= MAX_LOO_RELATIVE_SHIFT:
        f.append(f"one wild date must produce a large LOO shift, got {w2}")
    if det2.get("most_influential") != "d9":
        f.append("the LOO diagnostic must identify the influential date")
    if leave_one_date_out({"a": 0.1, "b": 0.2})[0] is not None:
        f.append("LOO needs at least three dates to mean anything")

    print("uncertainty_estimand selftest:", "OK" if not f else "FAIL")
    for x in f:
        print("   -", x)
    return not f


MUTANTS = [
    ("the decision-grade bar drops to the computable floor",
     "DECISION_GRADE_EFFECTIVE_CLUSTERS = 20.0", "DECISION_GRADE_EFFECTIVE_CLUSTERS = 6.0"),
    ("effective clusters stops accounting for imbalance",
     "    return (sum(ns) ** 2) / sum(n * n for n in ns)", "    return float(len(ns))"),
    ("the influential-cluster diagnostic stops blocking",
     "    elif loo > MAX_LOO_RELATIVE_SHIFT:", "    elif False:"),
    ("a leave-one-out check that never ran is treated as passing",
     '    if loo is None:\n        out["blockers"].append({"code": "LEAVE_ONE_DATE_OUT_NOT_RUN"})',
     "    if False:\n        pass"),
    ("unvalidated interval coverage is treated as validated",
     "    if coverage is None:", "    if False:"),
    ("coverage far from nominal is accepted",
     "    elif abs(float(coverage) - float(nominal_coverage)) > COVERAGE_TOLERANCE_PP:",
     "    elif False:"),
    ("the influence ceiling is loosened until any date may dominate",
     "MAX_LOO_RELATIVE_SHIFT = 0.25", "MAX_LOO_RELATIVE_SHIFT = 99.0"),
    ("the LOO diagnostic stops naming the influential date",
     '"most_influential": max(shifts, key=shifts.get) if shifts else None}',
     '"most_influential": None}'),
    ("computable and decision grade collapse into one tier",
     '    out["grade"] = GRADE_DECISION if not out["blockers"] else GRADE_COMPUTABLE',
     '    out["grade"] = GRADE_DECISION'),
    ("k=2 is reported as undefined rather than unstable",
     "    if k == 1:", "    if k <= 2:"),
    ("the instability refusal claims the value does not exist",
     'f"s = {s_pp:.4f}pp IS defined at k={k} — this is computed, not undefined. "',
     'f"s is undefined at k={k}. "'),
    ("the computable floor collapses, so k=2 sizes a bet",
     "MIN_COMPUTABLE_CLUSTERS = 6", "MIN_COMPUTABLE_CLUSTERS = 2"),
    ("the residual loses its sign, so over- and under-confidence look identical",
     "    return sum(y - p for p, y in rows) / len(rows), None",
     "    return sum(abs(y - p) for p, y in rows) / len(rows), None"),
    ("the residual stops averaging within a block, so coin-flip noise survives",
     "    return sum(y - p for p, y in rows) / len(rows), None",
     "    return sum(y - p for p, y in rows), None"),
    ("the sample SD uses ddof=0, understating an already unstable estimate",
     "    s = math.sqrt(sum((v - mean) ** 2 for v in vals) / (k - 1))",
     "    s = math.sqrt(sum((v - mean) ** 2 for v in vals) / k)"),
    ("the interval is dropped, hiding how unstable a small-k estimate is",
     "    lo, hi = sigma_interval(s_pp, k)", "    lo, hi = None, None"),
    ("ungradable pairs are averaged in instead of refused",
     "            if p is not None and y is not None and 0.0 <= float(p) <= 1.0 and float(y) in (0.0, 1.0)]",
     "            if True]"),
    ("a collapsed interval is dressed up as a precise estimate",
     '"an interval that collapses to a point only because s is exactly zero here"',
     '"a factor of 1.0 end to end"'),
    ("a zero-SD width ratio is published as 1.0, which reads as perfect precision",
     "sigma_ci95_width_ratio=(hi / lo) if (lo and hi and lo > 0) else None)",
     "sigma_ci95_width_ratio=(hi / lo) if (lo and hi and lo > 0) else 1.0)"),
    ("the Bernoulli impostor is quietly allowed to be the estimand",
     '    "BERNOULLI_OUTCOME_SD": "sqrt(p(1-p)) — outcome noise, not model error. Does not shrink with "\n                            "data and is largest where the model is best calibrated.",',
     ""),
]


def mutation_suite():
    src = open(__file__).read()
    # BASELINE FIRST. A failing selftest makes every mutant look killed, so a broken fixture reports
    # a perfect score. Caught 2026-08-25 when module_manifest printed 11/11 while its own selftest
    # was failing.
    import io as _io, contextlib as _cl
    _b = _io.StringIO()
    with _cl.redirect_stdout(_b):
        _base = selftest()
    if not _base:
        print("  BASELINE_FAILING  the unmutated selftest does not pass; every 'kill' below is "
              "meaningless until it does")
        print(_b.getvalue().strip())
        return False
    # WHERE THE CODE ENDS AND THE MUTANT LIST BEGINS. A mutant whose pattern occurs only inside the
    # MUTANTS literal edits its OWN definition, applies cleanly, changes no behaviour and reports
    # SURVIVED — indistinguishable from a decorative fixture. That happened here when a constant was
    # renamed and the mutant kept the old name, which by then existed nowhere but in the mutant.
    body = src[:src.index("MUTANTS = [")]
    killed = 0
    for name, old, new in MUTANTS:
        if old not in src:
            print("  UNAPPLIED ", name + ": pattern not found")
            continue
        if old not in body:
            print("  SELF_TARGETED ", name + ": pattern occurs only inside the MUTANTS list, so "
                                             "this mutant edits itself and tests nothing")
            continue
        ns = {"__file__": __file__, "__name__": "mutant"}
        try:
            exec(compile(src.replace(old, new, 1), "<mutant>", "exec"), ns)
            ok = ns["selftest"]()
        except Exception:
            ok = False
        print(("  KILLED    " if not ok else "  SURVIVED  ") + name)
        killed += not ok
    print(f"mutation suite: {killed}/{len(MUTANTS)} killed"
          + ("" if killed == len(MUTANTS) else "  — SURVIVORS MEAN DECORATIVE FIXTURES"))
    return killed == len(MUTANTS)


if __name__ == "__main__":
    if "--mutants" in sys.argv:
        sys.exit(0 if mutation_suite() else 1)
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    print(__doc__)
