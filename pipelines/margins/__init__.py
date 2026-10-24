"""Per-sport margin adapters mapping existing model outputs onto the shared
margin library (models.common.margins). Research-only; no action authority.

Registry: get_adapter(league) -> the league's adapter module. Adapter modules
never mutate their inputs and emit records via margin_quote_record (schema
sports.margin_quote.v2, research_only=True, action_authority=False), except
MLS which has no margin product (UNSUPPORTED_1X2_ONLY).
"""
from __future__ import annotations

import importlib

from ._shared import (
    ARM_NOT_SELECTED_CONSISTENT,
    MARGIN_POOL_MODEL_MISMATCH,
    MISSING_MARGIN_HEAD,
    SEGMENT_FALLBACK,
    SIGMA_PROVENANCE_NOT_OOF,
    SIGMA_SEGMENT_MISSING,
    SIGMA_SPORT_MISMATCH,
    UNSUPPORTED_1X2_ONLY,
    UNSUPPORTED_SETTLEMENT,
    MarginAdapterError,
    UnsupportedProductError,
)

_ADAPTERS = {
    "nfl": "pipelines.margins.nfl",
    "cfb": "pipelines.margins.cfb",
    "nhl": "pipelines.margins.nhl",
    "mlb": "pipelines.margins.mlb",
    "nba": "pipelines.margins.nba",
    "wnba": "pipelines.margins.wnba",
    "mls": "pipelines.margins.mls",
}


def leagues():
    """League keys with a registered margin adapter."""
    return tuple(_ADAPTERS)


def get_adapter(league: str):
    """Return the margin adapter module for `league` (e.g. 'nfl')."""
    key = str(league).strip().lower()
    if key not in _ADAPTERS:
        raise ValueError("UNKNOWN_LEAGUE_ADAPTER:" + str(league))
    return importlib.import_module(_ADAPTERS[key])


__all__ = [
    "get_adapter",
    "leagues",
    "MarginAdapterError",
    "UnsupportedProductError",
    "MARGIN_POOL_MODEL_MISMATCH",
    "MISSING_MARGIN_HEAD",
    "ARM_NOT_SELECTED_CONSISTENT",
    "SIGMA_SEGMENT_MISSING",
    "SEGMENT_FALLBACK",
    "SIGMA_SPORT_MISMATCH",
    "SIGMA_PROVENANCE_NOT_OOF",
    "UNSUPPORTED_1X2_ONLY",
    "UNSUPPORTED_SETTLEMENT",
]
