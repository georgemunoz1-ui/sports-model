import copy
import hashlib
import json

import pytest

from research.finding_evidence import validate_packet


def fixture(tmp_path):
    (tmp_path / "source.py").write_text("# frozen source\n")
    (tmp_path / "run.txt").write_text("1 passed\n")
    def ref(path):
        return {"path": path, "sha256": hashlib.sha256((tmp_path / path).read_bytes()).hexdigest()}
    receipt = {"schema": "acceptance-execution-v1", "command": "pytest test_example.py",
               "exit_code": 0, "executed_at_utc": "2026-10-23T06:00:00Z",
               "sources": [ref("source.py")], "log": ref("run.txt")}
    (tmp_path / "receipt.json").write_text(json.dumps(receipt))
    packet = {"schema": "finding-evidence-v1", "finding_id": "TEST-01",
              "observed": "bad behavior", "expected": "correct behavior", "scope": "test procedure",
              "classification": "implementation_bug", "change": "bound correction",
              "evidence": [ref("source.py")], "remaining_limitation": "No predictive claim",
              "publication_impact": "OFF", "owner": "test owner",
              "status": "verified_implementation", "delivery": {"stage": "Tested"},
              "acceptance_test": {"command": receipt["command"], "execution_receipt": ref("receipt.json")}}
    return packet


def test_closed_packet_binds_executed_source_and_log(tmp_path):
    packet = fixture(tmp_path)
    assert validate_packet(packet, root=tmp_path)["delivery_stage"] == "Tested"
    (tmp_path / "source.py").write_text("# changed after test\n")
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        validate_packet(packet, root=tmp_path)


def test_missing_limitation_or_execution_cannot_close(tmp_path):
    packet = fixture(tmp_path)
    del packet["remaining_limitation"]
    with pytest.raises(ValueError, match="TEN"):
        validate_packet(packet, root=tmp_path)
    packet = fixture(tmp_path)
    packet["acceptance_test"].pop("execution_receipt")
    with pytest.raises(ValueError, match="REFERENCE"):
        validate_packet(packet, root=tmp_path)


def test_located_code_does_not_grant_evaluation_or_delivery(tmp_path):
    packet = fixture(tmp_path)
    packet.update(status="located_pending_eval", next_action="Run declared chronological evaluation")
    packet["acceptance_test"].pop("execution_receipt")
    result = validate_packet(packet, root=tmp_path)
    assert not result["predictive_validation_granted"]
    assert not result["publication_allowed"]
    packet["delivery"]["stage"] = "Verified"
    with pytest.raises(ValueError, match="MERGE_EVIDENCE"):
        validate_packet(packet, root=tmp_path)


def test_path_escape_and_fake_exercised_rejected(tmp_path):
    packet = fixture(tmp_path)
    altered = copy.deepcopy(packet)
    altered["evidence"][0]["path"] = "../source.py"
    with pytest.raises(ValueError, match="PATH_ESCAPE"):
        validate_packet(altered, root=tmp_path)
    packet["delivery"] = {"stage": "Exercised", "merge_commit": "test", "configuration_ref": "test"}
    with pytest.raises(ValueError, match="MERGE_EVIDENCE"):
        validate_packet(packet, root=tmp_path)


def test_verified_delivery_binds_merge_configuration_run_and_receipt(tmp_path):
    packet = fixture(tmp_path)
    def put(name, value):
        (tmp_path / name).write_text(json.dumps(value))
        return {"path": name, "sha256": hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()}
    commit = "a" * 40
    run_url = "https://github.com/test/repo/actions/runs/123"
    config = put("configuration.json", {"enabled": True})
    merge = put("merge.json", {"merged": True, "sha": commit})
    run = put("run.json", {"html_url": run_url, "head_sha": commit, "status": "completed", "conclusion": "success"})
    verification = put("verification.json", {"schema": "delivery-verification-v1", "merge_commit": commit,
        "run_receipt": run, "configuration_ref": config, "verified": True, "verified_at_utc": "2026-10-23T06:00:00Z"})
    packet["delivery"] = {"stage": "Verified", "merge_commit": commit, "merge_receipt": merge,
        "configuration_ref": config, "run_url": run_url, "run_receipt": run, "verification_receipt": verification}
    assert validate_packet(packet, root=tmp_path)["delivery_stage"] == "Verified"
    packet["delivery"]["merge_commit"] = "b" * 40
    with pytest.raises(ValueError, match="MERGE_RECEIPT_BINDING"):
        validate_packet(packet, root=tmp_path)
