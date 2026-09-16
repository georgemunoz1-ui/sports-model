#!/usr/bin/env python3
"""Build the CFB and NFL 2026 season-launch shadow artifacts.

``GREEN`` in this module has a deliberately narrow, auditable meaning: a current schedule has
complete canonical identities, a point-in-time-safe shadow forecast path is runnable, and every
in-scope event is represented.  It does *not* authorize a recommendation, price comparison, or
wager.  Those remain separate gates and this module always emits ``action_authority: NO``.

The two sports use deliberately modest, reproducible models while the broader release remains
blocked:

* CFB consumes a frozen end-of-2025 causal-Elo state and the 2026 ESPN-id schedule.  Week-one
  forecasts never consume outcomes from another game in the same week.
* NFL reconstructs a regular-season Elo path from an immutable nflverse games snapshot and applies
  a Platt calibrator fitted only on 2002--2018 before reporting the 2019--2025 validation period.

Both paths are shadow-only.  No market values are read by this module.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import sys

MODULE_ID = "season_launch"

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFB_SCHEDULE = "data/cfb/source/2026-09-03_cfb_schedule.csv"
CFB_STATE = "data/cfb/model/cfb_causal_elo_launch_state_2026-09-03.json"
NFL_GAMES = "data/nfl/source/2026-09-03_nflverse_regular_games.csv"

CFB_MODEL_ID = "cfb.fbs.causal_elo.v1_0.launch_shadow"
NFL_MODEL_ID = "nfl.rs.elo_platt.v1_0.launch_shadow"
NFL_PARAMETERS = {"k": 20.0, "home_advantage": 55.0, "season_regression": 0.75}


def _utc(value: str) -> dt.datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"not a UTC ISO-8601 timestamp: {value!r}")
    return dt.datetime.fromisoformat(value[:-1] + "+00:00")


def _sha(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _read_csv(path: str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _probability(elo_home: float, elo_away: float, home_advantage: float) -> float:
    return 1.0 / (1.0 + 10.0 ** (-((elo_home + home_advantage) - elo_away) / 400.0))


def _mean(values: list[float]) -> float:
    if not values:
        raise ValueError("mean of no values")
    return sum(values) / len(values)


def _brier(rows: list[dict]) -> float:
    return _mean([(row["p"] - row["y"]) ** 2 for row in rows])


def _logloss(rows: list[dict]) -> float:
    return -_mean([
        row["y"] * math.log(min(max(row["p"], 1e-12), 1 - 1e-12))
        + (1 - row["y"]) * math.log(1 - min(max(row["p"], 1e-12), 1 - 1e-12))
        for row in rows
    ])


def _platt_fit(rows: list[dict]) -> dict[str, float]:
    """Fit y ~ logistic(intercept + slope * logit(raw_p)) without dependencies.

    The caller controls the time split.  A singular fit is a data-contract failure rather than a
    reason to fall back to an uncalibrated number silently.
    """
    if len({row["y"] for row in rows}) != 2:
        raise ValueError("PLATT_NEEDS_BOTH_OUTCOME_CLASSES")
    intercept, slope = 0.0, 1.0
    for _ in range(100):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for row in rows:
            p = min(max(float(row["p"]), 1e-9), 1 - 1e-9)
            x = math.log(p / (1 - p))
            q = 1.0 / (1.0 + math.exp(-(intercept + slope * x)))
            w = q * (1 - q)
            residual = row["y"] - q
            g0 += residual
            g1 += residual * x
            h00 += w
            h01 += w * x
            h11 += w * x * x
        determinant = h00 * h11 - h01 * h01
        if abs(determinant) < 1e-14:
            raise ValueError("PLATT_SINGULAR_HESSIAN")
        d0 = (g0 * h11 - g1 * h01) / determinant
        d1 = (g1 * h00 - g0 * h01) / determinant
        intercept += d0
        slope += d1
        if abs(d0) + abs(d1) < 1e-12:
            break
    return {"intercept": intercept, "slope": slope}


def _platt_apply(p: float, calibration: dict[str, float]) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    logit = math.log(p / (1 - p))
    return 1.0 / (1.0 + math.exp(-(calibration["intercept"] + calibration["slope"] * logit)))


def _cfb_rows(schedule_rows: list[dict[str, str]], state: dict, decision_time_utc: str) -> dict:
    anchor = _utc(decision_time_utc)
    if state.get("model_id") != CFB_MODEL_ID:
        raise ValueError("CFB_STATE_MODEL_ID_MISMATCH")
    if _utc(state["training_cutoff_utc"]) >= anchor:
        raise ValueError("CFB_STATE_LOOKAHEAD")
    if len({row.get("game_id") for row in schedule_rows}) != len(schedule_rows):
        raise ValueError("CFB_DUPLICATE_GAME_ID")
    if any(not str(row.get("game_id", "")).isdigit() for row in schedule_rows):
        raise ValueError("CFB_NONCANONICAL_GAME_ID")

    completed = [row for row in schedule_rows if row.get("completed") == "TRUE"]
    for row in completed:
        if row.get("home_points") in {"", "NA"} or row.get("away_points") in {"", "NA"}:
            raise ValueError(f"CFB_COMPLETED_WITHOUT_SCORE:{row['game_id']}")
    params = state["parameters"]
    elos = state["team_elo"]
    events = []
    for row in sorted(schedule_rows, key=lambda r: (r["start_date"], r["game_id"])):
        if (row.get("week") != "1" or row.get("completed") == "TRUE"
                or row.get("home_division") != "fbs" or row.get("away_division") != "fbs"):
            continue
        start = _utc(row["start_date"])
        if start <= anchor:
            continue
        home, away = row["home_team"], row["away_team"]
        if home not in elos or away not in elos:
            raise ValueError(f"CFB_TEAM_STATE_MISSING:{away}@{home}")
        hfa = 0.0 if row.get("neutral_site") == "TRUE" else float(params["home_advantage"])
        p_home = _probability(float(elos[home]), float(elos[away]), hfa)
        events.append({
            "event_key": f"ESPN_GAMEID:{row['game_id']}",
            "canonical_event_id": f"ESPN_GAMEID:{row['game_id']}",
            "start_utc": row["start_date"],
            "away": away,
            "home": home,
            "neutral_site": row.get("neutral_site") == "TRUE",
            "conference_game": row.get("conference_game") == "TRUE",
            "p_home": round(p_home, 6),
            "forecast_status": "SHADOW_FORECAST_READY",
            "action_status": "NO_ACTION",
            "reason_codes": ["ACTION_AUTHORITY_NO", "MARKET_NOT_INGESTED", "V2_INPUT_BLOCKED"],
        })
    return {
        "status": "GREEN",
        "green_scope": "CANONICAL_SCHEDULE_BACKFILL_AND_WEEK1_SHADOW_FORECAST",
        "model_id": CFB_MODEL_ID,
        "canonical_schedule_rows": len(schedule_rows),
        "completed_rows_before_anchor": len(completed),
        "future_week1_fbs_fbs_events": len(events),
        "same_week_results_used": False,
        "validation": state["validation"],
        "events": events,
        "action_authority": "NO",
        "not_green_for": ["V2_INPUT_COMPLETENESS", "MARKET_MAPPING", "EXECUTION"],
    }


def _nfl_shadow(games: list[dict[str, str]]) -> dict:
    regular = [row for row in games if row.get("game_type") == "REG"]
    regular.sort(key=lambda r: (int(r["season"]), r["gameday"], r.get("gametime") or "", r["game_id"]))
    state: dict[str, float] = {}
    previous_season = None
    historical: list[dict] = []
    week_one: list[dict] = []
    for row in regular:
        season = int(row["season"])
        if previous_season is not None and season != previous_season:
            state = {team: 1500.0 + (rating - 1500.0) * NFL_PARAMETERS["season_regression"]
                     for team, rating in state.items()}
        previous_season = season
        home, away = row["home_team"], row["away_team"]
        home_elo, away_elo = state.get(home, 1500.0), state.get(away, 1500.0)
        raw_p = _probability(home_elo, away_elo, NFL_PARAMETERS["home_advantage"])
        has_result = row.get("home_score", "") != "" and row.get("away_score", "") != ""
        if has_result:
            y = int(float(row["home_score"]) > float(row["away_score"]))
            historical.append({"season": season, "week": int(row["week"]), "p": raw_p, "y": y})
            delta = NFL_PARAMETERS["k"] * (y - raw_p)
            state[home] = home_elo + delta
            state[away] = away_elo - delta
        elif season == 2026 and str(row.get("week")) == "1":
            week_one.append({"row": row, "raw_p": raw_p})

    calibration_rows = [row for row in historical if 2002 <= row["season"] <= 2018]
    evaluation_raw = [row for row in historical if 2019 <= row["season"] <= 2025]
    calibration = _platt_fit(calibration_rows)
    evaluation = [{**row, "p": _platt_apply(row["p"], calibration)} for row in evaluation_raw]
    validation_calibration = _platt_fit(evaluation)
    events = []
    for item in week_one:
        row, raw_p = item["row"], item["raw_p"]
        espn = row.get("espn")
        if not espn or not str(espn).isdigit():
            raise ValueError(f"NFL_NONCANONICAL_ESPN_ID:{row['game_id']}")
        events.append({
            "event_key": f"ESPN_GAMEID:{espn}",
            "canonical_event_id": f"ESPN_GAMEID:{espn}",
            "schedule_game_id": row["game_id"],
            "start_local": {"date": row["gameday"], "time": row.get("gametime"),
                            "timezone": "America/New_York"},
            "away": row["away_team"],
            "home": row["home_team"],
            "p_home": round(_platt_apply(raw_p, calibration), 6),
            "forecast_status": "SHADOW_FORECAST_READY",
            "action_status": "NO_ACTION",
            "reason_codes": ["ACTION_AUTHORITY_NO", "QB_OL_INJURY_INPUTS_NOT_BOUND",
                             "MARKET_NOT_INGESTED"],
        })
    if len({event["canonical_event_id"] for event in events}) != len(events):
        raise ValueError("NFL_DUPLICATE_CANONICAL_ID")
    return {
        "status": "GREEN",
        "green_scope": "CANONICAL_REGULAR_SEASON_SCHEDULE_AND_WEEK1_SHADOW_FORECAST",
        "model_id": NFL_MODEL_ID,
        "source_counts": {"regular_season_schedule_rows_2026": sum(
            1 for row in regular if int(row["season"]) == 2026),
            "week1_events": len(events), "historical_regular_results": len(historical)},
        "parameters": NFL_PARAMETERS,
        "calibration_train": {"seasons": [2002, 2018], "n": len(calibration_rows), **calibration},
        "validation_2019_2025": {
            "n": len(evaluation), "brier": round(_brier(evaluation), 6),
            "logloss": round(_logloss(evaluation), 6),
            "calibration_intercept": round(validation_calibration["intercept"], 6),
            "calibration_slope": round(validation_calibration["slope"], 6),
            "season_week_blocks": len({(row["season"], row["week"]) for row in evaluation}),
        },
        "events": events,
        "action_authority": "NO",
        "not_green_for": ["EPA_V0_2_LINEAGE_RESTORATION", "QB_OL_INJURY_INPUTS",
                          "MARKET_MAPPING", "EXECUTION"],
    }


def build(decision_time_utc: str, cfb_schedule_path: str = CFB_SCHEDULE,
          cfb_state_path: str = CFB_STATE, nfl_games_path: str = NFL_GAMES) -> dict:
    # Parse before emitting any data: missing/invalid source is a hard failure, not a partial board.
    _utc(decision_time_utc)
    cfb_schedule = _read_csv(cfb_schedule_path)
    with open(cfb_state_path, encoding="utf-8") as handle:
        cfb_state = json.load(handle)
    nfl_games = _read_csv(nfl_games_path)
    cfb = _cfb_rows(cfb_schedule, cfb_state, decision_time_utc)
    nfl = _nfl_shadow(nfl_games)
    return {
        "schema": "ops.season_launch.v1",
        "launch_id": "SEASON-LAUNCH-2026-09-03",
        "decision_time_utc": decision_time_utc,
        "action_authority": "NO",
        "release_status": "NOT_A_WAGER_RELEASE",
        "green_definition": (
            "GREEN means canonical schedule backfill plus a point-in-time shadow forecast path; "
            "it never implies action authorization."),
        "input_sha256": {
            "cfb_schedule": _sha(cfb_schedule_path),
            "cfb_state": _sha(cfb_state_path),
            "nfl_games": _sha(nfl_games_path),
        },
        "sports": {"cfb": cfb, "nfl": nfl},
    }


def selftest() -> None:
    cfb_state = {
        "model_id": CFB_MODEL_ID,
        "training_cutoff_utc": "2025-12-31T23:59:59Z",
        "parameters": {"home_advantage": 55.0},
        "team_elo": {"A": 1600.0, "B": 1500.0},
        "validation": {"brier": 0.18},
    }
    cfb_schedule = [
        {"game_id": "1", "week": "1", "completed": "TRUE", "home_points": "21",
         "away_points": "14", "home_division": "fbs", "away_division": "fbs",
         "start_date": "2026-09-03T18:00:00Z", "home_team": "A", "away_team": "B",
         "neutral_site": "FALSE", "conference_game": "FALSE"},
        {"game_id": "2", "week": "1", "completed": "FALSE", "home_points": "NA",
         "away_points": "NA", "home_division": "fbs", "away_division": "fbs",
         "start_date": "2026-09-04T18:00:00Z", "home_team": "A", "away_team": "B",
         "neutral_site": "FALSE", "conference_game": "FALSE"},
    ]
    cfb = _cfb_rows(cfb_schedule, cfb_state, "2026-09-03T19:00:00Z")
    assert cfb["status"] == "GREEN" and len(cfb["events"]) == 1
    assert cfb["events"][0]["action_status"] == "NO_ACTION"

    games = []
    for season in range(2002, 2026):
        for index, (home, away) in enumerate((("A", "B"), ("C", "D"), ("A", "C"))):
            home_score = 24 if (season + index) % 2 else 14
            away_score = 14 if home_score == 24 else 24
            games.append({"game_type": "REG", "season": str(season), "week": "1",
                          "gameday": f"{season}-09-01", "gametime": f"1{index}:00",
                          "game_id": f"{season}_{index}", "home_team": home, "away_team": away,
                          "home_score": str(home_score), "away_score": str(away_score),
                          "espn": str(100000 + season * 10 + index)})
    games.extend([
        {"game_type": "REG", "season": "2026", "week": "1", "gameday": "2026-09-09",
         "gametime": "20:20", "game_id": "2026_A_B", "home_team": "A", "away_team": "B",
         "home_score": "", "away_score": "", "espn": "401000001"},
        {"game_type": "REG", "season": "2026", "week": "1", "gameday": "2026-09-10",
         "gametime": "20:20", "game_id": "2026_C_D", "home_team": "C", "away_team": "D",
         "home_score": "", "away_score": "", "espn": "401000002"},
    ])
    nfl = _nfl_shadow(games)
    assert nfl["status"] == "GREEN" and len(nfl["events"]) == 2
    assert all(0 < event["p_home"] < 1 for event in nfl["events"])
    assert _platt_fit([
        {"p": 0.1, "y": 0}, {"p": 0.2, "y": 0}, {"p": 0.3, "y": 0},
        {"p": 0.4, "y": 1}, {"p": 0.5, "y": 0}, {"p": 0.6, "y": 1},
        {"p": 0.7, "y": 1}, {"p": 0.8, "y": 1},
    ])["slope"] > 0
    print("season_launch selftest: OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--decision-time")
    parser.add_argument("--out")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    if not args.decision_time:
        parser.error("--decision-time is required")
    artifact = build(args.decision_time)
    body = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "x", encoding="utf-8") as handle:
            handle.write(body)
    else:
        print(body, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
