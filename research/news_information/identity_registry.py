from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research.news_information.contracts import digest, normalize_text, parse_utc
from research.news_information.entity_resolution import Resolution

REGISTRY_SCHEMA_VERSION = "sports_entity_registry.v1"


def _active_window(record: dict[str, Any], at_utc: str) -> bool:
    at = parse_utc(at_utc)
    start = parse_utc(record.get("valid_from_utc"))
    end = parse_utc(record.get("valid_to_utc"))
    if at is None:
        raise ValueError("at_utc is required")
    return (start is None or start <= at) and (end is None or at < end)


def _alias_values(record: dict[str, Any], at_utc: str) -> set[str]:
    values: set[str] = set()
    for key in ("name", "display_name", "abbr"):
        if record.get(key):
            values.add(normalize_text(str(record[key])))
    for alias in record.get("aliases") or []:
        if isinstance(alias, str):
            values.add(normalize_text(alias))
            continue
        if not isinstance(alias, dict) or not alias.get("value"):
            raise ValueError("alias must be string or object with value")
        if _active_window(alias, at_utc):
            values.add(normalize_text(str(alias["value"])))
    return values


def _team_at(player: dict[str, Any], at_utc: str) -> set[str]:
    assignments = player.get("team_assignments")
    if assignments is None:
        team_id = player.get("team_id")
        return {str(team_id)} if team_id is not None else set()
    out = set()
    for assignment in assignments:
        if _active_window(assignment, at_utc):
            out.add(str(assignment["team_id"]))
    return out


class CanonicalSportsEntityRegistry:
    """Exact, time-bounded cross-sport identity registry.

    The registry never fuzzy-matches. Trades, call-ups and historical aliases are resolved against
    the supplied point-in-time timestamp; ambiguity remains an explicit failure state.
    """

    def __init__(self, payload: dict[str, Any]):
        if payload.get("schema_version") != REGISTRY_SCHEMA_VERSION:
            raise ValueError("unexpected sports entity registry schema")
        self.payload = payload
        self.teams = list(payload.get("teams") or [])
        self.players = list(payload.get("players") or [])
        self.events = list(payload.get("events") or [])
        core = {k: v for k, v in payload.items() if k != "registry_sha256"}
        expected = digest(core)
        supplied = payload.get("registry_sha256")
        if supplied not in (None, expected):
            raise ValueError("registry_sha256 does not match canonical registry content")
        self.registry_sha256 = expected

    @classmethod
    def from_path(cls, path: Path) -> "CanonicalSportsEntityRegistry":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _finish(matches: list[str]) -> Resolution:
        unique = tuple(sorted(set(matches)))
        if len(unique) == 1:
            return Resolution("RESOLVED", unique[0], 1.0, unique)
        if not unique:
            return Resolution("UNRESOLVED", None, 0.0, unique)
        return Resolution("AMBIGUOUS", None, 0.0, unique)

    def resolve_team(self, mention: str, *, league: str, at_utc: str) -> Resolution:
        q = normalize_text(mention)
        matches = []
        for team in self.teams:
            if team.get("league") != league or not _active_window(team, at_utc):
                continue
            if q in _alias_values(team, at_utc):
                matches.append(str(team["canonical_team_id"]))
        return self._finish(matches)

    def resolve_player(self, mention: str, *, league: str, at_utc: str,
                       team_id: str | None = None) -> Resolution:
        q = normalize_text(mention)
        matches = []
        for player in self.players:
            if player.get("league") != league or not _active_window(player, at_utc):
                continue
            teams = _team_at(player, at_utc)
            if team_id is not None and str(team_id) not in teams:
                continue
            if q in _alias_values(player, at_utc):
                matches.append(str(player["canonical_player_id"]))
        return self._finish(matches)

    def resolve_event(self, event_ref: str, *, league: str) -> Resolution:
        matches = []
        ref = str(event_ref)
        for event in self.events:
            if event.get("league") != league:
                continue
            ids = {str(event.get("canonical_event_id")), str(event.get("official_provider_event_id"))}
            if ref in ids:
                matches.append(str(event["canonical_event_id"]))
        return self._finish(matches)

    def validate_event_assignment(self, *, canonical_event_id: str, league: str,
                                  at_utc: str, team_id: str | None = None,
                                  player_id: str | None = None) -> Resolution:
        matches = [e for e in self.events
                   if e.get("league") == league and str(e.get("canonical_event_id")) == str(canonical_event_id)]
        if len(matches) != 1:
            return Resolution("UNRESOLVED" if not matches else "AMBIGUOUS", None, 0.0, tuple())
        event = matches[0]
        event_teams = {str(event.get("home_team_id")), str(event.get("away_team_id"))}
        if team_id is not None and str(team_id) not in event_teams:
            return Resolution("MISMATCH", str(canonical_event_id), 0.0, (str(canonical_event_id),))
        if player_id is not None:
            players = [p for p in self.players
                       if p.get("league") == league and str(p.get("canonical_player_id")) == str(player_id)]
            if len(players) != 1 or not (_team_at(players[0], at_utc) & event_teams):
                return Resolution("MISMATCH", str(canonical_event_id), 0.0, (str(canonical_event_id),))
        return Resolution("RESOLVED", str(canonical_event_id), 1.0, (str(canonical_event_id),))
