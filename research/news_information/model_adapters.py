from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any, Callable

from research.news_information.contracts import sha256_file
from research.news_information.model_registry import Candidate, candidates

COMPONENT_SCHEMA = "sports_news_component_output.v1"


class ModelRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class VerifiedSnapshot:
    candidate: Candidate
    root: Path
    receipt: dict[str, Any]


def verify_materialized_snapshot(candidate_id: str, receipt_path: Path, *, registry_path: Path | None = None) -> VerifiedSnapshot:
    reg = candidates(registry_path)
    if candidate_id not in reg:
        raise ModelRuntimeError(f"candidate not in lock: {candidate_id}")
    candidate = reg[candidate_id]
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    if receipt.get("candidate_id") != candidate_id or receipt.get("revision") != candidate.revision:
        raise ModelRuntimeError("materialization receipt identity mismatch")
    root = Path(receipt.get("snapshot_path") or Path(receipt_path).parents[3])
    files = receipt.get("files") or []
    if not files:
        raise ModelRuntimeError("materialization receipt has no files")
    for item in files:
        path = root / item["path"]
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            raise ModelRuntimeError(f"materialized snapshot file hash mismatch: {item['path']}")
    return VerifiedSnapshot(candidate, root, receipt)


def component_output(*, candidate: Candidate, operation: str, payload: Any,
                     latency_ms: float, status: str = "PASS", error: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": COMPONENT_SCHEMA,
        "candidate_id": candidate.id,
        "hf_repo": candidate.hf_repo,
        "revision": candidate.revision,
        "role": candidate.role,
        "operation": operation,
        "status": status,
        "payload": payload,
        "latency_ms": float(latency_ms),
        "error": error,
        "research_only": True,
        "trusted": False,
        "forecast_adjustment_eligible": False,
        "market_input": False,
        "action_authority": "OFF",
    }


class InjectedBackendAdapter:
    """Candidate-pinned adapter around an injected local inference callable.

    Unit/integration tests use deterministic fake callables. Real runtime code must first verify a
    materialization receipt and then inject a loader-backed callable. This keeps CI network/weight free.
    """

    def __init__(self, candidate_id: str, backend: Callable[..., Any], *, registry_path: Path | None = None):
        reg = candidates(registry_path)
        if candidate_id not in reg:
            raise ModelRuntimeError(f"unknown candidate: {candidate_id}")
        self.candidate = reg[candidate_id]
        self.backend = backend

    def run(self, operation: str, **kwargs) -> dict[str, Any]:
        start = time.perf_counter()
        try:
            payload = self.backend(operation=operation, **kwargs)
            status, error = "PASS", None
        except Exception as exc:
            payload, status, error = None, "ERROR", f"{type(exc).__name__}: {exc}"
        elapsed = (time.perf_counter() - start) * 1000
        return component_output(candidate=self.candidate, operation=operation, payload=payload,
                                latency_ms=elapsed, status=status, error=error)


ROLE_TO_OPERATION = {
    "source_relevance_reranker": "RERANK",
    "primary_information_extraction": "EXTRACT",
    "sports_status_ner_second_opinion": "EXTRACT",
    "zero_shot_ner_challenger": "EXTRACT",
    "claim_state_verification": "NLI_VERIFY",
    "multimodal_document_extractor": "DOCUMENT_EXTRACT",
    "sports_domain_encoder_benchmark": "ENCODE",
    "future_custom_finetune_base": "ENCODE",
    "sentiment_triage_control_only": "SENTIMENT_TRIAGE",
}


def candidate_operations(registry_path: Path | None = None) -> dict[str, str]:
    return {cid: ROLE_TO_OPERATION[c.role] for cid, c in candidates(registry_path).items()}
