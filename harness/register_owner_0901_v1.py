#!/usr/bin/env python3
"""REGISTER the owner's 9/1 early shadow forecast v1 and RECONCILE it against the frozen board.

TWO ARTIFACTS, TWO AUTHORS, ONE SLATE. cards/2026-09-01_mlb_board_FREEZE.json is my
coordinator freeze (V13, dose-capped, market never read). The owner then delivered a 15-game
Model% + 100k-trial PA-simulation board from a different architecture ("shadow PA-state").
Owner uploads are PARSED, not read: the rows below are a literal transcription and everything
after them is computed. R3: neither board edits the other; the reconciliation is a third record.

TWO STARTER CONFLICTS the relay surfaced, both material:
  CWS@HOU  my search snippet read "Astros: Sean Burke / White Sox: TBD". The owner's relay of
           the MLB scoreboard reads Burke for CHICAGO and Ronel Blanco for HOUSTON. My frozen
           board therefore carries Burke's profile in the WRONG UNIFORM. The freeze stays
           frozen; the defect is recorded here and corrected in the v2 freeze only.
  SEA@BOS  I carried Jedixson Paez (FanGraphs, n=1). The owner's relay says Boston is TBD on
           MLB's own feed. Paez is DOWNGRADED to n=1-contradicted; v2 carries null + reason.
"""

MODULE_ID = "register_owner_0901_v1"

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SLATE_DATE = "2026-09-01"
FREEZE = "cards/2026-09-01_mlb_board_FREEZE.json"
OUT_CARD = "cards/2026-09-01_mlb_owner_shadow_v1.json"

# LITERAL transcription of the owner's board. away/home model and sim are percent of the
# AWAY team unless stated; stored here as p_home to one namespace. sim_score as delivered.
# ARI normalised to AZ (one club, two codes — standing rule).
OWNER_ROWS = [
    # event, model_home_pct, sim_home_pct, sim_score, flags
    ("SD@CIN",  38.8, 41.9, "SD 4.8-3.7",  ["CONVERGENCE_WATCH"]),
    ("SF@PIT",  60.4, 57.5, "PIT 5.1-4.6", []),
    ("NYM@TB",  56.5, 53.8, "TB 4.6-4.5",  []),
    ("TOR@CLE", 57.8, 56.2, "CLE 4.1-3.7", []),
    ("ATL@WSH", 43.4, 44.3, "ATL 6.2-5.3", []),
    ("SEA@BOS", 63.2, 60.8, "BOS 4.3-3.5", ["STARTER_UNCERTAINTY_BOS_TBD"]),
    ("DET@MIN", 35.2, 37.0, "DET 4.4-3.0", []),
    ("MIA@KC",  50.3, 48.5, "MIA 4.4-4.0", ["MODEL_SIM_DIRECTION_SPLIT"]),
    ("MIL@CHC", 51.3, 50.3, "MIL 5.1-4.8", ["MEAN_SCORE_VS_WINPCT_INVERSION_NOTED"]),
    ("ATH@TEX", 54.6, 53.9, "TEX 4.4-4.3", []),
    ("CWS@HOU", 32.3, 37.5, "CWS 5.6-4.0", ["CONVERGENCE_WATCH", "STARTER_ATTRIBUTION_CONFLICT"]),
    ("BAL@COL", 35.7, 39.1, "BAL 7.0-5.3", ["CONVERGENCE_WATCH"]),
    ("NYY@LAA", 27.3, 34.3, "NYY 4.6-2.9", ["CONVERGENCE_WATCH"]),
    ("PHI@AZ",  52.2, 50.7, "PHI 4.2-4.0", ["MEAN_SCORE_VS_WINPCT_INVERSION_NOTED"]),
    ("STL@LAD", 57.8, 55.3, "LAD 4.3-4.1", []),
]

OWNER_META = {
    "architecture": "shadow PA-state (NOT legacy V13): team PA event vectors + starter "
                    "skill/workload + shrinkage + park + home field -> 24 base/out states -> "
                    "TTO degradation -> bullpen phase -> extras; 100,000 trials/game",
    "mc_se_pp": "0.15-0.16 per game (owner-stated)",
    "market_used": False,
    "lineups_confirmed": "0/30",
    "warrant": "OWNER_RELAY - registered as delivered; probabilities are the owner's, not mine",
    "readiness": "EARLY_SHADOW_V1 - rerun pending lineups, BOS starter, bullpen, weather",
}


def load_freeze():
    return json.load(open(FREEZE))


def reconcile():
    fz = {g["event"]: g for g in load_freeze()["games"]}
    rows, problems = [], []
    agree_raw = agree_dosed = 0
    for event, m_home, s_home, sim_score, flags in OWNER_ROWS:
        g = fz.get(event)
        if g is None:
            problems.append({"event": event, "code": "NOT_ON_FROZEN_SCHEDULE"})
            continue
        p_raw = g["forecast"]["p_home"]
        p_dosed = g["forecast"]["p_home_dosed"]
        o_avg = (m_home + s_home) / 200.0
        dir_owner = o_avg > 0.5
        row = {
            "event": event,
            "owner_model_home": m_home / 100.0, "owner_sim_home": s_home / 100.0,
            "owner_avg_home": round(o_avg, 4), "owner_sim_score": sim_score,
            "owner_flags": flags,
            "freeze_p_home_raw": round(p_raw, 4), "freeze_p_home_dosed": round(p_dosed, 4),
            "freeze_dose": g["snapshot"]["resolved_information_dose"],
            "direction_agrees_raw": (p_raw > 0.5) == dir_owner,
            "direction_agrees_dosed": (p_dosed > 0.5) == dir_owner,
            "home_prob_delta_raw_pp": round(100 * (p_raw - o_avg), 2),
        }
        agree_raw += row["direction_agrees_raw"]
        agree_dosed += row["direction_agrees_dosed"]
        rows.append(row)
    for event in fz:
        if event not in {e for e, *_ in OWNER_ROWS}:
            problems.append({"event": event, "code": "ON_FREEZE_MISSING_FROM_RELAY"})
    n = len(rows)
    deltas = sorted(rows, key=lambda r: -abs(r["home_prob_delta_raw_pp"]))
    return {
        "n_owner_rows": len(OWNER_ROWS), "n_matched": n, "problems": problems,
        "schedule_set_identical": not problems,
        "direction_agreement_raw": "%d/%d" % (agree_raw, n),
        "direction_agreement_dosed": "%d/%d" % (agree_dosed, n),
        "largest_disagreements_pp": [
            {"event": r["event"], "delta_pp": r["home_prob_delta_raw_pp"],
             "freeze_raw": r["freeze_p_home_raw"], "owner_avg": r["owner_avg_home"]}
            for r in deltas[:5]],
        "rows": rows,
    }


def starter_conflicts():
    return [
        {"event": "CWS@HOU", "code": "STARTER_ATTRIBUTION_CONFLICT",
         "frozen_board_says": "home_starter Sean Burke, away null (TBD)",
         "owner_relay_says": "Burke starts for CHICAGO, Ronel Blanco for HOUSTON",
         "consequence": "the freeze ran Burke's profile in the wrong uniform",
         "resolution": "freeze stays frozen (R3); v2 freeze carries the relay attribution; "
                       "Blanco is not in the pitcher registry and enters NAMED_NO_LOG_CAP"},
        {"event": "SEA@BOS", "code": "SINGLE_SOURCE_CONTRADICTED",
         "frozen_board_says": "home_starter Jedixson Paez (FanGraphs, n=1)",
         "owner_relay_says": "Boston TBD on MLB's own feed; Bryan Woo (SEA) confirmed",
         "resolution": "Paez downgraded to n=1-contradicted; v2 carries null with reason"},
    ]


def build_card():
    return {
        "schema": "ops.owner_shadow_board.v1", "sport": "mlb", "slate_date": SLATE_DATE,
        "record_id": "2026-09-01_mlb_owner_shadow_v1",
        "OWNER_META": OWNER_META,
        "rows": [{"event": e, "model_home_pct": m, "sim_home_pct": s,
                  "sim_score": sc, "flags": fl} for e, m, s, sc, fl in OWNER_ROWS],
        "RECONCILIATION": reconcile(),
        "STARTER_CONFLICTS": starter_conflicts(),
        "LEDGER": {"wager_authority": "NO", "exposure_usd": 0, "n_bets": 0, "units": 0.0},
        "MARKET": "NOT JOINED - no admissible price board has been relayed for 9/1",
    }


def selftest():
    f = []
    evs = [e for e, *_ in OWNER_ROWS]
    if len(evs) != 15 or len(set(evs)) != 15:
        f.append("owner board is not 15 unique games")
    if any("ARI" in e for e in evs):
        f.append("ARI leaked through the AZ normalisation")
    r = reconcile()
    if r["n_matched"] != 15 or r["problems"]:
        f.append("schedule reconciliation not clean: %r" % r["problems"])
    split = [x for x in OWNER_ROWS if x[0] == "MIA@KC"][0]
    if (split[1] > 50) == (split[2] > 50):
        f.append("MIA@KC transcription lost the direction split")
    if not any("STARTER_ATTRIBUTION_CONFLICT" in x[4] for x in OWNER_ROWS):
        f.append("the CWS@HOU conflict is not flagged on its row")
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
    print(json.dumps({k: r[k] for k in ("schedule_set_identical", "direction_agreement_raw",
                                        "direction_agreement_dosed",
                                        "largest_disagreements_pp")}, indent=1))
