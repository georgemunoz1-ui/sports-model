import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

from harness import recovery_jobs as jobs, ingest_lancebroz as archive
from scripts import standing_health_triage as triage

NOW = dt.datetime(2026, 9, 16, tzinfo=dt.timezone.utc)

def card(root):
    p = root / "proof.txt"
    p.write_text("proof")
    return triage.seal(dict(issue_id="test", specific="Test archive absent", owner="maintainer",
        why_unresolved="Original bytes unavailable", next_action="Recover named object", due_at_utc="2026-09-17T00:00:00Z",
        closure_criteria=["Hash verifies"], dependency_assessment="Required", status="BLOCKED",
        external_dependency="Original archive object", residual_claim="No forecast clearance",
        last_material_change_at_utc="2026-08-01T00:00:00Z",
        evidence=[dict(path=p.name, sha256=hashlib.sha256(p.read_bytes()).hexdigest())]))

def test_closed_conditional_job_not_overdue():
    j = jobs.default_jobs()["RJ-003-FALLBACK-ARM"]
    j.update(status=jobs.CLOSED_CONDITION_NOT_FIRED, terminal_disposition="CONDITION_NOT_FIRED")
    r = jobs.status_report({j["job_id"]: j}, "2026-09-16T00:00:00Z")
    assert r["n_overdue"] == 0 and r["n_terminal"] == 1
    assert not r["open_blockers"] and not r["integrity_problems"]

def test_unknown_job_status_and_missing_terminal_disposition_fail():
    j = jobs.default_jobs()["RJ-003-FALLBACK-ARM"]
    for status in ("made-up", jobs.COMPLETE):
        j["status"] = status
        assert jobs.status_report({j["job_id"]: j}, "2026-09-16T00:00:00Z")["integrity_problems"]

def test_card_status_and_evidence_fail_closed(tmp_path):
    c = card(tmp_path)
    assert not triage.validate_card(c, tmp_path)
    bad = triage.seal(dict(c, status="OPEN"))
    assert "INVALID_DECISION" in triage.validate_card(bad, tmp_path)
    (tmp_path / "proof.txt").write_text("corrupt")
    assert any("EVIDENCE_HASH_MISMATCH" in e for e in triage.validate_card(c, tmp_path))

def test_risk_requires_authority_and_review_and_does_not_clear_release(tmp_path):
    c = card(tmp_path)
    c = triage.seal(dict(c, status="ACCEPTED-RISK"))
    assert "RISK_DECISION_INCOMPLETE" in triage.validate_card(c, tmp_path)
    c = triage.seal(dict(c, review_at_utc="2026-09-15T00:00:00Z", rationale="Defer with no release", decision_authority="owner"))
    r = triage.report({"issues": [c]}, [], NOW, tmp_path)
    assert r["issues"][0]["status"] == "OVERDUE-ESCALATED"
    assert not r["official_release_eligible"]

def test_third_blocked_session_escalates(tmp_path):
    c = card(tmp_path)
    prior = dict(issues=[dict(issue_id="test", decision="BLOCKED")], trend={"aged_over_14_days": 1})
    r = triage.report({"issues": [c]}, [prior, prior], NOW, tmp_path)
    assert r["issues"][0]["status"] == "OVERDUE-ESCALATED"
    assert r["trend"]["aged_over_14_days"] == 1

def test_first_trend_unknown_and_review_does_not_reset_age(tmp_path):
    c = card(tmp_path)
    c = triage.seal(dict(c, last_verified_at_utc=NOW.isoformat()))
    r = triage.report({"issues": [c]}, [], NOW, tmp_path)
    assert r["trend"]["previous_session_count"] is None
    assert r["trend"]["aged_over_14_days"] == 1

def test_chain_tamper_rejected(tmp_path):
    p = tmp_path / "sessions.jsonl"
    r = triage.seal(dict(session_id="a", previous_record_sha256=None))
    p.write_text(json.dumps(r) + "\n")
    assert len(triage.read_sessions(p)) == 1
    r["session_id"] = "changed"
    p.write_text(json.dumps(r) + "\n")
    import pytest
    with pytest.raises(ValueError, match="CHAIN_INVALID"):
        triage.read_sessions(p)

def test_claims_require_executed_and_closure_evidence(tmp_path):
    c = card(tmp_path)
    for state, error in (("FIX-IN-PROGRESS", "NO_EXECUTED_STEP"), ("RESOLVED", "NO_CLOSURE_EVIDENCE"), ("DESCOPED", "NO_DESCOPE_PROOF")):
        assert error in triage.validate_card(triage.seal(dict(c, status=state)), tmp_path)

def test_archive_checks_all_git_objects_not_just_one(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()
    git("init", "-q")
    daily = tmp_path / "data/raw/2026/daily"
    daily.mkdir(parents=True)
    a, b = daily / "2026-07-01.parquet", daily / "2026-07-02.parquet"
    a.write_bytes(b"synthetic contract bytes, not production parquet")
    b.write_bytes(b"second object")
    git("add", ".")
    git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "fixture")
    with patch.object(archive, "SRC", str(tmp_path)), patch.object(archive, "DAILY", str(daily)):
        with patch.dict("os.environ", {"SPORTSMODEL_LANCEBROZ_COMMIT": git("rev-parse", "HEAD")}):
            assert archive.source_health()["ok"]
            b.unlink()
            assert not archive.source_health()["ok"]
            b.write_bytes(b"changed")
            assert any("MODIFIED" in p for p in archive.source_health()["problems"])
            b.write_bytes(b"second object")
            (daily / "2026-07-03.parquet").write_bytes(b"untracked")
            assert any("UNTRACKED" in p for p in archive.source_health()["problems"])

def test_non_repo_subdirectory_cannot_borrow_parent_commit(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    p = tmp_path / "child"
    p.mkdir()
    with patch.object(archive, "SRC", str(p)), patch.object(archive, "DAILY", str(p / "data")):
        assert not archive.source_health()["ok"]

def test_evaluation_rejects_duplicate_cross_date_and_outcome_conflicts():
    from harness import evaluation_standard as es, promotion_gate as pg
    import pytest
    row = dict(game_id="SEA@LAA", slate_date="2026-08-25", p_model=.6, home_win=1, p=.6, y=1)
    calls = [lambda a,b: es.paired_postgame(a,b), lambda a,b: pg.compare_against_references(a, {"base":b}, reps=10)]
    for call in calls:
        with pytest.raises(ValueError, match="DUPLICATE"):
            call([row, row], [row])
        with pytest.raises(ValueError, match="DATE_CONFLICT"):
            call([row], [dict(row, slate_date="2026-08-26")])
        with pytest.raises(ValueError, match="OUTCOME_CONFLICT"):
            call([row], [dict(row, home_win=0, y=0)])
