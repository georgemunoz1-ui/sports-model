"""The 2026-08-27 MLB forecast board builder — COMMITTED, reusing the registered 8/25 engine path.

SLATE GRADE. SEARCH_IDENTIFIED_UNCONFIRMED: statsapi is EGRESS_BLOCKED (fresh receipt in the
schedule record); the 7-game slate was identified across four search passes with both day games
corroborated by venue, and two real gamePks surfaced in mlb.com gameday slugs (823503 HOU@NYY,
824879 LAD@ATL — recorded, pseudo-keys kept for contract continuity). Snippets identify and never
bind: nothing here settles, promotes, or feeds the estimator.

STARTER CLASSES (owner vocabulary 2026-08-27): named-and-resolved slots are PROBABLE (aggregator
naming, not official confirmation); a named pitcher whose public log was never retained is
NAMED_NO_LOG_RETAINED_CAP — the log exists in the world, the CAP is OUR retention gap, and calling
it "NO_LOG" would be false; unresolvable slots are TBD_CAP; the KC@TOR pair is CONFLICT_CAP (two
sources name different starters for both slots — capped until a resolving attestation, revisit at
T-90).

WNBA AND NFL freeze on their own boards: WNBA after the ~10:30Z wehoop commit lands the 8/26 boxes
(feature rebuild through 8/26 precedes any forecast), NFL as a no-forecast data-readiness board
(no registered NFL model exists).
"""
from __future__ import annotations

MODULE_ID = "build_board_0827"

import datetime as dt
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import build_board_0825 as B

SLATE_DATE = "2026-08-27"
B.SLATE_DATE = SLATE_DATE
B.SLATE_PSV = f"data/mlb/slates/{SLATE_DATE}_slate.psv"

EARLIEST_START_UTC = "2026-08-27T17:05:00Z"
TZ_NOTE = "SEARCH_INFERRED_START_ET_STATED"  # times were quoted in ET by multiple passes

#: owner starter-state vocabulary; keyed by (game, side)
STARTER_CLASS_OVERRIDES = {
    ("mlb:KC@TOR", "away"): "CONFLICT_CAP(Noah Cameron|Randy Dobnak)",
    ("mlb:KC@TOR", "home"): "CONFLICT_CAP(Spencer Arrighetti|Spencer Miles)",
}


def owner_class(game, side, raw_status):
    o = STARTER_CLASS_OVERRIDES.get((game, side))
    if o:
        return o
    if raw_status == "RESOLVED":
        return "PROBABLE"
    if raw_status == "OFFICIAL_TBD_CAP":
        return "TBD_CAP"
    if raw_status.startswith(("NO_PID_CAP", "NO_LOG_CAP")):
        # the pitcher has a public record; the retention gap is ours
        return f"NAMED_NO_LOG_RETAINED_CAP[{raw_status}]"
    return raw_status


def freeze(out_path=f"cards/{SLATE_DATE}_mlb_board.json"):
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
        sp_class = {s: owner_class(g["game"], s, g["sp_status"][s]) for s in ("away", "home")}
        base = {"game": g["game"], "sport": "mlb", "gamePk": g["gamePk"],
                "game_start_utc": g["start_utc"], "start_time_grade": TZ_NOTE,
                "away_starter": g["away_sp"], "home_starter": g["home_sp"],
                "sp_status": g["sp_status"], "starter_class": sp_class,
                "starter_identification_grade": "SEARCH_IDENTIFIED_UNCONFIRMED",
                "starter_slots_capped": g["starter_slots_capped"],
                "resolved_information_dose": g["information_dose"],
                "park_factor": g["park_factor"], "forecast_status": "FORECAST_REGISTERED",
                "prospectivity": prospect,
                "action_status": "NO_RETAINED_MARKET_ARTIFACT",
                "lineups": "UNCONFIRMED_AT_REGISTRATION"}
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

    def cohort_hash(rows_):
        return hashlib.sha256(json.dumps(rows_, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()

    board = {
        "record_id": f"BOARD-{SLATE_DATE}-MLB",
        "slate_date": SLATE_DATE,
        "sport": "mlb",
        "forecast_anchor_utc": now,
        "generated_at_utc_self_asserted": now,
        "earliest_start_utc": EARLIEST_START_UTC,
        "chronology_status": ("ANCHOR_PRECEDES_EARLIEST_START"
                              if now < EARLIEST_START_UTC else "ANCHOR_AFTER_EARLIEST_START"),
        "prospectivity_status": "SELF_ASSERTED_LOCAL until the CI anchor on this push lands; "
                                "per-game field carries any exception",
        "builder": "harness/build_board_0827.py (COMMITTED)",
        "model_identity": {"winner": ["mlb.winner.EXPANDING_HOME_PRIOR",
                                      "mlb.winner.CHAMPION_V13 (frozen 2026-08-10, v13_1)",
                                      "mlb.winner.CHALLENGER_ADAPTIVE",
                                      "mlb.winner.CHALLENGER_WIDENED"],
                           "total": ["mlb.total.EXPANDING_TOTAL_PRIOR",
                                     "mlb.total.CHAMPION_V13"]},
        "slate_grade": "SEARCH_IDENTIFIED_UNCONFIRMED — see module docstring and "
                       "data/audit/2026-08-27_schedule_acquisition.json",
        "board_scope": {"n_games": len(games), "mlb": len(games)},
        "SEPARATION": "MLB, WNBA and NFL are separate cohorts on separate boards, never pooled",
        "PRIORS": {"mlb_home": {"p": B.PRIOR_P, "n": 1684,
                                "unchanged_because": "no canonical result exists after "
                                                     "2026-08-21; later finals are relayed/"
                                                     "derived, not canonical"},
                   "mlb_total": {"runs": B.PRIOR_TOTAL, "n": 1684}},
        "WIDENING": {"formula": "logit(p_wide) = logit(prior) + k * residual_f",
                     "target_sd_pp": target, "solved_k": k, "solver": wide},
        "ADAPTIVE_IDENTITY": {"identity": B.AC.IDENTITY, "supersedes": B.AC.SUPERSEDES},
        "EVIDENCE": ev,
        "cohort_hashes": {"mlb": cohort_hash(mlb_rows)},
        "mlb": {"cohort_id": f"mlb:{SLATE_DATE}", "n_games": len(games), "rows": mlb_rows},
        "action_authority": "NONE — NO_RETAINED_MARKET_ARTIFACT for this slate at freeze "
                            "(EGRESS_BLOCKED receipts in 2026-08-27_market_acquisition.json); "
                            "prices attach only as a separately hashed overlay; conservative EV "
                            "unavailable pending the RJ-002 consumption-spec review",
        "LEDGERS": {"model_authorized_wagers_usd": 0, "n_bets": 0, "units": 0.0},
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as fh:
        json.dump(board, fh, indent=1, sort_keys=True)
    return board


if __name__ == "__main__":
    board = freeze()
    print("FROZEN", board["record_id"], "| mlb", board["cohort_hashes"]["mlb"][:8],
          "| anchor", board["forecast_anchor_utc"], board["chronology_status"])
    for r in board["mlb"]["rows"]:
        if r["arm"] == "mlb.winner.CHAMPION_V13":
            print(f"  {r['game']:<14} V13 {r['p_home']:.4f} dose {r['resolved_information_dose']}"
                  f" [{r['starter_class']['away']} / {r['starter_class']['home']}]")
