"""Read-only adapter infrastructure for frozen forecast/grade evaluation.

This module deliberately has no registry writer, canonical-ledger writer, market layer,
or action/recommendation surface. It only translates already-frozen forecast bytes and
append-only grade records into a common evaluation-row contract.
"""
from __future__ import annotations

from dataclasses import dataclass
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

from research import offline_benchmark as B

ROW_SCHEMA_VERSION = "evaluation_row.v1"
MANIFEST_SCHEMA_VERSION = "frozen_evaluation_manifest.v1"
GRADE_SCHEMA_VERSION = "outcome_grade.v1"

EVIDENCE_SCOPES = {
    "LOCAL_DIAGNOSTIC",
    "REMOTE_DURABLE_PROSPECTIVE",
    "UNGRADABLE",
    "QUARANTINED_IDENTITY_FAILURE",
    "POSTPONED",
}
EVALUATABLE_SCOPES = {"LOCAL_DIAGNOSTIC", "REMOTE_DURABLE_PROSPECTIVE"}
TERMINAL_EXCLUDED_SCOPES = {
    "UNGRADABLE",
    "QUARANTINED_IDENTITY_FAILURE",
    "POSTPONED",
}

SOURCE_SCOPE_TO_EVALUATION_SCOPE = {
    "LOCAL_ONLY": "LOCAL_DIAGNOSTIC",
    "LOCAL_ONLY_PENDING_REMOTE_MIRROR": "LOCAL_DIAGNOSTIC",
    "LOCAL_DIAGNOSTIC": "LOCAL_DIAGNOSTIC",
    "REMOTE_DURABLE": "REMOTE_DURABLE_PROSPECTIVE",
    "REMOTE_REGISTERED": "REMOTE_DURABLE_PROSPECTIVE",
    "REMOTE_DURABLE_PROSPECTIVE": "REMOTE_DURABLE_PROSPECTIVE",
}

ALLOWED_QUANTILE_KEYS = {
    "p05": 0.05,
    "p10": 0.10,
    "p25": 0.25,
    "p50": 0.50,
    "p75": 0.75,
    "p90": 0.90,
    "p95": 0.95,
}


class EvaluationError(ValueError):
    """Fail-closed error for malformed or incompatible frozen evidence."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json_readonly(path: Path) -> tuple[Any, str]:
    data = path.read_bytes()
    before = sha256_bytes(data)
    try:
        value = json.loads(data.decode("utf-8"))
    except Exception as exc:  # pragma: no cover - exact decoder error is not contract-relevant
        raise EvaluationError(f"invalid JSON: {path}: {exc}") from exc
    after = sha256_file(path)
    if before != after:
        raise EvaluationError(f"source mutated while reading: {path}")
    return value, before


def load_jsonl_readonly(path: Path) -> tuple[list[dict[str, Any]], str]:
    data = path.read_bytes()
    before = sha256_bytes(data)
    records: list[dict[str, Any]] = []
    for line_no, raw in enumerate(data.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise EvaluationError(f"invalid JSONL {path}:{line_no}: {exc}") from exc
        if not isinstance(record, dict):
            raise EvaluationError(f"JSONL row must be object: {path}:{line_no}")
        if not record.get("grade_record_hash"):
            record = dict(record)
            record["grade_record_hash"] = digest(record)
            record["grade_record_hash_provenance"] = "DERIVED_CANONICAL_GRADE_RECORD"
        records.append(record)
    after = sha256_file(path)
    if before != after:
        raise EvaluationError(f"source mutated while reading: {path}")
    return records, before


def require_sha256(value: str, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise EvaluationError(f"{field} must be lowercase sha256")
    return value


def finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EvaluationError(f"{field} must be finite numeric")
    return float(value)


def probability(value: Any, field: str) -> float:
    x = finite_number(value, field)
    if not 0.0 <= x <= 1.0:
        raise EvaluationError(f"{field} outside [0,1]")
    return x


def binary_probabilities(home: Any, away: Any | None = None) -> dict[str, float]:
    ph = probability(home, "home_win")
    pa = 1.0 - ph if away is None else probability(away, "away_win")
    if not math.isclose(ph + pa, 1.0, abs_tol=1e-9):
        raise EvaluationError("binary probabilities do not sum to one")
    return {"home_win": ph, "away_win": pa}


def multiclass_probabilities(home: Any, draw: Any, away: Any) -> dict[str, float]:
    p = {
        "home_win": probability(home, "home_win"),
        "draw": probability(draw, "draw"),
        "away_win": probability(away, "away_win"),
    }
    if not math.isclose(sum(p.values()), 1.0, abs_tol=1e-9):
        raise EvaluationError("H/D/A probabilities do not sum to one")
    return p


def normalize_quantiles(source: dict[str, Any] | None) -> dict[str, float | None]:
    out = {key: None for key in ALLOWED_QUANTILE_KEYS}
    if not source:
        return out
    for key in out:
        if key in source and source[key] is not None:
            out[key] = finite_number(source[key], f"quantiles.{key}")
    present = [out[k] for k in out if out[k] is not None]
    if present and present != sorted(present):
        raise EvaluationError("quantiles cross")
    return out


def quantiles_from_prefix(record: dict[str, Any], prefix: str) -> dict[str, float | None]:
    return normalize_quantiles({k: record.get(f"{prefix}_{k}") for k in ALLOWED_QUANTILE_KEYS})


def event_date_local_from_grade_or_start(grade: dict[str, Any], start_utc: str) -> str:
    value = grade.get("event_date_local")
    if value:
        import datetime as dt
        dt.date.fromisoformat(value)
        return value
    return B.instant(start_utc).date().isoformat()


def structural_pit_check(cutoff: str, start: str, graded_at: str) -> None:
    if not B.instant(cutoff) < B.instant(start):
        raise EvaluationError("forecast cutoff must precede scheduled start")
    if B.instant(graded_at) < B.instant(start):
        raise EvaluationError("grade timestamp precedes scheduled start")


def source_scope(entry: dict[str, Any], payload: dict[str, Any] | None = None) -> str:
    raw = entry.get("source_evidence_scope") or entry.get("registration_scope")
    if raw is None and payload:
        raw = payload.get("registration_scope")
        if raw is None and isinstance(payload.get("governance"), dict):
            raw = payload["governance"].get("registration_scope")
    if raw not in SOURCE_SCOPE_TO_EVALUATION_SCOPE:
        raise EvaluationError(f"unsupported/unknown source evidence scope: {raw!r}")
    return SOURCE_SCOPE_TO_EVALUATION_SCOPE[raw]


def enforce_requested_scope(row_scope: str, requested_scope: str, *, allow_combined_descriptive: bool = False) -> None:
    if requested_scope == "COMBINED_DESCRIPTIVE":
        if not allow_combined_descriptive:
            raise EvaluationError("combined scope requires --allow-combined-descriptive")
        if row_scope not in EVALUATABLE_SCOPES:
            raise EvaluationError(f"non-evaluable row scope in combined report: {row_scope}")
        return
    if row_scope != requested_scope:
        raise EvaluationError(f"evidence scope mismatch: row={row_scope}, requested={requested_scope}")


def grade_status(record: dict[str, Any]) -> str:
    status = record.get("evidence_scope") or record.get("status") or "LOCAL_DIAGNOSTIC"
    if status == "GRADED":
        status = record.get("evaluation_scope", "LOCAL_DIAGNOSTIC")
    if status not in EVIDENCE_SCOPES:
        raise EvaluationError(f"unknown grade/evidence status: {status}")
    return status


def score_actuals(grade: dict[str, Any]) -> dict[str, float]:
    home = finite_number(grade["home_score"], "grade.home_score")
    away = finite_number(grade["away_score"], "grade.away_score")
    return {"home_score": home, "away_score": away, "home_margin": home - away, "total": home + away}


def make_row(*, league: str, event_id: str, event_date_local: str, forecast_output_hash: str,
             grade_record_hash: str, model_id: str, model_arm_id: str, experiment_id: str | None,
             evidence_scope: str, canonical_prospective_eligible: bool, forecast_cutoff_utc: str,
             scheduled_start_utc: str, graded_at_utc: str, outcome_type: str, outcome_value: Any,
             probabilities: dict[str, float], point_predictions: dict[str, float | None] | None,
             quantiles: dict[str, dict[str, float | None]] | None, actuals: dict[str, float],
             data_quality: dict[str, Any] | None, target_contract: dict[str, Any],
             score_target_compatible: bool, score_metrics_excluded_reason: str | None,
             pairing: dict[str, Any] | None = None) -> dict[str, Any]:
    structural_pit_check(forecast_cutoff_utc, scheduled_start_utc, graded_at_utc)
    require_sha256(forecast_output_hash, "forecast_output_hash")
    require_sha256(grade_record_hash, "grade_record_hash")
    row = {
        "schema_version": ROW_SCHEMA_VERSION, "league": league.upper(), "event_id": str(event_id),
        "event_date_local": event_date_local, "forecast_output_hash": forecast_output_hash,
        "grade_record_hash": grade_record_hash, "model_id": str(model_id), "model_arm_id": str(model_arm_id),
        "experiment_id": experiment_id, "evidence_scope": evidence_scope,
        "canonical_prospective_eligible": bool(canonical_prospective_eligible),
        "forecast_cutoff_utc": forecast_cutoff_utc, "scheduled_start_utc": scheduled_start_utc,
        "graded_at_utc": graded_at_utc, "outcome_type": outcome_type, "outcome_value": outcome_value,
        "probabilities": probabilities, "point_predictions": point_predictions or {}, "quantiles": quantiles or {},
        "actuals": actuals, "data_quality": data_quality or {}, "target_contract": target_contract,
        "score_target_compatible": bool(score_target_compatible),
        "score_metrics_excluded_reason": score_metrics_excluded_reason, "pairing": pairing,
    }
    if evidence_scope == "LOCAL_DIAGNOSTIC" and row["canonical_prospective_eligible"]:
        raise EvaluationError("LOCAL_DIAGNOSTIC row cannot be canonical prospective eligible")
    if evidence_scope == "REMOTE_DURABLE_PROSPECTIVE" and not row["canonical_prospective_eligible"]:
        raise EvaluationError("remote-durable prospective row must carry eligibility=true")
    return row


@dataclass(frozen=True)
class Adapted:
    rows: list[dict[str, Any]]
    excluded: list[dict[str, Any]]


class GradeIndex:
    def __init__(self, records: Iterable[dict[str, Any]]):
        self.records = list(records)
        self.by_event: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for rec in self.records:
            league = str(rec.get("league", "")).upper()
            event = str(rec.get("event_id") or rec.get("game_id") or rec.get("canonical_game_id") or "")
            if not league or not event:
                raise EvaluationError("grade row missing league/event identity")
            self.by_event.setdefault((league, event), []).append(rec)

    def one(self, league: str, event_id: str, *, model_id: str | None = None,
            model_arm_id: str | None = None, allow_shared_result_grade: bool = True) -> dict[str, Any]:
        candidates = self.by_event.get((league.upper(), str(event_id)), [])
        if model_id is not None:
            exact = [r for r in candidates if r.get("model_id") == model_id and
                     (model_arm_id is None or r.get("model_arm_id") == model_arm_id or r.get("arm_id") == model_arm_id)]
            if exact:
                candidates = exact
            elif not allow_shared_result_grade:
                candidates = []
        if len(candidates) != 1:
            raise EvaluationError(f"expected exactly one grade for {league}:{event_id} model={model_id} arm={model_arm_id}; found {len(candidates)}")
        return candidates[0]


class BaseAdapter:
    league = "UNKNOWN"
    accepted_artifact_schemas: set[str] = set()

    def validate_entry(self, entry: dict[str, Any]) -> None:
        if str(entry.get("league", "")).upper() != self.league:
            raise EvaluationError(f"manifest league mismatch for {self.league}")
        schema = entry.get("artifact_schema")
        if schema not in self.accepted_artifact_schemas:
            raise EvaluationError(f"unknown {self.league} artifact schema: {schema!r}")
        require_sha256(entry.get("sha256", ""), "manifest artifact sha256")

    def adapt(self, payload: dict[str, Any], entry: dict[str, Any], grades: GradeIndex,
              requested_scope: str, *, exclude_statuses: set[str], fail_on_unexpected_row: bool,
              allow_combined_descriptive: bool) -> Adapted:
        raise NotImplementedError


def exclusion_record(*, league: str, event_id: str, reason: str, status: str,
                     model_id: str | None = None, model_arm_id: str | None = None) -> dict[str, Any]:
    return {"league": league, "event_id": event_id, "model_id": model_id, "model_arm_id": model_arm_id,
            "status": status, "reason": reason}
