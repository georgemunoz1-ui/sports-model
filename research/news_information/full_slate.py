from __future__ import annotations

from collections import defaultdict
from typing import Any

from research.news_information.source_adapters import source_profile


def _completeness(league: str, captures: list[dict[str, Any]]) -> tuple[str, list[str], list[str]]:
    profile = source_profile(league)
    required = set(profile.required_official_anchors)
    seen = {
        c.get("anchor_kind") for c in captures
        if c.get("known_before_cutoff") is True
        and c.get("usage_disposition") == "TIER_1_OFFICIAL_CANDIDATE"
        and c.get("market_facing") is False
    }
    present = sorted(required & seen)
    missing = sorted(required - seen)
    if not required:
        level = "HIGH"
    elif len(present) == len(required):
        level = "HIGH"
    elif present:
        level = "MEDIUM"
    else:
        level = "LOW"
    return level, present, missing


def build_full_slate_diagnostics(*, games: list[dict[str, Any]],
                                 source_captures: list[dict[str, Any]],
                                 information_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one diagnostic row per scheduled game; never silently filter on news coverage."""
    captures_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for capture in source_captures:
        captures_by_event[str(capture.get("event_id"))].append(capture)
    events_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in information_events:
        events_by_event[str(event.get("event_id"))].append(event)

    rows = []
    for game in games:
        event_id = str(game["event_id"])
        league = str(game["league"]).upper()
        level, present, missing = _completeness(league, captures_by_event.get(event_id, []))
        game_events = events_by_event.get(event_id, [])
        if any((e.get("resolution") or {}).get("cross_model_state") == "CONFLICTING" for e in game_events):
            news_state = "CONFLICTING"
        else:
            types = sorted({(e.get("claim") or {}).get("event_type") for e in game_events
                            if (e.get("claim") or {}).get("event_type")})
            news_state = "+".join(types[:4]) if types else "NO_STRUCTURED_EVENT"
            if len(types) > 4:
                news_state += f"+{len(types)-4}_MORE"

        identity = str(game.get("event_identity_status", "RESOLVED"))
        if identity != "RESOLVED":
            forecast_status = "BLOCKED"
            interpretation = "EVENT_IDENTITY_FAILURE"
            level = "INVALID"
        else:
            forecast_status = str(game.get("forecast_status", "SHADOW_ONLY"))
            interpretation = {
                "HIGH": "RICHER_RESEARCH_INPUT_STATE",
                "MEDIUM": "PARTIAL_INFORMATION_STATE",
                "LOW": "BASELINE_ONLY_OR_INFORMATION_PENDING",
            }[level]
        rows.append({
            "event_id": event_id,
            "league": league,
            "forecast_status": forecast_status,
            "news_state": news_state,
            "information_completeness": level,
            "official_anchors_present": present,
            "official_anchors_missing": missing,
            "interpretation": interpretation,
            "market_input": False,
            "action_authority": "OFF",
        })
    return rows
