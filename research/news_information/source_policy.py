from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def default_policy_path() -> Path:
    return Path(__file__).with_name("source_allowlist.v1.json")


def load_policy(path: Path | None = None) -> dict[str, Any]:
    p = path or default_policy_path()
    value = json.loads(p.read_text(encoding="utf-8"))
    if value.get("schema_version") != "sports_information_source_allowlist.v1":
        raise ValueError("unexpected source allowlist schema")
    return value


def source_disposition(*, source_id: str, source_tier: int, source_type: str,
                       policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or load_policy()
    if not 1 <= int(source_tier) <= 6:
        raise ValueError("source tier must be 1..6")
    named = {x.get("source_id"): x for x in policy.get("sources", [])}
    entry = named.get(source_id)
    if entry is not None:
        if int(entry.get("source_tier")) != int(source_tier) or entry.get("source_type") != source_type:
            raise ValueError("named source identity disagrees with allowlist")
        verification = "ALLOWLIST_VERIFIED"
    else:
        verification = "UNVERIFIED_SOURCE_ID"
    research_max = int(policy["policy"]["research_extraction_max_tier"])
    discovery_min = int(policy["policy"]["discovery_only_min_tier"])
    return {
        "source_verification_state": verification,
        "research_extraction_eligible": int(source_tier) <= research_max,
        "discovery_only": int(source_tier) >= discovery_min,
        "future_forecast_use_requires_separate_validation": True,
        "forecast_adjustment_eligible": False,
    }
