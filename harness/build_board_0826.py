"""The 2026-08-26 forecast board builder — COMMITTED, reusing the registered 8/25 engine path.

SLATE GRADE. This slate is SEARCH_IDENTIFIED_UNCONFIRMED: every official and aggregator fetch
rung is EGRESS_BLOCKED; search identified 15 games (the same fifteen matchups as 8/25, a series
continuation, concordant across two independent result sets), start times inferred from a listing
whose timezone is not stated (Pacific inferred; flagged per game), and three probable-pitcher
pairs. Snippets identify and never bind: nothing here settles, promotes, or feeds the estimator,
and the binding record carries every rung. TBD slots ride the preregistered CAP treatment.

PROSPECTIVITY. TB@DET's inferred start (17:10Z) is within minutes of the freeze; with the start
time itself unconfirmed, that game's forecast is marked PROSPECTIVITY_NOT_ESTABLISHED and is
excluded from grading unless a confirmed start time proves it was pregame.

WNBA. RJ-005 stands at 0/17 with routes exhausted: per wnba_feature_pipeline, a board built in
this state publishes SYSTEM_FAILURE_WNBA_FEATURE_PIPELINE — the WNBA section carries the failure,
not forecasts.
"""
from __future__ import annotations

MODULE_ID = "build_board_0826"

import datetime as dt
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import build_board_0825 as B

SLATE_DATE = "2026-08-26"
B.SLATE_DATE = SLATE_DATE
B.SLATE_PSV = f"data/mlb/slates/{SLATE_DATE}_slate.psv"

TZ_AMBIGUOUS = "SEARCH_INFERRED_START_TZ_AMBIGUOUS"


def freeze(out_path=f"cards/{SLATE_DATE}_board.json"):
    import math
    games, wide, target, ev = B.build()
    k = wide["k"]

    def logit(p): return math.log(p / (1 - p))
    def sig(z): return 1 / (1 + math.exp(-z))

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    mlb_rows = []
    for g in games:
        prospect = ("PROSPECTIVITY_NOT_ESTABLISHED" if g["start_utc"] <= now
                    else "SELF_ASSERTED_PREGAME")
        base = {"game": g["game"], "sport": "mlb", "gamePk": g["gamePk"],
                "game_start_utc": g["start_utc"], "start_time_grade": TZ_AMBIGUOUS,
                "away_starter": g["away_sp"], "home_starter": g["home_sp"],
                "sp_status": g["sp_status"],
                "starter_identification_grade": "SEARCH_IDENTIFIED_UNCONFIRMED",
                "starter_slots_capped": g["starter_slots_capped"],
                "resolved_information_dose": g["information_dose"],
                "park_factor": g["park_factor"], "forecast_status": "FORECAST_REGISTERED",
                "prospectivity": prospect,
                "action_status": "PASS_REFERENCE_ONLY", "lineups": "UNCONFIRMED_AT_REGISTRATION"}
        sim = g["sim"]
        mlb_rows += [
            dict(base, arm="mlb.winner.EXPANDING_HOME_PRIOR", target="winner",
                 p_home=B.PRIOR_P),
            dict(base, arm="mlb.winner.CHAMPION_V13", target="winner", p_home=sim["p_home"],
                 simulation_trials=B.TRIALS, simulation_seed=g["seed"],
                 simulation_version="v13_1", trial_standard="LEGACY_TRIAL_COUNT",
                 monte_carlo_sd_pp=100 * sim["mc_se"]),
            dict(base, arm="mlb.winner.CHALLENGER_ADAPTIVE", target="winner",
                 p_home=g["p_adaptive"], residual_f=g["residual_f"],
                 simulation_trials=0, simulation_version=B.AC.IDENTITY,
                 identity_note=B.AC.SUPERSEDES),
            dict(base, arm="mlb.winner.CHALLENGER_WIDENED", target="winner",
                 p_home=sig(logit(B.PRIOR_P) + k * g["residual_f"]),
                 simulation_version=f"widened({B.AC.IDENTITY})", widening_k=k),
            dict(base, arm="mlb.total.EXPANDING_TOTAL_PRIOR", target="total",
                 projected_total=B.PRIOR_TOTAL, target_authority="NEVER_DECISION_BEARING"),
            dict(base, arm="mlb.total.CHAMPION_V13", target="total",
                 projected_total=sim["proj_total"], target_authority="NEVER_DECISION_BEARING",
                 simulation_trials=B.TRIALS, simulation_seed=g["seed"]),
        ]

    wnba = {"cohort_id": f"wnba:{SLATE_DATE}",
            "status": "SYSTEM_FAILURE_WNBA_FEATURE_PIPELINE",
            "incident": "data/audit/2026-08-25_system_failure_wnba_feature_pipeline.json "
                        "(19a644a8); RJ-005 0/17, routes exhausted at build time",
            "schedule": "PENDING_IDENTIFICATION — appended when identified; no forecasts are "
                        "generated from a failed pipeline",
            "n_games": None}

    def cohort_hash(rows_):
        return hashlib.sha256(json.dumps(rows_, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()

    board = {
        "record_id": f"BOARD-{SLATE_DATE}",
        "slate_date": SLATE_DATE,
        "generated_at_utc_self_asserted": now,
        "prospectivity": "SELF_ASSERTED_LOCAL until the CI anchor on this push lands; TB@DET "
                         "individually PROSPECTIVITY_NOT_ESTABLISHED if its inferred start "
                         "precedes the freeze",
        "builder": "harness/build_board_0826.py (COMMITTED)",
        "slate_grade": "SEARCH_IDENTIFIED_UNCONFIRMED — see module docstring and the binding "
                       "record; snippets identify and never bind",
        "board_scope": {"n_games": 15, "mlb": 15, "wnba": "SYSTEM_FAILURE"},
        "SEPARATION": "MLB and WNBA are separate cohorts, never pooled",
        "PRIORS": {"mlb_home": {"p": B.PRIOR_P, "n": 1684,
                                "unchanged_because": "no canonical result exists after "
                                                     "2026-08-21; the 8/25 finals are relayed/"
                                                     "derived, not canonical"},
                   "mlb_total": {"runs": B.PRIOR_TOTAL, "n": 1684}},
        "WIDENING": {"formula": "logit(p_wide) = logit(prior) + k * residual_f",
                     "target_sd_pp": target, "solved_k": k, "solver": wide},
        "ADAPTIVE_IDENTITY": {"identity": B.AC.IDENTITY, "supersedes": B.AC.SUPERSEDES},
        "EVIDENCE": ev,
        "cohort_hashes": {"mlb": cohort_hash(mlb_rows)},
        "mlb": {"cohort_id": f"mlb:{SLATE_DATE}", "n_games": 15, "rows": mlb_rows},
        "wnba": wnba,
        "action_authority": "NONE — no market captured for this slate; "
                            "SYSTEM_NOT_DECISION_READY stands; prices attach only as a "
                            "separately hashed overlay after owner relay or rail recovery",
        "LEDGERS": {"model_authorized_wagers_usd": 0, "n_bets": 0},
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(board, fh, indent=1, sort_keys=True)
    return board


if __name__ == "__main__":
    board = freeze()
    print("FROZEN", board["record_id"], "| mlb", board["cohort_hashes"]["mlb"][:8],
          "| generated", board["generated_at_utc_self_asserted"])
    for r in board["mlb"]["rows"]:
        if r["arm"] == "mlb.winner.CHAMPION_V13":
            print(f"  {r['game']:<14} V13 {r['p_home']:.4f} dose {r['resolved_information_dose']}"
                  f" {r['prospectivity']}")
