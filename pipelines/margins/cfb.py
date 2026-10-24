"""CFB margin adapter for cfb.fbs.elo_form_logit_ridge.v1_0.shadow.

The incumbent CFB model is a logistic winner head plus a ridge margin head
over 10 features (Elo/EWMA/rest/neutral/conference); no cover output exists
today. This adapter maps the ridge margin point prediction to a discrete
football margin distribution (integer margins, key numbers) with a
WEEK-SEGMENTED residual sigma.

sigma_table contract (either form):
  {"buckets": [{"label": "early", "week_min": 2, "week_max": 5,
                "sigma": 12.1, "n": 412, ...}, ...],
   "fallback": {"label": "pooled", "sigma": 13.0, "n": 2400, ...} | None}
or a plain mapping {label: {"week_min":..,"week_max":..,"sigma":..,"n":..},
                    "fallback": {...}}.

Fallback is used ONLY when no bucket covers the requested week, and is always
labeled: warning SEGMENT_FALLBACK plus sigma_provenance['segment_fallback'].
No bucket and no fallback -> SIGMA_SEGMENT_MISSING.
"""
from __future__ import annotations

import numpy as np

from models.common.margins import cover_quote, discrete_football_margin, margin_quote_record

from ._shared import (
    SEGMENT_FALLBACK,
    SIGMA_SEGMENT_MISSING,
    MarginAdapterError,
    finalize_record,
    finite_margin,
    require_event,
    require_source_identity,
)

SPORT = "cfb"
MODEL_ID = "cfb.fbs.elo_form_logit_ridge.v1_0.shadow"

CFB_KEY_NUMBER_MASS = {
    3: 0.50, -3: 0.50,
    7: 0.35, -7: 0.35,
    10: 0.20, -10: 0.20,
    14: 0.15, -14: 0.15,
    6: 0.10, -6: 0.10,
    4: 0.10, -4: 0.10,
    17: 0.05, -17: 0.05,
    21: 0.05, -21: 0.05,
}
KEY_NUMBER_PROVENANCE = "RESEARCH_PLACEHOLDER_EMPIRICAL_REFIT_REQUIRED"


def _normalize_table(sigma_table: dict):
    if not isinstance(sigma_table, dict):
        raise MarginAdapterError(
            SIGMA_SEGMENT_MISSING, "sigma_table must be a dict of week buckets"
        )
    fallback = sigma_table.get("fallback")
    raw = sigma_table.get("buckets")
    if raw is None:
        raw = [
            dict(entry, label=label)
            for label, entry in sigma_table.items()
            if label != "fallback"
        ]
    buckets = []
    for entry in raw:
        e = dict(entry)
        if "week_min" not in e or "week_max" not in e:
            raise MarginAdapterError(
                SIGMA_SEGMENT_MISSING,
                f"sigma bucket {e.get('label')!r} lacks week_min/week_max",
            )
        buckets.append(e)
    return buckets, fallback


def _select_bucket(sigma_table: dict, week: int):
    buckets, fallback = _normalize_table(sigma_table)
    for bucket in buckets:
        if int(bucket["week_min"]) <= int(week) <= int(bucket["week_max"]):
            return bucket, False
    if fallback is None:
        raise MarginAdapterError(
            SIGMA_SEGMENT_MISSING,
            f"no sigma bucket covers week {week} and no fallback was supplied; "
            "refusing to silently reuse another segment's sigma",
        )
    return dict(fallback, label=fallback.get("label", "pooled")), True


def cfb_cover(
    margin_pred,
    sigma_table: dict,
    home_spread: float,
    *,
    week: int,
    artifact_sha256: str,
    event: dict,
    model_id: str = MODEL_ID,
    key_number_mass: dict | None = None,
    orientation: str = "home",
) -> dict:
    """Quote P(cover/push/loss) for `home_spread` (home covers iff M + s > 0).

    `week` selects the sigma segment; `margin_pred` is the ridge home-margin
    point prediction (home minus away). Inputs are never mutated.
    """
    mu = finite_margin(margin_pred, SPORT)
    if week is None:
        raise MarginAdapterError(SIGMA_SEGMENT_MISSING, "week is required for sigma segmentation")
    bucket, used_fallback = _select_bucket(sigma_table, int(week))
    sigma = bucket.get("sigma")
    if sigma is None or not np.isfinite(float(sigma)) or float(sigma) <= 0:
        raise MarginAdapterError(
            SIGMA_SEGMENT_MISSING, f"sigma bucket {bucket.get('label')!r} has no valid sigma"
        )
    model_id, artifact_sha256 = require_source_identity(model_id, artifact_sha256, SPORT)
    event = require_event(event)

    sigma_provenance = {
        "sport": SPORT,
        "sigma": float(sigma),
        "segment": str(bucket.get("label")),
        "segment_n": bucket.get("n"),
        "segment_week_min": bucket.get("week_min"),
        "segment_week_max": bucket.get("week_max"),
        "segment_fallback": bool(used_fallback),
    }
    for key in ("window_start", "window_end", "oof", "sample_kind"):
        if key in bucket:
            sigma_provenance[key] = bucket[key]

    dist = discrete_football_margin(
        mu,
        float(sigma),
        key_number_mass if key_number_mass is not None else CFB_KEY_NUMBER_MASS,
        {
            "sport": SPORT,
            "head": "margin_ridge",
            "model_id": model_id,
            "sigma_segment": str(bucket.get("label")),
            "key_number_mass_source": KEY_NUMBER_PROVENANCE,
        },
    )
    quote = cover_quote(dist, home_spread, orientation=orientation)
    record = margin_quote_record(
        dist,
        quote,
        event=event,
        source_model={"model_id": model_id, "artifact_sha256": artifact_sha256},
        sigma_provenance=sigma_provenance,
    )
    extra_warnings = ["RIDGE_MARGIN_HEAD_NOT_JOINT_SCORE_EXPECTATION"]
    if used_fallback:
        extra_warnings.append(SEGMENT_FALLBACK)
    return finalize_record(record, extra_warnings)


__all__ = ["cfb_cover", "CFB_KEY_NUMBER_MASS", "MODEL_ID"]
