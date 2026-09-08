from __future__ import annotations

from typing import Any

from research.news_information.taxonomies import all_event_types, allowed_event_types


def export_shadow_vector(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Expose neutral fact counts without silently dropping league extensions.

    This function remains a sport-neutral diagnostic exporter. It never maps an event to runs,
    points, goals, expected goals, player value or win probability. League-specific semantics belong
    in `build_league_information_state()` and any later impact transform must be separately versioned
    and validated.
    """
    if snapshot.get("schema_version") != "sports_information_state_snapshot.v1":
        raise ValueError("unexpected information-state snapshot")
    if snapshot.get("forecast_adjustment_enabled") is not False or snapshot.get("market_input") is not False:
        raise ValueError("information-state snapshot violates research-only policy")

    counts = snapshot.get("event_type_counts") or {}
    if not isinstance(counts, dict):
        raise ValueError("event_type_counts must be an object")
    league = snapshot.get("league")
    allowed = allowed_event_types(str(league).upper()) if league else all_event_types()
    unknown = sorted(set(counts) - set(allowed))
    if unknown:
        raise ValueError(f"unregistered information-state event types: {unknown}")

    return {
        "schema_version": "sports_information_shadow_vector.v1",
        "feature_contract_version": snapshot["feature_contract_version"],
        "event_id": snapshot["event_id"],
        "league": str(league).upper() if league else None,
        "cutoff_utc": snapshot["cutoff_utc"],
        "source_snapshot_sha256": snapshot["snapshot_sha256"],
        "features": {
            f"news_count__{key.lower()}": int(counts[key])
            for key in sorted(counts)
        },
        "news_conflict_count": int(snapshot.get("conflicting_information_event_count", 0)),
        "model_use": "SHADOW_ONLY_NO_TRANSFORM",
        "neutral_counts_only": True,
        "league_transform_required_for_impact": True,
        "forecast_adjustment_eligible": False,
        "market_input": False,
        "action_authority": "OFF",
    }
