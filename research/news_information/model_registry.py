from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

LOCK_SCHEMA = "sports_news_model_intake_lock.v1"
HEX40 = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class Candidate:
    id: str
    hf_repo: str
    revision: str
    role: str
    license: str
    license_status: str
    research_only: bool
    trusted: bool
    enabled_by_default: bool
    download_enabled: bool
    forecast_adjustment_eligible: bool
    allow_patterns: tuple[str, ...]


def default_lock_path() -> Path:
    return Path(__file__).parents[1] / "model_intake_lock.yaml"


def load_lock(path: Path | None = None) -> dict[str, Any]:
    p = path or default_lock_path()
    # JSON is valid YAML 1.2. Keeping this lock JSON-compatible lets the research core remain
    # standard-library-only while preserving the requested .yaml artifact name.
    data = json.loads(p.read_text(encoding="utf-8"))
    validate_lock(data)
    return data


def validate_lock(data: dict[str, Any]) -> None:
    if data.get("schema_version") != LOCK_SCHEMA:
        raise ValueError("unexpected model-intake lock schema")
    seen = set()
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("candidate lock must contain candidates")
    for item in candidates:
        cid = item.get("id")
        if not cid or cid in seen:
            raise ValueError(f"duplicate/missing candidate id: {cid!r}")
        seen.add(cid)
        if not HEX40.fullmatch(str(item.get("revision", ""))):
            raise ValueError(f"candidate {cid} revision must be immutable 40-char git SHA")
        if item.get("research_only") is not True:
            raise ValueError(f"candidate {cid} must be research_only")
        if item.get("trusted") is not False:
            raise ValueError(f"candidate {cid} cannot be predeclared trusted")
        if item.get("enabled_by_default") is not False:
            raise ValueError(f"candidate {cid} cannot be enabled by default")
        if item.get("forecast_adjustment_eligible") is not False:
            raise ValueError(f"candidate {cid} cannot alter forecasts")
        if item.get("download_enabled") is not True:
            raise ValueError(f"candidate {cid} was approved for research download and must record that explicitly")
        if not item.get("license_status"):
            raise ValueError(f"candidate {cid} missing license_status")


def candidates(path: Path | None = None) -> dict[str, Candidate]:
    lock = load_lock(path)
    out = {}
    for item in lock["candidates"]:
        out[item["id"]] = Candidate(
            id=item["id"], hf_repo=item["hf_repo"], revision=item["revision"], role=item["role"],
            license=item["license"], license_status=item["license_status"],
            research_only=bool(item["research_only"]), trusted=bool(item["trusted"]),
            enabled_by_default=bool(item["enabled_by_default"]), download_enabled=bool(item["download_enabled"]),
            forecast_adjustment_eligible=bool(item["forecast_adjustment_eligible"]),
            allow_patterns=tuple(item.get("allow_patterns") or ()),
        )
    return out
