"""Versioned acquisition inventory; source reports cannot declare their own scope.

This is the existing seven-league capture contract, not a forecast/input-readiness
contract. The WNBA extension intentionally retains the collector's historical
August 30 boundary. Changing that policy requires a separately reviewed version.
"""
from __future__ import annotations

import datetime as dt

from scripts.recovery_capture import ROUTES

SCHEMA = "sports.operational_capture.v1"
TIMEZONE = "America/Los_Angeles"


def schedule_specs(day: dt.date):
    specs = []
    for offset in range(-7, 8):
        date = day + dt.timedelta(days=offset)
        for league, route in ROUTES.items():
            specs.append((league, "schedule", f"https://site.api.espn.com/apis/site/v2/sports/{route}/scoreboard?dates={date:%Y%m%d}&limit=1000", 2))
        specs.append(("mlb", "official_schedule", f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date}&hydrate=probablePitcher,linescore,venue", 1))
    date = dt.date(day.year, 8, 30)
    while date < day - dt.timedelta(days=7):
        specs.append(("wnba", "schedule", f'https://site.api.espn.com/apis/site/v2/sports/{ROUTES["wnba"]}/scoreboard?dates={date:%Y%m%d}&limit=1000', 2))
        date += dt.timedelta(days=1)
    return specs


def summary_spec(league: str, event_id: str):
    return (league, "event_summary", f"https://site.api.espn.com/apis/site/v2/sports/{ROUTES[league]}/summary?event={event_id}", 2)


def nfl_source_urls(day: dt.date):
    return {
        "games.csv": "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv",
        f"play_by_play_{day.year}.csv": f"https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{day.year}.csv",
    }
