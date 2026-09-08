from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SUPPORTED_LEAGUES = ("MLB", "NFL", "NBA", "WNBA", "NHL", "CFB", "MLS")
LEAGUE_FAMILY = {
    "MLB": "mlb",
    "NFL": "football",
    "CFB": "football",
    "NBA": "basketball",
    "WNBA": "basketball",
    "NHL": "hockey",
    "MLS": "soccer",
}
TAXONOMY_FILES = {
    "core": "sports_event_taxonomy.v1.json",
    "mlb": "mlb_event_taxonomy.v1.json",
    "football": "football_event_taxonomy.v1.json",
    "basketball": "basketball_event_taxonomy.v1.json",
    "hockey": "hockey_event_taxonomy.v1.json",
    "soccer": "soccer_event_taxonomy.v1.json",
}


def taxonomy_dir() -> Path:
    return Path(__file__).with_name("taxonomies")


def _load(name: str) -> dict[str, Any]:
    path = taxonomy_dir() / TAXONOMY_FILES[name]
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = payload.get("taxonomy_version")
    if not isinstance(expected, str) or not expected.endswith(".v1"):
        raise ValueError(f"invalid taxonomy version in {path}")
    events = payload.get("event_types")
    if not isinstance(events, list) or not events or len(events) != len(set(events)):
        raise ValueError(f"invalid event_types in {path}")
    return payload


def taxonomy_for_league(league: str) -> dict[str, Any]:
    league = str(league).upper()
    if league not in LEAGUE_FAMILY:
        raise ValueError(f"unsupported league: {league}")
    core = _load("core")
    ext = _load(LEAGUE_FAMILY[league])
    events = tuple(sorted(set(core["event_types"]) | set(ext["event_types"])))
    destructive = tuple(sorted(set(core.get("destructive_event_types", [])) |
                               set(ext.get("destructive_event_types", []))))
    return {
        "league": league,
        "family": LEAGUE_FAMILY[league],
        "core_taxonomy_version": core["taxonomy_version"],
        "extension_taxonomy_version": ext["taxonomy_version"],
        "event_types": events,
        "destructive_event_types": destructive,
    }


def allowed_event_types(league: str) -> frozenset[str]:
    return frozenset(taxonomy_for_league(league)["event_types"])


def destructive_event_types(league: str) -> frozenset[str]:
    return frozenset(taxonomy_for_league(league)["destructive_event_types"])


def all_event_types() -> frozenset[str]:
    values: set[str] = set()
    for league in SUPPORTED_LEAGUES:
        values.update(allowed_event_types(league))
    return frozenset(values)


def validate_event_type_for_league(league: str, event_type: str) -> None:
    if event_type not in allowed_event_types(league):
        raise ValueError(f"event_type {event_type!r} is not registered for league {league!r}")
