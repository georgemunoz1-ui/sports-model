from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from research.news_information.contracts import RawSourceRecord, digest
from research.news_information.source_policy import source_disposition
from research.news_information.taxonomies import SUPPORTED_LEAGUES

SOURCE_CAPTURE_SCHEMA_VERSION = "sports_information_source_capture.v1"
UNSTRUCTURED_REPORT = "UNSTRUCTURED_REPORT"


@dataclass(frozen=True)
class LeagueSourceProfile:
    league: str
    required_official_anchors: tuple[str, ...]
    optional_official_anchors: tuple[str, ...]
    high_value_states: tuple[str, ...]
    first_research_target: str


_PROFILES = {
    "MLB": LeagueSourceProfile(
        "MLB",
        ("SCHEDULE", "ROSTER", "PROBABLE_PITCHERS", "OFFICIAL_LINEUP"),
        ("TRANSACTION_FEED", "INJURY_REPORT", "ROOF_WEATHER"),
        ("STARTER_CONFIRMED", "STARTER_SCRATCHED", "STARTER_PITCH_LIMIT",
         "LINEUP_CONFIRMED", "BULLPEN_LIMITED", "BULLPEN_UNAVAILABLE", "ROOF_STATUS", "WEATHER_CHANGE"),
        "EXPECTED_TEAM_RUNS_AND_PITCHER_BULLPEN_RUN_PREVENTION"),
    "NFL": LeagueSourceProfile(
        "NFL",
        ("SCHEDULE", "ROSTER", "OFFICIAL_INJURY_REPORT", "GAMEDAY_INACTIVE_LIST"),
        ("DEPTH_CHART",),
        ("QB_STATUS", "QB_OUT", "QB_LIMITED", "PRACTICE_PARTICIPATION", "INACTIVE_CONFIRMED",
         "OL_INJURY_CLUSTER", "SECONDARY_INJURY_CLUSTER", "SNAP_LIMIT"),
        "QB_AVAILABILITY_AND_POSITION_GROUP_STATE"),
    "NBA": LeagueSourceProfile(
        "NBA",
        ("SCHEDULE", "ROSTER", "OFFICIAL_INJURY_REPORT", "STARTING_LINEUP"),
        (),
        ("PLAYER_OUT", "INJURY_DESIGNATION", "STARTER_CONFIRMED", "MINUTES_RESTRICTION",
         "REST_STATUS", "BACK_TO_BACK_LOAD", "LATE_SCRATCH"),
        "PLAYER_MINUTE_AVAILABILITY_AND_LINEUP_NET_RATING_STATE"),
    "WNBA": LeagueSourceProfile(
        "WNBA",
        ("SCHEDULE", "ROSTER", "OFFICIAL_INJURY_REPORT", "STARTING_LINEUP"),
        ("TRANSACTION_FEED",),
        ("PLAYER_OUT", "INJURY_DESIGNATION", "STARTER_CONFIRMED", "MINUTES_RESTRICTION",
         "REST_STATUS", "TRAVEL_DISRUPTION"),
        "PLAYER_MINUTE_AND_LINEUP_STRENGTH_STATE"),
    "NHL": LeagueSourceProfile(
        "NHL",
        ("SCHEDULE", "ROSTER", "GAMEDAY_GOALIE_SOURCE"),
        ("LINE_COMBINATIONS",),
        ("GOALIE_CONFIRMED", "GOALIE_LIMITED", "GOALIE_REST", "SKATER_SCRATCHED",
         "LINE_COMBINATION_CHANGE", "CALLUP", "DEMOTION"),
        "GOALTENDER_AVAILABILITY_AND_EXPECTED_GOALS_STATE"),
    "CFB": LeagueSourceProfile(
        "CFB",
        ("SCHEDULE_VENUE", "TEAM_AVAILABILITY_SOURCE"),
        ("DEPTH_CHART", "OFFICIAL_AVAILABILITY_IF_AVAILABLE"),
        ("QB_STATUS", "QB_OUT", "QB_LIMITED", "DEPTH_CHART_CHANGE", "SUSPENSION",
         "NEUTRAL_SITE_STATUS", "ROSTER_TRANSACTION"),
        "TEAM_STRENGTH_UNCERTAINTY_AND_QB_POSITION_GROUP_STATE"),
    "MLS": LeagueSourceProfile(
        "MLS",
        ("SCHEDULE", "ROSTER", "STARTING_XI", "OFFICIAL_STATUS_SOURCE"),
        ("SUSPENSION_SOURCE",),
        ("STARTING_XI_CONFIRMED", "SUSPENSION", "INTERNATIONAL_DUTY",
         "GOALKEEPER_CONFIRMED", "FIXTURE_CONGESTION", "TRAVEL_DISRUPTION"),
        "ATTACK_DEFENSE_LINEUP_STATE_AND_UNCERTAINTY"),
}


def source_profile(league: str) -> LeagueSourceProfile:
    league = str(league).upper()
    if league not in SUPPORTED_LEAGUES:
        raise ValueError(f"unsupported league: {league}")
    return _PROFILES[league]


def normalize_source_capture(*, league: str, event_id: str, anchor_kind: str,
                             raw_source: RawSourceRecord, market_facing: bool = False,
                             policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize a captured source without claiming that its contents are true.

    This is an ingestion/coverage record, not an extracted sports-information fact.
    """
    profile = source_profile(league)
    allowed_anchors = set(profile.required_official_anchors) | set(profile.optional_official_anchors) | {UNSTRUCTURED_REPORT}
    if anchor_kind not in allowed_anchors:
        raise ValueError(f"anchor_kind {anchor_kind!r} is not registered for {league}")
    disposition = source_disposition(
        source_id=raw_source.source_id,
        source_tier=raw_source.source_tier,
        source_type=raw_source.source_type,
        policy=policy,
    )
    if market_facing:
        usage = "EXCLUDED_MARKET_FACING_SOURCE"
    elif raw_source.source_tier == 6:
        usage = "EXCLUDED"
    elif raw_source.source_tier == 1 and raw_source.source_type in {"LEAGUE_OFFICIAL", "TEAM_OFFICIAL"}:
        usage = "TIER_1_OFFICIAL_CANDIDATE"
    elif raw_source.source_tier == 2:
        usage = "RESEARCH_REQUIRES_CORROBORATION"
    elif raw_source.source_tier == 3:
        usage = "RESEARCH_CORROBORATION"
    else:
        usage = "DISCOVERY_ONLY"
    core = {
        "schema_version": SOURCE_CAPTURE_SCHEMA_VERSION,
        "league": league,
        "event_id": str(event_id),
        "anchor_kind": anchor_kind,
        "source_id": raw_source.source_id,
        "source_tier": raw_source.source_tier,
        "source_type": raw_source.source_type,
        "raw_bytes_sha256": raw_source.raw_bytes_sha256,
        "published_at_utc": raw_source.published_at_utc,
        "retrieved_at_utc": raw_source.retrieved_at_utc,
        "forecast_cutoff_utc": raw_source.forecast_cutoff_utc,
        "game_start_utc": raw_source.game_start_utc,
        "pit_status": raw_source.pit_status,
        "known_before_cutoff": raw_source.known_before_cutoff,
        "named_source_verification": disposition["source_verification_state"],
        "usage_disposition": usage,
        "market_facing": bool(market_facing),
        "forecast_adjustment_eligible": False,
        "market_input": False,
        "action_authority": "OFF",
    }
    return {**core, "source_capture_id": digest(core)}

class LeagueSourceAdapter:
    """League-specific boundary over already captured immutable source bytes.

    Network retrieval/parsing remains source-format specific. This adapter refuses unknown anchor
    kinds and normalizes coverage/governance before any NLP extraction runs.
    """
    league: str = ""

    @property
    def profile(self) -> LeagueSourceProfile:
        return source_profile(self.league)

    def capture(self, *, event_id: str, anchor_kind: str, raw_source: RawSourceRecord,
                market_facing: bool = False, policy: dict[str, Any] | None = None) -> dict[str, Any]:
        return normalize_source_capture(
            league=self.league,
            event_id=event_id,
            anchor_kind=anchor_kind,
            raw_source=raw_source,
            market_facing=market_facing,
            policy=policy,
        )


class MLBSourceAdapter(LeagueSourceAdapter): league = "MLB"
class NFLSourceAdapter(LeagueSourceAdapter): league = "NFL"
class NBASourceAdapter(LeagueSourceAdapter): league = "NBA"
class WNBASourceAdapter(LeagueSourceAdapter): league = "WNBA"
class NHLSourceAdapter(LeagueSourceAdapter): league = "NHL"
class CFBSourceAdapter(LeagueSourceAdapter): league = "CFB"
class MLSSourceAdapter(LeagueSourceAdapter): league = "MLS"


_ADAPTERS = {
    "MLB": MLBSourceAdapter(),
    "NFL": NFLSourceAdapter(),
    "NBA": NBASourceAdapter(),
    "WNBA": WNBASourceAdapter(),
    "NHL": NHLSourceAdapter(),
    "CFB": CFBSourceAdapter(),
    "MLS": MLSSourceAdapter(),
}


def source_adapter(league: str) -> LeagueSourceAdapter:
    league = str(league).upper()
    if league not in _ADAPTERS:
        raise ValueError(f"unsupported league: {league}")
    return _ADAPTERS[league]
