from __future__ import annotations

from typing import Any

ALLOWED_SHADOW_FIELDS = (
    "PLAYER_OUT", "PLAYER_DOUBTFUL", "PLAYER_QUESTIONABLE", "PLAYER_ACTIVE",
    "LINEUP_CONFIRMED", "LINEUP_PROJECTED", "STARTER_CONFIRMED", "STARTER_SCRATCHED",
    "STARTER_PITCH_LIMIT", "BULLPEN_AVAILABLE", "BULLPEN_LIMITED", "BULLPEN_UNAVAILABLE",
    "ROSTER_CALLUP", "ROSTER_OPTION", "TRAVEL_DISRUPTION", "WEATHER_DELAY_RISK",
    "ROOF_STATUS", "WEATHER_CHANGE",
)


def export_shadow_vector(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Expose reproducible information-state counts without a probability transform.

    This is intentionally not a production feature adapter. No coefficient or run/probability delta
    is defined. A later challenger must preregister a frozen transform/version separately.
    """
    if snapshot.get("schema_version") != "sports_information_state_snapshot.v1":
        raise ValueError("unexpected information-state snapshot")
    if snapshot.get("forecast_adjustment_enabled") is not False or snapshot.get("market_input") is not False:
        raise ValueError("information-state snapshot violates research-only policy")
    counts = snapshot.get("event_type_counts") or {}
    return {
        "schema_version": "sports_information_shadow_vector.v1",
        "feature_contract_version": snapshot["feature_contract_version"],
        "event_id": snapshot["event_id"],
        "cutoff_utc": snapshot["cutoff_utc"],
        "source_snapshot_sha256": snapshot["snapshot_sha256"],
        "features": {f"news_count__{key.lower()}": int(counts.get(key, 0)) for key in ALLOWED_SHADOW_FIELDS},
        "news_conflict_count": int(snapshot.get("conflicting_information_event_count", 0)),
        "model_use": "SHADOW_ONLY_NO_TRANSFORM",
        "forecast_adjustment_eligible": False,
        "market_input": False,
        "action_authority": "OFF",
    }
