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
# QUARANTINED DRAFT — NOT WIRED, NOT AUTHORITATIVE (2026-08-22)
# Built for the owner's roadmap and then adversarially reviewed. The review found critical/high
# defects and, more importantly, that many of this module's own fixtures are DECORATIVE: they stay
# green when the rule they supposedly guard is deleted. A passing selftest here therefore does not
# mean the rules hold. Findings: docs/audits/2026-08-22_roadmap_module_review.json
# This module is NOT imported by healthcheck, NOT used for any card, grade, or decision, and its
# numbers must not be quoted until the defect list is closed and the fixtures are proven killing.
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

def _seed(game, date):
    """Per-(game, date) keyed seed. NOT a function of slate position, so resolving a starter in the
    first game cannot move the draws of the ninth — the exact coupling this module exists to break.

    32 bits (8 hex chars) as specified; np.random.default_rng accepts it directly."""
    return int(hashlib.sha256(f"KEYED|{game}|{date}".encode()).hexdigest()[:8], 16)


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

def attribute_rows(v1_rows, v2_rows, date, form, pf_of, n=DEFAULT_N):
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
        seed = _seed(key, date)
        away_real, home_real = r2["asp_stats"], r2["hsp_stats"]
        away_treated, home_treated = not _is_cap(away_real), not _is_cap(home_real)

        arms, sims, p_raw = _arms(away_real, home_real), {}, []
        for arm_key, (asp, hsp) in zip(ARM_KEYS, arms):
            s = run_arm(asp, hsp, form, aw, hm, pf, n, seed)
            p_raw.append(s["hw"])
            sims[arm_key] = {"p_home": _r(s["hw"], 6), "proj_total": _r(s["tot"], 3),
                             "proj_away_runs": _r(s["proj_away"], 3),
                             "proj_home_runs": _r(s["proj_home"], 3),
                             "mc_se_pp_unpaired": _r(_mc_se_pp(s["hw"], n)),
                             "away_stats": asp, "home_stats": hsp}
        # deltas come from the UNROUNDED arm probabilities: rounding first would put a floor of
        # ~1e-4pp under an identity that is supposed to be exactly 0.0 for an untreated arm.
        d = _deltas(*p_raw)

        nulls = {}
        rep = {"away_only": d["away_only"], "home_only": d["home_only"],
               "joint": d["joint"], "non_additivity": d["non_additivity"]}
        if not away_treated:
            rep["away_only"] = None
            nulls["away_only"] = R1_NO_TREATMENT
        if not home_treated:
            rep["home_only"] = None
            nulls["home_only"] = R1_NO_TREATMENT
        if not (away_treated and home_treated):
            rep["non_additivity"] = None
            nulls["non_additivity"] = R1_NO_INTERACTION

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
            "seed_input": f"KEYED|{key}|{date}", "seed": seed,
            "n_per_arm": n, "park_factor_raw": _r(pf, 6),
            "away_slot": {"name_v1": r1.get("asp"), "name_v2": r2.get("asp"),
                          "class_v1": _slot_class(r1.get("asp"), r1["asp_stats"]),
                          "class_v2": _slot_class(r2.get("asp"), away_real),
                          "treated": away_treated},
            "home_slot": {"name_v1": r1.get("hsp"), "name_v2": r2.get("hsp"),
                          "class_v1": _slot_class(r1.get("hsp"), r1["hsp_stats"]),
                          "class_v2": _slot_class(r2.get("hsp"), home_real),
                          "treated": home_treated},
            "arms": sims,
            "deltas_pp": {k: _r(v) for k, v in rep.items()},
            "deltas_null_reasons": nulls,
            "delta_se_pp": None, "delta_se_null_reason": R1_SINGLE_REPLICATE,
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
    if _seed("A@B", D) != 3337157104:
        fails.append(f"keyed seed formula changed: _seed('A@B',{D}) = {_seed('A@B', D)}, expected 3337157104")
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
    if "R1_NO_TREATMENT" not in (got["deltas_null_reasons"].get("away_only") or ""):
        fails.append("an untreated away slot carried no R1 reason code")
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
    if both["delta_se_pp"] is not None or "R1_SINGLE_REPLICATE" not in both["delta_se_null_reason"]:
        fails.append("a per-delta SE was asserted from a single replicate")
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
    ap.add_argument("--date", default="2026-08-21")
    ap.add_argument("--v1", default=None, help="v1 (all-league-average) card path")
    ap.add_argument("--v2", default=None, help="v2 (starters resolved) card path")
    ap.add_argument("--n", type=int, default=DEFAULT_N, help="draws per arm (default 200000)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default=None, help="optional JSON output path (never overwrites)")
    a = ap.parse_args()
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
