"""Numerical replay checks and evidence snapshots; neither grants eligibility.

The report store is new infrastructure, not the separately supplied SnapshotStore.
It detects local drift and refuses overwrite. It is not remote durability or an
independent timestamp witness.
"""
from __future__ import annotations

import hashlib
import json
import math
from numbers import Real
from pathlib import Path


def validate_tolerances(abs_tol=1e-11, rel_tol=0.0):
    for value in (abs_tol, rel_tol):
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("INVALID_COMPARISON_CONFIGURATION")
        try:
            valid = math.isfinite(value) and value >= 0
        except (OverflowError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("INVALID_COMPARISON_CONFIGURATION")
    return abs_tol, rel_tol


def equivalent(actual, expected, path="root", *, abs_tol=1e-11, rel_tol=0.0):
    """Exact typed identities and support; tolerance applies only to float fields.

Boolean metadata may match boolean metadata, but never a numeric operand. All
numeric operands are checked before equality/tolerance, including exact ints.
"""
    validate_tolerances(abs_tol, rel_tol)

    def compare(a, b, where):
        for value in (a, b):
            if isinstance(value, Real) and not isinstance(value, bool):
                try:
                    valid = math.isfinite(value)
                except (OverflowError, TypeError, ValueError):
                    valid = False
                if not valid:
                    raise ValueError("INVALID_COMPARISON_VALUE:" + where)
        if isinstance(b, dict):
            if not isinstance(a, dict) or a.keys() != b.keys():
                raise ValueError("REPLAY_KEYS:" + where)
            for key in b:
                compare(a[key], b[key], where + "." + str(key))
        elif isinstance(b, (list, tuple)):
            if not isinstance(a, (list, tuple)) or len(a) != len(b):
                raise ValueError("REPLAY_LENGTH:" + where)
            for i, (av, bv) in enumerate(zip(a, b)):
                compare(av, bv, where + ":" + str(i))
        elif isinstance(b, float):
            if isinstance(a, bool) or not isinstance(a, Real):
                raise ValueError("INVALID_COMPARISON_VALUE:" + where)
            if not math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol):
                raise ValueError("REPLAY_NUMERIC:" + where)
        elif type(a) is not type(b) or a != b:
            raise ValueError("REPLAY_IDENTITY:" + where)

    compare(actual, expected, path)


REPORT_KINDS = frozenset({"replay", "pit", "semantic", "source", "predictive"})


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _write_once(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != data:
            raise ValueError("IMMUTABLE_EVIDENCE_CONFLICT:" + str(path))


def write_snapshot(root, *, run_id, reports):
    """Bind every independent verdict to its complete immutable report bytes.

Reports must identify the same execution. UNKNOWN/NOT_RUN reports are valid
evidence of unresolved state. No all-pass requirement is imposed on replay.
"""
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("EVIDENCE_RUN_ID_REQUIRED")
    if not isinstance(reports, dict) or set(reports) != REPORT_KINDS:
        raise ValueError("EVIDENCE_REPORT_SET_REQUIRED")
    prepared = {}
    for kind, report in reports.items():
        if (not isinstance(report, dict) or report.get("kind") != kind
                or report.get("run_id") != run_id
                or not isinstance(report.get("verdict"), str) or not report["verdict"]
                or not isinstance(report.get("evidence"), dict) or not report["evidence"]):
            raise ValueError("EVIDENCE_REPORT_BINDING:" + kind)
        raw = encoded(report)
        prepared[kind] = (raw, digest_bytes(raw))
    root = Path(root)
    refs = {}
    for kind, (raw, digest) in prepared.items():
        relative = "reports/" + digest + ".json"
        _write_once(root / relative, raw)
        refs[kind] = {"path": relative, "sha256": digest}
    snapshot = {"schema": "sports.replay_evidence_snapshot.v1", "run_id": run_id,
                "reports": refs, "wagering_authority": "OFF",
                "persistence_scope": "LOCAL_CONTENT_ADDRESSED_NO_EXTERNAL_TIMESTAMP"}
    raw = encoded(snapshot)
    path = root / "snapshots" / (digest_bytes(raw) + ".json")
    _write_once(path, raw)
    read_snapshot(root, path)
    return path


def read_snapshot(root, path):
    root, path = Path(root).resolve(), Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("EVIDENCE_PATH_ESCAPE")
    raw = path.read_bytes()
    if path.name != digest_bytes(raw) + ".json":
        raise ValueError("SNAPSHOT_HASH_MISMATCH")
    snapshot = json.loads(raw)
    if set(snapshot.get("reports", {})) != REPORT_KINDS:
        raise ValueError("EVIDENCE_REPORT_SET_REQUIRED")
    reports = {}
    for kind, ref in snapshot["reports"].items():
        target = root / ref["path"]
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            raise ValueError("EVIDENCE_PATH_ESCAPE")
        data = target.read_bytes()
        if digest_bytes(data) != ref["sha256"]:
            raise ValueError("EVIDENCE_REPORT_DRIFT:" + kind)
        report = json.loads(data)
        if report.get("kind") != kind or report.get("run_id") != snapshot["run_id"]:
            raise ValueError("EVIDENCE_REPORT_BINDING:" + kind)
        reports[kind] = report
    return {"snapshot": snapshot, "reports": reports}
