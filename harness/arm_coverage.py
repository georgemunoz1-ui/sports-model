#!/usr/bin/env python3
"""ARM COVERAGE — what fraction of the three-arm design a board actually delivered, per sport.

OWNER AMENDMENT 1 (2026-08-23): "Scope the three-arm claim correctly. Report arm coverage
explicitly: MLB 3/3, WNBA 3/3 challenger BASELINE_EQUIVALENT_NULL, NFL 1/3."

WHY A COUNT IS NOT ENOUGH. Three rows per game is a shape, not a design. Two failure modes both
render as a full table and neither is caught by counting arms:

  MISSING ARM.  NFL carried a baseline and nothing else. Calling that board "three-arm" because the
  MLB section was complete describes the best sport and attributes it to the slate.

  NULL CHALLENGER.  WNBA carried three rows per game, but the challenger's numbers were the
  baseline's numbers. An arm that is byte-identical to the arm it is supposed to beat contributes
  ZERO information about the challenger — every paired difference is exactly 0, so the comparison
  cannot come out any way but tied. That is a negative control. A negative control is a useful
  thing to run and a dishonest thing to count as challenger coverage.

AND IT IS PER ESTIMAND, NOT PER SPORT. The MLB board is the proof: on the WINNER estimand the
challenger genuinely differs from the baseline (cross-game SD 3.08pp, five sign flips), while on the
TOTAL estimand the baseline row carries the challenger's projected total in ALL FIFTEEN GAMES —
identical to the third decimal. The same board is therefore 3/3 on winner and a null challenger on
total. A sport-level verdict would have reported "MLB 3/3" and buried that.

WHAT THIS MODULE REFUSES TO DO. It will not upgrade a board to COMPLETE_THREE_ARM while any declared
sport is short an arm or any arm is baseline-equivalent on any graded estimand. There is no
threshold to tune and no partial credit: the claim is either true of every declared sport and every
declared estimand, or it is not made.

API
  coverage(rows, sports, estimands)  -> per-sport / per-estimand coverage record
  board_claim(cov)                   -> COMPLETE_THREE_ARM | PARTIAL_THREE_ARM_BOARD (+ reasons)
"""
from __future__ import annotations

MODULE_ID = "arm_coverage"

import json
import os
import sys

BASELINE, CHAMPION, CHALLENGER = "BASELINE", "CHAMPION", "CHALLENGER"
REQUIRED_ARMS = (BASELINE, CHAMPION, CHALLENGER)

# Estimand -> the row field that carries that arm's forecast for it.
DEFAULT_ESTIMANDS = {"winner": "p_home", "total": "projected_total"}

PRESENT = "PRESENT"
ABSENT = "ABSENT"
NULL_EQUIV = "BASELINE_EQUIVALENT_NULL"
UNPAIRED = "UNPAIRED_NO_COMMON_GAMES"
NO_FORECASTS = "PRESENT_BUT_NO_FORECASTS"

COMPLETE = "COMPLETE_THREE_ARM"
PARTIAL = "PARTIAL_THREE_ARM_BOARD"


def _num(x):
    """Strict numeric read. bool is not a number and a numeric string is not a number."""
    if x is None or isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def _by_arm(rows, sport):
    out = {}
    for r in rows:
        if r.get("sport") != sport:
            continue
        out.setdefault(r.get("arm"), {})[r.get("game")] = r
    return out


def arm_estimand_status(base_games, other_games, field):
    """Status of ONE arm against the baseline on ONE estimand.

    Returns (status, detail). Exact equality on EVERY commonly-covered game is the null verdict;
    anything else reports the largest absolute difference so a near-null is still visible.
    """
    if other_games is None:
        return ABSENT, {"n_paired": 0}
    common = sorted(set(base_games) & set(other_games))
    pairs = []
    for g in common:
        a, b = _num(base_games[g].get(field)), _num(other_games[g].get(field))
        if a is None or b is None:
            continue
        pairs.append((g, a, b))
    if not common:
        return UNPAIRED, {"n_paired": 0}
    if not pairs:
        return NO_FORECASTS, {"n_paired": 0, "n_common_games": len(common)}
    diffs = [abs(b - a) for _, a, b in pairs]
    detail = {"n_paired": len(pairs), "n_common_games": len(common),
              "max_abs_diff": max(diffs), "n_exactly_equal": sum(1 for d in diffs if d == 0.0)}
    if all(d == 0.0 for d in diffs):
        return NULL_EQUIV, detail
    return PRESENT, detail


def coverage(rows, sports, estimands=None):
    """Arm coverage for a board, by sport and by estimand.

    `sports` is DECLARED, not inferred from the rows: a sport that contributed no rows at all must
    still appear as 0/3 rather than vanishing from the denominator.
    """
    estimands = dict(estimands or DEFAULT_ESTIMANDS)
    per_sport = {}
    for sport in sports:
        by_arm = _by_arm(rows, sport)
        base = by_arm.get(BASELINE) or {}
        arms_present = [a for a in REQUIRED_ARMS if by_arm.get(a)]
        est = {}
        for name, field in sorted(estimands.items()):
            per_arm = {}
            for a in REQUIRED_ARMS:
                if not by_arm.get(a):
                    per_arm[a] = {"status": ABSENT, "n_paired": 0}
                    continue
                if a == BASELINE:
                    n = sum(1 for g in base if _num(base[g].get(field)) is not None)
                    per_arm[a] = {"status": PRESENT if n else NO_FORECASTS, "n_paired": n}
                    continue
                st, detail = arm_estimand_status(base, by_arm[a], field)
                per_arm[a] = dict(detail, status=st)
            informative = [a for a in REQUIRED_ARMS if per_arm[a]["status"] == PRESENT]
            est[name] = {
                "field": field,
                "per_arm": per_arm,
                "informative_arms": len(informative),
                "coverage": f"{len(informative)}/{len(REQUIRED_ARMS)}",
                "null_arms": [a for a in REQUIRED_ARMS if per_arm[a]["status"] == NULL_EQUIV],
                "absent_arms": [a for a in REQUIRED_ARMS if per_arm[a]["status"] == ABSENT],
            }
        per_sport[sport] = {
            "arms_with_rows": arms_present,
            "row_coverage": f"{len(arms_present)}/{len(REQUIRED_ARMS)}",
            "n_games": len(base) or max([len(v) for v in by_arm.values()] or [0]),
            "estimands": est,
        }
    return {"sports": list(sports), "estimands": estimands, "per_sport": per_sport}


def board_claim(cov):
    """COMPLETE_THREE_ARM only when every declared sport is 3/3 on every declared estimand."""
    reasons = []
    for sport, s in sorted(cov["per_sport"].items()):
        for name, e in sorted(s["estimands"].items()):
            for a in e["absent_arms"]:
                reasons.append(f"{sport}:{name}: {a} {ABSENT}")
            for a in e["null_arms"]:
                reasons.append(f"{sport}:{name}: {a} {NULL_EQUIV}")
            for a in REQUIRED_ARMS:
                st = e["per_arm"][a]["status"]
                if st in (UNPAIRED, NO_FORECASTS):
                    reasons.append(f"{sport}:{name}: {a} {st}")
    claim = COMPLETE if not reasons else PARTIAL
    return {"claim": claim, "reasons": sorted(set(reasons)),
            "note": "A negative control is not challenger coverage; a missing arm is not a short arm."}


def render_lines(cov):
    """One line per sport/estimand, for the report layer. Status tokens are never abbreviated."""
    out = []
    for sport, s in sorted(cov["per_sport"].items()):
        for name, e in sorted(s["estimands"].items()):
            tags = []
            for a in REQUIRED_ARMS:
                st = e["per_arm"][a]["status"]
                if st != PRESENT:
                    tags.append(f"{a}={st}")
            out.append(f"{sport}:{name}: {e['coverage']}" + (("  " + "  ".join(tags)) if tags else ""))
    return out


# =================================================================================================
def _row(sport, arm, game, p=None, tot=None):
    return {"sport": sport, "arm": arm, "game": game, "p_home": p, "projected_total": tot}


def selftest():
    f = []

    # --- the 8/23 board, reproduced in miniature -------------------------------------------------
    rows = []
    for g, pb, pch, pcl, tb, tch in [("A@B", .5252, .58, .616, 8.44, 8.5),
                                     ("C@D", .5252, .461, .431, 9.10, 9.5)]:
        rows.append(_row("mlb", BASELINE, g, pb, tb))
        rows.append(_row("mlb", CHALLENGER, g, pch, tb))    # total copied from baseline
        rows.append(_row("mlb", CHAMPION, g, pcl, tch))
    for g in ("E@F", "G@H"):
        rows.append(_row("wnba", BASELINE, g, .60, 160.0))
        rows.append(_row("wnba", CHALLENGER, g, .60, 160.0))   # null challenger, both estimands
        rows.append(_row("wnba", CHAMPION, g, .64, 162.0))
    rows.append(_row("nfl", BASELINE, "I@J", .52, 38.0))

    cov = coverage(rows, ["mlb", "wnba", "nfl"])
    mlb = cov["per_sport"]["mlb"]["estimands"]
    if mlb["winner"]["coverage"] != "3/3":
        f.append(f"mlb winner should be 3/3, got {mlb['winner']['coverage']}")
    if mlb["total"]["null_arms"] != [CHALLENGER]:
        f.append(f"mlb total challenger should be null-equivalent, got {mlb['total']['null_arms']}")
    if mlb["total"]["coverage"] != "2/3":
        f.append(f"mlb total should be 2/3, got {mlb['total']['coverage']}")
    wn = cov["per_sport"]["wnba"]["estimands"]
    if wn["winner"]["null_arms"] != [CHALLENGER]:
        f.append("wnba winner challenger should be BASELINE_EQUIVALENT_NULL")
    nf = cov["per_sport"]["nfl"]["estimands"]
    if nf["winner"]["coverage"] != "1/3":
        f.append(f"nfl should be 1/3, got {nf['winner']['coverage']}")
    if sorted(nf["winner"]["absent_arms"]) != [CHALLENGER, CHAMPION]:
        f.append("nfl should report champion and challenger absent")

    claim = board_claim(cov)
    if claim["claim"] != PARTIAL:
        f.append("a board with a missing arm and a null arm must not claim COMPLETE_THREE_ARM")
    if not any("wnba:winner" in r and NULL_EQUIV in r for r in claim["reasons"]):
        f.append("the null challenger must appear in the claim's reasons")
    if not any("nfl:winner" in r and ABSENT in r for r in claim["reasons"]):
        f.append("the absent NFL arms must appear in the claim's reasons")

    # --- a genuinely complete board does claim COMPLETE -----------------------------------------
    good = [_row("mlb", BASELINE, "A@B", .52, 8.4), _row("mlb", CHAMPION, "A@B", .60, 8.9),
            _row("mlb", CHALLENGER, "A@B", .55, 8.7)]
    gc = board_claim(coverage(good, ["mlb"]))
    if gc["claim"] != COMPLETE:
        f.append(f"a complete board should claim COMPLETE_THREE_ARM, got {gc['reasons']}")

    # --- ONE differing game is enough to defeat the null verdict --------------------------------
    near = [_row("mlb", BASELINE, "A@B", .52, 8.4), _row("mlb", BASELINE, "C@D", .52, 9.0),
            _row("mlb", CHAMPION, "A@B", .60, 8.9), _row("mlb", CHAMPION, "C@D", .61, 9.1),
            _row("mlb", CHALLENGER, "A@B", .52, 8.4), _row("mlb", CHALLENGER, "C@D", .5200001, 9.0)]
    nw = coverage(near, ["mlb"])["per_sport"]["mlb"]["estimands"]["winner"]
    if nw["per_arm"][CHALLENGER]["status"] != PRESENT:
        f.append("a challenger differing on one game is not baseline-equivalent")
    if nw["per_arm"][CHALLENGER]["max_abs_diff"] <= 0:
        f.append("max_abs_diff must be reported and positive when the arms differ")

    # --- no common games is UNPAIRED, not identical ---------------------------------------------
    up = [_row("mlb", BASELINE, "A@B", .52, 8.4), _row("mlb", CHAMPION, "A@B", .60, 8.9),
          _row("mlb", CHALLENGER, "Z@Y", .52, 8.4)]
    us = coverage(up, ["mlb"])["per_sport"]["mlb"]["estimands"]["winner"]["per_arm"][CHALLENGER]
    if us["status"] != UNPAIRED:
        f.append(f"disjoint games must be UNPAIRED, got {us['status']}")

    # --- a declared sport with no rows at all is still counted ----------------------------------
    dc = coverage(good, ["mlb", "nhl"])
    if "nhl" not in dc["per_sport"]:
        f.append("a declared sport with no rows must still appear")
    elif dc["per_sport"]["nhl"]["estimands"]["winner"]["coverage"] != "0/3":
        f.append("a sport with no rows is 0/3")

    # --- an arm present but carrying no numbers is not coverage ---------------------------------
    empty = [_row("mlb", BASELINE, "A@B", .52, 8.4), _row("mlb", CHAMPION, "A@B", .60, 8.9),
             _row("mlb", CHALLENGER, "A@B", None, None)]
    es = coverage(empty, ["mlb"])["per_sport"]["mlb"]["estimands"]["winner"]["per_arm"][CHALLENGER]
    if es["status"] != NO_FORECASTS:
        f.append(f"an arm with no forecasts is not PRESENT, got {es['status']}")

    # --- a baseline arm carrying no numbers is not coverage either -------------------------------
    nob = [_row("mlb", BASELINE, "A@B", None, None), _row("mlb", CHAMPION, "A@B", .60, 8.9),
           _row("mlb", CHALLENGER, "A@B", .55, 8.7)]
    nb = coverage(nob, ["mlb"])["per_sport"]["mlb"]["estimands"]["winner"]["per_arm"][BASELINE]
    if nb["status"] != NO_FORECASTS:
        f.append(f"a baseline with no forecasts is not PRESENT, got {nb['status']}")

    # --- a string probability is not a number ---------------------------------------------------
    if _num("0.52") is not None or _num(True) is not None:
        f.append("_num must refuse strings and bools")

    # --- render never abbreviates a status token ------------------------------------------------
    lines = render_lines(cov)
    if not any(NULL_EQUIV in l for l in lines):
        f.append("render must carry the full status token")

    for x in f:
        print("FAIL:", x)
    if not f:
        print("arm_coverage selftest: OK")
    return f


MUTANTS = [
    ("a missing arm counts toward coverage anyway",
     '                    per_arm[a] = {"status": ABSENT, "n_paired": 0}',
     '                    per_arm[a] = {"status": PRESENT, "n_paired": 0}'),
    ("baseline-equivalence stops being detected",
     "    if all(d == 0.0 for d in diffs):", "    if False:"),
    ("baseline-equivalence becomes approximate, so a real challenger is called null",
     "    if all(d == 0.0 for d in diffs):", "    if all(d < 0.10 for d in diffs):"),
    ("a null arm still counts as informative coverage",
     '            informative = [a for a in REQUIRED_ARMS if per_arm[a]["status"] == PRESENT]',
     '            informative = [a for a in REQUIRED_ARMS if per_arm[a]["status"] != ABSENT]'),
    ("null arms stop blocking the COMPLETE claim",
     '            for a in e["null_arms"]:\n                reasons.append(f"{sport}:{name}: {a} {NULL_EQUIV}")',
     '            for a in []:\n                reasons.append(f"{sport}:{name}: {a} {NULL_EQUIV}")'),
    ("absent arms stop blocking the COMPLETE claim",
     '            for a in e["absent_arms"]:\n                reasons.append(f"{sport}:{name}: {a} {ABSENT}")',
     '            for a in []:\n                reasons.append(f"{sport}:{name}: {a} {ABSENT}")'),
    ("the claim is made whenever anything is complete",
     "    claim = COMPLETE if not reasons else PARTIAL",
     "    claim = COMPLETE if len(reasons) < 99 else PARTIAL"),
    ("disjoint game sets are reported as agreement",
     "    if not common:\n        return UNPAIRED, {\"n_paired\": 0}",
     "    if False:\n        return UNPAIRED, {\"n_paired\": 0}"),
    ("an arm with no numbers is treated as covered",
     '        return NO_FORECASTS, {"n_paired": 0, "n_common_games": len(common)}',
     '        return PRESENT, {"n_paired": 0, "n_common_games": len(common)}'),
    ("coverage is inferred from the rows instead of the declared sport list",
     "    for sport in sports:", "    for sport in sorted({r.get('sport') for r in rows} & set(sports)):"),
    ("the estimand loop collapses to the winner only",
     "        for name, field in sorted(estimands.items()):",
     "        for name, field in [('winner', 'p_home')]:"),
    ("a numeric string passes as a forecast",
     "    if x is None or isinstance(x, bool) or not isinstance(x, (int, float)):",
     "    if x is None:"),
    ("the baseline arm is exempted from the empty check",
     '                    per_arm[a] = {"status": PRESENT if n else NO_FORECASTS, "n_paired": n}',
     '                    per_arm[a] = {"status": PRESENT, "n_paired": n}'),
    ("max_abs_diff stops being reported so near-nulls become invisible",
     '              "max_abs_diff": max(diffs), "n_exactly_equal": sum(1 for d in diffs if d == 0.0)}',
     '              "n_exactly_equal": sum(1 for d in diffs if d == 0.0)}'),
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
