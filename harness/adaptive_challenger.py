"""CHALLENGER_ADAPTIVE v0_2 — a registered identity, because v0_1's constants died uncommitted.

WHY THIS IS v0_2 AND NOT A RECONSTRUCTION. The 2026-08-24 board carries
mlb.winner.CHALLENGER_ADAPTIVE rows stamped adaptive_v0_1, with residuals like -7/450 whose exact
generating constants lived in that session's uncommitted builder. I tried to reverse them from the
registered windows and could not: no simple form-difference formula reproduces all ten residuals.
Guessing one and stamping it v0_1 would be adopting an unverifiable model identity — the class of
fabrication the evidence rules forbid, and the same defect the module manifest now exists to catch
in code. So v0_1 is CLOSED (its 8/24 rows remain gradable exactly as frozen), and this module IS
v0_2: the formula lives here, in a committed, manifest-registered file, and can never be lost the
same way.

THE FORMULA, registered pregame 2026-08-25, constants declared as policy — chosen before any v0_2
output existed, never fitted to a slate:

    residual_f = W_FORM * (shr_h - shr_a) + W_SP * (rs_away_sp - rs_home_sp)

    shr_t  = (wins_t + PRIOR_STRENGTH/2) / (games_t + PRIOR_STRENGTH) over the registered
             team_form_days window (30 days, adaptive_state.REGISTERED_WINDOWS, frozen 2026-08-23),
             canonical tier-1 FINAL rows strictly before the slate date
    rs_*   = the champion engine's own run-support-adjusted starter ERA (run_v13_historical.rs),
             so the starter term and the champion disagree only through weights, never through a
             private starter model
    p      = sigmoid(logit(PRIOR_P) + residual_f)  — baseline-offset form; the prior offset is
             never scaled, per the widening rule's contract

W_FORM = 1.0: a 30-day win-rate gap passes through at unit weight on the logit scale (a 0.10 gap
moves p by ~2.5pp at the prior). W_SP = 0.05 per run of adjusted starter ERA difference (a 2-run
starter edge moves p by ~2.5pp). Both deliberately conservative: this challenger exists to test
whether SMALL adaptive tilts beat the prior, not to compete with the simulation on amplitude.
"""

from __future__ import annotations

MODULE_ID = "adaptive_challenger"

import csv
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "harness"))

IDENTITY = "adaptive_v0_2"
SUPERSEDES = "adaptive_v0_1 (CLOSED — constants lost with an uncommitted builder; its frozen "\
             "2026-08-24 rows remain gradable; no continuity is claimed between the identities)"
W_FORM = 1.0
W_SP = 0.05
PRIOR_STRENGTH = 25          # adaptive_state.REGISTERED_WINDOWS team_rating_prior_strength_games
FORM_DAYS = 30               # adaptive_state.REGISTERED_WINDOWS team_form_days
RESULTS = "data/backfill/mlb/2026/results.csv"

FULL_TO_ABBR = {
    "Boston Red Sox": "BOS", "Miami Marlins": "MIA", "Tampa Bay Rays": "TB",
    "Detroit Tigers": "DET", "Colorado Rockies": "COL", "Washington Nationals": "WSH",
    "Texas Rangers": "TEX", "Chicago White Sox": "CWS", "Cleveland Guardians": "CLE",
    "Los Angeles Angels": "LAA", "Philadelphia Phillies": "PHI", "Seattle Mariners": "SEA",
    "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD", "Minnesota Twins": "MIN",
    "Athletics": "ATH", "Chicago Cubs": "CHC", "Arizona Diamondbacks": "AZ",
    "Cincinnati Reds": "CIN", "San Francisco Giants": "SF", "New York Yankees": "NYY",
    "New York Mets": "NYM", "Los Angeles Dodgers": "LAD", "Atlanta Braves": "ATL",
    "Houston Astros": "HOU", "Toronto Blue Jays": "TOR", "Kansas City Royals": "KC",
    "St. Louis Cardinals": "STL", "Milwaukee Brewers": "MIL", "Baltimore Orioles": "BAL",
}


def _abbr(t):
    return FULL_TO_ABBR.get(t, t)


def form_table(slate_date, results_path=RESULTS, form_days=FORM_DAYS):
    """Shrunken win rate per team over the registered window, canonical rows only, strictly before
    the slate date. Mixed name conventions in results.csv are folded (lesson 28)."""
    import datetime as dt
    d0 = (dt.date.fromisoformat(slate_date) - dt.timedelta(days=form_days)).isoformat()
    w, n = {}, {}
    for r in csv.DictReader(open(results_path)):
        if not (r["status"] == "final" and r["result_status"] == "FINAL"
                and r["source_tier"] == "1" and d0 <= r["date"] < slate_date):
            continue
        aw, hm = _abbr(r["away"]), _abbr(r["home"])
        hw = int(r["home_win"])
        w[hm] = w.get(hm, 0.0) + hw; n[hm] = n.get(hm, 0) + 1
        w[aw] = w.get(aw, 0.0) + (1 - hw); n[aw] = n.get(aw, 0) + 1
    return {t: (w[t] + PRIOR_STRENGTH / 2.0) / (n[t] + PRIOR_STRENGTH) for t in n}, n


def residual(away, home, form, rs_away_sp=None, rs_home_sp=None):
    """The registered residual. A team absent from the window contributes the shrinkage midpoint —
    absence of form is absence of evidence, not a penalty."""
    sh = form.get(home, 0.5)
    sa = form.get(away, 0.5)
    f = W_FORM * (sh - sa)
    if rs_away_sp is not None and rs_home_sp is not None:
        f += W_SP * (rs_away_sp - rs_home_sp)
    return f


def probability(prior_p, residual_f):
    z = math.log(prior_p / (1 - prior_p)) + residual_f
    return 1.0 / (1.0 + math.exp(-z))


# =================================================================================================
def selftest():
    f = []
    if IDENTITY != "adaptive_v0_2":
        f.append("this module is v0_2 and must say so")
    if "CLOSED" not in SUPERSEDES or "v0_1" not in SUPERSEDES:
        f.append("the supersession note must close v0_1 and claim no continuity")
    if W_FORM != 1.0 or W_SP != 0.05 or PRIOR_STRENGTH != 25 or FORM_DAYS != 30:
        f.append("the registered constants are policy, frozen at registration")

    # zero information -> the prior, exactly
    if abs(probability(0.5205, residual(("X"), ("Y"), {})) - 0.5205) > 1e-12:
        f.append("no form and no starters must return the prior untouched")
    # the residual is signed and antisymmetric in the teams
    form = {"AAA": 0.60, "BBB": 0.45}
    r1 = residual("AAA", "BBB", form)
    r2 = residual("BBB", "AAA", form)
    if abs(r1 + r2) > 1e-12:
        f.append("swapping the teams must flip the residual's sign")
    if r1 >= 0:
        f.append("the stronger AWAY team must produce a negative home residual")
    # the starter term points the right way: a better AWAY starter (lower rs) lowers p_home
    ra = residual("AAA", "BBB", {}, rs_away_sp=3.5, rs_home_sp=4.5)
    if ra >= 0:
        f.append("a better away starter must lower the home residual")
    if abs(ra - 0.05 * (3.5 - 4.5)) > 1e-12:
        f.append("the starter term is W_SP per run, exactly")
    # a missing starter pair contributes nothing rather than a guessed value
    if residual("AAA", "BBB", form, rs_away_sp=3.5, rs_home_sp=None) != r1:
        f.append("one missing starter must drop the starter term entirely")

    # shrinkage: a 30-day 6-3 team sits well inside raw 0.667
    ft, n = ({"T": (6 + 12.5) / (9 + 25)}, {"T": 9})
    if not (0.5 < ft["T"] < 0.667):
        f.append("shrinkage must pull a small-sample win rate toward 0.5")

    # form_table folds mixed name conventions and refuses non-canonical rows
    import tempfile, os as _os
    with tempfile.TemporaryDirectory() as td:
        p = _os.path.join(td, "r.csv")
        with open(p, "w") as fh:
            fh.write("date,status,result_status,source_tier,away,home,home_win\n")
            fh.write("2026-08-20,final,FINAL,1,Boston Red Sox,MIA,1\n")     # mixed conventions
            fh.write("2026-08-21,final,FINAL,1,BOS,Miami Marlins,0\n")
            fh.write("2026-08-21,final,PROVISIONAL,1,BOS,MIA,1\n")          # must be refused
            fh.write("2026-08-22,final,FINAL,3,BOS,MIA,1\n")                # tier 3: refused
            fh.write("2026-08-25,final,FINAL,1,BOS,MIA,0\n")                # slate day: refused
        ft2, n2 = form_table("2026-08-25", results_path=p)
        if n2.get("BOS") != 2 or n2.get("MIA") != 2:
            f.append(f"mixed name conventions must fold to one identity, got {n2}")
        # BOS is 2-0 in the two admissible rows (won as away in row 1, won as... check: row1 BOS
        # away @ MIA home, home_win=1 -> MIA won; row2 BOS away is wrong — recompute from fixture:
        # row1: away=Boston, home=MIA, home_win=1 -> MIA 1-0, BOS 0-1
        # row2: away=BOS, home=Miami, home_win=0 -> BOS 1-1, MIA 1-1
        # so BOS is 1-1 raw 0.5. That value cannot distinguish shrinkage from none, so the
        # DISTINGUISHING check is MIA-in-a-2-0-world below via a second table.
        if abs(ft2["BOS"] - (1 + 12.5) / (2 + 25)) > 1e-12:
            f.append("provisional, tier-3 and slate-day rows must not enter the form window")
        # a lopsided record where raw and shrunken DIFFER: 2-0 raw 1.0, shrunken 13.5/27
        p2 = _os.path.join(td, "r2.csv")
        with open(p2, "w") as fh:
            fh.write("date,status,result_status,source_tier,away,home,home_win\n")
            fh.write("2026-08-20,final,FINAL,1,BOS,MIA,0\n")
            fh.write("2026-08-21,final,FINAL,1,BOS,MIA,0\n")
        ft3, _n3 = form_table("2026-08-25", results_path=p2)
        if abs(ft3["BOS"] - (2 + 12.5) / (2 + 25)) > 1e-12:
            f.append(f"a 2-0 team must be SHRUNKEN to 14.5/27, got {ft3['BOS']}")
        if ft3["BOS"] >= 0.99:
            f.append("a 2-0 team at raw 1.0 means shrinkage is gone")

    print("adaptive_challenger selftest:", "OK" if not f else "FAIL")
    for x in f:
        print("   -", x)
    return not f


MUTANTS = [
    ("the prior offset is scaled along with the residual",
     '    z = math.log(prior_p / (1 - prior_p)) + residual_f',
     '    z = (math.log(prior_p / (1 - prior_p)) + residual_f) * 1.1'),
    ("provisional rows enter the form window",
     '        if not (r["status"] == "final" and r["result_status"] == "FINAL"',
     '        if not (r["status"] == "final"'),
    ("tier-3 rows enter the form window",
     'and r["source_tier"] == "1" and d0 <= r["date"] < slate_date):',
     'and d0 <= r["date"] < slate_date):'),
    ("the form window sees the slate date itself",
     'd0 <= r["date"] < slate_date):', 'd0 <= r["date"] <= slate_date):'),
    ("mixed name conventions stop being folded",
     '        aw, hm = _abbr(r["away"]), _abbr(r["home"])',
     '        aw, hm = r["away"], r["home"]'),
    ("shrinkage is dropped, so a 3-game team swings the residual",
     'return {t: (w[t] + PRIOR_STRENGTH / 2.0) / (n[t] + PRIOR_STRENGTH) for t in n}, n',
     'return {t: w[t] / n[t] for t in n}, n'),
    ("a missing starter pair invents a starter term",
     "    if rs_away_sp is not None and rs_home_sp is not None:", "    if True:"),
    ("the starter term flips direction",
     "        f += W_SP * (rs_away_sp - rs_home_sp)", "        f += W_SP * (rs_home_sp - rs_away_sp)"),
    ("an absent team is penalised instead of neutral",
     '    sh = form.get(home, 0.5)', '    sh = form.get(home, 0.3)'),
]


def mutation_suite():
    src = open(__file__).read()
    import io as _io, contextlib as _cl
    _b = _io.StringIO()
    with _cl.redirect_stdout(_b):
        _base = selftest()
    if not _base:
        print("  BASELINE_FAILING  the unmutated selftest does not pass")
        print(_b.getvalue().strip())
        return False
    body = src[:src.index("MUTANTS = [")]
    killed = 0
    for name, old, new in MUTANTS:
        if old not in src:
            print("  UNAPPLIED ", name + ": pattern not found")
            continue
        if old not in body:
            print("  SELF_TARGETED ", name + ": pattern occurs only inside the MUTANTS list")
            continue
        ns = {"__file__": __file__, "__name__": "mutant"}
        try:
            exec(compile(src.replace(old, new, 1), "<mutant>", "exec"), ns)
            ok = ns["selftest"]()
        except Exception:
            ok = False
        print(("  KILLED    " if not ok else "  SURVIVED  ") + name)
        killed += not ok
    print(f"mutation suite: {killed}/{len(MUTANTS)} killed"
          + ("" if killed == len(MUTANTS) else "  — SURVIVORS MEAN DECORATIVE FIXTURES"))
    return killed == len(MUTANTS)


if __name__ == "__main__":
    if "--mutants" in sys.argv:
        sys.exit(0 if mutation_suite() else 1)
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    print(__doc__)
