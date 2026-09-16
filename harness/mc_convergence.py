"""Monte-Carlo convergence gate, ported from the mc_engine lineage and bound INTO the
forecastable/actionable gate (P0-MC-CONVERGENCE-2026-08-30).

WHAT THIS IS. In the mc_engine lineage (branch kimi/mc-engine-lineage,
lineage/mc_engine_20260830/harness/mc_engine.py) every simulated probability carries a
per-block convergence diagnostic: TRIALS split into BLOCKS keyed-seed batch blocks, and if
max |block p_home - pooled p_home| exceeds CONVERGENCE_SIGMAS pooled-Bernoulli block sigmas
the engine RAISES ConvergenceError and the slate builder exits 1 — fail loud, no card row.
Observed live consequences on the 8/29 slate: CONVERGENCE_FAIL on HOU@NYM (2.968pp) and
COL@ATL (2.715pp). This lineage (sportsmodel/main) separates ``forecastable`` from
``actionable`` instead: only FRESH+CONFIRMED inputs may proceed toward action; everything
else is recorded as REGISTERED_FALLBACK_ONLY and the rest of the board still builds.

THE PORT'S INTEGRATION CONTRACT (owner-approved). A CONVERGENCE_FAIL no longer kills the
slate builder. It DEMOTES the game to forecast-only — the same fail-closed disposition the
freshness contract already uses (actionable=False, input_value_policy=
REGISTERED_FALLBACK_ONLY, the offending value retained for audit) — while every other game
on the board proceeds normally. Fail-closed, but not fail-loud-process-kill.

TOLERANCE PROVENANCE (R1/R3 — ported, not invented). The source gate's per-game threshold is
    CONVERGENCE_SIGMAS * mc_se,   mc_se = sqrt(p_pool*(1-p_pool) / (TRIALS/BLOCKS))
with CONVERGENCE_SIGMAS = 3.0, TRIALS = 30000, BLOCKS = 10. mc_se is the pooled-Bernoulli
standard error OF A BLOCK PROPORTION (the source module documents why: the tighter pooled
-reading false-fires on a healthy simulation; a max over 10 honest blocks sits at ~1.5
block-sigmas by construction). The named registered constant below, MC_CONVERGENCE_TOL_PP,
is the worst-case (p_pool = 0.5) value of that threshold:
    3.0 * sqrt(0.25/3000) * 100 = 2.7386pp
The two observed source-lineage failures are consistent with the ported rule: 2.968pp
(HOU@NYM) exceeds the p=0.5 worst case; 2.715pp (COL@ATL) exceeded its per-game threshold
because p_pool < 0.5 shrinks mc_se. This module keeps the source rule per-game
(gap_pp > MC_CONVERGENCE_SIGMAS * mc_se_pp) and uses MC_CONVERGENCE_TOL_PP as the registered
reference tolerance for the two-independent-estimator check and for documentation. Argue
with the provenance, not the number.

R3 (frozen stays frozen), R6 (append-only). Nothing here rewrites a frozen card, board or
grade. The gate applies to builders going forward.
"""
from __future__ import annotations

MODULE_ID = "mc_convergence"

import json
import math
import sys

# ------------------------------------------------------------------ ported protocol constants
MC_TRIALS = 30000            # ported: mc_engine.TRIALS (30k keeps block mc_se <= ~0.29pp at p=0.5)
MC_BLOCKS = 10               # ported: mc_engine.BLOCKS (keyed-seed batch blocks)
MC_CONVERGENCE_SIGMAS = 3.0  # ported: mc_engine.CONVERGENCE_SIGMAS — fail when
                             # max |block - pooled| exceeds 3 pooled Bernoulli block sigmas
#: Registered named tolerance, percentage points. PROVENANCE: derived, not tuned — the
#: worst-case (p_pool=0.5) value of the ported per-game threshold
#: MC_CONVERGENCE_SIGMAS * sqrt(0.25/(MC_TRIALS/MC_BLOCKS)) * 100 = 2.7386pp. The source
#: lineage's observed CONVERGENCE_FAILs (2.968pp HOU@NYM, 2.715pp COL@ATL) sit at/above
#: this scale. Do not re-tune inside this module (R3); change requires a patch-registry entry.
MC_CONVERGENCE_TOL_PP = round(
    MC_CONVERGENCE_SIGMAS * math.sqrt(0.25 / (MC_TRIALS / MC_BLOCKS)) * 100.0, 4)  # 2.7386

CONVERGENCE_OK = "OK"
CONVERGENCE_FAIL = "CONVERGENCE_FAIL"

#: disposition vocabulary mirrors harness/freshness_contract.py — the gate demotes INTO the
#: existing fail-closed shape rather than inventing a new one.
REGISTERED_FALLBACK_ONLY = "REGISTERED_FALLBACK_ONLY"
CURRENT_OBSERVED_VALUE = "CURRENT_OBSERVED_VALUE"


class ConvergenceInputError(ValueError):
    """Malformed block/estimator input. Raised rather than defaulted — R1."""


# ------------------------------------------------------------------ the gate itself

def block_convergence_verdict(block_p_home, trials=MC_TRIALS, blocks=MC_BLOCKS):
    """Port of mc_engine's batch-block diagnostic. Pure; returns a verdict, never raises on
    a FAIL (the demotion decision belongs to apply_convergence_gate).

    block_p_home  per-block simulated home-win proportions, len == blocks.
    Returns {status, gap_pp, mc_se_pp, threshold_pp, p_pool, block_p_home, protocol}.
    """
    vals = [float(x) for x in block_p_home]
    if len(vals) != blocks:
        raise ConvergenceInputError(
            f"expected {blocks} block proportions, got {len(vals)} — a partial block record "
            "cannot be convergence-checked and must not be waved through")
    for v in vals:
        if not 0.0 <= v <= 1.0:
            raise ConvergenceInputError(f"block proportion out of [0,1]: {v}")
    if trials % blocks:
        raise ConvergenceInputError("trials must divide evenly into blocks")
    p_pool = sum(vals) / blocks
    # pooled-Bernoulli se OF A BLOCK PROPORTION — the source lineage's documented scale.
    mc_se = math.sqrt(p_pool * (1.0 - p_pool) / (trials / blocks))
    gap = max(abs(b - p_pool) for b in vals)
    status = CONVERGENCE_FAIL if gap > MC_CONVERGENCE_SIGMAS * mc_se else CONVERGENCE_OK
    return {"status": status,
            "gap_pp": round(gap * 100.0, 4),
            "mc_se_pp": round(mc_se * 100.0, 4),
            "threshold_pp": round(MC_CONVERGENCE_SIGMAS * mc_se * 100.0, 4),
            "registered_tol_pp": MC_CONVERGENCE_TOL_PP,
            "p_pool": round(p_pool, 6),
            "block_p_home": [round(b, 5) for b in vals],
            "protocol": {"trials": trials, "blocks": blocks,
                         "convergence_sigmas": MC_CONVERGENCE_SIGMAS,
                         "ported_from": "lineage/mc_engine_20260830/harness/mc_engine.py"}}


def estimator_verdict(p_a, p_b, tol_pp=MC_CONVERGENCE_TOL_PP):
    """Two-independent-estimator check (analytic vs simulated, or split-half MC).

    Fails when |p_a - p_b| exceeds the REGISTERED tolerance MC_CONVERGENCE_TOL_PP (the
    worst-case ported threshold, provenance above).
    """
    a, b = float(p_a), float(p_b)
    for v in (a, b):
        if not 0.0 <= v <= 1.0:
            raise ConvergenceInputError(f"estimator out of [0,1]: {v}")
    gap_pp = abs(a - b) * 100.0
    return {"status": CONVERGENCE_FAIL if gap_pp > tol_pp else CONVERGENCE_OK,
            "gap_pp": round(gap_pp, 4),
            "registered_tol_pp": tol_pp,
            "estimators": [round(a, 6), round(b, 6)]}


# ------------------------------------------------------------------ actionable-gate binding

def apply_convergence_gate(disposition, verdict, game_id=None):
    """Bind the verdict INTO the forecastable/actionable gate. Returns a NEW disposition
    dict; the input is not mutated.

    disposition  a freshness_contract.Disposition.to_dict()-shaped dict (must carry at
                 least forecastable/actionable/input_value_policy).
    FAIL path (fail-closed, not process-kill): forecastable stays True — the labelled
    research row survives — but actionable/bettable flip False, input_value_policy becomes
    REGISTERED_FALLBACK_ONLY, and a ``convergence`` audit block recording the verdict and
    the pre-demotion action state is attached. OK path: the disposition's action state is
    UNCHANGED (convergence never promotes a non-actionable input — freshness still
    governs) and the audit block records the clean verdict.
    """
    if disposition is None:
        raise ConvergenceInputError("no disposition supplied — the gate binds into the "
                                    "freshness disposition, it does not replace it")
    out = dict(disposition)
    prior_actionable = bool(out.get("actionable"))
    prior_policy = out.get("input_value_policy")
    if verdict["status"] == CONVERGENCE_FAIL:
        out["forecastable"] = True                # the labelled forecast row survives
        out["actionable"] = False
        out["bettable"] = False
        out["input_value_policy"] = REGISTERED_FALLBACK_ONLY
        out["convergence"] = {
            "gate": MODULE_ID,
            "status": CONVERGENCE_FAIL,
            "verdict": verdict,
            "demotion": ("MC batch blocks disagree beyond "
                         f"{verdict.get('threshold_pp', verdict.get('registered_tol_pp'))}pp — "
                         "the simulator is measuring its own RNG, not the game. Demoted to "
                         "forecast-only; the rest of the board still builds."),
            "pre_demotion_actionable": prior_actionable,
            "pre_demotion_value_policy": prior_policy,
            "game_id": game_id,
        }
    else:
        out["convergence"] = {"gate": MODULE_ID, "status": CONVERGENCE_OK,
                              "verdict": verdict, "game_id": game_id}
    return out


def run_slate(games, trials=MC_TRIALS, blocks=MC_BLOCKS):
    """Reference slate assembly with the gate bound in. NEVER exits 1 on a convergence
    failure — that is the behavioural change this port exists to make.

    games  iterable of {game_id, disposition, block_p_home?, estimators?}. Each game must
           carry per-block proportions OR a two-estimator pair (p_a, p_b); a game with
           neither is an input error (R1), not a pass.
    Returns {rows, convergence_failures, n_games}. Every game produces exactly one row.
    """
    rows, failures = [], []
    for g in games:
        gid = g["game_id"]
        if g.get("block_p_home") is not None:
            verdict = block_convergence_verdict(g["block_p_home"], trials=trials,
                                                blocks=blocks)
        elif g.get("estimators") is not None:
            verdict = estimator_verdict(*g["estimators"])
        else:
            raise ConvergenceInputError(
                f"{gid}: no block_p_home and no estimators — a simulated number with no "
                "convergence evidence cannot be gated and must not skip the gate")
        disp = apply_convergence_gate(g["disposition"], verdict, game_id=gid)
        rows.append({"game": gid, "disposition": disp})
        if verdict["status"] == CONVERGENCE_FAIL:
            failures.append(f"CONVERGENCE_FAIL {gid}: gap {verdict['gap_pp']:.3f}pp — "
                            "demoted to REGISTERED_FALLBACK_ONLY (forecast-only)")
    return {"rows": rows, "convergence_failures": failures, "n_games": len(rows)}


# ====================================================================== selftest

def _actionable_disposition():
    """A FRESH+CONFIRMED freshness disposition, the only state that may reach action."""
    return {"subject": "test", "disposition": "FRESH", "grade": "CONFIRMED",
            "dose_multiplier": 1.0, "forecastable": True, "actionable": True,
            "bettable": True, "input_value_policy": CURRENT_OBSERVED_VALUE,
            "reason": "test fixture"}


def _blocks(p, wobble=0.001):
    """An honest simulation: blocks scattered well inside tolerance around p."""
    return [p + (wobble if i % 2 else -wobble) for i in range(MC_BLOCKS)]


def _rigged_blocks(p):
    """A simulator measuring its own RNG: one block departs by ~4.5pp."""
    return [p] * (MC_BLOCKS - 1) + [p + 0.05]


def selftest():
    f = []

    # C1 — the ported tolerance constant is the derived value, not a new one.
    expect = round(3.0 * math.sqrt(0.25 / 3000.0) * 100.0, 4)
    if MC_CONVERGENCE_TOL_PP != expect or MC_CONVERGENCE_TOL_PP != 2.7386:
        f.append(f"C1: MC_CONVERGENCE_TOL_PP={MC_CONVERGENCE_TOL_PP}, expected {expect}")

    # C2 — an honest simulation passes and the actionable path is UNCHANGED.
    v = block_convergence_verdict(_blocks(0.55))
    if v["status"] != CONVERGENCE_OK:
        f.append(f"C2: honest blocks failed convergence: {v}")
    d = apply_convergence_gate(_actionable_disposition(), v, game_id="OK@HOME")
    if not (d["actionable"] and d["input_value_policy"] == CURRENT_OBSERVED_VALUE):
        f.append("C2: a passing verdict altered the actionable path")
    if d.get("convergence", {}).get("status") != CONVERGENCE_OK:
        f.append("C2: the clean verdict was not recorded for audit")

    # C3 — a rigged simulation FAILS and DEMOTES: forecast-only, fallback policy, audit kept.
    v3 = block_convergence_verdict(_rigged_blocks(0.55))
    if v3["status"] != CONVERGENCE_FAIL:
        f.append(f"C3: rigged blocks did not trip the gate: {v3}")
    d3 = apply_convergence_gate(_actionable_disposition(), v3, game_id="BAD@HOME")
    if not d3["forecastable"]:
        f.append("C3: demotion erased the forecast row instead of keeping it forecast-only")
    if d3["actionable"] or d3["bettable"]:
        f.append("C3: a convergence failure remained action eligible")
    if d3["input_value_policy"] != REGISTERED_FALLBACK_ONLY:
        f.append("C3: the demoted row did not record REGISTERED_FALLBACK_ONLY")
    if d3["convergence"]["pre_demotion_actionable"] is not True:
        f.append("C3: the audit did not retain the pre-demotion action state")

    # C4 — the source lineage's observed failure points still fail under the ported rule.
    # HOU@NYM 2.968pp: with 9 equal blocks and one departing block the pooled gap is
    # 0.9 * departure, so a departure of 0.02968/0.9 reproduces the observed 2.968pp gap
    # (p_pool ~= 0.503, per-game threshold 3*mc_se ~= 2.739pp — the gap clears it).
    blocks_hou = [0.5] * (MC_BLOCKS - 1) + [0.5 + 0.02968 / 0.9]
    v4 = block_convergence_verdict(blocks_hou)
    if v4["status"] != CONVERGENCE_FAIL:
        f.append(f"C4: the 2.968pp HOU@NYM-scale gap did not fail: {v4['gap_pp']}pp")
    v4b = estimator_verdict(0.52968, 0.5)
    if v4b["status"] != CONVERGENCE_FAIL or abs(v4b["gap_pp"] - 2.968) > 0.001:
        f.append(f"C4b: two-estimator check did not reproduce the 2.968pp failure: {v4b}")
    if estimator_verdict(0.51, 0.50)["status"] != CONVERGENCE_OK:
        f.append("C4b: a 1.0pp estimator gap failed against the registered tolerance")

    # C5 — run_slate builds the REST of the board around a failing game; exit path is not 1.
    games = [
        {"game_id": "GOOD1@HOME", "disposition": _actionable_disposition(),
         "block_p_home": _blocks(0.60)},
        {"game_id": "BAD@HOME", "disposition": _actionable_disposition(),
         "block_p_home": _rigged_blocks(0.55)},
        {"game_id": "GOOD2@HOME", "disposition": _actionable_disposition(),
         "estimators": (0.505, 0.500)},
    ]
    slate = run_slate(games)
    if slate["n_games"] != 3 or len(slate["rows"]) != 3:
        f.append(f"C5: the board lost rows around a convergence failure: {slate['n_games']}")
    if len(slate["convergence_failures"]) != 1 or "BAD@HOME" not in slate["convergence_failures"][0]:
        f.append(f"C5: failures not recorded exactly once: {slate['convergence_failures']}")
    by_id = {r["game"]: r["disposition"] for r in slate["rows"]}
    if by_id["BAD@HOME"]["actionable"] or \
            by_id["BAD@HOME"]["input_value_policy"] != REGISTERED_FALLBACK_ONLY:
        f.append("C5: the failing game was not demoted in the board row")
    if not (by_id["GOOD1@HOME"]["actionable"] and by_id["GOOD2@HOME"]["actionable"]):
        f.append("C5: a healthy game's actionable path was damaged by a neighbour's failure")

    # C6 — convergence never PROMOTES. A non-actionable freshness disposition stays
    #      non-actionable even with a perfectly converged simulation.
    stale = dict(_actionable_disposition(), disposition="DEGRADED", grade="ABSENT",
                 actionable=False, bettable=False,
                 input_value_policy=REGISTERED_FALLBACK_ONLY)
    d6 = apply_convergence_gate(stale, block_convergence_verdict(_blocks(0.5)))
    if d6["actionable"]:
        f.append("C6: a clean convergence verdict promoted a degraded input to actionable")

    # C7 — malformed evidence refuses rather than passes.
    for bad in ([0.5] * 5, [0.5] * 9 + [1.5]):
        try:
            block_convergence_verdict(bad)
            f.append(f"C7: malformed block record {bad[:2]}... was waved through")
        except ConvergenceInputError:
            pass
    try:
        run_slate([{"game_id": "NOEV@HOME", "disposition": _actionable_disposition()}])
        f.append("C7: a game with no convergence evidence skipped the gate")
    except ConvergenceInputError:
        pass

    # C8 — the input disposition is never mutated in place.
    orig = _actionable_disposition()
    apply_convergence_gate(orig, block_convergence_verdict(_rigged_blocks(0.5)))
    if not orig["actionable"] or "convergence" in orig:
        f.append("C8: apply_convergence_gate mutated its input")

    print(f"mc_convergence selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("  !", x)
    return 0 if not f else 1


# ====================================================================== mutation suite

def mutation_suite():
    """Break the gate on purpose; every mutant must be caught by selftest.

    A gate nobody can prove is a gate nobody should trust.
    """
    mutants = []
    g = globals()

    def run(name, patch, restore):
        patch()
        try:
            caught = selftest() != 0
        except Exception:
            caught = True
        restore()
        mutants.append((name, caught))

    # M1 — convergence gate removed (threshold at infinity: can never fire).
    orig_sig = g["MC_CONVERGENCE_SIGMAS"]
    run("M1 convergence gate removed",
        lambda: g.__setitem__("MC_CONVERGENCE_SIGMAS", float("inf")),
        lambda: g.__setitem__("MC_CONVERGENCE_SIGMAS", orig_sig))

    # M2 — demotion removed: a FAIL keeps the row actionable.
    orig_apply = g["apply_convergence_gate"]
    run("M2 convergence failure stays actionable",
        lambda: g.__setitem__("apply_convergence_gate",
                              lambda disp, verdict, game_id=None: dict(disp)),
        lambda: g.__setitem__("apply_convergence_gate", orig_apply))

    # M3 — registered tolerance loosened 10x (the named constant silently re-tuned).
    orig_tol = g["MC_CONVERGENCE_TOL_PP"]
    run("M3 registered tolerance re-tuned 10x",
        lambda: g.__setitem__("MC_CONVERGENCE_TOL_PP", orig_tol * 10.0),
        lambda: g.__setitem__("MC_CONVERGENCE_TOL_PP", orig_tol))

    # M4 — demotion erases the forecast instead of keeping it forecast-only.
    def _apply_erasing(disp, verdict, game_id=None):
        out = orig_apply(disp, verdict, game_id=game_id)
        if verdict["status"] == CONVERGENCE_FAIL:
            out["forecastable"] = False
        return out
    run("M4 demotion erases the forecast row",
        lambda: g.__setitem__("apply_convergence_gate", _apply_erasing),
        lambda: g.__setitem__("apply_convergence_gate", orig_apply))

    n = sum(1 for _, c in mutants if c)
    print(f"\nmc_convergence mutation suite: {n}/{len(mutants)} caught")
    for name, c in mutants:
        print(f"  {'CAUGHT ' if c else 'ESCAPED'} {name}")
    return n == len(mutants)


def gate():
    ok = selftest() == 0
    print(f"mc_convergence gate: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--mutants" in sys.argv:
        sys.exit(0 if mutation_suite() else 1)
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "--gate" in sys.argv:
        sys.exit(gate())
    if "--demo" in sys.argv:
        demo = run_slate([
            {"game_id": "HOU@NYM", "disposition": _actionable_disposition(),
             "block_p_home": [0.5] * (MC_BLOCKS - 1) + [0.5 + 0.02968 / 0.9]},
            {"game_id": "TOY@HOME", "disposition": _actionable_disposition(),
             "block_p_home": _blocks(0.55)},
        ])
        print(json.dumps(demo, indent=1))
        sys.exit(0)   # the point: convergence failure does NOT exit 1
    print(__doc__)
