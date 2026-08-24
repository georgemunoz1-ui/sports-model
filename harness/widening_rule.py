#!/usr/bin/env python3
"""WIDENING RULE — solve k so the widened arm's dispersion actually matches, and refuse when it cannot.

OWNER DIRECTIVE 2026-08-24, and a correction I had coming:

    logit(p_i^wide) = logit(p_prior) + k * f_i

    "If the intent is exact dispersion matching, solve k numerically from pregame forecasts; simply
     using the ratio of probability standard deviations does not guarantee equal post-transformation
     dispersion. Predefine zero-dispersion, no-solution and extreme-k refusal behavior before
     producing the card."

WHY THE RATIO IS WRONG. I registered this arm with k = SD(champion)/SD(challenger) = 5.32/3.08 =
1.727 and called it dispersion matching. It is not. The map from k to probability dispersion runs
through the logistic, which is nonlinear: doubling k in LOGIT space does not double the standard
deviation of the resulting PROBABILITIES, and how far off it is depends on where the forecasts sit.
Near p=.5 the logistic is close to linear and the ratio is a decent approximation; out in the tails
it compresses hard, so a k chosen by the ratio undershoots. The ratio is a first-order guess at a
quantity that can simply be solved for.

WHAT IT WIDENS. The residual f_i only. logit(p_prior) is the constant offset and stays exactly
where it is — widening it would move the whole slate's central tendency, which is not what a
dispersion defect calls for and would silently re-tune the prior.

THE SOLVE. g(k) = SD_p({sigmoid(logit(p_prior) + k*f_i)}) is continuous and, for a fixed non-degenerate
f, strictly increasing in k on k >= 0 until saturation. So a bisection on [0, K_MAX] converges. There
is no closed form and no need for one.

THE THREE REFUSALS, PREDEFINED HERE AND NOT AFTER SEEING A SLATE:

  ZERO_DISPERSION      the residuals are all equal (SD(f) = 0), so no k produces any dispersion at
                       all, or the target dispersion is 0. There is nothing to match and no k means
                       anything. REFUSE — do not fall back to k=1, which would silently ship the
                       unwidened arm under the widened arm's name.
  NO_SOLUTION          the target dispersion is unreachable on [0, K_MAX] — typically the target
                       exceeds what saturation permits. REFUSE and report the best attainable, so
                       the gap is visible rather than being absorbed by a clamp.
  EXTREME_K            a solution exists but k lies outside [K_MIN_OK, K_MAX_OK]. A k of 40 is not a
                       widening, it is a different model wearing the arm's name. REFUSE and report k.

A refusal is not a failure of the slate. It means this arm produces NO ROW for that slate, which is
honest, and the card records the reason. An arm that quietly degrades to something else is worse
than an arm that is absent.
"""
from __future__ import annotations

import json
import math
import os
import sys

#: Bisection bracket. K_MAX is where the search gives up; K_MIN_OK/K_MAX_OK bound an ACCEPTABLE k.
K_MAX = 50.0
K_MIN_OK = 0.25
K_MAX_OK = 12.0
TOL = 1e-9
MAX_ITER = 200

OK = "WIDENING_SOLVED"
ZERO_DISPERSION = "REFUSED_ZERO_DISPERSION"
NO_SOLUTION = "REFUSED_NO_SOLUTION_IN_BRACKET"
EXTREME_K = "REFUSED_EXTREME_K"
BAD_INPUT = "REFUSED_MALFORMED_INPUT"

EPS = 1e-9


def _num(x):
    if x is None or isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def _logit(p):
    p = min(max(float(p), EPS), 1.0 - EPS)
    return math.log(p / (1.0 - p))


def _sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _sd(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / n)          # population SD, as on the card


def dispersion_at(k, prior_logit, residuals):
    """Cross-game probability SD produced by this k. This is the quantity being matched."""
    return _sd([_sigmoid(prior_logit + k * f) for f in residuals])


def solve_k(prior_p, residuals, target_sd_pp):
    """Solve for k such that the widened arm's cross-game probability SD equals the target.

    prior_p       the constant prior probability (the offset that is NOT widened)
    residuals     f_i, one per game, in logit units
    target_sd_pp  the dispersion to match, in probability POINTS (e.g. the champion's 5.32)
    """
    pp = _num(prior_p)
    tgt = _num(target_sd_pp)
    fs = [_num(f) for f in (residuals or [])]
    if pp is None or not (0.0 < pp < 1.0) or tgt is None or any(f is None for f in fs) or len(fs) < 2:
        return {"status": BAD_INPUT, "k": None,
                "reason": "prior must be a probability in (0,1), residuals numeric, and at least "
                          "two games are needed for a dispersion"}
    target = tgt / 100.0
    z0 = _logit(pp)
    if _sd(fs) <= EPS:
        return {"status": ZERO_DISPERSION, "k": None, "residual_sd": _sd(fs),
                "reason": "the residuals carry no variation, so NO k produces any dispersion. There "
                          "is nothing to match. Falling back to k=1 here would ship the unwidened "
                          "arm under the widened arm's name."}
    if target <= EPS:
        return {"status": ZERO_DISPERSION, "k": None, "target_sd_pp": tgt,
                "reason": "the target dispersion is zero; only k=0 attains it and a zero-width "
                          "forecast is not a widening"}
    lo, hi = 0.0, K_MAX
    d_hi = dispersion_at(hi, z0, fs)
    if d_hi < target:
        return {"status": NO_SOLUTION, "k": None, "target_sd_pp": tgt,
                "best_attainable_sd_pp": 100.0 * d_hi, "k_max_searched": K_MAX,
                "reason": "the target dispersion is unreachable within the bracket — the logistic "
                          "saturates before it is attained. Reported rather than clamped, so the "
                          "gap is visible."}
    for _ in range(MAX_ITER):
        mid = 0.5 * (lo + hi)
        if dispersion_at(mid, z0, fs) < target:
            lo = mid
        else:
            hi = mid
        if hi - lo < TOL:
            break
    k = 0.5 * (lo + hi)
    attained = dispersion_at(k, z0, fs)
    out = {"k": k, "target_sd_pp": tgt, "attained_sd_pp": 100.0 * attained,
           "residual_sd": _sd(fs), "prior_p": pp,
           "ratio_approximation_k": None, "iterations_bracket": [0.0, K_MAX]}
    if not (K_MIN_OK <= k <= K_MAX_OK):
        out["status"] = EXTREME_K
        out["reason"] = (f"k={k:.4f} lies outside the acceptable band "
                         f"[{K_MIN_OK}, {K_MAX_OK}]. A scale this far from 1 is not a widening of "
                         f"this model, it is a different model wearing its name.")
        return out
    out["status"] = OK
    return out


def apply_widening(prior_p, residuals, k):
    """The widened probabilities. The prior offset is untouched; only the residual is scaled."""
    z0 = _logit(prior_p)
    return [_sigmoid(z0 + k * f) for f in residuals]


def compare_to_ratio(prior_p, residuals, target_sd_pp, baseline_sd_pp):
    """What the SD ratio would have given, beside what the solve gives. Shows the size of my error."""
    r = solve_k(prior_p, residuals, target_sd_pp)
    ratio_k = (_num(target_sd_pp) or 0.0) / (_num(baseline_sd_pp) or 1.0)
    z0 = _logit(prior_p)
    return {"solved": r, "ratio_k": ratio_k,
            "ratio_attained_sd_pp": 100.0 * dispersion_at(ratio_k, z0, residuals),
            "target_sd_pp": target_sd_pp,
            "note": "the ratio is a first-order guess; the logistic is nonlinear, so it generally "
                    "misses the target it was chosen to hit"}


# =================================================================================================
def selftest():
    f = []
    PRIOR = 0.52054
    # a residual set with real spread, the shape a slate produces
    fs = [-0.35, -0.20, -0.08, -0.02, 0.03, 0.09, 0.17, 0.26, 0.38, 0.44]

    # --- the solve hits its target ----------------------------------------------------------------
    r = solve_k(PRIOR, fs, 5.32)
    if r["status"] != OK:
        f.append(f"a reachable target must solve, got {r}")
    elif abs(r["attained_sd_pp"] - 5.32) > 1e-4:
        f.append(f"the solve must ATTAIN its target, got {r['attained_sd_pp']}")
    else:
        # the reported attainment must be the dispersion the REPORTED k actually produces, verified
        # by an independent recompute. Comparing it to the target only would pass a solve that
        # simply echoed the target back and never measured anything.
        recomputed = 100.0 * dispersion_at(r["k"], _logit(PRIOR), fs)
        if abs(r["attained_sd_pp"] - recomputed) > 1e-12:
            f.append(f"attained_sd_pp {r['attained_sd_pp']!r} is not the dispersion produced by "
                     f"k={r['k']!r}, which recomputes to {recomputed!r} — the solve reported a "
                     f"number it did not measure")
    # and it is monotone: a wider target needs a bigger k
    r2 = solve_k(PRIOR, fs, 8.0)
    if r2["status"] == OK and not (r2["k"] > r["k"]):
        f.append("a wider target must require a larger k")

    # --- the correction: the ratio does NOT hit the target ----------------------------------------
    cmp_ = compare_to_ratio(PRIOR, fs, 5.32, 3.08)
    if abs(cmp_["ratio_k"] - 5.32 / 3.08) > 1e-9:
        f.append("the ratio k must be reported as the ratio")
    if abs(cmp_["ratio_attained_sd_pp"] - 5.32) < 1e-3:
        f.append("fixture is wrong: on this shape the ratio should MISS the target")
    if abs(cmp_["solved"]["attained_sd_pp"] - 5.32) > 1e-4:
        f.append("the solved k must hit the target the ratio misses")

    # --- only the residual is widened; the prior offset is untouched ------------------------------
    base = apply_widening(PRIOR, fs, 1.0)
    wide = apply_widening(PRIOR, fs, 2.0)
    if abs(_sd(wide) - _sd(base)) < 1e-9:
        f.append("a larger k must produce more dispersion")
    # with a zero residual the widened probability IS the prior, for every k
    for k in (0.5, 1.0, 7.0):
        if abs(apply_widening(PRIOR, [0.0, 0.0], k)[0] - PRIOR) > 1e-9:
            f.append(f"a zero residual must return the prior exactly at k={k}")
    # the ORDER of games is never changed by widening — it is a scale, not a re-ranking
    if [i for i, _ in sorted(enumerate(base), key=lambda t: t[1])] != \
       [i for i, _ in sorted(enumerate(wide), key=lambda t: t[1])]:
        f.append("widening must not re-rank the slate")

    # --- REFUSAL 1: zero dispersion ---------------------------------------------------------------
    z = solve_k(PRIOR, [0.11] * 6, 5.32)
    if z["status"] != ZERO_DISPERSION or z["k"] is not None:
        f.append(f"identical residuals must refuse, got {z}")
    if "k=1" not in z["reason"]:
        f.append("the zero-dispersion refusal must say why a k=1 fallback is forbidden")
    z2 = solve_k(PRIOR, fs, 0.0)
    if z2["status"] != ZERO_DISPERSION:
        f.append("a zero target must refuse")

    # --- REFUSAL 2: no solution in the bracket ----------------------------------------------------
    n = solve_k(PRIOR, fs, 49.0)
    if n["status"] != NO_SOLUTION or n["k"] is not None:
        f.append(f"an unreachable target must refuse, got {n}")
    if n.get("best_attainable_sd_pp") is None or n["best_attainable_sd_pp"] >= 49.0:
        f.append("the refusal must report the best attainable dispersion")

    # --- REFUSAL 3: extreme k ---------------------------------------------------------------------
    tiny = [x / 20.0 for x in fs]           # small residuals need a k above the band to reach 5.32pp
    e = solve_k(PRIOR, tiny, 5.32)
    if e["status"] != EXTREME_K:
        f.append(f"a solution outside the acceptable band must refuse, got {e['status']} k={e.get('k')}")
    if e.get("k") is None or e["k"] <= K_MAX_OK:
        f.append("the extreme-k refusal must still report the k it found")
    # and the band has a lower edge too
    huge = [x * 40.0 for x in fs]           # huge residuals need a k below the band
    lo = solve_k(PRIOR, huge, 1.0)
    if lo["status"] != EXTREME_K:
        f.append(f"a k below the band must refuse as EXTREME_K, got {lo['status']} k={lo.get('k')}")
    if lo.get("k") is None or lo["k"] >= K_MIN_OK:
        f.append(f"the low-side refusal must report the small k it found, got {lo.get('k')}")
    # and an unreachable target is a DIFFERENT refusal from an out-of-band one
    if solve_k(PRIOR, [x / 400.0 for x in fs], 5.32)["status"] != NO_SOLUTION:
        f.append("residuals too small for ANY k in the bracket is NO_SOLUTION, not EXTREME_K")

    # --- malformed input --------------------------------------------------------------------------
    for bad in ((None, fs, 5.0), (1.5, fs, 5.0), (PRIOR, [1.0], 5.0), (PRIOR, ["x", 1.0], 5.0),
                (PRIOR, fs, None), (0.0, fs, 5.0)):
        if solve_k(*bad)["status"] != BAD_INPUT:
            f.append(f"malformed input must refuse: {bad}")

    # --- a refusal never returns a usable k -------------------------------------------------------
    for r_ in (z, z2, n):
        if r_.get("k") is not None:
            f.append(f"{r_['status']} must not return a k")

    for x in f:
        print("FAIL:", x)
    if not f:
        print("widening_rule selftest: OK")
    return f


MUTANTS = [
    ("the bisection always narrows downward, so k converges to zero",
     "        if dispersion_at(mid, z0, fs) < target:\n            lo = mid\n        else:\n            hi = mid",
     "        hi = mid"),
    ("the solve reports its target as attained without measuring",
     '    attained = dispersion_at(k, z0, fs)', "    attained = target"),
    ("the bisection stops converging and returns the bracket midpoint once",
     "    for _ in range(MAX_ITER):", "    for _ in range(1):"),
    ("zero-variance residuals fall back to k=1 instead of refusing",
     "    if _sd(fs) <= EPS:", "    if False:"),
    ("a zero target is accepted",
     "    if target <= EPS:", "    if False:"),
    ("an unreachable target is clamped instead of refused",
     "    if d_hi < target:", "    if False:"),
    ("the unreachable refusal stops reporting what was attainable",
     '                "best_attainable_sd_pp": 100.0 * d_hi, "k_max_searched": K_MAX,',
     '                "k_max_searched": K_MAX,'),
    ("an extreme k is accepted",
     "    if not (K_MIN_OK <= k <= K_MAX_OK):", "    if False:"),
    ("the acceptable band is widened until nothing is extreme",
     "K_MIN_OK = 0.25\nK_MAX_OK = 12.0", "K_MIN_OK = 0.0\nK_MAX_OK = 1e9"),
    ("the extreme-k refusal hides the k it found",
     '    out = {"k": k, "target_sd_pp": tgt, "attained_sd_pp": 100.0 * attained,',
     '    out = {"k": None, "target_sd_pp": tgt, "attained_sd_pp": 100.0 * attained,'),
    ("widening moves the prior offset instead of only the residual",
     "    return [_sigmoid(z0 + k * f) for f in residuals]", "    return [_sigmoid(k * (z0 + f)) for f in residuals]"),
    ("malformed input is accepted",
     "    if pp is None or not (0.0 < pp < 1.0) or tgt is None or any(f is None for f in fs) or len(fs) < 2:",
     "    if False:"),
    ("a single game is enough to define a dispersion",
     "or len(fs) < 2:", "or len(fs) < 0:"),
    ("the dispersion is measured in logit space instead of probability space",
     '    return _sd([_sigmoid(prior_logit + k * f) for f in residuals])',
     "    return _sd([prior_logit + k * f for f in residuals])"),
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
            pr = _sp.run([sys.executable, path, "--selftest"], capture_output=True, text=True, timeout=120)
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
