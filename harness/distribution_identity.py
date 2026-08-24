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
LAPLACE_ALPHA = 1.0


def _num(x):
    if x is None or isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def pmf_sha256(pmf):
    """Hash of a pmf, keyed by integer support so two orderings of one pmf hash identically."""
    payload = json.dumps({str(int(k)): round(float(v), 12) for k, v in sorted(pmf.items())},
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def empirical_total_pmf(totals, support=MLB_TOTAL_SUPPORT, alpha=LAPLACE_ALPHA):
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
    outside = [t for t in obs if t not in sup]
    if outside:
        return None, f"POOL_TOTALS_OUTSIDE_STATED_SUPPORT: {sorted(set(outside))[:5]}"
    counts = {k: alpha for k in sup}
    for t in obs:
        counts[t] += 1.0
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
    # a pool total outside the stated support is a refusal, not a silent clip
    bad, err2 = empirical_total_pmf([7, 8, 99], support=range(0, 21))
    if bad is not None or "OUTSIDE_STATED_SUPPORT" not in (err2 or ""):
        f.append("a total outside the support must refuse rather than clip")
    if empirical_total_pmf([], support=range(0, 21))[0] is not None:
        f.append("an empty pool has no pmf")
    # the pool here must fall INSIDE any fallback support a defective build might invent, or the
    # out-of-support refusal masks the empty-support refusal and the fixture proves nothing
    if empirical_total_pmf([9, 9], support=[])[0] is not None:
        f.append("an empty support has no pmf, even when every total would fit a fallback")
    # alpha=0 removes smoothing and reintroduces exact zeros — allowed, but it must actually change it
    raw, _ = empirical_total_pmf(pool, support=range(0, 21), alpha=0.0)
    if raw is None or raw[3] != 0.0:
        f.append("alpha=0 must produce the unsmoothed pmf with real zeros")

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
    ("a pool total outside the support is silently clipped",
     "    if outside:", "    if False:"),
    ("an empty pool yields a pmf anyway",
     '    if not obs:\n        return None, "NO_TOTALS_IN_POOL"', '    if not obs:\n        obs = [9]'),
    ("an empty support yields a pmf anyway",
     '    if not sup:\n        return None, "EMPTY_SUPPORT"', '    if not sup:\n        sup = [9]'),
    ("the pmf is not normalised",
     "    return {k: v / z for k, v in counts.items()}, None", "    return dict(counts), None"),
    ("the pmf hash ignores the masses",
     '    payload = json.dumps({str(int(k)): round(float(v), 12) for k, v in sorted(pmf.items())},',
     '    payload = json.dumps({str(int(k)): 0 for k, v in sorted(pmf.items())},'),
    ("the pmf hash ignores the support",
     '    payload = json.dumps({str(int(k)): round(float(v), 12) for k, v in sorted(pmf.items())},',
     '    payload = json.dumps({"x": sorted(round(float(v), 12) for v in pmf.values())},'),
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
