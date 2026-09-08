from __future__ import annotations

from typing import Any

from research.news_information.contracts import RawSourceRecord, validate_information_event
from research.news_information.ensemble import consensus, destructive_claim_gate
from research.news_information.source_policy import source_disposition
from research.news_information.taxonomies import taxonomy_for_league


class ResearchInformationPipeline:
    """Pure orchestration layer over precomputed component outputs.

    It intentionally does not fetch the web, load weights, or modify any forecast. The same function
    is used for offline fixtures and locally materialized model outputs. League-specific impact is
    deliberately outside this shared extraction layer.
    """

    def build_event(self, *, league: str, event_id: str, source: RawSourceRecord,
                    component_outputs: list[dict[str, Any]], claim_seed: dict[str, Any],
                    resolution: dict[str, Any], nli_label: str | None = None) -> dict[str, Any]:
        league = str(league).upper()
        taxonomy = taxonomy_for_league(league)
        src = source_disposition(source_id=source.source_id, source_tier=source.source_tier,
                                 source_type=source.source_type)
        c = consensus(component_outputs, subject_id=claim_seed.get("subject_id"))
        event_type = c.get("event_type") or claim_seed.get("event_type")
        source_verified = src["source_verification_state"] == "ALLOWLIST_VERIFIED"
        entity_resolved = all(float(resolution.get(k, 0.0)) >= .999 for k in (
            "player_resolution_confidence", "team_resolution_confidence", "game_resolution_confidence"))
        gate = destructive_claim_gate(
            event_type=event_type,
            cross_model_state=c["cross_model_state"],
            source_tier=source.source_tier,
            source_verified=source_verified,
            nli_label=nli_label,
            entity_resolved=entity_resolved,
            pit_pass=source.known_before_cutoff,
            league=league,
        )
        event = {
            "schema_version": "sports_information_event.v1",
            "information_event_id": None,
            "event_id": event_id,
            "league": league,
            "source": {
                "source_id": source.source_id,
                "source_tier": source.source_tier,
                "source_type": source.source_type,
                "source_url": source.source_url,
                "post_id": source.post_id,
                "published_at_utc": source.published_at_utc,
                "retrieved_at_utc": source.retrieved_at_utc,
                "raw_bytes_sha256": source.raw_bytes_sha256,
            },
            "forecast_timing": {
                "forecast_cutoff_utc": source.forecast_cutoff_utc,
                "game_start_utc": source.game_start_utc,
                "known_before_cutoff": source.known_before_cutoff,
                "pit_status": source.pit_status,
            },
            "claim": {**claim_seed, "event_type": event_type},
            "extraction": {
                "component_outputs": component_outputs,
                "consensus": c,
                "nli_verification": {"label": nli_label} if nli_label else None,
                "taxonomy": {
                    "core": taxonomy["core_taxonomy_version"],
                    "extension": taxonomy["extension_taxonomy_version"],
                },
                "research_gate": gate,
            },
            "resolution": {
                **resolution,
                "source_verification_state": src["source_verification_state"],
                "cross_model_state": c["cross_model_state"],
            },
            "usage_policy": {
                "research_feature_eligible": bool(gate["research_feature_eligible"]),
                "forecast_adjustment_eligible": False,
                "market_input": False,
                "action_authority": "OFF",
            },
        }
        return validate_information_event(event)
