from __future__ import annotations

from collections import Counter
from typing import Any

from research.news_information.contracts import digest, validate_information_event
from research.news_information.source_adapters import source_profile
from research.news_information.taxonomies import taxonomy_for_league, validate_event_type_for_league

TRANSFORM_SCHEMA_VERSION = "sports_league_information_state.v1"


def _eligible(events: list[dict[str, Any]], *, league: str, event_id: str) -> list[dict[str, Any]]:
    out = []
    for raw in events:
        event = validate_information_event(raw)
        if event.get("league") != league or str(event.get("event_id")) != str(event_id):
            continue
        if not event["forecast_timing"]["known_before_cutoff"]:
            continue
        if not event["usage_policy"].get("research_feature_eligible"):
            continue
        validate_event_type_for_league(league, event["claim"]["event_type"])
        out.append(event)
    out.sort(key=lambda e: e["information_event_id"])
    return out


def _claims(events: list[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [e["claim"] for e in events if e["claim"]["event_type"] == event_type]


def _statuses(events: list[dict[str, Any]], event_type: str) -> list[str]:
    return sorted(str(c.get("status")) for c in _claims(events, event_type))


def _restrictions(events: list[dict[str, Any]], event_type: str) -> list[Any]:
    values = [c.get("restriction_value") for c in _claims(events, event_type) if c.get("restriction_value") is not None]
    return sorted(values, key=lambda x: str(x))


def _mlb(events):
    return {
        "starter": {
            "confirmed_count": len(_claims(events, "STARTER_CONFIRMED")),
            "scratched_count": len(_claims(events, "STARTER_SCRATCHED")),
            "pitch_limit_values": _restrictions(events, "STARTER_PITCH_LIMIT"),
        },
        "lineup": {
            "confirmed_count": len(_claims(events, "LINEUP_CONFIRMED")),
            "projected_count": len(_claims(events, "LINEUP_PROJECTED")),
            "player_out_count": len(_claims(events, "PLAYER_OUT")),
            "player_rest_count": len(_claims(events, "PLAYER_REST")),
        },
        "bullpen": {
            "available_count": len(_claims(events, "BULLPEN_AVAILABLE")),
            "limited_count": len(_claims(events, "BULLPEN_LIMITED")),
            "unavailable_count": len(_claims(events, "BULLPEN_UNAVAILABLE")),
        },
        "environment": {
            "roof_statuses": _statuses(events, "ROOF_STATUS"),
            "weather_change_count": len(_claims(events, "WEATHER_CHANGE")),
            "weather_delay_risk_count": len(_claims(events, "WEATHER_DELAY_RISK")),
        },
    }


def _football(events):
    return {
        "quarterback": {
            "qb_statuses": _statuses(events, "QB_STATUS"),
            "out_count": len(_claims(events, "QB_OUT")),
            "limited_count": len(_claims(events, "QB_LIMITED")),
        },
        "practice": dict(sorted(Counter(_statuses(events, "PRACTICE_PARTICIPATION")).items())),
        "availability": {
            "inactive_count": len(_claims(events, "INACTIVE_CONFIRMED")),
            "ol_injury_cluster_count": len(_claims(events, "OL_INJURY_CLUSTER")),
            "secondary_injury_cluster_count": len(_claims(events, "SECONDARY_INJURY_CLUSTER")),
            "snap_limit_values": _restrictions(events, "SNAP_LIMIT"),
            "suspension_count": len(_claims(events, "SUSPENSION")),
        },
        "venue": {"neutral_site_statuses": _statuses(events, "NEUTRAL_SITE_STATUS")},
    }


def _basketball(events):
    injury_types = ("PLAYER_OUT", "PLAYER_DOUBTFUL", "PLAYER_QUESTIONABLE", "PLAYER_PROBABLE")
    return {
        "availability": {t.lower(): len(_claims(events, t)) for t in injury_types},
        "injury_designations": _statuses(events, "INJURY_DESIGNATION"),
        "lineup": {
            "starter_confirmed_count": len(_claims(events, "STARTER_CONFIRMED")),
            "late_scratch_count": len(_claims(events, "LATE_SCRATCH")),
        },
        "minutes": {"restriction_values": _restrictions(events, "MINUTES_RESTRICTION")},
        "load": {
            "rest_statuses": _statuses(events, "REST_STATUS"),
            "back_to_back_count": len(_claims(events, "BACK_TO_BACK_LOAD")),
            "travel_disruption_count": len(_claims(events, "TRAVEL_DISRUPTION")),
        },
    }


def _hockey(events):
    return {
        "goaltender": {
            "confirmed_statuses": _statuses(events, "GOALIE_CONFIRMED"),
            "limited_statuses": _statuses(events, "GOALIE_LIMITED"),
            "rest_count": len(_claims(events, "GOALIE_REST")),
        },
        "skaters": {
            "scratched_count": len(_claims(events, "SKATER_SCRATCHED")),
            "line_combination_change_count": len(_claims(events, "LINE_COMBINATION_CHANGE")),
        },
        "roster": {
            "callup_count": len(_claims(events, "CALLUP")),
            "demotion_count": len(_claims(events, "DEMOTION")),
        },
    }


def _soccer(events):
    return {
        "lineup": {
            "starting_xi_confirmed_count": len(_claims(events, "STARTING_XI_CONFIRMED")),
            "goalkeeper_confirmed_count": len(_claims(events, "GOALKEEPER_CONFIRMED")),
        },
        "availability": {
            "suspension_count": len(_claims(events, "SUSPENSION")),
            "international_duty_count": len(_claims(events, "INTERNATIONAL_DUTY")),
        },
        "load": {
            "fixture_congestion_count": len(_claims(events, "FIXTURE_CONGESTION")),
            "travel_disruption_count": len(_claims(events, "TRAVEL_DISRUPTION")),
        },
    }


_BUILDERS = {
    "mlb": _mlb,
    "football": _football,
    "basketball": _basketball,
    "hockey": _hockey,
    "soccer": _soccer,
}

_TRANSFORM_VERSIONS = {
    "MLB": "mlb_information_transform.v0_1.research",
    "NFL": "nfl_information_transform.v0_1.research",
    "CFB": "cfb_information_transform.v0_1.research",
    "NBA": "nba_information_transform.v0_1.research",
    "WNBA": "wnba_information_transform.v0_1.research",
    "NHL": "nhl_information_transform.v0_1.research",
    "MLS": "mls_information_transform.v0_1.research",
}


def build_league_information_state(*, league: str, event_id: str, cutoff_utc: str,
                                   events: list[dict[str, Any]]) -> dict[str, Any]:
    league = str(league).upper()
    taxonomy = taxonomy_for_league(league)
    valid = _eligible(events, league=league, event_id=event_id)
    counts = Counter(e["claim"]["event_type"] for e in valid)
    conflicts = sum(e["resolution"]["cross_model_state"] == "CONFLICTING" for e in valid)
    profile = source_profile(league)
    core = {
        "schema_version": TRANSFORM_SCHEMA_VERSION,
        "league": league,
        "event_id": str(event_id),
        "cutoff_utc": cutoff_utc,
        "taxonomy": {
            "core": taxonomy["core_taxonomy_version"],
            "extension": taxonomy["extension_taxonomy_version"],
        },
        "impact_transform_version": _TRANSFORM_VERSIONS[league],
        "first_research_target": profile.first_research_target,
        "information_event_ids": [e["information_event_id"] for e in valid],
        "event_type_counts": dict(sorted(counts.items())),
        "conflict_count": int(conflicts),
        "feature_state": _BUILDERS[taxonomy["family"]](valid),
        "impact_transform_status": "UNVALIDATED_SHADOW_STATE_ONLY",
        "research_only": True,
        "forecast_adjustment_eligible": False,
        "market_input": False,
        "action_authority": "OFF",
    }
    return {**core, "state_sha256": digest(core)}
