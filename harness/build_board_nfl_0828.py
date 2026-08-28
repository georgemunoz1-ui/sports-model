"""The 2026-08-28 NFL board — a NO-FORECAST BENCHMARK board, and why that is the correct output.

WHAT THIS BOARD IS NOT ALLOWED TO SAY. The 8/27 NFL board carried the claim that "No NFL model has
EVER been registered in this system" and a status of SYSTEM_FAILURE_NFL_MODEL_NOT_REGISTERED. That
claim is FALSE and was withdrawn by the owner on 2026-08-27 against three recovered artifacts:
nfl.rs.epa_logit_ridge.v0_1.shadow (REJECTED_DO_NOT_USE, append-only invalidation) and v0_2.shadow
(VALIDATED_SHADOW_ARTIFACT) were both built and preregistered. What was true is narrower — the
ACTIVE branch registry carries no NFL model, and the audit generalised that to "ever". The 8/27
board is frozen and stays byte-unchanged under R3; data/audit/2026-08-27_nfl_history_correction.json
supersedes its registry_verdict and status fields. This board states the corrected position.

WHY THERE IS STILL NO FORECAST — a different reason, and a real one. v0_2.shadow passed its
retrospective gate on 1,865 walk-forward predictions (winner Brier 0.2298 vs 0.2497 expanding
baseline, paired CI95 [-0.0261,-0.0137]), but its REGISTERED SCOPE is regular season. Preseason was
excluded at preregistration because planned QB and starter snap share and substitution intent are
not reconstructible historically as pregame timestamped features. Every 8/28 game is preseason.
So the disposition is PRESEASON_EXCLUDED_BY_REGISTERED_SCOPE, not "no model exists" — and the
outcome, no forecast, is unchanged. Reaching outside a registered scope to produce a number would
be worse than producing none.

The fixture rows are benchmark-schedule only: all 10 are REFUSED_NOT_CANONICAL because no canonical
preseason source exists here. nflverse/nfldata games.csv is authoritative for PHASE and structurally
silent on preseason (0 August gamedays in any season, game_type domain {REG,WC,DIV,CON,SB}) — the
absence is the finding, not a gap to fill.

Ids are CAPTURED per game from each game's own ESPN URL and are retained so a future binding pass
has a real key. They are NOT ordered by kickoff and do NOT occupy one contiguous block — three sit
entirely outside the 4018733xx run — so sorting by kickoff and assigning sequentially would have
mis-assigned every row. That is the concrete reason adjacency inference was refused here.

Brier, logloss and EV are NULL BY RULE, not by omission. Wager authority NO. Stake $0.
"""
from __future__ import annotations

MODULE_ID = "build_board_nfl_0828"

import datetime as dt
import hashlib
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

SLATE_DATE = "2026-08-28"
ACQ = f"data/audit/{SLATE_DATE}_schedule_acquisition.json"
CORRECTION = "data/audit/2026-08-27_nfl_history_correction.json"
EARLIEST_START_UTC = "2026-08-28T22:00:00Z"

TEAM_ABBR = {
    "Washington Commanders": "WSH", "Baltimore Ravens": "BAL", "Houston Texans": "HOU",
    "Carolina Panthers": "CAR", "Atlanta Falcons": "ATL", "Miami Dolphins": "MIA",
    "New York Giants": "NYG", "New York Jets": "NYJ", "Tampa Bay Buccaneers": "TB",
    "Jacksonville Jaguars": "JAX", "New Orleans Saints": "NO", "Dallas Cowboys": "DAL",
    "Seattle Seahawks": "SEA", "Kansas City Chiefs": "KC", "Arizona Cardinals": "ARI",
    "Green Bay Packers": "GB", "Cincinnati Bengals": "CIN", "Philadelphia Eagles": "PHI",
    "Minnesota Vikings": "MIN", "Denver Broncos": "DEN",
}

#: Rows where the acquisition itself had to resolve something. Carried so a reader sees which
#: rows rest on a settled contradiction rather than on uncontested reporting.
ROW_RESOLUTIONS = {
    "nfl:NYG@NYJ": "HOME/AWAY RESOLVED 3-1 — one enumeration pass rendered this 'Jets at Giants'; "
                   "three independent sources put the Giants away at MetLife. A reversed home/away "
                   "is the same class of identity error as a reversed starter side.",
}


def freeze(out_path=f"cards/{SLATE_DATE}_nfl_board.json"):
    acq = json.load(open(ACQ))
    corr = json.load(open(CORRECTION))
    nfl = acq["nfl"]

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for g in nfl["rows"]:
        aw, hm = TEAM_ABBR[g["away"]], TEAM_ABBR[g["home"]]
        gid = f"nfl:{aw}@{hm}"
        cid = g["canonical_id"]
        if not re.fullmatch(r"ESPN_GAMEID:\d+", cid):
            raise ValueError(f"UNNORMALIZED_ID {cid!r} on {gid} — every id must be namespaced")
        rows.append({
            "game": gid, "sport": "nfl", "away": g["away"], "home": g["home"],
            "start_utc": g["start_utc"],
            "canonical_id": cid, "id_space": "ESPN_GAMEID", "id_grade": "CAPTURED",
            "id_provenance": g["id_provenance"],
            "row_disposition": "REFUSED_NOT_CANONICAL",
            "resolution_note": ROW_RESOLUTIONS.get(gid),
            # every decision-bearing quantity, stated as null WITH its reason rather than omitted
            "p_home": None, "side": None, "edge": None, "ev": None,
            "brier": None, "logloss": None,
            "null_reason": "PRESEASON_EXCLUDED_BY_REGISTERED_SCOPE",
            "forecast_status": "NO_FORECAST",
            "starters": "NOT_CAPTURED — preseason finales rest starters league-wide, but a "
                        "league-wide tendency is not a per-game attestation and no name may be "
                        "asserted from it",
            "action_status": "NO_RETAINED_MARKET_ARTIFACT",
        })

    if len({r["canonical_id"] for r in rows}) != len(rows):
        raise ValueError("DUPLICATE_CANONICAL_ID on the NFL board")

    def cohort_hash(rows_):
        return hashlib.sha256(json.dumps(rows_, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()

    board = {
        "record_id": f"BOARD-{SLATE_DATE}-NFL",
        "slate_date": SLATE_DATE,
        "sport": "nfl",
        "builder": "harness/build_board_nfl_0828.py (COMMITTED)",
        "forecast_anchor_utc": now,
        "earliest_start_utc": EARLIEST_START_UTC,
        "chronology_status": ("ANCHOR_PRECEDES_EARLIEST_START"
                              if now < EARLIEST_START_UTC else "ANCHOR_AFTER_EARLIEST_START"),
        "competition_phase": "PRESEASON_FINAL_WEEK — determined from nflverse/nfldata games.csv, "
                             "which is authoritative for phase and structurally silent on "
                             "preseason fixtures (0 August gamedays in any season)",
        "n_games": len(rows),
        "status": ["PRESEASON_EXCLUDED_BY_REGISTERED_SCOPE",
                   "DATA_PREPARATION_COMPLETE",
                   "NO_FORECAST",
                   "NO_SELECTION"],
        "REGISTRY_POSITION": {
            "corrected_on": corr["created_utc"],
            "correction_record": CORRECTION,
            "correction_sha256": corr["record_sha256"],
            "what_is_true": (
                "nfl.rs.epa_logit_ridge.v0_2.shadow WAS built and preregistered and PASSED its "
                "retrospective gate (2,895 completed RS games with PBP; 1,865 walk-forward "
                "predictions 2019-2025; winner Brier 0.2298 vs 0.2497 expanding baseline; paired "
                "CI95 [-0.0261,-0.0137] over 124 season-week blocks; margin MAE 10.41 vs 11.14; "
                "total MAE 11.01 vs 10.98 NOT validated, CI crosses zero). Its disposition is "
                "VALIDATED_SHADOW_ARTIFACT / NO_PROMOTE / no live forecast authority / $0. "
                "v0_1.shadow exists as REJECTED_DO_NOT_USE under an append-only invalidation. "
                "What is separately true is narrower: the ACTIVE branch registry carries no NFL "
                "model, and its lineage is not restored — the recorded commits 1d089d45* and "
                "f3cf5b1d* resolve nowhere in local history or the current remote."
            ),
            "withdrawn_and_not_repeated_here": corr["withdrawn_claims"],
            "why_no_forecast_anyway": (
                "the registered scope of v0_2.shadow is REGULAR SEASON. Preseason was excluded at "
                "preregistration because planned QB and starter snap share and substitution intent "
                "are not reconstructible historically as pregame timestamped features. Every 8/28 "
                "game is preseason. The no-forecast outcome is unchanged; only the reason is "
                "corrected, from 'never built' to 'outside registered scope'."
            ),
            "open_work": "RJ-006 — restoration of the immutable v0_2 run directory awaits an owner "
                         "upload; 1 of 6 components closed",
        },
        "GAME_IDENTITY": {
            "field": "canonical_id", "form": "ESPN_GAMEID:<integer>",
            "captured": len(rows), "inferred": 0, "synthetic_pseudo_pks": 0,
            "inference_refused_evidence": (
                "the captured ids are NOT ordered by kickoff and do NOT occupy one contiguous "
                "block. Within 4018733xx: 301=CIN@PHI (8:00), 302=WSH@BAL (6:00), 303=NYG@NYJ "
                "(7:30), 304=ATL@MIA (7:00), 305=SEA@KC (8:00), 306=TB@JAX (7:30), 307=HOU@CAR "
                "(7:00). Sorting by kickoff and assigning sequentially would have mis-assigned "
                "EVERY row. Three more sit entirely outside that block (401873614, 401874048, "
                "401874102), and the 2026 REG week-1 ids interleave below them."
            ),
            "binding_status": "IDENTIFIED, NOT BOUND — retained so a future result-binding pass "
                              "has a real key to archive-verify against",
        },
        "slate_grade": "SEARCH_IDENTIFIED_UNCONFIRMED — benchmark-schedule rows only; "
                       "reconciliation discovered 10 = canonical 0 + refused 10",
        "reconciliation": acq["reconciliation"]["per_sport"]["nfl"],
        "dispositions": ("every row NO_FORECAST with null_reason "
                         "PRESEASON_EXCLUDED_BY_REGISTERED_SCOPE. Brier, logloss and EV are NULL "
                         "BY RULE, not by omission; PENDING is not used, because nothing is "
                         "waiting to arrive."),
        "market": "NO_RETAINED_MARKET_ARTIFACT at freeze. Prices are never predictive features "
                  "and enter only the action/EV overlay, which cannot open without a forecast.",
        "SEPARATION": "MLB, WNBA and NFL are separate cohorts on separate boards, never pooled",
        "wager_authority": "NO",
        "LEDGERS": {"model_authorized_wagers_usd": 0, "n_bets": 0, "units": 0.0},
        "cohort_hashes": {"nfl": cohort_hash(rows)},
        "nfl": {"cohort_id": f"nfl:{SLATE_DATE}", "n_games": len(rows), "rows": rows},
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(board, fh, indent=1, sort_keys=True)
    return board


if __name__ == "__main__":
    b = freeze()
    print("FROZEN", b["record_id"], "| nfl", b["cohort_hashes"]["nfl"][:8],
          "|", b["chronology_status"])
    print("status:", " / ".join(b["status"]))
    for r in b["nfl"]["rows"]:
        note = "  <HOME/AWAY RESOLVED 3-1>" if r["resolution_note"] else ""
        print(f"  {r['game']:<12} {r['canonical_id']:<22} {r['start_utc']}  "
              f"p_home={r['p_home']} ({r['null_reason']}){note}")
