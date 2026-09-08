from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from research.news_information.contracts import normalize_text


class ResolutionError(ValueError):
    pass


@dataclass(frozen=True)
class Resolution:
    status: str
    entity_id: str | None
    confidence: float
    candidates: tuple[str, ...]


class OfficialEntityIndex:
    """Exact-alias resolver over a caller-supplied official ID snapshot.

    No fuzzy identity guess is made. Ambiguity fails closed and remains available for review.
    """

    def __init__(self, payload: dict[str, Any]):
        if payload.get("schema_version") != "sports_official_entity_index.v1":
            raise ResolutionError("unexpected entity index schema")
        self.payload = payload
        self.players = list(payload.get("players") or [])
        self.teams = list(payload.get("teams") or [])
        self.events = list(payload.get("events") or [])

    @classmethod
    def from_path(cls, path: Path):
        return cls(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _aliases(record: dict[str, Any]):
        values = list(record.get("aliases") or [])
        for key in ("name", "display_name", "abbr"):
            if record.get(key):
                values.append(record[key])
        return {normalize_text(str(x)) for x in values if x}

    def resolve_player(self, mention: str, *, league: str | None = None,
                       team_id: str | None = None) -> Resolution:
        q = normalize_text(mention)
        matches = []
        for player in self.players:
            if league and player.get("league") != league:
                continue
            if team_id and player.get("team_id") != team_id:
                continue
            if q in self._aliases(player):
                matches.append(str(player["player_id"]))
        return self._finish(matches)

    def resolve_team(self, mention: str, *, league: str | None = None) -> Resolution:
        q = normalize_text(mention)
        matches = []
        for team in self.teams:
            if league and team.get("league") != league:
                continue
            if q in self._aliases(team):
                matches.append(str(team["team_id"]))
        return self._finish(matches)

    def validate_event_assignment(self, event_id: str, *, team_id: str | None = None,
                                  player_team_id: str | None = None) -> Resolution:
        matches = [e for e in self.events if str(e.get("event_id")) == str(event_id)]
        if len(matches) != 1:
            return Resolution("UNRESOLVED" if not matches else "AMBIGUOUS", None, 0.0, tuple())
        event = matches[0]
        teams = {str(event.get("home_team_id")), str(event.get("away_team_id"))}
        for expected in (team_id, player_team_id):
            if expected is not None and str(expected) not in teams:
                return Resolution("MISMATCH", str(event_id), 0.0, (str(event_id),))
        return Resolution("RESOLVED", str(event_id), 1.0, (str(event_id),))

    @staticmethod
    def _finish(matches: list[str]) -> Resolution:
        unique = tuple(sorted(set(matches)))
        if len(unique) == 1:
            return Resolution("RESOLVED", unique[0], 1.0, unique)
        if not unique:
            return Resolution("UNRESOLVED", None, 0.0, unique)
        return Resolution("AMBIGUOUS", None, 0.0, unique)
