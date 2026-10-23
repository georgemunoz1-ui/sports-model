"""Offline archive contracts. The fake adapter is not a real Google Drive upload."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest
import yaml

from scripts.ci_evidence_archive import (ArchiveError, PinnedAdapter, archive_to_drive,
    build_bundle, canonical, digest, identity_from_environment, verify_bundle)

ROOT = Path(__file__).resolve().parents[1]
ENV = {"GITHUB_REPOSITORY": "TEST_ONLY/repository", "GITHUB_WORKFLOW": "Test evidence",
       "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": "a" * 40,
       "GITHUB_EVENT_NAME": "pull_request", "CI_HEAD_SHA": "b" * 40, "CI_BASE_SHA": "c" * 40}


def sample(tmp_path):
    source = tmp_path / "tests.log"
    source.write_bytes(b"TEST_ONLY: 32 passed\n")
    return build_bundle(tmp_path / "bundle", identity_from_environment(ENV),
                        [f"tests.log={source}"], [f"health.log={tmp_path / 'absent'}"],
                        created_at="2026-10-23T00:00:00Z")


def fake_adapter(tmp_path, mode="good"):
    remote = tmp_path / "fake_remote"
    remote.mkdir()
    script = tmp_path / "adapter.py"
    script.write_text('''import hashlib,json,pathlib,shutil,sys
root=pathlib.Path(__file__).parent/'fake_remote'
p=json.load(sys.stdin); op=sys.argv[1]; result={'provider':'google_drive'}
if op=='capabilities':
 result.update(protocol='ci-storage-adapter-v1',operations=['put_immutable','download','state_get','state_compare_and_swap'])
elif op=='put_immutable':
 target=root/p['name']
 if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=p['sha256']: sys.exit(9)
 if not target.exists(): shutil.copyfile(p['local_path'],target)
 result.update(object_id=p['name'],name=p['name'],destination_id=p['destination_id'])
elif op=='download':
 shutil.copyfile(root/p['object_id'],p['local_path'])
 if MODE=='corrupt': pathlib.Path(p['local_path']).write_bytes(b'corrupted')
elif op=='state_get':
 path=root/'state.json'
 result.update(json.loads(path.read_text()) if path.exists() else {'state':None,'revision':None})
elif op=='state_compare_and_swap':
 path=root/'state.json'; prior=json.loads(path.read_text()) if path.exists() else {'revision':None}
 if prior['revision']!=p['expected_revision'] or MODE=='conflict': sys.exit(10)
 raw=json.dumps(p['state'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()
 rev=hashlib.sha256(raw).hexdigest()
 path.write_text(json.dumps({'revision':rev,'state':p['state']}))
 result.update(revision=rev,state_sha256=rev)
 if MODE=='state_corrupt': path.write_text(json.dumps({'revision':rev,'state':{}}))
else: sys.exit(7)
print(json.dumps(result))
'''.replace("MODE", repr(mode)))
    config = {"schema": "ci-storage-config-v1", "adapter_path": str(script),
              "adapter_sha256": digest(script), "drive_destination_id": "TEST_ONLY_DESTINATION"}
    return PinnedAdapter(config), config


def test_bundle_preserves_source_manifest_checksums_and_attempt_identity(tmp_path):
    metadata = sample(tmp_path)
    archive = Path(metadata["archive_path"])
    manifest = verify_bundle(archive)
    assert manifest["identity"]["checkout_sha"] == ENV["GITHUB_SHA"]
    assert manifest["identity"]["head_sha"] == ENV["CI_HEAD_SHA"]
    assert manifest["identity"]["base_sha"] == ENV["CI_BASE_SHA"]
    assert "run-123-attempt-1" in archive.name
    assert manifest["missing_optional_files"] == ["health.log"]
    assert manifest["source_kind"] == "ORIGINAL_CURRENT_RUN_FILES"
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.read("tests.log") == (tmp_path / "tests.log").read_bytes()
        assert hashlib.sha256(bundle.read("manifest.json")).hexdigest() == metadata["manifest_sha256"]
        assert bundle.read("checksums.sha256").count(b"\n") == 2
    second = build_bundle(tmp_path / "attempt2", identity_from_environment(dict(ENV, GITHUB_RUN_ATTEMPT="2")),
                          [f"tests.log={tmp_path / 'tests.log'}"], [], created_at="2026-10-23T00:00:00Z")
    assert second["archive_name"] != metadata["archive_name"]


def test_upload_success_requires_byte_readback_and_local_member_verification(tmp_path):
    metadata = sample(tmp_path)
    adapter, _ = fake_adapter(tmp_path)
    status = archive_to_drive(metadata, adapter)
    assert status["status"] == "VERIFIED"
    assert status["durable_archive_verified"] is True
    assert digest(tmp_path / "fake_remote" / status["object_id"]) == metadata["archive_sha256"]


def test_corrupt_remote_bytes_never_grant_archive_success(tmp_path):
    metadata = sample(tmp_path)
    adapter, _ = fake_adapter(tmp_path, "corrupt")
    with pytest.raises(ArchiveError, match="READBACK_SHA256_MISMATCH"):
        archive_to_drive(metadata, adapter)


def test_pinned_adapter_code_cannot_change_after_authorization(tmp_path):
    adapter, _ = fake_adapter(tmp_path)
    adapter.path.write_text("raise SystemExit('changed')")
    with pytest.raises(ArchiveError, match="ADAPTER_CODE_CHANGED"):
        adapter.capabilities({"download"})


@pytest.mark.parametrize("name", ["../escape", "/absolute", "x\\y", "line\nbreak", "manifest.json"])
def test_unsafe_member_paths_and_manifest_replacement_fail(tmp_path, name):
    source = tmp_path / "source"
    source.write_text("data")
    with pytest.raises(ArchiveError):
        build_bundle(tmp_path / "bad", identity_from_environment(ENV), [f"{name}={source}"], [])


def test_unconfigured_cli_preserves_bundle_and_reports_blocked_without_overwrite(tmp_path):
    source = tmp_path / "source.log"
    source.write_text("TEST_ONLY")
    command = [sys.executable, str(ROOT / "scripts/ci_evidence_archive.py"),
               "--output-dir", str(tmp_path / "output"), "--source", f"source.log={source}"]
    environment = {**os.environ, **ENV, "CI_STORAGE_CONFIG_JSON": "", "GITHUB_OUTPUT": str(tmp_path / "outputs")}
    environment.pop("GITHUB_STEP_SUMMARY", None)
    result = subprocess.run(command, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    status = json.loads((tmp_path / "output/archive-status.json").read_text())
    assert status["status"] == "BLOCKED_UNCONFIGURED"
    assert status["durable_archive_verified"] is False
    assert status["optional_github_upload_allowed"] is False
    before = {p: p.read_bytes() for p in (tmp_path / "output").iterdir()}
    assert subprocess.run(command, env=environment, capture_output=True).returncode == 1
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert set((tmp_path / "output").iterdir()) == set(before)


def test_configured_readback_failure_is_fatal_and_recorded(tmp_path):
    source = tmp_path / "source.log"
    source.write_text("TEST_ONLY")
    _, config = fake_adapter(tmp_path, "corrupt")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/ci_evidence_archive.py"),
        "--output-dir", str(tmp_path / "output"), "--source", f"source.log={source}"],
        env={**os.environ, **ENV, "CI_STORAGE_CONFIG_JSON": json.dumps(config)}, capture_output=True)
    assert result.returncode == 1
    status = json.loads((tmp_path / "output/archive-status.json").read_text())
    assert status["status"] == "FAILED"
    assert status["durable_archive_verified"] is False


@pytest.mark.parametrize("workflow", ["mlb-current.yml", "consolidation.yml"])
def test_actual_workflows_enforce_drive_first_and_short_optional_retention(workflow):
    document = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())
    triggers = document.get("on", document.get(True))
    assert "main" in triggers["push"]["branches"]
    steps = document["jobs"]["verify"]["steps"]
    archive = next(step for step in steps if step.get("id") == "drive_archive")
    optional = next(step for step in steps if step.get("id") == "github_copy")
    assert steps.index(archive) < steps.index(optional)
    assert "continue-on-error" not in archive
    assert "ci_evidence_archive.py" in archive["run"]
    assert "archive_status == 'VERIFIED'" in optional["if"]
    assert "CI_OPTIONAL_GITHUB_ARTIFACTS == 'true'" in optional["if"]
    assert optional["with"]["retention-days"] == 7
    assert "github.run_attempt" in optional["with"]["name"]
    assert any("outcomes separately" in step.get("name", "") for step in steps)


@pytest.mark.parametrize("workflow", ["mlb-current.yml", "consolidation.yml", "storage-monitor.yml"])
def test_changed_workflow_shell_blocks_parse(workflow):
    document = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())
    for job in document["jobs"].values():
        for step in job["steps"]:
            if "run" in step:
                result = subprocess.run(["bash", "-n"], input=step["run"], text=True, capture_output=True)
                assert result.returncode == 0, (step.get("name"), result.stderr)
