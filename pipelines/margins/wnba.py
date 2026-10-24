"""WNBA margin adapter for wnba.rs.ff7_logit_ridge.v1_0.shadow (frozen fitter).

Same construction as the NBA adapter: ridge home-margin head mapped to a
continuity-corrected normal over integer margins (real push at integer
lines, zero push on half-point lines). The frozen-fitter status is carried
as a record limitation.
"""
from __future__ import annotations

from ._basketball import basketball_cover

SPORT = "wnba"
MODEL_ID = "wnba.rs.ff7_logit_ridge.v1_0.shadow"


def wnba_cover(
    home_spread: float,
    *,
    margin_pred=None,
    head: dict | None = None,
    features=None,
    sigma=None,
    sigma_provenance: dict | None = None,
    model_id: str = MODEL_ID,
    artifact_sha256: str,
    event: dict,
    orientation: str = "home",
) -> dict:
    """Quote WNBA spread cover (home covers iff M + home_spread > 0)."""
    return basketball_cover(
        SPORT,
        model_id,
        home_spread,
        margin_pred=margin_pred,
        head=head,
        features=features,
        sigma=sigma,
        sigma_provenance=sigma_provenance,
        artifact_sha256=artifact_sha256,
        event=event,
        orientation=orientation,
        extra_limitations=["SELECTED_FROZEN_FITTER_SHADOW"],
    )


__all__ = ["wnba_cover", "MODEL_ID"]
