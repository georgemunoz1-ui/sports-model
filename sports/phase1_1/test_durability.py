from pathlib import Path
import tempfile

from durability import build_late_import_event, build_remote_registration_event, append_hash_chained_record


def expect_fail(fn, code):
    try:
        fn()
        raise AssertionError(f"expected {code}")
    except ValueError as e:
        assert code in str(e), (code, str(e))


def main():
    manifest = "a" * 64
    forecast = {
        "event_id": "g1", "forecast_output_hash": "b" * 64,
        "forecast_status": "SHADOW_ONLY", "action_authority": "OFF",
        "model_code_commit": "c" * 40, "model_source_sha256": "d" * 64,
        "dependency_lock_sha256": "e" * 64, "forecast_cutoff_utc": "2026-09-06T10:00:00Z",
        "scheduled_start_utc": "2026-09-06T17:00:00Z", "artifact_manifest_sha256": manifest,
    }
    receipt = {
        "remote_repository": "owner/repo", "remote_branch": "main", "remote_commit_sha": "f" * 40,
        "remote_commit_received_at_utc": "2026-09-06T10:05:00Z",
        "remote_protection_status": "PROTECTED_BRANCH", "artifact_manifest_sha256": manifest,
    }
    row = build_remote_registration_event(forecast=forecast, receipt=receipt, previous_record_hash=None)
    assert row["registration_scope"] == "REMOTE_DURABLE" and row["prospective_eligible"] is True

    late = build_late_import_event(event_id="late", artifact_manifest_sha256=manifest,
                                   imported_at_utc="2026-09-06T18:00:00Z",
                                   original_local_registration_timestamp_claimed="2026-09-05T09:42:00Z")
    assert late["prospective_grade_eligible"] is False and late["remote_registration_timestamp"] is None

    bad = dict(receipt); bad["remote_commit_received_at_utc"] = "2026-09-06T18:00:00Z"
    expect_fail(lambda: build_remote_registration_event(forecast=forecast, receipt=bad, previous_record_hash=None),
                "REMOTE_RECEIPT_NOT_PREGAME")
    bad2 = dict(receipt); bad2["remote_protection_status"] = "UNPROTECTED"
    expect_fail(lambda: build_remote_registration_event(forecast=forecast, receipt=bad2, previous_record_hash=None),
                "REMOTE_BRANCH_NOT_PROTECTED")

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "journal.jsonl"
        append_hash_chained_record(p, late)
        assert p.read_text().count("\n") == 1
    print("Phase 1.1 durability tests: PASS")


if __name__ == "__main__":
    main()
