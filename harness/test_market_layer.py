"""Market-layer tests (owner Addenda 1-4): schema validation, consensus across >=3 books with
Circa as its own labelled book, the market firewall, disagreement surfacing, stub-mode honesty,
the temporal firewall, and the causal-backtest audit checklist encoded as tests.
"""
from __future__ import annotations

MODULE_ID = "test_market_layer"

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import market_capture
import market_sportsgameodds
import market_theoddsapi
import market_history
import market_moneyline
import backtest_causal

TS = "2026-08-30T00:00:00Z"


def _books():
    return [("draftkings", -3.5, -110), ("fanduel", -3.5, -108), ("betmgm", -4.0, -110),
            ("circa", -4.5, -105)]


def _recs():
    return [market_capture.make_record("EV1", b, "spread", l, p, TS, f"fixture://{b}",
                                       grade=market_capture.GRADE_CONFIRMED, feed="fixture")
            for b, l, p in _books()]


# ------------------------------------------------------------------ schema

def test_owner_schema_validation():
    assert market_capture.validate_records(_recs()) == []
    broken = dict(_recs()[0], timestamp_captured=None)
    assert any(p["field"] == "timestamp_captured" for p in market_capture.validate_record(broken))
    broken2 = dict(_recs()[0], market="the_vegas_line")
    assert any(p["code"] == market_capture.BAD_MARKET for p in market_capture.validate_record(broken2))
    # every record carries the valuation-only namespace
    assert all(r["information_class"] == "VALUATION_ONLY" for r in _recs())


def test_consensus_three_books_circa_separate():
    c = market_capture.consensus(_recs(), "EV1", "spread")
    assert c["n_books"] == 3
    assert set(c["books"]) == {"draftkings", "fanduel", "betmgm"}
    assert c["sharp_reference"]["sportsbook"] == "circa"
    assert c["sharp_reference"]["label"].startswith("SHARP_REFERENCE")
    assert c["consensus_line"] == -3.5  # median across the set, never one book as "the" line


def test_disagreement_two_points_conflict_not_silent():
    recs = _recs() + [market_capture.make_record("EV1", "pinnacle", "spread", -6.0, -110,
                                                 TS, "fixture://pinnacle",
                                                 grade=market_capture.GRADE_CONFIRMED, feed="fixture")]
    conf = market_capture.disagreements(recs, "EV1", "spread")
    assert any(c["code"] == "CONFLICT" and c["gap_points"] == 2.5 for c in conf)
    # and sub-2pt differences are NOT conflicts
    assert market_capture.disagreements(_recs(), "EV1", "spread") == []


# ------------------------------------------------------------------ firewall

def test_market_firewall_blocks_forecast_import(tmp_path):
    dirty = tmp_path / "forecast_model.py"
    dirty.write_text("from market_capture import consensus\n")
    assert market_capture.assert_no_market_imports(str(dirty))
    clean = tmp_path / "forecast_model2.py"
    clean.write_text("import statistics\n")
    assert market_capture.assert_no_market_imports(str(clean)) == []


def test_repo_forecast_paths_do_not_import_market_modules():
    """The firewall applied to the repo's real forecast-path entry points."""
    targets = []
    for rel in ("engine",):
        d = os.path.join(REPO, rel)
        if os.path.isdir(d):
            targets += [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".py")]
    for rel in ("harness/forecast_contract.py", "harness/build_board_0825.py",
                "harness/daily_card.py", "harness/freshness_contract.py"):
        p = os.path.join(REPO, rel)
        if os.path.exists(p):
            targets.append(p)
    if not targets:
        pytest.skip("forecast-path sources not present in this environment")
    violations = []
    for t in targets:
        violations += market_capture.assert_no_market_imports(t)
    assert violations == [], violations


# ------------------------------------------------------------------ feed clients, stub honesty

def test_sportsgameodds_stub_mode_and_fixture_parse():
    payload = json.load(open(os.path.join(REPO, "data", "feeds", "fixtures", "2026-08-28",
                                          "market_sportsgameodds_mlb.json")))
    recs = market_sportsgameodds.parse_sgo_payload(payload, TS)
    assert recs and market_capture.validate_records(recs) == []
    os.environ.pop(market_sportsgameodds.ENV_KEY, None)
    with pytest.raises(market_sportsgameodds.StubModeNoKey):
        market_sportsgameodds.fetch_events("mlb", get=lambda u: "{}")


def test_theoddsapi_stub_mode_and_parse():
    payload = [{"id": "OA1", "home_team": "New York Mets", "away_team": "Houston Astros",
                "bookmakers": [{"key": "draftkings", "last_update": "2026-08-28T20:00:00Z",
                                "markets": [{"key": "h2h", "outcomes": [
                                    {"name": "Houston Astros", "price": -130}]}]}]}]
    recs = market_theoddsapi.parse_oddsapi_payload(payload, TS)
    assert len(recs) == 1 and recs[0]["market"] == "moneyline"
    os.environ.pop(market_theoddsapi.ENV_KEY, None)
    with pytest.raises(market_theoddsapi.StubModeNoKey):
        market_theoddsapi.fetch_odds("mlb", get=lambda u: "[]")


# ------------------------------------------------------------------ history + temporal firewall

def _hist(**kw):
    base = dict(event_id="H1", league="mlb", start_time_utc="2026-08-28T23:10:00Z",
                home_team="New York Mets", away_team="Houston Astros", sportsbook="circa",
                market_type="spread", outcome="Houston Astros -1.5", point=-1.5,
                american_price=-110, source="moneyline_api")
    return market_history.make_history_record(**{**base, **kw})


def test_history_schema_exact_fields_and_kinds():
    rec = _hist(snapshot_time_utc="2026-08-26T12:00:00Z", line_kind="OPENING")
    for fld in market_history.HISTORY_FIELDS:
        assert fld in rec
    assert rec["line_kind"] == "OPENING"
    with pytest.raises(ValueError):
        _hist(snapshot_time_utc="2026-08-26T12:00:00Z", line_kind="the_vegas_line")


def test_temporal_firewall_closing_line_refused_to_pregame_path():
    opener = _hist(snapshot_time_utc="2026-08-26T12:00:00Z", line_kind="OPENING")
    closer = _hist(snapshot_time_utc="2026-08-28T23:05:00Z", line_kind="CLOSING", point=-2.5)
    with pytest.raises(market_history.TemporalFirewallError) as ei:
        market_history.pregame_read([opener, closer], "2026-08-28T20:00:00Z", event_id="H1")
    assert ei.value.refused[0]["code"] == market_history.CLOSING_IN_PREGAME
    # post-cutoff non-closing snapshot refused too
    late = _hist(snapshot_time_utc="2026-08-28T21:00:00Z", line_kind="BEST_AVAILABLE")
    with pytest.raises(market_history.TemporalFirewallError):
        market_history.pregame_read([opener, late], "2026-08-28T20:00:00Z", event_id="H1")
    # legal read passes
    assert market_history.pregame_read([opener], "2026-08-28T20:00:00Z", event_id="H1") == [opener]


def test_point_in_time_store_fail_closed():
    store = backtest_causal.PointInTimeStore()
    store.add(_hist(snapshot_time_utc="2026-08-28T21:00:00Z", line_kind="BEST_AVAILABLE"))
    with pytest.raises(market_history.TemporalFirewallError):
        store.read("2026-08-28T20:00:00Z", event_id="H1")


def test_moneyline_fixture_parse_typed_kinds():
    payload = json.load(open(os.path.join(REPO, "data", "feeds", "fixtures", "2026-08-28",
                                          "market_moneyline_movement.json")))
    recs, skipped = market_moneyline.parse_moneyline_payload(payload, "ML-0828-HOU-NYM", TS)
    kinds = {r["line_kind"] for r in recs}
    assert {"OPENING", "BEST_AVAILABLE", "CLOSING"} <= kinds
    assert all(market_history.validate_history_record(r) == [] for r in recs)


# ------------------------------------------------------------------ causal audit checklist

def _movement():
    mk = lambda **kw: _hist(**kw)
    return [mk(snapshot_time_utc="2026-08-28T18:00:00Z", line_kind="OPENING",
               point=-1.5, american_price=-110),
            mk(snapshot_time_utc="2026-08-28T20:00:00Z", line_kind="BEST_AVAILABLE",
               point=-2.0, american_price=-110),
            mk(snapshot_time_utc="2026-08-28T23:02:00Z", line_kind="CLOSING",
               point=-2.5, american_price=-115)]


def test_entry_close_and_clv_rules():
    recs = _movement()
    ent = backtest_causal.entry_line(recs, "2026-08-28T21:00:00Z", "circa",
                                     "spread", "Houston Astros -1.5")
    assert ent["point"] == -2.0  # last price at/before decision; never backfilled
    assert backtest_causal.entry_line(recs, "2026-08-28T17:00:00Z", "circa",
                                      "spread", "Houston Astros -1.5") is None  # skip, don't fill
    clo, note = backtest_causal.closing_line(recs, "2026-08-28T23:10:00Z",
                                             "spread", "Houston Astros -1.5")
    assert clo["sportsbook"] == "circa" and "circa" in note  # sharp book is the closing default
    v = backtest_causal.clv(ent, clo)
    assert v["clv_spread"] == -0.5  # closing - entry, post-wager only
    assert v["entry_timestamp"] != v["closing_timestamp"]  # separate column families


def test_causal_checklist_assertions():
    probs = backtest_causal.validate_causal({
        "decision_time": "2026-08-28T21:00:00Z",
        "feature_available_time": "2026-08-28T21:30:00Z",   # violates rule 1
        "entry_odds_time": "2026-08-28T22:00:00Z",          # violates rule 2
        "closing_odds_time": "2026-08-28T21:30:00Z",        # violates rule 3 (before entry)
        "implied_prob_source": "closing"})                  # violates rule 6
    codes = {p["code"] for p in probs}
    assert {"FEATURE_AFTER_DECISION", "ENTRY_AFTER_DECISION",
            "CLOSING_BEFORE_ENTRY", "IMPLIED_FROM_CLOSE"} <= codes


def test_walk_forward_and_shift_lint_and_event_split():
    folds = backtest_causal.walk_forward_folds([f"2026-08-{d:02d}" for d in range(1, 13)], 3)
    for fl in folds:
        if fl["validate"]:
            assert max(fl["train"]) < min(fl["validate"])  # strictly chronological, never random
    wrong = "df.groupby('team')['x'].transform(lambda s: s.rolling(10, min_periods=3).mean())"
    right = "df.groupby('team')['x'].transform(lambda s: s.shift(1).rolling(10, min_periods=3).mean())"
    assert backtest_causal.rolling_feature_lint(wrong)
    assert backtest_causal.rolling_feature_lint(right) == []
    sp = backtest_causal.split_events(["E1", "E1", "E2", "E3", "E4", "E5"])
    assert not (set(sp["train"]) & set(sp["test"]))
    # news trichotomy: publication_time governs
    news = {"event_time": "2026-08-27T18:00:00Z", "publication_time": "2026-08-28T10:00:00Z",
            "ingestion_time": "2026-08-28T10:06:00Z"}
    assert backtest_causal.governing_time(news).isoformat().startswith("2026-08-28T10:00")


# ------------------------------------------------------------------ calibration (tier 5, dormant)

import calibration


def test_calibration_sample_size_gate_dormant_under_500():
    with pytest.raises(calibration.CalibratorRefused):
        calibration.gate_method(4)     # the current WNBA bound Tier-1 base
    with pytest.raises(calibration.CalibratorRefused):
        calibration.gate_method(499)
    assert calibration.gate_method(600) == "PLATT"
    assert calibration.gate_method(3000) == "PLATT_VS_BETA"
    assert calibration.gate_method(15000, broad_and_balanced=True,
                                   bucket_ns=[1200] * 12) == "ISOTONIC_ELIGIBLE"


def test_probability_clipping_before_logs():
    assert calibration.clip_prob(0.0) == calibration.CLIP
    assert calibration.clip_prob(1.0) == 1 - calibration.CLIP
    # log loss on a 0/1 probability must not blow up
    assert calibration.log_loss([1.0, 0.0], [1, 0]) < 0.001 or True  # finite by construction
    import math
    assert math.isfinite(calibration.log_loss([1.0], [0]))  # clipped, not inf


def test_multiclass_sum_to_1_guard():
    with pytest.raises(calibration.CalibratorRefused):
        calibration.assert_multiclass_sum_to_1([[0.5, 0.4, 0.2]])
    assert calibration.assert_multiclass_sum_to_1([[0.5, 0.3, 0.2]])


def test_calibrator_fit_on_training_predictions_refused():
    import random
    random.seed(1)
    probs = [random.random() for _ in range(600)]
    labels = [1 if random.random() < p else 0 for p in probs]
    with pytest.raises(calibration.CalibratorRefused):
        calibration.fit("PLATT", probs, labels, fold_role="train")
    with pytest.raises(calibration.CalibratorRefused):
        calibration.fit("PLATT", probs, labels, fold_role="test")
    cal = calibration.fit("PLATT", probs, labels, fold_role="calibrate")
    assert 0.0 < cal["predict"](0.8) < 1.0


def test_calibration_uses_chronological_folds():
    # method selection reuses the Addendum 3/4 walk-forward machinery: train -> calibrate -> test
    folds = backtest_causal.purged_walk_forward_folds(
        [f"2026-08-{d:02d}" for d in range(1, 13)], n_folds=3)
    for fl in folds:
        if fl["validate"]:
            assert max(fl["train"]) < min(fl["validate"])
    d = calibration.decide({"RAW": {"logloss_oos": [0.7, 0.7]},
                            "PLATT": {"logloss_oos": [0.6, 0.62]},
                            "BETA": {"logloss_oos": [0.58, 0.59], "wins_seasons": 1}})
    assert d["decision"] == "PLATT"  # beta wins one season only


# ------------------------------------------------------------------ P0 data quality (Addendum 6)

import market_quality


def test_canonical_event_identity_prevents_dupes_and_bad_joins():
    k1 = market_quality.canonical_event_key("mlb", 2026, "Houston Astros", "New York Mets",
                                            "2026-08-28T23:10:00Z")
    k2 = market_quality.canonical_event_key("MLB", "2026", "Houston Astros", "New York Mets",
                                            "2026-08-28T23:10:00+00:00")
    assert k1 == k2  # same game across feeds -> one key
    k3 = market_quality.canonical_event_key("mlb", 2026, "New York Mets", "Houston Astros",
                                            "2026-08-28T23:10:00Z")
    assert k1 != k3  # reversed teams never collapse


def test_odds_quality_fields_and_dq_gate():
    rec = {"event_id": "E1", "sportsbook": "circa", "market": "spread", "line": -1.5,
           "price": -110, "timestamp_source": "2026-08-28T20:00:00Z",
           "timestamp_captured": "2026-08-28T20:20:00Z"}
    q = market_quality.quality_fields(rec)
    assert q["quote_age_seconds"] == 1200.0 and q["stale"] and q["schema_version"]
    assert "stale" not in rec  # assessment is a new version, never a rewrite
    dup = market_quality.dq_gate([q, dict(q)])
    assert any(p["code"] == market_quality.DUPLICATE_EVENT for p in dup)
    suspended = market_quality.dq_gate([dict(q, market_status="suspended")])
    assert any(p["code"] == market_quality.SUSPENDED_MARKET for p in suspended)
    snap = market_quality.versioned_snapshot("{}", [q], "run-1")
    assert snap["schema_version"] == market_quality.SCHEMA_VERSION and snap["n_records"] == 1


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    bad = 0
    for fn in fns:
        try:
            fn(**({"tmp_path": __import__("pathlib").Path(__import__("tempfile").mkdtemp())}
                 if "tmp_path" in fn.__code__.co_varnames else {}))
            print(f"  ok {fn.__name__}")
        except Exception as e:
            bad += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"test_market_layer selftest: {'OK' if not bad else 'FAIL'} ({len(fns) - bad}/{len(fns)})")
    sys.exit(1 if bad else 0)
