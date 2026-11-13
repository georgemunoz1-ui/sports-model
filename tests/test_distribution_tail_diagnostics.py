import copy

import pytest

from models.common import discrete_research as D
from research.distribution_diagnostics import summarize, audit_groups


def row(eid="one", observed=3, model="test-only"):
    return {"distribution": D.make_distribution([-3, 0, 3], [.2, .6, .2],
            league="nfl", product="margin", settlement="FULL_GAME_OT_REGULAR", model_id=model,
            provenance={"event_id": eid, "cutoff": "2026-01-01T00:00:00Z"}),
            "observed": observed, "start_time_utc": "2026-01-01T01:00:00Z",
            "result_available_at": "2026-01-01T08:00:00Z", "result_source_sha256": "a" * 64}


def test_discrete_tail_uses_actual_mass_beyond_quantile():
    report = summarize([row()])
    interval = report["intervals"]["0.5"]
    assert interval == {"covered": 0., "width": 0., "lower_miss": 0., "upper_miss": 1.,
                        "lower_probability": .2, "upper_probability": .2}
    assert report["zero_probability_outcomes"] == 0


def test_zero_support_is_explicit_infinite_log_loss():
    report = summarize([row(observed=4)])
    assert report["zero_probability_outcomes"] == 1 and report["log_loss"] is None
    assert report["log_loss_status"] == "INFINITE_DUE_TO_ZERO_SUPPORT"


def test_duplicate_and_unmatched_events_cannot_inflate_sample():
    with pytest.raises(ValueError, match="DUPLICATE_DIAGNOSTIC_EVENT"):
        summarize([row(), row()])
    a, b = row(), row(model="candidate")
    assert audit_groups([[a], [b]])["matched_unique_events"] == 1
    for key, value in [("observed", 0), ("result_source_sha256", "b" * 64)]:
        bad = copy.deepcopy(b); bad[key] = value
        with pytest.raises(ValueError, match="UNMATCHED_DIAGNOSTIC_POPULATION"):
            audit_groups([[a], [bad]])


def test_invalid_observation_and_late_cutoff_refuse():
    with pytest.raises(ValueError):
        summarize([row(observed=True)])
    a = row(); a["start_time_utc"] = "2025-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="CHRONOLOGY"):
        summarize([a])
