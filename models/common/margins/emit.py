"""Emit and validate `sports.margin_quote.v1` records.

record_sha256 is sha256 over the canonical JSON (sorted keys, compact
separators) of the record WITHOUT the record_sha256 field itself. Inject
generated_at_utc for deterministic hashing in tests.

Limitations are explicit on every record; research_only=True and
action_authority=False are non-negotiable and validated.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

SCHEMA = "sports.margin_quote.v1"
_PROB_TOL = 1e-6

DEFAULT_LIMITATIONS = [
    "RESEARCH_ONLY_NOT_BETTING_ADVICE",
    "PROBABILITIES_MODEL_DEPENDENT",
    "PUSH_PROBABILITY_REQUIRES_DISCRETE_SUPPORT",
]

REQUIRED_KEYS = (
    "schema",
    "event_id",
    "home_spread",
    "probabilities",
    "distribution_id",
    "source_model",
    "sigma_provenance",
    "warnings",
    "limitations",
    "research_only",
    "action_authority",
    "generated_at_utc",
    "record_sha256",
)


def _canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _record_hash(rec: dict) -> str:
    body = {k: v for k, v in rec.items() if k != "record_sha256"}
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def margin_quote_record(
    dist,
    quote,
    *,
    event: dict,
    source_model: dict,
    sigma_provenance: dict,
    generated_at_utc: str | None = None,
) -> dict:
    if not isinstance(event, dict) or "event_id" not in event:
        raise ValueError("MARGIN_RECORD_EVENT_ID_REQUIRED")
    for k in ("model_id", "artifact_sha256"):
        if k not in source_model:
            raise ValueError("MARGIN_RECORD_SOURCE_MODEL_INVALID")
    if generated_at_utc is None:
        generated_at_utc = datetime.now(timezone.utc).isoformat()

    warnings = list(quote.labels)
    if quote.p_push > 0.0:
        warnings.append("PUSH_MASS_PRESENT")

    rec = {
        "schema": SCHEMA,
        "event_id": str(event["event_id"]),
        "home_spread": float(quote.home_spread),
        "probabilities": {
            "p_cover": float(quote.p_cover),
            "p_push": float(quote.p_push),
            "p_loss": float(quote.p_loss),
            "p_cover_ex_push": (
                None if quote.p_cover_ex_push is None else float(quote.p_cover_ex_push)
            ),
            "labels": list(quote.labels),
        },
        "distribution_id": dist.distribution_id,
        "source_model": {
            "model_id": str(source_model["model_id"]),
            "artifact_sha256": str(source_model["artifact_sha256"]),
        },
        "sigma_provenance": dict(sigma_provenance),
        "warnings": warnings,
        "limitations": list(DEFAULT_LIMITATIONS),
        "research_only": True,
        "action_authority": False,
        "generated_at_utc": str(generated_at_utc),
    }
    rec["record_sha256"] = _record_hash(rec)
    return rec


def validate_record(rec: dict) -> bool:
    if not isinstance(rec, dict):
        raise ValueError("MARGIN_RECORD_SCHEMA_VIOLATION")
    for k in REQUIRED_KEYS:
        if k not in rec:
            raise ValueError("MARGIN_RECORD_SCHEMA_VIOLATION")
    if rec["schema"] != SCHEMA:
        raise ValueError("MARGIN_RECORD_SCHEMA_VIOLATION")

    probs = rec["probabilities"]
    for k in ("p_cover", "p_push", "p_loss"):
        if k not in probs:
            raise ValueError("MARGIN_RECORD_SCHEMA_VIOLATION")
        v = probs[k]
        if not (0.0 - _PROB_TOL <= v <= 1.0 + _PROB_TOL):
            raise ValueError("MARGIN_RECORD_PROBABILITY_RANGE")
    total = probs["p_cover"] + probs["p_push"] + probs["p_loss"]
    if abs(total - 1.0) > _PROB_TOL:
        raise ValueError("MARGIN_RECORD_PROBABILITY_SUM")
    ex = probs.get("p_cover_ex_push")
    p_push = probs["p_push"]
    if "EXCLUDING_PUSHES" in probs.get("labels", ()):
        if ex is None or not (0.0 - _PROB_TOL <= ex <= 1.0 + _PROB_TOL):
            raise ValueError("MARGIN_RECORD_LABEL_VIOLATION")
        if p_push < 1.0 and abs(ex - probs["p_cover"] / (1.0 - p_push)) > _PROB_TOL:
            raise ValueError("MARGIN_RECORD_LABEL_VIOLATION")
    elif p_push > _PROB_TOL:
        # Push mass without the EXCLUDING_PUSHES label: the only legitimate
        # case is the degenerate all-push quote (p_push == 1.0), where
        # p_cover_ex_push is undefined and must be None. Anything else means
        # the label was stripped after sealing (or never emitted) — fail
        # closed rather than let an unlabeled conditional probability pass.
        if p_push < 1.0 - _PROB_TOL or ex is not None:
            raise ValueError("MARGIN_RECORD_LABEL_VIOLATION")

    if rec["research_only"] is not True or rec["action_authority"] is not False:
        raise ValueError("MARGIN_RECORD_AUTHORITY_VIOLATION")
    sm = rec["source_model"]
    if not isinstance(sm, dict) or "model_id" not in sm or "artifact_sha256" not in sm:
        raise ValueError("MARGIN_RECORD_SCHEMA_VIOLATION")
    if not isinstance(rec["warnings"], list) or not isinstance(rec["limitations"], list):
        raise ValueError("MARGIN_RECORD_SCHEMA_VIOLATION")
    if _record_hash(rec) != rec["record_sha256"]:
        raise ValueError("MARGIN_RECORD_HASH_MISMATCH")
    return True
