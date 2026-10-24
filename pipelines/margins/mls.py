"""MLS adapter: the selected MLS model is 1X2 only.

mls.initial_causal_score.research.v1 fits Poisson goal heads and prices
home/draw/away via Skellam; there is NO margin/spread product and this
adapter must not invent one. mls_cover raises
UnsupportedProductError(UNSUPPORTED_1X2_ONLY). mls_1x2_record is a
pass-through that documents the 1X2 forecast while explicitly recording
that margin products are not offered.
"""
from __future__ import annotations

import copy
import hashlib
import json

from ._shared import (
    UNSUPPORTED_1X2_ONLY,
    MarginAdapterError,
    UnsupportedProductError,
)

SPORT = "mls"
MODEL_ID = "mls.initial_causal_score.research.v1"
PASSTHROUGH_SCHEMA = "sports.mls_1x2_passthrough.v1"
DEFAULT_REASON = (
    "MLS selected model is regulation 1X2 (Poisson goal heads + Skellam); "
    "no home-margin head is fitted, so no spread/margin cover product exists"
)


def mls_cover(*_args, **_kwargs):
    """No MLS margin product exists; fail closed."""
    raise UnsupportedProductError(UNSUPPORTED_1X2_ONLY, DEFAULT_REASON)


def mls_1x2_record(forecast_result: dict, *, reason: str | None = None) -> dict:
    """Pass the 1X2 forecast through, documenting that margins are unsupported.

    The input forecast is deep-copied (never mutated); the wrapper record is
    research-only with action_authority False.
    """
    if not isinstance(forecast_result, dict):
        raise MarginAdapterError(UNSUPPORTED_1X2_ONLY, "forecast_result must be a dict")
    record = {
        "schema": PASSTHROUGH_SCHEMA,
        "sport": SPORT,
        "model_id": forecast_result.get("model_id", MODEL_ID),
        "forecast": copy.deepcopy(forecast_result),
        "margin_products": {
            "status": UNSUPPORTED_1X2_ONLY,
            "reason": reason or DEFAULT_REASON,
            "spread_cover": None,
            "p_cover": None,
            "p_push": None,
            "p_loss": None,
        },
        "research_only": True,
        "action_authority": False,
    }
    body = {k: v for k, v in record.items() if k != "record_sha256"}
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    record["record_sha256"] = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    return record


__all__ = [
    "mls_cover",
    "mls_1x2_record",
    "MODEL_ID",
    "PASSTHROUGH_SCHEMA",
    "UNSUPPORTED_1X2_ONLY",
    "DEFAULT_REASON",
]
