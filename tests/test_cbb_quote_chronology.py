from dataclasses import replace
from datetime import datetime, timezone

import pytest

from pipelines.cards.cbb_quote_chronology import (
    ChronologyError,
    PregameContext,
    check_pregame_pair_chronology,
)


def at(hour, minute=0):
    return datetime(2026, 11, 6, hour, minute, tzinfo=timezone.utc)


CTX = PregameContext(
    quote_cutoff_utc=at(9), verified_tipoff_utc=at(10),
    verification_time_utc=at(11), forecast_sealed_utc=at(8, 20),
)
EVENT = {"start_time_utc": "2026-11-06T10:00Z"}
SIDE = {"quote_retrieved_utc": "2026-11-06T08:30:00Z"}


def check(home=SIDE, away=SIDE, *, event=EVENT, ctx=CTX):
    return check_pregame_pair_chronology(event, home, away, context=ctx)


def test_same_instants_different_offsets_and_source_formats():
    result = check(
        home=dict(SIDE, start_time_utc="2026-11-06T05:00-05:00"),
        away={"quote_retrieved_utc": "2026-11-06T09:30:00+01:00",
              "retrieved_at_utc": "2026-11-06T00:30:00-08:00"},
    )
    assert result.retrieved_utc == at(8, 30)
    assert result.observation_basis == "retrieval_only"


@pytest.mark.parametrize("stamp", [CTX.forecast_sealed_utc, CTX.quote_cutoff_utc])
def test_seal_and_cutoff_boundaries_are_inclusive(stamp):
    side = {"quote_retrieved_utc": stamp.isoformat()}
    assert check(side, side).retrieved_utc == stamp


@pytest.mark.parametrize(("timestamp", "reason"), [
    ("2026-11-06T08:19:59.999999Z", "QUOTE_BEFORE_FORECAST_SEAL"),
    ("2026-11-06T09:00:00.000001Z", "QUOTE_AFTER_CUTOFF"),
    ("2026-11-06T10:00:00Z", "QUOTE_NOT_PRE_TIP"),
    ("2026-11-06T12:00:00Z", "QUOTE_NOT_PRE_TIP"),
])
def test_chronology_boundaries(timestamp, reason):
    side = {"quote_retrieved_utc": timestamp}
    with pytest.raises(ChronologyError) as caught:
        check(side, side)
    assert caught.value.reason == reason


def test_optional_seal_and_independent_verification_time():
    side = {"quote_retrieved_utc": at(8).isoformat()}
    assert check(side, side, ctx=replace(CTX, forecast_sealed_utc=None)).retrieved_utc == at(8)
    with pytest.raises(ChronologyError, match="QUOTE_AFTER_VERIFICATION"):
        check(ctx=replace(CTX, verification_time_utc=at(8, 29)))


@pytest.mark.parametrize("bad", [None, "invalid", "2026-11-06T08:30:00",
                                 "2026-11-06T08:30:00+00:60", "2026-11-06T08:30:00.0000001Z",
                                 "2026-11-31T08:30:00Z", 0])
def test_bad_quote_timestamp_on_either_side(bad):
    side = {"quote_retrieved_utc": bad}
    for home, away in ((side, SIDE), (SIDE, side)):
        with pytest.raises(ChronologyError, match="INVALID_QUOTE_RETRIEVAL"):
            check(home, away)


@pytest.mark.parametrize(("side", "reason"), [
    ({}, "INVALID_QUOTE_RETRIEVAL"),
    ({"quote_retrieved_utc": "2026-11-06T08:30:01Z"}, "PAIR_RETRIEVAL_MISMATCH"),
    (dict(SIDE, retrieved_at_utc="2026-11-06T08:29Z"), "PAIR_RETRIEVAL_MISMATCH"),
    (dict(SIDE, start_time_utc="2026-11-07T10:00Z"), "EVENT_START_MISMATCH"),
    (dict(SIDE, observed_at_utc=""), "INVALID_VENDOR_OBSERVATION"),
    (dict(SIDE, observed_at_utc="2026-11-06T08:30:00.000001Z"),
     "VENDOR_OBSERVATION_AFTER_RETRIEVAL"),
])
def test_missing_contradictory_or_future_side_evidence(side, reason):
    with pytest.raises(ChronologyError) as caught:
        check(SIDE, side)
    assert caught.value.reason == reason


def test_vendor_observation_scope():
    earlier = dict(SIDE, observed_at_utc="2026-11-06T08:28Z")
    simultaneous = dict(SIDE, observed_at_utc=SIDE["quote_retrieved_utc"])
    assert check(earlier, simultaneous).observation_basis == "vendor_observed"
    assert check(earlier, dict(SIDE, observed_at_utc=None)).observation_basis == "retrieval_only"


@pytest.mark.parametrize(("event", "reason"), [
    ({}, "INVALID_EVENT_START"),
    ({"start_time_utc": "2026-11-06T10:00"}, "INVALID_EVENT_START"),
    ({"start_time_utc": "2026-11-06T10:01Z"}, "EVENT_START_MISMATCH"),
])
def test_event_start_must_match_bound_schedule(event, reason):
    with pytest.raises(ChronologyError) as caught:
        check(event=event)
    assert caught.value.reason == reason


@pytest.mark.parametrize(("ctx", "reason"), [
    (None, "PREGAME_CONTEXT_REQUIRED"),
    (replace(CTX, quote_cutoff_utc=None), "INVALID_QUOTE_CUTOFF"),
    (replace(CTX, verified_tipoff_utc=None), "INVALID_VERIFIED_TIPOFF"),
    (replace(CTX, verification_time_utc=None), "INVALID_VERIFICATION_TIME"),
    (replace(CTX, forecast_sealed_utc=at(8).replace(tzinfo=None)), "INVALID_FORECAST_SEAL"),
])
def test_context_cannot_fall_back_to_pair(ctx, reason):
    with pytest.raises(ChronologyError) as caught:
        check(ctx=ctx)
    assert caught.value.reason == reason
