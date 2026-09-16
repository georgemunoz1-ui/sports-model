#!/usr/bin/env python3
"""SIMULATION STANDARD — trial count, and common random numbers across arms.

OWNER AMENDMENTS 4 AND 5 (2026-08-23).

  4. "Restore the 100,000-simulation standard. V13's 30,000-trial champion is a frozen legacy
     identity and can remain registered, but it does not satisfy the current 100k standard. Future
     cards should fork a separately identified 100k champion/reference arm."

  5. "Independent seeds add about 0.41pp Monte Carlo noise to a difference near 50% at 30k trials.
     Several reported arm deltas are only 0.5-0.7pp. Use the same game-level random stream across
     arms in the attribution harness while preserving distinct model identities."

THE ARITHMETIC THE OWNER IS POINTING AT. A probability estimated from n independent trials near
p=.5 has sd = sqrt(p(1-p)/n). At n=30,000 that is 0.289pp per arm; the DIFFERENCE of two arms drawn
on independent streams has sd = sqrt(2) x 0.289 = 0.408pp. The 8/23 card reported champion-minus-
challenger deltas of 0.5-0.7pp on several games. Those are barely above one standard deviation of
pure seed noise: re-running the same two models with different seeds could reorder them. Reporting
such a delta as a model difference is reporting the RNG.

WHY COMMON RANDOM NUMBERS AND NOT JUST MORE TRIALS. More trials shrink the noise as 1/sqrt(n) — a
16x cost to halve it twice. Sharing the stream removes most of it for free, because the arms then
differ only in their parameters and not in which coin flips they saw. The constraint the owner
attaches is the important half: SHARED STREAM, DISTINCT IDENTITY. Two arms that share a stream and
a model_id are not two arms.

AND THE HONEST LIMIT. Common random numbers reduce the variance of a difference by 2*cov, and cov
is not known in advance — it is usually strongly positive here but is not guaranteed to be, so the
independent-seed formula is NOT a valid upper bound under CRN. This module therefore refuses to
quantify CRN delta noise from theory. It reports DELTA_NOISE_UNQUANTIFIED unless the caller supplies
a paired standard deviation actually MEASURED by re-running the pair across seeds. A resolvability
verdict is never asserted from an assumption.

THE LEGACY IDENTITY IS NOT DELETED. V13 at 30,000 trials stays registered and gradeable — a
standard raised today does not retroactively unmake yesterday's forecasts. It is marked
LEGACY_TRIAL_COUNT, it cannot be described as meeting the current standard, and the 100k arm is a
SEPARATE identity so the two can never be pooled or silently substituted for one another.

API
  mc_sd_pp(p, trials)                     -> per-arm Monte Carlo sd, in probability points
  independent_delta_sd_pp(p, n_a, n_b)    -> sd of a difference on INDEPENDENT streams
  trial_compliance(model_id, trials)      -> COMPLIANT | LEGACY_TRIAL_COUNT
  fork_100k(model_id)                     -> the separately identified 100k arm
  crn_stream_id(...)                      -> a stream shared by every arm on one game
  crn_manifest(arms, slate_date, game_ids, simulation_version)
  delta_report(delta_pp, ...)             -> resolvable / not resolvable / unquantified
"""
from __future__ import annotations

MODULE_ID = "simulation_standard"

import hashlib
import json
import math
import os
import re
import sys

TRIAL_STANDARD = 100_000
COMPLIANT = "MEETS_CURRENT_TRIAL_STANDARD"
LEGACY = "LEGACY_TRIAL_COUNT"

RESOLVABLE = "DELTA_EXCEEDS_MONTE_CARLO_NOISE"
NOT_RESOLVABLE = "DELTA_WITHIN_MONTE_CARLO_NOISE"
UNQUANTIFIED = "DELTA_NOISE_UNQUANTIFIED"

# A delta must clear this many sd of pure seed noise before it is called a model difference.
RESOLVABILITY_Z = 2.0

STREAM_FIELDS = ("slate_date", "game_id", "simulation_version")  # deliberately NOT model_id
SEED_BITS = 63


def _num(x):
    if x is None or isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


# =================================================================================================
# 4. TRIAL COUNT
# =================================================================================================
def mc_sd_pp(p, trials):
    """Monte Carlo sd of one arm's probability estimate, in probability POINTS."""
    p, n = _num(p), _num(trials)
    if p is None or n is None or n <= 0 or not (0.0 <= p <= 1.0):
        return None
    return 100.0 * math.sqrt(p * (1.0 - p) / n)


def independent_delta_sd_pp(p, trials_a, trials_b=None):
    """sd of (arm A - arm B) when the two arms draw on INDEPENDENT streams."""
    a = mc_sd_pp(p, trials_a)
    b = mc_sd_pp(p, trials_a if trials_b is None else trials_b)
    if a is None or b is None:
        return None
    return math.sqrt(a * a + b * b)


def trial_compliance(model_id, trials):
    n = _num(trials)
    if n is None or n <= 0:
        return {"model_id": model_id, "trials": trials, "status": LEGACY,
                "reason": "NO_TRIAL_COUNT_RECORDED", "standard": TRIAL_STANDARD,
                "may_claim_standard": False}
    ok = n >= TRIAL_STANDARD
    return {
        "model_id": model_id,
        "trials": int(n),
        "standard": TRIAL_STANDARD,
        "status": COMPLIANT if ok else LEGACY,
        "may_claim_standard": ok,
        "mc_sd_pp_at_p50": mc_sd_pp(0.5, n),
        "required_action": None if ok else
            f"remains registered and gradeable; fork a separate {TRIAL_STANDARD}-trial identity "
            f"for any arm that is to be described as meeting the current standard",
    }


def fork_100k(model_id, trials=TRIAL_STANDARD):
    """The separately identified 100k arm. It MUST NOT collide with the legacy identity."""
    n = int(_num(trials) or 0)
    if n < TRIAL_STANDARD:
        raise ValueError(f"a fork below {TRIAL_STANDARD} trials is not a 100k arm")
    # V13 ids carry their trial count in the tail, e.g. ...s722n30000
    forked = re.sub(r"n\d+$", f"n{n}", model_id) if re.search(r"n\d+$", model_id) else f"{model_id}.n{n}"
    if forked == model_id:
        raise ValueError("the forked identity is identical to the legacy identity")
    return {"legacy_model_id": model_id, "forked_model_id": forked, "trials": n,
            "distinct_identity": True,
            "note": "a separate arm, not a re-tagging: the legacy arm keeps its own grades"}


# =================================================================================================
# 5. COMMON RANDOM NUMBERS
# =================================================================================================
def crn_stream_id(slate_date, game_id, simulation_version, model_id=None):
    """The game-level random stream SHARED by every arm.

    model_id is ACCEPTED AND IGNORED. That is deliberate and it is the whole mechanism: callers hold
    an arm's identity and would naturally pass it, so the key is built by projecting onto
    STREAM_FIELDS rather than by hoping no one adds it. Including model_id would give each arm its
    own stream and reintroduce exactly the independent-seed noise this exists to remove.
    """
    values = {"slate_date": slate_date, "game_id": game_id,
              "simulation_version": simulation_version, "model_id": model_id}
    payload = json.dumps({k: values[k] for k in sorted(STREAM_FIELDS)},
                         sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256(payload.encode()).hexdigest()
    return int(h, 16) % (1 << SEED_BITS)


def crn_manifest(arms, slate_date, game_ids, simulation_version):
    """Shared stream, distinct identity — both asserted, and neither inferred from the other."""
    ids = [a.get("model_id") for a in arms]
    failures = []
    if len(set(ids)) != len(ids):
        failures.append("ARMS_SHARE_A_MODEL_IDENTITY")
    if any(i is None for i in ids):
        failures.append("ARM_WITHOUT_MODEL_IDENTITY")
    streams = {g: crn_stream_id(slate_date, g, simulation_version) for g in game_ids}
    if len(set(streams.values())) != len(game_ids):
        failures.append("TWO_GAMES_SHARE_ONE_STREAM")
    return {
        "slate_date": slate_date,
        "simulation_version": simulation_version,
        "arm_model_ids": ids,
        "identities_distinct": not any(f.startswith("ARMS_SHARE") or f.startswith("ARM_WITHOUT")
                                       for f in failures),
        "streams_shared_across_arms": True,
        "streams": streams,
        "failures": failures,
        "status": "CRN_OK" if not failures else "CRN_REFUSED",
    }


def delta_report(delta_pp, p=0.5, trials_a=None, trials_b=None, crn=False,
                 measured_paired_sd_pp=None):
    """Is a reported arm difference bigger than the noise that produced it?"""
    d = _num(delta_pp)
    if d is None:
        return {"status": UNQUANTIFIED, "reason": "NO_DELTA_SUPPLIED"}
    if crn:
        m = _num(measured_paired_sd_pp)
        if m is None:
            return {"delta_pp": d, "crn": True, "status": UNQUANTIFIED,
                    "reason": "CRN_REDUCES_DELTA_VARIANCE_BY_AN_UNKNOWN_COVARIANCE",
                    "note": "the independent-seed formula is not a valid bound under CRN; supply a "
                            "paired sd measured across seeds or leave the delta unquantified"}
        sd = m
    else:
        sd = independent_delta_sd_pp(p, trials_a, trials_b)
        if sd is None:
            return {"delta_pp": d, "crn": False, "status": UNQUANTIFIED,
                    "reason": "NO_TRIAL_COUNT_SUPPLIED"}
    z = abs(d) / sd if sd > 0 else float("inf")
    return {"delta_pp": d, "crn": bool(crn), "delta_sd_pp": sd, "z": z,
            "threshold_z": RESOLVABILITY_Z,
            "status": RESOLVABLE if z >= RESOLVABILITY_Z else NOT_RESOLVABLE}


# =================================================================================================
def selftest():
    f = []

    # --- the owner's arithmetic, reproduced -------------------------------------------------------
    per = mc_sd_pp(0.5, 30000)
    if abs(per - 0.28868) > 1e-4:
        f.append(f"per-arm sd at p=.5, n=30k should be 0.2887pp, got {per}")
    dsd = independent_delta_sd_pp(0.5, 30000)
    if abs(dsd - 0.4082) > 1e-3:
        f.append(f"independent delta sd should be ~0.41pp, got {dsd}")
    if not (mc_sd_pp(0.5, 100000) < per):
        f.append("100k trials must be quieter than 30k")
    # a delta the size the card reported is NOT resolvable; a big one is
    small = delta_report(0.6, trials_a=30000, trials_b=30000)
    if small["status"] != NOT_RESOLVABLE:
        f.append(f"a 0.6pp delta at 30k independent seeds is not resolvable, got {small}")
    big = delta_report(6.7, trials_a=30000, trials_b=30000)
    if big["status"] != RESOLVABLE:
        f.append("a 6.7pp delta is resolvable")
    if mc_sd_pp(0.5, 0) is not None or mc_sd_pp(1.5, 100) is not None:
        f.append("zero trials or an out-of-range probability must return null, not a number")

    # --- trial standard ---------------------------------------------------------------------------
    v13 = trial_compliance("ml.v13_1.hfa1005.card.s722n30000", 30000)
    if v13["status"] != LEGACY or v13["may_claim_standard"]:
        f.append("a 30k arm does not meet the 100k standard")
    if v13["required_action"] is None:
        f.append("a legacy arm must state the required action")
    ok = trial_compliance("x.n100000", 100000)
    if ok["status"] != COMPLIANT or not ok["may_claim_standard"]:
        f.append("exactly 100k meets the standard")
    if trial_compliance("x", 99999)["may_claim_standard"]:
        f.append("99,999 trials does not meet a 100,000 trial standard")
    if trial_compliance("x", None)["may_claim_standard"]:
        f.append("an arm with no recorded trial count may not claim the standard")

    fk = fork_100k("ml.v13_1.hfa1005.card.s722n30000")
    if fk["forked_model_id"] == fk["legacy_model_id"]:
        f.append("the fork must be a distinct identity")
    if not fk["forked_model_id"].endswith("n100000"):
        f.append(f"the fork should carry its trial count, got {fk['forked_model_id']}")
    if not trial_compliance(fk["forked_model_id"], fk["trials"])["may_claim_standard"]:
        f.append("the forked arm must itself meet the standard")
    try:
        fork_100k("x", trials=30000)
        f.append("a fork below the standard must raise")
    except ValueError:
        pass

    # --- common random numbers --------------------------------------------------------------------
    s1 = crn_stream_id("2026-08-23", "TB@BAL", "v13_1")
    s2 = crn_stream_id("2026-08-23", "TB@BAL", "v13_1")
    s3 = crn_stream_id("2026-08-23", "STL@PHI", "v13_1")
    if s1 != s2:
        f.append("the stream must be reproducible for one game")
    if s1 == s3:
        f.append("two games must not share a stream")
    if crn_stream_id("2026-08-24", "TB@BAL", "v13_1") == s1:
        f.append("a different slate date must give a different stream")
    # the whole point: the stream does not depend on which arm is drawing it
    if "model_id" in STREAM_FIELDS:
        f.append("model_id must not be part of the stream key")
    a_stream = crn_stream_id("2026-08-23", "TB@BAL", "v13_1", model_id="ml.v13_1.card.s722n30000")
    b_stream = crn_stream_id("2026-08-23", "TB@BAL", "v13_1", model_id="mlb.baseline_offset.v0_1")
    if not (a_stream == b_stream == s1):
        f.append("two arms on the same game must draw the identical stream regardless of identity")

    arms = [{"model_id": "mlb.expanding_home_prior.beta_10_10"},
            {"model_id": "ml.v13_1.hfa1005.card.s722n30000"},
            {"model_id": "mlb.baseline_offset.adaptive.v0_1"}]
    man = crn_manifest(arms, "2026-08-23", ["TB@BAL", "STL@PHI"], "v13_1")
    if man["status"] != "CRN_OK" or not man["identities_distinct"]:
        f.append(f"three distinct arms on a shared stream must pass, got {man}")
    dup = crn_manifest([arms[0], arms[0]], "2026-08-23", ["TB@BAL"], "v13_1")
    if dup["status"] != "CRN_REFUSED" or dup["identities_distinct"]:
        f.append("two arms sharing a model identity must be refused")
    noid = crn_manifest([{"model_id": None}, arms[1]], "2026-08-23", ["TB@BAL"], "v13_1")
    if noid["status"] != "CRN_REFUSED":
        f.append("an arm without a model identity must be refused")

    # --- the honest limit: CRN noise is not quantified from theory ---------------------------------
    c = delta_report(0.6, crn=True)
    if c["status"] != UNQUANTIFIED:
        f.append("CRN delta noise must not be asserted from the independent-seed formula")
    cm = delta_report(0.6, crn=True, measured_paired_sd_pp=0.10)
    if cm["status"] != RESOLVABLE:
        f.append("with a MEASURED paired sd, a 0.6pp delta at sd 0.10pp is resolvable")
    cm2 = delta_report(0.10, crn=True, measured_paired_sd_pp=0.20)
    if cm2["status"] != NOT_RESOLVABLE:
        f.append("a measured sd wider than the delta is not resolvable")
    if delta_report(0.6)["status"] != UNQUANTIFIED:
        f.append("no trial count and no CRN means unquantified, not resolvable")

    for x in f:
        print("FAIL:", x)
    if not f:
        print("simulation_standard selftest: OK")
    return f


MUTANTS = [
    ("the delta sd drops the two-arm term, halving the reported noise",
     "    return math.sqrt(a * a + b * b)", "    return a"),
    ("the per-arm sd loses its square root, so noise scales as 1/n",
     "    return 100.0 * math.sqrt(p * (1.0 - p) / n)", "    return 100.0 * (p * (1.0 - p) / n)"),
    ("30k trials pass the 100k standard",
     "    ok = n >= TRIAL_STANDARD", "    ok = n >= 30000"),
    ("the standard itself is quietly lowered",
     "TRIAL_STANDARD = 100_000", "TRIAL_STANDARD = 30_000"),
    ("an arm with no trial count may claim the standard",
     '        return {"model_id": model_id, "trials": trials, "status": LEGACY,\n                "reason": "NO_TRIAL_COUNT_RECORDED", "standard": TRIAL_STANDARD,\n                "may_claim_standard": False}',
     '        return {"model_id": model_id, "trials": trials, "status": COMPLIANT,\n                "reason": "NO_TRIAL_COUNT_RECORDED", "standard": TRIAL_STANDARD,\n                "may_claim_standard": True}'),
    ("a legacy arm stops being told what to do about it",
     '        "required_action": None if ok else', '        "required_action": None if True else'),
    ("the fork re-tags the legacy identity instead of forking it",
     '    forked = re.sub(r"n\\d+$", f"n{n}", model_id) if re.search(r"n\\d+$", model_id) else f"{model_id}.n{n}"',
     "    forked = model_id"),
    ("a fork below the standard is allowed",
     "    if n < TRIAL_STANDARD:", "    if False:"),
    ("model_id enters the stream key, so every arm gets its own noise again",
     'STREAM_FIELDS = ("slate_date", "game_id", "simulation_version")',
     'STREAM_FIELDS = ("slate_date", "game_id", "simulation_version", "model_id")'),
    ("every game shares one stream",
     '    streams = {g: crn_stream_id(slate_date, g, simulation_version) for g in game_ids}',
     '    streams = {g: crn_stream_id(slate_date, "ALL", simulation_version) for g in game_ids}'),
    ("two arms may share one model identity under CRN",
     "    if len(set(ids)) != len(ids):", "    if False:"),
    ("an arm with no identity passes CRN registration",
     "    if any(i is None for i in ids):", "    if False:"),
    ("CRN delta noise is asserted from the independent-seed formula",
     '            return {"delta_pp": d, "crn": True, "status": UNQUANTIFIED,',
     '            return {"delta_pp": d, "crn": True, "status": NOT_RESOLVABLE,'),
    ("the resolvability threshold collapses to a bare sign test",
     "RESOLVABILITY_Z = 2.0", "RESOLVABILITY_Z = 0.0"),
    ("a delta with no trial count is called resolvable",
     '            return {"delta_pp": d, "crn": False, "status": UNQUANTIFIED,\n                    "reason": "NO_TRIAL_COUNT_SUPPLIED"}',
     '            return {"delta_pp": d, "crn": False, "status": RESOLVABLE,\n                    "reason": "NO_TRIAL_COUNT_SUPPLIED"}'),
    ("an out-of-range probability produces a number",
     "    if p is None or n is None or n <= 0 or not (0.0 <= p <= 1.0):", "    if False:"),
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
