"""NBA diagnostic-card adapter.

Stage-1 execution boundary: canonical future schedule acquisition is live and PIT-stamped.
Forecast generation remains fail-closed until the NBA model state is fitted and the
team/player PIT feature snapshots are materialized.
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
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"


def _utcnow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _dt(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "sports-model-nba/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def load_schedule(card_date, as_of_utc):
    # ESPN is used only for event identity/schedule acquisition here. It contributes
    # no ratings, probabilities, prices, or model parameters.
    query_date = card_date.replace("-", "")
    url = ESPN_SCOREBOARD + "?" + urllib.parse.urlencode({"dates": query_date, "limit": 100})
    fetched_at = _utcnow()
    payload = _get_json(url)
    rows = []
    for event in payload.get("events", []):
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        competition = competitions[0]
        competitors = competition.get("competitors") or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        start = event.get("date") or competition.get("date")
        if not start or _dt(start).astimezone(CARD_TZ).date().isoformat() != card_date:
            continue
        home_team = (home.get("team") or {}).get("abbreviation") or (home.get("team") or {}).get("displayName")
        away_team = (away.get("team") or {}).get("abbreviation") or (away.get("team") or {}).get("displayName")
        if not home_team or not away_team:
            continue
        rows.append({
            "event_id": str(event.get("id") or competition.get("id")),
            "away_team": str(away_team),
            "home_team": str(home_team),
            "start_time_utc": _dt(start).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "_schedule_source": "ESPN_SCOREBOARD",
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
                "source": "ESPN_SCOREBOARD",
                "purpose": "NBA_SCHEDULE_ONLY",
                "fetched_at_utc": stamp,
            })
    return {
        "state": state,
        "as_of_utc": as_of_utc,
        "pit_provenance": {
            "pit_mode": "LIVE_SNAPSHOT",
            "pit_reconstruction_supported": False,
            "adapter_source": "ESPN_SCOREBOARD",
            "data_vintage_basis": "FETCH_TIME_PROXY_SCHEDULE_ONLY",
            "source_fetches": fetches,
        },
    }


def forecast_event(event, context, simulations=100000):
    state = context["state"]
    if bool(state.get("fit_required", True)):
        raise RuntimeError("NBA_MODEL_STATE_PARAMETER_ESTIMATION_REQUIRED")

    # These fields are intentionally required rather than synthesized. The next NBA
    # build stage must materialize them from PIT team ratings + EPM/minutes scenarios.
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
        "dose": 0.5,
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
