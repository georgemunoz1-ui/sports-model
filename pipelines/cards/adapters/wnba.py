"""Registered WNBA FF7 card adapter.

This adapter binds the common card interface to the selected, pinned
wnba.rs.ff7_logit_ridge.v1_0.shadow implementation. It does not introduce a
new estimator or the blocked RAPM candidate.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from harness import wnba_model_v1 as W
from pipelines.cards.selection import select

ROOT = Path(__file__).resolve().parents[3]
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={date}"


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_json(url):
    req = Request(url, headers={"User-Agent": "sports-model-diagnostic/1.0"})
    with urlopen(req, timeout=20) as response:
        raw = response.read()
    return json.loads(raw), hashlib.sha256(raw).hexdigest(), _now()


def _abbr(competitor):
    return W._xw(str(competitor["team"]["abbreviation"]), 2026)


def load_schedule(card_date, as_of_utc):
    payload, digest, fetched = _get_json(ESPN.format(date=card_date.replace("-", "")))
    rows = []
    for ev in payload.get("events", []):
        comp = ev.get("competitions", [{}])[0]
        sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        if set(sides) != {"home", "away"}:
            continue
        rows.append({
            "event_id": str(ev["id"]),
            "away_team": _abbr(sides["away"]),
            "home_team": _abbr(sides["home"]),
            "start_time_utc": ev["date"],
            "_schedule_fetch_timestamp_utc": fetched,
            "_schedule_source_sha256": digest,
        })
    return rows


def _state():
    games = W.build_games()
    rows, ts, lg = W.make_rows(games)
    model = W.fit_full(rows)
    return games, rows, ts, lg, model


def build_context(schedule, as_of_utc, allow_stale=True, overrides_path=None):
    if overrides_path:
        raise ValueError("WNBA_UNTYPED_OVERRIDES_UNSUPPORTED")
    selection = select("wnba")
    games, rows, ts, lg, model = _state()
    fetched = sorted({r.get("_schedule_fetch_timestamp_utc") for r in schedule if r.get("_schedule_fetch_timestamp_utc")})
    return {
        "selection": selection,
        "games": games,
        "rows": rows,
        "team_state": ts,
        "league_state": lg,
        "model": model,
        "as_of_utc": as_of_utc,
        "pit_provenance": {
            "pit_mode": "LIVE_SCHEDULE_PLUS_PINNED_FEATURE_POOL",
            "pit_reconstruction_supported": False,
            "adapter_source": __name__,
            "data_vintage_basis": "LIVE_SCHEDULE; REGISTERED_FF7_FEATURE_POOL",
            "source_fetches": [
                {"source": "ESPN WNBA scoreboard", "label": "schedule", "fetched_at_utc": x}
                for x in fetched
            ],
        },
    }


def forecast_event(event, context, simulations=100000):
    result = W.predict_slate(
        context["model"], context["team_state"], context["league_state"],
        [(event["away_team"], event["home_team"], event["start_time_utc"])], 2026
    )[0]
    if "p_home" not in result:
        raise RuntimeError("WNBA_REGISTERED_FF7_DATA_BLOCKED:" + result.get("status", "UNKNOWN"))
    p_home = float(result["p_home"])
    margin = float(result["margin_home"])
    total = float(result["total"])
    home_pick = p_home >= 0.5
    winner = event["home_team"] if home_pick else event["away_team"]
    selected_p = p_home if home_pick else 1.0 - p_home
    # FF7 is deterministic and has no registered Monte Carlo layer. Do not invent one.
    snapshot = {
        "event_id": event["event_id"], "away_team": event["away_team"],
        "home_team": event["home_team"], "start_time_utc": event["start_time_utc"],
        "feature_state_as_of": max(g["date"] for g in context["games"]),
        "model_id": context["selection"]["default_model_id"],
    }
    ih = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    return {
        "model_id": context["selection"]["default_model_id"],
        "forecast_tier": "PRIMARY_SHADOW",
        "data_quality": "REGISTERED_FF7_FEATURE_POOL",
        "dose": 0.0,
        "model_winner": winner,
        "model_p": selected_p,
        # Common card schema requires sim_p; for a model with no simulation layer this
        # is explicitly the deterministic registered probability, not a simulated value.
        "sim_p": selected_p,
        "analytic_p": selected_p,
        "stochastic_sim_p": selected_p,
        "probability_estimator": "DETERMINISTIC_NO_REGISTERED_SIMULATION",
        "projected_margin": margin,
        "projected_total": total,
        "projected_home_points": (total + margin) / 2.0,
        "projected_away_points": (total - margin) / 2.0,
        "margin_std": W.MARGIN_SD,
        "spread_or_runline": "MODEL_MARGIN_ONLY_NO_REGISTERED_COVER_SIMULATION",
        "total_market": "MODEL_TOTAL_ONLY_NO_REGISTERED_OU_SIMULATION",
        "warnings": ["FF7_HAS_NO_REGISTERED_MONTE_CARLO_LAYER"],
        "input_snapshot_hash": ih,
        "model_state_config_hash": context["selection"]["policy_sha256"],
        "model_input_snapshot": snapshot,
        "diagnostics": {
            "coherence_gap_pp": result["coherence_gap_pp"],
            "coherence_pass": result["coherence_pass"],
            "games_used": result["games_used"],
            "registered_simulation_count": 0,
            "requested_simulations_ignored": int(simulations),
        },
        "simulation": {
            "status": "NOT_REGISTERED_FOR_FF7",
            "simulation_count": 0,
            "random_seed": None,
        },
        "provenance": {
            "model_id": context["selection"]["default_model_id"],
            "selection_hash": context["selection"]["policy_sha256"],
            "runner": "harness.wnba_model_v1.predict_slate",
        },
        "action_authority": False,
    }
