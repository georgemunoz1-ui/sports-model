"""MLB run-line adapter for mlb.winner.CHAMPION_V13.

The selected MLB winner model is a Gamma-Poisson Monte Carlo producing
simulated game scores; run margins are integers, so the typical +/-1.5 run
line has zero push mass while integer lines carry real push mass. Settlement
is by DIRECT SIMULATION COUNTING only (no analytic approximation).

Other products (totals, team totals, ...) stay UNSUPPORTED_SETTLEMENT:
`mlb_totals_cover` raises UnsupportedProductError rather than inventing a
settlement.
"""
from __future__ import annotations

import numpy as np

from models.common.margins import cover_quote, margin_quote_record, simulated_margin

from ._shared import (
    UNSUPPORTED_SETTLEMENT,
    MarginAdapterError,
    UnsupportedProductError,
    finalize_record,
    require_event,
    require_source_identity,
)

SPORT = "mlb"
MODEL_ID = "mlb.winner.CHAMPION_V13"
DEFAULT_RUN_LINE = -1.5


def mlb_runline_cover(
    simulated_home_scores,
    simulated_away_scores,
    home_line: float = DEFAULT_RUN_LINE,
    *,
    event: dict,
    artifact_sha256: str,
    model_id: str = MODEL_ID,
    orientation: str = "home",
) -> dict:
    """Quote run-line cover by direct counting over simulated score draws.

    home_line follows the core convention: home covers iff M + home_line > 0
    (home -1.5 -> home_line=-1.5). Score arrays are paired draw-by-draw and
    are never mutated.
    """
    home = np.asarray(simulated_home_scores, dtype=np.float64).ravel()
    away = np.asarray(simulated_away_scores, dtype=np.float64).ravel()
    if home.shape != away.shape or home.size == 0:
        raise MarginAdapterError(
            "SCORE_DRAW_SHAPE_MISMATCH",
            "simulated_home_scores and simulated_away_scores must be paired 1-D draws",
        )
    draws = home - away
    if not np.all(np.isfinite(draws)):
        raise MarginAdapterError("SIMULATED_MARGIN_NAN", "score draws contain non-finite values")
    if not np.all(np.isclose(draws, np.round(draws), atol=1e-9)):
        raise MarginAdapterError(
            "RUN_MARGIN_DRAWS_NOT_INTEGER",
            "MLB run margins must be integers; non-integer draws indicate the "
            "inputs are not simulated final scores",
        )
    model_id, artifact_sha256 = require_source_identity(model_id, artifact_sha256, SPORT)
    event = require_event(event)

    dist = simulated_margin(
        draws,
        {
            "sport": SPORT,
            "model_id": model_id,
            "generator": "GAMMA_POISSON_MONTE_CARLO",
            "unit": "run_margin_home_minus_away",
        },
    )
    quote = cover_quote(dist, float(home_line), orientation=orientation)
    record = margin_quote_record(
        dist,
        quote,
        event=event,
        source_model={"model_id": model_id, "artifact_sha256": artifact_sha256},
        sigma_provenance={
            "sport": SPORT,
            "kind": "DIRECT_SIMULATION_COUNTING",
            "n_draws": int(draws.size),
        },
    )
    return finalize_record(
        record,
        extra_warnings=["RUN_LINE_SETTLEMENT_BY_DIRECT_SIMULATION_COUNTING"],
        extra_limitations=["MONTE_CARLO_ESTIMATE_NO_INDEPENDENT_ANALYTIC_VALUE"],
    )


def mlb_totals_cover(*_args, **_kwargs):
    """Totals are not settled by this adapter (UNSUPPORTED_SETTLEMENT)."""
    raise UnsupportedProductError(
        UNSUPPORTED_SETTLEMENT,
        "MLB totals settlement is UNSUPPORTED_SETTLEMENT for the V13 simulation "
        "product; only the run line is emitted by this adapter",
    )


__all__ = [
    "mlb_runline_cover",
    "mlb_totals_cover",
    "MODEL_ID",
    "DEFAULT_RUN_LINE",
    "UNSUPPORTED_SETTLEMENT",
]
