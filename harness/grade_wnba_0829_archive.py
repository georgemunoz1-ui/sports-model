#!/usr/bin/env python3
"""Grade the 2026-08-29 WNBA forecasts against the wehoop archive.

Two things this module refuses to do, both because they have already caused damage:

1. It does not slice on the UTC date. TOR@PHX tipped 2026-08-30T02:00Z, which is the ET
   EVENING of 8/29. A UTC slice files it under 8/30 and splits the cohort -- the exact
   RESULT_DATE_COHORT_CONTAMINATION door found this week. The ET date is derived with
   zoneinfo from the UTC instant.

2. It does not type its counters. Every counter comes out of
   result_binding_gate.binding_proof, and aggregate_guard runs inside that call, so a
   cohort that fails to bind cannot have a Brier score published over it.

The forecasts graded here carry grade SELF_ASSERTED_PREGAME. They were produced and
recorded in data/audit/2026-08-29_card_refresh.json but were never frozen into a
registered board. That is a WEAKER warrant than a frozen board and is stamped as such on
every row. The provenance that makes them prospective at all is the extension sha and the
retrieval timestamp, both of which predate the tips.
"""
import json, os, sys, hashlib, math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from result_binding_gate import binding_proof, guarded_aggregate, AggregateRefused

import pandas as pd

ET = ZoneInfo("America/New_York")
SLATE_DATE = "2026-08-29"
WEHOOP = "/home/user/sportsdataverse/wehoop-wnba-raw"
SCHED_REL = "wnba/schedules/parquet/wnba_schedule_2026.parquet"

# Recorded 2026-08-30T03:06:19Z in data/audit/2026-08-29_card_refresh.json, from a feature
# run retrieved 2026-08-29T08:23:35Z against extension sha256 2373022d... Both tips are
# later than that run, which is what makes these prospective rather than post hoc.
FORECASTS = {
    "ESPN_GAMEID:401857184": {"game": "wnba:CHI@NYL", "p_home": 0.6968,
                              "margin_home": 6.21, "total": 176.6},
    "ESPN_GAMEID:401857185": {"game": "wnba:TOR@PHX", "p_home": 0.6115,
                              "margin_home": 3.43, "total": 170.4},
}
PROVENANCE = {
    "grade": "SELF_ASSERTED_PREGAME",
    "weaker_than": "a frozen registered board",
    "why_prospective": "the feature run was retrieved 2026-08-29T08:23:35Z; CHI@NYL tipped "
                       "2026-08-29T17:00Z (+8.6h) and TOR@PHX 2026-08-30T02:00Z (+17.6h)",
    "extension_sha256": "2373022df440b34acc12e408c5cc0916ce0b9ec0d682e4c7181d016f6b856656",
    "recorded_in": "data/audit/2026-08-29_card_refresh.json",
    "standing_gap": "no board was frozen for this slate. A forecast that never became an "
                    "artifact is a forecast that cannot be scored cleanly, and the only "
                    "reason it is scoreable at all is that the conversation record carries "
                    "the retrieval timestamp and the source sha.",
}

# data/audit/2026-08-30_sigma_provenance_register.json -- MEASURED, n=1721 each.
SIGMA_MARGIN = 12.5523
SIGMA_TOTAL = 18.0156


def et_date(ts):
    """ET calendar date of a UTC instant. NEVER slice on the UTC date."""
    return (datetime.strptime(str(ts).replace("Z", "+0000"), "%Y-%m-%dT%H:%M%z")
            .astimezone(ET).date().isoformat())


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def archive_state():
    import subprocess
    head = subprocess.run(["git", "-C", WEHOOP, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    origin = subprocess.run(["git", "-C", WEHOOP, "rev-parse", "origin/main"],
                            capture_output=True, text=True).stdout.strip()
    when = subprocess.run(["git", "-C", WEHOOP, "log", "-1", "--format=%cI", "origin/main"],
                          capture_output=True, text=True).stdout.strip()
    return {"working_tree_head": head, "origin_main": origin,
            "origin_main_committed": when,
            "note": "the working tree stays at its pin; the snapshot is read out of the "
                    "fetched commit with git show, so the pin is not silently advanced"}


def load_snapshot(path):
    d = pd.read_parquet(path)
    d["game_id"] = d["game_id"].astype(str)
    return d


def build_result_rows(df):
    """Every ET-8/29 game in the archive, not just the two we forecast.

    Cohort coverage is part of the binding contract: a metric computed over a subset that
    was silently narrowed is the 8/27 defect wearing different clothes.
    """
    rows, slate = [], []
    for _, r in df.iterrows():
        d = et_date(r["date"])
        if d != SLATE_DATE:
            continue
        slate.append(str(r["game_id"]))
        if str(r["status_type_name"]) != "STATUS_FINAL":
            continue
        away = str(r["away_display_name"])
        home = str(r["home_display_name"])
        rows.append({
            "sport": "wnba",
            "game_pk": f"ESPN_GAMEID:{r['game_id']}",
            "scheduled_date": d,
            "result_date": d,
            "away": away, "home": home,
            "away_score": int(r["away_score"]), "home_score": int(r["home_score"]),
            "utc_instant": str(r["date"]),
            "utc_date_would_have_been": str(r["date"])[:10],
        })
    return rows, sorted(set(slate))


def make_board(rows):
    games = {}
    for r in rows:
        games[f"wnba:{r['away']}@{r['home']}"] = {
            "game_pk": r["game_pk"], "away": r["away"], "home": r["home"],
            "start_utc": r["utc_instant"]}
    return {"sport": "wnba", "slate_date": SLATE_DATE, "games": games}


def grade(rows):
    out = []
    for r in rows:
        pk = r["game_pk"]
        f = FORECASTS.get(pk)
        if f is None:
            out.append({"game_pk": pk, "matchup": f"{r['away']}@{r['home']}",
                        "final": f"{r['away_score']}-{r['home_score']}",
                        "forecast": None,
                        "disposition": "NO_FORECAST — in the ET slate, never forecast. "
                                       "Listed so the cohort denominator is visible."})
            continue
        home_won = r["home_score"] > r["away_score"]
        m_act = r["home_score"] - r["away_score"]
        t_act = r["home_score"] + r["away_score"]
        brier = (f["p_home"] - (1.0 if home_won else 0.0)) ** 2
        p = f["p_home"] if home_won else 1 - f["p_home"]
        m_res = f["margin_home"] - m_act
        t_res = f["total"] - t_act
        out.append({
            "game_pk": pk, "game": f["game"],
            "matchup": f"{r['away']}@{r['home']}",
            "final": f"{r['away']} {r['away_score']} - {r['home']} {r['home_score']}",
            "utc_instant": r["utc_instant"],
            "et_date_derived": r["result_date"],
            "utc_date_would_have_been": r["utc_date_would_have_been"],
            "date_slice_would_have_split_cohort":
                r["utc_date_would_have_been"] != r["result_date"],
            "p_home": f["p_home"], "home_won": home_won,
            "su_correct": (f["p_home"] > 0.5) == home_won,
            "brier": round(brier, 6), "logloss": round(-math.log(max(p, 1e-12)), 6),
            "margin": {
                "projected_home": f["margin_home"], "actual_home": m_act,
                "residual": round(m_res, 4),
                "numerator_base": "MODEL residual (projected home margin minus actual)",
                "denominator_base": "WNBA margin residual SD, MEASURED",
                "sigma": SIGMA_MARGIN, "sigma_n": 1721,
                "z": round(m_res / SIGMA_MARGIN, 4), "base_coherence": "COHERENT"},
            "total": {
                "projected": f["total"], "actual": t_act,
                "residual": round(t_res, 4),
                "numerator_base": "MODEL residual (projected total minus actual)",
                "denominator_base": "WNBA totals residual SD, MEASURED",
                "sigma": SIGMA_TOTAL, "sigma_n": 1721,
                "z": round(t_res / SIGMA_TOTAL, 4), "base_coherence": "COHERENT"},
        })
    return out


def main():
    snap = sys.argv[1]
    df = load_snapshot(snap)
    rows, slate_ids = build_result_rows(df)
    board = make_board(rows)
    proof = binding_proof(rows, board, f"wnba:{SLATE_DATE}")

    try:
        agg = guarded_aggregate(proof, "wnba 2026-08-29 arm statistics")
    except AggregateRefused as e:
        agg = {"permitted": False, "refusal": str(e)}

    graded = grade(rows)
    scored = [g for g in graded if g.get("forecast") is not False and "brier" in g]

    summary = None
    if agg.get("permitted") and scored:
        n = len(scored)
        summary = {
            "n": n,
            "su_record": f"{sum(1 for g in scored if g['su_correct'])}-"
                         f"{sum(1 for g in scored if not g['su_correct'])}",
            "brier": round(sum(g["brier"] for g in scored) / n, 6),
            "logloss": round(sum(g["logloss"] for g in scored) / n, 6),
            "margin_bias": round(sum(g["margin"]["residual"] for g in scored) / n, 4),
            "margin_mae": round(sum(abs(g["margin"]["residual"]) for g in scored) / n, 4),
            "total_bias": round(sum(g["total"]["residual"] for g in scored) / n, 4),
            "total_mae": round(sum(abs(g["total"]["residual"]) for g in scored) / n, 4),
            "accrues": "NOTHING. n=2 at a SELF_ASSERTED_PREGAME warrant. Reported, not "
                       "promoted, and not fed to the estimator.",
        }

    rec = {
        "schema": "ops.wnba_archive_grading.v1",
        "record_id": f"WNBA-ARCHIVE-GRADING-{SLATE_DATE}",
        "slate_date_et": SLATE_DATE,
        "PROVENANCE": PROVENANCE,
        "ARCHIVE": archive_state(),
        "SNAPSHOT": {"path_in_repo": SCHED_REL, "local_copy": snap,
                     "sha256": sha256_file(snap)},
        "COHORT_COVERAGE": {
            "et_slate_game_ids": slate_ids,
            "n_in_et_slate": len(slate_ids),
            "n_final": len(rows),
            "n_forecast": len([g for g in graded if "brier" in g]),
            "note": "the ET slate is enumerated from the archive, not assumed. A forecast "
                    "count below the slate count is disclosed rather than hidden.",
        },
        "BINDING": {"counters": proof["counters"], "gradable": proof["gradable"],
                    "cohort_problems": proof["cohort_problems"],
                    "aggregate_verdict": proof["aggregate_verdict"]},
        "AGGREGATE_GUARD": agg,
        "GAMES": graded,
        "SUMMARY": summary,
        "LEDGER": {"wager_authority": "NO", "exposure_usd": 0, "n_bets": 0, "units": 0.0},
    }
    return rec


if __name__ == "__main__":
    rec = main()
    print(json.dumps(rec, indent=1))
