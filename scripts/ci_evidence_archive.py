#!/usr/bin/env python3
"""Package CI evidence and verify a configured Drive adapter by byte read-back.

No uploader, destination or credential is configured here. The adapter reuses
an operator-authorized uploader; see docs/CI_STORAGE_ARCHIVE.md for its protocol.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import zipfile


class ArchiveError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def decode(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ArchiveError("DUPLICATE_JSON_KEY")
            value[key] = item
        return value
    def invalid(value):
        raise ArchiveError("NONFINITE_JSON")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def write_new(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def identity_from_environment(env):
    required = {"repository": "GITHUB_REPOSITORY", "workflow": "GITHUB_WORKFLOW",
                "run_id": "GITHUB_RUN_ID", "run_attempt": "GITHUB_RUN_ATTEMPT",
                "checkout_sha": "GITHUB_SHA", "event_name": "GITHUB_EVENT_NAME"}
    identity = {key: env.get(value, "") for key, value in required.items()}
    if any(not value for value in identity.values()):
        raise ArchiveError("MISSING_RUN_IDENTITY")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", identity["repository"]) is None:
        raise ArchiveError("INVALID_REPOSITORY")
    if any(re.fullmatch(r"[1-9][0-9]*", identity[key]) is None for key in ("run_id", "run_attempt")):
        raise ArchiveError("INVALID_RUN_OR_ATTEMPT")
    if re.fullmatch(r"[0-9a-f]{40}", identity["checkout_sha"]) is None:
        raise ArchiveError("INVALID_CHECKOUT_SHA")
    for key, variable in (("head_sha", "CI_HEAD_SHA"), ("base_sha", "CI_BASE_SHA")):
        value = env.get(variable) or None
        if value is not None and re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise ArchiveError("INVALID_HEAD_OR_BASE_SHA")
        identity[key] = value
    identity["run_url"] = f"https://github.com/{identity['repository']}/actions/runs/{identity['run_id']}/attempts/{identity['run_attempt']}"
    return identity


def collect_sources(required, optional):
    sources, missing, names = [], [], set()
    for spec, mandatory in [(x, True) for x in required] + [(x, False) for x in optional]:
        if "=" not in spec:
            raise ArchiveError("SOURCE_REQUIRES_ARCHIVE_NAME_EQUALS_PATH")
        name, location = spec.split("=", 1)
        parts = PurePosixPath(name).parts
        if not name or any(ord(c) < 32 for c in name) or "\\" in name or name.startswith("/") or any(x in {".", ".."} for x in parts) or name in names or name in {"manifest.json", "checksums.sha256"}:
            raise ArchiveError("INVALID_OR_DUPLICATE_MEMBER_NAME")
        names.add(name)
        path = Path(location)
        if path.is_symlink():
            raise ArchiveError("SYMLINK_SOURCE_REFUSED")
        if not path.exists():
            if mandatory:
                raise ArchiveError("REQUIRED_SOURCE_MISSING:" + name)
            missing.append(name)
            continue
        if not path.is_file():
            raise ArchiveError("SOURCE_MUST_BE_FILE:" + name)
        sources.append((name, path.resolve(), {"path": name, "size_bytes": path.stat().st_size,
                                             "sha256": digest(path), "required": mandatory}))
    if not sources:
        raise ArchiveError("NO_EVIDENCE_FILES")
    return sorted(sources), sorted(missing)


def build_bundle(output_dir, identity, required, optional, *, created_at=None):
    sources, missing = collect_sources(required, optional)
    manifest = {"schema": "ci-evidence-manifest-v1", "created_at_utc": created_at or now(),
                "identity": identity, "files": [item[2] for item in sources],
                "missing_optional_files": missing, "source_kind": "ORIGINAL_CURRENT_RUN_FILES",
                "publication_allowed": False, "wagering_status": "OFF"}
    manifest_raw = canonical(manifest) + b"\n"
    manifest_hash = hashlib.sha256(manifest_raw).hexdigest()
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", identity["repository"] + "-" + identity["workflow"])
    name = f"{slug}-run-{identity['run_id']}-attempt-{identity['run_attempt']}-{manifest_hash[:16]}.zip"
    output = Path(output_dir)
    output.mkdir(parents=False, exist_ok=False)
    archive = output / name
    checksums = "".join(f"{item[2]['sha256']}  {item[0]}\n" for item in sources)
    checksums += f"{manifest_hash}  manifest.json\n"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for member, path, receipt in sources:
            bundle.write(path, member)
            if path.stat().st_size != receipt["size_bytes"] or digest(path) != receipt["sha256"]:
                raise ArchiveError("SOURCE_CHANGED_DURING_BUNDLE:" + member)
        bundle.writestr("manifest.json", manifest_raw)
        bundle.writestr("checksums.sha256", checksums)
    verify_bundle(archive, manifest)
    metadata = {"schema": "ci-evidence-bundle-v1", "created_at_utc": now(), "identity": identity,
                "archive_path": str(archive.resolve()), "archive_name": name,
                "archive_sha256": digest(archive), "size_bytes": archive.stat().st_size,
                "manifest_sha256": manifest_hash, "missing_optional_files": missing}
    write_new(output / "bundle.json", metadata)
    (output / "archive.sha256").write_text(f"{metadata['archive_sha256']}  {name}\n", encoding="utf-8")
    return metadata


def verify_bundle(path, expected_manifest=None):
    with zipfile.ZipFile(path) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)):
            raise ArchiveError("DUPLICATE_ZIP_MEMBERS")
        manifest_raw = bundle.read("manifest.json")
        manifest = decode(manifest_raw)
        if expected_manifest is not None and manifest != expected_manifest:
            raise ArchiveError("MANIFEST_CHANGED")
        expected = {item["path"] for item in manifest["files"]} | {"manifest.json", "checksums.sha256"}
        if set(names) != expected:
            raise ArchiveError("UNMANIFESTED_ZIP_MEMBERS")
        checksums = ""
        for receipt in manifest["files"]:
            data = bundle.read(receipt["path"])
            if len(data) != receipt["size_bytes"] or hashlib.sha256(data).hexdigest() != receipt["sha256"]:
                raise ArchiveError("MEMBER_CHECKSUM_MISMATCH")
            checksums += f"{receipt['sha256']}  {receipt['path']}\n"
        checksums += f"{hashlib.sha256(manifest_raw).hexdigest()}  manifest.json\n"
        if bundle.read("checksums.sha256") != checksums.encode():
            raise ArchiveError("CHECKSUM_INDEX_MISMATCH")
    return manifest


class PinnedAdapter:
    """Trusted local bridge to an existing uploader; no shell or implicit auth."""
    def __init__(self, config):
        if not isinstance(config, dict) or config.get("schema") != "ci-storage-config-v1":
            raise ArchiveError("INVALID_STORAGE_CONFIG")
        self.path = Path(config.get("adapter_path", "")).resolve(strict=True)
        self.expected_hash = config.get("adapter_sha256")
        self.destination = config.get("drive_destination_id")
        if not isinstance(self.destination, str) or not self.destination.strip():
            raise ArchiveError("DRIVE_DESTINATION_REQUIRED")
        if not self.path.is_file() or digest(self.path) != self.expected_hash:
            raise ArchiveError("ADAPTER_CODE_HASH_MISMATCH")

    def call(self, operation, payload):
        if digest(self.path) != self.expected_hash:
            raise ArchiveError("ADAPTER_CODE_CHANGED")
        process = subprocess.run([sys.executable, str(self.path), operation], input=canonical(payload),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300, check=False)
        if process.returncode:
            # Adapter output might contain credentials. Preserve only operation/exit.
            raise ArchiveError(f"ADAPTER_OPERATION_FAILED:{operation}:exit={process.returncode}")
        result = decode(process.stdout)
        if not isinstance(result, dict) or result.get("provider") != "google_drive":
            raise ArchiveError("ADAPTER_PROVIDER_NOT_GOOGLE_DRIVE")
        return result

    def capabilities(self, required):
        result = self.call("capabilities", {})
        if result.get("protocol") != "ci-storage-adapter-v1" or not set(required) <= set(result.get("operations", [])):
            raise ArchiveError("ADAPTER_CAPABILITY_MISSING")


def archive_to_drive(metadata, adapter):
    adapter.capabilities({"put_immutable", "download"})
    local = Path(metadata["archive_path"])
    if digest(local) != metadata["archive_sha256"]:
        raise ArchiveError("LOCAL_BUNDLE_CHANGED")
    uploaded = adapter.call("put_immutable", {"destination_id": adapter.destination,
        "name": metadata["archive_name"], "local_path": str(local),
        "sha256": metadata["archive_sha256"], "size_bytes": metadata["size_bytes"]})
    if uploaded.get("destination_id") != adapter.destination or uploaded.get("name") != metadata["archive_name"] or not isinstance(uploaded.get("object_id"), str) or not uploaded["object_id"]:
        raise ArchiveError("UPLOAD_IDENTITY_MISMATCH")
    with tempfile.TemporaryDirectory(prefix="ci-drive-readback-") as temporary:
        downloaded = Path(temporary) / "readback.zip"
        adapter.call("download", {"object_id": uploaded["object_id"], "local_path": str(downloaded)})
        if not downloaded.is_file() or downloaded.stat().st_size != metadata["size_bytes"] or digest(downloaded) != metadata["archive_sha256"]:
            raise ArchiveError("DRIVE_READBACK_SHA256_MISMATCH")
        manifest = verify_bundle(downloaded)
        if manifest["identity"] != metadata["identity"]:
            raise ArchiveError("DRIVE_READBACK_RUN_IDENTITY_MISMATCH")
    return {"status": "VERIFIED", "reason": "DRIVE_BYTES_AND_MEMBERS_VERIFIED",
            "object_id": uploaded["object_id"], "destination_id": adapter.destination,
            "archive_sha256": metadata["archive_sha256"], "verified_at_utc": now(),
            "durable_archive_verified": True, "optional_github_upload_allowed": True}


def config_from_environment(variable):
    value = os.environ.get(variable, "")
    return decode(value) if value.strip() else None


def report_status(status):
    print(json.dumps(status, sort_keys=True))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("archive_status=" + status["status"] + "\n")
            output.write("durable_archive_verified=" + str(status["durable_archive_verified"]).lower() + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write(f"\nDrive archive: **{status['status']}** — {status['reason']}. "
                          "Software checks and archive durability are separate results.\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, help="Fresh directory for the bundle and receipts.")
    parser.add_argument("--source", action="append", default=[], help="Required archive_member=local_file.")
    parser.add_argument("--optional-source", action="append", default=[], help="Missing members explicitly recorded.")
    parser.add_argument("--config-env", default="CI_STORAGE_CONFIG_JSON", help="Explicit adapter/destination config; never credentials.")
    args = parser.parse_args(argv)
    output_existed = Path(args.output_dir).exists() or Path(args.output_dir).is_symlink()
    status = {"status": "FAILED", "reason": "NOT_EXECUTED", "durable_archive_verified": False,
              "optional_github_upload_allowed": False, "created_at_utc": now()}
    try:
        metadata = build_bundle(args.output_dir, identity_from_environment(os.environ), args.source, args.optional_source)
        config = config_from_environment(args.config_env)
        if config is None:
            status.update(status="BLOCKED_UNCONFIGURED", reason="AUTHORIZED_UPLOADER_AND_DRIVE_DESTINATION_NOT_CONFIGURED")
        else:
            status.update(archive_to_drive(metadata, PinnedAdapter(config)))
        write_new(Path(args.output_dir) / "archive-status.json", status)
        report_status(status)
        return 0  # Explicit BLOCKED status is not a successful archive claim.
    except (ArchiveError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired, zipfile.BadZipFile) as exc:
        status.update(reason=str(exc))
        if not output_existed and Path(args.output_dir).is_dir() and not (Path(args.output_dir) / "archive-status.json").exists():
            write_new(Path(args.output_dir) / "archive-status.json", status)
        report_status(status)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
