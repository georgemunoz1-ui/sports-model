"""Counterexamples found during the October 24 PR review; synthetic only."""
import copy

import numpy as np
import pytest

from models.common.margins import cover_quote, margin_quote_record, simulated_margin, validate_record
from models.common.margins.emit import _record_hash
from pipelines.margins.validate import cover_calibration, paired_brier_vs_baseline


def fixture_records():
    return [dict(p_cover=.4, p_push=.2, probability_basis="UNCONDITIONAL",
                 line=0, actual_margin=m, orientation="home", sport="nfl",
                 season=2026, week=i + 1)
            for i, m in enumerate([-1, -1, 0, 1, 1])]


def test_nonpush_scoring_conditions_each_forecast_and_both_comparisons():
    rows = fixture_records()
    before = copy.deepcopy(rows)
    actual = cover_calibration(rows)
    assert actual["brier"] == pytest.approx(.25)
    assert actual["bias"] == pytest.approx(0)
    assert (actual["n_total"], actual["n_push"], actual["n_scored"]) == (5, 1, 4)
    paired = paired_brier_vs_baseline(rows, reps=200)
    assert paired["diff_mean"] == pytest.approx(0)
    conditional = [{**r, "p_cover": .5, "probability_basis": "CONDITIONAL_ON_NO_PUSH"} for r in rows]
    assert cover_calibration(conditional)["brier"] == pytest.approx(.25)
    assert rows == before


@pytest.mark.parametrize("mutation", [
    {"probability_basis": "UNKNOWN"}, {"p_push": float("nan")},
    {"p_push": .8}, {"p_cover": True}, {"p_push": True},
    {"line": .25}, {"actual_margin": float("inf")},
    {"line": .5}, {"p_cover": 0, "p_push": 1},
])
def test_ambiguous_or_impossible_scoring_inputs_fail(mutation):
    rows = fixture_records()
    rows[0].update(mutation)
    with pytest.raises(ValueError):
        cover_calibration(rows)


@pytest.mark.parametrize("key", ["p_push", "probability_basis"])
def test_legacy_probability_records_require_explicit_migration(key):
    rows = fixture_records()
    del rows[0][key]
    with pytest.raises(ValueError, match="RECORD_SCHEMA_MISSING_FIELDS"):
        cover_calibration(rows)


def quote_record(side):
    dist = simulated_margin(np.repeat([-1., 0., 1.], [2500, 5000, 2500]), {"fixture": "synthetic"})
    return margin_quote_record(dist, cover_quote(dist, 0, orientation=side),
        event={"event_id": "SYNTHETIC_ONLY"},
        source_model={"model_id": "fixture", "artifact_sha256": "0" * 64},
        sigma_provenance={"fixture": True}, generated_at_utc="2026-10-24T00:00:00Z")


def test_opposing_symmetric_quotes_have_different_bound_identities():
    home, away = quote_record("home"), quote_record("away")
    assert home["probabilities"] == away["probabilities"]
    assert home["orientation"] == "home"
    assert away["orientation"] == "away"
    assert home["record_sha256"] != away["record_sha256"]
    assert validate_record(home) and validate_record(away)
    altered = copy.deepcopy(home)
    altered["orientation"] = "away"
    with pytest.raises(ValueError, match="MARGIN_RECORD_HASH_MISMATCH"):
        validate_record(altered)


@pytest.mark.parametrize("key,value", [
    ("schema", "sports.margin_quote.v1"), ("orientation", "unknown"),
    ("probability_basis", "CONDITIONAL_ON_NO_PUSH"),
    ("home_spread", .25), ("payoff_contract", "QUARTER_HANDICAP"),
])
def test_resealing_does_not_bypass_contract_validation(key, value):
    record = quote_record("home")
    record[key] = value
    record["record_sha256"] = _record_hash(record)
    with pytest.raises(ValueError):
        validate_record(record)


def test_generic_three_outcome_api_refuses_quarter_lines():
    dist = simulated_margin(np.zeros(10000), {"fixture": "synthetic"})
    with pytest.raises(ValueError, match="COVER_FRACTIONAL_SETTLEMENT_UNSUPPORTED"):
        cover_quote(dist, .25)
