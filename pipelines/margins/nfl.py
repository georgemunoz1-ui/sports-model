"""NFL margin adapter: bind to the SELECTED arm's own home_margin ridge head.

Input is a models/nfl/contextual/runtime.run result bundle
(schema nfl.integrated_context_forecast.v1). The bundle carries every arm's
predictions in result['arms'][arm]['prediction'] plus the selected arm in
result['selected_arm'] (and/or result['diagnostics']['selected_arm']).

Hard rules implemented here:
  * The margin distribution is built ONLY from the selected arm's own
    home_margin head output. A different arm's head or a mismatched top-level
    prediction -> ARM_NOT_SELECTED_CONSISTENT.
  * The joint final-score residual pool is COMBINED-specific (runtime reports
    score_simulation status UNAVAILABLE_FOR_SELECTED_ARM for the qb arm). Any
    sigma provenance pointing at a residual pool from a different arm than the
    selected one (the combined pool with a qb-arm model_id is the canonical
    misuse) -> MARGIN_POOL_MODEL_MISMATCH.
  * Missing home_margin head output -> MISSING_MARGIN_HEAD.

NFL margins are integers with key numbers, so the quote uses
discrete_football_margin; the default key-number inflation magnitudes are
RESEARCH PLACEHOLDERS and must be refit from OOF margins before any trust.
"""
from __future__ import annotations

import re

import numpy as np

from models.common.margins import cover_quote, discrete_football_margin, margin_quote_record

from ._shared import (
    ARM_NOT_SELECTED_CONSISTENT,
    MARGIN_POOL_MODEL_MISMATCH,
    MISSING_MARGIN_HEAD,
    MarginAdapterError,
    finalize_record,
    finite_margin,
    require_event,
    require_sigma,
    require_source_identity,
)

SPORT = "nfl"
KNOWN_ARMS = ("base", "qb", "availability", "travel", "combined")

# Multiplicative key-number inflation, applied at signed integer margins
# (both +k and -k). NOTE: the symmetric boosts do NOT exactly preserve the
# fitted mean for mu != 0 — they induce a small mean-reverting drift toward 0
# (probe: mu=-7, sigma=13.5 with the defaults below gives E[M] ~= -6.62). This is accepted
# for the placeholder mass model; the magnitudes must be refit from OOF
# margins before any trust. PLACEHOLDER magnitudes.
NFL_KEY_NUMBER_MASS = {
    3: 0.60, -3: 0.60,
    7: 0.40, -7: 0.40,
    10: 0.25, -10: 0.25,
    14: 0.15, -14: 0.15,
    6: 0.10, -6: 0.10,
    4: 0.10, -4: 0.10,
    1: 0.05, -1: 0.05,
    17: 0.05, -17: 0.05,
}
KEY_NUMBER_PROVENANCE = "RESEARCH_PLACEHOLDER_EMPIRICAL_REFIT_REQUIRED"

_POOL_ARM_KEYS = ("pool_arm", "residual_pool_arm", "residuals_arm")


def _selected_arm(result: dict) -> str:
    diagnostics = result.get("diagnostics") or {}
    if not isinstance(diagnostics, dict):
        raise MarginAdapterError(
            ARM_NOT_SELECTED_CONSISTENT,
            "result['diagnostics'] must be a dict when present; got "
            f"{type(diagnostics).__name__}",
        )
    diag_arm = diagnostics.get("selected_arm")
    top_arm = result.get("selected_arm")
    if diag_arm is None and top_arm is None:
        raise MarginAdapterError(
            ARM_NOT_SELECTED_CONSISTENT,
            "no selected_arm in result['diagnostics'] or result top level",
        )
    if diag_arm is not None and top_arm is not None and diag_arm != top_arm:
        raise MarginAdapterError(
            ARM_NOT_SELECTED_CONSISTENT,
            f"diagnostics.selected_arm '{diag_arm}' disagrees with "
            f"top-level selected_arm '{top_arm}'",
        )
    return diag_arm if diag_arm is not None else top_arm


def _arm_margin(result: dict, arm: str) -> float:
    arms = result.get("arms") or {}
    entry = arms.get(arm)
    if not isinstance(entry, dict):
        raise MarginAdapterError(
            MISSING_MARGIN_HEAD, f"result['arms'] has no entry for selected arm '{arm}'"
        )
    prediction = entry.get("prediction") or {}
    mu = prediction.get("home_margin", prediction.get("margin", entry.get("margin_mean")))
    return finite_margin(mu, f"nfl arm '{arm}' home_margin head")


def _check_top_level_consistency(result: dict, arm: str, mu: float) -> None:
    top = (result.get("prediction") or {}).get("home_margin")
    if top is not None and abs(float(top) - mu) > 1e-9:
        raise MarginAdapterError(
            ARM_NOT_SELECTED_CONSISTENT,
            f"result['prediction']['home_margin'] ({top}) does not match the "
            f"selected arm '{arm}' prediction ({mu})",
        )


def _arm_token(value) -> str | None:
    """Known arm named by a provenance value, else None.

    Token-exact matching after lowercasing and splitting on non-alphanumeric
    characters — never substring matching: 'database_residuals' has no arm
    token and must NOT match 'base'.
    """
    tokens = re.split(r"[^a-z0-9]+", str(value).lower())
    for token in tokens:
        if token in KNOWN_ARMS:
            return token
    return None


def _pool_arm(sigma_provenance: dict):
    """Residual-pool arm named by the sigma provenance, if any.

    Explicit key lookup with exact/normalized value matching. Fail closed:
      * a dedicated pool-arm key whose value names no known arm, or
      * free text that mentions a residual *pool* without naming an arm,
    both raise MARGIN_POOL_MODEL_MISMATCH — the pool origin cannot be
    verified, so silently skipping the check is not allowed.
    """
    for key in _POOL_ARM_KEYS:
        value = sigma_provenance.get(key)
        if value is None:
            continue
        arm = _arm_token(value)
        if arm is None:
            raise MarginAdapterError(
                MARGIN_POOL_MODEL_MISMATCH,
                f"sigma provenance key '{key}' value {value!r} does not name a "
                f"known arm {KNOWN_ARMS}; refusing to guess the residual pool "
                "origin",
            )
        return arm
    for key in ("residual_source", "source", "pool"):
        value = sigma_provenance.get(key)
        if value is None:
            continue
        arm = _arm_token(value)
        if arm is not None:
            return arm
        if key == "pool" or "pool" in str(value).lower():
            raise MarginAdapterError(
                MARGIN_POOL_MODEL_MISMATCH,
                f"sigma provenance key '{key}' carries residual-pool info "
                f"({value!r}) that names no known arm {KNOWN_ARMS}; refusing "
                "to silently skip the pool/arm consistency check",
            )
    return None


def nfl_cover(
    forecast_result: dict,
    home_spread: float,
    *,
    sigma_provenance: dict,
    key_number_mass: dict | None = None,
    orientation: str = "home",
) -> dict:
    """Quote P(cover/push/loss) for `home_spread` from a runtime result bundle.

    home_spread follows the core convention: home covers iff M + home_spread > 0
    (home -3.5 -> home_spread=-3.5). Never mutates `forecast_result`.
    """
    if not isinstance(forecast_result, dict):
        raise MarginAdapterError(
            ARM_NOT_SELECTED_CONSISTENT, "forecast_result must be a runtime result dict"
        )
    arm = _selected_arm(forecast_result)
    mu = _arm_margin(forecast_result, arm)
    _check_top_level_consistency(forecast_result, arm, mu)

    pool = _pool_arm(sigma_provenance if isinstance(sigma_provenance, dict) else {})
    if pool is not None and pool != arm:
        raise MarginAdapterError(
            MARGIN_POOL_MODEL_MISMATCH,
            f"residual pool from arm '{pool}' cannot back a forecast whose selected "
            f"arm is '{arm}' (model_id={forecast_result.get('model_id')}); the joint "
            "score/residual simulator is COMBINED-specific",
        )
    sigma = require_sigma(sigma_provenance, SPORT)
    model_id, artifact_sha256 = require_source_identity(
        forecast_result.get("model_id"),
        forecast_result.get("model_artifact_sha256"),
        SPORT,
    )
    event = require_event(forecast_result.get("event"))

    dist = discrete_football_margin(
        mu,
        sigma,
        key_number_mass if key_number_mass is not None else NFL_KEY_NUMBER_MASS,
        {
            "sport": SPORT,
            "selected_arm": arm,
            "head": "home_margin_ridge",
            "model_id": model_id,
            "key_number_mass_source": KEY_NUMBER_PROVENANCE,
        },
    )
    quote = cover_quote(dist, home_spread, orientation=orientation)
    record = margin_quote_record(
        dist,
        quote,
        event=event,
        source_model={"model_id": model_id, "artifact_sha256": artifact_sha256},
        sigma_provenance={**sigma_provenance, "sport": SPORT, "selected_arm": arm},
    )
    extra_warnings = [
        "MARGIN_HEAD_IS_SELECTED_ARM_RIDGE_NOT_JOINT_SCORE_EXPECTATION",
        "KEY_NUMBER_MASS_PLACEHOLDER_NOT_FITTED",
    ]
    score_sim = forecast_result.get("score_simulation") or {}
    if score_sim.get("status") == "UNAVAILABLE_FOR_SELECTED_ARM":
        extra_warnings.append("JOINT_SCORE_SIMULATOR_UNAVAILABLE_FOR_SELECTED_ARM")
    return finalize_record(record, extra_warnings)


__all__ = ["nfl_cover", "NFL_KEY_NUMBER_MASS"]
