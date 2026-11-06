"""Engineering fixtures only; no synthetic event is predictive evidence."""
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from pipelines import daily_research as D

NOW = dt.datetime(2026, 11, 2, 12, tzinfo=dt.timezone.utc)
START = "2026-11-03T23:00:00Z"


def current(**changes):
    return dict(game_id=123, season=2026, week=10, home_team="Home", away_team="Away",
                home_division="fbs", away_division="fbs", start_date=START, completed=False, **changes)


def payload():
    return {"events": [{"id": "123", "date": START, "status": {"type": {"name": "STATUS_SCHEDULED", "state": "pre", "completed": False}}, "competitions": [{"competitors": [
        {"homeAway": "home", "team": {"location": "Home", "displayName": "Home Team"}},
        {"homeAway": "away", "team": {"location": "Away", "displayName": "Away Team"}},
    ]}]}]}


def reconcile(rows=None, source=None):
    return D.reconcile_schedule(rows if rows is not None else [current()], source if source is not None else payload(), "2026-11-03", NOW)


def test_exact_schedule_match_and_no_markets_consumed():
    p = payload()
    p["events"][0]["odds"] = {"homeProbability": .99}
    r = reconcile(source=p)
    assert r[0]["status"] == "PREGAME"
    assert r[0]["event_id"] == "CFB:123"
    assert "odds" not in r[0]


@pytest.mark.parametrize("change,reason", [
    ({"home_team": "Other"}, "TEAM_CONFLICT"),
    ({"start_date": "2026-11-03T23:01:00Z"}, "START_CONFLICT"),
    ({"season": 2025}, "SEASON_MISMATCH"),
    ({"completed": True}, "FUTURE_FINAL"),
])
def test_schedule_conflicts_fail(change, reason):
    row = current(); row.update(change)
    with pytest.raises(ValueError, match=reason): reconcile([row])


def test_missing_provider_does_not_become_empty_slate():
    with pytest.raises(ValueError, match="MISSING_FROM_PROVIDER"):
        reconcile(source={"events": []})


def test_provider_only_event_requires_division():
    with pytest.raises(ValueError, match="UNCLASSIFIED"):
        reconcile([])


@pytest.mark.parametrize("division", [None, "", "unknown"])
def test_missing_division_not_mislabeled_supported_or_lower_division(division):
    row = current()
    row["away_division"] = division
    with pytest.raises(ValueError, match="SCHEDULE_DIVISION_UNVERIFIED"):
        reconcile([row])


def test_no_games_requires_both_schedules_empty():
    assert reconcile([], {"events": []}) == []
    with pytest.raises(ValueError, match="SCHEDULE_EVENTS_REQUIRED"):
        reconcile([], {})


def test_started_and_out_of_scope_visible():
    row = current(); row["start_date"] = "2026-11-02T10:00:00Z"
    source = payload(); source["events"][0]["date"] = row["start_date"]
    result = D.reconcile_schedule([row], source, "2026-11-02", NOW)
    assert result[0]["status"] == "POST_START"
    row = current(); row["away_division"] = "fcs"
    assert reconcile([row])[0]["status"] == "NOT_SUPPORTED_FBS_VS_FCS_OR_LOWER"


def test_duplicate_current_and_schedule_rejected():
    with pytest.raises(ValueError, match="DUPLICATE_CURRENT"):
        reconcile([current(), current()])
    p = payload(); p["events"] *= 2
    with pytest.raises(ValueError, match="DUPLICATE_SCHEDULE"):
        reconcile(source=p)


def test_original_bytes_retained_on_pin_failure(tmp_path):
    rec = D._capture(tmp_path, ("binary/input", "https://example.test", "0" * 64, "pinned_cfb_history"), lambda _: b"actual")
    assert rec["status"] == "FAILED" and rec["error"] == "PIN_MISMATCH"
    assert (tmp_path / "binary/input").read_bytes() == b"actual"
    assert rec["provider_observed_at_utc"] is None
    assert rec["historical_pregame_eligibility"] is False


def test_capture_transport_failure_explicit(tmp_path):
    def fail(url): raise OSError("ACCESS_DENIED")
    rec = D._capture(tmp_path, ("raw/input", "https://example.test", None, "cfb_current"), fail)
    assert rec["status"] == "FAILED"
    assert "ACCESS_DENIED" in rec["error"]
    assert not (tmp_path / "raw/input").exists()


def test_run_failure_is_sealed_and_never_replaces_prior(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "utcnow", lambda: NOW)
    output = tmp_path / "attempt"
    result = D.run("2026-11-01", output)
    assert result["status"] == "FAILED"
    assert result["error"] == "CURRENT_OR_NEXT_SIX_DAYS_REQUIRED_NO_BACKDATE"
    assert result["registered_count"] == 0
    from scripts.daily_research_archive import verify_directory
    verify_directory(output)
    original = (output / "run.json").read_bytes()
    with pytest.raises(FileExistsError): D.run("2026-11-02", output)
    assert (output / "run.json").read_bytes() == original


def test_no_game_route_never_claims_forecast_or_registration(tmp_path, monkeypatch):
    import pandas as pd
    monkeypatch.setattr(D, "utcnow", lambda: NOW)
    def capture(root, date, **kwargs):
        root.mkdir()
        (root / "binary").mkdir(); (root / "raw").mkdir()
        pd.DataFrame([current()]).to_parquet(root / "binary/cfb_current.parquet")
        (root / "raw/espn_schedule.json").write_text(json.dumps({"events": []}))
        (root / "report.json").write_text(json.dumps({"sources": [{"path": "raw/espn_schedule.json"}]}))
        return {"slate_date": date}
    monkeypatch.setattr(D, "capture_cfb", capture)
    monkeypatch.setattr(D, "verify_acquisition", lambda _: [])
    r = D.run("2026-11-02", tmp_path / "empty")
    assert r["status"] == "NO_GAMES_VERIFIED"
    assert r["forecast_count"] == r["registered_count"] == 0
    assert r["forward_forecast_run"] is False
    assert r["publication_eligibility"] == "INELIGIBLE"
    assert r["wagering_authority"] == "OFF"


def bound_card():
    selected = "cfb.fbs.elo_form_logit_ridge.v1_0.shadow"
    cutoff = "2026-11-02T11:00:00+00:00"
    row = {"event_id": "CFB:123", "model_id": selected, "home_team": "Home", "away_team": "Away",
           "start_time_utc": START, "forecast_status": "FORECAST_GENERATED", "model_winner": "Home",
           "analytic_p": .6, "stochastic_sim_p": .6, "input_snapshot_hash": "input", "model_state_config_hash": "model",
           "simulation": {"binary": {"count": 1000, "seed": 1, "sha256": "1" * 64, "home_win_probability": .6}},
           "grading": {"eligibility_reason": "REGISTRATION_ATTESTATION_REQUIRED"},
           "diagnostics": {"package_sha256": "package"}, "dose": 0, "action_authority": False}
    card = {"league": "CFB", "requested_as_of_utc": cutoff, "generated_at_utc": "2026-11-02T11:01:00Z",
            "pit_provenance": {"pit_status": "PIT_ORDERED", "max_source_timestamp_utc": "2026-11-02T10:59:00Z",
                               "source_fetches": [{"fetched_at_utc": "2026-11-02T10:59:00Z"}],
                               "source_attestation": {"status": "RAW_BYTES_AND_RECEIPTS_VERIFIED"}},
            "forecasts": [row], "coverage_breach_event_ids": [], "incidents": []}
    package = {"model_id": selected, "_file_sha256": "package"}
    return card, reconcile(), package, cutoff, NOW


def test_valid_card_ready_for_existing_writer_not_registration():
    assert D.verify_card(*bound_card()) == {"CFB:123"}


@pytest.mark.parametrize("mutation,reason", [
    (lambda c: c.update(forecasts=[]), "COVERAGE_INCOMPLETE"),
    (lambda c: c.update(official_release=True), "RESEARCH_AUTHORITY_REQUIRED"),
    (lambda c: c.update(wagering_authority="ACTION_ENABLED"), "RESEARCH_AUTHORITY_REQUIRED"),
    (lambda c: c["forecasts"][0].update(home_team="Changed"), "SCHEDULE_BINDING_MISMATCH"),
    (lambda c: c["forecasts"][0]["diagnostics"].update(package_sha256="wrong"), "PACKAGE_BINDING_MISMATCH"),
    (lambda c: c["forecasts"][0].update(dose=.1), "NONZERO_DOSE"),
    (lambda c: c["forecasts"][0].update(action_authority=True), "FIREWALL_FAIL"),
    (lambda c: c["forecasts"][0].update(analytic_p=True), "INVALID_PROBABILITY"),
    (lambda c: c["pit_provenance"]["source_attestation"].update(status="SOURCE_RETENTION_UNVERIFIED"), "SOURCE_RETENTION_UNVERIFIED"),
])
def test_malformed_or_ineligible_card_refused(mutation, reason):
    args = bound_card()
    mutation(args[0])
    with pytest.raises(ValueError, match=reason): D.verify_card(*args)


def test_start_crossing_never_registers_late_card():
    args = list(bound_card()); args[-1] = D.instant(START)
    with pytest.raises(ValueError, match="COVERAGE_INCOMPLETE"): D.verify_card(*args)


def test_tbd_kickoff_not_assumed():
    row = current(); row["start_time_tbd"] = True
    with pytest.raises(ValueError, match="START_TIME_TBD"): reconcile([row])


@pytest.mark.parametrize("status", ["STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_DELAYED", "STATUS_FINAL"])
def test_future_event_requires_explicit_scheduled_state(status):
    source = payload()
    source["events"][0]["status"]["type"]["name"] = status
    with pytest.raises(ValueError, match="FUTURE_EVENT_NOT_VERIFIED_SCHEDULED"):
        reconcile(source=source)


def test_missing_provider_status_does_not_become_pregame():
    source = payload()
    del source["events"][0]["status"]
    with pytest.raises(ValueError, match="PROVIDER_EVENT_STATUS_REQUIRED"):
        reconcile(source=source)


def test_discovery_parse_failure_retains_raw_receipts(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "utcnow", lambda: NOW)
    def fake(root, spec, fetcher):
        relative, url, pin, kind = spec
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = b'not a parquet file' if kind == 'cfb_current' else b'{"events":[]}'
        path.write_bytes(raw)
        return {"name": relative.removeprefix("binary/"), "path": relative, "url": url,
                "kind": kind, "status": "CAPTURED", "sha256": hashlib.sha256(raw).hexdigest(),
                "requested_at_utc": NOW.isoformat(), "retrieved_at_utc": NOW.isoformat()}
    monkeypatch.setattr(D, "_capture", fake)
    root = tmp_path / "source"
    with pytest.raises(ValueError, match="NEXT_SLATE_DISCOVERY_FAILED"):
        D.capture_cfb(root, "2026-11-02", next_slate=True)
    assert (root / "binary/cfb_current.parquet").read_bytes() == b'not a parquet file'
    assert json.loads((root / "report.json").read_text())["discovery_error"]
    assert (root / "acquisition.json").exists() and (root / "manifest.json").exists()
