"""Materialize pinned Hugging Face research candidates and emit immutable receipts.

Weights are never committed to git. A receipt records exact revision, local snapshot path,
per-file SHA-256 values, aggregate snapshot digest and license metadata from the intake lock.
Materialization never changes trusted/enabled/forecast-impacting state.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.news_information.contracts import digest, sha256_file, write_immutable_json
from research.news_information.model_registry import candidates


def materialize(candidate_id: str, *, cache_dir: Path, receipt_dir: Path, token: str | None = None):
    registry = candidates()
    if candidate_id not in registry:
        raise ValueError(f"unknown candidate: {candidate_id}")
    c = registry[candidate_id]
    if not c.download_enabled:
        raise ValueError(f"research download disabled for {candidate_id}")
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise RuntimeError("huggingface_hub is required for model materialization") from exc

    local = (Path(cache_dir) / candidate_id / c.revision).resolve()
    local.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=c.hf_repo,
        revision=c.revision,
        local_dir=str(local),
        allow_patterns=list(c.allow_patterns) or None,
        token=token,
    )
    files = []
    for path in sorted(p for p in local.rglob("*") if p.is_file() and ".cache" not in p.parts):
        files.append({"path": str(path.relative_to(local)), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    if not files:
        raise RuntimeError(f"materialization produced no files for {candidate_id}")
    core = {
        "schema_version": "sports_news_model_materialization_receipt.v1",
        "candidate_id": candidate_id,
        "hf_repo": c.hf_repo,
        "revision": c.revision,
        "role": c.role,
        "license": c.license,
        "license_status": c.license_status,
        "research_only": True,
        "trusted": False,
        "enabled_by_default": False,
        "forecast_adjustment_eligible": False,
        "snapshot_path": str(local),
        "files": files,
        "snapshot_sha256": digest(files),
    }
    receipt = {**core, "receipt_sha256": digest(core)}
    dest = Path(receipt_dir) / candidate_id / c.revision / receipt["receipt_sha256"] / "materialization_receipt.json"
    write_immutable_json(dest, receipt)
    return receipt, dest


def parser():
    p = argparse.ArgumentParser()
    p.add_argument("--candidate", default="all")
    p.add_argument("--cache-dir", type=Path, required=True)
    p.add_argument("--receipt-dir", type=Path, required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    ids = list(candidates()) if args.candidate == "all" else [args.candidate]
    results = []
    for cid in ids:
        receipt, path = materialize(cid, cache_dir=args.cache_dir, receipt_dir=args.receipt_dir)
        results.append({"candidate_id": cid, "snapshot_sha256": receipt["snapshot_sha256"], "receipt": str(path)})
    print(json.dumps({"status": "PASS", "count": len(results), "results": results}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
