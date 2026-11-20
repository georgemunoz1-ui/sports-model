"""Synthetic acquisition contract tests; no provider or predictive qualification."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

from scripts import capture_operational_inputs as collector
from scripts import validate_operational_capture as validator
from scripts.operational_capture_contract import SCHEMA, TIMEZONE, nfl_source_urls, schedule_specs
from scripts.recovery_capture import ROUTES

DAY = dt.date(2026, 11, 4)
NOW = dt.datetime(2026, 11, 4, 16, tzinfo=dt.timezone.utc)
CAPTURE_ID = "a" * 32


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def manifest(root):
    dump(root / "manifest.json", {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in root.rglob("*") if p.is_file() and p.name != "manifest.json"})


def payload_for(spec):
    league, kind, url, _ = spec
    query = parse_qs(urlparse(url).query)
    if kind == "event_summary":
        return {"header": {"id": query["event"][0], "competitions": event(query["event"][0])["competitions"]}}
    if kind == "official_schedule":
        return {"totalGames": 1 if query["date"] == [str(DAY)] else 0,
                "dates": [{"date": str(DAY), "games": [{"gamePk": 1234, "gameDate": "2026-11-04T20:00:00Z",
                    "teams": {"home": {"team": {"id": 111}}, "away": {"team": {"id": 222}}},
                    "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"}}]}] if query["date"] == [str(DAY)] else []}
    events = []
    if query["dates"] == [DAY.strftime("%Y%m%d")]:
        events.append(event(str(100 + list(ROUTES).index(league))))
    return {"events": events}


def event(eid="999", date="2026-11-04T20:00:00Z"):
    return {"id": eid, "date": date, "name": "Synthetic away at synthetic home",
            "competitions": [{"id": eid, "date": date,
                              "competitors": [{"homeAway": "home", "team": {"id": "1"}},
                                              {"homeAway": "away", "team": {"id": "2"}}],
                              "status": {"type": {"name": "STATUS_SCHEDULED", "state": "pre", "completed": False}}}]}


def fake_capture(root, spec):
    league, kind, url, tier = spec
    payload = payload_for(spec)
    raw = json.dumps(payload, sort_keys=True).encode()
    sha = hashlib.sha256(raw).hexdigest()
    path = root / "raw" / (sha + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"league": league, "kind": kind, "url": url, "evidence_tier": tier,
            "requested_at_utc": NOW.isoformat(), "retrieved_at_utc": NOW.isoformat(),
            "provider_observed_at_utc": None, "historical_pregame_eligibility": False,
            "http_status": 200, "headers": {}, "final_url": url, "raw_sha256": sha,
            "raw_path": "raw/" + sha + ".json", "status": "CAPTURED", "parse_status": "JSON_PARSED"}, payload


class FakeResponse:
    status = 200
    headers = {}

    def __init__(self, url):
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        if "play_by_play" in self.url:
            return b"game_id,season,week,play_id\n2026_01_A_B,2026,1,1\n"
        return b"game_id,season,week\n2026_01_A_B,2026,1\n"


class FrozenDateTime(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


@pytest.fixture
def capture_tree(tmp_path, monkeypatch):
    root = tmp_path / "capture"
    monkeypatch.setattr(collector, "capture", fake_capture)
    monkeypatch.setattr(collector.urllib.request, "urlopen", lambda url, **kwargs: FakeResponse(url))
    monkeypatch.setattr(collector.dt, "datetime", FrozenDateTime)
    monkeypatch.setattr(collector.uuid, "uuid4", lambda: type("ID", (), {"hex": CAPTURE_ID})())
    monkeypatch.setattr(sys, "argv", ["capture", "--output", str(root)])
    assert collector.main() == 0
    return root


def report(root):
    return json.loads((root / "report.json").read_text())


def save_report(root, value, *, mirror=True):
    dump(root / "report.json", value)
    if mirror:
        dump(root / "nfl/receipt.json", value["nfl_sources"])
    manifest(root)


def verify(root):
    return validator.verify_capture(root, str(DAY), now=NOW)


def replace_source(root, row, payload):
    raw = json.dumps(payload, sort_keys=True).encode()
    sha = hashlib.sha256(raw).hexdigest()
    row.update(raw_sha256=sha, raw_path="raw/" + sha + ".json")
    (root / row["raw_path"]).write_bytes(raw)


def test_real_collector_shape_and_full_inventory_passes(capture_tree):
    result = verify(capture_tree)
    assert result["ok"] is True
    assert result["source_count"] == len(schedule_specs(DAY)) + 3
    assert result["event_counts"] == {league: 1 for league in ROUTES}
    assert result["nfl_source_count"] == 2
    assert result["source_capture_only"] is True
    assert result["provider_authenticity_verified"] is False
    assert result["action_authority"] is False


def test_complete_zero_event_schedules_are_valid_capture_evidence(capture_tree, monkeypatch):
    # Zero games are legitimate only when the complete expected inventory has
    # actual parseable empty schedules; an empty events document is insufficient.
    root = capture_tree.parent / "zero-events"
    monkeypatch.setattr(sys.modules[__name__], "payload_for", lambda spec:
                        {"totalGames": 0, "dates": []} if spec[1] == "official_schedule" else {"events": []})
    monkeypatch.setattr(sys, "argv", ["capture", "--output", str(root)])
    assert collector.main() == 0
    result = verify(root)
    assert result["ok"] is True
    assert result["source_count"] == len(schedule_specs(DAY))
    assert result["event_counts"] == {league: 0 for league in ROUTES}
    assert result["action_authority"] is False
    assert result["provider_authenticity_verified"] is False


@pytest.mark.parametrize("name", ["report.json", "events.json", "manifest.json"])
def test_empty_objects_are_rejected(capture_tree, name):
    dump(capture_tree / name, {})
    if name != "manifest.json":
        manifest(capture_tree)
    with pytest.raises(ValueError):
        verify(capture_tree)


@pytest.mark.parametrize("key", sorted(validator.REPORT_KEYS))
def test_missing_report_fields_are_rejected(capture_tree, key):
    value = report(capture_tree)
    del value[key]
    dump(capture_tree / "report.json", value)
    manifest(capture_tree)
    with pytest.raises(ValueError, match="REPORT_SCHEMA_INVALID"):
        verify(capture_tree)


@pytest.mark.parametrize("mutation,reason", [
    (lambda r: r.update(schema="legacy"), "CONTRACT_VERSION"),
    (lambda r: r.update(date="2026-11-03"), "DATE_MISMATCH"),
    (lambda r: r.update(action_authority=True), "AUTHORITY_INVALID"),
    (lambda r: r.update(capture_id=""), "CAPTURE_ID_INVALID"),
    (lambda r: r.update(capture_started_at_utc="2026-11-04T16:00:00"), "UTC_TIMESTAMP_REQUIRED"),
    (lambda r: r.update(created_at_utc="2026-11-04T16:00:01Z"), "CLOCK_OR_DATE"),
    (lambda r: r["sources"].pop(0), "MANDATORY_SCHEDULE_SOURCE_MISSING"),
    (lambda r: r["sources"].clear(), "MANDATORY_SCHEDULE_SOURCE_MISSING"),
    (lambda r: r["sources"].append(copy.deepcopy(r["sources"][0])), "DUPLICATE_SOURCE"),
    (lambda r: r["sources"][0].update(capture_id="b" * 32), "CROSS_CAPTURE"),
    (lambda r: r["sources"][0].update(requested_at_utc="2026-11-04T15:59:59Z"), "CHRONOLOGY"),
    (lambda r: r["sources"][0].update(retrieved_at_utc="2026-11-04T16:00:01Z"), "CHRONOLOGY"),
    (lambda r: r["sources"][0].update(status="FAILED"), "NOT_CAPTURED"),
    (lambda r: r["sources"][0].update(final_url="https://example.com"), "HTTP_IDENTITY"),
    (lambda r: r["sources"][0].update(raw_sha256="0" * 64), "PATH_HASH_BINDING"),
    (lambda r: r["sources"][0].update(raw_path="../outside.json"), "PATH_HASH_BINDING"),
    (lambda r: r["sources"][0].update(raw_path="/tmp/outside.json"), "PATH_HASH_BINDING"),
    (lambda r: r["event_counts"].update(cfb=2), "EVENT_COUNTS"),
    (lambda r: r["event_counts"].update(cfb=True), "EVENT_COUNTS"),
    (lambda r: r["nfl_sources"].pop(0), "MANDATORY_NFL"),
    (lambda r: r["nfl_sources"].append(copy.deepcopy(r["nfl_sources"][0])), "NFL_SOURCE_INVENTORY"),
    (lambda r: r["nfl_sources"][0].update(capture_id="b" * 32), "CROSS_CAPTURE"),
    (lambda r: r["nfl_sources"][0].update(source_url="https://example.com/games.csv"), "NFL_SOURCE_INVENTORY"),
    (lambda r: r["nfl_sources"][0].update(sha256="0" * 64), "NFL_MANIFEST"),
])
def test_mutually_rehashed_bad_receipts_fail(capture_tree, mutation, reason):
    value = report(capture_tree)
    mutation(value)
    save_report(capture_tree, value)
    with pytest.raises(ValueError, match=reason):
        verify(capture_tree)


@pytest.mark.parametrize("mode", ["missing", "modified"])
def test_actual_bytes_are_required(capture_tree, mode):
    path = capture_tree / report(capture_tree)["sources"][0]["raw_path"]
    if mode == "missing":
        path.unlink()
    else:
        path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="MEMBER_MISSING|HASH_MISMATCH"):
        verify(capture_tree)


@pytest.mark.parametrize("name", ["../outside.json", "/tmp/outside.json", "raw/../outside.json", "raw\\outside.json", "./report.json"])
def test_manifest_paths_refused(capture_tree, name):
    value = json.loads((capture_tree / "manifest.json").read_text())
    value[name] = "a" * 64
    dump(capture_tree / "manifest.json", value)
    with pytest.raises(ValueError, match="INVALID_MEMBER_PATH"):
        verify(capture_tree)


def test_unmanifested_files_refused(capture_tree):
    (capture_tree / "unretained.txt").write_text("unretained")
    with pytest.raises(ValueError, match="FILE_SET"):
        verify(capture_tree)


def test_unreferenced_but_manifested_files_refused(capture_tree):
    (capture_tree / "unreferenced.txt").write_text("unreferenced")
    manifest(capture_tree)
    with pytest.raises(ValueError, match="UNREFERENCED"):
        verify(capture_tree)


def test_symbolic_raw_file_refused(capture_tree):
    path = capture_tree / report(capture_tree)["sources"][0]["raw_path"]
    external = capture_tree.parent / "external.json"
    external.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(external)
    with pytest.raises(ValueError, match="SYMLINK"):
        verify(capture_tree)


def test_nfl_receipt_mirror_must_match(capture_tree):
    dump(capture_tree / "nfl/receipt.json", [])
    manifest(capture_tree)
    with pytest.raises(ValueError, match="MIRROR"):
        verify(capture_tree)


@pytest.mark.parametrize("raw", [b"", b"garbage\n1\n", b"game_id,season,week\n", b"game_id,season,week\nx,2026\n", b"game_id,season,week\nx,2026,1,extra\n", b'game_id,season,week\n"unclosed,2026,1\n'])
def test_rehashed_malformed_nfl_csv_refused(capture_tree, raw):
    value = report(capture_tree)
    (capture_tree / "nfl/games.csv").write_bytes(raw)
    value["nfl_sources"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
    save_report(capture_tree, value)
    with pytest.raises((ValueError, validator.csv.Error)):
        verify(capture_tree)


@pytest.mark.parametrize("mode,reason", [("missing", "EVENT_COVERAGE"), ("wrong_hash", "EVENT_COVERAGE"), ("wrong_clock", "EVENT_COVERAGE")])
def test_rehashed_event_bindings_refused(capture_tree, mode, reason):
    value = json.loads((capture_tree / "events.json").read_text())
    row = value["cfb"]["102"]
    if mode == "missing":
        value["cfb"].clear()
    elif mode == "wrong_hash":
        row["source_sha256"] = "0" * 64
    else:
        row["retrieved_at_utc"] = "2026-11-04T15:59:59Z"
    dump(capture_tree / "events.json", value)
    manifest(capture_tree)
    with pytest.raises(ValueError, match=reason):
        verify(capture_tree)


@pytest.mark.parametrize("payload,reason", [({}, "SCHEDULE_EVENTS"), ({"events": [None]}, "EVENT_OBJECT"),
    ({"events": [event(date="2030-01-01T00:00:00Z")]}, "QUERY_DATE"),
    ({"events": [event(date="2026-10-28T20:00:00Z")] * 2}, "DUPLICATE_SCHEDULE"),
    ({"events": [{"id": "999", "date": "2026-10-28T20:00:00Z"}]}, "COMPETITION_REQUIRED")])
def test_rehashed_bad_schedule_payload_refused(capture_tree, payload, reason):
    value = report(capture_tree)
    replace_source(capture_tree, value["sources"][0], payload)
    save_report(capture_tree, value)
    with pytest.raises(ValueError, match=reason):
        verify(capture_tree)


def test_wrong_summary_event_refused(capture_tree):
    value = report(capture_tree)
    row = next(r for r in value["sources"] if r["kind"] == "event_summary")
    replace_source(capture_tree, row, {"header": {"id": "99999"}})
    save_report(capture_tree, value)
    with pytest.raises(ValueError, match="SUMMARY_EVENT"):
        verify(capture_tree)


@pytest.mark.parametrize("mode,reason", [("empty", "SUMMARY_COMPETITION"), ("start", "SUMMARY_START"),
    ("team", "SUMMARY_TEAM_IDENTITY"), ("orientation", "SUMMARY_TEAM_IDENTITY")])
def test_summary_identity_bound_to_schedule(capture_tree, mode, reason):
    value = report(capture_tree)
    row = next(r for r in value["sources"] if r["kind"] == "event_summary")
    payload = payload_for((row["league"], row["kind"], row["url"], row["evidence_tier"]))
    comp = payload["header"]["competitions"][0]
    if mode == "empty":
        payload["header"]["competitions"] = []
    elif mode == "start":
        comp["date"] = "2026-11-04T21:00:00Z"
    elif mode == "team":
        comp["competitors"][0]["team"]["id"] = "3"
    else:
        for side in comp["competitors"]:
            side["homeAway"] = "away" if side["homeAway"] == "home" else "home"
    replace_source(capture_tree, row, payload)
    save_report(capture_tree, value)
    with pytest.raises(ValueError, match=reason):
        verify(capture_tree)


@pytest.mark.parametrize("field", ["gameDate", "teams", "status"])
def test_official_mlb_schedule_shape_required(capture_tree, field):
    value = report(capture_tree)
    row = next(r for r in value["sources"] if r["kind"] == "official_schedule" and "date=2026-11-04" in r["url"])
    payload = payload_for((row["league"], row["kind"], row["url"], row["evidence_tier"]))
    del payload["dates"][0]["games"][0][field]
    replace_source(capture_tree, row, payload)
    save_report(capture_tree, value)
    with pytest.raises(ValueError):
        verify(capture_tree)


def test_conflicting_adjacent_schedule_event_refused(capture_tree):
    value = report(capture_tree)
    row = next(r for r in value["sources"] if r["league"] == "cfb" and "dates=20261105" in r["url"])
    changed = event("102")
    changed["competitions"][0]["competitors"][0]["team"]["id"] = "3"
    replace_source(capture_tree, row, {"events": [changed]})
    save_report(capture_tree, value)
    with pytest.raises(ValueError, match="CONFLICTING_SCHEDULE_EVENT"):
        verify(capture_tree)


def test_unknown_source_cannot_expand_the_contract(capture_tree):
    value = report(capture_tree)
    extra = copy.deepcopy(value["sources"][0])
    extra["url"] = extra["final_url"] = "https://example.com/unapproved"
    value["sources"].append(extra)
    save_report(capture_tree, value)
    with pytest.raises(ValueError, match="SOURCE_INVENTORY_MISMATCH"):
        verify(capture_tree)


@pytest.mark.parametrize("mutation,reason", [
    (lambda e: e["competitions"][0].update(id="different"), "COMPETITION_ID"),
    (lambda e: e["competitions"][0]["competitors"][0].update(homeAway="away"), "TEAM_ORIENTATION"),
    (lambda e: e["competitions"][0]["competitors"][0]["team"].update(id="2"), "TEAM_ID_CONFLICT"),
    (lambda e: e["competitions"][0]["status"]["type"].update(completed="false"), "STATUS_INVALID"),
    (lambda e: e["competitions"][0].update(date="2026-11-05T20:00:00Z"), "START_CONFLICT"),
])
def test_source_event_identity_fields_required(capture_tree, mutation, reason):
    value = report(capture_tree)
    row = next(r for r in value["sources"] if r["league"] == "cfb" and "dates=20261104" in r["url"])
    changed = event("102")
    mutation(changed)
    replace_source(capture_tree, row, {"events": [changed]})
    save_report(capture_tree, value)
    with pytest.raises(ValueError, match=reason):
        verify(capture_tree)


def test_collector_retains_failure_receipts_and_returns_nonzero(capture_tree, monkeypatch):
    output = capture_tree.parent / "failed-capture"
    def fail_one(root, spec):
        row, payload = fake_capture(root, spec)
        if spec == schedule_specs(DAY)[0]:
            row.update(status="FAILED", error="synthetic failure")
            return row, None
        return row, payload
    monkeypatch.setattr(collector, "capture", fail_one)
    monkeypatch.setattr(sys, "argv", ["capture", "--output", str(output)])
    assert collector.main() == 2
    assert report(output)["sources"][0]["error"] == "synthetic failure"
    assert (output / "manifest.json").is_file()
    with pytest.raises(ValueError):
        verify(output)


def test_duplicate_json_keys_refused(capture_tree):
    (capture_tree / "manifest.json").write_text('{"x":"a","x":"b"}')
    with pytest.raises(ValueError, match="DUPLICATE_JSON_KEY"):
        verify(capture_tree)


def test_cli_reports_missing_capture_as_failure(tmp_path):
    result = subprocess.run([sys.executable, "scripts/validate_operational_capture.py", "--root", str(tmp_path / "missing")], capture_output=True, text=True)
    assert result.returncode == 1
    assert json.loads(result.stdout)["ok"] is False


def test_workflow_enforces_capture_validation_and_upload():
    text = Path(".github/workflows/daily-operations-preflight.yml").read_text()
    assert 'python scripts/validate_operational_capture.py --root "$RUNNER_TEMP/sports-inputs"' in text
    assert 'printf \'%s\\n\' "- Commit: $GITHUB_SHA"' in text
    assert 'if-no-files-found: error' in text
    assert '${{ steps.evidence.outcome }}' in text


def test_hosted_premerge_route_is_narrow_read_only_and_separate_from_daily_runs():
    workflow = yaml.load(Path(".github/workflows/daily-operations-preflight.yml").read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch", "pull_request", "schedule"}
    assert set(workflow["on"]["pull_request"]["paths"]) == {
        ".github/workflows/daily-operations-preflight.yml", "scripts/capture_operational_inputs.py",
        "scripts/validate_operational_capture.py", "scripts/operational_capture_contract.py",
        "scripts/recovery_capture.py", "tests/test_operational_capture_validation.py",
        "tests/test_recovery_governance.py",
    }
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "daily-sports-operations-preflight-${{ github.event.pull_request.number || 'scheduled-manual' }}",
        "cancel-in-progress": "false",
    }


@pytest.mark.parametrize("capture,checks,evidence,code", [("success", "success", "success", 0),
    ("failure", "success", "success", 1), ("success", "failure", "success", 1),
    ("success", "success", "failure", 1), ("success", "success", "skipped", 1)])
def test_actual_final_shell_step_rejects_missing_operational_stage(capture, checks, evidence, code):
    text = Path(".github/workflows/daily-operations-preflight.yml").read_text()
    script = textwrap.dedent(text.split("- name: Fail closed on incomplete acquisition or unhealthy repository", 1)[1].split("run: |", 1)[1])
    for key, outcome in {"capture": capture, "checks": checks, "evidence": evidence}.items():
        script = script.replace("${{ steps." + key + ".outcome }}", outcome)
    result = subprocess.run(["bash", "-e", "-c", script], capture_output=True, text=True)
    assert result.returncode == code


def test_actual_report_shell_preserves_commit_identity(tmp_path):
    text = Path(".github/workflows/daily-operations-preflight.yml").read_text()
    script = textwrap.dedent(text.split("- name: Publish operational report", 1)[1].split("run: |", 1)[1].split("\n      - name:", 1)[0])
    output = tmp_path / "summary.md"
    env = {**os.environ, "GITHUB_SHA": "5acf5972bc448b4e5c03b65ee69ecd38033765c0", "GITHUB_STEP_SUMMARY": str(output),
           "RUNNER_TEMP": str(tmp_path), "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "synthetic/fixture", "GITHUB_RUN_ID": "1"}
    result = subprocess.run(["bash", "-e", "-c", script], env=env, capture_output=True, text=True)
    assert result.returncode == 0
    assert "- Commit: " + env["GITHUB_SHA"] in output.read_text()
    assert "command not found" not in result.stderr
