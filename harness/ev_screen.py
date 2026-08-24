#!/usr/bin/env python3
"""EV SCREEN — the twelve numbers behind a moneyline verdict, and why uncertainty is one of them.

OWNER DIRECTIVE 2026-08-24 item 6: for every MLB moneyline compute the model probability from the
preregistered PRIMARY arm, the American-odds break-even, the two-sided hold, the no-vig probability,
edge in points, EV per $1 and per $100, model uncertainty, Monte Carlo error SEPARATELY, arm
disagreement, personnel/information risk, and a final status.

TWO EDGES, BOTH REPORTED, BECAUSE THEY ANSWER DIFFERENT QUESTIONS.
  edge vs break-even   p_model - p_breakeven. The EV-relevant edge: the break-even is the probability
                       the PRICE demands, vig included, and beating it is what makes money. EV is a
                       monotone function of exactly this quantity.
  edge vs no-vig       p_model - p_novig. The disagreement with the market's own opinion once the
                       hold is removed. It never appears in an EV calculation.
Quoting one and calling it "edge" is how a 2pp disagreement becomes a 5pp edge in a summary.

MONTE CARLO ERROR IS NOT MODEL UNCERTAINTY. MC error says how well the simulation converged; model
uncertainty says how wrong the model may be. More draws shrink the first and leave the second exactly
where it was. A screen that used MC error as its uncertainty would grow more confident by running
longer, which is the most dangerous possible failure mode for a betting screen.

WHEN UNCERTAINTY CANNOT BE PRODUCED, the owner's instruction is explicit: show the computed price and
the raw EV, then return UNCERTAINTY_PIPELINE_DEFECT. Do not fall back to a missing-price explanation
and do not relabel dispersion, prior-parameter SD or MC error to fill the field.
"""
from __future__ import annotations

import json
import math
import os
import sys

SELECT = "SELECT"
LEAN_HOLD = "LEAN_HOLD"
PASS = "PASS"
BLOCK = "BLOCK"
UNCERTAINTY_DEFECT = "UNCERTAINTY_PIPELINE_DEFECT"

#: Preregistered. Necessary conditions for a selection, never sufficient ones.
MIN_EDGE_PP_FOR_SELECT = 2.0
MIN_EDGE_PP_FOR_LEAN = 0.5
MIN_SIGMA_FOR_SELECT = 1.0


def _num(x):
    if x is None or isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def breakeven(american):
    """Implied probability INCLUDING the vig — the probability the price demands."""
    a = _num(american)
    if a is None or a == 0 or -100 < a < 100:
        return None
    return (-a) / ((-a) + 100.0) if a < 0 else 100.0 / (a + 100.0)


def payout(american):
    """Profit per $1 staked on a win."""
    a = _num(american)
    if a is None or a == 0 or -100 < a < 100:
        return None
    return 100.0 / (-a) if a < 0 else a / 100.0


def hold(away_odds, home_odds):
    a, h = breakeven(away_odds), breakeven(home_odds)
    if a is None or h is None:
        return None
    return a + h - 1.0


def novig(away_odds, home_odds):
    a, h = breakeven(away_odds), breakeven(home_odds)
    if a is None or h is None:
        return None, None
    s = a + h
    if s <= 0:
        return None, None
    return a / s, h / s


def ev_per_dollar(p, american):
    pp, w = _num(p), payout(american)
    if pp is None or w is None or not (0.0 <= pp <= 1.0):
        return None
    return pp * w - (1.0 - pp)


def screen(row):
    r = row or {}
    side_odds = _num(r.get("side_odds"))
    p = _num(r.get("model_probability"))
    out = {
        "game": r.get("game"), "side": r.get("side"), "primary_arm": r.get("primary_arm"),
        "model_probability": p, "side_odds": side_odds, "other_odds": _num(r.get("other_odds")),
        "breakeven_probability": breakeven(side_odds),
        "two_sided_hold": hold(r.get("away_odds"), r.get("home_odds")),
        "novig_probability": None, "edge_vs_breakeven_pp": None, "edge_vs_novig_pp": None,
        "ev_per_dollar": ev_per_dollar(p, side_odds), "ev_per_100": None,
        "model_uncertainty_pp": _num(r.get("model_uncertainty_pp")),
        "model_uncertainty_source": r.get("model_uncertainty_source"),
        "monte_carlo_error_pp": _num(r.get("monte_carlo_error_pp")),
        "arm_disagreement_pp": _num(r.get("arm_disagreement_pp")),
        "information_risk": r.get("information_risk"),
        "blocks": list(r.get("blocks") or []),
    }
    nva, nvh = novig(r.get("away_odds"), r.get("home_odds"))
    out["novig_probability"] = nva if r.get("side") == "away" else nvh
    if p is not None and out["breakeven_probability"] is not None:
        out["edge_vs_breakeven_pp"] = 100.0 * (p - out["breakeven_probability"])
    if p is not None and out["novig_probability"] is not None:
        out["edge_vs_novig_pp"] = 100.0 * (p - out["novig_probability"])
    if out["ev_per_dollar"] is not None:
        out["ev_per_100"] = 100.0 * out["ev_per_dollar"]

    if out["blocks"]:
        out["status"] = BLOCK
        out["status_reason"] = "; ".join(out["blocks"])
        return out
    if out["model_uncertainty_pp"] is None:
        out["status"] = PASS
        out["uncertainty_status"] = UNCERTAINTY_DEFECT
        out["status_reason"] = (
            f"{UNCERTAINTY_DEFECT} — the price and the raw EV above are computed and correct; what "
            f"is missing is a defensible per-game model uncertainty. Cross-game dispersion, the "
            f"prior parameter SD and Monte Carlo error are none of them that quantity and are not "
            f"substituted here.")
        return out
    if out["model_uncertainty_pp"] == out["monte_carlo_error_pp"]:
        out["status"] = PASS
        out["uncertainty_status"] = UNCERTAINTY_DEFECT
        out["status_reason"] = (f"{UNCERTAINTY_DEFECT} — model uncertainty equals Monte Carlo error, "
                                f"which means one was substituted for the other")
        return out
    e = out["edge_vs_breakeven_pp"]
    if e is None:
        out["status"] = PASS
        out["status_reason"] = "no computable edge"
        return out
    sigma = e / out["model_uncertainty_pp"] if out["model_uncertainty_pp"] > 0 else None
    out["edge_sigma"] = sigma
    if e >= MIN_EDGE_PP_FOR_SELECT and sigma is not None and sigma >= MIN_SIGMA_FOR_SELECT:
        out["status"] = SELECT
        out["status_reason"] = f"edge {e:+.2f}pp over break-even at {sigma:.2f} sigma"
    elif e >= MIN_EDGE_PP_FOR_LEAN:
        out["status"] = LEAN_HOLD
        out["status_reason"] = (f"edge {e:+.2f}pp is positive but below the "
                                f"{MIN_EDGE_PP_FOR_SELECT}pp floor or under "
                                f"{MIN_SIGMA_FOR_SELECT} sigma")
    else:
        out["status"] = PASS
        out["status_reason"] = f"edge {e:+.2f}pp does not clear the {MIN_EDGE_PP_FOR_LEAN}pp floor"
    return out


# =================================================================================================
def selftest():
    f = []
    if abs(breakeven(-124) - 124/224) > 1e-12: f.append("breakeven(-124) must be 124/224")
    if abs(breakeven(115) - 100/215) > 1e-12: f.append("breakeven(+115) must be 100/215")
    if abs(payout(-124) - 100/124) > 1e-12: f.append("payout(-124) must be 100/124")
    if abs(payout(115) - 1.15) > 1e-12: f.append("payout(+115) must be 1.15")
    for bad in (0, 50, -50, 99, -99, None, "x", True):
        if breakeven(bad) is not None or payout(bad) is not None:
            f.append(f"{bad!r} is not a valid American price")
    # -110/-110: the OVERROUND (sum of break-evens minus 1) is 4.7619%. The figure usually quoted
    # as "4.55% hold" is the same vig expressed as a fraction of handle, overround/(1+overround).
    # Two conventions, routinely confused; this function returns the overround and says so.
    h = hold(-110, -110)
    if abs(h - 0.047619047619047616) > 1e-12:
        f.append(f"hold(-110,-110) is the 4.7619% overround, got {h}")
    if abs(h/(1+h) - 0.045454545454545456) > 1e-12:
        f.append("the handle-fraction form of that same vig is 4.5455%")
    a, hm = novig(-110, -110)
    if abs(a - 0.5) > 1e-12 or abs(hm - 0.5) > 1e-12: f.append("a symmetric market de-vigs to 50/50")
    ha = hold(-124, 115)
    if abs(ha - 0.018687707641195983) > 1e-12:
        f.append(f"the real BOS@MIA market holds 1.8688%, got {ha}")
    nva, nvh = novig(-124, 115)
    if abs(nva + nvh - 1.0) > 1e-12: f.append("no-vig probabilities must sum to 1")
    # de-vigging divides BOTH sides by a sum greater than 1, so both fall; it does not favour a side
    if not (nva < breakeven(-124) and nvh < breakeven(115)):
        f.append("de-vigging must lower both implied probabilities, not raise either")
    if abs(ev_per_dollar(0.5, 100) - 0.0) > 1e-12: f.append("p=.5 at +100 is EV zero")
    if abs(ev_per_dollar(0.55, 115) - (0.55*1.15 - 0.45)) > 1e-12: f.append("EV formula wrong")
    if ev_per_dollar(1.0, -200) <= 0: f.append("a certain winner has positive EV")
    for bad in (-0.1, 1.1, None):
        if ev_per_dollar(bad, 115) is not None: f.append(f"p={bad} is not a probability")

    base = {"game": "mlb:BOS@MIA", "side": "home", "primary_arm": "mlb.winner.CHAMPION_V13_100K",
            "model_probability": 0.4999, "side_odds": 115, "other_odds": -124,
            "away_odds": -124, "home_odds": 115}
    s = screen(base)
    if s["edge_vs_breakeven_pp"] is None or s["edge_vs_novig_pp"] is None:
        f.append("both edges must be reported")
    if abs(s["edge_vs_breakeven_pp"] - s["edge_vs_novig_pp"]) < 1e-9:
        f.append("the two edges must differ on a real market")
    # the no-vig probability is always BELOW the break-even, so the no-vig edge is always the LARGER
    # of the two. Reporting the larger one as "the edge" is how a disagreement becomes an edge.
    if s["edge_vs_novig_pp"] <= s["edge_vs_breakeven_pp"]:
        f.append("the no-vig edge is always the larger; only the break-even edge drives EV")
    if abs(s["ev_per_100"] - 100*s["ev_per_dollar"]) > 1e-12:
        f.append("EV per 100 must be 100x EV per dollar")
    if s["status"] != PASS or s.get("uncertainty_status") != UNCERTAINTY_DEFECT:
        f.append(f"no model uncertainty must PASS with the defect, got {s['status']}")
    if s["ev_per_dollar"] is None or s["ev_per_100"] is None:
        f.append("the raw EV must still be computed and shown under the defect")
    if "no prices" in s["status_reason"].lower() or "missing price" in s["status_reason"].lower():
        f.append("the defect reason must never fall back to a missing-price explanation")
    if "Monte Carlo error are none of them" not in s["status_reason"]:
        f.append("the defect reason must name what may NOT be substituted")

    sub = screen(dict(base, model_uncertainty_pp=0.157, monte_carlo_error_pp=0.157))
    if sub["status"] != PASS or sub.get("uncertainty_status") != UNCERTAINTY_DEFECT:
        f.append("identical uncertainty and MC error must be refused as a substitution")

    big = screen(dict(base, model_probability=0.60, model_uncertainty_pp=3.0, monte_carlo_error_pp=0.16))
    if big["status"] != SELECT: f.append(f"a large edge at >1 sigma must SELECT, got {big['status']}")
    thin = screen(dict(base, model_probability=0.475, model_uncertainty_pp=3.0, monte_carlo_error_pp=0.16))
    if thin["status"] != LEAN_HOLD: f.append(f"a thin positive edge must LEAN_HOLD, got {thin['status']}")
    # a sub-2pp edge that DOES clear a sigma must still be held, or the point floor is decorative:
    # with a tight uncertainty the sigma test alone would let a +0.99pp edge through
    tight = screen(dict(base, model_probability=0.475, model_uncertainty_pp=0.5,
                        monte_carlo_error_pp=0.16))
    if tight["status"] != LEAN_HOLD:
        f.append(f"a +0.99pp edge at {tight.get('edge_sigma'):.2f} sigma is below the point floor "
                 f"and must LEAN_HOLD, got {tight['status']}")
    if tight.get("edge_sigma") is None or tight["edge_sigma"] < MIN_SIGMA_FOR_SELECT:
        f.append("fixture is wrong: this row must clear the sigma test so the POINT floor is what binds")

    neg = screen(dict(base, model_probability=0.40, model_uncertainty_pp=3.0, monte_carlo_error_pp=0.16))
    if neg["status"] != PASS: f.append("a negative edge must PASS")
    noisy = screen(dict(base, model_probability=0.60, model_uncertainty_pp=25.0, monte_carlo_error_pp=0.16))
    if noisy["status"] == SELECT: f.append("a sub-1-sigma edge must not select however large the point edge")
    blocked = screen(dict(base, model_probability=0.60, model_uncertainty_pp=3.0, monte_carlo_error_pp=0.16,
                          blocks=["MATERIAL_STARTER_STATE_CHANGED_AFTER_LOCK"]))
    if blocked["status"] != BLOCK or "STARTER" not in blocked["status_reason"]:
        f.append("a block must override a selectable edge and name itself")

    for x in f:
        print("FAIL:", x)
    if not f:
        print("ev_screen selftest: OK")
    return f


MUTANTS = [
    ("break-even ignores the price entirely",
     "    return (-a) / ((-a) + 100.0) if a < 0 else 100.0 / (a + 100.0)", "    return 0.5"),
    ("the favourite and underdog break-even branches are swapped",
     "    return (-a) / ((-a) + 100.0) if a < 0 else 100.0 / (a + 100.0)",
     "    return 100.0 / ((-a) + 100.0) if a < 0 else a / (a + 100.0)"),
    ("payout swaps its branches",
     "    return 100.0 / (-a) if a < 0 else a / 100.0", "    return (-a) / 100.0 if a < 0 else 100.0 / a"),
    ("a price inside the +/-100 gap is accepted",
     "    if a is None or a == 0 or -100 < a < 100:\n        return None\n    return (-a) / ((-a) + 100.0) if a < 0 else 100.0 / (a + 100.0)",
     "    if a is None or a == 0:\n        return None\n    return (-a) / ((-a) + 100.0) if a < 0 else 100.0 / (a + 100.0)"),
    ("hold is the raw sum rather than the excess over 1",
     "    return a + h - 1.0", "    return a + h"),
    ("de-vig stops normalising",
     "    return a / s, h / s", "    return a, h"),
    ("EV forgets the stake at risk",
     "    return pp * w - (1.0 - pp)", "    return pp * w"),
    ("EV per 100 is not 100x EV per dollar",
     '        out["ev_per_100"] = 100.0 * out["ev_per_dollar"]', '        out["ev_per_100"] = out["ev_per_dollar"]'),
    ("the break-even edge is replaced by the no-vig edge",
     '        out["edge_vs_breakeven_pp"] = 100.0 * (p - out["breakeven_probability"])',
     '        out["edge_vs_breakeven_pp"] = 100.0 * (p - (out["novig_probability"] or 0))'),
    ("a missing model uncertainty stops blocking selection",
     '    if out["model_uncertainty_pp"] is None:', "    if False:"),
    ("the raw EV is suppressed under the uncertainty defect",
     '        "ev_per_dollar": ev_per_dollar(p, side_odds), "ev_per_100": None,',
     '        "ev_per_dollar": None, "ev_per_100": None,'),
    ("Monte Carlo error may stand in for model uncertainty",
     '    if out["model_uncertainty_pp"] == out["monte_carlo_error_pp"]:', "    if False:"),
    ("the uncertainty defect blames missing prices",
     '            f"{UNCERTAINTY_DEFECT} — the price and the raw EV above are computed and correct; what "',
     '            f"{UNCERTAINTY_DEFECT} — no prices exist for this slate; what "'),
    ("the defect stops naming what may not be substituted",
     '            f"prior parameter SD and Monte Carlo error are none of them that quantity and are not "\n            f"substituted here.")',
     '            f"something is missing.")'),
    ("a block no longer overrides a selectable edge",
     '    if out["blocks"]:', "    if False:"),
    ("the sigma floor is removed, so a noisy edge selects",
     "    if e >= MIN_EDGE_PP_FOR_SELECT and sigma is not None and sigma >= MIN_SIGMA_FOR_SELECT:",
     "    if e >= MIN_EDGE_PP_FOR_SELECT:"),
    ("the selection floor collapses to zero",
     "MIN_EDGE_PP_FOR_SELECT = 2.0", "MIN_EDGE_PP_FOR_SELECT = 0.0"),
    ("a negative edge is treated as a lean",
     "MIN_EDGE_PP_FOR_LEAN = 0.5", "MIN_EDGE_PP_FOR_LEAN = -99.0"),
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
