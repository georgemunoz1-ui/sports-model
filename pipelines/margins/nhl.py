"""NHL puck-line adapter wrapping the existing separate margin model.

The existing NHL margin model produces puck-line (+/-1.5) covers and is
labeled uncalibrated. This adapter NEVER removes that label: every record
carries the limitation MARGIN_MODEL_UNCALIBRATED_SEPARATE_FIT, and any
calibration/uncalibrated labels present on the input output are preserved
verbatim in the record warnings.

Supports half-point puck lines (+/-1.5, +/-2.5, push == 0) and integer lines
(real push mass: hockey margins are integers).

Input forms (never mutated):
  * margin_model_output: dict from the existing margin model, e.g.
    {"model_id":..., "artifact_sha256":..., "margin_mean": 0.8,
     "sigma": 2.4, "labels": ["UNCALIBRATED"], "event": {...}}
    (also accepts prediction.home_margin / projected_margin, model_sha256,
    and a 'residuals' array for an integer-snapped empirical margin), or
  * explicit kwargs margin_pred + sigma (or residuals), model_id,
    artifact_sha256, event.
"""
from __future__ import annotations

import numpy as np

from models.common.margins import cover_quote, empirical_margin, margin_quote_record

from ._shared import (
    SIGMA_REQUIRED,
    IntegerNormalMargin,
    MarginAdapterError,
    finalize_record,
    finite_margin,
    require_event,
    require_source_identity,
)

SPORT = "nhl"
MODEL_ID = "nhl.margin.research.v1"
UNCALIBRATED_LIMITATION = "MARGIN_MODEL_UNCALIBRATED_SEPARATE_FIT"
DEFAULT_PUCK_LINE = -1.5


def _extract(out: dict, margin_pred, sigma, residuals):
    mu = margin_pred
    if mu is None:
        prediction = out.get("prediction") or {}
        mu = out.get("margin_mean", prediction.get("home_margin", out.get("projected_margin")))
    sig = sigma if sigma is not None else out.get("sigma")
    res = residuals if residuals is not None else out.get("residuals")
    return mu, sig, res


def nhl_puckline_cover(
    margin_model_output: dict | None = None,
    home_line: float = DEFAULT_PUCK_LINE,
    *,
    margin_pred=None,
    sigma=None,
    residuals=None,
    model_id: str | None = None,
    artifact_sha256: str | None = None,
    event: dict | None = None,
    orientation: str = "home",
) -> dict:
    """Quote puck-line cover, preserving the uncalibrated labels."""
    out = margin_model_output if isinstance(margin_model_output, dict) else {}
    labels = list(out.get("labels") or out.get("warnings") or [])
    mid, sha = require_source_identity(
        model_id or out.get("model_id") or MODEL_ID,
        artifact_sha256
        or out.get("artifact_sha256")
        or out.get("model_artifact_sha256")
        or out.get("model_sha256"),
        SPORT,
    )
    mu, sig, res = _extract(out, margin_pred, sigma, residuals)
    mu = finite_margin(mu, SPORT)  # MISSING_MARGIN_HEAD when absent
    ev = require_event(event if event is not None else out.get("event"))

    provenance = {"sport": SPORT, "model_id": mid, "fit": "SEPARATE_MARGIN_MODEL"}
    if res is not None:
        dist = empirical_margin(mu, np.asarray(res, dtype=np.float64), provenance,
                                integer_snap=True)
        sigma_kind = "EMPIRICAL_RESIDUAL_INTEGER_SNAP"
    else:
        if sig is None or not np.isfinite(float(sig)) or float(sig) <= 0:
            raise MarginAdapterError(
                SIGMA_REQUIRED,
                "nhl: margin model output must carry sigma or residuals",
            )
        provenance["approximation"] = "CONTINUITY_CORRECTED_NORMAL_ON_INTEGER_MARGINS"
        dist = IntegerNormalMargin(mu, float(sig), provenance)
        sigma_kind = "SEPARATE_FIT_SIGMA_UNCALIBRATED"

    quote = cover_quote(dist, float(home_line), orientation=orientation)
    record = margin_quote_record(
        dist,
        quote,
        event=ev,
        source_model={"model_id": mid, "artifact_sha256": sha},
        sigma_provenance={"sport": SPORT, "kind": sigma_kind, "uncalibrated": True},
    )
    return finalize_record(
        record,
        extra_warnings=labels,  # preserve input labels verbatim
        extra_limitations=[UNCALIBRATED_LIMITATION],
    )


__all__ = ["nhl_puckline_cover", "MODEL_ID", "UNCALIBRATED_LIMITATION", "DEFAULT_PUCK_LINE"]
