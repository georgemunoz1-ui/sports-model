#!/usr/bin/env python3
"""TOTALS ESTIMAND — how a run-total forecast is graded, and the three ways it must not be.

OWNER AMENDMENTS 2 AND 3 (2026-08-23).

  2. "Do not grade an arm's total against its own rounded projection as an O/U result. That is
     self-referential. Grade: projected total versus actual (MAE, RMSE, signed error); full
     simulated distribution versus actual (log score or CRPS); market O/U only when an
     independently captured market line exists."

  3. "Add a real total baseline. The table displays champion and challenger totals but no baseline
     total. Use an expanding league scoring prior, optionally adjusted only for park/venue."

THE SELF-REFERENTIAL DEFECT, CONCRETELY. The 2026-08-23 card set each arm's line to
floor(mu)+0.5 from that arm's OWN mean and then reported p_over / p_under against it. Every arm
therefore scores about 50/50 by construction, an over/under "record" near .500 is guaranteed
regardless of accuracy, and a model that projects every game at 30 runs looks exactly as calibrated
as one that projects the truth. The card labelled this MODEL_FAIR_LINE_NOT_MARKET, which is honest
about the input and still produces a number that cannot mean what an O/U record means. Labelling a
self-referential statistic does not make it an estimand. This module REFUSES it.

WHY A BASELINE TOTAL IS NOT OPTIONAL. Without one there is no skill denominator, and "MAE 2.39" is
unreadable — the league's own scoring mean posted MAE 2.6 over the same window, so most of that
looked like model accuracy and was arithmetic on the league mean. Worse, on the 8/23 card the
baseline row did not merely lack a total: it CARRIED THE CHALLENGER'S TOTAL, identical to the third
decimal in all fifteen games. A baseline whose numbers are the candidate's numbers cannot lose.

THE BANNED MEAN survives from totals_eval: no error block reports a mean without its median, its
SIGNED bias and its largest miss. A mean absolute error travelling alone hides the shape of the miss
and hides direction entirely — a model 2.0 high on every game and one splitting +2/-2 report the
same MAE and are not the same model.

R1. A game with no actual total is EXCLUDED WITH A REASON and counted, never dropped silently and
never filled in. A distributional score with no distribution supplied is null plus a reason — a
point projection is not a distribution and this module will not manufacture one from it.

API
  expanding_total_prior(finals, cutoff_date, park_factor=None) -> the baseline total arm
  point_error(rows)                                            -> MAE/RMSE/signed/median/largest
  distribution_scores(rows)                                    -> log score + CRPS
  market_ou(rows)                                              -> graded only on an independent line
  evaluate(rows, ...)                                          -> all three, plus refusals
"""
from __future__ import annotations

MODULE_ID = "totals_estimand"

import json
import math
import os
import sys

# --- estimand names -----------------------------------------------------------------------------
POINT = "TOTAL_POINT_ERROR_VS_ACTUAL"
DIST = "TOTAL_DISTRIBUTION_VS_ACTUAL"
MARKET = "TOTAL_MARKET_OVER_UNDER"

# --- refusal / exclusion codes ------------------------------------------------------------------
SELF_REFERENTIAL = "REFUSED_SELF_REFERENTIAL_OWN_FAIR_LINE"
NO_INDEPENDENT_LINE = "MARKET_OU_UNAVAILABLE_NO_INDEPENDENT_LINE"
LINE_NOT_PREGAME = "MARKET_LINE_CAPTURED_AT_OR_AFTER_START"
NO_ACTUAL = "EXCLUDED_NO_ACTUAL_TOTAL"
NO_DISTRIBUTION = "EXCLUDED_NO_SIMULATED_DISTRIBUTION"
HALF_LINE_PUSH = "STRUCTURAL_HALF_LINE_CARRIES_PUSH_MASS"
PRIOR_LEAK = "PRIOR_POOL_CONTAINS_CUTOFF_OR_LATER_GAME"
UNDERPOWERED_N = 30

# The only line provenance that makes an over/under record mean anything.
INDEPENDENT_LINE_SOURCES = ("MARKET_CAPTURE_SINGLE_BOOK", "MARKET_CAPTURE_OWNER_SUPPLIED_BOARD")


class TotalsStructuralError(Exception):
    pass


def _num(x):
    if x is None or isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


# =================================================================================================
# 3. THE BASELINE TOTAL ARM
# =================================================================================================
def expanding_total_prior(finals, cutoff_date, park_factor=None):
    """Expanding league scoring prior: the mean total of every tier-1 final STRICTLY BEFORE cutoff.

    finals: [{"date": "YYYY-MM-DD", "total": float}, ...]
    park_factor: optional multiplicative venue adjustment. It is the ONLY adjustment permitted here
        — no team, no starter, no form. A baseline that knows about the teams is not a baseline.

    A pool containing a game dated on or after the cutoff is a leak and raises, rather than being
    filtered quietly: silently dropping the offending rows would let a caller keep a leaking pool
    and never learn of it.
    """
    pool = []
    for g in finals:
        d, t = g.get("date"), _num(g.get("total"))
        if d is None or t is None:
            continue
        if str(d) >= str(cutoff_date):
            raise TotalsStructuralError(f"{PRIOR_LEAK}: {d} >= cutoff {cutoff_date}")
        pool.append(t)
    if not pool:
        return {"model_id": "mlb.expanding_total_prior.league_mean", "n": 0,
                "projected_total": None, "reason": "NO_PRIOR_GAMES_BEFORE_CUTOFF",
                "park_factor": park_factor, "cutoff_date": cutoff_date}
    mean = sum(pool) / len(pool)
    sd = math.sqrt(sum((t - mean) ** 2 for t in pool) / (len(pool) - 1)) if len(pool) > 1 else None
    pf = _num(park_factor)
    return {
        "model_id": "mlb.expanding_total_prior.league_mean",
        "n": len(pool),
        "cutoff_date": cutoff_date,
        "league_mean_total": mean,
        "park_factor": pf,
        "park_adjustment_applied": pf is not None,
        "projected_total": mean * pf if pf is not None else mean,
        "prior_sd_runs": sd,
        "uncertainty_kind": "PRIOR_POOL_SD_RUNS",
        "inputs_used": ["tier1_final_totals_before_cutoff"] + (["park_factor"] if pf is not None else []),
        "inputs_forbidden": ["team", "starter", "lineup", "form", "market"],
    }


# =================================================================================================
# 2a. POINT ERROR
# =================================================================================================
def point_error(rows, pred_key="projected_total", actual_key="actual_total"):
    """MAE, RMSE, signed bias, median and largest miss — always together (BANNED MEAN)."""
    errs, excluded = [], []
    for r in rows:
        p, a = _num(r.get(pred_key)), _num(r.get(actual_key))
        if a is None:
            excluded.append({"game": r.get("game"), "reason": NO_ACTUAL})
            continue
        if p is None:
            excluded.append({"game": r.get("game"), "reason": "EXCLUDED_NO_PROJECTION"})
            continue
        errs.append(p - a)
    n = len(errs)
    if n == 0:
        return {"estimand": POINT, "n": 0, "mae": None, "rmse": None, "signed_bias": None,
                "median_abs_error": None, "largest_miss": None, "reason": "NO_GRADEABLE_ROWS",
                "excluded": excluded, "underpowered": True}
    absx = sorted(abs(e) for e in errs)
    mid = absx[n // 2] if n % 2 else (absx[n // 2 - 1] + absx[n // 2]) / 2.0
    worst = max(errs, key=abs)
    return {
        "estimand": POINT,
        "n": n,
        "mae": sum(absx) / n,
        "rmse": math.sqrt(sum(e * e for e in errs) / n),
        "signed_bias": sum(errs) / n,
        "median_abs_error": mid,
        "largest_miss": worst,
        "excluded": excluded,
        "underpowered": n < UNDERPOWERED_N,
    }


def banned_mean_gate(node, path="root"):
    """Walk a finished report and refuse any node reporting a mean without its companions."""
    bad = []
    if isinstance(node, dict):
        if "mae" in node:
            for companion in ("median_abs_error", "signed_bias", "largest_miss", "n"):
                if companion not in node:
                    bad.append(f"{path}: mae without {companion}")
        if "log_score" in node and "n_zero_mass" not in node:
            bad.append(f"{path}: log_score without n_zero_mass")
        for k, v in node.items():
            bad += banned_mean_gate(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            bad += banned_mean_gate(v, f"{path}[{i}]")
    return bad


# =================================================================================================
# 2b. DISTRIBUTIONAL SCORES
# =================================================================================================
def _pmf(dist):
    """{total: probability} from a caller-supplied distribution; refuses a non-distribution."""
    if not isinstance(dist, dict) or not dist:
        return None
    out = {}
    for k, v in dist.items():
        kk = _num(k) if not isinstance(k, str) else _num(float(k)) if k.strip() else None
        p = _num(v)
        if kk is None or p is None or p < 0:
            return None
        out[int(round(kk))] = out.get(int(round(kk)), 0.0) + p
    s = sum(out.values())
    if not (0.98 <= s <= 1.02):
        return None
    return {k: v / s for k, v in out.items()}


def crps_discrete(pmf, y):
    """CRPS for an integer-supported forecast: sum_k (F(k) - 1[y <= k])^2 over the support hull."""
    ks = sorted(set(list(pmf) + [int(round(y))]))
    lo, hi = min(ks), max(ks)
    total, cum = 0.0, 0.0
    for k in range(lo, hi + 1):
        cum += pmf.get(k, 0.0)
        total += (cum - (1.0 if y <= k else 0.0)) ** 2
    return total


def distribution_scores(rows, dist_key="total_distribution", actual_key="actual_total"):
    """Log score and CRPS against the FULL simulated distribution. No distribution, no score."""
    logs, crpss, excluded, zero_mass = [], [], [], []
    for r in rows:
        a = _num(r.get(actual_key))
        if a is None:
            excluded.append({"game": r.get("game"), "reason": NO_ACTUAL})
            continue
        pmf = _pmf(r.get(dist_key))
        if pmf is None:
            excluded.append({"game": r.get("game"), "reason": NO_DISTRIBUTION})
            continue
        y = int(round(a))
        p = pmf.get(y, 0.0)
        if p > 0:
            logs.append(-math.log(p))
        else:
            zero_mass.append(r.get("game"))
        crpss.append(crps_discrete(pmf, y))
    return {
        "estimand": DIST,
        "n": len(crpss),
        "n_scored_log": len(logs),
        "n_zero_mass": len(zero_mass),
        "zero_mass_games": zero_mass,
        "log_score": (sum(logs) / len(logs)) if logs else None,
        "log_score_note": "mean over rows with positive mass on the outcome; n_zero_mass counts the "
                          "rows the model called impossible and is reported beside it, never netted in",
        "crps": (sum(crpss) / len(crpss)) if crpss else None,
        "excluded": excluded,
        "underpowered": len(crpss) < UNDERPOWERED_N,
    }


# =================================================================================================
# 2c. MARKET OVER/UNDER — only on an independently captured line
# =================================================================================================
def line_is_independent(row):
    """(ok, reason). The line must come from a market capture taken before the game started."""
    src = row.get("line_source")
    if src not in INDEPENDENT_LINE_SOURCES:
        return False, SELF_REFERENTIAL if src in (None, "MODEL_FAIR_LINE", "OWN_FAIR_LINE") \
            else NO_INDEPENDENT_LINE
    cap, start = row.get("line_captured_at_utc"), row.get("game_start_utc")
    if cap is None or start is None or str(cap) >= str(start):
        return False, LINE_NOT_PREGAME
    return True, None


def market_ou(rows):
    """Over/under record, computed ONLY on rows whose line is an independent pregame capture."""
    graded, refused = [], []
    for r in rows:
        ok, why = line_is_independent(r)
        if not ok:
            refused.append({"game": r.get("game"), "reason": why})
            continue
        line, a = _num(r.get("line")), _num(r.get("actual_total"))
        if a is None:
            refused.append({"game": r.get("game"), "reason": NO_ACTUAL})
            continue
        if line is None:
            refused.append({"game": r.get("game"), "reason": NO_INDEPENDENT_LINE})
            continue
        whole = float(line).is_integer()
        push_mass = _num(r.get("p_push")) or 0.0
        if not whole and push_mass > 0:
            raise TotalsStructuralError(f"{HALF_LINE_PUSH}: {r.get('game')} line {line} p_push {push_mass}")
        side = r.get("total_side")
        if a == line:
            result = "PUSH"
        elif (a > line) == (side == "OVER"):
            result = "WIN"
        else:
            result = "LOSS"
        graded.append({"game": r.get("game"), "line": line, "whole_line": whole,
                       "side": side, "actual": a, "result": result})
    def _sub(sel):
        rs = [g for g in graded if sel(g)]
        w = sum(1 for g in rs if g["result"] == "WIN")
        l = sum(1 for g in rs if g["result"] == "LOSS")
        p = sum(1 for g in rs if g["result"] == "PUSH")
        return {"n": len(rs), "win": w, "loss": l, "push": p,
                "rate": (w / (w + l)) if (w + l) else None,
                "underpowered": len(rs) < UNDERPOWERED_N}
    return {
        "estimand": MARKET,
        "n_graded": len(graded),
        "n_refused": len(refused),
        "refused": refused,
        # whole and half lines settle in different spaces; pooling them makes the rate uninterpretable
        "whole_line": _sub(lambda g: g["whole_line"]),
        "half_line": _sub(lambda g: not g["whole_line"]),
        "status": "GRADED" if graded else NO_INDEPENDENT_LINE,
    }


# =================================================================================================
def evaluate(rows):
    rep = {
        "point": point_error(rows),
        "distribution": distribution_scores(rows),
        "market": market_ou(rows),
        "estimand_note": "An arm's own fair line is not an estimand. Over/under is graded against an "
                         "independently captured market line or it is not graded.",
    }
    bad = banned_mean_gate(rep)
    if bad:
        raise TotalsStructuralError("BANNED_MEAN: " + "; ".join(bad))
    return rep


# =================================================================================================
def selftest():
    f = []

    # --- baseline total arm ----------------------------------------------------------------------
    finals = [{"date": "2026-08-20", "total": 9.0}, {"date": "2026-08-21", "total": 7.0},
              {"date": "2026-08-22", "total": 8.0}]
    b = expanding_total_prior(finals, "2026-08-23")
    if abs(b["projected_total"] - 8.0) > 1e-12:
        f.append(f"expanding prior should be the league mean 8.0, got {b['projected_total']}")
    if b["park_adjustment_applied"]:
        f.append("no park factor was supplied, so none may be reported as applied")
    bp = expanding_total_prior(finals, "2026-08-23", park_factor=1.10)
    if abs(bp["projected_total"] - 8.8) > 1e-12:
        f.append(f"park factor must multiply the prior mean, got {bp['projected_total']}")
    try:
        expanding_total_prior(finals + [{"date": "2026-08-23", "total": 12.0}], "2026-08-23")
        f.append("a same-day game in the prior pool must raise, not be filtered away")
    except TotalsStructuralError:
        pass
    if expanding_total_prior([], "2026-08-23")["projected_total"] is not None:
        f.append("an empty pool must return null plus a reason, never a zero")

    # --- point error: the banned mean and the direction of the miss ------------------------------
    rows = [{"game": "A@B", "projected_total": 9.0, "actual_total": 7.0},
            {"game": "C@D", "projected_total": 8.0, "actual_total": 9.0},
            {"game": "E@F", "projected_total": 10.0, "actual_total": 10.0}]
    pe = point_error(rows)
    if pe["n"] != 3 or abs(pe["mae"] - 1.0) > 1e-12:
        f.append(f"MAE should be 1.0 over 3 rows, got {pe['n']} {pe['mae']}")
    if abs(pe["signed_bias"] - (1.0 / 3.0)) > 1e-12:
        f.append(f"signed bias should be +1/3, got {pe['signed_bias']}")
    if abs(pe["rmse"] - math.sqrt(5.0 / 3.0)) > 1e-12:
        f.append(f"RMSE should be sqrt(5/3), got {pe['rmse']}")
    if pe["largest_miss"] != 2.0:
        f.append(f"largest miss should keep its sign, got {pe['largest_miss']}")
    # the worst miss is graded on magnitude but REPORTED with its sign: a model 4 runs LOW is not
    # the same finding as one 4 runs high, and abs() would render them identically.
    low = point_error([{"game": "A@B", "projected_total": 5.0, "actual_total": 9.0},
                       {"game": "C@D", "projected_total": 9.0, "actual_total": 8.0}])
    if low["largest_miss"] != -4.0:
        f.append(f"largest miss must stay negative when the model was low, got {low['largest_miss']}")
    if not pe["underpowered"]:
        f.append("3 rows must be marked underpowered")
    # a symmetric-error model and a biased one must NOT report the same block
    biased = [{"game": "A@B", "projected_total": 9.0, "actual_total": 7.0},
              {"game": "C@D", "projected_total": 11.0, "actual_total": 9.0}]
    sym = [{"game": "A@B", "projected_total": 9.0, "actual_total": 7.0},
           {"game": "C@D", "projected_total": 7.0, "actual_total": 9.0}]
    if point_error(biased)["mae"] != point_error(sym)["mae"]:
        f.append("fixture is wrong: the two models should share an MAE")
    if point_error(biased)["signed_bias"] == point_error(sym)["signed_bias"]:
        f.append("signed bias must separate a biased model from a symmetric one")

    # --- R1: a missing actual is excluded with a reason, not dropped -----------------------------
    miss = point_error(rows + [{"game": "G@H", "projected_total": 9.0, "actual_total": None}])
    if miss["n"] != 3 or not any(x["reason"] == NO_ACTUAL for x in miss["excluded"]):
        f.append("a row with no actual must be excluded WITH a reason and counted")

    # --- distributional scores -------------------------------------------------------------------
    d = {7: 0.2, 8: 0.5, 9: 0.3}
    ds = distribution_scores([{"game": "A@B", "total_distribution": d, "actual_total": 8}])
    if abs(ds["log_score"] - (-math.log(0.5))) > 1e-12:
        f.append(f"log score should be -log(.5), got {ds['log_score']}")
    # CRPS by hand: F(7)=.2, F(8)=.7, F(9)=1.0 ; y=8 -> (.2-0)^2 + (.7-1)^2 + (1-1)^2 = .13
    if abs(ds["crps"] - 0.13) > 1e-12:
        f.append(f"CRPS should be 0.13, got {ds['crps']}")
    # a sharper correct forecast must score better than a diffuse one on both scores
    sharp = distribution_scores([{"game": "A@B", "total_distribution": {8: 0.9, 9: 0.1}, "actual_total": 8}])
    if not (sharp["log_score"] < ds["log_score"] and sharp["crps"] < ds["crps"]):
        f.append("a sharper correct forecast must beat a diffuse one on log score AND CRPS")
    # a confident WRONG forecast must be punished by both
    wrong = distribution_scores([{"game": "A@B", "total_distribution": {8: 0.9, 9: 0.1}, "actual_total": 9}])
    if not (wrong["log_score"] > ds["log_score"] and wrong["crps"] > ds["crps"]):
        f.append("a confident wrong forecast must be punished on log score AND CRPS")
    # zero mass on the outcome is counted, never netted away
    zm = distribution_scores([{"game": "A@B", "total_distribution": {8: 1.0}, "actual_total": 12}])
    if zm["n_zero_mass"] != 1 or zm["log_score"] is not None:
        f.append("a zero-mass outcome must be counted and must not produce a log score")
    if zm["crps"] is None or zm["crps"] <= 0:
        f.append("CRPS is still defined when the outcome had zero mass")
    # a point projection is not a distribution
    nod = distribution_scores([{"game": "A@B", "projected_total": 8.0, "actual_total": 8}])
    if nod["n"] != 0 or not any(x["reason"] == NO_DISTRIBUTION for x in nod["excluded"]):
        f.append("no distribution supplied must exclude with a reason, not synthesise one")
    if _pmf({8: 0.3, 9: 0.3}) is not None:
        f.append("a pmf that does not sum to 1 must be refused")

    # --- market O/U: the self-referential refusal ------------------------------------------------
    own = [{"game": "A@B", "line": 8.5, "line_source": "MODEL_FAIR_LINE", "total_side": "UNDER",
            "actual_total": 7, "game_start_utc": "2026-08-23T17:35:00Z"}]
    m = market_ou(own)
    if m["n_graded"] != 0 or m["refused"][0]["reason"] != SELF_REFERENTIAL:
        f.append(f"an arm's own fair line must be refused as self-referential, got {m['refused']}")
    if m["status"] != NO_INDEPENDENT_LINE:
        f.append("with nothing graded the market block must say so")
    good = [{"game": "A@B", "line": 8.5, "line_source": "MARKET_CAPTURE_SINGLE_BOOK",
             "line_captured_at_utc": "2026-08-23T15:00:00Z", "game_start_utc": "2026-08-23T17:35:00Z",
             "total_side": "UNDER", "actual_total": 7},
            {"game": "C@D", "line": 9.0, "line_source": "MARKET_CAPTURE_SINGLE_BOOK",
             "line_captured_at_utc": "2026-08-23T15:00:00Z", "game_start_utc": "2026-08-23T18:05:00Z",
             "total_side": "OVER", "actual_total": 9}]
    g = market_ou(good)
    if g["half_line"]["win"] != 1 or g["whole_line"]["push"] != 1:
        f.append(f"half/whole lines must settle in separate subgroups, got {g}")
    if g["whole_line"]["n"] != 1 or g["half_line"]["n"] != 1:
        f.append("whole and half lines must not be pooled")
    late = [dict(good[0], line_captured_at_utc="2026-08-23T18:00:00Z")]
    if market_ou(late)["refused"][0]["reason"] != LINE_NOT_PREGAME:
        f.append("a line captured after first pitch is not a pregame line")
    try:
        market_ou([dict(good[0], p_push=0.02)])
        f.append("push mass on a half line must raise")
    except TotalsStructuralError:
        pass

    # --- the banned-mean gate actually bites -----------------------------------------------------
    if not banned_mean_gate({"mae": 1.0, "n": 3}):
        f.append("a bare MAE must be caught by the banned-mean gate")
    if not banned_mean_gate({"by_sport": {"mlb": {"mae": 1.0, "n": 3}}}):
        f.append("the banned-mean gate must recurse into nested nodes")
    if not banned_mean_gate({"arms": [{"mae": 1.0, "n": 3}]}):
        f.append("the banned-mean gate must recurse into lists")
    if banned_mean_gate(point_error(rows)):
        f.append("a real point-error block must pass its own gate")
    if not banned_mean_gate({"log_score": 1.0}):
        f.append("a log score without n_zero_mass must be caught")

    # --- end to end ------------------------------------------------------------------------------
    rep = evaluate([dict(good[0], projected_total=8.2, total_distribution={7: .3, 8: .4, 9: .3})])
    if rep["point"]["n"] != 1 or rep["market"]["n_graded"] != 1 or rep["distribution"]["n"] != 1:
        f.append("evaluate must run all three estimands")

    for x in f:
        print("FAIL:", x)
    if not f:
        print("totals_estimand selftest: OK")
    return f


MUTANTS = [
    ("an arm's own fair line is accepted as a market line",
     "    if src not in INDEPENDENT_LINE_SOURCES:", "    if False:"),
    ("the fair-line refusal is downgraded to a generic unavailable",
     '        return False, SELF_REFERENTIAL if src in (None, "MODEL_FAIR_LINE", "OWN_FAIR_LINE") \\\n            else NO_INDEPENDENT_LINE',
     "        return False, NO_INDEPENDENT_LINE"),
    ("a line captured after first pitch counts as pregame",
     "    if cap is None or start is None or str(cap) >= str(start):", "    if False:"),
    ("signed bias loses its sign, so a biased model reads as symmetric",
     '        "signed_bias": sum(errs) / n,', '        "signed_bias": sum(abs(e) for e in errs) / n,'),
    ("RMSE is computed as MAE, so large misses stop being penalised",
     '        "rmse": math.sqrt(sum(e * e for e in errs) / n),', '        "rmse": sum(absx) / n,'),
    ("the largest miss loses its sign",
     '    worst = max(errs, key=abs)', '    worst = max(abs(e) for e in errs)'),
    ("a missing actual is dropped silently instead of excluded with a reason",
     '            excluded.append({"game": r.get("game"), "reason": NO_ACTUAL})\n            continue\n        if p is None:',
     '            continue\n        if p is None:'),
    ("the CRPS indicator is off by one",
     "        total += (cum - (1.0 if y <= k else 0.0)) ** 2", "        total += (cum - (1.0 if y < k else 0.0)) ** 2"),
    ("CRPS drops the squaring, so it stops being a proper score",
     "        total += (cum - (1.0 if y <= k else 0.0)) ** 2", "        total += abs(cum - (1.0 if y <= k else 0.0))"),
    ("a zero-mass outcome is silently skipped instead of counted",
     "        else:\n            zero_mass.append(r.get(\"game\"))", "        else:\n            pass"),
    ("a point projection is accepted in place of a distribution",
     "        if pmf is None:\n            excluded.append({\"game\": r.get(\"game\"), \"reason\": NO_DISTRIBUTION})\n            continue",
     "        if pmf is None:\n            continue"),
    ("an unnormalised pmf is accepted",
     "    if not (0.98 <= s <= 1.02):", "    if False:"),
    ("whole and half lines are pooled into one over/under rate",
     '        "half_line": _sub(lambda g: not g["whole_line"]),', '        "half_line": _sub(lambda g: True),'),
    ("push mass on a half line stops being structural",
     "        if not whole and push_mass > 0:", "        if False:"),
    ("the prior pool accepts a game from the cutoff date itself",
     "        if str(d) >= str(cutoff_date):", "        if str(d) > str(cutoff_date):"),
    ("an empty prior pool returns zero instead of null",
     '                "projected_total": None, "reason": "NO_PRIOR_GAMES_BEFORE_CUTOFF",',
     '                "projected_total": 0.0, "reason": "NO_PRIOR_GAMES_BEFORE_CUTOFF",'),
    ("the park factor is reported as applied when none was supplied",
     '        "park_adjustment_applied": pf is not None,', '        "park_adjustment_applied": True,'),
    ("the park factor stops being applied to the projection",
     '        "projected_total": mean * pf if pf is not None else mean,', '        "projected_total": mean,'),
    ("the banned-mean gate stops requiring the companions",
     '            for companion in ("median_abs_error", "signed_bias", "largest_miss", "n"):',
     '            for companion in ():'),
    ("the banned-mean gate stops recursing into nested nodes",
     '        for k, v in node.items():\n            bad += banned_mean_gate(v, f"{path}.{k}")',
     '        for k, v in []:\n            bad += banned_mean_gate(v, f"{path}.{k}")'),
    ("a log score may be reported without its zero-mass count",
     '        if "log_score" in node and "n_zero_mass" not in node:', "        if False:"),
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
