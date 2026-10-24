"""NBA margin adapter for nba.initial_causal_score.research.v1.

The NBA baseline is logistic + ridge heads; this adapter maps the ridge
home-margin head to a margin distribution. Basketball margins are integers,
so the continuous ridge output is settled on an integer grid via a
continuity-corrected normal: half-point lines have exactly zero push,
integer lines carry real push mass.

Margin source: either a precomputed `margin_pred`, or `head` + `features`
(a frozen standardized ridge head in the models/current/linear.py packing,
applied with median-imputation semantics; no fitting at inference).
"""
from __future__ import annotations

from ._basketball import basketball_cover

SPORT = "nba"
MODEL_ID = "nba.initial_causal_score.research.v1"


def nba_cover(
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
    """Quote NBA spread cover (home covers iff M + home_spread > 0)."""
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
        extra_limitations=["INITIAL_RESEARCH_BASELINE_NOT_ACCURACY_DEFAULT"],
    )


__all__ = ["nba_cover", "MODEL_ID"]
