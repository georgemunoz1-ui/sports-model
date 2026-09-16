#!/usr/bin/env python3
"""WNBA STANDINGS FALLBACK ARM — a worse honest arm beats an indefinite outage.

Registered 2026-08-26 under owner direction ("sitting since July 22nd is unacceptable"). Every
fetch route is blocked by the environment's network policy; the only working content route is
search, whose snippets never bind canonical units. This arm therefore runs on the coarsest input
that a single concordant snapshot can supply — season win-loss records — and says so on every
output.

METHOD (v1, fully stated, nothing tunable left silent):
    p_log5   = (wh*(1-wa)) / (wh*(1-wa) + wa*(1-wh))      # Bill James log5 on season win%
    p_home   = sigmoid(logit(p_log5) + logit(WNBA_HOME_PRIOR))  # registered home shift
No shrinkage, no schedule adjustment, no recency weighting — v1 declines to invent constants.

GRADE. Inputs are PROVISIONAL_SEARCH_ASSEMBLED (concordance-checked snapshot, as-of dated,
rolled forward only with owner-relayed finals). Outputs are DIAGNOSTIC_ONLY and action-blocked:
they never settle, never promote, never enter the estimator, and never count as RJ-005 units —
the pipeline SYSTEM_FAILURE stands until real artifacts bind. This arm exists so the reader sees
the model family's best honest current output instead of a bare failure card.
"""
from __future__ import annotations

import math
import sys

MODULE_ID = "wnba_standings_fallback"

IDENTITY = "wnba.fallback.STANDINGS_LOG5_v1"
INPUT_GRADE = "PROVISIONAL_SEARCH_ASSEMBLED"
OUTPUT_GRADE = "DIAGNOSTIC_ONLY_ACTION_BLOCKED"
WNBA_HOME_PRIOR = 0.536585   # the registered 21-game provisional prior; single source of truth


def _logit(p):
    return math.log(p / (1.0 - p))


def _sig(z):
    return 1.0 / (1.0 + math.exp(-z))


def win_pct(w, l):
    if w + l <= 0:
        return None
    return w / (w + l)


def p_home(home_w, home_l, away_w, away_l):
    """Returns (p_home, parts) or (None, reason). Refuses empty records."""
    wh, wa = win_pct(home_w, home_l), win_pct(away_w, away_l)
    if wh is None or wa is None:
        return None, "EMPTY_RECORD"
    # log5 is undefined at 0% and 100%; clamp to one game's worth of doubt, and say so
    eps = 1.0 / (home_w + home_l + 1)
    wh = min(max(wh, eps), 1 - eps)
    eps = 1.0 / (away_w + away_l + 1)
    wa = min(max(wa, eps), 1 - eps)
    p5 = (wh * (1 - wa)) / (wh * (1 - wa) + wa * (1 - wh))
    p = _sig(_logit(p5) + _logit(WNBA_HOME_PRIOR))
    return p, {"log5": p5, "home_shift_logit": _logit(WNBA_HOME_PRIOR),
               "identity": IDENTITY, "input_grade": INPUT_GRADE,
               "output_grade": OUTPUT_GRADE}


# =================================================================================================
def selftest():
    f = []
    p, parts = p_home(10, 27, 26, 11)   # weak home vs strong away
    if p is None or not (0.10 < p < 0.30):
        f.append(f"a .270 home team against a .703 road team lands well under 50%, got {p}")
    q, _ = p_home(26, 11, 10, 27)       # reversed
    if q is None or not (0.80 < q < 0.95):
        f.append(f"reversed matchup must mirror high, got {q}")
    e, ee = p_home(18, 18, 18, 18)      # equal teams -> exactly the home prior
    # compare against the LITERAL, not the module constant — a fixture that reads the constant
    # it is supposed to police cannot notice the constant drifting (lesson 32)
    if e is None or abs(e - 0.536585) > 1e-9:
        f.append(f"equal records must return exactly the registered home prior, got {e}")
    z, zr = p_home(0, 0, 5, 5)
    if z is not None or zr != "EMPTY_RECORD":
        f.append("an empty record must refuse, not guess")
    u, _ = p_home(0, 37, 37, 0)         # extremes clamp instead of exploding
    if u is None or not (0.0 < u < 0.15):
        f.append(f"extreme records clamp to one game's doubt, got {u}")
    if parts["identity"] != IDENTITY or parts["output_grade"] != OUTPUT_GRADE:
        f.append("every output carries the identity and the action-blocked grade")
    print("wnba_standings_fallback selftest:", "OK" if not f else "FAIL")
    for x in f:
        print("   -", x)
    return not f


MUTANTS = [
    ("the home shift silently disappears",
     "    p = _sig(_logit(p5) + _logit(WNBA_HOME_PRIOR))",
     "    p = p5"),
    ("the prior constant drifts from the registered value",
     "WNBA_HOME_PRIOR = 0.536585",
     "WNBA_HOME_PRIOR = 0.5"),
    ("empty records start guessing 50%",
     '    if wh is None or wa is None:\n        return None, "EMPTY_RECORD"',
     "    wh = wh if wh is not None else 0.5\n    wa = wa if wa is not None else 0.5"),
    ("outputs stop carrying the action-blocked grade",
     '               "identity": IDENTITY, "input_grade": INPUT_GRADE,\n'
     '               "output_grade": OUTPUT_GRADE}',
     '               "identity": IDENTITY, "input_grade": INPUT_GRADE,\n'
     '               "output_grade": "FORECAST_REGISTERED"}'),
    ("log5 inverts home and away",
     "    p5 = (wh * (1 - wa)) / (wh * (1 - wa) + wa * (1 - wh))",
     "    p5 = (wa * (1 - wh)) / (wa * (1 - wh) + wh * (1 - wa))"),
]


def mutation_suite():
    src = open(__file__).read()
    import io as _io, contextlib as _cl
    _b = _io.StringIO()
    with _cl.redirect_stdout(_b):
        _base = selftest()
    if not _base:
        print("  BASELINE_FAILING")
        print(_b.getvalue().strip())
        return False
    body = src[:src.index("MUTANTS = [")]
    killed = 0
    for name, old, new in MUTANTS:
        if old not in src:
            print("  UNAPPLIED ", name)
            continue
        if old not in body:
            print("  SELF_TARGETED ", name)
            continue
        ns = {"__file__": __file__, "__name__": "mutant"}
        try:
            exec(compile(src.replace(old, new, 1), "<mutant>", "exec"), ns)
            ok = ns["selftest"]()
        except Exception:
            ok = False
        print(("  KILLED    " if not ok else "  SURVIVED  ") + name)
        killed += not ok
    print(f"mutation suite: {killed}/{len(MUTANTS)} killed")
    return killed == len(MUTANTS)


if __name__ == "__main__":
    if "--mutants" in sys.argv:
        sys.exit(0 if mutation_suite() else 1)
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    print(__doc__)
