"""Shared internals for the per-sport margin adapters (research-only).

Everything here supports the adapters in this package; the public entry point
is ``pipelines.margins.get_adapter``. No adapter mutates its inputs, every
emitted record goes through ``models.common.margins.margin_quote_record`` and
keeps ``research_only=True`` / ``action_authority=False``.
"""
from __future__ import annotations

import copy
import hashlib
import json

import numpy as np
from scipy.stats import norm

from models.common.margins import distribution_id_for, validate_record

# ---------------------------------------------------------------------------
# Error codes (stable strings; carried on MarginAdapterError.code)
# ---------------------------------------------------------------------------
MARGIN_POOL_MODEL_MISMATCH = "MARGIN_POOL_MODEL_MISMATCH"
MISSING_MARGIN_HEAD = "MISSING_MARGIN_HEAD"
ARM_NOT_SELECTED_CONSISTENT = "ARM_NOT_SELECTED_CONSISTENT"
SIGMA_SEGMENT_MISSING = "SIGMA_SEGMENT_MISSING"
SEGMENT_FALLBACK = "SEGMENT_FALLBACK"
SIGMA_SPORT_MISMATCH = "SIGMA_SPORT_MISMATCH"
SIGMA_REQUIRED = "SIGMA_REQUIRED"
SIGMA_PROVENANCE_NOT_OOF = "SIGMA_PROVENANCE_NOT_OOF"
SOURCE_MODEL_IDENTITY_REQUIRED = "SOURCE_MODEL_IDENTITY_REQUIRED"
UNSUPPORTED_SETTLEMENT = "UNSUPPORTED_SETTLEMENT"
UNSUPPORTED_1X2_ONLY = "UNSUPPORTED_1X2_ONLY"


class MarginAdapterError(ValueError):
    """Adapter failure with a stable machine-readable ``.code``."""

    def __init__(self, code: str, message: str):
        self.code = str(code)
        super().__init__(f"{self.code}: {message}")


class UnsupportedProductError(MarginAdapterError):
    """Raised when a league/model fundamentally cannot quote the product."""


# ---------------------------------------------------------------------------
# Integer-normal margin distribution (adapter-side; core has no constructor
# for "continuous model, integer-settled margin" yet). Used by NBA/WNBA/NHL:
# basketball and hockey margins are integers, so integer lines carry real push
# mass. M = round(N(mu, sigma)); CDF/push via continuity correction.
# ---------------------------------------------------------------------------
class IntegerNormalMargin:
    """Continuity-corrected normal over integer margins (HOME orientation).

    cdf(m)      = Phi((floor(m) + 0.5 - mu) / sigma)   (inclusive at integers)
    push_mass(k)= Phi((k + 0.5 - mu)/sigma) - Phi((k - 0.5 - mu)/sigma), k integer
    push_mass(m)= 0 for non-integer m.
    """

    def __init__(self, mu: float, sigma: float, provenance: dict):
        sigma = float(sigma)
        if not np.isfinite(sigma) or sigma <= 0:
            raise ValueError("MARGIN_SIGMA_INVALID")
        if not np.isfinite(float(mu)):
            raise ValueError("MARGIN_MU_INVALID")
        self.mu = float(mu)
        self.sigma = sigma
        self.provenance = dict(provenance or {})
        self.distribution_id = distribution_id_for(
            "integer_normal", {"mu": self.mu, "sigma": self.sigma}, self.provenance
        )

    def cdf(self, margin: float) -> float:
        m = float(margin)
        return float(norm.cdf((np.floor(m) + 0.5 - self.mu) / self.sigma))

    def push_mass(self, margin: float) -> float:
        m = float(margin)
        if not m.is_integer():
            return 0.0
        hi = norm.cdf((m + 0.5 - self.mu) / self.sigma)
        lo = norm.cdf((m - 0.5 - self.mu) / self.sigma)
        return float(hi - lo)

    def sample(self, n: int, seed: int) -> np.ndarray:
        n = int(n)
        if n <= 0:
            raise ValueError("MARGIN_SAMPLE_N_INVALID")
        rng = np.random.default_rng(seed)
        return np.round(rng.normal(self.mu, self.sigma, n))


# ---------------------------------------------------------------------------
# Record finalization: margin_quote_record does not accept extra warnings or
# limitations, so adapter labels (e.g. SEGMENT_FALLBACK, NHL uncalibrated) are
# merged here and record_sha256 recomputed exactly as emit._record_hash does,
# keeping validate_record green.
# ---------------------------------------------------------------------------
def _canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def finalize_record(record: dict, extra_warnings=(), extra_limitations=()) -> dict:
    rec = copy.deepcopy(record)
    for w in extra_warnings:
        if w not in rec["warnings"]:
            rec["warnings"].append(str(w))
    for lim in extra_limitations:
        if lim not in rec["limitations"]:
            rec["limitations"].append(str(lim))
    body = {k: v for k, v in rec.items() if k != "record_sha256"}
    rec["record_sha256"] = hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()
    # A re-sealed record must still satisfy the schema: adapters can never
    # emit a structurally invalid record, even after label/limitation merges.
    validate_record(rec)
    return rec


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------
def require_sigma(sigma_provenance: dict, sport: str) -> float:
    """Pull a sport-matched positive sigma out of a provenance mapping.

    Mirrors the provenance contract of
    models.common.margins.sigma.estimate_sigma: the sigma must be
    demonstrably out-of-fold — provenance carries oof=True plus
    window_start/window_end — and must not be labeled in-sample.
    Fabricated, in-sample, or window-less provenance fails closed with
    SIGMA_PROVENANCE_NOT_OOF.
    """
    if not isinstance(sigma_provenance, dict):
        raise MarginAdapterError(
            SIGMA_REQUIRED, f"{sport}: sigma_provenance mapping is required"
        )
    prov_sport = sigma_provenance.get("sport")
    if prov_sport is None:
        raise MarginAdapterError(
            SIGMA_REQUIRED, f"{sport}: sigma_provenance must carry a 'sport' label"
        )
    if str(prov_sport) != sport:
        raise MarginAdapterError(
            SIGMA_SPORT_MISMATCH,
            f"sigma provenance sport '{prov_sport}' cannot back a {sport} quote",
        )
    sigma = sigma_provenance.get("sigma")
    if sigma is None or not np.isfinite(float(sigma)) or float(sigma) <= 0:
        raise MarginAdapterError(
            SIGMA_REQUIRED,
            f"{sport}: sigma_provenance must carry a positive finite 'sigma' "
            "(from models.common.margins.estimate_sigma, OOF/chronological only)",
        )
    if (
        sigma_provenance.get("label_in_sample") is True
        or sigma_provenance.get("oof") is not True
        or "window_start" not in sigma_provenance
        or "window_end" not in sigma_provenance
    ):
        raise MarginAdapterError(
            SIGMA_PROVENANCE_NOT_OOF,
            f"{sport}: sigma provenance must demonstrate chronological "
            "out-of-fold origin (oof=True with window_start/window_end, per "
            "models.common.margins.estimate_sigma); in-sample or window-less "
            "sigmas cannot back a quote",
        )
    return float(sigma)


def require_event(event) -> dict:
    if not isinstance(event, dict) or "event_id" not in event:
        raise MarginAdapterError(
            "MARGIN_RECORD_EVENT_ID_REQUIRED",
            "an event dict with 'event_id' is required for the margin quote record",
        )
    return event


def require_source_identity(model_id, artifact_sha256, sport: str):
    if not model_id or not artifact_sha256:
        raise MarginAdapterError(
            SOURCE_MODEL_IDENTITY_REQUIRED,
            f"{sport}: model_id and artifact_sha256 are both required",
        )
    return str(model_id), str(artifact_sha256)


def finite_margin(value, sport: str) -> float:
    if value is None or not np.isfinite(float(value)):
        raise MarginAdapterError(
            MISSING_MARGIN_HEAD, f"{sport}: margin prediction is missing or non-finite"
        )
    return float(value)


def margin_from_ridge_head(head: dict, values) -> float:
    """Apply a frozen standardized ridge head (no fitting at inference).

    Accepts both repo packings: models/current/linear.py ('impute','mean',
    'scale','coefficient','intercept') and models/nfl/contextual/model.py
    ('impute','center','scale','coefficient','intercept'). None -> impute.
    """
    x = np.asarray([np.nan if v is None else v for v in values], dtype=float)
    coef = np.asarray(head["coefficient"], dtype=float)
    if x.shape[0] != coef.shape[0] or np.isinf(x).any():
        raise ValueError("FEATURE_SCHEMA_OR_INFINITY")
    center = head.get("mean", head.get("center"))
    x = np.where(np.isnan(x), np.asarray(head["impute"], dtype=float), x)
    z = (x - np.asarray(center, dtype=float)) / np.asarray(head["scale"], dtype=float)
    return float(np.dot(z, coef) + float(head["intercept"]))
