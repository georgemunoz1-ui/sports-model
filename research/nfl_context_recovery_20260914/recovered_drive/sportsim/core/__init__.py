"""Sport-agnostic building blocks: types, ratings, market math, metrics."""

from __future__ import annotations

from .market import (
    BetEdge,
    american_to_decimal,
    american_to_prob,
    closing_line_value,
    expected_value,
    find_edge,
    kelly_fraction,
    no_vig_probs,
    prob_to_american,
    remove_vig,
    scan_edges,
)
from .metrics import (
    accuracy,
    ats_record,
    brier_score,
    calibration,
    calibration_report,
    evaluate,
    expected_calibration_error,
    log_loss,
    margin_errors,
    skill_score,
)
from .ratings import (
    ELO_PRESETS,
    EloConfig,
    EloModel,
    MarginFit,
    StrengthFit,
    blend_ratings,
    fit_poisson_strength,
    fit_ridge_margin,
)
from .types import Game, GameForecast, LeagueStructure, ScoreSamples, TeamRating, teams_from_games

__all__ = [
    "ELO_PRESETS",
    "BetEdge",
    "EloConfig",
    "EloModel",
    "Game",
    "GameForecast",
    "LeagueStructure",
    "MarginFit",
    "ScoreSamples",
    "StrengthFit",
    "TeamRating",
    "accuracy",
    "american_to_decimal",
    "american_to_prob",
    "ats_record",
    "blend_ratings",
    "brier_score",
    "calibration",
    "calibration_report",
    "closing_line_value",
    "evaluate",
    "expected_calibration_error",
    "expected_value",
    "find_edge",
    "fit_poisson_strength",
    "fit_ridge_margin",
    "kelly_fraction",
    "log_loss",
    "margin_errors",
    "no_vig_probs",
    "prob_to_american",
    "remove_vig",
    "scan_edges",
    "skill_score",
    "teams_from_games",
]

