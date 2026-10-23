"""Deterministic research selection, separate from forecasting and publication.

The objective is unconditional winning-settlement accuracy. Pushes and voids
are distinct outcomes, never half wins. Prices are diagnostics after selection.
An artifact hash establishes content identity, not the truth of its source.
Only the validation registry can establish procedural qualification; this
module never grants ACTIVE publication or wagering authority.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


class ResearchSelectionError(ValueError):
    """The supplied artifact is malformed or its claimed identity changed."""


SPEC = {
    "schema": "research-selection-spec-v1",
    "objective": "unconditional_win",
    "selection_rule": "win_probability >= frozen_threshold",
    "decision_classes": ["BLOCKED", "ELIGIBLE_NOT_SELECTED", "SHADOW_SELECTED"],
    "price_policy": "diagnostic_only",
    "push_and_void": "separate_outcomes_stake_refunded",
    "confidence_bands": "unimplemented_null",
    "publication_allowed": False,
    "wagering_status": "OFF",
}
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_TARGET_KEYS = {
    "event_id", "league", "product", "period", "side", "line",
    "settlement_rules_id", "starts_at_utc",
}
_FORECAST_KEYS = {
    "schema", "procedure_id", "input_snapshot_sha256", "target", "probabilities",
    "forecast_cutoff_utc", "forecast_created_at_utc",
}
_CONFIG_KEYS = {"schema", "objective", "threshold", "require_quality_receipt"}
_QUALITY_KEYS = {
    "forecast_id", "input_snapshot_sha256", "created_at_utc",
    "blocking_reasons", "review_notes", "receipt_id",
}
_OUTCOMES = {"win", "loss", "push", "void"}
_PRICE_FIELDS = {
    "price_status", "price_break_even", "estimated_value", "estimated_value_basis",
    "price_reasons", "price_quote", "price_diagnostics_id",
}


def content_hash(value: Any) -> str:
    """SHA256 of canonical UTF-8 JSON; NaN/Infinity are not valid artifacts."""
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise ResearchSelectionError("NON_CANONICAL_ARTIFACT") from exc
    return hashlib.sha256(raw).hexdigest()


SELECTOR_SPEC_ID = content_hash(SPEC)


def _mapping(value: Any, name: str, keys: set[str]) -> dict:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ResearchSelectionError("INVALID_" + name + "_FIELDS")
    return copy.deepcopy(dict(value))


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ResearchSelectionError("INVALID_" + name)
    return value


def _hash(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise ResearchSelectionError("INVALID_" + name)
    return value


def _number(value: Any, name: str, *, probability: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResearchSelectionError("INVALID_" + name)
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ResearchSelectionError("INVALID_" + name) from exc
    if not math.isfinite(result) or (probability and not 0 <= result <= 1):
        raise ResearchSelectionError("INVALID_" + name)
    return result


def _time(value: Any, name: str) -> datetime:
    _text(value, name)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchSelectionError("INVALID_" + name) from exc
    if result.tzinfo is None or result.utcoffset() != timezone.utc.utcoffset(result):
        raise ResearchSelectionError("UTC_REQUIRED_" + name)
    return result


def _target(value: Any) -> dict:
    result = _mapping(value, "TARGET", _TARGET_KEYS)
    for key in _TARGET_KEYS - {"line", "starts_at_utc"}:
        _text(result[key], "TARGET_" + key.upper())
    product, side = result["product"], result["side"]
    if product not in {"winner", "spread", "total"}:
        raise ResearchSelectionError("UNSUPPORTED_PRODUCT")
    if side not in ({"over", "under"} if product == "total" else {"home", "away"}):
        raise ResearchSelectionError("INVALID_TARGET_SIDE")
    if product == "winner":
        if result["line"] is not None:
            raise ResearchSelectionError("WINNER_LINE_MUST_BE_NULL")
    else:
        _number(result["line"], "TARGET_LINE")
    _time(result["starts_at_utc"], "EVENT_START")
    return result


def target_id(target: Mapping[str, Any]) -> str:
    """Concrete event, side, line, period and settlement identity."""
    return content_hash(_target(target))


def target_family(target: Mapping[str, Any]) -> dict:
    checked = _target(target)
    return {key: checked[key] for key in
            ("league", "product", "period", "settlement_rules_id")}


def _probabilities(value: Any) -> tuple[dict, bool]:
    result = _mapping(value, "PROBABILITIES", _OUTCOMES)
    for key, number in result.items():
        if number is not None:
            _number(number, "PROBABILITY_" + key.upper(), probability=True)
    complete = all(number is not None for number in result.values())
    if sum(number for number in result.values() if number is not None) > 1 + 1e-9:
        raise ResearchSelectionError("PROBABILITY_MASS_EXCEEDS_ONE")
    if complete and not math.isclose(sum(result.values()), 1.0, rel_tol=0, abs_tol=1e-9):
        raise ResearchSelectionError("PROBABILITY_MASS_MUST_SUM_TO_ONE")
    return result, complete


def _forecast_payload(payload: Any) -> dict:
    result = _mapping(payload, "FORECAST", _FORECAST_KEYS)
    if result["schema"] != "research-forecast-v1":
        raise ResearchSelectionError("UNSUPPORTED_FORECAST_SCHEMA")
    _hash(result["procedure_id"], "PROCEDURE_ID")
    _hash(result["input_snapshot_sha256"], "INPUT_SNAPSHOT_SHA256")
    _target(result["target"])
    _probabilities(result["probabilities"])
    cutoff = _time(result["forecast_cutoff_utc"], "FORECAST_CUTOFF")
    created = _time(result["forecast_created_at_utc"], "FORECAST_CREATED")
    if cutoff > created:
        raise ResearchSelectionError("FORECAST_CUTOFF_AFTER_CREATION")
    return result


def seal_forecast(payload: Mapping[str, Any]) -> dict:
    """Wrap upstream facts with a reproducible identity, without certifying them."""
    result = _forecast_payload(payload)
    return {**result, "forecast_id": content_hash(result)}


def _forecast(value: Any) -> dict:
    result = _mapping(value, "SEALED_FORECAST", _FORECAST_KEYS | {"forecast_id"})
    claimed = _hash(result.pop("forecast_id"), "FORECAST_ID")
    payload = _forecast_payload(result)
    if content_hash(payload) != claimed:
        raise ResearchSelectionError("FORECAST_ID_MISMATCH")
    return {**payload, "forecast_id": claimed}


def selector_config_artifact(config: Mapping[str, Any]) -> dict:
    """Canonical protocol-bound configuration object for the artifact store."""
    result = _mapping(config, "CONFIG", _CONFIG_KEYS)
    if result["schema"] != "research-selector-config-v1":
        raise ResearchSelectionError("UNSUPPORTED_CONFIG_SCHEMA")
    if result["objective"] != "unconditional_win":
        raise ResearchSelectionError("UNSUPPORTED_SELECTION_OBJECTIVE")
    _number(result["threshold"], "THRESHOLD", probability=True)
    if type(result["require_quality_receipt"]) is not bool:
        raise ResearchSelectionError("INVALID_REQUIRE_QUALITY_RECEIPT")
    return {"selector_spec_id": SELECTOR_SPEC_ID, "config": result}


def selector_config_id(config: Mapping[str, Any]) -> str:
    return content_hash(selector_config_artifact(config))


def seal_quality_receipt(payload: Mapping[str, Any]) -> dict:
    """Bind upstream diagnostic findings; this is not a validation certificate."""
    result = _mapping(payload, "QUALITY_RECEIPT", _QUALITY_KEYS - {"receipt_id"})
    _hash(result["forecast_id"], "QUALITY_FORECAST_ID")
    _hash(result["input_snapshot_sha256"], "QUALITY_INPUT_SNAPSHOT_SHA256")
    _time(result["created_at_utc"], "QUALITY_CREATED")
    for key in ("blocking_reasons", "review_notes"):
        if not isinstance(result[key], list):
            raise ResearchSelectionError("INVALID_QUALITY_" + key.upper())
        for reason in result[key]:
            _text(reason, "QUALITY_REASON")
    return {**result, "receipt_id": content_hash(result)}


def _quality(receipt: Any, forecast: dict, at: datetime) -> tuple[list, list, str | None]:
    if receipt is None:
        return [], ["INPUT_QUALITY_RECEIPT_NOT_PROVIDED"], None
    result = _mapping(receipt, "QUALITY_RECEIPT", _QUALITY_KEYS)
    claimed = _hash(result.pop("receipt_id"), "QUALITY_RECEIPT_ID")
    checked = seal_quality_receipt(result)
    if checked["receipt_id"] != claimed:
        raise ResearchSelectionError("QUALITY_RECEIPT_ID_MISMATCH")
    if (result["forecast_id"] != forecast["forecast_id"] or
            result["input_snapshot_sha256"] != forecast["input_snapshot_sha256"]):
        raise ResearchSelectionError("QUALITY_RECEIPT_BINDING_MISMATCH")
    created = _time(result["created_at_utc"], "QUALITY_CREATED")
    if created < _time(forecast["forecast_created_at_utc"], "FORECAST_CREATED") or created > at:
        raise ResearchSelectionError("QUALITY_RECEIPT_TIME_OUT_OF_RANGE")
    return result["blocking_reasons"], result["review_notes"], claimed


def _qualification(registry: Any, forecast: dict, config_id: str, at_utc: str) -> dict:
    empty = {"eligible": False, "reasons": ["MISSING_VALIDATION_REGISTRY"],
             "record_id": None, "protocol_id": None, "evidence_id": None,
             "reviewer_id": None}
    if registry is None:
        return empty
    # No duck typing: a caller-supplied {eligible: true} is not certification.
    from research.validation_registry import ValidationRegistry
    if type(registry) is not ValidationRegistry:
        raise ResearchSelectionError("VERIFIED_VALIDATION_REGISTRY_REQUIRED")
    result = registry.assess(forecast["procedure_id"], target_family(forecast["target"]),
                             at_utc, selector_config_id=config_id)
    if type(result.eligible) is not bool:
        raise ResearchSelectionError("INVALID_REGISTRY_ASSESSMENT")
    receipt = {key: getattr(result, key) for key in
               ("eligible", "record_id", "protocol_id", "evidence_id", "reviewer_id")}
    receipt["reasons"] = list(result.reasons)
    for reason in receipt["reasons"]:
        _text(reason, "REGISTRY_REASON")
    if receipt["eligible"]:
        for key in ("record_id", "protocol_id", "evidence_id"):
            _hash(receipt[key], "VALIDATION_" + key.upper())
        _text(receipt["reviewer_id"], "VALIDATION_REVIEWER_ID")
        if receipt["reasons"]:
            raise ResearchSelectionError("CONTRADICTORY_REGISTRY_ASSESSMENT")
    elif not receipt["reasons"]:
        receipt["reasons"] = ["VALIDATION_NOT_QUALIFIED"]
    return receipt


def _price_diagnostics(price: Any, forecast: dict, at: datetime, decision_id: str) -> dict:
    diagnostics = {"price_status": "MISSING_PRICE", "price_break_even": None,
                   "estimated_value": None, "estimated_value_basis": "net_units_per_unit_staked",
                   "price_reasons": [], "price_quote": None}
    if price is not None:
        try:
            quote = _mapping(price, "PRICE", {"target_id", "decimal_odds", "quoted_at_utc"})
            if _hash(quote["target_id"], "PRICE_TARGET_ID") != target_id(forecast["target"]):
                raise ResearchSelectionError("PRICE_TARGET_MISMATCH")
            decimal = _number(quote["decimal_odds"], "DECIMAL_ODDS")
            if decimal <= 1:
                raise ResearchSelectionError("DECIMAL_ODDS_MUST_EXCEED_ONE")
            if _time(quote["quoted_at_utc"], "PRICE_QUOTED") > at:
                raise ResearchSelectionError("PRICE_FROM_FUTURE")
            diagnostics.update(price_status="VALID_PRICE", price_quote=quote,
                               price_break_even={"value": 1 / decimal,
                                                 "probability_basis": "conditional_decisive",
                                                 "push_and_void": "stake_refunded"})
            probabilities, complete = _probabilities(forecast["probabilities"])
            if complete:
                diagnostics["estimated_value"] = probabilities["win"] * (decimal - 1) - probabilities["loss"]
            else:
                diagnostics["price_reasons"] = ["EXPECTED_VALUE_REQUIRES_COMPLETE_MASS"]
        except ResearchSelectionError as exc:
            diagnostics.update(price_status="INVALID_PRICE", price_reasons=[str(exc)])
    diagnostics["price_diagnostics_id"] = content_hash({"decision_id": decision_id, **diagnostics})
    return diagnostics


def verify_selection_record(record: Mapping[str, Any]) -> None:
    """Detect edits to a previously emitted decision or its diagnostic appendix.

    Identity verification is not qualification or proof of prospective logging.
    Persist records using the append-only research journal or artifact store.
    """
    if not isinstance(record, Mapping) or not (_PRICE_FIELDS | {"decision_id"}) <= set(record):
        raise ResearchSelectionError("INVALID_SELECTION_RECORD")
    core = {key: value for key, value in record.items()
            if key not in _PRICE_FIELDS and key != "decision_id"}
    claimed = _hash(record["decision_id"], "DECISION_ID")
    if content_hash(core) != claimed:
        raise ResearchSelectionError("DECISION_ID_MISMATCH")
    prices = {key: record[key] for key in _PRICE_FIELDS - {"price_diagnostics_id"}}
    if content_hash({"decision_id": claimed, **prices}) != _hash(record["price_diagnostics_id"], "PRICE_DIAGNOSTICS_ID"):
        raise ResearchSelectionError("PRICE_DIAGNOSTICS_ID_MISMATCH")


def select_research(
    forecast: Mapping[str, Any], config: Mapping[str, Any], *,
    decision_at_utc: str, registry: Any = None, price: Mapping[str, Any] | None = None,
    quality_receipt: Mapping[str, Any] | None = None,
    components: Sequence[Mapping[str, Any]] = (),
    replay_at_utc: str | None = None,
) -> dict:
    """Return an evidence-bound SHADOW decision and separately hashed prices.

    ``threshold`` is required, frozen by the registry's protocol, and applied to
    unconditional win probability. Same-target components are disclosed only;
    a winner probability is never compared with a margin-head sign. The caller
    must persist the returned record append-only to claim chronological logs.
    """
    original = _forecast(forecast)
    policy = _mapping(config, "CONFIG", _CONFIG_KEYS)
    config_id = selector_config_id(policy)
    at = _time(decision_at_utc, "DECISION_AT")
    if replay_at_utc is not None and _time(replay_at_utc, "REPLAY_AT") < at:
        raise ResearchSelectionError("REPLAY_BEFORE_ORIGINAL_DECISION")
    probabilities, complete = _probabilities(original["probabilities"])
    raw_win = probabilities["win"]
    blocks: list[str] = []
    if not complete:
        blocks.append("PROBABILITY_MASS_INCOMPLETE")
    if _time(original["forecast_created_at_utc"], "FORECAST_CREATED") > at:
        blocks.append("FORECAST_FROM_FUTURE")
    if at >= _time(original["target"]["starts_at_utc"], "EVENT_START"):
        blocks.append("PREGAME_DECISION_WINDOW_CLOSED")
    quality_blocks, reviews, quality_id = _quality(quality_receipt, original, at)
    blocks.extend(quality_blocks)
    if policy["require_quality_receipt"] and quality_receipt is None:
        blocks.append("REQUIRED_INPUT_QUALITY_RECEIPT_MISSING")
    qualification = _qualification(registry, original, config_id, decision_at_utc)
    if not qualification["eligible"]:
        blocks.extend(qualification["reasons"])
    comparable = []
    noncomparable = []
    concrete_target_id = target_id(original["target"])
    if isinstance(components, (str, bytes)) or not isinstance(components, Sequence):
        raise ResearchSelectionError("INVALID_COMPONENTS")
    for sibling in components:
        sibling = _forecast(sibling)
        if _time(sibling["forecast_created_at_utc"], "COMPONENT_CREATED") > at:
            raise ResearchSelectionError("COMPONENT_FROM_FUTURE")
        if target_id(sibling["target"]) != concrete_target_id:
            noncomparable.append(sibling["forecast_id"])
            continue
        comparable.append({"forecast_id": sibling["forecast_id"],
                           "raw_probability": sibling["probabilities"]["win"]})
    if noncomparable:
        reviews.append("COMPONENT_TARGET_NOT_COMPARABLE")
    blocks = sorted(set(blocks))
    eligible = not blocks
    selected = eligible and raw_win >= policy["threshold"]
    decisive_mass = (probabilities["win"] + probabilities["loss"]) if complete else None
    core = {
        "schema": "research-selection-v1", "selector_spec_id": SELECTOR_SPEC_ID,
        "selector_config_id": config_id, "forecast_id": original["forecast_id"],
        "procedure_id": original["procedure_id"], "target_id": concrete_target_id,
        "target": copy.deepcopy(original["target"]), "decision_at_utc": decision_at_utc,
        "replay_at_utc": replay_at_utc,
        "execution_mode": "RETROSPECTIVE_DIAGNOSTIC" if replay_at_utc else "UNREGISTERED_RESEARCH",
        "prospective_registration_verified": False,
        "objective": "unconditional_win", "threshold": policy["threshold"],
        "raw_probability": raw_win, "raw_probabilities": probabilities,
        "selection_probability": raw_win if eligible else None,
        "confidence_band": None,
        "confidence_band_status": "NO_QUALIFIED_BAND_DEFINITION",
        "decisive_probability": (raw_win / decisive_mass) if decisive_mass else None,
        "selection_decision": "SHADOW_PICK" if selected else "NO_PICK",
        "decision_class": ("SHADOW_SELECTED" if selected else
                           "ELIGIBLE_NOT_SELECTED" if eligible else "BLOCKED"),
        "blocking_reasons": blocks, "review_notes": sorted(set(reviews)),
        "quality_receipt_id": quality_id, "validation": qualification,
        "same_target_components": sorted(comparable, key=lambda item: item["forecast_id"]),
        "noncomparable_component_ids": sorted(set(noncomparable)),
        "research_mode": "SHADOW", "publication_allowed": False,
        "official_release": False, "action_authority": False, "wagering_status": "OFF",
    }
    core["decision_id"] = content_hash(core)
    return {**core, **_price_diagnostics(price, original, at, core["decision_id"])}
