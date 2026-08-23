#!/usr/bin/env python3
"""EMPIRICAL UNCERTAINTY — the action screen consumes what the model has actually been wrong by.

OWNER SPECIFICATION 2026-08-23:
    "This is more important than merely changing the probability."

    Uncertainty expands when: starter information is incomplete; a named starter uses CAP
    statistics; a player has little historical data; the matchup is out of domain; recent
    calibration has deteriorated; model versions disagree materially; totals show increased tail
    misses.

    conservative_edge = raw_edge - 1.645 * empirical_edge_sd
    "Simulation sampling error alone is insufficient."

WHY SIMULATION ERROR IS THE WRONG NUMBER. A 30,000-draw Monte Carlo reports a standard error near
0.3pp, which makes a 2.7pp edge look like nine sigma. The model's OWN probabilities have an
empirical standard deviation near 3.25pp, and its 5pp-plus edges are 0-6 lifetime. The sampling
error measures how precisely the simulator reproduces its own assumptions; it says nothing about
whether those assumptions are right. Using it as the denominator is measuring the ruler instead of
the thing.

The 2026-08-22 CON +190 row is the worked example: a 2.73pp edge against a 3.25pp empirical
standard deviation is 0.84 sigma. Under this screen its conservative edge is about -2.6pp, i.e.
negative, and it fails without anyone having to argue about it.

INFLATION IS MULTIPLICATIVE AND COMPOUNDS. Each condition the owner named multiplies the base
standard deviation. Two conditions are worse than one, and the model does not get to net them off.
There is no path here that SHRINKS uncertainty: every factor is >= 1.0, and a caller that supplies
no evidence about a condition gets the penalised value, not the clean one.
"""
from __future__ import annotations

import json
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The model's own empirical probability spread, measured 2026-08: SD ~3.25pp against a market
# ~11.5pp. This is the FLOOR, not an estimate to be improved away by a better simulator.
BASE_EDGE_SD_PP = 3.25
Z_ONE_SIDED_95 = 1.645

# Every factor is >= 1.0. There is no condition under which the screen becomes more permissive.
INFLATION = {
    "ALL_CAP_BASELINE": 1.60,
    "LOW_STARTER_INFORMATION": 1.35,
    "PARTIAL_STARTER_INFORMATION": 1.15,
    "FULL_STARTER_INFORMATION": 1.00,
    "NOT_CLASSIFIABLE": 1.60,
    "UNKNOWN_INFORMATION_CLASS": 1.60,
    "named_cap_slot": 1.15,
    "thin_player_history": 1.20,
    "out_of_domain": 1.50,
    "calibration_deteriorated": 1.30,
    "model_versions_disagree": 1.25,
    "totals_tail_misses_elevated": 1.20,
}
MATERIAL_VERSION_DISAGREEMENT_PP = 3.0


def information_class_factor(cls):
    """An unknown class is penalised exactly as hard as the worst known one. A caller that cannot
    say how much starter information a card carried does not get the benefit of the doubt."""
    return INFLATION.get(cls, INFLATION["UNKNOWN_INFORMATION_CLASS"])


def empirical_edge_sd(information_class=None, named_cap_slots=0, thin_player_history=False,
                      out_of_domain=False, calibration_deteriorated=False,
                      version_disagreement_pp=None, totals_tail_misses_elevated=False,
                      base_sd_pp=BASE_EDGE_SD_PP):
    """The standard deviation the action screen must use, with every applied factor itemised."""
    sd = float(base_sd_pp)
    applied = []
    fc = information_class_factor(information_class)
    sd *= fc
    applied.append({"condition": f"information_class={information_class}", "factor": fc})
    if named_cap_slots:
        # compounds per slot: a card naming two pitchers it knows nothing about is worse than one
        fac = INFLATION["named_cap_slot"] ** int(named_cap_slots)
        sd *= fac
        applied.append({"condition": f"named_cap_slots={named_cap_slots}", "factor": fac})
    for flag, key in ((thin_player_history, "thin_player_history"),
                      (out_of_domain, "out_of_domain"),
                      (calibration_deteriorated, "calibration_deteriorated"),
                      (totals_tail_misses_elevated, "totals_tail_misses_elevated")):
        if flag:
            sd *= INFLATION[key]
            applied.append({"condition": key, "factor": INFLATION[key]})
    if version_disagreement_pp is not None and abs(version_disagreement_pp) >= MATERIAL_VERSION_DISAGREEMENT_PP:
        sd *= INFLATION["model_versions_disagree"]
        applied.append({"condition": f"model_versions_disagree({version_disagreement_pp:+.2f}pp)",
                        "factor": INFLATION["model_versions_disagree"]})
    return {"empirical_edge_sd_pp": sd, "base_sd_pp": float(base_sd_pp),
            "total_inflation": sd / float(base_sd_pp) if base_sd_pp else None,
            "factors_applied": applied}


def conservative_edge(raw_edge_pp, sd_rec=None, z=Z_ONE_SIDED_95, **kw):
    """raw_edge - z * empirical_edge_sd, with the sigma count stated.

    The sigma count is reported because it is the number that makes the case legible: a 2.73pp edge
    against a 3.25pp spread is 0.84 sigma, and no amount of simulation precision changes that."""
    rec = sd_rec if sd_rec is not None else empirical_edge_sd(**kw)
    sd = rec["empirical_edge_sd_pp"]
    ce = float(raw_edge_pp) - z * sd
    return {"raw_edge_pp": float(raw_edge_pp),
            "empirical_edge_sd_pp": sd,
            "z": z,
            "conservative_edge_pp": ce,
            "sigma": (float(raw_edge_pp) / sd) if sd else None,
            "passes_screen": ce > 0.0,
            "basis": "EMPIRICAL model spread, not Monte Carlo sampling error",
            "factors_applied": rec["factors_applied"]}


def screen(raw_edge_pp, simulation_se_pp=None, **kw):
    """The full screen, and a refusal if anyone tries to substitute the simulation standard error."""
    out = conservative_edge(raw_edge_pp, **kw)
    if simulation_se_pp is not None:
        out["simulation_se_pp"] = float(simulation_se_pp)
        out["simulation_se_sigma"] = (float(raw_edge_pp) / float(simulation_se_pp)
                                      if simulation_se_pp else None)
        out["why_simulation_se_is_not_used"] = (
            "Monte Carlo standard error measures how precisely the simulator reproduces its own "
            "assumptions. It does not measure whether those assumptions are right, and using it as "
            "the denominator makes a compressed model look decisive.")
    return out


def selftest():
    f = []
    # --- NO PATH SHRINKS UNCERTAINTY ------------------------------------------------------------
    for k, v in INFLATION.items():
        if v < 1.0:
            f.append(f"inflation factor {k}={v} is below 1.0 — no condition may make the screen "
                     f"more permissive")
    clean = empirical_edge_sd("FULL_STARTER_INFORMATION")
    if abs(clean["empirical_edge_sd_pp"] - BASE_EDGE_SD_PP) > 1e-12:
        f.append(f"a fully informed clean row did not sit at the base sd: {clean}")
    # every single condition must WIDEN
    for kw in ({"named_cap_slots": 1}, {"thin_player_history": True}, {"out_of_domain": True},
               {"calibration_deteriorated": True}, {"totals_tail_misses_elevated": True},
               {"version_disagreement_pp": 5.0}):
        w = empirical_edge_sd("FULL_STARTER_INFORMATION", **kw)["empirical_edge_sd_pp"]
        if not (w > BASE_EDGE_SD_PP):
            f.append(f"{kw} did not widen the empirical sd ({w})")
    # ...and conditions COMPOUND
    one = empirical_edge_sd("FULL_STARTER_INFORMATION", out_of_domain=True)["empirical_edge_sd_pp"]
    two = empirical_edge_sd("FULL_STARTER_INFORMATION", out_of_domain=True,
                            calibration_deteriorated=True)["empirical_edge_sd_pp"]
    if not (two > one):
        f.append("two conditions did not compound beyond one")
    # named CAP slots compound per slot
    s1 = empirical_edge_sd("PARTIAL_STARTER_INFORMATION", named_cap_slots=1)["empirical_edge_sd_pp"]
    s2 = empirical_edge_sd("PARTIAL_STARTER_INFORMATION", named_cap_slots=2)["empirical_edge_sd_pp"]
    if not (s2 > s1):
        f.append("two named-CAP slots were not penalised more than one")

    # --- INFORMATION CLASS ORDERING ---------------------------------------------------------------
    order = [empirical_edge_sd(c)["empirical_edge_sd_pp"] for c in
             ("FULL_STARTER_INFORMATION", "PARTIAL_STARTER_INFORMATION",
              "LOW_STARTER_INFORMATION", "ALL_CAP_BASELINE")]
    if not all(a < b for a, b in zip(order, order[1:])):
        f.append(f"uncertainty does not increase STRICTLY as starter information falls: {order} — "
                 f"a non-strict check passes when the class factor is not applied at all")
    # an UNKNOWN class is penalised as hard as the worst known one
    for lbl in (None, "SOMETHING_NEW"):
        u = empirical_edge_sd(lbl)["empirical_edge_sd_pp"]
        if u < empirical_edge_sd("ALL_CAP_BASELINE")["empirical_edge_sd_pp"]:
            f.append(f"information class {lbl!r} was treated more leniently than ALL_CAP_BASELINE")
        if u <= BASE_EDGE_SD_PP:
            f.append(f"information class {lbl!r} carried NO penalty at all ({u})")

    # --- THE WORKED EXAMPLE: 2026-08-22 CON +190 ---------------------------------------------------
    ce = conservative_edge(2.73, information_class="ALL_CAP_BASELINE")
    if ce["sigma"] is None or ce["sigma"] >= 1.0:
        f.append(f"the CON +190 row scored {ce['sigma']} sigma; a 2.73pp edge against a 3.25pp "
                 f"spread must be under one sigma even before inflation")
    if ce["conservative_edge_pp"] >= 0 or ce["passes_screen"]:
        f.append(f"the CON +190 row PASSED the screen with a conservative edge of "
                 f"{ce['conservative_edge_pp']:.2f}pp")
    # the same edge against SIMULATION error would look decisive — that is the point
    sc = screen(2.73, simulation_se_pp=0.30, information_class="ALL_CAP_BASELINE")
    if sc["simulation_se_sigma"] < 5:
        f.append("the simulation-error sigma is not being reported for contrast")
    if sc["passes_screen"]:
        f.append("supplying a simulation standard error caused the row to pass")
    if "does not measure whether those assumptions are right" not in \
            sc.get("why_simulation_se_is_not_used", ""):
        f.append("the screen does not state why simulation error is rejected")
    if "EMPIRICAL" not in sc["basis"]:
        f.append("the screen does not declare its basis")

    # --- THE ARITHMETIC -----------------------------------------------------------------------------
    e = conservative_edge(10.0, information_class="FULL_STARTER_INFORMATION")
    if abs(e["conservative_edge_pp"] - (10.0 - 1.645 * 3.25)) > 1e-12:
        f.append(f"conservative_edge arithmetic wrong: {e['conservative_edge_pp']}")
    if abs(e["sigma"] - 10.0 / 3.25) > 1e-12:
        f.append("sigma is not raw_edge / empirical_sd")
    # sigma must be measured against the INFLATED sd, not the base — otherwise every penalty applied
    # above is invisible in the one number a reader actually looks at
    infl = conservative_edge(10.0, information_class="ALL_CAP_BASELINE", out_of_domain=True)
    if abs(infl["sigma"] - 10.0 / infl["empirical_edge_sd_pp"]) > 1e-12:
        f.append(f"sigma {infl['sigma']} is not measured against the inflated sd "
                 f"{infl['empirical_edge_sd_pp']}")
    if infl["sigma"] >= e["sigma"]:
        f.append("an inflated row reported the same or a larger sigma than a clean one")
    # an edge must exceed 1.645 sd to pass, and the boundary is checked ON the boundary
    b = 1.645 * 3.25
    if conservative_edge(b, information_class="FULL_STARTER_INFORMATION")["passes_screen"]:
        f.append("an edge exactly at 1.645 sd passed; the screen must be strict")
    if not conservative_edge(b + 1e-6, information_class="FULL_STARTER_INFORMATION")["passes_screen"]:
        f.append("an edge just above 1.645 sd failed")
    # a NEGATIVE raw edge can never pass
    if conservative_edge(-1.0, information_class="FULL_STARTER_INFORMATION")["passes_screen"]:
        f.append("a negative raw edge passed the screen")
    # the historical 5pp band: 0-6 lifetime. A 5pp edge on an all-CAP card must NOT pass.
    if conservative_edge(5.0, information_class="ALL_CAP_BASELINE")["passes_screen"]:
        f.append("a 5pp edge on an all-CAP card passed the screen; that band is 0-6 lifetime")
    # every applied factor must be itemised, so a refusal can be argued with
    r = conservative_edge(2.0, information_class="ALL_CAP_BASELINE", named_cap_slots=2,
                          out_of_domain=True)
    if len(r["factors_applied"]) < 3:
        f.append(f"factors were applied without being itemised: {r['factors_applied']}")
    if not all("factor" in x and "condition" in x for x in r["factors_applied"]):
        f.append("an applied factor was recorded without its condition or its size")

    # --- version disagreement threshold -------------------------------------------------------------
    if empirical_edge_sd("FULL_STARTER_INFORMATION", version_disagreement_pp=2.99)["empirical_edge_sd_pp"] \
            != BASE_EDGE_SD_PP:
        f.append("an immaterial version disagreement widened the interval")
    if empirical_edge_sd("FULL_STARTER_INFORMATION", version_disagreement_pp=3.0)["empirical_edge_sd_pp"] \
            <= BASE_EDGE_SD_PP:
        f.append("a version disagreement exactly at the material threshold did not widen it")
    if empirical_edge_sd("FULL_STARTER_INFORMATION", version_disagreement_pp=-5.0)["empirical_edge_sd_pp"] \
            <= BASE_EDGE_SD_PP:
        f.append("a NEGATIVE version disagreement of the same size was ignored")

    print("empirical_uncertainty selftest:", "PASS" if not f else "FAIL")
    for x in f:
        print("  " + x)
    return f


MUTANTS = [
    ("the screen uses SIMULATION sampling error instead of the empirical spread",
     "BASE_EDGE_SD_PP = 3.25", "BASE_EDGE_SD_PP = 0.30"),
    ("the one-sided 95% z drops to zero, so any positive edge passes",
     "Z_ONE_SIDED_95 = 1.645", "Z_ONE_SIDED_95 = 0.0"),
    ("an unknown information class gets the CLEAN factor",
     '    return INFLATION.get(cls, INFLATION["UNKNOWN_INFORMATION_CLASS"])',
     '    return INFLATION.get(cls, 1.0)'),
    ("the all-CAP penalty is removed", '    "ALL_CAP_BASELINE": 1.60,', '    "ALL_CAP_BASELINE": 1.00,'),
    ("information-class inflation stops being applied at all",
     "    sd *= fc\n", "    sd *= 1.0\n"),
    ("named CAP slots stop compounding per slot",
     '        fac = INFLATION["named_cap_slot"] ** int(named_cap_slots)',
     '        fac = INFLATION["named_cap_slot"]'),
    ("named CAP slots stop being penalised", "    if named_cap_slots:", "    if False:"),
    ("the itemised conditions stop compounding and only the last one counts",
     "            sd *= INFLATION[key]", "            sd = float(base_sd_pp) * INFLATION[key]"),
    ("out-of-domain, calibration and tail-miss conditions are ignored",
     "        if flag:", "        if False:"),
    ("the screen becomes non-strict at exactly 1.645 sd",
     '            "passes_screen": ce > 0.0,', '            "passes_screen": ce >= 0.0,'),
    ("the conservative edge stops subtracting the interval",
     "    ce = float(raw_edge_pp) - z * sd", "    ce = float(raw_edge_pp)"),
    ("sigma is computed against the BASE sd, hiding every inflation",
     '            "sigma": (float(raw_edge_pp) / sd) if sd else None,',
     '            "sigma": (float(raw_edge_pp) / BASE_EDGE_SD_PP),'),
    ("the material version-disagreement threshold is raised out of reach",
     "MATERIAL_VERSION_DISAGREEMENT_PP = 3.0", "MATERIAL_VERSION_DISAGREEMENT_PP = 99.0"),
    ("version disagreement is read signed, so a negative gap is ignored",
     "    if version_disagreement_pp is not None and abs(version_disagreement_pp) >= MATERIAL_VERSION_DISAGREEMENT_PP:",
     "    if version_disagreement_pp is not None and version_disagreement_pp >= MATERIAL_VERSION_DISAGREEMENT_PP:"),
    ("applied factors stop being itemised, so a refusal cannot be argued with",
     '    applied.append({"condition": f"information_class={information_class}", "factor": fc})',
     "    pass"),
    ("the screen stops declaring why simulation error is rejected",
     '        out["why_simulation_se_is_not_used"] = (', '        out["_unused"] = ('),
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
