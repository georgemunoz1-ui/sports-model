#!/usr/bin/env python3
"""MLB TOTALS FORWARD EVALUATION — the shadow-candidate arm for the run-total projection.

WHY THIS EXISTS (owner roadmap item 4, 2026-08-22). The total projection is the steadiest thing the
model produces (8/21 read: MAE 2.39, signed +0.72), and the owner wants that preserved as a FORMAL
shadow candidate with a real forward evaluation rather than as a number quoted in prose. Preserved
is not promoted: this module classifies the arm DIAGNOSTIC and CANNOT do anything else. Promotion is
an owner act taken against the preregistered thresholds below; the module only reports which are met.

THE RULES IT ENFORCES, AND THE INCIDENTS THAT MOTIVATED THEM

  BANNED MEAN (see unified_card.totals_report). A mean absolute error travelling alone hides the
  shape of the miss. Every error block here carries MAE + MEDIAN + SIGNED bias + LARGEST miss
  together, and banned_mean_gate() walks the finished report and REFUSES any node that reports a
  mean without its companions — so the rule survives future edits to the report shape, not just
  this file's current output. (The block duplicates unified_card.totals_report deliberately:
  importing that module executes an os.chdir at import time, and an evaluation library must be
  importable without moving the process's working directory.)

  PUSH MASS (2026-08-19 totals incident). Four O/P/U probability rows were asserted that no replay
  ever produced; push mass on a half-point line was the tell, because run totals are INTEGERS and
  P(push) at x.5 is structurally zero. unified_card.totals_gate catches that at capture time. Here
  it is re-checked at EVALUATION time, because an evaluation that silently averages impossible rows
  launders them: a half-line row with nonzero push mass is REJECTED and no metric is computed. The
  same invariant is why WHOLE-number and HALF-number lines are reported as SEPARATE subgroups — a
  whole line can push and a half line cannot, so pooling them mixes two different settlement spaces
  and makes an over/under frequency uninterpretable.

  LINE BINDING (decision_card render_gate rule 3). A probability detached from its exact line is
  refused, here as there.

  R1 / NEVER INVENT. A row with no actual total is EXCLUDED WITH A REASON CODE and counted, never
  dropped silently and never filled in. A subgroup with no rows reports null metrics plus a reason,
  not a zero. A calibration slope with no predictor variance is null plus a reason, not 0.0.

  POWER. Every subgroup states its own n and is marked UNDERPOWERED below n=30. The 8/21 numbers
  come from a handful of slates; an unlabelled subgroup mean over 6 games reads like a finding.

Reads nothing, writes nothing: pure functions over caller-supplied rows. No registered artifact is
touched, so this module can never corrupt one.

API
  evaluate(rows) -> dict
      row: {model_total, actual_total} plus optional {line, p_over, p_push, p_under, park,
            cap_slots, game, date}
      cap_slots is the count of CAP starter slots for the game (0/1/2) in the sense frozen by
      unified_card.slot_status: CAP means TBD or REGISTRY_MISS only — a LOW_SAMPLE starter is NOT
      a CAP slot. Passing daily_card's broader `capped` flag here would silently change the
      subgroup definition, so cap_slots outside {0,1,2,None} is a structural refusal.
      Raises TotalsStructuralError if any row is structurally impossible.

Usage: python3 harness/totals_eval.py --selftest | --rows path/to/rows.json
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

MODULE_ID = "totals_eval"

import argparse
import hashlib
import json
import math
import statistics as st
import sys

SPEC_VERSION = "TOTALS-FWD-EVAL-1"

#: Below this, a subgroup mean is noise wearing a decimal point. Frozen with the arm.
UNDERPOWERED_MIN_N = 30

#: Park-factor band edges (run environment multiplier, data/backfill/mlb/2026/park_factors.json,
#: observed range 0.856 .. 1.449). Half-open: PITCHER < 0.97 <= NEUTRAL < 1.03 <= HITTER.
PARK_EDGE_LOW, PARK_EDGE_HIGH = 0.97, 1.03
PARK_KEYS = ("PARK_PITCHER", "PARK_NEUTRAL", "PARK_HITTER", "PARK_UNKNOWN")
CAP_KEYS = ("CAP_0", "CAP_1", "CAP_2", "CAP_UNKNOWN")
LINE_KEYS = ("WHOLE_LINE", "HALF_LINE", "NO_LINE")

PROB_TOL = 1e-6

#: PREREGISTERED PROMOTION THRESHOLDS — frozen 2026-08-22, BEFORE any forward window was scored.
#: The signed-bias ceiling is deliberately tighter than the 8/21 observation (+0.72): a projection
#: that is close on average while running systematically hot is a calibration failure, not a
#: steady model, and the whole point of freezing the number first is that it cannot be widened to
#: fit the read it is about to be judged against.
PREREG_THRESHOLDS = {
    "frozen_utc": "2026-08-22T00:00:00Z",
    "min_n_games": 100,
    "max_mae": 2.50,
    "max_median_ae": 2.00,
    "max_abs_signed_bias": 0.35,
    "max_mean_poisson_deviance": 1.35,
    "min_n_priced_for_calibration": 100,
    "calibration_slope_min": 0.80,
    "calibration_slope_max": 1.20,
}
#: sha256 of json.dumps(PREREG_THRESHOLDS, sort_keys=True). A post-hoc edit to any threshold
#: changes this and is reported as PREREG_TAMPERED — the arm then cannot report thresholds met.
PREREG_SHA = "1c3e2ba2b2ae26099c44e20e5a20c6f94d5b8bcde70b7ff286cd79fa5021b6b6"


class TotalsStructuralError(ValueError):
    """Raised when a row asserts something that cannot happen (e.g. push mass at x.5).

    Deliberately an exception rather than a filter: averaging around an impossible row would
    launder it into a headline number, which is exactly what the 8/19 incident did."""


# ---------------------------------------------------------------- small helpers

def _num(x):
    """Numeric or None. Booleans are rejected: True would silently become the total 1."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x)):
        return float(x)
    return None


def is_half_line(line):
    """x.5 lines cannot push (run totals are integers). Same predicate as unified_card.totals_gate."""
    return round(line * 2) % 2 == 1


def line_kind(line):
    if line is None:
        return "NO_LINE"
    return "HALF_LINE" if is_half_line(line) else "WHOLE_LINE"


def park_band(pf):
    """Frozen band edges. Half-open so that a park factor of exactly 0.97 has ONE home."""
    if pf is None:
        return "PARK_UNKNOWN"
    if pf < PARK_EDGE_LOW:
        return "PARK_PITCHER"
    if pf < PARK_EDGE_HIGH:
        return "PARK_NEUTRAL"
    return "PARK_HITTER"


def cap_band(cap_slots):
    """Null cap_slots gets its OWN bucket. Defaulting an unknown starter state to 0 would move
    incomplete-personnel games into the clean subgroup and flatter it (R1)."""
    if cap_slots is None:
        return "CAP_UNKNOWN"
    return f"CAP_{int(cap_slots)}"


def poisson_deviance(actual, projected):
    """Unit Poisson deviance 2*(y*ln(y/mu) - (y - mu)); the y=0 limit is 2*mu.

    WHY, alongside absolute error: MAE is in runs and rewards a projection that is merely near the
    mean. Deviance asks whether the projected RATE could plausibly have produced the observed count,
    so a projection of 9.0 against an actual of 3 is penalised much harder than 9.0 against 8 even
    though both are 'a few runs off'. Zero exactly when projected == actual."""
    if projected is None or projected <= 0:
        raise TotalsStructuralError(f"poisson deviance undefined for projected total {projected}")
    if actual < 0:
        raise TotalsStructuralError(f"negative actual total {actual}")
    if actual == 0:
        return 2.0 * projected
    return 2.0 * (actual * math.log(actual / projected) - (actual - projected))


def _ref(row, i):
    g = row.get("game") or row.get("row_id") or f"row[{i}]"
    d = row.get("date")
    return f"{d} {g}" if d else str(g)


# ---------------------------------------------------------------- structural gate

def structural_failures(rows):
    """Every refusal that says 'this row describes something that cannot exist'.

    Distinct from EXCLUSION (a fact that is merely unknown -> null + reason code). Returns a list
    of strings; empty means every row is at least possible."""
    fails = []
    for i, row in enumerate(rows):
        tag = _ref(row, i)
        model = _num(row.get("model_total"))
        actual = _num(row.get("actual_total"))
        line = _num(row.get("line"))

        if row.get("model_total") is not None and model is None:
            fails.append(f"{tag}: model_total is not a number ({row.get('model_total')!r})")
        elif model is not None and model <= 0:
            fails.append(f"{tag}: model_total {model} is not a positive rate — a projected run "
                         f"total of zero or less cannot be scored as a Poisson mean")

        if row.get("actual_total") is not None and actual is None:
            fails.append(f"{tag}: actual_total is not a number ({row.get('actual_total')!r})")
        elif actual is not None:
            if actual != int(actual):
                fails.append(f"{tag}: actual_total {actual} is not an integer — run totals are "
                             f"integer counts (the same invariant that forbids push mass at x.5)")
            if actual < 0:
                fails.append(f"{tag}: actual_total {actual} is negative")

        if row.get("line") is not None and line is None:
            fails.append(f"{tag}: line is not a number ({row.get('line')!r})")
        elif line is not None and abs(line * 2 - round(line * 2)) > PROB_TOL:
            fails.append(f"{tag}: line {line} is not a half-run step — no such total is quoted")

        cs = row.get("cap_slots")
        if cs is not None and (isinstance(cs, bool) or not isinstance(cs, int) or cs not in (0, 1, 2)):
            fails.append(f"{tag}: cap_slots {cs!r} outside {{0,1,2}} — a game has exactly two "
                         f"starter slots, and CAP means TBD or REGISTRY_MISS only "
                         f"(unified_card.slot_status)")

        pf = row.get("park")
        if pf is not None and _num(pf) is None:
            fails.append(f"{tag}: park factor is not a number ({pf!r})")

        po, pp, pu = (_num(row.get("p_over")), _num(row.get("p_push")), _num(row.get("p_under")))
        stated = [k for k in ("p_over", "p_push", "p_under") if row.get(k) is not None]
        bad_prob = [k for k in stated if _num(row.get(k)) is None]
        if bad_prob:
            fails.append(f"{tag}: non-numeric probability field(s) {bad_prob}")
            continue
        if not stated:
            continue
        # decision_card render_gate rule 3, applied to the evaluation input
        if line is None:
            fails.append(f"{tag}: over/under probabilities stated with NO line — a probability "
                         f"detached from its exact line is refused")
            continue
        for k, v in (("p_over", po), ("p_push", pp), ("p_under", pu)):
            if v is not None and not (0.0 - PROB_TOL <= v <= 1.0 + PROB_TOL):
                fails.append(f"{tag}: {k}={v} outside [0,1]")
        half = is_half_line(line)
        if half:
            # THE 8/19 INVARIANT
            if pp is not None and abs(pp) > PROB_TOL:
                fails.append(f"{tag}: push mass {pp} on half-point line {line} — integer run totals "
                             f"cannot land on x.5, so P(push) is structurally zero (2026-08-19)")
            if po is None or pu is None:
                fails.append(f"{tag}: half-point line {line} needs both p_over and p_under")
                continue
            total = po + pu + (pp or 0.0)
        else:
            if pp is None:
                fails.append(f"{tag}: whole-number line {line} stated without explicit push mass — "
                             f"a whole line CAN push, and an implicit p_push=0 is the same silent "
                             f"assertion that produced the 8/19 report")
                continue
            if po is None or pu is None:
                fails.append(f"{tag}: whole-number line {line} needs p_over, p_push and p_under")
                continue
            total = po + pp + pu
        if abs(total - 1.0) > 1e-6:
            fails.append(f"{tag}: probabilities do not partition ({total:.6f} != 1) at line {line}")
    return fails


# ---------------------------------------------------------------- preparation

def _prepare(rows):
    """Split rows into scoreable records and EXCLUSIONS-WITH-REASONS (R1)."""
    prepared, excluded = [], []
    for i, row in enumerate(rows):
        tag = _ref(row, i)
        model, actual = _num(row.get("model_total")), _num(row.get("actual_total"))
        if model is None:
            excluded.append({"ref": tag, "reason_code": "R1_MODEL_TOTAL_NULL",
                             "reason": "no projected total on this row; nothing is imputed"})
            continue
        if actual is None:
            excluded.append({"ref": tag, "reason_code": "R1_ACTUAL_TOTAL_NULL",
                             "reason": "no final total for this game yet; the row is counted as "
                                       "excluded rather than dropped or filled in"})
            continue
        line = _num(row.get("line"))
        po, pp, pu = (_num(row.get("p_over")), _num(row.get("p_push")), _num(row.get("p_under")))
        if line is not None and is_half_line(line) and po is not None and pp is None:
            pp = 0.0  # exact, by the structural invariant — not an assumption
        prepared.append({
            "ref": tag, "model": model, "actual": actual, "error": model - actual,
            "deviance": poisson_deviance(actual, model),
            "line": line, "line_kind": line_kind(line),
            "p_over": po, "p_push": pp, "p_under": pu,
            "park": _num(row.get("park")), "park_band": park_band(_num(row.get("park"))),
            "cap_slots": row.get("cap_slots"), "cap_band": cap_band(row.get("cap_slots")),
            "settle": (None if line is None else
                       ("OVER" if actual > line else "UNDER" if actual < line else "PUSH")),
        })
    return prepared, excluded


# ---------------------------------------------------------------- metric blocks

def error_block(recs, label):
    """MAE, MEDIAN, SIGNED bias and LARGEST miss — always together (the banned-mean rule) — plus
    Poisson deviance and the power statement. An empty group is null + reason, never zero."""
    n = len(recs)
    if n == 0:
        return {"group": label, "n": 0, "underpowered": True,
                "power_note": f"n=0 < {UNDERPOWERED_MIN_N}: UNDERPOWERED",
                "mae": None, "median_ae": None, "signed_bias": None, "largest_miss": None,
                "largest_miss_ref": None, "mean_poisson_deviance": None,
                "total_poisson_deviance": None,
                "null_reason": "R1_NO_ROWS_IN_SUBGROUP — no scoreable row fell in this subgroup"}
    errs = [r["error"] for r in recs]
    abs_errs = [abs(e) for e in errs]
    worst = max(recs, key=lambda r: abs(r["error"]))
    under = n < UNDERPOWERED_MIN_N
    return {
        "group": label, "n": n, "underpowered": under,
        "power_note": (f"n={n} < {UNDERPOWERED_MIN_N}: UNDERPOWERED — read as a sample, not a rate"
                       if under else f"n={n} >= {UNDERPOWERED_MIN_N}: powered"),
        "mae": round(sum(abs_errs) / n, 3),
        "median_ae": round(st.median(abs_errs), 3),
        "signed_bias": round(sum(errs) / n, 3),
        "largest_miss": round(worst["error"], 3),
        "largest_miss_ref": worst["ref"],
        "mean_poisson_deviance": round(sum(r["deviance"] for r in recs) / n, 4),
        "total_poisson_deviance": round(sum(r["deviance"] for r in recs), 4),
        "unit_note": "errors are model_total - actual_total, in runs; deviance is unitless",
    }


def _line_block(recs, label):
    """Error block plus the settlement counts that make whole vs half comparable at all."""
    b = error_block(recs, label)
    b["observed_pushes"] = sum(1 for r in recs if r["settle"] == "PUSH")
    priced = [r for r in recs if r["p_push"] is not None]
    b["expected_push_mass"] = (round(sum(r["p_push"] for r in priced), 4) if priced else None)
    if not priced:
        b["expected_push_mass_null_reason"] = "R1_NO_PUSH_PROBABILITIES_SUPPLIED"
    b["push_note"] = ("half-point lines cannot push: expected and observed push mass are zero BY "
                      "CONSTRUCTION, not by fit" if label == "HALF_LINE" else
                      "whole-number lines can push; expected vs observed push mass is a real check"
                      if label == "WHOLE_LINE" else "no line: over/under is undefined for this group")
    return b


def calibration(recs):
    """Decile calibration of P(over) plus an OLS slope of outcome on predicted probability.

    Conventions stated because a bare frequency with an ambiguous denominator is the reporting
    defect this repo keeps re-learning:
      * the over indicator is y = 1 iff actual_total > line. A PUSH is NOT an over: it is counted
        in the denominator and scores y = 0, because p_over is the unconditional probability that
        the over SETTLES AS A WIN.
      * every bucket therefore also reports n_over / n_push / n_under and a second frequency
        computed on the push-free denominator, each with its denominator named.
      * slope 1.0 with intercept 0.0 is perfect calibration. No predictor variance -> null with a
        reason code, never a slope of zero."""
    priced = [r for r in recs if r["line"] is not None and r["p_over"] is not None]
    n = len(priced)
    if n == 0:
        return {"n": 0, "underpowered": True,
                "power_note": f"n=0 < {UNDERPOWERED_MIN_N}: UNDERPOWERED",
                "buckets": [], "slope": None, "intercept": None,
                "null_reason": "R1_NO_PRICED_ROWS — no row carried both a line and p_over"}
    buckets = []
    for d in range(10):
        lo, hi = d / 10.0, (d + 1) / 10.0
        sel = [r for r in priced if (lo <= r["p_over"] < hi) or (d == 9 and r["p_over"] >= hi)]
        bn = len(sel)
        n_over = sum(1 for r in sel if r["settle"] == "OVER")
        n_push = sum(1 for r in sel if r["settle"] == "PUSH")
        n_under = sum(1 for r in sel if r["settle"] == "UNDER")
        ex_den = bn - n_push
        buckets.append({
            "bucket": f"[{lo:.1f},{hi:.1f}{']' if d == 9 else ')'}",
            "n": bn,
            "underpowered": bn < UNDERPOWERED_MIN_N,
            "power_note": (f"n={bn} < {UNDERPOWERED_MIN_N}: UNDERPOWERED" if bn < UNDERPOWERED_MIN_N
                           else f"n={bn} >= {UNDERPOWERED_MIN_N}: powered"),
            "mean_predicted_p_over": (round(sum(r["p_over"] for r in sel) / bn, 4) if bn else None),
            "observed_over_freq_all_rows": (round(n_over / bn, 4) if bn else None),
            "observed_over_denominator": bn,
            "observed_over_freq_excluding_pushes": (round(n_over / ex_den, 4) if ex_den else None),
            "observed_over_ex_push_denominator": ex_den,
            "n_over": n_over, "n_push": n_push, "n_under": n_under,
            "null_reason": (None if bn else "R1_EMPTY_BUCKET — no forecast landed in this decile"),
        })
    xs = [r["p_over"] for r in priced]
    ys = [1.0 if r["settle"] == "OVER" else 0.0 for r in priced]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-12:
        slope, intercept, sreason = None, None, ("R1_NO_PREDICTION_VARIANCE — every p_over is "
                                                 "identical, so no slope is identified")
    else:
        sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        slope = round(sxy / sxx, 4)
        intercept = round(my - (sxy / sxx) * mx, 4)
        sreason = None
    return {"n": n, "underpowered": n < UNDERPOWERED_MIN_N,
            "power_note": (f"n={n} < {UNDERPOWERED_MIN_N}: UNDERPOWERED" if n < UNDERPOWERED_MIN_N
                           else f"n={n} >= {UNDERPOWERED_MIN_N}: powered"),
            "buckets": buckets, "slope": slope, "intercept": intercept,
            "slope_null_reason": sreason,
            "mean_predicted_p_over": round(mx, 4), "observed_over_rate": round(my, 4),
            "perfect_calibration_reference": {"slope": 1.0, "intercept": 0.0},
            "push_convention": "a push scores y=0 and stays in the denominator; p_over is the "
                               "probability the over SETTLES AS A WIN"}


def push_mass_block(recs):
    """The 8/19 invariant carried into evaluation: expected vs observed pushes, split by line type,
    with half-point lines shown as structurally zero rather than as a fitted zero."""
    whole = [r for r in recs if r["line_kind"] == "WHOLE_LINE"]
    half = [r for r in recs if r["line_kind"] == "HALF_LINE"]
    wp = [r for r in whole if r["p_push"] is not None]
    return {
        "whole_line_n": len(whole),
        "whole_line_expected_pushes": (round(sum(r["p_push"] for r in wp), 3) if wp else None),
        "whole_line_expected_null_reason": (None if wp else "R1_NO_PUSH_PROBABILITIES_SUPPLIED"),
        "whole_line_observed_pushes": sum(1 for r in whole if r["settle"] == "PUSH"),
        "half_line_n": len(half),
        "half_line_expected_pushes": 0.0,
        "half_line_observed_pushes": sum(1 for r in half if r["settle"] == "PUSH"),
        "invariant": "half-point lines: expected == observed == 0 EXACTLY, by construction "
                     "(integer run totals cannot land on x.5). A nonzero value here would mean the "
                     "structural gate was bypassed.",
        "underpowered_whole": len(whole) < UNDERPOWERED_MIN_N,
        "underpowered_half": len(half) < UNDERPOWERED_MIN_N,
    }


# ---------------------------------------------------------------- promotion

def _prereg_sha(prereg):
    return hashlib.sha256(json.dumps(prereg, sort_keys=True).encode()).hexdigest()


def promotion_status(report, prereg=None, expected_sha=None):
    """Which preregistered thresholds are met. This function CANNOT promote anything: the arm's
    class stays DIAGNOSTIC either way, and 'THRESHOLDS_MET_AWAITING_OWNER_PROMOTION' is a report,
    not a state change. Thresholds are hash-pinned (ml_p4_forward's frozen-config discipline): an
    edit after the freeze is reported as PREREG_TAMPERED and no threshold can then read as met."""
    prereg = PREREG_THRESHOLDS if prereg is None else prereg
    expected_sha = PREREG_SHA if expected_sha is None else expected_sha
    sha = _prereg_sha(prereg)
    tampered = (sha != expected_sha)
    o, cal = report["overall"], report["calibration"]
    unmet, met = [], []

    def chk(name, ok, detail):
        (met if ok else unmet).append(f"{name}: {detail}")

    chk("min_n_games", o["n"] >= prereg["min_n_games"],
        f'n={o["n"]} vs required >= {prereg["min_n_games"]}')
    for key, thr_key, cmpname in (("mae", "max_mae", "<="),
                                  ("median_ae", "max_median_ae", "<="),
                                  ("mean_poisson_deviance", "max_mean_poisson_deviance", "<=")):
        v = o[key]
        chk(key, v is not None and v <= prereg[thr_key], f'{v} vs {cmpname} {prereg[thr_key]}')
    sb = o["signed_bias"]
    chk("abs_signed_bias", sb is not None and abs(sb) <= prereg["max_abs_signed_bias"],
        f'{sb} vs |bias| <= {prereg["max_abs_signed_bias"]}')
    chk("min_n_priced_for_calibration", cal["n"] >= prereg["min_n_priced_for_calibration"],
        f'priced n={cal["n"]} vs required >= {prereg["min_n_priced_for_calibration"]}')
    sl = cal.get("slope")
    chk("calibration_slope",
        sl is not None and prereg["calibration_slope_min"] <= sl <= prereg["calibration_slope_max"],
        f'slope={sl} vs [{prereg["calibration_slope_min"]}, {prereg["calibration_slope_max"]}]'
        + ("" if sl is not None else f' ({cal.get("slope_null_reason") or cal.get("null_reason")})'))

    if tampered:
        status = "DIAGNOSTIC — PREREG_TAMPERED"
        unmet = [f"prereg_hash: {sha[:12]} != frozen {str(expected_sha)[:12]} — thresholds were "
                 f"edited after the freeze; no threshold may read as met"] + unmet
        met = []
    else:
        status = ("THRESHOLDS_MET_AWAITING_OWNER_PROMOTION" if not unmet else "DIAGNOSTIC")
    return {"status": status, "class": "DIAGNOSTIC", "prereg_sha256": sha,
            "prereg_tampered": tampered, "thresholds": prereg, "unmet": unmet, "met": met,
            "note": "this module never promotes: class is DIAGNOSTIC in every branch, and a met "
                    "threshold set is an owner decision input, not a state change"}


# ---------------------------------------------------------------- report gate

MEAN_COMPANIONS = ("median_ae", "signed_bias", "largest_miss")


def banned_mean_gate(node, path="report"):
    """Walk the finished report and REFUSE any node that reports a mean without its companions,
    an n without a power statement, or a null metric without a reason code (R1).

    The gate exists so the banned-mean rule outlives this file's current output shape: a future
    edit that adds a new MAE somewhere fails here instead of shipping a lonely mean."""
    fails = []
    if isinstance(node, dict):
        if "mae" in node:
            if node.get("mae") is None:
                if not node.get("null_reason"):
                    fails.append(f"{path}: mae is null with no reason code (R1)")
            else:
                for k in MEAN_COMPANIONS:
                    if node.get(k) is None:
                        fails.append(f"{path}: mae reported without {k} — the banned-mean rule")
            if "n" not in node:
                fails.append(f"{path}: mae reported without n")
            if "underpowered" not in node:
                fails.append(f"{path}: metric block does not state whether it is UNDERPOWERED")
        if "n" in node and "underpowered" in node:
            n, u = node["n"], node["underpowered"]
            if isinstance(n, int) and bool(u) != (n < UNDERPOWERED_MIN_N):
                fails.append(f"{path}: underpowered flag {u} contradicts n={n} "
                             f"(threshold {UNDERPOWERED_MIN_N})")
        for k, v in node.items():
            fails += banned_mean_gate(v, f"{path}.{k}")[1]
    elif isinstance(node, list):
        for i, v in enumerate(node):
            fails += banned_mean_gate(v, f"{path}[{i}]")[1]
    return (not fails), fails


# ---------------------------------------------------------------- entry point

def evaluate(rows):
    """Forward evaluation of the MLB total projection. See module docstring for every rule."""
    sf = structural_failures(rows)
    if sf:
        raise TotalsStructuralError(
            f"REFUSED: {len(sf)} structurally impossible row(s); no metric is computed on "
            "impossible data (a mean over an impossible row launders it):\n  " + "\n  ".join(sf))
    prepared, excluded = _prepare(rows)
    report = {
        "spec_version": SPEC_VERSION,
        "class": "DIAGNOSTIC",
        "class_reason": "shadow candidate: the totals arm is registered and scored forward, and "
                        "stays DIAGNOSTIC until the preregistered thresholds are met and the owner "
                        "promotes it. This module cannot promote.",
        "n_rows_in": len(rows),
        "n_evaluated": len(prepared),
        "n_excluded": len(excluded),
        "excluded": excluded,
        "structural_check": f"PASSED — {len(rows)} row(s) checked against the structural invariants",
        "overall": error_block(prepared, "ALL"),
        "calibration": calibration(prepared),
        "push_mass": push_mass_block(prepared),
        "subgroups": {
            "park_band": {k: error_block([r for r in prepared if r["park_band"] == k], k)
                          for k in PARK_KEYS},
            "cap_slots": {k: error_block([r for r in prepared if r["cap_band"] == k], k)
                          for k in CAP_KEYS},
            "line_type": {k: _line_block([r for r in prepared if r["line_kind"] == k], k)
                          for k in LINE_KEYS},
        },
        "band_definitions": {
            "park": f"PARK_PITCHER < {PARK_EDGE_LOW} <= PARK_NEUTRAL < {PARK_EDGE_HIGH} <= PARK_HITTER",
            "cap_slots": "count of CAP starter slots per unified_card.slot_status (TBD or "
                         "REGISTRY_MISS only; LOW_SAMPLE is NOT a CAP slot)",
            "line_type": "WHOLE_LINE can push; HALF_LINE cannot (integer run totals) — reported "
                         "separately, never pooled",
            "underpowered": f"any subgroup with n < {UNDERPOWERED_MIN_N}",
        },
    }
    report["underpowered_subgroups"] = sorted(
        f"{fam}.{k}" for fam, grps in report["subgroups"].items()
        for k, v in grps.items() if v["underpowered"])
    report["promotion"] = promotion_status(report)
    ok, gate_fails = banned_mean_gate(report)
    report["report_gate"] = {"passed": ok, "failures": gate_fails}
    if not ok:
        raise TotalsStructuralError("REFUSED: report gate failed:\n  " + "\n  ".join(gate_fails))
    return report


# ---------------------------------------------------------------- selftest

def _rows(n, model, actual, **kw):
    return [dict(model_total=model, actual_total=actual, game=f"G{i}", **kw) for i in range(n)]


def selftest():
    fails = []

    # ---- 1. THE 8/19 INVARIANT: push mass on a half-point line is REJECTED, not averaged
    half_push = [{"game": "A@B", "model_total": 8.4, "actual_total": 9, "line": 8.5,
                  "p_over": 0.55, "p_push": 0.03, "p_under": 0.42}]
    if not any("push mass" in f for f in structural_failures(half_push)):
        fails.append("half-line row with push mass was NOT rejected (the 8/19 incident case)")
    try:
        evaluate(half_push)
        fails.append("evaluate() computed metrics over a half-line row carrying push mass")
    except TotalsStructuralError:
        pass
    # the same row with the push mass removed must pass — the rule must not reject everything
    half_ok = [dict(half_push[0], p_push=0.0, p_over=0.58, p_under=0.42)]
    if structural_failures(half_ok):
        fails.append(f"a valid half-line row was rejected: {structural_failures(half_ok)}")

    # ---- 2. whole-number line stated with NO explicit push mass is refused
    whole_implicit = [{"game": "C@D", "model_total": 8.1, "actual_total": 8, "line": 8.0,
                       "p_over": 0.55, "p_under": 0.45}]
    if not any("without explicit push mass" in f for f in structural_failures(whole_implicit)):
        fails.append("whole line with an implicit p_push=0 was accepted")
    if structural_failures([dict(whole_implicit[0], p_over=0.5, p_push=0.1, p_under=0.4)]):
        fails.append("a valid whole-line triple was rejected")

    # ---- 3. probabilities must partition, and must be bound to an exact line
    if not any("do not partition" in f for f in structural_failures(
            [{"game": "E@F", "model_total": 8, "actual_total": 8, "line": 8.0,
              "p_over": 0.5, "p_push": 0.1, "p_under": 0.5}])):
        fails.append("a non-partitioning probability triple was accepted")
    if not any("detached from its exact line" in f for f in structural_failures(
            [{"game": "E@F", "model_total": 8, "actual_total": 8, "p_over": 0.6, "p_under": 0.4}])):
        fails.append("over/under probabilities with NO line were accepted")

    # ---- 4. impossible scalars: non-integer actual, non-half-step line, non-positive projection,
    #         out-of-range cap_slots
    if not any("not an integer" in f for f in structural_failures(
            [{"game": "G@H", "model_total": 8.0, "actual_total": 8.5}])):
        fails.append("a non-integer actual run total was accepted")
    if not any("not a half-run step" in f for f in structural_failures(
            [{"game": "G@H", "model_total": 8.0, "actual_total": 8, "line": 8.25}])):
        fails.append("a line off the half-run grid was accepted")
    if not any("not a positive rate" in f for f in structural_failures(
            [{"game": "G@H", "model_total": 0.0, "actual_total": 8}])):
        fails.append("a non-positive projected total was accepted")
    if not any("outside {0,1,2}" in f for f in structural_failures(
            [{"game": "G@H", "model_total": 8.0, "actual_total": 8, "cap_slots": 3}])):
        fails.append("cap_slots=3 was accepted — a game has exactly two starter slots")

    # ---- 5. Poisson deviance on known fixtures
    if abs(poisson_deviance(8, 8.0)) > 1e-12:
        fails.append("deviance of a perfect projection is not zero")
    if abs(poisson_deviance(4, 2.0) - (8 * math.log(2) - 4)) > 1e-12:
        fails.append(f"deviance(y=4, mu=2) wrong: {poisson_deviance(4, 2.0)} != {8*math.log(2)-4}")
    if abs(poisson_deviance(0, 2.0) - 4.0) > 1e-12:
        fails.append(f"deviance(y=0, mu=2) must be 2*mu=4.0, got {poisson_deviance(0, 2.0)}")
    if not (poisson_deviance(3, 9.0) > poisson_deviance(8, 9.0)):
        fails.append("deviance did not penalise the far-off rate harder than the near one")
    known = evaluate([{"game": "K1", "model_total": 2.0, "actual_total": 4},
                      {"game": "K2", "model_total": 2.0, "actual_total": 0}])
    expect_mean = ((8 * math.log(2) - 4) + 4.0) / 2
    if abs(known["overall"]["mean_poisson_deviance"] - round(expect_mean, 4)) > 1e-9:
        fails.append(f'mean deviance wrong: {known["overall"]["mean_poisson_deviance"]} != '
                     f'{round(expect_mean, 4)}')

    # ---- 6. BANNED MEAN: median, signed bias and largest miss travel with every mean
    skew = evaluate([{"game": f"S{i}", "model_total": 8.0, "actual_total": a}
                     for i, a in enumerate([8, 8, 8, 8, 28])])
    o = skew["overall"]
    if o["largest_miss"] != -20.0:
        fails.append(f'largest miss lost to cancellation/abs: {o["largest_miss"]} (want -20.0)')
    if o["median_ae"] != 0.0:
        fails.append(f'median absolute error wrong: {o["median_ae"]} (want 0.0)')
    if o["mae"] == o["median_ae"] or o["signed_bias"] == o["mae"]:
        fails.append("the mean is indistinguishable from median/signed bias on a skewed fixture")
    lonely = {"n": 40, "underpowered": False, "mae": 2.39}
    if banned_mean_gate(lonely)[0]:
        fails.append("banned_mean_gate passed a bare MAE with no median/signed/largest")
    if banned_mean_gate({"subgroups": {"x": dict(lonely)}})[0]:
        fails.append("banned_mean_gate missed a lonely mean nested inside subgroups")
    if not banned_mean_gate(dict(lonely, median_ae=2.0, signed_bias=0.72, largest_miss=-9.0))[0]:
        fails.append("banned_mean_gate rejected a complete block")
    if banned_mean_gate({"n": 4, "underpowered": False, "mae": 1.0, "median_ae": 1.0,
                         "signed_bias": 1.0, "largest_miss": 1.0})[0]:
        fails.append("banned_mean_gate accepted an underpowered flag contradicting n")
    if banned_mean_gate({"n": 0, "underpowered": True, "mae": None})[0]:
        fails.append("banned_mean_gate accepted a null MAE with no reason code (R1)")

    # ---- 7. SUBGROUPS: park bands, CAP slots, whole vs half — each with n, each power-marked
    if (park_band(0.9699), park_band(0.97), park_band(1.0299), park_band(1.03), park_band(None)) != \
            ("PARK_PITCHER", "PARK_NEUTRAL", "PARK_NEUTRAL", "PARK_HITTER", "PARK_UNKNOWN"):
        fails.append("park band edges are not the frozen half-open bands")
    if cap_band(None) != "CAP_UNKNOWN" or cap_band(0) != "CAP_0":
        fails.append("an unknown cap_slots count did not get its own bucket (it must not read as 0)")
    mixed = (_rows(4, 9.0, 7, park=1.10, cap_slots=0, line=8.5, p_over=0.6, p_under=0.4)
             + _rows(3, 8.0, 9, park=0.90, cap_slots=1)
             + _rows(2, 8.0, 8, park=1.00, cap_slots=2, line=8.0, p_over=.4, p_push=.15, p_under=.45)
             + _rows(1, 8.0, 8))  # no park, no cap_slots, no line
    rep = evaluate(mixed)
    sg = rep["subgroups"]
    if sg["park_band"]["PARK_HITTER"]["n"] != 4 or sg["park_band"]["PARK_PITCHER"]["n"] != 3:
        fails.append("park subgroup counts wrong")
    if sg["park_band"]["PARK_UNKNOWN"]["n"] != 1:
        fails.append("a row with no park factor did not land in PARK_UNKNOWN")
    if sg["cap_slots"]["CAP_UNKNOWN"]["n"] != 1 or sg["cap_slots"]["CAP_0"]["n"] != 4:
        fails.append("a row with unknown cap_slots leaked into CAP_0")
    if sg["line_type"]["HALF_LINE"]["n"] != 4 or sg["line_type"]["WHOLE_LINE"]["n"] != 2 \
            or sg["line_type"]["NO_LINE"]["n"] != 4:
        fails.append(f'whole/half/no-line split wrong: '
                     f'{ {k: v["n"] for k, v in sg["line_type"].items()} }')
    if sg["line_type"]["HALF_LINE"]["observed_pushes"] != 0 \
            or sg["line_type"]["HALF_LINE"]["expected_push_mass"] != 0.0:
        fails.append("half-line subgroup reported push mass — the invariant is not being carried")
    if sg["line_type"]["WHOLE_LINE"]["expected_push_mass"] != 0.3:
        fails.append("whole-line expected push mass not summed from the supplied p_push")
    if sg["line_type"]["WHOLE_LINE"]["observed_pushes"] != 2:
        fails.append("an actual total landing exactly on a whole line was not counted as a push")
    for fam, grps in sg.items():
        for k, v in grps.items():
            if "n" not in v:
                fails.append(f"subgroup {fam}.{k} does not report n")
            if v["n"] < UNDERPOWERED_MIN_N and not v["underpowered"]:
                fails.append(f"subgroup {fam}.{k} with n={v['n']} was NOT flagged UNDERPOWERED")
    if "park_band.PARK_HITTER" not in rep["underpowered_subgroups"]:
        fails.append("underpowered subgroup missing from the top-level roll-up")

    # ---- 8. the underpowered boundary is exactly n < 30
    b29 = evaluate(_rows(29, 8.0, 8))["overall"]
    b30 = evaluate(_rows(30, 8.0, 8))["overall"]
    if not b29["underpowered"]:
        fails.append("n=29 was not flagged UNDERPOWERED")
    if b30["underpowered"]:
        fails.append("n=30 was flagged UNDERPOWERED — the bar is n < 30")

    # ---- 9. CALIBRATION: slope, deciles, push convention, null-with-reason
    cal_rows = ([{"game": f"L{i}", "model_total": 8.0, "actual_total": (9 if i < 2 else 8),
                  "line": 8.5, "p_over": 0.2, "p_under": 0.8} for i in range(10)]
                + [{"game": f"H{i}", "model_total": 9.0, "actual_total": (9 if i < 8 else 8),
                    "line": 8.5, "p_over": 0.8, "p_under": 0.2} for i in range(10)])
    cal = evaluate(cal_rows)["calibration"]
    if cal["slope"] != 1.0 or cal["intercept"] != 0.0:
        fails.append(f'calibration slope/intercept wrong on a perfectly calibrated fixture: '
                     f'{cal["slope"]}/{cal["intercept"]} (want 1.0/0.0)')
    b2 = next(b for b in cal["buckets"] if b["bucket"].startswith("[0.2"))
    b8 = next(b for b in cal["buckets"] if b["bucket"].startswith("[0.8"))
    if b2["n"] != 10 or b2["observed_over_freq_all_rows"] != 0.2:
        fails.append(f"decile bucket [0.2,0.3) wrong: {b2}")
    if b8["n"] != 10 or b8["observed_over_freq_all_rows"] != 0.8:
        fails.append(f"decile bucket [0.8,0.9) wrong: {b8}")
    if not all("n" in b for b in cal["buckets"]) or len(cal["buckets"]) != 10:
        fails.append("calibration must report all ten deciles, each with its n")
    if not b2["underpowered"]:
        fails.append("an n=10 calibration bucket was not flagged UNDERPOWERED")
    # a PUSH is not an over: it stays in the denominator and scores 0
    push_rows = [{"game": f"P{i}", "model_total": 8.0, "actual_total": (8 if i < 5 else 9),
                  "line": 8.0, "p_over": 0.5, "p_push": 0.1, "p_under": 0.4} for i in range(10)]
    pcal = evaluate(push_rows)["calibration"]
    pb = next(b for b in pcal["buckets"] if b["n"])
    if pb["n_push"] != 5 or pb["observed_over_freq_all_rows"] != 0.5 \
            or pb["observed_over_freq_excluding_pushes"] != 1.0:
        fails.append(f"push handling in calibration wrong: {pb}")
    if pb["observed_over_denominator"] != 10 or pb["observed_over_ex_push_denominator"] != 5:
        fails.append("calibration frequencies printed without their named denominators")
    # ... and the SLOPE obeys the same convention: a push scores y=0, it is not a cheap win.
    # 10 pushes at p_over=.2 and 10 overs at p_over=.8 identify a slope of exactly 5/3; scoring
    # the pushes as overs makes every outcome a 1 and collapses the slope to 0.
    slope_push = evaluate(
        [{"game": f"Q{i}", "model_total": 8.0, "actual_total": 8, "line": 8.0,
          "p_over": 0.2, "p_push": 0.1, "p_under": 0.7} for i in range(10)]
        + [{"game": f"R{i}", "model_total": 9.0, "actual_total": 9, "line": 8.0,
            "p_over": 0.8, "p_push": 0.1, "p_under": 0.1} for i in range(10)])["calibration"]
    if abs(slope_push["slope"] - 5 / 3) > 5e-4:
        fails.append(f'calibration slope mishandles pushes: {slope_push["slope"]} (want 1.6667 — a '
                     f'push scores y=0 and stays in the denominator)')
    flat = evaluate(_rows(5, 8.0, 8, line=8.5, p_over=0.5, p_under=0.5))["calibration"]
    if flat["slope"] is not None or not flat["slope_null_reason"]:
        fails.append("a slope with no predictor variance must be null WITH a reason, not 0.0")
    noline = evaluate(_rows(5, 8.0, 8))["calibration"]
    if noline["n"] != 0 or not noline["null_reason"]:
        fails.append("calibration over rows with no line must be null with a reason code")

    # ---- 10. R1: a row with no final total is EXCLUDED WITH A REASON, never dropped or invented
    exc = evaluate([{"game": "X1", "model_total": 8.0, "actual_total": 8},
                    {"game": "X2", "model_total": 8.0, "actual_total": None},
                    {"game": "X3", "model_total": None, "actual_total": 7}])
    if exc["n_rows_in"] != 3 or exc["n_evaluated"] != 1 or exc["n_excluded"] != 2:
        fails.append(f"exclusion accounting wrong: {exc['n_rows_in']}/{exc['n_evaluated']}/{exc['n_excluded']}")
    if {e["reason_code"] for e in exc["excluded"]} != {"R1_ACTUAL_TOTAL_NULL", "R1_MODEL_TOTAL_NULL"}:
        fails.append("an excluded row carried no R1 reason code")

    # ---- 11. PROMOTION: stays DIAGNOSTIC at the 8/21 signed bias, and this module never promotes
    hot = [{"game": f"B{i}", "model_total": 8.0 + 0.72, "actual_total": 8, "line": 8.5,
            "p_over": (i % 10) / 10 + 0.05, "p_under": 1 - ((i % 10) / 10 + 0.05)}
           for i in range(120)]
    hp = evaluate(hot)["promotion"]
    if hp["status"] != "DIAGNOSTIC":
        fails.append(f'a +0.72 signed bias reached {hp["status"]} — the 8/21 read must stay DIAGNOSTIC')
    if not any(u.startswith("abs_signed_bias") for u in hp["unmet"]):
        fails.append("the signed-bias threshold did not appear as unmet")
    if not any(u.startswith("min_n_games") for u in hp["met"]):
        fails.append("a met threshold was not reported as met (the gate must not be vacuous)")
    # a well-calibrated, unbiased 120-game window meets EVERY threshold — so the gate is not
    # unreachable-by-construction — and the arm STILL cannot be promoted from inside this module
    clean = []
    for d in range(10):
        p = d / 10 + 0.05
        k = round(p * 12)          # overs land at the predicted rate: slope ~1
        for j in range(12):
            a = 9 if j < k else 8  # line 8.5: 9 = over, 8 = under, no push possible
            clean.append({"game": f"C{d}-{j}", "model_total": round(8.5 + (p - 0.5) * 2, 3),
                          "actual_total": a, "line": 8.5, "p_over": p, "p_under": round(1 - p, 3)})
    crep = evaluate(clean)
    cp = crep["promotion"]
    if cp["unmet"] or cp["status"] != "THRESHOLDS_MET_AWAITING_OWNER_PROMOTION":
        fails.append(f"a clean window met no threshold set — the bar is unreachable: {cp['unmet']}")
    if crep["class"] != "DIAGNOSTIC" or cp["class"] != "DIAGNOSTIC":
        fails.append("the arm's class left DIAGNOSTIC — this module must not be able to promote")
    # threshold tampering is visible
    loose = dict(PREREG_THRESHOLDS, max_abs_signed_bias=1.0)
    tp = promotion_status(evaluate(hot), prereg=loose)
    if not tp["prereg_tampered"] or tp["status"] != "DIAGNOSTIC — PREREG_TAMPERED" or tp["met"]:
        fails.append("a post-hoc widened threshold was not caught as PREREG_TAMPERED")
    if _prereg_sha(PREREG_THRESHOLDS) != PREREG_SHA:
        fails.append("the frozen threshold hash does not match the thresholds in this file")

    # ---- 12. the finished report passes its own gate
    ok, gf = banned_mean_gate(rep)
    if not ok:
        fails.append(f"the real report failed the banned-mean gate: {gf}")

    if fails:
        print("totals_eval selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("totals_eval selftest: PASS (half-line push mass is REJECTED and no metric is computed "
          "over it; whole/half lines are scored as separate subgroups; Poisson deviance exact at "
          "y=mu, y=4/mu=2 and the y=0 limit; MAE never travels without median, signed bias and "
          "largest miss — enforced recursively by the report gate; calibration slope 1.0/intercept "
          "0.0 on a calibrated fixture, null-with-reason when unidentified, pushes kept in a named "
          "denominator; every subgroup states n and flags UNDERPOWERED below 30; the 8/21 +0.72 "
          "bias stays DIAGNOSTIC and threshold tampering is caught)")
    return 0


def _print_summary(rep):
    o = rep["overall"]
    print(f'{SPEC_VERSION} — class {rep["class"]} — evaluated {rep["n_evaluated"]} of '
          f'{rep["n_rows_in"]} row(s), {rep["n_excluded"]} excluded with reason codes')
    print(f'  ALL  n={o["n"]:<4} MAE {o["mae"]}  median {o["median_ae"]}  signed {o["signed_bias"]:+}'
          f'  largest {o["largest_miss"]:+} ({o["largest_miss_ref"]})  deviance {o["mean_poisson_deviance"]}'
          f'  [{ "UNDERPOWERED" if o["underpowered"] else "powered" }]')
    for fam, grps in rep["subgroups"].items():
        print(f'  {fam}:')
        for k, v in grps.items():
            if v["n"] == 0:
                print(f'    {k:<14} n=0    — {v["null_reason"]}')
                continue
            print(f'    {k:<14} n={v["n"]:<4} MAE {v["mae"]}  median {v["median_ae"]}  '
                  f'signed {v["signed_bias"]:+}  largest {v["largest_miss"]:+}  '
                  f'dev {v["mean_poisson_deviance"]}'
                  f'{"  UNDERPOWERED" if v["underpowered"] else ""}')
    c = rep["calibration"]
    print(f'  calibration: n={c["n"]} slope={c["slope"]} intercept={c["intercept"]}'
          f'{"  " + (c.get("slope_null_reason") or c.get("null_reason") or "")}')
    for b in c["buckets"]:
        if b["n"]:
            print(f'    {b["bucket"]:<12} n={b["n"]:<4} pred {b["mean_predicted_p_over"]}  '
                  f'obs {b["observed_over_freq_all_rows"]} (of {b["observed_over_denominator"]})  '
                  f'O/P/U {b["n_over"]}/{b["n_push"]}/{b["n_under"]}'
                  f'{"  UNDERPOWERED" if b["underpowered"] else ""}')
    p = rep["promotion"]
    print(f'  promotion: {p["status"]}  (met {len(p["met"])}, unmet {len(p["unmet"])})')
    for u in p["unmet"]:
        print(f'    unmet: {u}')


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="MLB totals forward evaluation (read-only)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--rows", help="JSON file: a list of rows, or {\"rows\": [...]}")
    ap.add_argument("--json", action="store_true", help="print the full report as JSON")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(selftest())
    if not a.rows:
        ap.error("nothing to do: pass --selftest or --rows")
    doc = json.load(open(a.rows))
    rows = doc["rows"] if isinstance(doc, dict) else doc
    try:
        rep = evaluate(rows)
    except TotalsStructuralError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps(rep, indent=1) if a.json else "", end="")
    if not a.json:
        _print_summary(rep)
