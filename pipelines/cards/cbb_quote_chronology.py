"""Chronology for an already identified pair of full-game CBB spread offers."""
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone


# ESPN schedule times may omit seconds. Reject unrepresentable precision
# instead of silently truncating an instant across a cutoff or tipoff.
_STAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-5][0-9]"
    r"(?::[0-5][0-9](?:\.[0-9]{1,6})?)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


class ChronologyError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class PregameContext:
    """Trusted inputs resolved by the caller from policy and schedule evidence."""
    quote_cutoff_utc: datetime
    verified_tipoff_utc: datetime
    verification_time_utc: datetime
    forecast_sealed_utc: datetime | None = None


@dataclass(frozen=True)
class ChronologyResult:
    retrieved_utc: datetime
    observation_basis: str


def parse_utc(value, reason: str) -> datetime:
    """Return an aware UTC instant or a caller-specific refusal reason."""
    try:
        if isinstance(value, str) and _STAMP.fullmatch(value):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if isinstance(value, datetime) and value.utcoffset() is not None:
            return value.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise ChronologyError(reason) from exc
    raise ChronologyError(reason)


def check_pregame_pair_chronology(
    event: Mapping, home: Mapping, away: Mapping, *, context: PregameContext
) -> ChronologyResult:
    if not isinstance(context, PregameContext):
        raise ChronologyError("PREGAME_CONTEXT_REQUIRED")
    cutoff = parse_utc(context.quote_cutoff_utc, "INVALID_QUOTE_CUTOFF")
    tip = parse_utc(context.verified_tipoff_utc, "INVALID_VERIFIED_TIPOFF")
    verification = parse_utc(context.verification_time_utc, "INVALID_VERIFICATION_TIME")
    if parse_utc(event.get("start_time_utc"), "INVALID_EVENT_START") != tip:
        raise ChronologyError("EVENT_START_MISMATCH")
    retrieved = parse_utc(home.get("quote_retrieved_utc"), "INVALID_QUOTE_RETRIEVAL")
    if parse_utc(away.get("quote_retrieved_utc"), "INVALID_QUOTE_RETRIEVAL") != retrieved:
        raise ChronologyError("PAIR_RETRIEVAL_MISMATCH")
    if retrieved >= tip:
        raise ChronologyError("QUOTE_NOT_PRE_TIP")
    if retrieved > cutoff:
        raise ChronologyError("QUOTE_AFTER_CUTOFF")
    if retrieved > verification:
        raise ChronologyError("QUOTE_AFTER_VERIFICATION")
    if context.forecast_sealed_utc is not None:
        seal = parse_utc(context.forecast_sealed_utc, "INVALID_FORECAST_SEAL")
        if retrieved < seal:
            raise ChronologyError("QUOTE_BEFORE_FORECAST_SEAL")
    all_observed = True
    for side in (home, away):
        if "start_time_utc" in side and parse_utc(side["start_time_utc"], "INVALID_EVENT_START") != tip:
            raise ChronologyError("EVENT_START_MISMATCH")
        if "retrieved_at_utc" in side and parse_utc(
            side["retrieved_at_utc"], "INVALID_QUOTE_RETRIEVAL"
        ) != retrieved:
            raise ChronologyError("PAIR_RETRIEVAL_MISMATCH")
        observed = side.get("observed_at_utc")
        if observed is None:
            all_observed = False
        elif parse_utc(observed, "INVALID_VENDOR_OBSERVATION") > retrieved:
            raise ChronologyError("VENDOR_OBSERVATION_AFTER_RETRIEVAL")
    return ChronologyResult(retrieved, "vendor_observed" if all_observed else "retrieval_only")
