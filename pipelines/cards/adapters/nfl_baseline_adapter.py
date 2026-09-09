"""NFL baseline-only bridge.

Emits a diagnostic model opinion when live availability/news enrichment is absent.
Market inputs and action authority are forbidden. The bridge wraps the existing
nfl.elo_margin_monte_carlo.v1 engine; rating construction must be explicit in the
input snapshot and may not silently consume current injuries or prices.
"""
from __future__ import annotations

from models.nfl import elo_margin_monte_carlo_v1 as engine

DEFAULT_CONFIG = {
    "home_field_points": 1.8,
    "points_per_elo": 0.036,
    "margin_sd": 13.5,
    "total_sd": 10.5,
    "margin_logistic_scale": 8.0,
    "league_total_prior": 44.0,
}


def srs_to_elo_equivalent(srs: float, *, points_per_elo: float = 0.036) -> float:
    """Map zero-centered SRS points to the engine's Elo scale without adding information."""
    return 1500.0 + float(srs) / float(points_per_elo)


def run_baseline(event: dict, historical: dict, n_sims: int = 100_000) -> dict:
    if event.get("market_input_used") not in (None, False):
        raise ValueError("MARKET_INPUT_FORBIDDEN")
    for team in (event["home_team"], event["away_team"]):
        if team not in historical:
            raise ValueError(f"HISTORICAL_TEAM_STATE_MISSING:{team}")

    home = historical[event["home_team"]]
    away = historical[event["away_team"]]
    ppe = DEFAULT_CONFIG["points_per_elo"]
    # Total center is the symmetric prior-season offense/defense blend.
    home_pf = home["points_for"] / home["games"]
    home_pa = home["points_against"] / home["games"]
    away_pf = away["points_for"] / away["games"]
    away_pa = away["points_against"] / away["games"]
    total_prior = 0.5 * (home_pf + away_pa) + 0.5 * (away_pf + home_pa)

    snapshot = {
        "event_id": event["event_id"],
        "home_team": event["home_team"],
        "away_team": event["away_team"],
        "home_elo": srs_to_elo_equivalent(home["srs"], points_per_elo=ppe),
        "away_elo": srs_to_elo_equivalent(away["srs"], points_per_elo=ppe),
        "neutral_site": bool(event.get("neutral_site", False)),
        "home_adjustment_points": 0.0,
        "away_adjustment_points": 0.0,
        "total_prior": total_prior,
    }
    raw = engine.run(snapshot, DEFAULT_CONFIG, n_sims=n_sims)
    return {
        **raw,
        "event_id": event["event_id"],
        "away_team": event["away_team"],
        "home_team": event["home_team"],
        "start_time_utc": event["start_time_utc"],
        "baseline_input_method": "PRIOR_SEASON_SRS_TO_ELO_EQUIVALENT",
        "p_home_baseline": raw["sim_p"],
        "p_away_baseline": 1.0 - raw["sim_p"],
        "projected_home_points": raw["home_score_mean"],
        "projected_away_points": raw["away_score_mean"],
        "information_state": "UNAVAILABLE_BY_BASELINE_CONTRACT",
        "starter_or_qb_state": "UNRESOLVED_NO_ADJUSTMENT",
        "injury_state": "UNAVAILABLE_NO_ADJUSTMENT",
        "practice_state": "UNAVAILABLE_NO_ADJUSTMENT",
        "inactive_state": "UNAVAILABLE_NO_ADJUSTMENT",
        "news_adjustment": 0.0,
        "information_transform": "DISABLED",
        "forecast_status": "BASELINE_DIAGNOSTIC",
        "coverage_label": "BASELINE_WITH_UNRESOLVED_INPUTS",
        "play_label": "NO_PLAY_DIAGNOSTIC",
        "market_input_used": False,
        "market_overlay": False,
        "action_authority": False,
    }
