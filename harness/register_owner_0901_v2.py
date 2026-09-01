#!/usr/bin/env python3
"""REGISTER the owner's 9/1 PA-state shadow forecast v2 (MLB_PA_STATE_2026-09-01_v2).

Supersedes the owner's v1 BY RECORD, not by edit: the v1 registration stands (R6), this file
adds the v2 rows, reconciles them against my v2 freeze, and measures how far the owner's own
numbers moved between their v1 and v2 — the size of the correction the starter layer bought.

Owner-stated basis: no prices used; direct Model% + 100k-trial PA sim; roster-vs-starter
Statcast shrunk hard toward baseline; BOS on a league-average short-workload fallback (TBD).
"""

MODULE_ID = "register_owner_0901_v2"

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SLATE_DATE = "2026-09-01"
FREEZE_V2 = "cards/2026-09-01_mlb_board_FREEZE_v2.json"
OWNER_V1 = "cards/2026-09-01_mlb_owner_shadow_v1.json"
OUT_CARD = "cards/2026-09-01_mlb_owner_shadow_v2.json"

# LITERAL transcription. p_home in percent. ARI normalised to AZ.
OWNER_ROWS_V2 = [
    ("SD@CIN",  44.32, 43.52, "SD 4.76-3.89",  []),
    ("SF@PIT",  56.37, 53.75, "PIT 4.64-4.53", []),
    ("NYM@TB",  56.37, 53.92, "TB 4.69-4.53",  []),
    ("TOR@CLE", 56.42, 57.27, "CLE 4.28-3.78", []),
    ("SEA@BOS", 58.89, 58.33, "BOS 3.95-3.44", ["BOS_SP_TBD_LEAGUE_AVG_FALLBACK"]),
    ("ATL@WSH", 47.22, 45.66, "ATL 6.01-5.24", []),
    ("DET@MIN", 40.27, 37.11, "DET 4.43-2.99", []),
    ("MIA@KC",  51.91, 49.88, "SPLIT",         ["MODEL_SIM_DIRECTION_SPLIT"]),
    ("MIL@CHC", 51.05, 52.02, "CHC 4.35-4.40", []),
    ("ATH@TEX", 56.97, 58.32, "TEX 4.95-4.35", []),
    ("CWS@HOU", 35.93, 32.88, "CWS 6.12-3.95", []),
    ("BAL@COL", 38.45, 36.50, "BAL 7.07-5.07", ["COORS_TOTAL_NOT_AN_OVER_REC"]),
    ("NYY@LAA", 37.20, 33.79, "NYY 4.58-2.89", ["BVP_UNFAVOURABLE_TO_COLE_APPLIED"]),
    ("PHI@AZ",  52.41, 51.76, "AZ 3.99-3.91",  []),
    ("STL@LAD", 57.00, 60.29, "LAD 4.21-3.49", []),
]

OWNER_META_V2 = {
    "record_name": "MLB_PA_STATE_2026-09-01_v2", "status": "SHADOW_FORECAST",
    "market_used": False, "trials": 100000, "probable_starters": "29/30 (BOS TBD)",
    "supersedes": "owner shadow v1 - starter state was wrong for multiple games there",
    "warrant": "OWNER_RELAY; probabilities are the owner's",
}


def reconcile():
    fz = {g["event"]: g for g in json.load(open(FREEZE_V2))["games"]}
    v1 = {r["event"]: r for r in json.load(open(OWNER_V1))["rows"]}
    rows = []
    agree = 0
    for event, m_home, s_home, score, flags in OWNER_ROWS_V2:
        g = fz[event]
        p_raw = g["forecast"]["p_home"]
        o_avg = (m_home + s_home) / 200.0
        r1 = v1[event]
        o1_avg = (r1["model_home_pct"] + r1["sim_home_pct"]) / 200.0
        agree += (p_raw > 0.5) == (o_avg > 0.5)
        rows.append({
            "event": event, "owner_model_home": m_home / 100.0,
            "owner_sim_home": s_home / 100.0, "owner_avg_home": round(o_avg, 4),
            "owner_sim_runs": score, "owner_flags": flags,
            "owner_v1_avg_home": round(o1_avg, 4),
            "owner_v2_minus_v1_pp": round(100 * (o_avg - o1_avg), 2),
            "freeze_v2_p_home_raw": round(p_raw, 4),
            "freeze_minus_owner_pp": round(100 * (p_raw - o_avg), 2),
            "direction_agrees": (p_raw > 0.5) == (o_avg > 0.5),
        })
    moves = sorted(rows, key=lambda r: -abs(r["owner_v2_minus_v1_pp"]))
    return {"n": len(rows), "direction_agreement_with_freeze": "%d/%d" % (agree, len(rows)),
            "largest_owner_self_corrections_pp": [
                {"event": r["event"], "moved_pp": r["owner_v2_minus_v1_pp"]}
                for r in moves[:5]],
            "rows": rows}


def build_card():
    return {"schema": "ops.owner_shadow_board.v2", "sport": "mlb", "slate_date": SLATE_DATE,
            "record_id": "2026-09-01_mlb_owner_shadow_v2",
            "OWNER_META": OWNER_META_V2,
            "rows": [{"event": e, "model_home_pct": m, "sim_home_pct": s,
                      "sim_runs": sc, "flags": fl} for e, m, s, sc, fl in OWNER_ROWS_V2],
            "RECONCILIATION": reconcile(),
            "LEDGER": {"wager_authority": "NO", "exposure_usd": 0, "n_bets": 0, "units": 0.0},
            "MARKET": "NOT JOINED at registration"}


def selftest():
    f = []
    evs = [e for e, *_ in OWNER_ROWS_V2]
    if len(evs) != 15 or len(set(evs)) != 15:
        f.append("not 15 unique games")
    if any("ARI" in e for e in evs):
        f.append("ARI leaked through AZ normalisation")
    split = [x for x in OWNER_ROWS_V2 if x[0] == "MIA@KC"][0]
    if (split[1] > 50) == (split[2] > 50):
        f.append("MIA@KC direction split lost in transcription")
    r = reconcile()
    if r["n"] != 15:
        f.append("reconciliation dropped rows")
    print("%s selftest: %s" % (MODULE_ID, "PASS" if not f else "FAIL"))
    for x in f:
        print("  -", x)
    return not f


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    card = build_card()
    with open(OUT_CARD, "w") as fh:
        json.dump(card, fh, indent=1, sort_keys=True)
    print("registered ->", OUT_CARD)
    r = card["RECONCILIATION"]
    print(json.dumps({k: r[k] for k in ("direction_agreement_with_freeze",
                                        "largest_owner_self_corrections_pp")}, indent=1))
