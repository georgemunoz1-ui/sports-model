#!/usr/bin/env python3
"""DISTRIBUTION IDENTITY — "distribution retained" is a claim with nine parts, not a checkbox.

OWNER CORRECTION 4 (2026-08-24). I reported that total distributions were retained and treated that
as closing the log-score/CRPS blocker. Retaining an array is necessary and nowhere near sufficient. A
distributional score is only reproducible if every one of these is bound:

    arm and target identity      which arm, on which target — a total distribution and a margin
                                 distribution are different objects and must not share an identity
    rng seed                     the exact seed, not the derivation rule
    draw count                   30,000 and 100,000 are different forecasts of the same model
    distribution hash            so the pmf that scored is provably the pmf that was registered
    support                      which integers carry mass; a pmf over 0..30 and one over 0..40
                                 give different CRPS for the same outcome
    scoring convention           where CRPS sums, and whether the indicator is 1[y <= k]
    crps implementation          named and pinned, because two "CRPS"es disagree at the boundary
    exact-total log-score mass   an integer total means P(Y = y), NOT a density and NOT a bin
    zero-probability handling    what happens when the model called the outcome impossible

WHY THE LAST TWO ARE NOT PEDANTRY. Log score at an integer outcome is -log P(Y = y). If a
convention instead scored -log P(Y <= y) or a half-open bin, the number would look similar and mean
something else. And a zero-probability outcome makes the log score infinite: silently dropping those
rows improves the mean, silently substituting an epsilon invents a probability the model never
assigned. Neither is acceptable, so zero-mass rows are COUNTED and reported beside the mean, and the
epsilon convention is refused outright rather than configured.

AND THE EXPANDING TOTAL PRIOR NEEDS A DISTRIBUTION AT ALL. The owner is right that a mean of 8.99
with a pool SD of 4.55 does not define a forecast — infinitely many distributions share them. Rather
than impose a parametric family the pool was never shown to follow, this module derives the prior's
predictive pmf as the EMPIRICAL pmf of the canonical pool's own totals, with Laplace smoothing over
a stated support so that no observable integer carries exactly zero mass. That choice is recorded as
a convention, not discovered from the data being scored.

API
  empirical_total_pmf(totals, support, alpha) -> the prior's predictive distribution
  bind(...)                                   -> a complete, hashable distribution identity
  audit(identity)                             -> which of the nine parts are missing
  CONVENTIONS                                 -> the frozen scoring conventions
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys

REQUIRED_PARTS = ("arm", "target", "rng_seed", "draw_count", "distribution_sha256",
                  "support", "scoring_convention", "crps_implementation",
                  "log_score_mass_convention", "zero_probability_handling")

COMPLETE = "DISTRIBUTION_IDENTITY_COMPLETE"
INCOMPLETE = "DISTRIBUTION_IDENTITY_INCOMPLETE"

#: Frozen conventions. Named so that a future reader can tell WHICH CRPS and WHICH log score ran.
CONVENTIONS = {
    "scoring_convention": "DISCRETE_INTEGER_SUPPORT_INCLUSIVE",
    "crps_implementation": "SUM_OVER_INTEGER_SUPPORT_HULL_OF_(F(k)-1[y<=k])^2",
    "crps_indicator": "1[y <= k], evaluated at every integer k from min(support ∪ {y}) to "
                      "max(support ∪ {y}) inclusive",
    "log_score_mass_convention": "EXACT_INTEGER_MASS: score is -log P(Y = y). NOT -log P(Y <= y), "
                                 "NOT a binned density, NOT a continuous approximation.",
    "zero_probability_handling": "COUNTED_NOT_SUBSTITUTED: a zero-mass outcome yields no log score "
                                 "and increments n_zero_mass, which is reported beside the mean. No "
                                 "epsilon is added — an epsilon invents a probability the model "
                                 "never assigned, and dropping the row silently improves the mean.",
    "epsilon_floor": None,
    "prior_pmf_derivation": "EMPIRICAL_LAPLACE_SMOOTHED over a stated integer support; no parametric "
                            "family is assumed because none was ever fitted or tested",
}

# The support the MLB total prior is defined over. Stated, not inferred from the scored slate.
MLB_TOTAL_SUPPORT = tuple(range(0, 41))

#: SMOOTHING. Laplace alpha=1 over 41 bins adds 41 pseudo-counts to 1,684 real ones and drags the
#: prior mean from 8.9911 to 9.2528 — a +0.262 run distortion of the very quantity the pmf
#: represents. Unit total pseudo-mass (alpha = 1/|support|) shifts it +0.0065 and still leaves no
#: integer at exactly zero.
LAPLACE_ALPHA = None            # explicit: there is no single default; callers pass a policy
UNIT_PSEUDO_MASS = "UNIT_TOTAL_PSEUDO_MASS"

#: TAIL. A pmf bounded at 40 assigns ZERO probability to a legitimate 41-run game, and under the
#: exact-mass log-score convention that is an infinite penalty for an outcome the support simply
#: refused to imagine. Baseball totals have no upper bound: the modern record is in the 40s and
#: nothing forbids more. So the distribution carries an explicit OVERFLOW bin holding the mass above
#: the support, and the scorer must be told how to spend it.
#: AND THE OVERFLOW BIN IS NOT AN EXACT-INTEGER PMF. This is the owner's correction and it is
#: structural, not cosmetic. A bin holding P(Y >= 41) does not assign a probability to 41, or to 42,
#: or to any single integer above the support. Under EXACT_INTEGER_MASS the scorer asks for
#: P(Y = y); above the support there is no such number to give. So the OUTCOME SPACE itself changes:
#: the distribution is a pmf over the COARSENED space {0, 1, ..., 40, "41+"}, and every arm and every
#: realised outcome must be coarsened the same way before any of them are compared. Scoring a
#: coarsened forecast against an uncoarsened outcome, or one arm against another under different
#: coarsenings, silently compares different estimands.
#:
#: Two admissible resolutions, both stated rather than assumed:
#:   COARSENED_TERMINAL_BIN  — collapse every arm and every outcome to {0..40, 41+}. Exact, cheap,
#:                             and it costs resolution: the model can no longer be graded on
#:                             distinguishing a 41-run game from a 47-run one.
#:   UNBOUNDED_INTEGER_TAIL  — spread the overflow mass over 41, 42, ... with a stated decay, which
#:                             restores an exact-integer pmf at the cost of one assumed parameter
#:                             that no data in this repository has ever fitted or tested.
#: Until one is chosen and applied to every arm, the FULL pmf mean is UNDEFINED. The body mean is a
#: real quantity but it is CONDITIONAL on Y <= 40, and it must be named that way — calling it the
#: full pmf mean asserts exactly the value the overflow bin correctly refuses to supply.
OVERFLOW_KEY = "OVERFLOW_ABOVE_SUPPORT"
COARSE_KEY = "41+"
OUTCOME_SPACE = {
    "EXACT_INTEGER": "every integer in the support carries its own mass; nothing above it exists. "
                     "Assigns zero to a possible outcome and is therefore not admissible for an "
                     "unbounded quantity like a baseball total.",
    "COARSENED_TERMINAL_BIN": "the outcome space is {0..max(support), '<max+1>+'}. The terminal bin "
                              "is an EVENT, not a value. Means over it are undefined; conditional "
                              "means over the body are defined and must be labelled conditional.",
    "UNBOUNDED_INTEGER_TAIL": "the outcome space is every non-negative integer, with a stated decay "
                              "above the support. Exact-integer scoring is restored; the decay "
                              "parameter is an assumption and is recorded as one.",
}
DEFAULT_OUTCOME_SPACE = "COARSENED_TERMINAL_BIN"
TAIL_CONVENTIONS = {
    "OVERFLOW_BIN": "mass above max(support) is held in one bin. An outcome above the support scores "
                    "against that bin's mass, so the log score is finite and honest — it is a large "
                    "penalty, not an infinite one, which is the correct treatment for a rare but "
                    "possible event.",
    "GEOMETRIC_TAIL": "the overflow mass is spread over k > max(support) with a stated decay, giving "
                      "every integer positive mass at the cost of one more assumed parameter.",
}
DEFAULT_TAIL = "OVERFLOW_BIN"


def _num(x):
    if x is None or isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def pmf_sha256(pmf):
    """Hash of a pmf. The overflow bin is a named key and hashes alongside the integer support."""
    payload = json.dumps({(k if isinstance(k, str) else str(int(k))): round(float(v), 12)
                          for k, v in sorted(pmf.items(), key=lambda kv: str(kv[0]))},
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def pmf_mean(pmf, overflow_representative=None):
    """(mean, note). The overflow bin has no single value, so its treatment is stated, not assumed.

    Under COARSENED_TERMINAL_BIN this returns None by design: the terminal bin is an EVENT, and the
    mean of a distribution one of whose atoms is an event is not a number. Use
    body_conditional_mean() for the quantity that IS defined, and say "conditional" when you print it.
    """
    body = {k: v for k, v in pmf.items() if not isinstance(k, str)}
    m = sum(k * v for k, v in body.items())
    ov = pmf.get(OVERFLOW_KEY, 0.0)
    if ov <= 0:
        return m, "no overflow mass"
    if overflow_representative is None:
        return None, (f"{100*ov:.4f}% of the mass sits in {OVERFLOW_KEY}, which is an EVENT "
                      f"(Y >= max(support)+1), not a value. The FULL pmf mean is UNDEFINED. A mean "
                      f"over the body alone is a different quantity — a mean CONDITIONAL on Y being "
                      f"inside the support — and must be labelled conditional, not reported as the "
                      f"pmf mean. Supply a representative value only if the outcome space has been "
                      f"declared UNBOUNDED_INTEGER_TAIL with a stated decay.")
    return m + float(overflow_representative) * ov, f"overflow priced at {overflow_representative}"


def body_conditional_mean(pmf):
    """(mean, conditioning_event). E[Y | Y <= max(support)] — defined, and named for what it is."""
    body = {k: v for k, v in pmf.items() if not isinstance(k, str)}
    z = sum(body.values())
    if z <= 0:
        return None, "NO_BODY_MASS"
    hi = max(body)
    return sum(k * v for k, v in body.items()) / z, f"CONDITIONAL_ON_Y_LE_{hi}"


def coarsen_pmf(pmf):
    """Collapse a pmf to the COARSENED_TERMINAL_BIN outcome space {0..hi, '<hi+1>+'}.

    Idempotent, and it renames the overflow key to the terminal EVENT label so a reader cannot
    mistake the bin for an integer.
    """
    body = {int(k): float(v) for k, v in pmf.items() if not isinstance(k, str)}
    if not body:
        return None, "NO_BODY_MASS"
    hi = max(body)
    tail = sum(float(v) for k, v in pmf.items() if isinstance(k, str))
    out = dict(body)
    out[f"{hi + 1}+"] = tail
    return out, f"COARSENED_TERMINAL_BIN at {hi + 1}+"


def coarsen_outcome(y, hi):
    """Coarsen a realised outcome the SAME way the forecast was coarsened.

    An arm scored on {0..hi, 'hi+1+'} must be scored against an outcome on that same space. Scoring
    a coarsened forecast against a raw integer is a category error that produces a number anyway,
    which is why it has to be a function and not a convention nobody applies.
    """
    yi = _num(y)
    if yi is None:
        return None
    yi = int(round(yi))
    return yi if yi <= int(hi) else f"{int(hi) + 1}+"


def empirical_total_pmf(totals, support=MLB_TOTAL_SUPPORT, alpha=None, tail=DEFAULT_TAIL,
                        overflow_mass=None):
    """The prior's predictive pmf: the pool's own empirical distribution, Laplace-smoothed.

    Smoothing is what stops a never-observed integer inside the support from carrying exactly zero
    mass, which under the exact-mass log-score convention would be an infinite penalty for an
    outcome the pool simply had not seen yet. alpha is a stated convention, not a fitted parameter.
    """
    obs = [int(round(t)) for t in (_num(x) for x in (totals or [])) if t is not None]
    if not obs:
        return None, "NO_TOTALS_IN_POOL"
    sup = sorted(set(int(k) for k in support))
    if not sup:
        return None, "EMPTY_SUPPORT"
    if tail not in TAIL_CONVENTIONS:
        return None, f"UNKNOWN_TAIL_CONVENTION: {tail!r}"
    hi = max(sup)
    above = [t for t in obs if t > hi]
    below = [t for t in obs if t < min(sup)]
    if below:
        return None, f"POOL_TOTALS_BELOW_STATED_SUPPORT: {sorted(set(below))[:5]}"
    if alpha is None:
        alpha = 1.0 / len(sup)          # unit TOTAL pseudo-mass, not one per bin
    counts = {k: alpha for k in sup}
    for t in obs:
        if t <= hi:
            counts[t] += 1.0
    # the overflow bin: observed exceedances plus a stated floor so a never-yet-seen 41+ game is
    # improbable rather than impossible
    floor = alpha if overflow_mass is None else float(overflow_mass)
    counts[OVERFLOW_KEY] = floor + float(len(above))
    z = sum(counts.values())
    return {k: v / z for k, v in counts.items()}, None


def bind(arm, target, rng_seed, draw_count, pmf, support, **kw):
    """A complete distribution identity. Every part is required; none is defaulted into existence."""
    ident = {
        "arm": arm,
        "target": target,
        "rng_seed": rng_seed,
        "draw_count": draw_count,
        "distribution_sha256": pmf_sha256(pmf) if pmf else None,
        "support": [int(min(support)), int(max(support))] if support else None,
        "n_support_points": len(set(support)) if support else None,
        "scoring_convention": CONVENTIONS["scoring_convention"],
        "crps_implementation": CONVENTIONS["crps_implementation"],
        "log_score_mass_convention": CONVENTIONS["log_score_mass_convention"],
        "zero_probability_handling": CONVENTIONS["zero_probability_handling"],
    }
    ident.update(kw)
    return ident


def audit(identity):
    """(status, missing). Which of the nine parts are absent or empty."""
    i = identity or {}
    missing = [k for k in REQUIRED_PARTS
               if i.get(k) is None or (isinstance(i.get(k), str) and not i[k].strip())
               or (isinstance(i.get(k), (list, tuple)) and not i[k])]
    # a seed and a draw count of zero are meaningful for a CLOSED-FORM arm, but then there is no
    # distribution to score and the identity must say so rather than pretending to be simulated
    if i.get("draw_count") == 0 and i.get("distribution_sha256"):
        missing.append("DRAW_COUNT_ZERO_WITH_A_SIMULATED_DISTRIBUTION")
    return (COMPLETE if not missing else INCOMPLETE), sorted(set(missing))


# =================================================================================================
def selftest():
    f = []

    # --- the coarsened outcome space: an overflow bin is NOT an exact-integer pmf -----------------
    cpool = [7, 8, 8, 9, 9, 10, 25]          # a genuine exceedance, so the terminal bin has real mass
    cpmf, cerr = empirical_total_pmf(cpool, support=range(0, 21))
    if cerr or cpmf is None:
        f.append(f"coarsening fixture pool failed to build: {cerr}")
    else:
        if cpmf.get(OVERFLOW_KEY, 0) <= 0:
            f.append("fixture is wrong: the coarsening pool must put real mass above the support")
        m, note = pmf_mean(cpmf)
        if m is not None:
            f.append("the full pmf mean must be UNDEFINED while terminal-bin mass is present")
        if "UNDEFINED" not in (note or ""):
            f.append("the refusal must say the full mean is UNDEFINED, not merely decline")
        if "EVENT" not in (note or ""):
            f.append("the refusal must say the terminal bin is an event, not a value")
        bm, cond = body_conditional_mean(cpmf)
        if bm is None:
            f.append("the body-conditional mean must be computable")
        elif not (cond or "").startswith("CONDITIONAL_ON_Y_LE_"):
            f.append("the conditional mean must name its conditioning event")
        else:
            naive = sum(k * v for k, v in cpmf.items() if not isinstance(k, str))
            if abs(bm - naive) < 1e-12:
                f.append("the conditional mean must renormalize over the body, not just drop the tail")
        co, cnote = coarsen_pmf(cpmf)
        if co is None:
            f.append("coarsen_pmf must return a pmf")
        else:
            if "21+" not in co:
                f.append(f"coarsen_pmf must emit the 21+ terminal event key, got "
                         f"{[k for k in co if isinstance(k, str)]}")
            elif abs(co["21+"] - cpmf[OVERFLOW_KEY]) > 1e-12:
                f.append("the terminal bin must carry exactly the overflow mass")
            if abs(sum(co.values()) - 1.0) > 1e-9:
                f.append("coarsening must preserve total mass")
            if OVERFLOW_KEY in co:
                f.append("the coarsened pmf must not still carry the raw overflow key")
            if coarsen_pmf(co)[0] != co:
                f.append("coarsening must be idempotent")
        if coarsen_outcome(9, 20) != 9:
            f.append("an in-support outcome must survive coarsening unchanged")
        if coarsen_outcome(25, 20) != "21+":
            f.append(f"an above-support outcome must coarsen to the terminal bin, got "
                     f"{coarsen_outcome(25, 20)!r}")
        if coarsen_outcome(20, 20) != 20:
            f.append("the boundary outcome belongs to the body, not the terminal bin")
        if coarsen_outcome(21, 20) != "21+":
            f.append("the first outcome above the support must fall in the terminal bin")
        if coarsen_outcome(None, 20) is not None:
            f.append("a missing outcome must not be coarsened into a real bin")
        if DEFAULT_OUTCOME_SPACE not in OUTCOME_SPACE:
            f.append("the declared default outcome space must be one of the named ones")
        if "EXACT_INTEGER" not in OUTCOME_SPACE:
            f.append("the inadmissible exact-integer space must still be named, so it can be refused")

    # --- the empirical prior pmf -----------------------------------------------------------------
    pool = [7, 8, 8, 9, 9, 9, 10, 11, 12]
    pmf, err = empirical_total_pmf(pool, support=range(0, 21))
    if err or pmf is None:
        f.append(f"a normal pool must produce a pmf, got {err}")
    else:
        if abs(sum(pmf.values()) - 1.0) > 1e-12:
            f.append("the pmf must sum to 1")
        if min(pmf.values()) <= 0:
            f.append("smoothing must leave NO integer in the support at exactly zero mass")
        # the mode must still be the pool's mode — smoothing may not overturn the data
        if max(pmf, key=pmf.get) != 9:
            f.append(f"smoothing must not move the mode off 9, got {max(pmf, key=pmf.get)}")
        # an unobserved integer inside the support carries alpha/Z, not zero
        if pmf[3] <= 0 or pmf[3] >= pmf[9]:
            f.append("an unobserved integer must carry small positive mass, below the mode")
    # --- the tail: a total ABOVE the support goes to the overflow bin, never to zero mass --------
    if OVERFLOW_KEY not in pmf:
        f.append("every pmf must carry an overflow bin; a bounded pmf calls 41+ impossible")
    if pmf[OVERFLOW_KEY] <= 0:
        f.append("the overflow bin must hold positive mass even with no observed exceedance")
    # two pools differing ONLY by one exceedance: normalisation is otherwise identical, so the
    # comparison isolates whether the exceedance actually reached the bin
    noex, _ = empirical_total_pmf([7, 8, 9], support=range(0, 21))
    withex, err2 = empirical_total_pmf([7, 8, 9, 99], support=range(0, 21))
    if withex is None:
        f.append(f"a total above the support belongs in the overflow bin, not a refusal: {err2}")
    elif withex[OVERFLOW_KEY] <= noex[OVERFLOW_KEY]:
        f.append(f"an observed exceedance must increase the overflow mass: "
                 f"{withex[OVERFLOW_KEY]:.6f} vs {noex[OVERFLOW_KEY]:.6f}")
    # BELOW the support is still a refusal — a negative total is not a tail event
    low, err3 = empirical_total_pmf([7, 8, -3], support=range(0, 21))
    if low is not None or "BELOW_STATED_SUPPORT" not in (err3 or ""):
        f.append("a total below the support must refuse")
    if empirical_total_pmf(pool, support=range(0, 21), tail="VIBES")[0] is not None:
        f.append("an unknown tail convention must refuse")
    # --- the two means are different quantities and must not be conflated -------------------------
    m_body, note = pmf_mean(pmf)
    if m_body is not None:
        f.append("with overflow mass present, a bare mean must refuse and say why")
    if OVERFLOW_KEY not in (note or ""):
        f.append("the refusal must name the overflow bin")
    m_priced, note2 = pmf_mean(pmf, overflow_representative=25)
    if m_priced is None:
        f.append("with a stated representative value the mean is computable")
    if empirical_total_pmf([], support=range(0, 21))[0] is not None:
        f.append("an empty pool has no pmf")
    # the pool here must fall INSIDE any fallback support a defective build might invent, or the
    # out-of-support refusal masks the empty-support refusal and the fixture proves nothing
    if empirical_total_pmf([9, 9], support=[])[0] is not None:
        f.append("an empty support has no pmf, even when every total would fit a fallback")
    # alpha=0 removes smoothing and reintroduces exact zeros — allowed, but it must actually change it
    raw, _ = empirical_total_pmf(pool, support=range(0, 21), alpha=0.0, overflow_mass=0.0)
    if raw is None or raw[3] != 0.0:
        f.append("alpha=0 must produce the unsmoothed pmf with real zeros")
    # unit total pseudo-mass is the default and must distort far less than Laplace alpha=1
    unit, _ = empirical_total_pmf(pool, support=range(0, 21))
    lap, _ = empirical_total_pmf(pool, support=range(0, 21), alpha=1.0)
    emp = sum(pool) / len(pool)
    du = abs(sum(k*v for k, v in unit.items() if not isinstance(k, str))/(1-unit[OVERFLOW_KEY]) - emp)
    dl = abs(sum(k*v for k, v in lap.items() if not isinstance(k, str))/(1-lap[OVERFLOW_KEY]) - emp)
    if not (du < dl):
        f.append(f"unit pseudo-mass must distort the mean less than Laplace: {du:.4f} vs {dl:.4f}")

    # --- the hash is over the pmf, and is order-insensitive --------------------------------------
    if pmf_sha256({8: 0.5, 9: 0.5}) != pmf_sha256({9: 0.5, 8: 0.5}):
        f.append("the pmf hash must not depend on key order")
    if pmf_sha256({8: 0.5, 9: 0.5}) == pmf_sha256({8: 0.6, 9: 0.4}):
        f.append("the pmf hash must depend on the masses")
    if pmf_sha256({8: 1.0}) == pmf_sha256({9: 1.0}):
        f.append("the pmf hash must depend on the support")

    # --- a complete identity, and every single-part omission ------------------------------------
    ident = bind("mlb.total.CHAMPION_V13_100K", "total", 12345, 100000, {8: 0.4, 9: 0.6}, range(0, 41))
    st, miss = audit(ident)
    if st != COMPLETE or miss:
        f.append(f"a complete identity must pass, missing {miss}")
    for k in ("arm", "target", "rng_seed", "draw_count", "distribution_sha256", "support",
              "scoring_convention", "crps_implementation", "log_score_mass_convention",
              "zero_probability_handling"):
        if k not in REQUIRED_PARTS:
            f.append(f"{k} must be a required part")
        broken = dict(ident); broken[k] = None
        st2, miss2 = audit(broken)
        if st2 != INCOMPLETE or k not in miss2:
            f.append(f"an identity missing {k} must be INCOMPLETE")
    # a closed-form arm claiming a simulated distribution is incoherent
    st3, miss3 = audit(dict(ident, draw_count=0))
    if st3 != INCOMPLETE or not any("DRAW_COUNT_ZERO" in m for m in miss3):
        f.append("draw_count 0 with a distribution hash must be refused as incoherent")

    # --- the conventions are stated, and the dangerous ones are the right way round --------------
    if "P(Y = y)" not in CONVENTIONS["log_score_mass_convention"]:
        f.append("the log-score convention must state exact integer mass")
    if "NOT -log P(Y <= y)" not in CONVENTIONS["log_score_mass_convention"]:
        f.append("the log-score convention must explicitly exclude the cumulative form")
    if CONVENTIONS["epsilon_floor"] is not None:
        f.append("no epsilon floor may be configured — an epsilon invents a probability")
    if "COUNTED_NOT_SUBSTITUTED" not in CONVENTIONS["zero_probability_handling"]:
        f.append("zero-mass outcomes must be counted, never substituted")
    if "1[y <= k]" not in CONVENTIONS["crps_indicator"]:
        f.append("the CRPS indicator must be pinned")

    for x in f:
        print("FAIL:", x)
    if not f:
        print("distribution_identity selftest: OK")
    return f


MUTANTS = [
    ("smoothing is dropped, so an unobserved integer carries exactly zero mass",
     "    counts = {k: alpha for k in sup}", "    counts = {k: 0.0 for k in sup}"),
    ("smoothing is so heavy it overturns the pool's mode",
     "    counts = {k: alpha for k in sup}", "    counts = {k: 1e6 for k in sup}"),
    ("a total below the support is silently accepted",
     "    if below:", "    if False:"),
    ("the overflow bin is dropped, so an unbounded outcome gets zero mass",
     "    counts[OVERFLOW_KEY] = floor + float(len(above))", "    pass"),
    ("the overflow bin starts empty, so a never-seen 41+ game is impossible",
     "    floor = alpha if overflow_mass is None else float(overflow_mass)", "    floor = 0.0"),
    ("observed exceedances stop reaching the overflow bin",
     "    counts[OVERFLOW_KEY] = floor + float(len(above))", "    counts[OVERFLOW_KEY] = floor"),
    ("an unknown tail convention is accepted",
     "    if tail not in TAIL_CONVENTIONS:", "    if False:"),
    ("the default smoothing reverts to Laplace alpha=1",
     "        alpha = 1.0 / len(sup)          # unit TOTAL pseudo-mass, not one per bin", "        alpha = 1.0"),
    ("the terminal bin is treated as an integer, so a coarsened outcome lands in the body",
     '    return yi if yi <= int(hi) else f"{int(hi) + 1}+"', "    return yi"),
    ("the coarsening boundary shifts, sweeping the last body integer into the terminal bin",
     "    return yi if yi <= int(hi) else", "    return yi if yi < int(hi) else"),
    ("the conditional mean stops renormalizing, so it silently understates",
     '    return sum(k * v for k, v in body.items()) / z, f"CONDITIONAL_ON_Y_LE_{hi}"',
     '    return sum(k * v for k, v in body.items()), f"CONDITIONAL_ON_Y_LE_{hi}"'),
    ("the conditional mean stops naming its conditioning event",
     'f"CONDITIONAL_ON_Y_LE_{hi}"', '"mean"'),
    ("coarsening drops the tail mass instead of collapsing it",
     '    out[f"{hi + 1}+"] = tail', "    pass"),
    ("coarsening keeps the raw overflow key alongside the terminal bin",
     "    out = dict(body)", "    out = dict(pmf)"),
    ("the refusal stops calling the full mean UNDEFINED",
     "f\"(Y >= max(support)+1), not a value. The FULL pmf mean is UNDEFINED. A mean \"",
     "f\"(Y >= max(support)+1). A mean \""),
    ("a mean is reported over the body while overflow mass is unpriced",
     '    if overflow_representative is None:\n        return None, (f"{100*ov:.4f}% of the mass sits in {OVERFLOW_KEY}, which is an EVENT "',
     '    if False:\n        return None, (f"{100*ov:.4f}% of the mass sits in {OVERFLOW_KEY}, which is an EVENT "'),
    ("an empty pool yields a pmf anyway",
     '    if not obs:\n        return None, "NO_TOTALS_IN_POOL"', '    if not obs:\n        obs = [9]'),
    ("an empty support yields a pmf anyway",
     '    if not sup:\n        return None, "EMPTY_SUPPORT"', '    if not sup:\n        sup = [9]'),
    ("the pmf is not normalised",
     "    return {k: v / z for k, v in counts.items()}, None", "    return dict(counts), None"),
    ("the pmf hash ignores the masses",
     '    payload = json.dumps({(k if isinstance(k, str) else str(int(k))): round(float(v), 12)',
     '    payload = json.dumps({(k if isinstance(k, str) else str(int(k))): 0.0'),
    ("a missing part stops making the identity incomplete",
     '    missing = [k for k in REQUIRED_PARTS\n               if i.get(k) is None or (isinstance(i.get(k), str) and not i[k].strip())\n               or (isinstance(i.get(k), (list, tuple)) and not i[k])]',
     "    missing = []"),
    ("the required parts shrink to the easy ones",
     'REQUIRED_PARTS = ("arm", "target", "rng_seed", "draw_count", "distribution_sha256",\n                  "support", "scoring_convention", "crps_implementation",\n                  "log_score_mass_convention", "zero_probability_handling")',
     'REQUIRED_PARTS = ("arm", "target")'),
    ("a closed-form arm may claim a simulated distribution",
     '    if i.get("draw_count") == 0 and i.get("distribution_sha256"):', "    if False:"),
    ("the log score switches to the cumulative form",
     '    "log_score_mass_convention": "EXACT_INTEGER_MASS: score is -log P(Y = y). NOT -log P(Y <= y), "',
     '    "log_score_mass_convention": "CUMULATIVE: score is -log P(Y <= y). ("'),
    ("an epsilon floor is configured, inventing a probability",
     '    "epsilon_floor": None,', '    "epsilon_floor": 1e-9,'),
    ("zero-mass outcomes are substituted rather than counted",
     '    "zero_probability_handling": "COUNTED_NOT_SUBSTITUTED: a zero-mass outcome yields no log score "',
     '    "zero_probability_handling": "SUBSTITUTED: a zero-mass outcome is floored ("'),
    ("the CRPS indicator is unpinned",
     '    "crps_indicator": "1[y <= k], evaluated at every integer k from min(support ∪ {y}) to "',
     '    "crps_indicator": "the usual one ("'),
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
