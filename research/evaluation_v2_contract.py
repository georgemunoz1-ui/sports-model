"""Additive v2 research row validation; does not register, grade or authorize.
A byte match verifies a reference, not independent source or registration truth.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_PATH = Path(__file__).with_name("schemas") / "evaluation_row.v2.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
CLASSES = {
    "BINARY_HA": {"HOME", "AWAY"},
    "REGULATION_HDA": {"HOME", "DRAW", "AWAY"},
    "SETTLEMENT_3": {"WIN", "PUSH", "LOSS"},
    "SETTLEMENT_5": {"WIN", "HALF_WIN", "PUSH", "HALF_LOSS", "LOSS"},
}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def stamp(value):
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(t.tzinfo is not None, "TIMEZONE_REQUIRED")
    return t.astimezone(timezone.utc)


def finite(value):
    return type(value) in (float, int) and math.isfinite(value)


def verify_distribution_bytes(distribution, root):
    require(root is not None, "DISTRIBUTION_ROOT_REQUIRED")
    root = Path(root).resolve(strict=True)
    relative = Path(distribution["path"])
    require(not relative.is_absolute() and ".." not in relative.parts,
            "DISTRIBUTION_PATH_OUTSIDE_ROOT")
    path = (root / relative).resolve(strict=True)
    require(path.is_relative_to(root) and path.is_file(),
            "DISTRIBUTION_PATH_OUTSIDE_ROOT")
    with path.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    require(actual == distribution["sha256"], "DISTRIBUTION_HASH_MISMATCH")


def validate_row(row, *, artifact_root=None):
    """Check local structure and chronology, never confer canonical eligibility."""
    VALIDATOR.validate(row)
    require(row["evidence_scope"] != "REMOTE_DURABLE_PROSPECTIVE",
            "CANONICAL_ATTESTATION_INTEGRATION_REQUIRED")
    require(row["registration_receipt_sha256"] is None,
            "UNVERIFIED_REGISTRATION_REFERENCE")
    start = stamp(row["scheduled_start_utc"])
    cutoff = row["forecast_cutoff_utc"]
    training = row["training_cutoff_utc"]
    graded = row["graded_at_utc"]
    if cutoff is not None:
        require(stamp(cutoff) < start, "FORECAST_NOT_PRESTART")
    if training is not None:
        require(cutoff is not None and stamp(training) <= stamp(cutoff),
                "TRAINING_AFTER_FORECAST_CUTOFF")
    target = row["target"]
    family, side, line = target["family"], target["side"], target["line"]
    if line is not None:
        require(finite(line), "NONFINITE_LINE")
    if family == "SPREAD":
        require(side in {"HOME", "AWAY"} and line is not None,
                "SPREAD_CONTRACT_REQUIRED")
    elif family == "TOTAL":
        require((side in {"OVER", "UNDER"} and line is not None and line >= 0)
                or (side == "NONE" and line is None), "TOTAL_CONTRACT_REQUIRED")
    elif family == "WINNER":
        require(side in {"HOME", "AWAY", "NONE"} and line is None,
                "WINNER_CONTRACT_REQUIRED")
    elif family == "REGULATION_1X2":
        require(side in {"HOME", "AWAY", "DRAW", "NONE"} and line is None,
                "REGULATION_CONTRACT_REQUIRED")
    else:
        require(side == "NONE" and line is None, "DISTRIBUTION_CONTRACT_REQUIRED")
    for key in ("actuals", "point_predictions"):
        require(all(finite(v) for v in row[key].values()), "NONFINITE_" + key.upper())
    status, outcome = row["outcome_status"], row["outcome_value"]
    if status == "UNRESOLVED":
        require(graded is None and row["grade_record_hash"] is None
                and outcome is None and not row["actuals"], "UNRESOLVED_HAS_GRADE")
    else:
        require(graded is not None and row["grade_record_hash"] is not None,
                "GRADE_REFERENCE_REQUIRED")
        if cutoff is not None:
            require(stamp(graded) >= stamp(cutoff), "GRADE_BEFORE_FORECAST_CUTOFF")
        if status != "VOID":
            require(stamp(graded) >= start, "GRADE_BEFORE_START")
        if status in {"VOID"}:
            require(outcome is None, "VOID_HAS_SCOREABLE_OUTCOME")
        elif status in {"PUSH", "HALF_WIN", "HALF_LOSS"}:
            require(outcome == status, "SETTLEMENT_STATUS_OUTCOME_MISMATCH")
        else:
            require(outcome is not None or bool(row["actuals"]), "ACTUAL_REQUIRED")
    basis, probs = row["probability_basis"], row["probabilities"]
    distribution = row["distribution"]
    if row["forecast_status"] != "GENERATED":
        require(bool(row["reason_code"]), "REFUSAL_REASON_REQUIRED")
        require(all(row[k] is None for k in ("fitted_state_hash", "forecast_output_hash",
                    "probability_basis", "probabilities", "distribution"))
                and not row["point_predictions"], "REFUSAL_HAS_FORECAST")
        return row
    require(cutoff is not None and training is not None
            and row["forecast_output_hash"] is not None
            and row["fitted_state_hash"] is not None, "GENERATED_PROVENANCE_REQUIRED")
    require((basis is None) == (probs is None), "PROBABILITY_BASIS_MISMATCH")
    require(probs is not None or distribution is not None or bool(row["point_predictions"]),
            "GENERATED_WITHOUT_PREDICTION")
    if probs is not None:
        require(set(probs) == CLASSES[basis] and all(finite(v) and 0 <= v <= 1
                for v in probs.values()) and math.isclose(sum(probs.values()), 1.0,
                rel_tol=0, abs_tol=1e-9), "INVALID_PROBABILITY_SIMPLEX")
        if basis == "BINARY_HA":
            require(family == "WINNER", "BINARY_TARGET_MISMATCH")
        elif basis == "REGULATION_HDA":
            require(family == "REGULATION_1X2", "HDA_TARGET_MISMATCH")
        else:
            require(family in {"WINNER", "SPREAD", "TOTAL"} and
                    (family == "WINNER" or line is not None), "SETTLEMENT_TARGET_MISMATCH")
        if status not in {"UNRESOLVED", "VOID"}:
            require(outcome in CLASSES[basis], "OUTCOME_OUTSIDE_BASIS")
            decisive = {"HOME", "AWAY", "DRAW", "WIN", "LOSS"}
            require(status != "DECISIVE" or outcome in decisive,
                    "DECISIVE_STATUS_OUTCOME_MISMATCH")
    if distribution is not None:
        verify_distribution_bytes(distribution, artifact_root)
        # Support, settlement semantics and probability derivation are adapter work.
    return row


def population_key(row):
    t = row["target"]
    return (row["league"], row["season"], row["event_id"],
            t["family"], t["period"], t["side"], t["line"], t["settlement_rule"])


def pair_population(control, challenger, *, artifact_root=None):
    """Retain all rows, including refusals and non-decisive outcomes; never intersect silently."""
    def index(rows):
        out = {}
        for row in rows:
            validate_row(row, artifact_root=artifact_root)
            key = population_key(row)
            require(key not in out, "DUPLICATE_POPULATION_KEY")
            out[key] = row
        return out
    a, b = index(control), index(challenger)
    require(bool(a) and a.keys() == b.keys(), "PAIR_POPULATION_MISMATCH")
    paired = []
    for key, left in a.items():
        right = b[key]
        require(stamp(left["scheduled_start_utc"]) == stamp(right["scheduled_start_utc"]),
                "PAIR_START_MISMATCH")
        require(all(left[k] == right[k] for k in ("outcome_status", "outcome_value", "actuals")),
                "PAIR_OUTCOME_MISMATCH")
        if left["forecast_status"] == right["forecast_status"] == "GENERATED":
            require(stamp(left["forecast_cutoff_utc"]) == stamp(right["forecast_cutoff_utc"]),
                    "PAIR_CUTOFF_MISMATCH")
            require(left["probability_basis"] == right["probability_basis"],
                    "PAIR_PROBABILITY_BASIS_MISMATCH")
        paired.append((left, right))
    return paired
