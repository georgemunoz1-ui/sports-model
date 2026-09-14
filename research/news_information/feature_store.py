from __future__ import annotations

from pathlib import Path
from typing import Any

from research.news_information.contracts import digest, validate_information_event, write_immutable_json


class ResearchFeatureStore:
    """Immutable content-addressed store for research information events and snapshots."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def put_event(self, event: dict[str, Any]) -> Path:
        event = validate_information_event(event)
        eid = event["information_event_id"]
        dest = self.root / "events" / eid[:2] / eid / "event.json"
        write_immutable_json(dest, event)
        return dest

    def snapshot(self, *, event_id: str, cutoff_utc: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        valid = [validate_information_event(e) for e in events]
        valid = [e for e in valid if e["event_id"] == event_id and e["forecast_timing"]["known_before_cutoff"]]
        leagues = sorted({e["league"] for e in valid})
        if len(leagues) > 1:
            raise ValueError("information-state snapshot cannot mix leagues")
        league = leagues[0] if leagues else None
        valid.sort(key=lambda x: x["information_event_id"])
        counts: dict[str, int] = {}
        conflict = 0
        for e in valid:
            t = e["claim"]["event_type"]
            counts[t] = counts.get(t, 0) + 1
            conflict += int(e["resolution"]["cross_model_state"] == "CONFLICTING")
        core = {
            "schema_version": "sports_information_state_snapshot.v1",
            "feature_contract_version": "sports_information_state.v0_1.research",
            "event_id": event_id,
            "league": league,
            "cutoff_utc": cutoff_utc,
            "information_event_ids": [e["information_event_id"] for e in valid],
            "event_type_counts": dict(sorted(counts.items())),
            "conflicting_information_event_count": conflict,
            "research_only": True,
            "forecast_adjustment_enabled": False,
            "market_input": False,
            "action_authority": "OFF",
        }
        return {**core, "snapshot_sha256": digest(core)}

    def write_snapshot(self, snapshot: dict[str, Any]) -> Path:
        sid = snapshot["snapshot_sha256"]
        dest = self.root / "snapshots" / sid[:2] / sid / "information_state_snapshot.json"
        write_immutable_json(dest, snapshot)
        return dest
