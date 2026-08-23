#!/usr/bin/env python3
"""Deterministic 2026-08-23 cross-sport reference simulations.

This is a comparison baseline, not a replacement for the owner's trained models.
Forecast production is unconditional.  Action eligibility is a separate field and
must never suppress a forecast row.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass

import numpy as np


SEED = 20260823
N_SIM = 100_000
MLB_LEAGUE_ERA = 4.30
MLB_DISPERSION = 12.0


@dataclass(frozen=True)
class MlbGame:
    game: str
    away_rf: float
    away_ra: float
    home_rf: float
    home_ra: float
    away_sp_era: float | None
    away_sp_gs: int
    home_sp_era: float | None
    home_sp_gs: int
    park_factor: float
    total_line: float
    neutral: bool = False
    action_status: str = "PASS_REFERENCE_ONLY"


MLB = [
    MlbGame("STL@PHI", 4.4, 4.3, 4.5, 4.3, None, 0, None, 0, 1.02, 7.5),
    MlbGame("WSH@MIA", 5.2, 5.1, 4.3, 4.2, None, 0, None, 0, 0.94, 8.5),
    MlbGame("PIT@LAD", 5.0, 4.7, 5.0, 3.8, 3.75, 5, 3.60, 3, 0.96, 8.5),
    MlbGame("CIN@ARI", 4.0, 4.8, 4.5, 4.4, 4.13, 26, 3.74, 8, 1.04, 8.5),
    MlbGame("ATL@MIL", 4.7, 3.8, 5.0, 3.7, 4.53, 21, 3.86, 14, 1.00, 7.5, True, "BLOCKED_NEUTRAL_SITE_PARK_UNMODELED"),
    MlbGame("TB@BAL", 4.5, 4.2, 4.5, 4.7, None, 0, None, 0, 1.02, 8.5),
    MlbGame("TOR@NYY", 3.9, 4.3, 4.4, 3.7, 3.16, 25, 3.30, 10, 1.03, 7.5),
    MlbGame("DET@KC", 4.5, 3.9, 4.2, 4.9, None, 0, None, 0, 0.98, 8.5),
    MlbGame("ATH@HOU", 4.3, 5.7, 4.5, 4.8, 3.91, 2, 6.44, 7, 1.00, 9.0),
    MlbGame("LAA@TEX", 4.1, 4.6, 4.0, 4.3, None, 0, 3.13, 9, 1.01, 8.0),
    MlbGame("NYM@CWS", 4.1, 4.5, 4.7, 4.4, 3.34, 25, 2.44, 3, 1.01, 8.0),
    MlbGame("SF@BOS", 4.0, 4.6, 4.5, 3.8, None, 0, 3.46, 14, 1.05, 8.0),
    MlbGame("CLE@COL", 4.0, 4.1, 4.7, 5.8, None, 0, None, 0, 1.25, 11.0),
    MlbGame("MIN@SD", 4.6, 4.9, 4.2, 4.2, None, 0, None, 0, 0.94, 8.5),
    MlbGame("CHC@SEA", 5.1, 4.3, 3.9, 4.2, 3.77, 25, 3.71, 15, 0.94, 7.5),
]


WNBA = [
    {"game": "SEA@DAL", "p_home": 0.682646, "margin_home": 5.3308, "total": 171.9421, "spread_home": -8.5, "total_line": 172.5, "action": "BLOCKED_DOG_COMPRESSION"},
    {"game": "IND@CHI", "p_home": 0.302283, "margin_home": -5.8791, "total": 179.1412, "spread_home": 3.5, "total_line": 187.5, "action": "BLOCKED_STALE_STATE_NO_INJURY_BYTES"},
    {"game": "LVA@TOR", "p_home": 0.225150, "margin_home": -8.1285, "total": 166.9191, "spread_home": 13.5, "total_line": 180.5, "action": "BLOCKED_DOG_COMPRESSION_NEUTRAL_SITE_HCA"},
    {"game": "WAS@POR", "p_home": 0.475263, "margin_home": -1.0851, "total": 165.8501, "spread_home": 4.5, "total_line": 164.5, "action": "BLOCKED_DOG_COMPRESSION"},
]


def pitcher_factor(era: float | None, gs: int) -> tuple[float, float]:
    """Return run factor and information weight; CAP/no history maps to 1.0."""
    if era is None or gs <= 0:
        return 1.0, 0.0
    weight = gs / (gs + 10.0)
    shrunk = weight * era + (1.0 - weight) * MLB_LEAGUE_ERA
    factor = (shrunk / MLB_LEAGUE_ERA) ** 0.55
    return factor, weight


def mlb_run_means(g: MlbGame) -> tuple[float, float]:
    away_sp_factor, _ = pitcher_factor(g.away_sp_era, g.away_sp_gs)
    home_sp_factor, _ = pitcher_factor(g.home_sp_era, g.home_sp_gs)
    hfa = 1.0 if g.neutral else 1.025
    away = math.sqrt(g.away_rf * g.home_ra) * home_sp_factor * g.park_factor
    home = math.sqrt(g.home_rf * g.away_ra) * away_sp_factor * g.park_factor * hfa
    return away, home


def nb_draw(rng: np.random.Generator, mean: float, size: int) -> np.ndarray:
    p = MLB_DISPERSION / (MLB_DISPERSION + mean)
    return rng.negative_binomial(MLB_DISPERSION, p, size=size)


def grade_total(draws: np.ndarray, line: float) -> dict[str, float]:
    over = float(np.mean(draws > line))
    push = float(np.mean(draws == line)) if line.is_integer() else 0.0
    under = float(np.mean(draws < line))
    return {"p_over": over, "p_push": push, "p_under": under}


def simulate() -> dict:
    rng = np.random.default_rng(SEED)
    mlb_rows = []
    for g in MLB:
        away_mean, home_mean = mlb_run_means(g)
        away = nb_draw(rng, away_mean, N_SIM)
        home = nb_draw(rng, home_mean, N_SIM)
        ties = away == home
        home_wins = home > away
        tie_breaks = rng.random(N_SIM) < 0.5
        p_home = float(np.mean(home_wins | (ties & tie_breaks)))
        totals = away + home
        row = {
            "game": g.game,
            "model_class": "TRANSPARENT_RF_RA_STARTER_REFERENCE",
            "p_away": 1.0 - p_home,
            "p_home": p_home,
            "predicted_winner": g.game.split("@")[1] if p_home >= 0.5 else g.game.split("@")[0],
            "projected_away_runs": away_mean,
            "projected_home_runs": home_mean,
            "projected_total": away_mean + home_mean,
            "total_line": g.total_line,
            "total_probabilities": grade_total(totals, g.total_line),
            "away_starter_weight": pitcher_factor(g.away_sp_era, g.away_sp_gs)[1],
            "home_starter_weight": pitcher_factor(g.home_sp_era, g.home_sp_gs)[1],
            "forecast_status": "FORECAST_REGISTERED",
            "action_status": g.action_status,
        }
        row["total_forecast"] = "OVER" if row["total_probabilities"]["p_over"] >= row["total_probabilities"]["p_under"] else "UNDER"
        mlb_rows.append(row)

    wnba_rows = []
    for g in WNBA:
        margin = rng.normal(g["margin_home"], 12.0, N_SIM)
        total = rng.normal(g["total"], 14.0, N_SIM)
        home_cover = float(np.mean(margin + g["spread_home"] > 0.0))
        p_over = float(np.mean(total > g["total_line"]))
        home_team = g["game"].split("@")[1]
        away_team = g["game"].split("@")[0]
        wnba_rows.append({
            "game": g["game"],
            "model_class": "WNBA_FROZEN_SHADOW_WITH_REFERENCE_DISTRIBUTIONS",
            "direct_p_home": g["p_home"],
            "direct_p_away": 1.0 - g["p_home"],
            "predicted_winner": g["game"].split("@")[1] if g["p_home"] >= 0.5 else g["game"].split("@")[0],
            "margin_home_mean": g["margin_home"],
            "total_mean": g["total"],
            "market_home_spread": g["spread_home"],
            "p_home_cover": home_cover,
            "p_away_cover": 1.0 - home_cover,
            "ats_forecast": home_team if home_cover >= 0.5 else away_team,
            "total_line": g["total_line"],
            "p_over": p_over,
            "p_under": 1.0 - p_over,
            "total_forecast": "OVER" if p_over >= 0.5 else "UNDER",
            "forecast_status": "FORECAST_REGISTERED",
            "action_status": g["action"],
        })

    margin = rng.normal(4.25, 13.5, N_SIM)
    total = rng.normal(38.0, 13.0, N_SIM)
    nfl = [{
        "game": "SEA@TEN",
        "model_class": "INFORMATION_ADJUSTED_PRESEASON_REFERENCE",
        "direct_p_home": 0.645,
        "direct_p_away": 0.355,
        "predicted_winner": "TEN",
        "projected_margin_home": 4.25,
        "projected_total": 38.0,
        "market_home_spread": -4.5,
        "p_home_cover": float(np.mean(margin > 4.5)),
        "p_away_cover": float(np.mean(margin < 4.5)),
        "ats_forecast": "SEA",
        "total_line": 38.5,
        "p_over": float(np.mean(total > 38.5)),
        "p_under": float(np.mean(total < 38.5)),
        "total_forecast": "UNDER",
        "forecast_status": "FORECAST_REGISTERED",
        "action_status": "BET_TEN_ML_-170_0.5U",
    }]

    result = {
        "date": "2026-08-23",
        "seed": SEED,
        "n_sim": N_SIM,
        "contract": {
            "forecast_generation": "UNCONDITIONAL",
            "action_gate": "SEPARATE_DOWNSTREAM_FIELD",
            "blocked_forecasts_remain_gradable": True,
            "market_data_used_as_predictive_input": False,
        },
        "assumptions": {
            "mlb": "RF/RA geometric blend; starter ERA shrunk to 4.30 and applied at 55% strength; fixed reference park factors; negative-binomial runs with dispersion 12.",
            "wnba": "Frozen direct winner probabilities; margin N(mean,12); total N(mean,14); distributional assumptions are reference-only.",
            "nfl": "Evidence-adjusted direct winner probability 0.645; margin N(4.25,13.5); total N(38.0,13.0); preseason reference-only.",
        },
        "mlb": mlb_rows,
        "wnba": wnba_rows,
        "nfl": nfl,
    }
    return result


def selftest(result: dict) -> None:
    assert len(result["mlb"]) == 15
    assert len(result["wnba"]) == 4
    assert len(result["nfl"]) == 1
    for sport in ("mlb", "wnba", "nfl"):
        for row in result[sport]:
            assert row["forecast_status"] == "FORECAST_REGISTERED"
            assert row["action_status"]
            assert row["predicted_winner"]
            assert row["total_forecast"] in {"OVER", "UNDER"}
    for row in result["mlb"]:
        assert abs(row["p_home"] + row["p_away"] - 1.0) < 1e-12
        probs = row["total_probabilities"]
        assert abs(sum(probs.values()) - 1.0) < 1e-12
        if not float(row["total_line"]).is_integer():
            assert probs["p_push"] == 0.0
    for row in result["wnba"] + result["nfl"]:
        assert row["ats_forecast"]
        assert abs(row["p_home_cover"] + row["p_away_cover"] - 1.0) < 1e-12
        assert abs(row["p_over"] + row["p_under"] - 1.0) < 1e-12


if __name__ == "__main__":
    output = simulate()
    selftest(output)
    print(json.dumps(output, indent=2, sort_keys=True))
