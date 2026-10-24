"""Shared basketball margin adapter logic (NBA/WNBA).

Basketball margins are integers: quotes use a continuity-corrected normal
(IntegerNormalMargin) so integer lines have real push mass and half-point
lines have exactly none. Inputs are never mutated.
"""
from __future__ import annotations

import numpy as np

from models.common.margins import cover_quote, margin_quote_record

from ._shared import (
    MISSING_MARGIN_HEAD,
    IntegerNormalMargin,
    MarginAdapterError,
    finalize_record,
    margin_from_ridge_head,
    require_event,
    require_sigma,
    require_source_identity,
)


def basketball_cover(
    sport: str,
    default_model_id: str,
    home_spread: float,
    *,
    margin_pred=None,
    head: dict | None = None,
    features=None,
    sigma=None,
    sigma_provenance: dict | None = None,
    artifact_sha256: str,
    event: dict,
    orientation: str = "home",
    extra_limitations=(),
) -> dict:
    if margin_pred is None:
        if head is None or features is None:
            raise MarginAdapterError(
                MISSING_MARGIN_HEAD,
                f"{sport}: provide margin_pred or a frozen ridge head + features",
            )
        mu = margin_from_ridge_head(head, features)
    else:
        if not np.isfinite(float(margin_pred)):
            raise MarginAdapterError(MISSING_MARGIN_HEAD, f"{sport}: non-finite margin_pred")
        mu = float(margin_pred)

    sp = dict(sigma_provenance or {})
    if sigma is not None:
        # Convenience scalar override only: the provenance must still
        # demonstrate chronological OOF origin (require_sigma enforces the
        # estimate_sigma contract: oof=True + window_start/window_end,
        # never label_in_sample). A bare scalar sigma cannot back a quote.
        sp["sigma"] = float(sigma)
    sig = require_sigma(sp, sport)
    sp["sport"] = sport
    model_id, artifact_sha256 = require_source_identity(
        default_model_id, artifact_sha256, sport
    )
    event = require_event(event)

    dist = IntegerNormalMargin(
        mu,
        float(sig),
        {
            "sport": sport,
            "model_id": model_id,
            "head": "margin_ridge",
            "approximation": "CONTINUITY_CORRECTED_NORMAL_ON_INTEGER_MARGINS",
        },
    )
    quote = cover_quote(dist, float(home_spread), orientation=orientation)
    record = margin_quote_record(
        dist,
        quote,
        event=event,
        source_model={"model_id": model_id, "artifact_sha256": artifact_sha256},
        sigma_provenance=sp,
    )
    return finalize_record(
        record,
        extra_warnings=["RIDGE_MARGIN_HEAD_NOT_JOINT_SCORE_EXPECTATION"],
        extra_limitations=extra_limitations,
    )
