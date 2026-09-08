from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
from typing import Any

EVENT_SCHEMA_VERSION = "sports_information_event.v1"
FEATURE_CONTRACT_VERSION = "sports_information_state.v0_1.research"

EVENT_TYPES = {
    "PLAYER_OUT", "PLAYER_DOUBTFUL", "PLAYER_QUESTIONABLE", "PLAYER_ACTIVE",
    "LINEUP_CONFIRMED", "LINEUP_PROJECTED", "STARTER_CONFIRMED", "STARTER_SCRATCHED",
    "STARTER_PITCH_LIMIT", "BULLPEN_AVAILABLE", "BULLPEN_LIMITED", "BULLPEN_UNAVAILABLE",
    "ROSTER_CALLUP", "ROSTER_OPTION", "TRAVEL_DISRUPTION", "WEATHER_DELAY_RISK",
    "ROOF_STATUS", "WEATHER_CHANGE",
}
DESTRUCTIVE_EVENT_TYPES = {"PLAYER_OUT", "STARTER_SCRATCHED", "BULLPEN_UNAVAILABLE"}
CERTAINTY_VALUES = {"CONFIRMED", "EXPECTED", "POSSIBLE", "UNCERTAIN", "CONTRADICTED"}
CROSS_MODEL_STATES = {"CONSENSUS", "PARTIAL_AGREEMENT", "CONFLICTING", "ABSTAIN"}
PIT_STATES = {"PASS", "FAIL_POST_CUTOFF", "FAIL_BAD_CHRONOLOGY", "FAIL_TIMESTAMP_MISSING"}
SOURCE_TYPES = {"LEAGUE_OFFICIAL", "TEAM_OFFICIAL", "BEAT_REPORTER", "NEWS_OUTLET", "AGGREGATOR", "FAN_SOCIAL", "ANONYMOUS"}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_utc(value: str | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be non-empty ISO-8601 string")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


def pit_status(*, published_at_utc: str | None, retrieved_at_utc: str,
               forecast_cutoff_utc: str, game_start_utc: str) -> tuple[str, bool]:
    published = parse_utc(published_at_utc)
    retrieved = parse_utc(retrieved_at_utc)
    cutoff = parse_utc(forecast_cutoff_utc)
    start = parse_utc(game_start_utc)
    if retrieved is None or cutoff is None or start is None:
        return "FAIL_TIMESTAMP_MISSING", False
    if not cutoff < start:
        return "FAIL_BAD_CHRONOLOGY", False
    # Retrieval time is the conservative availability bound. A post that existed earlier but was
    # not captured until after cutoff was not known to the pipeline at cutoff.
    if retrieved > cutoff or (published is not None and published > cutoff):
        return "FAIL_POST_CUTOFF", False
    return "PASS", True


def deterministic_information_event_id(event: dict[str, Any]) -> str:
    core = {k: v for k, v in event.items() if k != "information_event_id"}
    return digest(core)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


@dataclass(frozen=True)
class RawSourceRecord:
    source_id: str
    source_tier: int
    source_type: str
    source_url: str | None
    post_id: str | None
    published_at_utc: str | None
    retrieved_at_utc: str
    raw_bytes_sha256: str
    forecast_cutoff_utc: str
    game_start_utc: str
    pit_status: str
    known_before_cutoff: bool

    @classmethod
    def from_bytes(cls, *, raw: bytes, source_id: str, source_tier: int, source_type: str,
                   retrieved_at_utc: str, forecast_cutoff_utc: str, game_start_utc: str,
                   published_at_utc: str | None = None, source_url: str | None = None,
                   post_id: str | None = None) -> "RawSourceRecord":
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {source_type}")
        if not 1 <= int(source_tier) <= 6:
            raise ValueError("source_tier must be 1..6")
        status, known = pit_status(
            published_at_utc=published_at_utc, retrieved_at_utc=retrieved_at_utc,
            forecast_cutoff_utc=forecast_cutoff_utc, game_start_utc=game_start_utc)
        return cls(
            source_id=source_id, source_tier=int(source_tier), source_type=source_type,
            source_url=source_url, post_id=post_id, published_at_utc=published_at_utc,
            retrieved_at_utc=retrieved_at_utc, raw_bytes_sha256=sha256_bytes(raw),
            forecast_cutoff_utc=forecast_cutoff_utc, game_start_utc=game_start_utc,
            pit_status=status, known_before_cutoff=known)


def validate_usage_policy(policy: dict[str, Any]) -> None:
    if policy.get("market_input") is not False:
        raise ValueError("market_input must be explicitly false")
    if policy.get("forecast_adjustment_eligible") is not False:
        raise ValueError("research information event cannot be forecast-adjustment eligible")
    if policy.get("action_authority") != "OFF":
        raise ValueError("action_authority must be OFF")


def validate_information_event(event: dict[str, Any]) -> dict[str, Any]:
    if event.get("schema_version") != EVENT_SCHEMA_VERSION:
        raise ValueError("unexpected information-event schema")
    claim = event.get("claim") or {}
    if claim.get("event_type") not in EVENT_TYPES:
        raise ValueError("unknown sports information event_type")
    if claim.get("certainty") not in CERTAINTY_VALUES:
        raise ValueError("unknown claim certainty")
    resolution = event.get("resolution") or {}
    if resolution.get("cross_model_state") not in CROSS_MODEL_STATES:
        raise ValueError("unknown cross_model_state")
    timing = event.get("forecast_timing") or {}
    if timing.get("pit_status") not in PIT_STATES:
        raise ValueError("unknown PIT status")
    if bool(timing.get("known_before_cutoff")) != (timing.get("pit_status") == "PASS"):
        raise ValueError("known_before_cutoff inconsistent with PIT status")
    validate_usage_policy(event.get("usage_policy") or {})
    expected_id = deterministic_information_event_id(event)
    if event.get("information_event_id") not in (None, expected_id):
        raise ValueError("information_event_id does not match canonical content")
    out = dict(event)
    out["information_event_id"] = expected_id
    return out


def write_immutable_json(path: Path, value: Any) -> None:
    data = canonical_bytes(value) + b"\n"
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"immutable output collision: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
