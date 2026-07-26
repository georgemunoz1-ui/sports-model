"""Season-level simulation: schedules, standings, playoffs."""

from __future__ import annotations

from .playoffs import SeriesOracle, series_win_prob
from .schedule import build_schedule, merge_results, remaining_schedule
from .simulator import SeasonResult, SeasonSimulator
from .standings import TeamRecord, compute_standings, standings_table

__all__ = [
    "SeasonResult",
    "SeasonSimulator",
    "SeriesOracle",
    "TeamRecord",
    "build_schedule",
    "compute_standings",
    "merge_results",
    "remaining_schedule",
    "series_win_prob",
    "standings_table",
]
