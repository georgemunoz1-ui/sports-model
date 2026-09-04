"""NBA diagnostic-card adapter.

Schedule identity is loaded from immutable source snapshots committed to the repository.
Model inference remains fail-closed until fitted NBA state and PIT team/player features exist.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from models.nba.efficiency_monte_carlo_v1 import run as run_mc

STATE = Path("data/models/nba/efficiency_monte_carlo_config_v1.json")
SCHEDULE_DIR = Path("data/nba/schedule")
CARD_TZ = ZoneInfo("America/New_York")


def _dt(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _season_key(card_date):
    date = datetime.fromisoformat(card_date).date()
    start_year = date.year if date.month >= 7 else date.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _snapshot_path(card_date):
    return SCHEDULE_DIR / f"nba_schedule_snapshot_v1_{card_date}.json"


def load_schedule(card_date, as_of_utc):
    path = _snapshot_path(card_date)
    if not path.exists():
        raise RuntimeError(f"NBA_SCHEDULE_SNAPSHOT_UNAVAILABLE:{path}")
    snapshot = json.loads(path.read_text())
    if snapshot.get("artifact_type") != "nba_schedule_snapshot_v1":
        raise RuntimeError("NBA_SCHEDULE_SNAPSHOT_TYPE_INVALID")
    if snapshot.get("card_date") != card_date:
        raise RuntimeError("NBA_SCHEDULE_SNAPSHOT_DATE_MISMATCH")
    expected_season = _season_key(card_date)
    if snapshot.get("season") != expected_season:
        raise RuntimeError(f"NBA_SCHEDULE_SEASON_MISMATCH:{snapshot.get('season')}!={expected_season}")

    rows = []
    for game in snapshot.get("games", []):
        event_id = game.get("event_id")
        away = game.get("away_team")
        home = game.get("home_team")
        start = game.get("start_time_utc")
        if not event_id or not away or not home or not start:
            raise RuntimeError("NBA_SCHEDULE_CANONICAL_IDENTITY_UNRESOLVED")
        if _dt(start).astimezone(CARD_TZ).date().isoformat() != card_date:
            raise RuntimeError(f"NBA_SCHEDULE_EVENT_DATE_MISMATCH:{event_id}")
        rows.append({
            "event_id": str(event_id),
            "away_team": str(away),
            "home_team": str(home),
            "start_time_utc": str(start),
            "_schedule_source": "IMMUTABLE_NBA_SCHEDULE_SNAPSHOT_V1",
            "_schedule_snapshot_path": str(path),
            "_schedule_source_snapshot_time_utc": (snapshot.get("source") or {}).get("source_snapshot_time_utc"),
            "_schedule_source_blob_sha": (snapshot.get("source") or {}).get("mirror_blob_sha"),
        })
    rows.sort(key=lambda row: (row["start_time_utc"], row["event_id"]))
    if not rows:
        raise RuntimeError("NBA_SCHEDULE_SNAPSHOT_EMPTY")
    return rows


def build_context(schedule, as_of_utc, allow_stale=True, overrides_path=None):
    if not STATE.exists():
        raise RuntimeError(f"MODEL_STATE_UNAVAILABLE:{STATE}")
    state = json.loads(STATE.read_text())
    first = schedule[0] if schedule else {}
    return {
        "state": state,
        "as_of_utc": as_of_utc,
        "schedule_provenance": {
            "artifact_type": "nba_schedule_snapshot_v1",
            "snapshot_path": first.get("_schedule_snapshot_path"),
            "source_snapshot_time_utc": first.get("_schedule_source_snapshot_time_utc"),
            "source_blob_sha": first.get("_schedule_source_blob_sha"),
        },
        # Schedule acquisition is not the model feature-vintage clock. Until team,
        # player and availability PIT inputs exist, model PIT status must remain unknown.
        "pit_provenance": {
            "pit_mode": "IMMUTABLE_SCHEDULE_ONLY",
            "pit_reconstruction_supported": False,
            "adapter_source": "IMMUTABLE_NBA_SCHEDULE_SNAPSHOT_V1",
            "data_vintage_basis": "SCHEDULE_IDENTITY_ONLY_MODEL_INPUT_VINTAGE_UNAVAILABLE",
            "source_fetches": [],
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
