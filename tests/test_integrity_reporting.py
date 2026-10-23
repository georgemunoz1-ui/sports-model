import copy
import hashlib
import json

import pytest

from pipelines.cards.integrity_reporting import integrity_report, render_integrity_md, REVIEW_CLASS

CUTOFF = "2026-10-22T15:00:00Z"
HASH = "a" * 64


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def card(league="NHL"):
    features = {"home_rest": 3.25, "away_rest": 5.25}
    return {"league": league, "as_of_utc": CUTOFF, "forecasts": [{
        "event_id": "event-1", "model_id": "parent.v1", "home_team": "H", "away_team": "A",
        "home_id": "h", "away_id": "a", "start_time_utc": "2026-10-23T00:00:00Z",
        "forecast_status": "FORECAST_GENERATED", "model_winner": "A", "model_p": .6,
        "input_snapshot_hash": digest(features), "model_state_config_hash": HASH,
        "model_input_snapshot": features, "diagnostics": {"home_margin": -.4}}]}


def freshness(c):
    from models.current.freshness import state_freshness_receipt
    row = c["forecasts"][0]
    package = {"model_id": row["model_id"], "model_sha256": HASH, "training_cutoff_utc": CUTOFF,
               "team_state": {"h": {"last": "2026-10-19T18:00:00Z"}, "a": {"last": "2026-10-17T18:00:00Z"}}}
    row["diagnostics"]["state_freshness_receipt"] = state_freshness_receipt(package, row, row["model_input_snapshot"], cutoff_utc=CUTOFF)
    return c


def receipt(c, terms=None):
    row = c["forecasts"][0]
    row["model_input_snapshot"]["starting_goalie_rating"] = .3
    row["input_snapshot_hash"] = digest(row["model_input_snapshot"])
    out = {"schema": "sports.numerical_consumption_receipt.v1", "event_id": row["event_id"],
           "model_id": row["model_id"], "input_snapshot_hash": row["input_snapshot_hash"],
           "model_state_config_hash": HASH, "cutoff_utc": CUTOFF, "rows": [{
           "feature": "starting_goalie_rating", "feature_group": "goalie", "active_in_run": True,
           "implemented": True, "fitted_artifact_available": True, "pregame_eligible": True,
           "contribution_method": "exact_centered_linear_term", "contribution": {"home_win": .01} if terms is None else terms,
           "lineage": {"model_artifact_sha256": HASH, "feature_value_sha256": digest(.3)}}]}
    out["receipt_sha256"] = digest(out)
    row["diagnostics"]["numerical_consumption_receipt"] = out
    return c


@pytest.mark.parametrize("league", ["NFL", "CFB", "NBA", "NHL", "WNBA", "MLB", "MLS"])
def test_missing_receipts_are_unknown_and_parent_unchanged(league):
    c = card(league); before = copy.deepcopy(c)
    report = integrity_report(c); rendered = render_integrity_md(c)
    assert c == before and report["status"] == "DIAGNOSTIC_NOT_CERTIFICATION"
    assert report["events"][0]["state_freshness"]["status"] == "UNKNOWN"
    assert "UNKNOWN" in rendered and "not certification" in rendered
    assert report["events"][0]["numerical_consumption"]["status"] == "INPUT_PRESENT_USE_UNPROVEN"
    assert not report["probabilities_modified"] and not report["selection_modified"]


def test_freshness_shows_consumed_age_not_capture_time_and_rest_trace():
    c = freshness(card()); report = integrity_report(c)["events"][0]
    assert report["state_freshness"]["status"] == "RECEIPT_BOUND"
    assert report["state_freshness"]["per_side"]["away"]["state_age_at_cutoff_hours"] == 117
    assert report["numerical_consumption"]["rest_feature_traces"] == ["home", "away"]
    assert "2026-10-17T18:00:00Z (117.0h)" in render_integrity_md(c)
    assert "effect size unmeasured" in render_integrity_md(c)


@pytest.mark.parametrize("key,value", [("event_id", "wrong"), ("input_snapshot_hash", "b" * 64),
    ("model_state_config_hash", "b" * 64), ("cutoff_utc", "2026-10-21T15:00:00Z")])
def test_wrong_parent_receipts_never_assert_state_known(key, value):
    c = freshness(card()); r = c["forecasts"][0]["diagnostics"]["state_freshness_receipt"]
    r[key] = value; r.pop("receipt_sha256"); r["receipt_sha256"] = digest(r)
    assert integrity_report(c)["events"][0]["state_freshness"]["status"] == "UNKNOWN"


def test_tamper_nonfinite_or_bad_age_cannot_claim_freshness():
    c = freshness(card()); r = c["forecasts"][0]["diagnostics"]["state_freshness_receipt"]
    r["per_side"]["away"]["state_age_at_cutoff_hours"] = 1
    assert integrity_report(c)["events"][0]["state_freshness"]["status"] == "UNKNOWN"
    r.pop("receipt_sha256"); r["receipt_sha256"] = digest(r)
    assert integrity_report(c)["events"][0]["state_freshness"]["per_side"]["away"]["state_age_at_cutoff_hours"] is None


def test_head_and_distribution_sign_disclosure_preserves_forecast():
    c = card("NBA"); row = c["forecasts"][0]
    row["diagnostics"] = {"home_margin": -1.12, "joint_distribution": {"mean_margin": .28},
                          "score_simulation": {"mean_margin": .29}}
    before = copy.deepcopy(c); m = integrity_report(c)["events"][0]["margins"]
    assert m["sign_disagreement"] and m["orientation"] == "HOME_MINUS_AWAY"
    assert len(m["sibling_distributions"]) == 1
    assert "-1.12 / +0.28" in render_integrity_md(c)
    assert "HEAD_DISTRIBUTION_SIGN_DISAGREEMENT" in render_integrity_md(c)
    assert c == before


def test_ambiguous_margin_is_unknown_explicit_away_orientation_is_correct():
    c = card(); row = c["forecasts"][0]; row["diagnostics"] = {}; row["projected_margin"] = .7
    assert integrity_report(c)["events"][0]["margins"]["head_home_margin"] is None
    row["projected_margin_orientation"] = "WINNER_MINUS_OPPONENT"
    assert integrity_report(c)["events"][0]["margins"]["head_home_margin"] == -.7
    row["projected_margin"] = float("nan")
    assert integrity_report(c)["events"][0]["margins"]["head_home_margin"] is None


@pytest.mark.parametrize("p,mean,winner,expected", [(.6, -.4, "A", True), (.5, -.4, "A", False),
    (.6, -1., "A", False), (.6, .4, "H", False), (.6, None, "A", False)])
def test_nhl_review_exact_scope_never_a_fade(p, mean, winner, expected):
    c = card(); row = c["forecasts"][0]; row.update(model_p=p, model_winner=winner); row["diagnostics"]["home_margin"] = mean
    event = integrity_report(c)["events"][0]
    assert (REVIEW_CLASS in event["review_flags"]) is expected
    assert event["review_action"] == "REVIEW_ONLY_NO_AUTO_FADE" and row["model_p"] == p


def test_bound_zero_term_is_use_not_nonzero_effect_and_suppresses_only_unconsumed_flag():
    c = receipt(card(), terms={"home_win": 0.})
    event = integrity_report(c)["events"][0]; trace = event["numerical_consumption"]["traces"][0]
    assert trace["nonzero_reported_term"] is False
    assert event["numerical_consumption"]["goalie_numerical_trace_bound"]
    assert REVIEW_CLASS not in event["review_flags"]
    assert "NOT_CAUSAL" in trace["scope"]


def test_claimed_usage_without_matching_fitted_trace_is_not_proof():
    c = receipt(card()); r = c["forecasts"][0]["diagnostics"]["numerical_consumption_receipt"]
    r["rows"][0]["lineage"]["model_artifact_sha256"] = "b" * 64
    r.pop("receipt_sha256"); r["receipt_sha256"] = digest(r)
    event = integrity_report(c)["events"][0]
    assert not event["numerical_consumption"]["traces"] and REVIEW_CLASS in event["review_flags"]


def test_card_render_escapes_data_and_handles_absent_rows():
    c = card(); c["forecasts"][0]["away_team"] = "<script>|\nX"
    rendered = render_integrity_md(c)
    assert "<script>" not in rendered and "&lt;script&gt;&#124; X" in rendered
    assert "No forecast rows" in render_integrity_md({})


def test_nonfinite_parent_features_remain_diagnostic_without_render_failure():
    c = freshness(card()); c["forecasts"][0]["model_input_snapshot"]["away_rest"] = float("nan")
    report = integrity_report(c)
    assert report["events"][0]["state_freshness"]["status"] == "UNKNOWN"
    assert "PARENT_FEATURE_HASH_MISMATCH" in render_integrity_md(c)


def test_existing_nfl_capability_report_is_bound_to_actual_head_features():
    from models.nfl.contextual.capabilities import reporter_hash
    c = card("NFL"); row = c["forecasts"][0]
    cap = {"schema": "nfl.capabilities.v1", "event_id": row["event_id"], "model_id": row["model_id"],
           "cutoff_utc": CUTOFF, "reporter_sha256": reporter_hash(), "rows": [{
           "feature": "home_rest", "feature_group": "rest_venue", "active_in_run": True,
           "implemented": True, "fitted_artifact_available": True, "pregame_eligible": True,
           "value_status": "derived", "contribution_method": "exact_centered_linear_term",
           "contribution": {"home_win": .01, "home_margin": .1, "total_points": -.1},
           "lineage": {"model_artifact_sha256": HASH, "feature_value_sha256": digest(3.25)}}]}
    row["diagnostics"]["capability_report"] = cap
    report = integrity_report(c)["events"][0]["numerical_consumption"]
    assert report["status"] == "NUMERICAL_TRACE_BOUND" and len(report["traces"]) == 1
    cap["model_id"] = "other.arm"
    assert not integrity_report(c)["events"][0]["numerical_consumption"]["traces"]


def test_external_distribution_requires_exact_parent_then_discloses_sign():
    from models.common import discrete_research as D
    c = card("NBA"); row = c["forecasts"][0]
    d = D.make_distribution([-1, 2], [.2, .8], league="nba", product="margin", settlement="FULL_GAME_OT",
        model_id="child.v1", provenance={"event_id": row["event_id"], "cutoff": CUTOFF,
        "parent_model_id": row["model_id"], "parent_forecast_sha256": D.digest(row)})
    c["distribution_research_report"] = {"results": [{"event_id": row["event_id"], "distribution": d}]}
    m = integrity_report(c)["events"][0]["margins"]
    assert m["sign_disagreement"] and m["sibling_distributions"][0]["mean_home_margin"] == pytest.approx(1.4)
    row["input_snapshot_hash"] = "b" * 64
    m = integrity_report(c)["events"][0]["margins"]
    assert not m["sibling_distributions"] and m["reasons"] == ["SIBLING_DISTRIBUTION_INVALID_OR_UNBOUND"]
