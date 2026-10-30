"""Strict payoff arithmetic for research contracts, without allocation authority.

The centered second moment avoids cancellation from E[X²] - E[X]². No invalid
arithmetic is converted to zero variance. This measures payout variability under
the supplied probabilities, not uncertainty about those probabilities.
"""
from __future__ import annotations

import math
from numbers import Real
from typing import Mapping

SCHEMA = "sports.settlement_risk.research.v1"
STATES = ("win", "half_win", "push", "half_loss", "loss", "void")
MASS_ABS_TOLERANCE = 1e-12


def finite_real(value, label):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("INVALID_" + label)
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("INVALID_" + label) from exc
    if not math.isfinite(value):
        raise ValueError("INVALID_" + label)
    return value


def decimal_odds(odds, odds_format):
    odds = finite_real(odds, "ODDS")
    if odds_format == "american":
        if abs(odds) < 100:
            raise ValueError("INVALID_AMERICAN_ODDS")
        result = 1 + (odds / 100 if odds > 0 else 100 / -odds)
    elif odds_format == "decimal":
        result = odds
    else:
        raise ValueError("UNSUPPORTED_ODDS_FORMAT")
    if not math.isfinite(result) or result <= 1:
        raise ValueError("INVALID_DECIMAL_ODDS")
    return result


def payoff_moments(probabilities: Mapping, *, odds, odds_format="american"):
    """Return net-unit EV and SD with all supplied settlement states retained.

    A three-state input must explicitly provide win/push/loss. Half and void
    states are optional, defaulting only to declared absence (zero). Additional
    keys, booleans, nonfinite values and nonunit mass are rejected. Tiny mass
    roundoff is accepted within a fixed 1e-12; probabilities are not normalized.
    """
    if (not isinstance(probabilities, Mapping)
            or not {"win", "push", "loss"} <= set(probabilities)
            or set(probabilities) - set(STATES)):
        raise ValueError("INVALID_SETTLEMENT_PROBABILITY_FIELDS")
    p = {key: finite_real(probabilities.get(key, 0.), "PROBABILITY_" + key.upper())
         for key in STATES}
    if any(value < 0 or value > 1 for value in p.values()):
        raise ValueError("PROBABILITY_OUT_OF_RANGE")
    if not math.isclose(math.fsum(p.values()), 1., rel_tol=0., abs_tol=MASS_ABS_TOLERANCE):
        raise ValueError("INVALID_PROBABILITY_SUM")
    decimal = decimal_odds(odds, odds_format)
    net = decimal - 1
    returns = dict(zip(STATES, (net, .5 * net, 0., -.5, -1., 0.)))
    try:
        mean_terms = [p[key] * returns[key] for key in STATES if p[key] > 0]
        if not all(math.isfinite(v) for v in mean_terms):
            raise ValueError("NONFINITE_EXPECTED_RETURN")
        mean = math.fsum(mean_terms)
        if not math.isfinite(mean):
            raise ValueError("NONFINITE_EXPECTED_RETURN")
        # Multiply sqrt(p) before squaring: zero-probability extreme returns
        # never produce 0 * inf, and rare-event terms avoid unnecessary overflow.
        centered = [math.sqrt(p[key]) * (returns[key] - mean)
                    for key in STATES if p[key] > 0]
        terms = [value * value for value in centered]
        if not all(math.isfinite(v) for v in centered + terms):
            raise ValueError("NONFINITE_RETURN_VARIANCE")
        variance = math.fsum(terms)
        if not math.isfinite(variance) or variance < 0:
            raise ValueError("NONFINITE_RETURN_VARIANCE")
        sd = math.sqrt(variance)
    except (OverflowError, ArithmeticError) as exc:
        raise ValueError("NONFINITE_PAYOFF_ARITHMETIC") from exc
    standardized = mean / sd if sd > 0 else None
    if standardized is not None and not math.isfinite(standardized):
        raise ValueError("NONFINITE_STANDARDIZED_RETURN")
    return {"schema": SCHEMA, "probabilities": p, "decimal_odds": decimal,
            "net_returns": returns, "expected_return_per_unit": mean,
            "return_variance_per_unit": variance, "return_sd_per_unit": sd,
            "standardized_expected_return": standardized,
            "standardized_return_status": "DEFINED" if sd > 0 else "UNDEFINED_ZERO_SD",
            "variance_method": "CENTERED_WEIGHTED_SECOND_MOMENT_NO_CLAMP",
            "uncertainty_scope": "PAYOUT_VARIABILITY_ONLY_NOT_MODEL_UNCERTAINTY",
            "price_assessment": "NEGATIVE_MODEL_EV" if mean < 0 else
                                "POSITIVE_MODEL_EV" if mean > 0 else "ZERO_MODEL_EV",
            "research_only": True, "action_authority": False}
