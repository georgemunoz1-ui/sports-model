"""Opt-in settlement bridge for retained research margin distributions.

Use the existing discrete artifact/settlement contract, also used by PR #69,
through the CDF/push/sample interface proposed by PR #70. No fitting, inferred
dispersion, winner-to-margin conversion, key-number boost, or default routing.
Bindings verify consistency with supplied evidence, not source authenticity or
historical point-in-time availability. Original artifacts are never rewritten.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol

import numpy as np

from models.common import discrete_research as D

SCHEMA = "sports.bound_margin_quote.research.v1"
SOURCE_FIELDS = {"source_sha256", "parent_forecast_sha256"}


class MarginDistribution(Protocol):
    """PR #70-compatible read interface; insufficient alone to price a contract."""

    distribution_id: str

    def cdf(self, margin: float) -> float: ...
    def push_mass(self, margin: float) -> float: ...
    def sample(self, n: int, seed: int) -> np.ndarray: ...


@dataclass(frozen=True)
class BoundMargin:
    """Immutable snapshot with an explicit event, cutoff and source binding.

    Construct via bind_margin. The original distribution identity and probability
    mass are preserved, including any declared truncation/conditioning limits.
    """

    _json: str
    _binding_json: str

    def artifact(self):
        return json.loads(self._json)

    @property
    def distribution_id(self):
        return self.artifact()["distribution_sha256"]

    def cdf(self, margin):
        x, p = D.validate(self.artifact())
        return float(p[x <= D.finite(margin)].sum())

    def push_mass(self, margin):
        x, p = D.validate(self.artifact())
        return float(p[x == D.finite(margin)].sum())

    def sample(self, n, seed):
        # An explicit new compatibility draw, never a replacement for saved MC.
        if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
            raise ValueError("POSITIVE_INTEGER_DRAW_COUNT_REQUIRED")
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("NONNEGATIVE_INTEGER_SEED_REQUIRED")
        x, p = D.validate(self.artifact())
        return np.random.default_rng(seed).choice(x, size=n, p=p)


def bind_margin(distribution, *, event_id, cutoff, source_sha256,
                source_field="source_sha256"):
    """Require a matching external expectation; never repair/reseal a source."""
    if not isinstance(distribution, dict):
        raise ValueError("DISCRETE_MARGIN_ARTIFACT_REQUIRED")
    x, p = D.validate(distribution)
    if distribution["product"] != "margin":
        raise ValueError("MARGIN_PRODUCT_REQUIRED")
    if abs(float(p.sum()) - 1.0) > 1e-12:
        raise ValueError("PROBABILITY_MASS_INVALID")
    if source_field not in SOURCE_FIELDS:
        raise ValueError("SOURCE_BINDING_FIELD_UNSUPPORTED")
    D.identity(event_id, "EVENT_ID")
    D.stamp(cutoff)
    D.source_hash(source_sha256)
    prov = distribution["provenance"]
    if not isinstance(prov, dict) or prov.get("orientation") != "HOME_MINUS_AWAY":
        raise ValueError("EXPLICIT_HOME_MINUS_AWAY_REQUIRED")
    if (prov.get("event_id") != event_id or prov.get("cutoff") != cutoff
            or prov.get(source_field) != source_sha256):
        raise ValueError("EVENT_CUTOFF_SOURCE_MISMATCH")
    binding = {"event_id": event_id, "cutoff": cutoff,
               "source_field": source_field, "source_sha256": source_sha256}
    return BoundMargin(json.dumps(distribution, sort_keys=True, allow_nan=False),
                       json.dumps(binding, sort_keys=True, allow_nan=False))


def cover_quote(distribution, home_spread, *, orientation="home"):
    """Return explicit full/half win, push and loss states for the selected side.

    M=home-away; the supplied line is ALWAYS the home handicap. Away at home -3
    means away +3, not away -3. MLS quarter handicaps retain all five states;
    their stake-weighted outcomes cannot be represented by a binary ex-push p.
    """
    if not isinstance(distribution, BoundMargin):
        raise ValueError("BOUND_DISCRETE_MARGIN_REQUIRED")
    if orientation not in {"home", "away"}:
        raise ValueError("COVER_ORIENTATION_INVALID")
    # Revalidate even a directly constructed wrapper; a Python type is no seal.
    artifact = distribution.artifact()
    binding = json.loads(distribution._binding_json)
    bind_margin(artifact, **binding)
    line = D.finite(home_spread)
    side = orientation.upper()
    states = D.price(artifact, line, side)
    split = line * 2 != round(line * 2)
    resolved = states["win"] + states["loss"]
    conditional = None if split or resolved == 0 else states["win"] / resolved
    record = {
        "schema": SCHEMA, **binding,
        "league": artifact["league"], "product": "margin",
        "settlement": artifact["settlement"], "model_id": artifact["model_id"],
        "distribution_id": distribution.distribution_id,
        "orientation": "HOME_MINUS_AWAY", "side": side,
        "line_basis": "HOME_HANDICAP", "home_spread": line,
        "side_handicap": line if side == "HOME" else -line,
        "probability_basis": "UNCONDITIONAL_FIVE_SETTLEMENT_STATES",
        "probabilities": states,
        "p_cover_ex_push": conditional,
        "ex_push_basis": "UNAVAILABLE_SPLIT_HANDICAP" if split else
                         "UNDEFINED_ALL_PUSH" if resolved == 0 else "CONDITIONAL_NON_PUSH",
        "winning_stake_probability": states["win"] + .5 * states["half_win"],
        "losing_stake_probability": states["loss"] + .5 * states["half_loss"],
        "source_provenance": artifact["provenance"],
        "research_only": True, "action_authority": False,
        "prospective_grade_eligible": False,
        "predictive_validation": "NOT_ASSESSED",
        "source_verification": "BINDING_ONLY_NOT_INDEPENDENT_ATTESTATION",
    }
    record["record_sha256"] = D.digest(record)
    return record


def validate_quote(record, distribution):
    """Recompute against the bound law, including orientation and every label."""
    if not isinstance(record, dict):
        raise ValueError("MARGIN_QUOTE_RECORD_REQUIRED")
    try:
        expected = cover_quote(distribution, record["home_spread"],
                               orientation=record["side"].lower())
        if D.digest(record) != D.digest(expected):
            raise ValueError("MARGIN_QUOTE_BINDING_MISMATCH")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("MARGIN_QUOTE_STRUCTURE_INVALID") from exc
    return True
