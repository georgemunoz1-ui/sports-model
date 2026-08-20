#!/usr/bin/env python3
"""Three prospective WNBA ATS ledgers (owner ratification 2026-08-20).

  1. FULL diagnostic cohort      — every preregistered selection, graded, no filter. The experiment.
  2. ACTION-ELIGIBLE subset      — selections the amended card-action gate would have surfaced
                                   (favorite-side read AND |home_cover_delta| >= 2.0 spread points).
  3. BLOCKED subset              — underdog/compression reads and sub-deadband deltas.

The gate classifies; it never filters registration or grading. Ledgers 2 and 3 partition the
post-amendment portion of ledger 1, which is how the gate's value gets measured without rewriting
the experiment. Selections registered BEFORE 2026-08-20 belong to ledger 1 only (PRE_AMENDMENT) —
the owner barred retroactive gating of the 8/19 grades.

UNITS: home_cover_delta is SPREAD POINTS. Moneyline edges elsewhere are PROBABILITY PERCENTAGE
POINTS. The two never share a threshold or a sentence without their unit named.
"""
import json, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)
SELECTIONS = "data/wnba/forecasts/ats_selections.jsonl"
GRADES = "data/wnba/forecasts/grades.jsonl"
AMENDMENT_EFFECTIVE = "2026-08-20"

sys.path.insert(0, os.path.join(BASE, "harness"))
from unified_card import wnba_ats_status, WNBA_ATS_DEADBAND_PTS


def _rows(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def _selected_is_market_dog(sel):
    """Selections bind the SELECTED team's own line at registration (TOR +9.5 stores 9.5).
    The selected side is the market underdog iff it receives points: line > 0."""
    return (sel.get("line") or 0) > 0


def build():
    sels = _rows(SELECTIONS)
    grades = {g.get("ats_selection_id"): g for g in _rows(GRADES) if g.get("estimand") == "ATS"}
    led = {"FULL": [], "ACTION_ELIGIBLE": [], "BLOCKED_SUBSET": []}
    for s in sels:
        sid = s["ats_selection_id"]
        g = grades.get(sid)
        reg_date = (s.get("captured_at_utc") or "")[:10]
        pre = reg_date < AMENDMENT_EFFECTIVE
        status = ("PRE_AMENDMENT" if pre else
                  wnba_ats_status(s.get("home_cover_delta"), _selected_is_market_dog(s)))
        row = {"ats_selection_id": sid, "selected_team": s.get("selected_team"),
               "line_spread_points": s.get("line"),
               "home_cover_delta_spread_points": s.get("home_cover_delta"),
               "gate_class": status,
               "result": (g or {}).get("ats_result", "PENDING")}
        led["FULL"].append(row)
        if not pre:
            if status == "ATS_DIAGNOSTIC_ONLY":
                led["ACTION_ELIGIBLE"].append(row)
            else:
                led["BLOCKED_SUBSET"].append(row)
    def rec(rows):
        w = sum(1 for r in rows if r["result"] == "WIN")
        l = sum(1 for r in rows if r["result"] == "LOSS")
        p = sum(1 for r in rows if r["result"] == "PUSH")
        return {"n_graded": w + l + p, "W-L-P": f"{w}-{l}-{p}",
                "pending": sum(1 for r in rows if r["result"] == "PENDING")}
    return {"amendment_effective": AMENDMENT_EFFECTIVE,
            "deadband_spread_points": WNBA_ATS_DEADBAND_PTS,
            "records": {k: rec(v) for k, v in led.items()},
            "ledgers": led,
            "note": "ledger 1 is the experiment; ledgers 2+3 partition its post-amendment rows. "
                    "Gate classifies, never filters registration or grading."}


def selftest():
    fails = []
    fake_sels = [
        {"ats_selection_id": "A", "game_ref": "X@Y:2026-08-19", "captured_at_utc": "2026-08-19T05:30:00Z",
         "selected_team": "Y", "line": 2.5, "home_cover_delta": 0.97},
        {"ats_selection_id": "B", "game_ref": "X@Y:2026-08-21", "captured_at_utc": "2026-08-21T05:30:00Z",
         "selected_team": "X", "line": -3.5, "home_cover_delta": -4.2},
        {"ats_selection_id": "C", "game_ref": "X@Y:2026-08-21", "captured_at_utc": "2026-08-21T05:30:00Z",
         "selected_team": "X", "line": 6.5, "home_cover_delta": -4.2},
    ]
    import unittest.mock as _m
    global _rows
    orig = _rows
    try:
        _rows_map = {SELECTIONS: fake_sels, GRADES: []}
        _rows = lambda p: _rows_map.get(p, [])
        out = build()
        classes = {r["ats_selection_id"]: r["gate_class"] for r in out["ledgers"]["FULL"]}
        if classes["A"] != "PRE_AMENDMENT":
            fails.append("8/19 selection retro-gated — owner barred this")
        if classes["B"] != "ATS_DIAGNOSTIC_ONLY":
            fails.append("post-amendment favorite read >=2.0 not action-eligible")
        if classes["C"] != "MARGIN_COMPRESSION_BLOCK":
            fails.append("post-amendment dog read not blocked")
        if len(out["ledgers"]["FULL"]) != 3:
            fails.append("FULL ledger filtered — must carry every selection")
        if len(out["ledgers"]["ACTION_ELIGIBLE"]) != 1 or len(out["ledgers"]["BLOCKED_SUBSET"]) != 1:
            fails.append("post-amendment rows do not partition into ledgers 2+3")
    finally:
        _rows = orig
    print("ats_ledgers selftest:", "PASS" if not fails else f"FAIL {fails}")
    return fails


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(1 if selftest() else 0)
    print(json.dumps(build(), indent=1))
