"""Independent release-readback and partial-failure regressions.

The fixtures use ephemeral TEST_ONLY keys and never grant real model approval.
These cases were observed failing at 14ccf3ed before the repair.
"""
from copy import deepcopy
import hashlib
import json

import pytest

from harness import release_gate
from pipelines.cards.missingness import seal_audit
from test_missingness_release import approved_study, release_case, study


def _write_release(tmp_path, evidence):
    evidence_path = tmp_path / "release-evidence.json"
    evidence_path.write_text(json.dumps(evidence))
    report = release_gate.evaluate(evidence)
    assert report["global_status"] == "HEALTHY"  # Exercise a valid acceptance path.
    report["evidence_sha256"] = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    return evidence_path, report


def test_complete_release_manifest_round_trip(release_case, tmp_path):
    evidence, _ = release_case
    evidence_path, report = _write_release(tmp_path, evidence)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(report))
    expected, problems = release_gate.verify_artifact(evidence_path, path)
    assert expected["global_status"] == "HEALTHY"
    assert problems == []


@pytest.mark.parametrize("field,value", [
    ("action_authority", "YES"),
    ("decision_time_utc", "2099-01-01T00:00:00Z"),
    ("enabled_sports", []),
    ("enabled_markets", ["WAGER"]),
    ("as_of_date", "2099-01-01"),
    ("coverage_start", "2099-01-01"),
    ("source_evidence", {"substituted": True}),
])
def test_release_readback_rejects_changed_published_contract(release_case, tmp_path, field, value):
    evidence, _ = release_case
    evidence_path, report = _write_release(tmp_path, evidence)
    report[field] = value
    path = tmp_path / "altered-manifest.json"
    path.write_text(json.dumps(report))
    _, problems = release_gate.verify_artifact(evidence_path, path)
    assert problems, f"Published {field} change escaped readback"


@pytest.mark.parametrize("field", ["action_authority", "decision_time_utc", "enabled_sports"])
def test_release_readback_requires_published_contract_fields(release_case, tmp_path, field):
    evidence, _ = release_case
    evidence_path, report = _write_release(tmp_path, evidence)
    del report[field]
    path = tmp_path / "incomplete-manifest.json"
    path.write_text(json.dumps(report))
    _, problems = release_gate.verify_artifact(evidence_path, path)
    assert problems, f"Missing published {field} escaped readback"


@pytest.mark.parametrize("field,value", [
    ("events", [None]),
    ("events", [{"event_key": ["invalid"], "disposition": "EXPLICITLY_BLOCKED"}]),
    ("gates", {"freshness": "PASS"}),
])
def test_malformed_other_league_is_blocked_without_losing_valid_sibling(release_case, field, value):
    evidence, healthy_sport = release_case
    healthy_before = release_gate.evaluate(evidence)["sports"][healthy_sport]
    assert healthy_before["status"] == "HEALTHY"
    bad = deepcopy(evidence)
    bad["sports"]["nba"][field] = value
    report = release_gate.evaluate(bad)
    assert report["global_status"] == "BLOCKED"
    assert report["sports"]["nba"]["status"] == "BLOCKED"
    assert report["sports"][healthy_sport] == healthy_before


@pytest.mark.parametrize("details_patch", [
    {"status": "TRACE_BLOCKED"},
    {"status": "REFUSED"},
    {"status": "UNREGISTERED_OR_UNSUPPORTED"},
    {"feature_contracts": {"status": "INCOMPLETE_ENGINEERING_INVENTORY"}},
    {"comparison_status": "CHILD_SENSITIVITY_NOT_ESTABLISHED"},
    {"parent_receipt_verified": False},
    {"parent_receipt_verified": 0},
    {"parent_receipt_verified": None},
    {"status": "BLOCKED"},
    {"feature_contracts": {"status": "COMPLETE_ENGINEERING_INVENTORY",
                           "model_scope_matches": False, "head_scope_matches": False,
                           "unregistered_features": ["collector_worked"]}},
])
def test_signed_inventory_cannot_override_current_unsupported_trace(release_case, study, details_patch):
    evidence, sport = release_case
    fixture, store, *_ = study
    block = evidence["sports"][sport]
    event = block["events"][0]
    output = event["model_outputs"][0]
    old = output["missingness_audit"]
    output["missingness_audit"] = seal_audit(
        league=sport, event_id=event["event_key"], model_id=output["model_id"],
        products=output["products"], forecast=output["forecast"],
        details={**old["details"], **details_patch})
    inventory = store.read(block["inventory_id"])
    inventory["event_products"][event["event_key"]]["model_outputs"][0]["receipt_sha256"] = (
        output["missingness_audit"]["receipt_sha256"])
    block["inventory_id"] = store.put(inventory)
    block["inventory_witness_id"] = fixture["sign"](
        block["inventory_id"], "missingness_release_inventory", "TEST_ONLY_witness", evidence["decision_time_utc"])
    report = release_gate.evaluate(evidence)
    assert report["sports"][sport]["status"] == "BLOCKED"
    assert "MISSINGNESS_EVENT_RECEIPT_OR_SCOPE_INVALID" in report["sports"][sport]["reason_codes"]
    assert report["sports"]["mls"]["status"] == "HEALTHY"

