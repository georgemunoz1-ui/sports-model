"""MLS three-way baseline-only independent-Poisson bridge.

Research diagnostic only. Uses completed pregame GF/GA plus frozen league home/away
goal priors. No XI, injury, news, price, or market feature is permitted.
"""
from __future__ import annotations

import math

MODEL_ID = "mls.independent_poisson_baseline.v0_1.research"
MODEL_VERSION = "0.1.0"
MAX_GOALS = 12
DEFAULT_SHRINKAGE_MATCHES = 8


def _pmf(lam: float) -> list[float]:
    return [math.exp(-lam) * lam**k / math.factorial(k) for k in range(MAX_GOALS + 1)]


def _strength(row: dict, league_mean: float, pseudo_matches: int) -> tuple[float, float]:
    games = float(row["games"])
    gf_rate = (float(row["gf"]) + pseudo_matches * league_mean) / (games + pseudo_matches)
    ga_rate = (float(row["ga"]) + pseudo_matches * league_mean) / (games + pseudo_matches)
    return gf_rate / league_mean, ga_rate / league_mean


def run_baseline(event: dict, teams: dict, league: dict, *, pseudo_matches: int = DEFAULT_SHRINKAGE_MATCHES) -> dict:
    if event.get("market_input_used") not in (None, False):
        raise ValueError("MARKET_INPUT_FORBIDDEN")
    home, away = event["home_team"], event["away_team"]
    if home not in teams or away not in teams:
        raise ValueError("TEAM_STATE_MISSING")
    matches = float(league["matches"])
    home_prior = float(league["home_goals"]) / matches
    away_prior = float(league["away_goals"]) / matches
    league_mean = float(league["goals"]) / (2.0 * matches)

    home_attack, home_defense = _strength(teams[home], league_mean, pseudo_matches)
    away_attack, away_defense = _strength(teams[away], league_mean, pseudo_matches)
    lam_home = home_prior * home_attack * away_defense
    lam_away = away_prior * away_attack * home_defense

    hp, ap = _pmf(lam_home), _pmf(lam_away)
    norm = sum(hp) * sum(ap)
    p_home = p_draw = p_away = 0.0
    mode = (-1.0, 0, 0)
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            p = hp[h] * ap[a] / norm
            if p > mode[0]:
                mode = (p, h, a)
            if h > a:
                p_home += p
            elif h == a:
                p_draw += p
            else:
                p_away += p
    total_p = p_home + p_draw + p_away
    if abs(total_p - 1.0) > 1e-12:
        raise RuntimeError("THREE_WAY_PROBABILITY_CONTRACT_FAIL")
    state = "HOME" if p_home >= max(p_draw, p_away) else ("DRAW" if p_draw >= max(p_home, p_away) else "AWAY")
    return {
        "event_id": event["event_id"],
        "source_schedule_id": event.get("source_schedule_id"),
        "away_team": away,
        "home_team": home,
        "start_time_utc": event["start_time_utc"],
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "p_home_win": p_home,
        "p_draw": p_draw,
        "p_away_win": p_away,
        "expected_home_goals": lam_home,
        "expected_away_goals": lam_away,
        "expected_total_goals": lam_home + lam_away,
        "projected_margin_home": lam_home - lam_away,
        "most_likely_result_state": state,
        "most_likely_score": {"home_goals": mode[1], "away_goals": mode[2], "probability": mode[0]},
        "probability_sum": total_p,
        "distribution_contract": f"INDEPENDENT_POISSON_SCORE_GRID_0_TO_{MAX_GOALS}_RENORMALIZED",
        "starting_xi_state": "UNAVAILABLE_NO_ADJUSTMENT",
        "goalkeeper_state": "UNAVAILABLE_NO_ADJUSTMENT",
        "injury_suspension_state": "UNAVAILABLE_NO_ADJUSTMENT",
        "news_adjustment": 0.0,
        "information_transform": "DISABLED",
        "forecast_status": "BASELINE_DIAGNOSTIC",
        "coverage_label": event.get("coverage_label", "BASELINE_WITH_UNRESOLVED_INPUTS"),
        "market_input_used": False,
        "market_overlay": False,
        "action_authority": False,
    }
