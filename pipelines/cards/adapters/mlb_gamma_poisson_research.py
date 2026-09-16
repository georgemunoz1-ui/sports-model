"""MLB diagnostic-card adapter wired to the registered Gamma-Poisson engine.

Schedule/team run context comes from MLB StatsAPI at runtime. The API is a
live-only source in this adapter: ``as_of_utc`` is a requested cutoff, not a
historical-replay guarantee. Fetch timestamps are therefore captured separately
from the numerical snapshot and surfaced as PIT provenance.

Required starter and team profiles fail closed before simulation. Optional
enrichments remain explicit limitations; this adapter remains diagnostic-only.
"""
from __future__ import annotations

import json
import math
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from models.mlb.monte_carlo_v1 import run as run_mc

CONFIG = Path("data/models/mlb/v13_1_monte_carlo_config_v1.json")
PARKS = Path("data/backfill/mlb/2026/park_factors.json")
BASE = "https://statsapi.mlb.com/api/v1"


def _utcnow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _record_fetch(pit, label, fetched_at_utc):
    if pit is None:
        return
    pit.setdefault("source_fetches", []).append(
        {
            "source": "MLB StatsAPI",
            "label": label,
            "fetched_at_utc": fetched_at_utc,
        }
    )


def _get(url, pit=None, label=None):
    req = urllib.request.Request(url, headers={"User-Agent": "sports-model-diagnostic/1.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = json.load(response)
    _record_fetch(pit, label or url, _utcnow())
    return payload


def load_schedule(card_date, as_of_utc):
    data = _get(f"{BASE}/schedule?sportId=1&date={card_date}&hydrate=probablePitcher,venue")
    schedule_fetch_timestamp_utc = _utcnow()
    rows = []
    for date_row in data.get("dates", []):
        for game in date_row.get("games", []):
            rows.append(
                {
                    "event_id": str(game["gamePk"]),
                    "away_team": game["teams"]["away"]["team"]["name"],
                    "home_team": game["teams"]["home"]["team"]["name"],
                    "start_time_utc": game["gameDate"],
                    "away_team_id": game["teams"]["away"]["team"]["id"],
                    "home_team_id": game["teams"]["home"]["team"]["id"],
                    "away_sp": game["teams"]["away"].get("probablePitcher"),
                    "home_sp": game["teams"]["home"].get("probablePitcher"),
                    "venue": game.get("venue", {}).get("name"),
                    # Provenance-only field. It is intentionally excluded from
                    # the engine input snapshot and therefore cannot perturb the
                    # deterministic forecast hash/seed.
                    "_schedule_fetch_timestamp_utc": schedule_fetch_timestamp_utc,
                }
            )
    return rows


def _standings(pit):
    data = _get(
        f"{BASE}/standings?leagueId=103,104&season=2026&standingsTypes=regularSeason",
        pit,
        "standings:2026:regularSeason",
    )
    out = {}
    for record in data.get("records", []):
        for team_record in record.get("teamRecords", []):
            team_id = int(team_record["team"]["id"])
            games_played = int(team_record.get("gamesPlayed") or 0)
            runs_scored = team_record.get("runsScored")
            runs_allowed = team_record.get("runsAllowed")
            if games_played and runs_scored is not None and runs_allowed is not None:
                out[team_id] = {
                    "rf_pg": float(runs_scored) / games_played,
                    "ra_pg": float(runs_allowed) / games_played,
                }
    return out


def _pitcher(person, pit, label):
    if not person or not person.get("id"):
        return None
    pitcher_id = int(person["id"])
    try:
        data = _get(
            f"{BASE}/people/{pitcher_id}/stats?stats=season&group=pitching&season=2026",
            pit,
            f"pitcher:{pitcher_id}:{label}",
        )
        splits = data.get("stats", [{}])[0].get("splits", [])
        if not splits:
            return None
        stat = splits[0].get("stat", {})
        batters_faced = float(stat.get("battersFaced") or 0)
        strikeouts = float(stat.get("strikeOuts") or 0)
        walks = float(stat.get("baseOnBalls") or 0)
        return {
            "id": pitcher_id,
            "name": person.get("fullName"),
            "era": stat.get("era"),
            "gs": stat.get("gamesStarted", 0),
            "k": 100 * strikeouts / batters_faced if batters_faced else None,
            "bb": 100 * walks / batters_faced if batters_faced else None,
        }
    except Exception:
        return None


def build_context(schedule, as_of_utc, allow_stale=True, overrides_path=None):
    if not CONFIG.exists():
        raise RuntimeError(f"MODEL_STATE_UNAVAILABLE:{CONFIG}")

    schedule_timestamps = sorted(
        {
            row.get("_schedule_fetch_timestamp_utc")
            for row in schedule
            if row.get("_schedule_fetch_timestamp_utc")
        }
    )
    pit = {
        "requested_as_of_utc": as_of_utc,
        "pit_mode": "LIVE_SNAPSHOT",
        "pit_reconstruction_supported": False,
        "adapter_source": "MLB StatsAPI",
        "data_vintage_basis": "LIVE_FETCH_TIMESTAMP_PROXY_NOT_SOURCE_EFFECTIVE_TIME",
        "source_fetches": [
            {
                "source": "MLB StatsAPI",
                "label": "schedule",
                "fetched_at_utc": ts,
            }
            for ts in schedule_timestamps
        ],
    }

    standings = _standings(pit)
    parks = json.loads(PARKS.read_text()) if PARKS.exists() else {}
    overrides = {}
    if overrides_path:
        payload = json.loads(Path(overrides_path).read_text())
        items = payload if isinstance(payload, list) else [payload]
        overrides = {str(item["event_id"]): item for item in items}

    return {
        "config": json.loads(CONFIG.read_text()),
        "standings": standings,
        "parks": parks,
        "overrides": overrides,
        "as_of_utc": as_of_utc,
        "pit_provenance": pit,
    }


def _poisson_win_prob(mu_home, mu_away, limit=30):
    # Deterministic point estimate for Analytic P: independent-Poisson score model
    # at the engine-implied mean runs. Ties split 50/50. Stochastic Sim P remains
    # the registered Gamma-Poisson empirical path fraction and is never averaged in.
    home_pmf = [math.exp(-mu_home)]
    away_pmf = [math.exp(-mu_away)]
    for k in range(1, limit + 1):
        home_pmf.append(home_pmf[-1] * mu_home / k)
        away_pmf.append(away_pmf[-1] * mu_away / k)
    probability = 0.0
    for home_runs, p_home_runs in enumerate(home_pmf):
        probability += p_home_runs * (sum(away_pmf[:home_runs]) + 0.5 * away_pmf[home_runs])
    return min(1.0, max(0.0, probability))


def _normal_margin_home_win(mean_margin, margin_std):
    if margin_std is None or not math.isfinite(float(margin_std)) or float(margin_std) <= 0:
        return None
    z = float(mean_margin) / float(margin_std)
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def forecast_event(event, context, simulations=100000):
    team_away = context["standings"].get(int(event["away_team_id"]), {})
    team_home = context["standings"].get(int(event["home_team_id"]), {})
    override = context["overrides"].get(str(event["event_id"]), {}).get("overrides", {})
    pit = context["pit_provenance"]

    away_sp = override.get("away_sp") or _pitcher(event.get("away_sp"), pit, "away")
    home_sp = override.get("home_sp") or _pitcher(event.get("home_sp"), pit, "home")

    for side, profile in (("away", away_sp), ("home", home_sp)):
        if not profile or not profile.get("id"):
            raise RuntimeError(f"REQUIRED_STARTER_MISSING:{side}")
        for key in ("era", "gs", "k", "bb"):
            try:
                value = float(profile[key])
            except (KeyError, TypeError, ValueError):
                raise RuntimeError(f"REQUIRED_STARTER_METRIC_MISSING:{side}:{key}")
            if not math.isfinite(value) or value < 0:
                raise RuntimeError(f"INVALID_STARTER_METRIC:{side}:{key}")
    for side, team in (("away", team_away), ("home", team_home)):
        for key in ("rf_pg", "ra_pg"):
            try:
                value = float(team[key])
            except (KeyError, TypeError, ValueError):
                raise RuntimeError(f"REQUIRED_TEAM_BASELINE_MISSING:{side}:{key}")
            if not math.isfinite(value) or value <= 0:
                raise RuntimeError(f"INVALID_TEAM_BASELINE:{side}:{key}")

    snapshot = {
        "event_id": str(event["event_id"]),
        "game_start_utc": event["start_time_utc"],
        "away_team": event["away_team"],
        "home_team": event["home_team"],
        "away_rf_pg": team_away.get("rf_pg"),
        "away_ra_pg": team_away.get("ra_pg"),
        "home_rf_pg": team_home.get("rf_pg"),
        "home_ra_pg": team_home.get("ra_pg"),
        "away_sp": away_sp,
        "home_sp": home_sp,
        "park_factor": context["parks"].get(event.get("venue"), 1.0),
        "venue": event.get("venue"),
    }

    out = run_mc(snapshot, context["config"], int(simulations))
    projection = out["projection"]
    home_analytic = _poisson_win_prob(
        float(projection["home_runs_mean"]),
        float(projection["away_runs_mean"]),
    )
    home_sim = float(projection["home_win_p_sim"])

    home_pick = home_analytic >= 0.5
    analytic_p = home_analytic if home_pick else 1 - home_analytic
    stochastic_sim_p = home_sim if home_pick else 1 - home_sim

    margin_std = projection.get("margin_std")
    home_normal_candidate = _normal_margin_home_win(projection["home_margin_mean"], margin_std)
    candidate_p = None
    if home_normal_candidate is not None:
        candidate_p = home_normal_candidate if home_pick else 1 - home_normal_candidate

    adjustments = list(out.get("quality_adjustments", []))
    if not team_away or not team_home:
        adjustments.append("TEAM_RUN_CONTEXT_PRIOR_FALLBACK")
    if event.get("venue") not in context["parks"]:
        adjustments.append("PARK_NEUTRAL_FALLBACK")

    tier = "BASELINE" if adjustments else "PRIMARY_SHADOW"
    dose = max(0.2, 0.90 - 0.10 * len(adjustments))

    return {
        "forecast_tier": tier,
        "data_quality": out["forecast_quality"],
        "dose": dose,
        "model_winner": event["home_team"] if home_pick else event["away_team"],
        # Backward-compatible names. New renderer exposes the explicit terms.
        "model_p": analytic_p,
        "sim_p": stochastic_sim_p,
        "analytic_p": analytic_p,
        "stochastic_sim_p": stochastic_sim_p,
        "model_p_candidate_normal_margin": candidate_p,
        "model_p_candidate_status": "DIAGNOSTIC_ONLY_NOT_CANONICAL",
        "projected_margin": float(projection["home_margin_mean"]),
        "projected_total": float(projection["total_mean"]),
        "projected_home_runs": float(projection["home_runs_mean"]),
        "projected_away_runs": float(projection["away_runs_mean"]),
        "margin_std": projection.get("margin_std"),
        "total_std": projection.get("total_std"),
        "spread_or_runline": "UNSUPPORTED_SETTLEMENT_NOT_VALIDATED",
        "total_market": "UNSUPPORTED_SETTLEMENT_NOT_VALIDATED",
        "warnings": adjustments,
        "input_snapshot_hash": out["input_snapshot_hash"],
        "model_state_config_hash": out["model_state_config_hash"],
        "model_input_snapshot": snapshot,
        "diagnostics": out.get("diagnostics", {}),
        "simulation": {
            "simulation_engine": out["simulation_engine"],
            "simulation_engine_version": out["simulation_engine_version"],
            "simulation_count": out["simulation_count"],
            "random_seed": out["random_seed"],
            "rng_algorithm": out.get("rng_algorithm"),
        },
        "provenance": {
            "model_id": context["config"]["model_id"],
            "model_version": context["config"]["version"],
            "output_hash": out["output_hash"],
            "analytic_p_definition": "independent-Poisson fixed-rate win probability at engine-implied realized mean runs; ties split 50/50",
            "stochastic_sim_p_definition": "registered Gamma-Poisson empirical win fraction with starter-workload uncertainty",
            "model_p_candidate_definition": "Normal CDF of simulated mean margin divided by simulated margin standard deviation; diagnostic only",
        },
    }

