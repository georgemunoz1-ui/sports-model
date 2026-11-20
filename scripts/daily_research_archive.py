#!/usr/bin/env python3
"""Seal complete research trees and verify independent byte readback.

A matching tree is an integrity result. The caller must separately bind a remote
provider, immutable object/commit, and successful independent fetch before calling
it durable archival. This utility creates no forecast or wagering authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.ci_evidence_archive import canonical, decode, digest, write_new

SCHEMA = "daily.research.manifest.v1"
MANIFEST = "manifest.json"


def _files(root):
    root = Path(root)
    if not root.is_dir() or any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("ARCHIVE_ROOT_INVALID_OR_SYMLINK")
    found = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError("ARCHIVE_SYMLINK_REFUSED:" + relative)
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("ARCHIVE_SPECIAL_FILE_REFUSED:" + relative)
        if relative == MANIFEST:
            continue
        if "\\" in relative or any(ord(c) < 32 for c in relative):
            raise ValueError("ARCHIVE_INVALID_MEMBER_NAME")
        found[relative] = path
    return found


def _member(name):
    if not isinstance(name, str) or not name or name == MANIFEST or "\\" in name:
        raise ValueError("ARCHIVE_INVALID_MEMBER_NAME")
    p = PurePosixPath(name)
    if p.is_absolute() or any(x in {".", ".."} for x in p.parts) or p.as_posix() != name or any(ord(c) < 32 for c in name):
        raise ValueError("ARCHIVE_INVALID_MEMBER_NAME")
    return name


def seal_directory(root):
    root = Path(root)
    if (root / MANIFEST).exists() or (root / MANIFEST).is_symlink():
        raise ValueError("ARCHIVE_MANIFEST_ALREADY_EXISTS")
    files = _files(root)
    if not files:
        raise ValueError("ARCHIVE_EMPTY_TREE")
    rows = [{"path": name, "size_bytes": path.stat().st_size, "sha256": digest(path)}
            for name, path in files.items()]
    manifest = {"schema": SCHEMA, "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "files": rows, "file_count": len(rows), "total_bytes": sum(x["size_bytes"] for x in rows),
                "action_authority": False, "official_release": False}
    write_new(root / MANIFEST, manifest)
    verify_directory(root, manifest)
    return manifest


def verify_directory(root, expected_manifest=None):
    root = Path(root)
    files = _files(root)
    manifest_path = root / MANIFEST
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("ARCHIVE_MANIFEST_MISSING_OR_SYMLINK")
    raw = manifest_path.read_bytes()
    manifest = decode(raw)
    if expected_manifest is not None:
        if isinstance(expected_manifest, (str, Path)):
            if raw != Path(expected_manifest).read_bytes():
                raise ValueError("ARCHIVE_MANIFEST_READBACK_MISMATCH")
        elif manifest != expected_manifest:
            raise ValueError("ARCHIVE_MANIFEST_READBACK_MISMATCH")
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise ValueError("ARCHIVE_MANIFEST_SCHEMA")
    if manifest.get("action_authority") is not False or manifest.get("official_release") is not False:
        raise ValueError("ARCHIVE_AUTHORITY_NOT_OFF")
    rows = manifest.get("files")
    if not isinstance(rows, list) or not rows:
        raise ValueError("ARCHIVE_EMPTY_MANIFEST")
    names = []
    total = 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "size_bytes", "sha256"}:
            raise ValueError("ARCHIVE_MEMBER_SCHEMA")
        name = _member(row["path"])
        if name in names:
            raise ValueError("ARCHIVE_DUPLICATE_MEMBER")
        names.append(name)
        if type(row["size_bytes"]) is not int or row["size_bytes"] < 0:
            raise ValueError("ARCHIVE_INVALID_MEMBER_SIZE")
        sha = row["sha256"]
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("ARCHIVE_INVALID_MEMBER_HASH")
        if name not in files or files[name].stat().st_size != row["size_bytes"] or digest(files[name]) != sha:
            raise ValueError("ARCHIVE_MEMBER_READBACK_MISMATCH:" + name)
        total += row["size_bytes"]
    if set(names) != set(files):
        raise ValueError("ARCHIVE_UNMANIFESTED_FILES")
    if type(manifest.get("file_count")) is not int or manifest["file_count"] != len(names) or type(manifest.get("total_bytes")) is not int or manifest["total_bytes"] != total:
        raise ValueError("ARCHIVE_MANIFEST_COUNTS")
    return {"schema": "daily.research.archive_verification.v1", "status": "VERIFIED",
            "verified_at_utc": datetime.now(timezone.utc).isoformat(),
            "manifest_sha256": hashlib.sha256(raw).hexdigest(), "file_count": len(names), "total_bytes": total,
            "verification_scope": "EXACT_MANIFEST_AND_ALL_TREE_BYTES", "remote_origin_verified": False,
            "durable_archive_verified": False, "action_authority": False, "official_release": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["seal", "verify"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, help="Original manifest to compare against independent readback")
    parser.add_argument("--report", type=Path, required=True, help="New path outside sealed tree")
    args = parser.parse_args(argv)
    if args.report.resolve().is_relative_to(args.root.resolve()):
        parser.error("--report must be outside the sealed tree")
    if args.report.exists():
        parser.error("--report must not exist")
    try:
        if args.operation == "seal":
            seal_directory(args.root)
        report = verify_directory(args.root, args.manifest)
    except (ValueError, OSError, KeyError) as exc:
        report = {"schema": "daily.research.archive_verification.v1", "status": "FAILED", "reason": str(exc),
                  "durable_archive_verified": False, "action_authority": False, "official_release": False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    write_new(args.report, report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
