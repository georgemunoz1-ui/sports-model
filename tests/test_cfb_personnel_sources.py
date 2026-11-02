"""TEST_ONLY synthetic provider-shape fixtures, never predictive observations."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

from research.efficiency import cfb_personnel_sources as s


@pytest.fixture
def packet(monkeypatch):
    monkeypatch.setattr(s, "now", lambda: datetime(2026, 11, 2, 6, tzinfo=timezone.utc))
    document = {"synthetic-report": {
        "ReportType": "Initial", "conferenceTimeZone": "CT",
        "publishDate": "2026-11-01", "postedTime": "19:00:00",
        "footer": {"date": "2026-11-07", "time": "11:00:00"},
        "games": [{"teamName": "TEST_ONLY_A", "teamDisplayName": "TEST_ONLY_A", "rows": [
            {"name": "QB #1 Synthetic Athlete", "status": "Questionable", "exemptStatus": "NonExempt"}]},
                  {"teamName": "TEST_ONLY_B", "rows": [
            {"name": "QB #2 Synthetic Other", "status": "Available", "exemptStatus": "NonExempt"}]}]}}
    return document


def inspect(document, *, retrieved=None):
    raw = json.dumps(document).encode()
    receipt = s.imported_receipt(raw, "SEC", "current")
    if retrieved:
        receipt["retrieved_at_utc"] = retrieved
    return s.inspect_retained(raw, receipt)


def test_public_report_is_not_a_personnel_model_observation(packet):
    result = inspect(packet)
    assert result["report_count"] == 1 and result["quarterback_row_count"] == 2
    report = result["reports"][0]
    assert report["reported_publication_at_utc"] == "2026-11-02T01:00:00+00:00"
    assert report["reported_start_time_utc"] == "2026-11-07T17:00:00+00:00"
    assert report["provider_observed_at_utc"] is None
    assert report["event_id"] is None
    assert report["quarterback_rows"][0]["expected_participation_probability"] is None
    assert report["quarterback_rows"][1]["expected_qb_designation"] is None
    assert result["personnel_v2_evidence"] is None
    assert result["admissible_personnel_v2_observations"] == 0
    assert not result["canonical_prospective_eligible"]
    assert result["model_usage"] == "NOT_USED"
    assert result["action_authority"] is False


def test_import_clock_cannot_be_used_as_original_retrieval(packet):
    result = inspect(packet)
    assert result["retrieved_at_utc"] is None
    assert result["historical_original_pit_proven"] is False
    assert result["provider_observed_at_utc"] is None


def test_real_retrieval_does_not_become_provider_observation(packet):
    result = inspect(packet, retrieved="2026-11-02T05:00:00Z")
    assert result["provider_observed_at_utc"] is None
    assert result["admissible_personnel_v2_observations"] == 0


@pytest.mark.parametrize("status", ["Available", "Probable", "Questionable", "Doubtful", "Out", "Game Time Decision"])
def test_no_status_probability_mapping_or_starter_inference(packet, status):
    packet["synthetic-report"]["games"][0]["rows"][0]["status"] = status
    row = inspect(packet)["reports"][0]["quarterback_rows"][0]
    assert row["reported_status"] == status
    assert row["expected_participation_probability"] is None
    assert row["expected_qb_designation"] is None


def test_missing_qb_rows_are_unknown_not_all_available(packet):
    packet["synthetic-report"]["games"][0]["rows"] = []
    result = inspect(packet)
    assert result["quarterback_row_count"] == 1
    assert "EXPECTED_QB_DESIGNATION_UNAVAILABLE" in result["blockers"]


@pytest.mark.parametrize("key,value", [("postedTime", None), ("conferenceTimeZone", "CST"),
                                      ("publishDate", "2026-11-50")])
def test_missing_or_invalid_publication_time_is_quarantined(packet, key, value):
    packet["synthetic-report"][key] = value
    result = inspect(packet)
    assert result["report_count"] == 0
    assert len(result["quarantined"]) == 1


@pytest.mark.parametrize("day,clock", [("2026-11-01", "01:30:00"), ("2026-03-08", "02:30:00")])
def test_daylight_time_ambiguity_and_missing_time_refuse(day, clock):
    with pytest.raises(ValueError, match="AMBIGUOUS_OR_NONEXISTENT"):
        s.local_time(day, clock, "CT")


def test_duplicate_team_or_player_report_quarantined(packet):
    packet["synthetic-report"]["games"][0]["rows"] *= 2
    result = inspect(packet)
    assert result["quarantined"][0]["reason"] == "CFB_SOURCE_DUPLICATE_QB_ROW"
    assert result["report_count"] == 0


def test_old_report_cannot_be_future_evidence(packet):
    packet["synthetic-report"].update({"publishDate": "2026-10-31", "postedTime": "10:00:00"})
    packet["synthetic-report"]["footer"]["date"] = "2026-10-31"
    result = inspect(packet)
    assert result["future_report_count"] == 0
    assert "NO_FUTURE_PREGAME_REPORT_IN_CAPTURE" in result["blockers"]


def test_future_claims_and_report_retrieval_order_refuse(packet):
    with pytest.raises(ValueError, match="CAPTURE_CLOCK_INVALID"):
        inspect(packet, retrieved="2026-11-03T05:00:00Z")
    result = inspect(packet, retrieved="2026-11-01T05:00:00Z")
    assert result["quarantined"][0]["reason"] == "CFB_SOURCE_REPORT_PUBLISHED_AFTER_RETRIEVAL"


def test_import_cannot_admit_a_future_publication_time(packet):
    packet["synthetic-report"]["publishDate"] = "2026-11-03"
    result = inspect(packet)
    assert result["quarantined"][0]["reason"] == "CFB_SOURCE_FUTURE_PUBLICATION_CLAIM"


def test_hash_and_source_identity_checked(packet):
    raw = json.dumps(packet).encode()
    receipt = s.imported_receipt(raw, "SEC", "current")
    with pytest.raises(ValueError, match="BYTES_CHANGED"):
        s.inspect_retained(raw + b" ", receipt)
    receipt["request_parameters"]["conference"] = "ACC"
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        s.inspect_retained(raw, receipt)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}'])
def test_ambiguous_or_nonfinite_json_refused(raw):
    with pytest.raises(ValueError, match="CFB_SOURCE_"):
        s.decode(raw)


def test_archive_stage_labels_are_not_timestamps():
    raw = json.dumps({"loaded": True, "report_days": ["Initial", "Game Day"], "data": [
        {"Team": "TEST_ONLY_A", "Player": "Synthetic Athlete", "Week": "Sat, 31 Oct 2026 00:00:00 GMT",
         "Initial": "Questionable", "Game Day": "Out"}]}).encode()
    result = s.inspect_retained(raw, s.imported_receipt(raw, "SEC", "archive"))
    assert result["archive_rows"] == 1
    assert result["provider_observed_at_utc"] is None
    assert result["historical_original_pit_proven"] is False
    assert result["admissible_personnel_v2_observations"] == 0


def test_unprovisioned_permission_blocks_before_any_network_or_output(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network must not run")
    monkeypatch.setattr(s, "build_opener", forbidden)
    output = tmp_path / "new"
    with pytest.raises(ValueError, match="SOURCE_USE_NOT_CLEARED"):
        s.capture("SEC", "current", output)
    assert not output.exists()


def test_permission_grant_requires_retained_rights_document(tmp_path, monkeypatch):
    registry = tmp_path / "permissions.json"
    registry.write_text(json.dumps({"schema": "cfb.personnel-source-permissions.v1", "grants": {
        "SEC": {"automated_capture": True, "source_origin": "https://app.hdintelligence.com",
                "valid_from_utc": "2000-01-01T00:00:00Z", "valid_until_utc": "2100-01-01T00:00:00Z",
                "rights_document": {"path": str(tmp_path / "absent"), "sha256": "0" * 64},
                "review_record": "TEST_ONLY"}}}))
    monkeypatch.setattr(s, "PERMISSIONS", registry)
    with pytest.raises(ValueError, match="RIGHTS_DOCUMENT_UNAVAILABLE_OR_CHANGED"):
        s.require_permission("SEC", "automated_capture")


def test_original_freshness_validator_is_still_authoritative(packet):
    # A normalized inspection cannot masquerade as a complete v2 snapshot.
    report = inspect(packet)
    with pytest.raises(ValueError, match="CFB_REFRESH_SNAPSHOT_SCHEMA"):
        s.validate_refresh_inputs({}, report)


def test_cli_retains_bytes_and_refuses_overwrite(tmp_path, packet):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(packet))
    root = Path(__file__).resolve().parents[1]
    out = tmp_path / "inspection"
    args = [sys.executable, str(root / "scripts/capture_cfb_personnel_sources.py"),
            "--conference", "SEC", "--raw", str(source), "--output", str(out)]
    first = subprocess.run(args, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    assert before["raw.json"] == source.read_bytes()
    second = subprocess.run(args, capture_output=True, text=True)
    assert second.returncode != 0
    assert before == {p.name: p.read_bytes() for p in out.iterdir()}


def test_cli_capture_permission_refusal_is_explicit(tmp_path):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / "scripts/capture_cfb_personnel_sources.py"),
        "--conference", "SEC", "--output", str(tmp_path / "never")], capture_output=True, text=True)
    assert result.returncode == 2
    assert json.loads(result.stdout)["network_requests"] == 0
    assert not (tmp_path / "never").exists()
