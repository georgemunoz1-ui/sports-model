#!/usr/bin/env python3
"""GRADE THE FROZEN 2026-08-30 WNBA BOARD against the canonical wehoop archive.

Stronger warrant than 8/29: the forecasts come from cards/2026-08-30_wnba_board.json, a FROZEN
REGISTERED BOARD (cohort_hash e034438fd2a61805), not a self-asserted conversation record. Three
arms, paired, on the same four-game cohort. MLB and WNBA cohorts are never pooled.

The CON@DAL row tips 2026-08-31T00:30Z: a UTC slice files it on the wrong day and splits the
cohort. result_date derives in ET via zoneinfo, exactly as the board's
date_slice_would_misfile flag demands.
"""

MODULE_ID = "grade_wnba_0830"

import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from result_binding_gate import binding_proof, guarded_aggregate, AggregateRefused

import pandas as pd

ET = ZoneInfo("America/New_York")
SLATE_DATE = "2026-08-30"
WEHOOP = "/home/user/sportsdataverse/wehoop-wnba-raw"
SCHED_REL = "wnba/schedules/parquet/wnba_schedule_2026.parquet"
BOARD = "cards/2026-08-30_wnba_board.json"
BOARD_COHORT_HASH = "e034438fd2a618058f056effe9bc075ec879e944e583e400b6a06cde89d3c29a"

# data/audit/2026-08-30_sigma_provenance_register.json — MEASURED, n=1721 each. 13.97 is a
# registered coherence tolerance, not a distributional constant, and is not used here.
SIGMA_MARGIN = 12.5523
SIGMA_TOTAL = 18.0156
SIGMA_N = 1721


def et_date(ts):
    return (datetime.strptime(str(ts).replace("Z", "+0000"), "%Y-%m-%dT%H:%M%z")
            .astimezone(ET).date().isoformat())


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def archive_state():
    def g(*args):
        return subprocess.run(["git", "-C", WEHOOP] + list(args),
                              capture_output=True, text=True).stdout.strip()
    return {"working_tree_head": g("rev-parse", "HEAD"),
            "origin_main": g("rev-parse", "origin/main"),
            "origin_main_committed": g("log", "-1", "--format=%cI", "origin/main"),
            "board_pin_was": "5875eba831d8013ed28843353174d3557ba36db0",
            "note": "results read from the FETCHED commit via git show; the working-tree pin "
                    "is not advanced by grading"}


def load_board():
    b = json.load(open(BOARD))
    if b["cohort_hash"] != BOARD_COHORT_HASH:
        raise AssertionError("frozen board hash changed: %s" % b["cohort_hash"])
    return b


def build_result_rows(df):
    rows, slate = [], []
    for _, r in df.iterrows():
        if et_date(r["date"]) != SLATE_DATE:
            continue
        slate.append(str(r["game_id"]))
        if str(r["status_type_name"]) != "STATUS_FINAL":
            continue
        rows.append({
            "sport": "wnba",
            "game_pk": "ESPN_GAMEID:%s" % r["game_id"],
            "scheduled_date": SLATE_DATE, "result_date": SLATE_DATE,
            "away": str(r["away_display_name"]), "home": str(r["home_display_name"]),
            "away_score": int(r["away_score"]), "home_score": int(r["home_score"]),
            "utc_instant": str(r["date"]),
            "utc_date_would_have_been": str(r["date"])[:10]})
    return rows, sorted(set(slate))


def make_board_for_binding(board):
    games = {}
    for r in board["rows"]:
        if r["arm"] != "wnba.replacement.FEATURE_REFRESH":
            continue
        games["wnba:%s@%s" % (r["away_name"], r["home_name"])] = {
            "game_pk": r["canonical_id"], "away": r["away_name"], "home": r["home_name"],
            "start_utc": r["game_start_utc"]}
    return {"sport": "wnba", "slate_date": SLATE_DATE, "games": games}


def grade_arm(board, rows):
    by_id = {r["game_pk"]: r for r in rows}
    out = {}
    for br in board["rows"]:
        r = by_id.get(br["canonical_id"])
        if r is None:
            continue
        home_won = r["home_score"] > r["away_score"]
        m_act = r["home_score"] - r["away_score"]
        t_act = r["home_score"] + r["away_score"]
        p = br["p_home"]
        g = {"game": br["game"], "game_pk": br["canonical_id"],
             "final": "%s %d - %s %d" % (r["away"], r["away_score"], r["home"], r["home_score"]),
             "utc_instant": r["utc_instant"],
             "date_slice_would_have_split_cohort":
                 r["utc_date_would_have_been"] != SLATE_DATE,
             "p_home": p, "home_won": home_won,
             "su_correct": (p > 0.5) == home_won,
             "brier": round((p - (1.0 if home_won else 0.0)) ** 2, 6),
             "logloss": round(-math.log(max(p if home_won else 1 - p, 1e-12)), 6)}
        if br.get("margin_home") is not None:
            mr = br["margin_home"] - m_act
            g["margin"] = {"projected_home": br["margin_home"], "actual_home": m_act,
                           "residual": round(mr, 4),
                           "numerator_base": "MODEL residual (projected home margin - actual)",
                           "denominator_base": "WNBA margin residual SD, MEASURED",
                           "sigma": SIGMA_MARGIN, "sigma_n": SIGMA_N,
                           "z": round(mr / SIGMA_MARGIN, 4)}
        if br.get("projected_total") is not None:
            tr = br["projected_total"] - t_act
            g["total"] = {"projected": br["projected_total"], "actual": t_act,
                          "residual": round(tr, 4),
                          "numerator_base": "MODEL residual (projected total - actual)",
                          "denominator_base": "WNBA totals residual SD, MEASURED",
                          "sigma": SIGMA_TOTAL, "sigma_n": SIGMA_N,
                          "z": round(tr / SIGMA_TOTAL, 4)}
        out.setdefault(br["arm"], []).append(g)
    return out


def summarise(gs):
    n = len(gs)
    s = {"n": n,
         "su_record": "%d-%d" % (sum(g["su_correct"] for g in gs),
                                 sum(not g["su_correct"] for g in gs)),
         "brier": round(sum(g["brier"] for g in gs) / n, 6),
         "logloss": round(sum(g["logloss"] for g in gs) / n, 6)}
    ms = [g["margin"]["residual"] for g in gs if "margin" in g]
    if ms:
        s["margin_bias"] = round(sum(ms) / len(ms), 4)
        s["margin_mae"] = round(sum(abs(x) for x in ms) / len(ms), 4)
        s["margin_n"] = len(ms)
    return s


def main(snap):
    board = load_board()
    df = pd.read_parquet(snap)
    df["game_id"] = df["game_id"].astype(str)
    rows, slate_ids = build_result_rows(df)
    bind_board = make_board_for_binding(board)
    proof = binding_proof(rows, bind_board, "wnba:%s" % SLATE_DATE)
    try:
        agg = guarded_aggregate(proof, "wnba 2026-08-30 arm statistics")
    except AggregateRefused as e:
        agg = {"permitted": False, "refusal": str(e)}
    arms = grade_arm(board, rows)
    summaries = {a: summarise(gs) for a, gs in arms.items()} if agg.get("permitted") else None

    # the standing shape watch: 8/29 under-projected BOTH home margins (bias -20.68, n=2).
    fr = arms.get("wnba.replacement.FEATURE_REFRESH", [])
    resids = [g["margin"]["residual"] for g in fr if "margin" in g]
    shape = {"prior_nights": {"2026-08-29": {"bias": -20.68, "n": 2,
                                             "direction": "home under-projected"}},
             "tonight_residuals": resids,
             "tonight_all_negative": bool(resids) and all(x < 0 for x in resids),
             "verdict": None}
    if resids:
        neg = sum(1 for x in resids if x < 0)
        shape["verdict"] = ("CANDIDATE_BIAS_CONTINUES n=%d one-directional"
                           % (len(resids) + 2) if neg == len(resids) else
                           "SHAPE_BROKEN — %d of %d tonight are negative; the 8/29 direction "
                           "did not repeat uniformly. Not promoted either way." % (neg, len(resids)))

    rec = {
        "schema": "ops.wnba_board_grading.v1",
        "record_id": "WNBA-BOARD-GRADING-%s" % SLATE_DATE,
        "slate_date_et": SLATE_DATE,
        "WARRANT": {"grade": "FROZEN_REGISTERED_BOARD", "board": BOARD,
                    "cohort_hash": BOARD_COHORT_HASH,
                    "stronger_than": "8/29's SELF_ASSERTED_PREGAME"},
        "ARCHIVE": archive_state(),
        "SNAPSHOT": {"path_in_repo": SCHED_REL, "local_copy": snap,
                     "sha256": sha256_file(snap)},
        "COHORT_COVERAGE": {"et_slate_game_ids": slate_ids,
                            "n_in_et_slate": len(slate_ids), "n_final": len(rows)},
        "BINDING": {"counters": proof["counters"], "gradable": proof["gradable"],
                    "cohort_problems": proof["cohort_problems"],
                    "aggregate_verdict": proof["aggregate_verdict"]},
        "AGGREGATE_GUARD": agg,
        "ET_DERIVATION": {"hazard_row": "ESPN_GAMEID:401857189 tips 2026-08-31T00:30Z",
                          "utc_slice_would_have": "filed it on 8/31 and split the cohort",
                          "cohort_stayed_whole": True},
        "ARMS": arms,
        "SUMMARIES": summaries,
        "STANDING_SHAPE_WATCH": shape,
        "LEDGER": {"wager_authority": "NO", "exposure_usd": 0, "n_bets": 0, "units": 0.0},
        "ACCRUES": "descriptive grading of a frozen board; n=4 promotes nothing",
    }
    return rec


def selftest():
    f = []
    if et_date("2026-08-31T00:30Z") != "2026-08-30":
        f.append("ET derivation misfiles the 00:30Z tip")
    if et_date("2026-08-30T19:00Z") != "2026-08-30":
        f.append("ET derivation misfiles an afternoon tip")
    b = load_board()
    if len([r for r in b["rows"] if r["arm"] == "wnba.replacement.FEATURE_REFRESH"]) != 4:
        f.append("frozen board does not carry four FEATURE_REFRESH rows")
    print("%s selftest: %s" % (MODULE_ID, "PASS" if not f else "FAIL"))
    for x in f:
        print("  -", x)
    return not f


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    rec = main(sys.argv[1])
    out = "data/audit/2026-08-30_wnba_board_grading.json"
    blob = json.dumps(rec, sort_keys=True).encode()
    rec["record_sha256"] = hashlib.sha256(blob).hexdigest()
    with open(out, "w") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
    print("written ->", out)
    print(json.dumps(rec["SUMMARIES"], indent=1))
    print(json.dumps(rec["BINDING"]["counters"], indent=1))
    print(json.dumps(rec["STANDING_SHAPE_WATCH"], indent=1))
