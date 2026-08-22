#!/usr/bin/env python3
"""KEYED CAUSAL STARTER ATTRIBUTION — a controlled per-game counterfactual, not a card diff.

WHY THIS MODULE EXISTS (the incidents it is built from)

1. THE COUPLING DEFECT (2026-08-17, external auditor; see harness/rng_noise_study.py).
   harness/daily_card.py drives an ENTIRE slate from ONE global generator,
   np.random.default_rng(722), consumed sequentially in slate order. numpy's gamma and poisson
   samplers are rejection-based, so the NUMBER of underlying uniforms a game consumes depends on
   its parameters. Change one starter in the first game and every LATER game on the slate is drawn
   from a re-coupled stream. The registered v1->v2 card delta is therefore

       observed delta = starter information + sequential-RNG coupling noise

   and a v1->v2 card diff is not an effect estimate for any single game.

2. THE MISLABELLING DEFECT (owner card review, 2026-08-21, defect 2). A "starter move" was
   rendered on a bettor-facing card as a causal effect. harness/decision_card.py render-gate
   check #10 now refuses the phrase "starter effect" unless it is sourced from the keyed-seed
   reference harness. THIS IS THAT HARNESS, and assert_not_causal() below is that refusal in
   callable form so the rule travels with the number instead of living only in a text gate.

3. THE CONTROL-PRECISION DEFECT (8/21 v2 contract audit). Of 30 starter slots, 3 were unresolved
   — but all 15 GAMES received at least one named starter, so NOT ONE GAME was a clean untreated
   control. Waiting for naturally untreated games therefore never produces a control; the control
   has to be MANUFACTURED per game, which is what the four arms below do.

WHAT IS CONTROLLED, AND HOW

  keyed seed        seed = int(sha256("KEYED|{game}|{date}").hexdigest()[:8], 16). Per GAME, so a
                    change in game 1 cannot reach game 9. Deterministic and reproducible from the
                    game key and slate date alone — no stream position, no slate order.
  common random     the SAME seed opens every arm of the same game (paired comparison). Two arms
  numbers (CRN)     with identical stat vectors are then bit-identical, so their delta is EXACTLY
                    0.0 — the property the paired-arm fixture asserts.
  four arms         (a) both slots league-average CAP      <- the manufactured control
                    (b) away starter real  + home CAP
                    (c) away CAP           + home starter real
                    (d) both real                          <- the registered v2 configuration
  reported          AWAY-ONLY = b-a, HOME-ONLY = c-a, JOINT = d-a,
                    NON-ADDITIVITY = JOINT - (AWAY-ONLY + HOME-ONLY)   [the interaction term]

WHY THE INTERACTION TERM IS NOT DECORATION. In daily_card.sim() the two run distributions are
SEPARABLE by slot — away runs raA are driven by the HOME starter (rs(hsp), pfa via bip(hsp), shape
sa via hsp["k"]) and home runs rhH by the AWAY starter (rs(asp), pfh via bip(asp), shape sh via
asp["k"]). But the reported quantity is P(home win) = P(rhH > raA) plus a tie-break, a NONLINEAR
functional of both. Two separately small slot effects can therefore combine into something that is
not their sum, and only the joint arm can see it. Note the direction trap this creates and which
the field names preserve: the AWAY-ONLY delta is the effect of resolving the AWAY slot, and in this
sim that pitcher suppresses the HOME team's scoring.

WHAT CRN DOES *NOT* BUY (stated because overclaiming it would repeat defect 2 in a new place).
A common seed is a common STARTING STATE, not a common draw sequence: because gamma/poisson are
rejection samplers, arm (b) can consume a different number of uniforms than arm (a) and desynchronise
partway through its own game. CRN here guarantees (i) exact reproducibility, (ii) an exactly-zero
delta for identical arms, and (iii) PARTIAL variance reduction. It does not guarantee draw-for-draw
pairing, which is why the per-delta standard error is reported as null-with-a-reason rather than
assumed negligible — a single replicate cannot estimate it. Replicated keyed estimates with
intervals are harness/rng_noise_study.py's paired_study().

SCOPE LIMIT (owner terminology ruling 2026-08-17, and lesson 20 of 2026-08-22). Every number here
is a LOCAL SENSITIVITY of a frozen artifact: how far V13's output moves when one input slot is
swapped, under this engine, on this slate. It is NOT evidence that starter resolution improves
prospective accuracy. On 8/21 the home teams went 14-1 and an always-pick-home heuristic beat the
resolved-starter cohort by four games; the starter effect remains UNESTABLISHED. Sensitivity and
skill are different claims and this module measures only the first.

The simulation math is not re-transcribed here. It is card_render.sim_full(), the transcription of
daily_card.sim() that card_render's own selftest verifies reproduces a registered card field for
field; re-typing it would create a second copy to keep in sync. attribute() additionally REFUSES to
run unless both cards replay exactly under the frozen global-sequential discipline first.

READS ONLY. Registers nothing, grades nothing, and writes no artifact unless an operator names an
explicit --out path outside every registered-artifact directory.

Usage: python3 harness/starter_attribution.py --selftest
       python3 harness/starter_attribution.py --date 2026-08-21 [--n 200000] [--json] [--out PATH]
"""
# =============================================================================================
# QUARANTINED — BUILT TO THE OWNER ACCEPTANCE CONTRACT, AWAITING INDEPENDENT REVIEW (2026-08-22)
# Contract: docs/experiments/2026-08-22_STARTER_ATTRIBUTION_ACCEPTANCE_CONTRACT.json
#
# THE THREE STATES. Every reported quantity carries exactly one:
#   MEASURED_PAIRED_DELTA  both arms genuinely differ, drawn under identical random numbers
#   STRUCTURAL_ZERO        the arms are identical BY CONSTRUCTION; the 0.0 is attached to the state,
#                          never placed in a numeric field a reader would take for a measurement
#   NOT_MEASURABLE         the counterfactual could not be formed; value null, reason REQUIRED
#
# DESIGN, as specified: draws keyed by model ID + game ID + date + replicate index; common random
# numbers across arms; away-only, home-only and both scenarios; the interaction reported SEPARATELY
# because joint movement need not equal the sum; missing/CAP/unregistered slots null-with-reason;
# PAIRED Monte-Carlo uncertainty across independently keyed replicates; results described as model
# counterfactual deltas, never real-world causal effects; scenario order cannot change results.
# Scenario keys the RECORD, not the draws — putting it in the seed would destroy the common random
# numbers the same contract requires.
#
# `--mutants` runs 29 source mutants, one per rule, and requires the selftest to FAIL for each.
# 29/29 are KILLED. That number is NOT the release condition. The owner's condition is an
# INDEPENDENT review killing these mutants, and this module's own suite passing is exactly the
# standing lesson 21 exists to deny. Three defects were found in the fixtures while building them:
# the ten falsification fixtures were briefly DEAD CODE below an early return (their failures were
# collected and discarded, and every mutant they guard survived); two "binding" mutants left the
# covered field reachable by another route and so proved nothing; and one order mutant could not
# break a property that holds structurally. All three were repairs to the TEST, not the code.
#
# UNTIL INDEPENDENT REVIEW: not imported by healthcheck, not used for any card, grade or decision,
# numbers not quoted.
# =============================================================================================

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
sys.path.insert(0, os.path.join(BASE, "harness"))

import numpy as np  # noqa: E402

import card_render as cr  # noqa: E402  — the already-verified transcription of daily_card.sim()
from rng_noise_study import _ab, raw_pf, team_form  # noqa: E402

DEFAULT_N = 200_000
FROZEN_SEED, FROZEN_N = 722, 30000  # daily_card.py's global-sequential discipline

# daily_card.py: CAP = dict(era=LG_ERA, gs=0, k=LG_K, bb=LG_BB, ek=None)
LG_ERA, LG_K, LG_BB = 4.20, 22.0, 8.5
CAP_STATS = {"era": LG_ERA, "gs": 0, "k": LG_K, "bb": LG_BB, "ek": None}
# The ONLY stat fields daily_card.sim() reads. "ek" is a display projection and never enters the
# simulation, so it is deliberately excluded from the CAP predicate below.
SIM_STAT_FIELDS = ("era", "gs", "k", "bb")

ARM_KEYS = ("a_both_cap", "b_away_real_home_cap", "c_away_cap_home_real", "d_both_real")
# The scenario each arm expresses, and which slot it is ALLOWED to move relative to the control.
ARM_SCENARIO = {"a_both_cap": "CONTROL_BOTH_LEAGUE_AVERAGE",
                "b_away_real_home_cap": "AWAY_STARTER_ONLY",
                "c_away_cap_home_real": "HOME_STARTER_ONLY",
                "d_both_real": "BOTH_STARTERS"}
ARM_MAY_MOVE = {"a_both_cap": (), "b_away_real_home_cap": ("away",),
                "c_away_cap_home_real": ("home",), "d_both_real": ("away", "home")}
# The model whose response is being probed. It is part of the DRAW KEY: two model identities must
# never share a draw sequence, or a delta measured under one could be read as the other's.
MODEL_ID = "ml.v13_1.hfa1005.card"
# Replicates for the PAIRED Monte-Carlo uncertainty the owner requires. Each replicate re-keys the
# draws (rep index enters the seed) and re-runs all four arms, so the spread of the PAIRED delta
# across replicates is a real sampling distribution rather than a closed form assumed to apply.
DEFAULT_REPS = 5

# The three states every reported quantity carries (owner acceptance contract 2026-08-22).
MEASURED = "MEASURED_PAIRED_DELTA"
STRUCTURAL_ZERO = "STRUCTURAL_ZERO"
NOT_MEASURABLE = "NOT_MEASURABLE"
DH_SUFFIX = {"DH1": "-G1", "DH2": "-G2"}  # rng_noise_study's doubleheader disambiguation

# Directories holding registered artifacts. --out may never land in one of these (R6: registered
# artifacts are append-only and are never rewritten by a measurement module).
REGISTERED_PREFIXES = ("cards/", "data/cards_unified/", "data/mlb/forecasts/",
                       "data/wnba/forecasts/", "data/backfill/")

R1_NO_TREATMENT = ("R1_NO_TREATMENT — this slot is league-average CAP in v2, so the arm is "
                   "IDENTICAL to the control by construction. The measured delta would be exactly "
                   "0.0 for a mechanical reason, not because the starter was measured and found "
                   "not to matter. Reported null rather than 0.0.")
R1_NO_INTERACTION = ("R1_NO_INTERACTION — an interaction term requires BOTH slots to be treated. "
                     "With one slot untreated the joint arm equals the single treated arm and the "
                     "arithmetic collapses to 0.0 by construction, which is not a measurement.")
R1_SINGLE_REPLICATE = ("R1_SINGLE_REPLICATE — one keyed replicate per game cannot estimate the "
                       "standard error of its own paired delta, and CRN pairing here is partial "
                       "(rejection samplers desynchronise), so no closed form applies either. For "
                       "an interval, run harness/rng_noise_study.py paired_study() with reps > 1.")
R1_V1_NOT_CAP = ("R1_BASIS_MISMATCH — the v1 card does not carry league-average CAP in both slots, "
                 "so arm (a) is not v1's configuration and the registered v1->v2 delta is a "
                 "different contrast from the joint delta. Not differenced.")


# --------------------------------------------------------------------------------------------
# the refusal
# --------------------------------------------------------------------------------------------

def assert_not_causal(label):
    """REFUSE to call a delta a starter effect unless it came from the keyed harness.

    The 2026-08-21 owner card review found "starter move" rendered as a causal effect on a
    bettor-facing card. harness/decision_card.py check #10 gates the rendered TEXT; this gates the
    LABEL at the point of construction, so a number cannot acquire a causal name on its way to a
    report that never passes through that render gate.

    Whitespace is normalised before matching so "starter  effect" cannot slip past, and matching is
    case-insensitive because the phrase appears capitalised in the operations log. Returns the label
    unchanged on success so it can be used inline: row["label"] = assert_not_causal(f"...").
    """
    if not label:
        return label
    if not isinstance(label, str):
        raise TypeError(f"assert_not_causal expects a string label, got {type(label).__name__}")
    flat = " ".join(label.lower().split())
    if "starter effect" in flat and "keyed" not in flat:
        raise ValueError(
            "REFUSED: this label calls a delta a 'starter effect' without naming the keyed-seed "
            "harness. A sequential v1->v2 card delta mixes starter information with global-RNG "
            "coupling noise and is not a causal effect for any single game. Use "
            "sequential_delta_label() for an observed card delta, or take the number from "
            f"attribute(). Offending label: {label!r}")
    return label


def sequential_delta_label(dpp):
    """Wording for a v1->v2 CARD delta. Mirrors decision_card.delta_display(dpp) — deliberately
    carries no causal claim, and is passed through the refusal so the two can never drift apart."""
    return assert_not_causal(f"observed change {dpp:+.2f} points versus the all-league-average "
                             f"version (not yet separated from simulation coupling noise)")


def keyed_delta_label(dpp):
    """Wording for a delta produced by THIS module. Mirrors decision_card.delta_display(keyed=True)."""
    return assert_not_causal(f"keyed-seed reference starter effect {dpp:+.2f} points")


# --------------------------------------------------------------------------------------------
# pure helpers
# --------------------------------------------------------------------------------------------

def _seed_input(game, date, model_id=MODEL_ID, rep=0):
    """The draw key, stated as a string so it appears verbatim in every record.

    KEYED BY: model identity, game identity, slate date, replicate index.
    NOT KEYED BY: slate position (that is the 2026-08-17 coupling defect) and NOT by SCENARIO.

    Scenario is deliberately absent from the DRAW key. The acceptance contract requires both
    "key simulations by model ID, game ID, scenario and simulation index" AND "use identical random
    draws for baseline and counterfactual"; those two can only both hold if scenario keys the
    RECORD and not the draws. Putting scenario in the seed would give every arm its own random
    sequence, which is exactly what destroys common random numbers and turns a paired contrast back
    into the difference of two independently noisy estimates."""
    return f"KEYED|{model_id}|{game}|{date}|rep{rep}"


def _seed(game, date, model_id=MODEL_ID, rep=0):
    """32 bits (8 hex chars) of the draw key; np.random.default_rng accepts it directly."""
    return int(hashlib.sha256(_seed_input(game, date, model_id, rep).encode()).hexdigest()[:8], 16)


def _arm_binding(model_id, game, date, rep, n, seed, arms):
    """Bind the reported deltas to the ACTUAL draw configuration they came from.

    Without this a record's numbers float free of the arrays that produced them: a later change to
    n, to the seed, to the model identity or to an arm's stat vector leaves the delta looking
    equally authoritative. The binding is a hash over every input that selects the draws, so a
    record whose binding does not recompute is not the record it claims to be."""
    payload = json.dumps({
        "model_id": model_id, "game": game, "date": date, "rep": rep, "n": n, "seed": seed,
        "seed_input": _seed_input(game, date, model_id, rep),
        "arms": [{"scenario": ARM_SCENARIO[k],
                  "away": {f: a.get(f) for f in SIM_STAT_FIELDS},
                  "home": {f: h.get(f) for f in SIM_STAT_FIELDS}}
                 for k, (a, h) in zip(ARM_KEYS, arms)],
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _assert_one_slot_changed(arms):
    """Every single-starter arm must move EXACTLY the slot its scenario names.

    An arm that quietly changes both slots still produces a plausible number, and that number would
    be reported as the effect of one starter. The check is over the four stat fields sim() reads."""
    control_away, control_home = arms[0]
    bad = []
    for key, (asp, hsp) in zip(ARM_KEYS, arms):
        may = ARM_MAY_MOVE[key]
        away_moved = any(asp.get(f) != control_away.get(f) for f in SIM_STAT_FIELDS)
        home_moved = any(hsp.get(f) != control_home.get(f) for f in SIM_STAT_FIELDS)
        if away_moved and "away" not in may:
            bad.append(f"{key} ({ARM_SCENARIO[key]}) moved the AWAY slot, which its scenario "
                       f"forbids — a two-slot change reported as a one-starter effect")
        if home_moved and "home" not in may:
            bad.append(f"{key} ({ARM_SCENARIO[key]}) moved the HOME slot, which its scenario "
                       f"forbids — a two-slot change reported as a one-starter effect")
    if bad:
        raise ValueError("REFUSED: " + "; ".join(bad))
    return True


def classify(value, arms_identical, measurable=True, reason=None):
    """THE THREE STATES (owner acceptance contract 2026-08-22).

    A structural zero must never render as an observed measurement, so it is returned as its own
    state with the zero attached to the state — never as a bare numeric field a reader would take
    for a measurement."""
    if not measurable:
        return {"state": NOT_MEASURABLE, "value_pp": None,
                "reason": reason or ("NOT_MEASURABLE — the counterfactual could not be formed; " +
                                     "no reason was supplied, which is itself an R1 violation")}
    if arms_identical:
        return {"state": STRUCTURAL_ZERO, "value_pp": None, "structural_value_pp": 0.0,
                "reason": ("STRUCTURAL_ZERO — the two arms are IDENTICAL by construction, so the "
                           "difference is 0.0 as an arithmetic fact about the setup. It is not an "
                           "observation that the starter did not matter.")}
    return {"state": MEASURED, "value_pp": _r(value), "reason": None}


def _game_key(row):
    """away@home, with the doubleheader suffix rng_noise_study uses. Without the suffix both halves
    of a doubleheader would hash to ONE seed and share draws, silently correlating two independent
    contrasts. attribute_rows() additionally refuses any slate whose keys are not unique."""
    return f'{row["away"]}@{row["home"]}{DH_SUFFIX.get(row.get("gamePk"), "")}'


def _is_cap(stats):
    """True when this slot's stat vector IS the league-average CAP the simulation would receive.

    A STAT-VECTOR predicate, deliberately not a name predicate. unified_card.slot_status() answers
    a reporting question ("is this slot TBD, a registry miss, low-sample, or resolved?"); the arms
    here are defined by the numbers handed to sim(), so the right test is over exactly the four
    fields sim() reads. The consequence worth stating: a LOW_SAMPLE starter (gs=1, real stats,
    shrunk ~89% toward league average — the Brad Lord case the owner caught on 8/21) is NOT CAP and
    IS a treatment here, even though daily_card's broader `capped` flag fires for him."""
    return all(stats.get(f) == CAP_STATS[f] for f in SIM_STAT_FIELDS)


def _slot_class(name, stats):
    """Reporting label for one slot. CAP_TBD / CAP_REGISTRY_MISS / LOW_SAMPLE / RESOLVED, keeping
    the four predicates unconflated exactly as unified_card.slot_status() requires."""
    if _is_cap(stats):
        return "CAP_TBD" if (name in (None, "TBD", "TBA")) else "CAP_REGISTRY_MISS"
    return "LOW_SAMPLE" if stats.get("gs", 0) < 2 else "RESOLVED"


def _arms(away_real, home_real):
    """The four (away_stats, home_stats) pairs, in the frozen order a, b, c, d.

    Order and content are asserted by fixture: a swapped b/c would silently transpose every
    away-only and home-only delta on every card built from this module, and both would still look
    plausible."""
    return ((dict(CAP_STATS), dict(CAP_STATS)),
            (dict(away_real), dict(CAP_STATS)),
            (dict(CAP_STATS), dict(home_real)),
            (dict(away_real), dict(home_real)))


def _deltas(p_a, p_b, p_c, p_d):
    """The four reported quantities, in probability percentage points (never bare 'points' — the
    unit rule of 2026-08-20; ATS deltas are spread points and the two never share a sentence)."""
    away = (p_b - p_a) * 100.0
    home = (p_c - p_a) * 100.0
    joint = (p_d - p_a) * 100.0
    return {"away_only": away, "home_only": home, "joint": joint,
            "non_additivity": joint - (away + home)}


def _paired_se(per_rep):
    """Standard error of each PAIRED delta across independently keyed replicates.

    The contrast is what is being measured, so the contrast is what gets an interval. One replicate
    yields None WITH a reason rather than 0.0 — a single observation has no spread, and printing
    0.0 there would read as a perfectly precise estimate."""
    keys = ("away_only", "home_only", "joint", "non_additivity")
    out = {}
    for k in keys:
        vals = [r[k] for r in per_rep if r.get(k) is not None]
        if len(vals) < 2:
            out[k] = None
            continue
        m = sum(vals) / len(vals)
        var = sum((v - m) ** 2 for v in vals) / (len(vals) - 1)
        out[k] = float(np.sqrt(var / len(vals)))
    return out


def _mc_se_pp(p, n):
    """Monte-Carlo standard error of ONE arm's probability, in pp. An UNPAIRED bound: the paired
    delta's SE is smaller, but see R1_SINGLE_REPLICATE — it is not estimated from one replicate."""
    return float(np.sqrt(max(p * (1.0 - p), 0.0) / n) * 100.0)


def _r(x, k=4):
    return None if x is None else round(float(x), k)


def _dist_report(vals, unit="pp"):
    """Spread of a set of deltas. The mean NEVER travels alone (unified_card.totals_report rule,
    imposed after a report quoted a mean that cancellation had hollowed out): mean absolute, median
    absolute, signed mean and the largest signed value are always reported together."""
    if not vals:
        return {"n": 0, "unit": unit, "mean_abs": None, "median_abs": None,
                "signed_mean": None, "largest_signed": None,
                "reason_null": "R1_EMPTY — no game contributed a value to this statistic"}
    a = [abs(v) for v in vals]
    return {"n": len(vals), "unit": unit, "mean_abs": _r(sum(a) / len(a)),
            "median_abs": _r(statistics.median(a)), "signed_mean": _r(sum(vals) / len(vals)),
            "largest_signed": _r(max(vals, key=abs))}


# --------------------------------------------------------------------------------------------
# simulation arms
# --------------------------------------------------------------------------------------------

def run_arm(asp, hsp, form, aw, hm, pf, n, seed):
    """One arm, from a FRESH generator seeded with the game's keyed seed.

    Fresh-per-arm is the whole mechanism: a shared generator advanced across arms is precisely the
    daily_card discipline this module replaces, and under it two IDENTICAL arms do not agree (the
    falsification fixture in selftest() demonstrates exactly that)."""
    return cr.sim_full(asp, hsp, form, aw, hm, pf, n, np.random.default_rng(seed))


def verify_transcription(rows, form, seed=FROZEN_SEED, n=FROZEN_N):
    """Replay a registered card under the FROZEN global-sequential RNG and return the mismatches.

    The same doctrine card_render applies: a counterfactual built on a sim that does not reproduce
    the registered card is worse than no counterfactual, because every delta would then be measured
    against a card nobody registered. Also catches as-of drift — replaying with results.csv rows
    from the card's own date silently introduces look-ahead and moves the probabilities."""
    rng = np.random.default_rng(seed)
    bad = []
    for r in rows:
        pf = raw_pf(form, _ab(r["home"]))
        s = cr.sim_full(r["asp_stats"], r["hsp_stats"], form, _ab(r["away"]), _ab(r["home"]),
                        pf, n, rng)
        if round(s["hw"], 3) != r["v13"]["home_wp"]:
            bad.append(f'{r["away"]}@{r["home"]}: replay {round(s["hw"],3)} vs registered '
                       f'{r["v13"]["home_wp"]}')
    return bad


# --------------------------------------------------------------------------------------------
# attribution
# --------------------------------------------------------------------------------------------

def attribute_rows(v1_rows, v2_rows, date, form, pf_of, n=DEFAULT_N, reps=DEFAULT_REPS,
                   model_id=MODEL_ID, arm_order=None, arms_builder=None):
    """Per-game keyed counterfactual over two aligned card row lists. Pure with respect to disk:
    `form` is a (rf, ra, g, venue) tuple and `pf_of(home_abbr) -> float` supplies the park factor,
    so the whole estimator is exercisable on synthetic input without touching a registered card."""
    if not isinstance(n, int) or n < 1:
        raise ValueError(f"n must be a positive int (draws per arm), got {n!r}")
    if len(v1_rows) != len(v2_rows):
        raise ValueError(f"REFUSED: v1 has {len(v1_rows)} rows and v2 has {len(v2_rows)}. The arms "
                         "must be the same games in the same order or the contrast is not paired.")
    seen = {}
    out = []
    for i, (r1, r2) in enumerate(zip(v1_rows, v2_rows)):
        for f in ("away", "home", "gamePk"):
            if r1.get(f) != r2.get(f):
                raise ValueError(f"REFUSED: row {i} disagrees on {f} ({r1.get(f)!r} vs "
                                 f"{r2.get(f)!r}). Slate order must be identical across arms.")
        if r1.get("park") != r2.get("park"):
            raise ValueError(f"REFUSED: row {i} ({r1['away']}@{r1['home']}) has park {r1['park']} "
                             f"in v1 and {r2['park']} in v2. A park-factor difference contaminates "
                             "a contrast that is supposed to isolate starters.")
        key = _game_key(r2)
        if key in seen:
            raise ValueError(f"REFUSED: duplicate game key {key!r} (rows {seen[key]} and {i}). Two "
                             "games would share one keyed seed and their contrasts would be "
                             "correlated; a doubleheader needs gamePk DH1/DH2 to disambiguate.")
        seen[key] = i

        aw, hm = _ab(r2["away"]), _ab(r2["home"])
        pf = pf_of(hm)
        away_real, home_real = r2["asp_stats"], r2["hsp_stats"]
        away_treated, home_treated = not _is_cap(away_real), not _is_cap(home_real)

        # arms_builder is injected ONLY by the fixture that proves the assertion below is
        # actually called. Defaulting to _arms keeps the production path identical.
        arms = (arms_builder or _arms)(away_real, home_real)
        # An arm may move ONLY the slot its scenario names. Checked before any draw is taken.
        _assert_one_slot_changed(arms)
        # SCENARIO ORDER INVARIANCE: arms are addressed by NAME, never by position, so evaluating
        # them in any order yields the same record. `arm_order` exists purely so a fixture can prove
        # that — the draws are keyed by identity, so a permutation cannot reach the numbers.
        order = list(arm_order or ARM_KEYS)
        if sorted(order) != sorted(ARM_KEYS):
            raise ValueError(f"REFUSED: arm_order {order} is not a permutation of {list(ARM_KEYS)}")
        arm_of = dict(zip(ARM_KEYS, arms))   # CANONICAL names, never the caller's order

        seed = _seed(key, date, model_id, 0)
        binding = _arm_binding(model_id, key, date, 0, n, seed, arms)
        sims, per_rep = {}, []
        for rep_i in range(max(1, int(reps))):
            rseed = _seed(key, date, model_id, rep_i)
            p_by_arm = {}
            for arm_key in order:                      # ORDER-INDEPENDENT: addressed by name
                asp, hsp = arm_of[arm_key]
                sim = run_arm(asp, hsp, form, aw, hm, pf, n, rseed)
                p_by_arm[arm_key] = sim
                if rep_i == 0:
                    sims[arm_key] = {"scenario": ARM_SCENARIO[arm_key],
                                     "p_home": _r(sim["hw"], 6), "proj_total": _r(sim["tot"], 3),
                                     "proj_away_runs": _r(sim["proj_away"], 3),
                                     "proj_home_runs": _r(sim["proj_home"], 3),
                                     "mc_se_pp_unpaired": _r(_mc_se_pp(sim["hw"], n)),
                                     "draw_key": _seed_input(key, date, model_id, rep_i),
                                     "seed": rseed, "n_draws": n,
                                     "away_stats": asp, "home_stats": hsp}
            # deltas from the UNROUNDED arm probabilities: rounding first would put a floor of
            # ~1e-4pp under an identity that must be exactly 0.0 for an untreated arm.
            per_rep.append(_deltas(*[p_by_arm[k]["hw"] for k in ARM_KEYS]))
        d = {k: per_rep[0][k] for k in per_rep[0]}
        # PAIRED Monte-Carlo uncertainty: the spread of the PAIRED delta across independently keyed
        # replicates. This is a sampling distribution of the contrast itself, not a closed form
        # borrowed from one arm's binomial error.
        se = _paired_se(per_rep)

        # THREE STATES. An untreated slot means arm b (or c) is identical to the control BY
        # CONSTRUCTION — a structural zero, never a measurement, and never a bare 0.0.
        states = {
            "away_only": classify(d["away_only"], arms_identical=not away_treated),
            "home_only": classify(d["home_only"], arms_identical=not home_treated),
            "joint": classify(d["joint"],
                              arms_identical=not (away_treated or home_treated)),
            "non_additivity": classify(
                d["non_additivity"],
                arms_identical=False,
                measurable=(away_treated and home_treated),
                reason=R1_NO_INTERACTION),
        }
        nulls = {k: v["reason"] for k, v in states.items() if v["reason"]}
        rep = {k: v["value_pp"] for k, v in states.items()}

        v1_basis_is_cap = _is_cap(r1["asp_stats"]) and _is_cap(r1["hsp_stats"])
        seq = (r2["v13"]["home_wp"] - r1["v13"]["home_wp"]) * 100.0
        if v1_basis_is_cap:
            residual = seq - d["joint"]
            residual_null = None
        else:
            residual, residual_null = None, R1_V1_NOT_CAP

        out.append({
            "game": key, "date": date, "gamePk": r2.get("gamePk"),
            "away": r2["away"], "home": r2["home"],
            "model_id": model_id,
            "seed_input": _seed_input(key, date, model_id, 0), "seed": seed,
            "draw_binding_sha256": binding,
            "binding_covers": ["model_id", "game", "date", "rep", "n", "seed", "seed_input",
                               "per-arm scenario", "per-arm stat vectors"],
            "n_per_arm": n, "replicates": max(1, int(reps)), "park_factor_raw": _r(pf, 6),
            "away_slot": {"name_v1": r1.get("asp"), "name_v2": r2.get("asp"),
                          "class_v1": _slot_class(r1.get("asp"), r1["asp_stats"]),
                          "class_v2": _slot_class(r2.get("asp"), away_real),
                          "treated": away_treated},
            "home_slot": {"name_v1": r1.get("hsp"), "name_v2": r2.get("hsp"),
                          "class_v1": _slot_class(r1.get("hsp"), r1["hsp_stats"]),
                          "class_v2": _slot_class(r2.get("hsp"), home_real),
                          "treated": home_treated},
            "arms": sims,
            "arm_scenarios": dict(ARM_SCENARIO),
            "delta_states": states,
            "deltas_pp": {k: _r(v) for k, v in rep.items()},
            "deltas_null_reasons": nulls,
            "delta_se_pp": {k: _r(v) for k, v in se.items()},
            "delta_se_basis": (f"paired standard error across {max(1, int(reps))} independently "
                               f"keyed replicates of the SAME contrast (rep index enters the draw "
                               f"key); n={n} draws per arm per replicate. Not a closed form."),
            "registered_sequential_delta_pp": _r(seq),
            "registered_minus_keyed_joint_pp": _r(residual),
            "registered_minus_keyed_null_reason": residual_null,
            "v1_basis_is_both_cap": v1_basis_is_cap,
            "keyed_label": keyed_delta_label(d["joint"]),
            "sequential_label": sequential_delta_label(seq),
            "direction_note": ("AWAY-ONLY is the effect of resolving the AWAY slot; in "
                               "daily_card.sim() that pitcher drives the HOME team's run "
                               "distribution, so a positive away-only delta means the away starter "
                               "RAISED the home win probability relative to league average."),
            "residual_note": ("registered_minus_keyed_joint_pp mixes sequential-RNG coupling with "
                              "the Monte-Carlo error of BOTH estimates (the card at n=30000, this "
                              "harness at n={}). It is not decomposed further here.".format(n)),
            "scope_limit": ("LOCAL SENSITIVITY of a frozen artifact. Not evidence of prospective "
                            "accuracy; on 2026-08-21 an always-pick-home heuristic beat the "
                            "resolved-starter cohort outright."),
        })
    return out


def attribute(date, v1_card_path, v2_card_path, n=DEFAULT_N):
    """Keyed causal starter attribution for one slate. Returns a list of per-game dicts.

    REFUSES (ValueError) before doing any counterfactual work if either card fails to replay under
    the frozen global-sequential RNG, because every delta below is measured against arm (a) of a
    simulation that must be the same simulation the cards were registered from."""
    c1, c2 = json.load(open(v1_card_path)), json.load(open(v2_card_path))
    for path, c in ((v1_card_path, c1), (v2_card_path, c2)):
        if c.get("date") != date:
            raise ValueError(f"REFUSED: {path} is dated {c.get('date')!r}, not {date!r}. The keyed "
                             "seed binds the slate date and would silently key to the wrong slate.")
    # AS-OF form: a card dated D was built from results strictly BEFORE D (card_render, after the
    # STL@CIN 0.452 -> 0.456 look-ahead was caught the moment 8/17 finals landed).
    form = team_form(cr._results_before(date))
    bad = verify_transcription(c1["rows"], form) + verify_transcription(c2["rows"], form)
    if bad:
        raise ValueError("REFUSED: the sim transcription does not reproduce the registered cards, "
                         "so no counterfactual against them is meaningful:\n  " + "\n  ".join(bad[:10]))
    return attribute_rows(c1["rows"], c2["rows"], date, form, lambda hm: raw_pf(form, hm), n=n)


def summarize(rows):
    """Slate-level spread of each reported quantity. Games whose slot was untreated contribute
    NOTHING to the away/home/interaction statistics — averaging their structural zeros in would
    drag every mean toward zero and manufacture a smaller effect than was measured."""
    def col(k):
        return [r["deltas_pp"][k] for r in rows if r["deltas_pp"].get(k) is not None]
    treated_both = sum(1 for r in rows if r["away_slot"]["treated"] and r["home_slot"]["treated"])
    resid = [r["registered_minus_keyed_joint_pp"] for r in rows
             if r["registered_minus_keyed_joint_pp"] is not None]
    return {
        "games": len(rows),
        "games_both_slots_treated": treated_both,
        "games_away_slot_treated": sum(1 for r in rows if r["away_slot"]["treated"]),
        "games_home_slot_treated": sum(1 for r in rows if r["home_slot"]["treated"]),
        "away_only_pp": _dist_report(col("away_only")),
        "home_only_pp": _dist_report(col("home_only")),
        "joint_pp": _dist_report(col("joint")),
        "non_additivity_pp": _dist_report(col("non_additivity")),
        "registered_sequential_pp": _dist_report([r["registered_sequential_delta_pp"] for r in rows]),
        "registered_minus_keyed_joint_pp": _dist_report(resid),
        "denominator_note": ("every statistic names its own denominator: away/home/interaction "
                             "statistics are computed ONLY over games whose relevant slot(s) were "
                             "actually treated, so n differs between rows by design."),
    }


# --------------------------------------------------------------------------------------------
# selftest
# --------------------------------------------------------------------------------------------

# Synthetic form: (rf, ra, g, venue_of) exactly as rng_noise_study.team_form returns. Keeps every
# fixture off disk and off every registered artifact.
_FORM = ({"AAA": 41.0, "BBB": 45.0, "CCC": 39.0, "DDD": 44.0},
         {"AAA": 38.0, "BBB": 47.0, "CCC": 43.0, "DDD": 40.0},
         {"AAA": 10, "BBB": 10, "CCC": 10, "DDD": 10},
         {"BBB": "Park B", "DDD": "Park D"})
_ACE = {"era": 2.22, "gs": 19, "k": 29.8, "bb": 5.8, "ek": 6.79}
_BACK = {"era": 5.10, "gs": 14, "k": 17.2, "bb": 10.1, "ek": 3.90}
_LOW = {"era": 3.00, "gs": 1, "k": 20.0, "bb": 9.0, "ek": None}
_TINY_N = 4000
# Direction fixtures need enough draws that an ace-vs-league-average gap is not simulation noise.
_BIG_N = 60000


def _row(away, home, pk, aname, astats, hname, hstats, hwp, park=1.0):
    return {"gamePk": pk, "away": away, "home": home, "asp": aname, "hsp": hname,
            "asp_stats": dict(astats), "hsp_stats": dict(hstats), "park": park,
            "v13": {"home_wp": hwp}}


def selftest():
    fails = []
    D = "2026-08-21"

    # ---- 1. KEYED SEED ----------------------------------------------------------------------
    # exact value fixture: pins the formula itself, so any change to the hash input, the digest
    # slice or the base is caught rather than absorbed as "still deterministic"
    # The draw key now carries MODEL ID and REPLICATE INDEX as well as game and date (acceptance
    # contract 2026-08-22). Pinned exactly, so a change to the hash input, digest slice, base, model
    # identity or separator is caught rather than absorbed as "still deterministic".
    if _seed_input("A@B", D) != "KEYED|ml.v13_1.hfa1005.card|A@B|2026-08-21|rep0":
        fails.append(f"draw key string changed: {_seed_input('A@B', D)!r}")
    if _seed("A@B", D) != 2384510613:
        fails.append(f"keyed seed formula changed: _seed('A@B',{D}) = {_seed('A@B', D)}, expected 2384510613")
    if _seed("A@B", D, "OTHER_MODEL") == _seed("A@B", D):
        fails.append("two MODEL IDENTITIES received the same draw sequence — a delta measured under "
                     "one model could be read as the other's")
    if _seed("A@B", D, MODEL_ID, 1) == _seed("A@B", D, MODEL_ID, 0):
        fails.append("two REPLICATES received the same seed — the paired SE would then be 0 by "
                     "construction rather than measured")
    if "SCENARIO" in _seed_input("A@B", D).upper() or any(
            sc in _seed_input("A@B", D) for sc in ARM_SCENARIO.values()):
        fails.append("SCENARIO entered the DRAW key — that destroys common random numbers, which "
                     "the contract requires for the baseline and the counterfactual")
    if _seed("A@B", D) != _seed("A@B", D):
        fails.append("keyed seed is not deterministic for the same game+date")
    if _seed("A@B", D) == _seed("B@A", D):
        fails.append("two DIFFERENT games received the SAME seed — the coupling defect reintroduced")
    if _seed("A@B", D) == _seed("A@B", "2026-08-22"):
        fails.append("the same game on two dates received the same seed — the seed ignores the slate")
    if not (0 <= _seed("A@B", D) < 2 ** 32):
        fails.append("keyed seed is not the specified 32-bit (8 hex char) width")

    # ---- 2. COMMON RANDOM NUMBERS / paired-arm identity -------------------------------------
    s = _seed("A@B", D)
    r1 = run_arm(CAP_STATS, CAP_STATS, _FORM, "AAA", "BBB", 1.0, _TINY_N, s)
    r2 = run_arm(CAP_STATS, CAP_STATS, _FORM, "AAA", "BBB", 1.0, _TINY_N, s)
    if (r2["hw"] - r1["hw"]) * 100.0 != 0.0:
        fails.append("PAIRED-ARM IDENTITY BROKEN: two arms with identical stats and one keyed seed "
                     f"differed by {(r2['hw'] - r1['hw']) * 100:+.6f}pp — it must be exactly 0.0")
    if r1 != r2:
        fails.append("identical arms under one keyed seed differed on a non-p_home output")
    # FALSIFICATION: the fixture above only has teeth if the SEQUENTIAL discipline actually fails
    # it. This is the daily_card mechanism — one generator advanced across arms — and it must NOT
    # reproduce itself. If this ever returned identical results the identity fixture would be vacuous.
    g = np.random.default_rng(s)
    q1 = cr.sim_full(CAP_STATS, CAP_STATS, _FORM, "AAA", "BBB", 1.0, _TINY_N, g)
    q2 = cr.sim_full(CAP_STATS, CAP_STATS, _FORM, "AAA", "BBB", 1.0, _TINY_N, g)
    if q1 == q2:
        fails.append("falsification arm is vacuous: a SHARED sequential generator reproduced "
                     "identical arms, so the paired-arm identity fixture proves nothing")
    # and a real treatment must actually move the number
    rt = run_arm(_ACE, CAP_STATS, _FORM, "AAA", "BBB", 1.0, _TINY_N, s)
    if (rt["hw"] - r1["hw"]) * 100.0 == 0.0:
        fails.append("a real starter produced an exactly-zero delta — the harness cannot detect a "
                     "treatment at all")

    # ---- 3. ARM CONSTRUCTION -----------------------------------------------------------------
    arms = _arms(_ACE, _BACK)
    if len(arms) != 4:
        fails.append(f"expected 4 arms, got {len(arms)}")
    else:
        want = ((CAP_STATS, CAP_STATS), (_ACE, CAP_STATS), (CAP_STATS, _BACK), (_ACE, _BACK))
        for k, got, exp in zip(ARM_KEYS, arms, want):
            if got[0] != exp[0] or got[1] != exp[1]:
                fails.append(f"arm {k} built wrong: away={got[0]} home={got[1]} (b/c transposed?)")
    if arms[1][1] != CAP_STATS or arms[2][0] != CAP_STATS:
        fails.append("arm b must hold the AWAY starter with home CAP and arm c the reverse")

    # ---- 4. CAP PREDICATE --------------------------------------------------------------------
    if not _is_cap(CAP_STATS):
        fails.append("the CAP stat vector was not recognised as CAP")
    if not _is_cap({"era": 4.2, "gs": 0, "k": 22.0, "bb": 8.5, "ek": 3.3}):
        fails.append("a CAP slot was rejected over 'ek', which sim() never reads")
    if _is_cap(_LOW):
        fails.append("a LOW_SAMPLE starter (gs=1, real stats) was treated as CAP — the Brad Lord "
                     "conflation the owner caught on 8/21")
    if _is_cap(_ACE):
        fails.append("a resolved starter was treated as CAP")
    if _slot_class("TBD", CAP_STATS) != "CAP_TBD" or _slot_class("H. Wesneski", CAP_STATS) != "CAP_REGISTRY_MISS":
        fails.append("slot classes conflate TBD with REGISTRY_MISS")
    if _slot_class("B. Lord", _LOW) != "LOW_SAMPLE" or _slot_class("C. Sale", _ACE) != "RESOLVED":
        fails.append("slot classes conflate LOW_SAMPLE with RESOLVED")

    # ---- 5. NON-ADDITIVITY ARITHMETIC --------------------------------------------------------
    d = _deltas(0.500, 0.530, 0.470, 0.505)
    for k, exp in (("away_only", 3.0), ("home_only", -3.0), ("joint", 0.5)):
        if abs(d[k] - exp) > 1e-9:
            fails.append(f"{k} arithmetic wrong: {d[k]} vs {exp}")
    if abs(d["non_additivity"] - 0.5) > 1e-9:
        fails.append(f"non-additivity wrong: {d['non_additivity']} vs 0.5 "
                     "(joint - (away_only + home_only))")
    add = _deltas(0.500, 0.520, 0.530, 0.550)  # perfectly additive: +2 and +3 give +5
    if abs(add["non_additivity"]) > 1e-9:
        fails.append(f"a perfectly additive case reported interaction {add['non_additivity']}")
    sub = _deltas(0.500, 0.540, 0.560, 0.580)  # +4 and +6 give +8, not +10
    if abs(sub["non_additivity"] + 2.0) > 1e-9:
        fails.append(f"sub-additive case wrong: {sub['non_additivity']} vs -2.0")

    # ---- 6. THE REFUSAL ----------------------------------------------------------------------
    for bad_label in ("starter effect +3.19pp", "STARTER EFFECT +8.10 points",
                      "the starter  effect was +3.2 points", "Starter Effect"):
        try:
            assert_not_causal(bad_label)
            fails.append(f"assert_not_causal ACCEPTED a causal label: {bad_label!r}")
        except ValueError:
            pass
    for ok_label in ("keyed-seed reference starter effect +7.49 points",
                     "KEYED starter effect +7.49 points",
                     "observed change +8.10 points versus the all-league-average version",
                     "", None):
        try:
            assert_not_causal(ok_label)
        except ValueError:
            fails.append(f"assert_not_causal REFUSED a correctly-qualified label: {ok_label!r}")
    if assert_not_causal("plain text") != "plain text":
        fails.append("assert_not_causal does not return its label for inline use")
    if "starter effect" in sequential_delta_label(3.19).lower():
        fails.append("sequential_delta_label emitted a causal 'starter effect' phrase")
    if "keyed" not in keyed_delta_label(3.28).lower():
        fails.append("keyed_delta_label does not name the keyed harness")
    # cross-check: this refusal and decision_card's render-gate check #10 must agree, or a label
    # this module blesses could still be refused downstream (or worse, the reverse)
    try:
        from decision_card import delta_display
        assert_not_causal(delta_display(8.10))
        assert_not_causal(delta_display(7.49, keyed=True))
        if "starter effect" not in delta_display(7.49, keyed=True).lower():
            fails.append("decision_card.delta_display(keyed=True) no longer emits the phrase this "
                         "module is the sole authorised source of")
    except ValueError as e:
        fails.append(f"decision_card.delta_display output was REFUSED by assert_not_causal: {e}")
    except ImportError as e:
        fails.append(f"could not cross-check against decision_card: {e}")

    # ---- 7. R1 NULLS: an untreated slot is null-with-a-reason, never 0.0 ----------------------
    v1 = [_row("AAA", "BBB", "NG01", "TBD", CAP_STATS, "TBD", CAP_STATS, 0.520)]
    v2_untreated_away = [_row("AAA", "BBB", "NG01", "TBD", CAP_STATS, "Ace", _ACE, 0.474)]
    got = attribute_rows(v1, v2_untreated_away, D, _FORM, lambda hm: 1.0, n=_TINY_N)[0]
    if got["deltas_pp"]["away_only"] is not None:
        fails.append("an UNTREATED away slot reported a numeric delta (structural 0.0 presented as "
                     "a measurement) instead of null + reason")
    if got["delta_states"]["away_only"]["state"] != STRUCTURAL_ZERO:
        fails.append(f"an untreated away slot was not classed STRUCTURAL_ZERO: "
                     f"{got['delta_states']['away_only']}")
    if "STRUCTURAL_ZERO" not in (got["deltas_null_reasons"].get("away_only") or ""):
        fails.append("an untreated away slot carried no reason code")
    if got["delta_states"]["away_only"].get("structural_value_pp") != 0.0:
        fails.append("the structural zero is not carried as a state-attached value")
    if got["deltas_pp"]["non_additivity"] is not None:
        fails.append("an interaction term was reported with only one slot treated")
    if got["deltas_pp"]["home_only"] is None or got["deltas_pp"]["joint"] is None:
        fails.append("the TREATED slot's delta and the joint delta must still be reported")
    if got["arms"]["a_both_cap"]["p_home"] != got["arms"]["b_away_real_home_cap"]["p_home"]:
        fails.append("arm b differed from arm a while the away slot was CAP in both — CRN broken")
    if got["away_slot"]["treated"] or not got["home_slot"]["treated"]:
        fails.append("treatment flags wrong for a v2 with only the home slot resolved")

    # both treated: every quantity present, and the identity holds on the reported numbers
    v2_both = [_row("AAA", "BBB", "NG01", "Back", _BACK, "Ace", _ACE, 0.474)]
    both = attribute_rows(v1, v2_both, D, _FORM, lambda hm: 1.0, n=_TINY_N)[0]
    dp = both["deltas_pp"]
    if any(dp[k] is None for k in ("away_only", "home_only", "joint", "non_additivity")):
        fails.append(f"a fully treated game left a delta null: {dp}")
    else:
        if abs(dp["non_additivity"] - (dp["joint"] - (dp["away_only"] + dp["home_only"]))) > 2e-4:
            fails.append(f"reported interaction does not satisfy its own identity: {dp}")
    if not isinstance(both["delta_se_pp"], dict):
        fails.append("no paired Monte-Carlo uncertainty was reported — the contract requires it")
    elif any(both["delta_se_pp"].get(k) is None for k in ("away_only", "home_only", "joint")):
        fails.append(f"a paired SE is missing: {both['delta_se_pp']}")
    elif any(both["delta_se_pp"][k] <= 0 for k in ("away_only", "home_only", "joint")):
        fails.append(f"a paired SE is non-positive — replicates that never differ would give 0 by "
                     f"construction: {both['delta_se_pp']}")
    single = attribute_rows(v1, v2_both, D, _FORM, lambda hm: 1.0, n=_TINY_N, reps=1)[0]
    if single["delta_se_pp"].get("joint") is not None:
        fails.append("a SE was asserted from ONE replicate — a single observation has no spread, "
                     "and 0.0 there would read as a perfectly precise estimate")
    if both["registered_sequential_delta_pp"] is None:
        fails.append("the registered sequential delta was not carried alongside the keyed one")
    if abs(both["registered_sequential_delta_pp"] - (0.474 - 0.520) * 100) > 1e-6:
        fails.append("registered sequential delta miscomputed from the stored card fields")
    if both["registered_minus_keyed_joint_pp"] is None:
        fails.append("v1 was both-CAP, so registered-minus-keyed should have been differenced")
    if not both["v1_basis_is_both_cap"]:
        fails.append("an all-CAP v1 card was not recognised as arm (a)'s basis")
    # v1 NOT both-CAP: the registered delta is a different contrast and must not be differenced
    v1_real = [_row("AAA", "BBB", "NG01", "Old", _ACE, "TBD", CAP_STATS, 0.510)]
    nb = attribute_rows(v1_real, v2_both, D, _FORM, lambda hm: 1.0, n=_TINY_N)[0]
    if nb["registered_minus_keyed_joint_pp"] is not None:
        fails.append("registered-minus-keyed was differenced against a v1 that is not arm (a)")
    if "R1_BASIS_MISMATCH" not in (nb["registered_minus_keyed_null_reason"] or ""):
        fails.append("a non-CAP v1 basis carried no R1 reason code")
    # every emitted label survives the module's own refusal
    for r in (got, both, nb):
        assert_not_causal(r["keyed_label"])
        assert_not_causal(r["sequential_label"])
        if "starter effect" in r["sequential_label"].lower():
            fails.append("the sequential label acquired a causal phrase")

    # ---- 8. STRUCTURAL REFUSALS --------------------------------------------------------------
    def _refuses(a, b, why, n=_TINY_N):
        try:
            attribute_rows(a, b, D, _FORM, lambda hm: 1.0, n=n)
            fails.append(f"attribute_rows did NOT refuse: {why}")
        except ValueError:
            pass
    _refuses(v1, v2_both + v2_both, "row counts differ between arms")
    _refuses(v1, [_row("CCC", "BBB", "NG01", "Back", _BACK, "Ace", _ACE, 0.474)],
             "the two arms name different teams in the same slot")
    _refuses(v1, [_row("AAA", "BBB", "NG01", "Back", _BACK, "Ace", _ACE, 0.474, park=1.04)],
             "the park factor differs between arms, contaminating a starter-only contrast")
    dup1 = [_row("AAA", "BBB", "NG01", "TBD", CAP_STATS, "TBD", CAP_STATS, 0.52)] * 2
    dup2 = [_row("AAA", "BBB", "NG01", "Back", _BACK, "Ace", _ACE, 0.474)] * 2
    _refuses(dup1, dup2, "two games share one game key and therefore one keyed seed")
    _refuses(v1, v2_both, "n is not a positive integer", n=0)
    # a doubleheader with DH1/DH2 IS accepted and gets DISTINCT seeds
    dh1 = [_row("AAA", "BBB", "DH1", "TBD", CAP_STATS, "TBD", CAP_STATS, 0.52),
           _row("AAA", "BBB", "DH2", "TBD", CAP_STATS, "TBD", CAP_STATS, 0.52)]
    dh2 = [_row("AAA", "BBB", "DH1", "Back", _BACK, "Ace", _ACE, 0.474),
           _row("AAA", "BBB", "DH2", "Back", _BACK, "Ace", _ACE, 0.474)]
    dh = attribute_rows(dh1, dh2, D, _FORM, lambda hm: 1.0, n=_TINY_N)
    if dh[0]["seed"] == dh[1]["seed"]:
        fails.append("both halves of a doubleheader received the same keyed seed")

    # ---- 9. SUMMARY DENOMINATORS -------------------------------------------------------------
    s2 = summarize([got, both])
    if s2["away_only_pp"]["n"] != 1:
        fails.append(f"summary averaged an untreated slot's structural zero into away_only "
                     f"(n={s2['away_only_pp']['n']}, expected 1)")
    if s2["games_both_slots_treated"] != 1 or s2["games"] != 2:
        fails.append("summary denominators wrong")
    if s2["joint_pp"]["median_abs"] is None or s2["joint_pp"]["largest_signed"] is None:
        fails.append("summary let a mean travel alone without its median and largest value")
    if _dist_report([])["mean_abs"] is not None or "R1_EMPTY" not in _dist_report([])["reason_null"]:
        fails.append("an empty statistic was not reported as null + reason")

    # =========================================================================================
    # THE TEN MINIMUM FALSIFICATION FIXTURES (owner acceptance contract 2026-08-22).
    # Numbered exactly as the owner stated them. Each is paired with a mutant in MUTANTS below,
    # and `--mutants` requires this selftest to FAIL for every one.
    # =========================================================================================
    _CT = dict(CAP_STATS)
    _v1cap = [_row("AAA", "BBB", "NG01", "TBD", _CT, "TBD", _CT, 0.520)]

    # (1) IDENTICAL INPUTS PRODUCE STRUCTURAL_ZERO — never a measurement.
    ident = attribute_rows(_v1cap, [_row("AAA", "BBB", "NG01", "TBD", _CT, "TBD", _CT, 0.520)],
                           D, _FORM, lambda hm: 1.0, n=_TINY_N)[0]
    for q in ("away_only", "home_only", "joint"):
        st = ident["delta_states"][q]
        if st["state"] != STRUCTURAL_ZERO:
            fails.append(f"(1) identical inputs did not produce STRUCTURAL_ZERO on {q}: {st}")
        if st["value_pp"] is not None:
            fails.append(f"(1) a structural zero was reported as a measured value on {q}: {st}")
        if st.get("structural_value_pp") != 0.0:
            fails.append(f"(1) the structural zero lost its attached 0.0 on {q}: {st}")
    if ident["arms"]["a_both_cap"]["p_home"] != ident["arms"]["d_both_real"]["p_home"]:
        fails.append("(1) identical arms did not reproduce each other — CRN is broken")

    # (2) MISSING STARTER PRODUCES NOT_MEASURABLE, NEVER 0.0.
    miss = attribute_rows(_v1cap, [_row("AAA", "BBB", "NG01", "Back", _BACK, "TBD", _CT, 0.474)],
                          D, _FORM, lambda hm: 1.0, n=_TINY_N)[0]
    na = miss["delta_states"]["non_additivity"]
    if na["state"] != NOT_MEASURABLE:
        fails.append(f"(2) an interaction with one slot missing was not NOT_MEASURABLE: {na}")
    if na["value_pp"] is not None or not na["reason"]:
        fails.append(f"(2) NOT_MEASURABLE carried a value or no reason: {na}")
    if miss["delta_states"]["home_only"]["state"] != STRUCTURAL_ZERO:
        fails.append("(2) the missing HOME slot was not classed a structural zero")
    if miss["deltas_pp"]["home_only"] == 0.0:
        fails.append("(2) a missing starter produced a NUMERIC 0.0 — the exact defect the three "
                     "states exist to prevent")

    # (3) IMPROVING THE HOME STARTER MOVES HOME PROBABILITY IN THE EXPECTED DIRECTION.
    good = attribute_rows(_v1cap, [_row("AAA", "BBB", "NG01", "TBD", _CT, "Ace", _ACE, 0.474)],
                          D, _FORM, lambda hm: 1.0, n=_BIG_N)[0]
    bad_ = attribute_rows(_v1cap, [_row("AAA", "BBB", "NG01", "TBD", _CT, "Back", _BACK, 0.474)],
                          D, _FORM, lambda hm: 1.0, n=_BIG_N)[0]
    gh, bh = good["deltas_pp"]["home_only"], bad_["deltas_pp"]["home_only"]
    if gh is None or bh is None:
        fails.append("(3) a treated home slot produced no measured delta")
    elif not (gh > 0 and gh > bh):
        fails.append(f"(3) an ACE home starter did not raise the home win probability relative to "
                     f"league average, or did not beat a BACK-END starter: ace {gh:+.4f}pp vs "
                     f"back {bh:+.4f}pp")

    # (4) IMPROVING THE AWAY STARTER MOVES IT OPPOSITELY.
    gaway = attribute_rows(_v1cap, [_row("AAA", "BBB", "NG01", "Ace", _ACE, "TBD", _CT, 0.474)],
                           D, _FORM, lambda hm: 1.0, n=_BIG_N)[0]
    baway = attribute_rows(_v1cap, [_row("AAA", "BBB", "NG01", "Back", _BACK, "TBD", _CT, 0.474)],
                           D, _FORM, lambda hm: 1.0, n=_BIG_N)[0]
    ga, ba = gaway["deltas_pp"]["away_only"], baway["deltas_pp"]["away_only"]
    if ga is None or ba is None:
        fails.append("(4) a treated away slot produced no measured delta")
    elif not (ga < 0 and ga < ba):
        fails.append(f"(4) an ACE AWAY starter did not LOWER the home win probability: "
                     f"ace {ga:+.4f}pp vs back {ba:+.4f}pp")
    elif not (ga < 0 < gh):
        fails.append(f"(4) the away and home effects of the same ace are not OPPOSITE in sign: "
                     f"away {ga:+.4f}pp, home {gh:+.4f}pp")

    # (5) REORDERING GAMES AND SCENARIOS CHANGES NOTHING.
    g1 = _row("AAA", "BBB", "NG01", "Back", _BACK, "Ace", _ACE, 0.474)
    g2 = _row("CCC", "DDD", "NG02", "Ace", _ACE, "Back", _BACK, 0.512)
    c1 = _row("AAA", "BBB", "NG01", "TBD", _CT, "TBD", _CT, 0.520)
    c2 = _row("CCC", "DDD", "NG02", "TBD", _CT, "TBD", _CT, 0.500)
    fwd = attribute_rows([c1, c2], [g1, g2], D, _FORM, lambda hm: 1.0, n=_TINY_N)
    rev = attribute_rows([c2, c1], [g2, g1], D, _FORM, lambda hm: 1.0, n=_TINY_N)
    fwd_by = {r["game"]: r["deltas_pp"] for r in fwd}
    rev_by = {r["game"]: r["deltas_pp"] for r in rev}
    if fwd_by != rev_by:
        fails.append(f"(5) reordering the SLATE changed the deltas — position leaked into the "
                     f"draws: {fwd_by} vs {rev_by}")
    perm = attribute_rows([c1, c2], [g1, g2], D, _FORM, lambda hm: 1.0, n=_TINY_N,
                          arm_order=("d_both_real", "a_both_cap", "c_away_cap_home_real",
                                     "b_away_real_home_cap"))
    if {r["game"]: r["deltas_pp"] for r in perm} != fwd_by:
        fails.append("(5) reordering the SCENARIOS changed the deltas — arms are being addressed "
                     "by position, so the draws depend on evaluation order")
    if [r["draw_binding_sha256"] for r in perm] != [r["draw_binding_sha256"] for r in fwd]:
        fails.append("(5) scenario order changed the draw binding")
    # arms must be addressed by CANONICAL name: a permuted order that re-labels the arms would
    # report the home-only contrast under the away-only field.
    if perm[0]["arms"]["b_away_real_home_cap"]["away_stats"] != fwd[0]["arms"]["b_away_real_home_cap"]["away_stats"]:
        fails.append("(5) a permuted arm_order re-assigned stat vectors to the wrong scenarios")
    for bad_order in (("a_both_cap", "a_both_cap", "c_away_cap_home_real", "d_both_real"),
                      ("a_both_cap", "b_away_real_home_cap"),
                      ("a_both_cap", "b_away_real_home_cap", "c_away_cap_home_real", "nonsense")):
        try:
            attribute_rows([c1], [g1], D, _FORM, lambda hm: 1.0, n=_TINY_N, arm_order=bad_order)
            fails.append(f"(5) an arm_order that is not a permutation was accepted: {bad_order}")
        except ValueError:
            pass

    # (6) REMOVING COMMON RANDOM NUMBERS FAILS. Two identical arms under ONE key must be bit-equal;
    #     the shared-sequential mechanism this module replaces must NOT reproduce itself, or the
    #     equality above would prove nothing.
    _s = _seed("A@B", D)
    q1 = run_arm(dict(_CT), dict(_CT), _FORM, "AAA", "BBB", 1.0, _TINY_N, _s)
    q2 = run_arm(dict(_CT), dict(_CT), _FORM, "AAA", "BBB", 1.0, _TINY_N, _s)
    if q1["hw"] != q2["hw"]:
        fails.append("(6) two identical arms under one keyed seed did not agree exactly — common "
                     "random numbers are not in force")
    shared = np.random.default_rng(_s)
    z1 = cr.sim_full(dict(_CT), dict(_CT), _FORM, "AAA", "BBB", 1.0, _TINY_N, shared)
    z2 = cr.sim_full(dict(_CT), dict(_CT), _FORM, "AAA", "BBB", 1.0, _TINY_N, shared)
    if z1["hw"] == z2["hw"]:
        fails.append("(6) the SHARED-generator mechanism reproduced itself, so the CRN fixture "
                     "above cannot distinguish paired draws from unpaired ones and proves nothing")

    # (7) REVERSING THE DELTA SIGN FAILS. Pinned as an arithmetic identity on the arms themselves,
    #     independently of fixtures 3 and 4, so a sign flip cannot hide behind a direction test.
    ap = both["arms"]["a_both_cap"]["p_home"]
    bp = both["arms"]["b_away_real_home_cap"]["p_home"]
    cp = both["arms"]["c_away_cap_home_real"]["p_home"]
    dpp = both["arms"]["d_both_real"]["p_home"]
    for q, want in (("away_only", (bp - ap) * 100), ("home_only", (cp - ap) * 100),
                    ("joint", (dpp - ap) * 100)):
        if abs(both["deltas_pp"][q] - want) > 2e-3:
            fails.append(f"(7) {q} is not (arm - control): reported {both['deltas_pp'][q]} vs "
                         f"{want:.4f} — a reversed sign would report the counterfactual as the base")

    # (8) ACCIDENTALLY CHANGING BOTH STARTERS IN A ONE-STARTER SCENARIO FAILS.
    try:
        _assert_one_slot_changed(((dict(_CT), dict(_CT)), (dict(_ACE), dict(_ACE)),
                                  (dict(_CT), dict(_ACE)), (dict(_ACE), dict(_ACE))))
        fails.append("(8) a one-starter arm that moved BOTH slots was accepted — its number would "
                     "be reported as the effect of a single starter")
    except ValueError as exc:
        if "AWAY" not in str(exc) and "HOME" not in str(exc):
            fails.append(f"(8) the two-slot refusal names no slot: {exc}")
    try:
        _assert_one_slot_changed(((dict(_CT), dict(_CT)), (dict(_ACE), dict(_CT)),
                                  (dict(_ACE), dict(_ACE)), (dict(_ACE), dict(_ACE))))
        fails.append("(8) a HOME-only arm that also moved the away slot was accepted")
    except ValueError:
        pass
    if _assert_one_slot_changed(_arms(dict(_ACE), dict(_BACK))) is not True:
        fails.append("(8) the correctly-built arms were refused")
    # ... and attribute_rows must actually CALL it. Proven by injecting a builder that produces a
    # one-starter arm which moves both slots; without the call the run would return a number.
    def _bad_builder(a, h):
        return ((dict(_CT), dict(_CT)), (dict(a), dict(h)),   # arm b illegally moves BOTH slots
                (dict(_CT), dict(h)), (dict(a), dict(h)))
    try:
        attribute_rows(_v1cap, [_row("AAA", "BBB", "NG01", "Back", _BACK, "Ace", _ACE, 0.474)],
                       D, _FORM, lambda hm: 1.0, n=_TINY_N, arms_builder=_bad_builder)
        fails.append("(8) attribute_rows produced a delta from arms where the AWAY-ONLY scenario "
                     "moved both slots — the assertion exists but is never called")
    except ValueError as exc:
        if "REFUSED" not in str(exc):
            fails.append(f"(8) the in-loop refusal is not the one-slot assertion: {exc}")

    # (9) DROPPING THE INTERACTION FIELD FAILS.
    for q in ("away_only", "home_only", "joint", "non_additivity"):
        if q not in both["delta_states"] or q not in both["deltas_pp"]:
            fails.append(f"(9) {q} is absent from the record — the interaction must be reported "
                         f"SEPARATELY because joint movement need not equal the sum")
    if both["delta_states"]["non_additivity"]["state"] != MEASURED:
        fails.append("(9) a fully treated game did not MEASURE the interaction")
    if both["deltas_pp"]["non_additivity"] is None:
        fails.append("(9) the interaction field is null on a fully treated game")
    add = both["deltas_pp"]["away_only"] + both["deltas_pp"]["home_only"]
    if abs(both["deltas_pp"]["joint"] - add) < 1e-12 and both["deltas_pp"]["non_additivity"] != 0.0:
        fails.append("(9) the interaction contradicts its own components")

    # (10) REMOVING THE ARRAY/SEED BINDING FAILS.
    if not both.get("draw_binding_sha256"):
        fails.append("(10) the record carries no draw binding — its numbers float free of the "
                     "arrays that produced them")
    b_ref = _arm_binding(MODEL_ID, "AAA@BBB", D, 0, _TINY_N, _seed("AAA@BBB", D),
                         _arms(_BACK, _ACE))
    if both["draw_binding_sha256"] != b_ref:
        fails.append("(10) the stored binding does not recompute from its stated inputs")
    # The binding must be SENSITIVE to each input it claims to cover — proven against LITERAL
    # digests, because comparing the module's output to the module's own recomputation moves with
    # any mutation and can never detect one.
    _pin = _arm_binding("M", "A@B", "2026-08-21", 0, 1000, 12345,
                        ((dict(_CT), dict(_CT)), (dict(_ACE), dict(_CT)),
                         (dict(_CT), dict(_ACE)), (dict(_ACE), dict(_ACE))))
    _variants = {
        "model id": _arm_binding("OTHER", "A@B", "2026-08-21", 0, 1000, 12345,
                                 ((dict(_CT), dict(_CT)), (dict(_ACE), dict(_CT)),
                                  (dict(_CT), dict(_ACE)), (dict(_ACE), dict(_ACE)))),
        "game": _arm_binding("M", "X@Y", "2026-08-21", 0, 1000, 12345,
                             ((dict(_CT), dict(_CT)), (dict(_ACE), dict(_CT)),
                              (dict(_CT), dict(_ACE)), (dict(_ACE), dict(_ACE)))),
        "date": _arm_binding("M", "A@B", "2026-08-22", 0, 1000, 12345,
                             ((dict(_CT), dict(_CT)), (dict(_ACE), dict(_CT)),
                              (dict(_CT), dict(_ACE)), (dict(_ACE), dict(_ACE)))),
        "rep": _arm_binding("M", "A@B", "2026-08-21", 1, 1000, 12345,
                            ((dict(_CT), dict(_CT)), (dict(_ACE), dict(_CT)),
                             (dict(_CT), dict(_ACE)), (dict(_ACE), dict(_ACE)))),
        "n": _arm_binding("M", "A@B", "2026-08-21", 0, 1001, 12345,
                          ((dict(_CT), dict(_CT)), (dict(_ACE), dict(_CT)),
                           (dict(_CT), dict(_ACE)), (dict(_ACE), dict(_ACE)))),
        "seed": _arm_binding("M", "A@B", "2026-08-21", 0, 1000, 12346,
                             ((dict(_CT), dict(_CT)), (dict(_ACE), dict(_CT)),
                              (dict(_CT), dict(_ACE)), (dict(_ACE), dict(_ACE)))),
        "arm stat vectors": _arm_binding("M", "A@B", "2026-08-21", 0, 1000, 12345,
                                         ((dict(_CT), dict(_CT)), (dict(_BACK), dict(_CT)),
                                          (dict(_CT), dict(_ACE)), (dict(_BACK), dict(_ACE)))),
    }
    for label, v in _variants.items():
        if v == _pin:
            fails.append(f"(10) changing the {label} did not change the draw binding — the binding "
                         f"does not cover the thing it claims to")
    if len(set(_variants.values()) | {_pin}) != len(_variants) + 1:
        fails.append("(10) two different draw configurations collided to the same binding")
    for label, changed in (
            ("n", _arm_binding(MODEL_ID, "AAA@BBB", D, 0, _TINY_N + 1, _seed("AAA@BBB", D),
                               _arms(_BACK, _ACE))),
            ("model id", _arm_binding("OTHER", "AAA@BBB", D, 0, _TINY_N, _seed("AAA@BBB", D),
                                      _arms(_BACK, _ACE))),
            ("seed", _arm_binding(MODEL_ID, "AAA@BBB", D, 0, _TINY_N, 999, _arms(_BACK, _ACE))),
            ("game", _arm_binding(MODEL_ID, "XXX@YYY", D, 0, _TINY_N, _seed("AAA@BBB", D),
                                  _arms(_BACK, _ACE))),
            ("date", _arm_binding(MODEL_ID, "AAA@BBB", "2026-08-22", 0, _TINY_N,
                                  _seed("AAA@BBB", D), _arms(_BACK, _ACE))),
            ("arm stats", _arm_binding(MODEL_ID, "AAA@BBB", D, 0, _TINY_N, _seed("AAA@BBB", D),
                                       _arms(_ACE, _ACE)))):
        if changed == b_ref:
            fails.append(f"(10) changing the {label} did not change the draw binding — the binding "
                         f"does not cover the thing it claims to")

    # SELFTEST STRUCTURE — proved, not assumed. The ten fixtures above were briefly DEAD CODE:
    # an early `if fails: return 1` sat above them, so their failures were collected and then
    # discarded and every mutant they guard survived. A selftest that cannot report its own last
    # fixture is decoration in the purest form (lesson 21), so the structure is now asserted.
    # Markers are CONCATENATED at runtime so this check does not match its own source text.
    _src = open(os.path.abspath(__file__)).read()
    _vm = 'print("starter_attribution selftest: ' + 'FAIL")'
    _fm = 'fails.append(f"(10) changing ' + 'the'
    if _src.count(_vm) != 1:
        fails.append(f"{_src.count(_vm)} FAIL verdicts in the selftest — an early return silently "
                     f"orphans every fixture below it, which is exactly what happened on 2026-08-22")
    elif _src.rindex(_fm) > _src.rindex(_vm):
        fails.append("SELFTEST STRUCTURE BROKEN — the last fixture appends failures BELOW the "
                     "verdict, so its result can never be reported")

    if fails:
        print("starter_attribution selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("starter_attribution selftest: PASS (keyed seed pinned to its exact formula and distinct "
          "per game and per date; two identical arms under one keyed seed differ by exactly 0.0 "
          "while the shared sequential generator they replace does NOT reproduce itself; arms b/c "
          "hold the away/home starter against a CAP partner; non-additivity satisfies "
          "joint-(away+home) on additive, super- and sub-additive fixtures; assert_not_causal "
          "refuses 'starter effect' without 'keyed' and agrees with decision_card check #10; an "
          "untreated slot is null+R1 reason, never a structural 0.0; mismatched rows, parks, "
          "duplicate game keys and n<1 are REFUSED)")
    return 0


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------

# ----------------------------------------------------------------------- mutation harness
# LESSON 21 + owner acceptance contract: the ten falsification fixtures are only worth their name
# if each KILLS the mutant it exists to catch. `--mutants` applies each source edit to a temp copy
# and REQUIRES that copy's selftest to fail. A survivor means the fixture is decoration and the
# quarantine stays regardless.
MUTANTS = [
    # (1) identical inputs must be STRUCTURAL_ZERO, never a measurement
    ("(1) structural zero rendered as a measured value",
     "    if arms_identical:", "    if False:"),
    ("(1) structural zero carries a numeric value_pp",
     '        return {"state": STRUCTURAL_ZERO, "value_pp": None, "structural_value_pp": 0.0,',
     '        return {"state": STRUCTURAL_ZERO, "value_pp": 0.0, "structural_value_pp": 0.0,'),
    ("(1) the attached structural 0.0 dropped",
     '"structural_value_pp": 0.0,', '"structural_value_pp": None,'),
    # (2) missing starter -> NOT_MEASURABLE, never 0.0
    ("(2) NOT_MEASURABLE state removed", "    if not measurable:", "    if False:"),
    ("(2) NOT_MEASURABLE returns 0.0 instead of null",
     '        return {"state": NOT_MEASURABLE, "value_pp": None,',
     '        return {"state": NOT_MEASURABLE, "value_pp": 0.0,'),
    ("(2) interaction measurable with only one slot treated",
     "                measurable=(away_treated and home_treated),", "                measurable=True,"),
    # (3)/(4) direction
    ("(3/4) home-only and away-only arms transposed",
     "            (dict(away_real), dict(CAP_STATS)),\n            (dict(CAP_STATS), dict(home_real)),",
     "            (dict(CAP_STATS), dict(home_real)),\n            (dict(away_real), dict(CAP_STATS)),"),
    ("(3/4) away and home deltas transposed",
     '    away = (p_b - p_a) * 100.0\n    home = (p_c - p_a) * 100.0',
     '    away = (p_c - p_a) * 100.0\n    home = (p_b - p_a) * 100.0'),
    # (5) order invariance
    ("(5) arms re-labelled by the caller's order instead of canonical names",
     "        arm_of = dict(zip(ARM_KEYS, arms))   # CANONICAL names, never the caller's order",
     "        arm_of = dict(zip(order, arms))"),
    ("(5) slate position enters the draw key",
     '    return f"KEYED|{model_id}|{game}|{date}|rep{rep}"',
     '    return f"KEYED|{model_id}|{game}|{date}|rep{rep}|{len(game)}"'),
    ("(5) arm_order permutation not validated",
     "        if sorted(order) != sorted(ARM_KEYS):", "        if False:"),
    # (6) common random numbers
    ("(6) CRN removed — each arm gets its own generator",
     "    return cr.sim_full(asp, hsp, form, aw, hm, pf, n, np.random.default_rng(seed))",
     "    return cr.sim_full(asp, hsp, form, aw, hm, pf, n, np.random.default_rng())"),
    ("(6) scenario enters the draw key, destroying pairing",
     "                sim = run_arm(asp, hsp, form, aw, hm, pf, n, rseed)",
     "                sim = run_arm(asp, hsp, form, aw, hm, pf, n, rseed + hash(arm_key) % 97)"),
    ("(6) replicate index dropped from the seed, so every replicate is identical",
     "def _seed(game, date, model_id=MODEL_ID, rep=0):\n    \"\"\"32 bits",
     "def _seed(game, date, model_id=MODEL_ID, rep=0):\n    rep = 0\n    \"\"\"32 bits"),
    ("(6) model identity dropped from the draw key",
     '    return f"KEYED|{model_id}|{game}|{date}|rep{rep}"',
     '    return f"KEYED|{game}|{date}|rep{rep}"'),
    # (7) sign
    ("(7) delta sign reversed (control minus arm)",
     '    away = (p_b - p_a) * 100.0\n    home = (p_c - p_a) * 100.0\n    joint = (p_d - p_a) * 100.0',
     '    away = (p_a - p_b) * 100.0\n    home = (p_a - p_c) * 100.0\n    joint = (p_a - p_d) * 100.0'),
    # (8) one-slot scenarios
    ("(8) the one-slot-changed assertion never called",
     "        _assert_one_slot_changed(arms)", "        pass  # assertion removed"),
    ("(8) the assertion never raises", '        raise ValueError("REFUSED: " + "; ".join(bad))',
     '        pass'),
    ("(8) only the away slot is checked for illegal movement",
     '        if home_moved and "home" not in may:', "        if False:"),
    # (9) interaction
    ("(9) interaction dropped from the reported quantities",
     '            "non_additivity": classify(', '            "_dropped_non_additivity": classify('),
    ("(9) interaction reported as the sum instead of the residual",
     '    return {"away_only": away, "home_only": home, "joint": joint,\n            "non_additivity": joint - (away + home)}',
     '    return {"away_only": away, "home_only": home, "joint": joint,\n            "non_additivity": away + home}'),
    # (10) binding
    ("(10) draw binding removed from the record",
     '            "draw_binding_sha256": binding,', '            "draw_binding_sha256": None,'),
    ("(10) binding ignores n", '        "model_id": model_id, "game": game, "date": date, "rep": rep, "n": n, "seed": seed,',
     '        "model_id": model_id, "game": game, "date": date, "rep": rep, "seed": seed,'),
    # These two mutants must REMOVE coverage, not merely perturb the payload. An earlier pair
    # "survived" because they left the covered field reachable by another route — `_x: 0` still
    # carried the stat vectors, and dropping `model_id` left model identity inside `seed_input`.
    # A mutant that does not actually delete the rule proves as little as a decorative fixture.
    ("(10) binding ignores the per-arm stat vectors",
     '''        "arms": [{"scenario": ARM_SCENARIO[k],
                  "away": {f: a.get(f) for f in SIM_STAT_FIELDS},
                  "home": {f: h.get(f) for f in SIM_STAT_FIELDS}}
                 for k, (a, h) in zip(ARM_KEYS, arms)],''',
     '        "arms": [ARM_SCENARIO[k] for k in ARM_KEYS],'),
    ("(10) binding ignores the model identity",
     '        "model_id": model_id, "game": game, "date": date, "rep": rep, "n": n, "seed": seed,\n        "seed_input": _seed_input(game, date, model_id, rep),',
     '        "game": game, "date": date, "rep": rep, "n": n, "seed": seed,'),
    # paired uncertainty
    ("SE: single replicate asserted as 0.0 instead of null",
     "        if len(vals) < 2:\n            out[k] = None", "        if len(vals) < 2:\n            out[k] = 0.0"),
    ("SE: paired uncertainty not reported at all",
     '            "delta_se_pp": {k: _r(v) for k, v in se.items()},', '            "delta_se_pp": None,'),
    # the causal-language refusal (kept from the original suite)
    ("causal language: 'starter effect' allowed without 'keyed'",
     '    if "starter effect" in flat and "keyed" not in flat:', "    if False:"),
    ("selftest structure: a second FAIL verdict orphans the fixtures below it",
     "    if fails:\n        print(\"starter_attribution selftest: FAIL\")",
     "    if fails:\n        print(\"starter_attribution selftest: FAIL\")\n        return 1\n    if fails:\n        print(\"starter_attribution selftest: FAIL\")"),
]


def mutation_suite(verbose=True):
    import subprocess as _sp, tempfile as _tf
    src = open(os.path.abspath(__file__)).read()
    i = src.index("MUTANTS = [")
    j = src.index("\ndef mutation_suite", i)
    head, block, tail = src[:i], src[i:j], src[j:]
    survivors, unapplied = [], []
    for name, old, new in MUTANTS:
        where = "head" if old in head else ("tail" if old in tail else None)
        if where is None:
            unapplied.append(f"{name}: pattern not found in executable source")
            continue
        mutated = (head.replace(old, new, 1) + block + tail) if where == "head" \
            else (head + block + tail.replace(old, new, 1))
        if mutated == src:
            unapplied.append(f"{name}: no-op replacement")
            continue
        with _tf.NamedTemporaryFile("w", suffix="_mutant.py", delete=False,
                                    dir=os.path.dirname(os.path.abspath(__file__))) as fh:
            fh.write(mutated)
            path = fh.name
        try:
            pr = _sp.run([sys.executable, path, "--selftest"], capture_output=True, text=True,
                         timeout=1800)
            killed = pr.returncode != 0
        except _sp.TimeoutExpired:
            killed = True
        finally:
            os.unlink(path)
        if verbose:
            print(f"  {'KILLED  ' if killed else 'SURVIVED'}  {name}", flush=True)
        if not killed:
            survivors.append(name)
    for u in unapplied:
        print(f"  UNAPPLIED  {u}")
    print(f"mutation suite: {len(MUTANTS) - len(survivors) - len(unapplied)}/{len(MUTANTS)} killed"
          f"{'' if not (survivors or unapplied) else '  — SURVIVORS MEAN DECORATIVE FIXTURES'}")
    return survivors + unapplied


def _safe_out(path):
    rel = os.path.relpath(os.path.abspath(path), BASE)
    if rel.startswith(".."):
        raise SystemExit(f"REFUSED: --out {path} is outside the repository.")
    for p in REGISTERED_PREFIXES:
        if rel.startswith(p):
            raise SystemExit(f"REFUSED: --out {rel} is inside a registered-artifact directory "
                             f"({p}). This module measures registered artifacts and never writes "
                             "to them.")
    return rel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--mutants", action="store_true",
                    help="apply every mutant to a temp copy and require the selftest to FAIL for "
                         "each; a SURVIVOR means the fixture guarding that rule is decoration")
    ap.add_argument("--date", default="2026-08-21")
    ap.add_argument("--v1", default=None, help="v1 (all-league-average) card path")
    ap.add_argument("--v2", default=None, help="v2 (starters resolved) card path")
    ap.add_argument("--n", type=int, default=DEFAULT_N, help="draws per arm (default 200000)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default=None, help="optional JSON output path (never overwrites)")
    a = ap.parse_args()
    if a.mutants:
        return 1 if mutation_suite() else 0
    if a.selftest:
        return selftest()

    v1 = a.v1 or f"cards/{a.date}_card.json"
    v2 = a.v2 or f"cards/{a.date}_card_v2.json"
    rows = attribute(a.date, v1, v2, n=a.n)
    payload = {"record_id": f"KEYED-STARTER-ATTRIBUTION-{a.date}", "date": a.date,
               "v1_card": v1, "v2_card": v2, "n_per_arm": a.n,
               "estimand": ("per-game controlled counterfactual on the starter slots under a "
                            "per-game keyed seed with common random numbers across arms"),
               "summary": summarize(rows), "games": rows}
    if a.json:
        print(json.dumps(payload, indent=1))
    else:
        s = payload["summary"]
        print(f'{a.date} — {s["games"]} games — {a.n:,} draws/arm × 4 arms — keyed per-game seeds')
        print(f'  slots treated: away {s["games_away_slot_treated"]}/{s["games"]}, '
              f'home {s["games_home_slot_treated"]}/{s["games"]}, '
              f'both {s["games_both_slots_treated"]}/{s["games"]}\n')
        def f(v):
            """null is printed as null. A structural zero must never be rendered as a measurement."""
            return "     null" if v is None else f"{v:+9.4f}"
        print(f'{"game":<14}{"away-only":>11}{"home-only":>11}{"joint":>9}{"interact":>10}'
              f'{"registered":>12}{"reg-keyed":>11}  slots (v2)')
        for r in rows:
            d = r["deltas_pp"]
            print(f'{r["game"]:<14}{f(d["away_only"]):>11}{f(d["home_only"]):>11}'
                  f'{f(d["joint"]):>9}{f(d["non_additivity"]):>10}'
                  f'{r["registered_sequential_delta_pp"]:>+12.4f}'
                  f'{f(r["registered_minus_keyed_joint_pp"]):>11}  '
                  f'{r["away_slot"]["class_v2"]}/{r["home_slot"]["class_v2"]}')
        for name in ("away_only_pp", "home_only_pp", "joint_pp", "non_additivity_pp",
                     "registered_sequential_pp", "registered_minus_keyed_joint_pp"):
            b = s[name]
            print(f'\n{name}: n={b["n"]} mean|d| {b["mean_abs"]} median|d| {b["median_abs"]} '
                  f'signed mean {b["signed_mean"]} largest {b["largest_signed"]}')
        print(f'\n{s["denominator_note"]}')
        print("\nSCOPE: local sensitivity of a frozen artifact. NOT evidence of prospective "
              "accuracy. No per-delta interval exists from one replicate — see rng_noise_study.")
    if a.out:
        rel = _safe_out(a.out)
        try:
            fd = os.open(rel, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            raise SystemExit(f"REFUSED: {rel} already exists; measurement output is never overwritten.")
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh, indent=1)
        print(f"wrote {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
