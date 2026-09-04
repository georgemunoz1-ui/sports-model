"""NBA diagnostic-card adapter.

Canonical schedule acquisition is isolated from model inference. Forecast generation
remains fail-closed until fitted NBA state and PIT team/player features exist.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from models.nba.efficiency_monte_carlo_v1 import run as run_mc

STATE = Path("data/models/nba/efficiency_monte_carlo_config_v1.json")
CARD_TZ = ZoneInfo("America/New_York")
NBA_SCHEDULE = "https://stats.nba.com/stats/scheduleleaguev2"
NBA_HEADERS = {
    "Host": "stats.nba.com",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
    "Referer": "https://www.nba.com/",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "Sec-Fetch-Dest": "empty",
}


def _utcnow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _dt(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _season_key(card_date):
    date = datetime.fromisoformat(card_date).date()
    start_year = date.year if date.month >= 7 else date.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _get_json(url):
    req = urllib.request.Request(url, headers=NBA_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def _league_schedule(payload):
    for value in payload.values():
        if isinstance(value, dict) and isinstance(value.get("gameDates"), list):
            return value
    raise RuntimeError("NBA_SCHEDULE_RESPONSE_SCHEMA_UNRECOGNIZED")


def load_schedule(card_date, as_of_utc):
    season = _season_key(card_date)
    url = NBA_SCHEDULE + "?" + urllib.parse.urlencode({"LeagueID": "00", "Season": season})
    fetched_at = _utcnow()
    payload = _get_json(url)
    schedule = _league_schedule(payload)
    rows = []
    for date_row in schedule.get("gameDates", []):
        for game in date_row.get("games", []):
            start = game.get("gameDateTimeUTC")
            game_id = game.get("gameId")
            home = game.get("homeTeam") or {}
            away = game.get("awayTeam") or {}
            home_team = home.get("teamTricode")
            away_team = away.get("teamTricode")
            if not start or not game_id or not home_team or not away_team:
                continue
            start_dt = _dt(start)
            if start_dt.astimezone(CARD_TZ).date().isoformat() != card_date:
                continue
            rows.append({
                "event_id": str(game_id),
                "away_team": str(away_team),
                "home_team": str(home_team),
                "start_time_utc": start_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "_schedule_source": "NBA_STATS_SCHEDULELEAGUEV2",
                "_schedule_season": season,
                "_schedule_fetched_at_utc": fetched_at,
            })
    rows.sort(key=lambda row: (row["start_time_utc"], row["event_id"]))
    return rows


def build_context(schedule, as_of_utc, allow_stale=True, overrides_path=None):
    if not STATE.exists():
        raise RuntimeError(f"MODEL_STATE_UNAVAILABLE:{STATE}")
    state = json.loads(STATE.read_text())
    fetches = []
    seen = set()
    for event in schedule:
        stamp = event.get("_schedule_fetched_at_utc")
        if stamp and stamp not in seen:
            seen.add(stamp)
            fetches.append({
                "source": "NBA_STATS_SCHEDULELEAGUEV2",
                "purpose": "NBA_CANONICAL_SCHEDULE",
                "fetched_at_utc": stamp,
                "season": event.get("_schedule_season"),
            })
    return {
        "state": state,
        "as_of_utc": as_of_utc,
        "pit_provenance": {
            "pit_mode": "LIVE_SNAPSHOT",
            "pit_reconstruction_supported": False,
            "adapter_source": "NBA_STATS_SCHEDULELEAGUEV2",
            "data_vintage_basis": "FETCH_TIME_PROXY_SCHEDULE_ONLY",
            "source_fetches": fetches,
        },
    }


def forecast_event(event, context, simulations=100000):
    state = context["state"]
    if bool(state.get("fit_required", True)):
        raise RuntimeError("NBA_MODEL_STATE_PARAMETER_ESTIMATION_REQUIRED")

    snapshot = event.get("_model_input_snapshot")
    if not isinstance(snapshot, dict):
        raise RuntimeError("NBA_PIT_FEATURE_SNAPSHOT_UNAVAILABLE")

    out = run_mc(snapshot, state, int(simulations))
    home_model_p = float(out["model_p"])
    home_sim_p = float(out["sim_p"])
    home_is_pick = home_model_p >= 0.5
    model_p = home_model_p if home_is_pick else 1.0 - home_model_p
    sim_p = home_sim_p if home_is_pick else 1.0 - home_sim_p
    return {
        "forecast_tier": "PRIMARY_SHADOW",
        "data_quality": "PIT_VERIFIED",
        "model_winner": event["home_team"] if home_is_pick else event["away_team"],
        "model_p": model_p,
        "sim_p": sim_p,
        "projected_margin": float(out["projected_margin"]),
        "projected_total": float(out["projected_total"]),
        "projected_home_runs": float(out["home_score_mean"]),
        "projected_away_runs": float(out["away_score_mean"]),
        "spread_or_runline": "SUPPORTED_AFTER_LINE_ATTACH",
        "total_market": "SUPPORTED_AFTER_LINE_ATTACH",
        "warnings": [],
        "input_snapshot_hash": out["input_snapshot_hash"],
        "model_state_config_hash": out["model_state_config_hash"],
        "simulation": out["simulation"],
        "provenance": {
            "model_id": out["model_id"],
            "model_version": out["model_version"],
            "output_hash": out["output_hash"],
            "model_p_definition": "fitted analytic estimator from frozen NBA model state",
            "sim_p_definition": "empirical seeded Monte Carlo win fraction",
            "market_features_used": False,
            "action_authority": False,
        },
    }
