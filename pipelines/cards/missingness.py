"""Bind missing-data diagnostics to one forecast without changing numerical/RNG identity."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping

OBSERVATION_STATES = (
    "VERIFIED_OBSERVATION", "VERIFIED_ABSENCE", "NOT_YET_PUBLISHED",
    "ACQUISITION_FAILURE", "UNRESOLVED_IDENTITY_OR_COVERAGE",
)
REQUIRED_TESTS = (
    "metadata_invariance", "missingness_sensitivity", "source_failure",
    "identity_and_ordering", "duplicate_protection", "partial_run_isolation",
    "training_inference_parity",
)


def content_digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                     allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def seal_audit(*, league, event_id, model_id, products, forecast, details):
    """Receipt integrity does not confer release or selection eligibility."""
    if not all(isinstance(x, str) and x.strip() for x in (league, event_id, model_id)):
        raise ValueError("MISSINGNESS_SCOPE_REQUIRED")
    if (not isinstance(products, (tuple, list)) or not products or
            not all(isinstance(p, str) and p.strip() for p in products) or
            len(set(products)) != len(products)):
        raise ValueError("MISSINGNESS_PRODUCT_SCOPE_REQUIRED")
    if not isinstance(forecast, dict) or not forecast or not isinstance(details, dict) or not details:
        raise ValueError("MISSINGNESS_FORECAST_AND_DETAILS_REQUIRED")
    body = {"schema": "sports.missingness_audit.v1", "league": league, "event_id": event_id,
            "model_id": model_id, "products": sorted(products), "forecast_sha256": content_digest(forecast),
            "details": details, "release_status": "HOLD_PENDING_SCOPE_REVIEW", "action_authority": False}
    return {**body, "receipt_sha256": content_digest(body)}


def verify_audit(receipt, *, league, event_id, model_id, products, forecast):
    if not isinstance(receipt, dict):
        return False
    try:
        expected = seal_audit(league=league, event_id=event_id, model_id=model_id,
                              products=products, forecast=forecast, details=receipt["details"])
        # Compare canonical encodings. Python equality treats false and 0 as equal.
        return content_digest(receipt) == content_digest(expected)
    except (TypeError, ValueError, KeyError, OverflowError):
        return False


def observation_state(*, acquired, published, identity_resolved, complete, count):
    """Classify evidence before a sport-specific feature transform. Count alone cannot prove absence."""
    if not all(type(v) is bool for v in (acquired, published, identity_resolved, complete)):
        raise ValueError("MISSINGNESS_EXPLICIT_EVIDENCE_REQUIRED")
    if count is not None and (type(count) is not int or count < 0):
        raise ValueError("MISSINGNESS_INVALID_COUNT")
    if not acquired:
        return "ACQUISITION_FAILURE"
    if not published:
        return "NOT_YET_PUBLISHED"
    if not identity_resolved or not complete or count is None:
        return "UNRESOLVED_IDENTITY_OR_COVERAGE"
    return "VERIFIED_OBSERVATION" if count else "VERIFIED_ABSENCE"


def factorial_attribution(*, original, sporting_only, reporting_only, refreshed):
    """Four numerical evaluations of one fixed head, fit, units, law and cutoff.

    These are interventions on inputs. A mixed corner outside model support must
    be omitted by the caller and is reported as unresolved, never as zero.
    """
    values = (original, sporting_only, reporting_only, refreshed)
    if any(x is not None and (type(x) not in (int, float) or not math.isfinite(x)) for x in values):
        raise ValueError("MISSINGNESS_NONFINITE_HEAD")
    if original is None or refreshed is None:
        raise ValueError("MISSINGNESS_ENDPOINTS_REQUIRED")
    delta = refreshed - original
    sport = None if sporting_only is None else sporting_only - original
    reporting = None if reporting_only is None else reporting_only - original
    interaction = None if sport is None or reporting is None else delta - sport - reporting
    return {"method": "FIXED_MODEL_FOUR_CORNERS", "total_change": delta, "sporting": sport,
            "missingness_imputation": reporting, "interaction": interaction,
            "decomposition_complete": interaction is not None}
