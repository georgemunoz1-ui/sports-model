from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from research.news_information.contracts import RawSourceRecord, canonical_bytes, write_immutable_json


class RawArchive:
    """Content-addressed immutable raw-source archive.

    The archive does not fetch sources. Callers provide the bytes and their conservative
    retrieval/publication timestamps. Existing byte-different metadata collisions fail closed.
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    def put(self, raw: bytes, record: RawSourceRecord, *, media_type: str = "text/plain") -> dict[str, Any]:
        if record.raw_bytes_sha256 == "" or len(record.raw_bytes_sha256) != 64:
            raise ValueError("invalid raw bytes sha256")
        from research.news_information.contracts import sha256_bytes
        if sha256_bytes(raw) != record.raw_bytes_sha256:
            raise ValueError("raw bytes do not match source record hash")
        base = self.root / record.raw_bytes_sha256[:2] / record.raw_bytes_sha256
        raw_path = base / "source.bin"
        # Identical bytes may be observed repeatedly. Preserve each observation's
        # chronology instead of colliding with the first capture's metadata.
        from research.news_information.contracts import digest
        meta_path = base / "observations" / (digest(asdict(record)) + ".json")
        if raw_path.exists() and raw_path.read_bytes() != raw:
            raise ValueError(f"immutable raw-source collision: {raw_path}")
        if not raw_path.exists():
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(raw)
        metadata = {
            "schema_version": "sports_raw_source_record.v1",
            **asdict(record),
            "media_type": media_type,
            "raw_path": str(raw_path),
        }
        write_immutable_json(meta_path, metadata)
        return {"raw_path": str(raw_path), "metadata_path": str(meta_path), "raw_bytes_sha256": record.raw_bytes_sha256}
