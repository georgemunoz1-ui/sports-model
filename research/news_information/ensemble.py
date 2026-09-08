from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

DESTRUCTIVE = {"PLAYER_OUT", "STARTER_SCRATCHED", "BULLPEN_UNAVAILABLE"}


def normalize_candidate_claims(component_outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claims = []
    for output in component_outputs:
        if output.get("status") != "PASS":
            continue
        payload = output.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("claims"), list):
            items = payload["claims"]
        elif isinstance(payload, list):
            items = payload
        else:
            continue
        for claim in items:
            if not isinstance(claim, dict) or not claim.get("event_type"):
                continue
            claims.append({**claim, "candidate_id": output.get("candidate_id")})
    return claims


def consensus(component_outputs: list[dict[str, Any]], *, subject_id: str | None = None) -> dict[str, Any]:
    claims = normalize_candidate_claims(component_outputs)
    if subject_id is not None:
        claims = [c for c in claims if c.get("subject_id") in (None, subject_id)]
    if not claims:
        return {"cross_model_state": "ABSTAIN", "event_type": None, "vote_counts": {}, "claims": []}
    votes = Counter(c["event_type"] for c in claims)
    max_n = max(votes.values())
    leaders = sorted(k for k, n in votes.items() if n == max_n)
    unique_models = {c.get("candidate_id") for c in claims if c.get("candidate_id")}
    if len(leaders) != 1:
        state, event_type = "CONFLICTING", None
    else:
        event_type = leaders[0]
        leader_models = {c.get("candidate_id") for c in claims if c["event_type"] == event_type}
        if len(votes) == 1 and len(leader_models) >= 2:
            state = "CONSENSUS"
        elif len(votes) == 1:
            state = "PARTIAL_AGREEMENT"
        else:
            state = "PARTIAL_AGREEMENT" if len(leader_models) > max(1, len(unique_models) / 2) else "CONFLICTING"
            if state == "CONFLICTING":
                event_type = None
    return {"cross_model_state": state, "event_type": event_type,
            "vote_counts": dict(sorted(votes.items())), "claims": claims}


def destructive_claim_gate(*, event_type: str, cross_model_state: str,
                           source_tier: int, source_verified: bool,
                           nli_label: str | None, entity_resolved: bool,
                           pit_pass: bool) -> dict[str, Any]:
    """Research confidence gate only; never grants forecast adjustment authority."""
    destructive = event_type in DESTRUCTIVE
    reasons = []
    if not pit_pass: reasons.append("PIT_FAIL")
    if not entity_resolved: reasons.append("ENTITY_UNRESOLVED")
    if destructive and cross_model_state != "CONSENSUS": reasons.append("DESTRUCTIVE_NO_CONSENSUS")
    if destructive and not source_verified: reasons.append("DESTRUCTIVE_SOURCE_UNVERIFIED")
    if destructive and int(source_tier) > 2: reasons.append("DESTRUCTIVE_SOURCE_TIER_TOO_LOW")
    if destructive and nli_label not in ("ENTAILMENT", None): reasons.append("DESTRUCTIVE_NLI_NOT_ENTAILED")
    eligible = not reasons
    return {
        "research_feature_eligible": eligible,
        "forecast_adjustment_eligible": False,
        "destructive_claim": destructive,
        "reasons": reasons,
        "action_authority": "OFF",
    }
