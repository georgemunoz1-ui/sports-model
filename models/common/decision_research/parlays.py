"""Research arithmetic for explicitly supplied correlated ticket scenarios.

This module does not generate probabilities, verify a venue rule, qualify a
forecast, select a ticket, or authorize an order.  A LOSS always loses the
ticket.  Otherwise push/void behavior is explicitly selected by the caller.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json


@dataclass(frozen=True)
class JointScenario:
    weight: Decimal | str | int
    outcomes: tuple[str, ...]


@dataclass(frozen=True)
class ParlayRules:
    rules_id: str
    push_policy: str


def _decimal(value: object, name: str) -> Decimal:
    # Bound precision/scale so exact additions/products below cannot silently
    # discard a tiny supplied probability under the process Decimal context.
    if isinstance(value, bool) or not isinstance(value, (Decimal, str, int)):
        raise ValueError(f"{name}: Decimal, decimal string or integer required")
    try:
        answer = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name}: invalid decimal") from None
    if not answer.is_finite():
        raise ValueError(f"{name}: finite decimal required")
    if len(answer.as_tuple().digits) > 28 or abs(answer.as_tuple().exponent) > 28:
        raise ValueError(f"{name}: maximum 28 digits and absolute scale 28")
    if answer < 0:
        raise ValueError(f"{name}: nonnegative value required")
    return answer


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name}: nonempty, whitespace-trimmed string required")
    return value


def parlay_value(
    leg_ids: Sequence[str],
    scenarios: Sequence[JointScenario],
    payout_by_active_legs: Mapping[tuple[int, ...], Decimal | str | int],
    cost: Decimal | str | int,
    fee: Decimal | str | int,
    rules: ParlayRules,
) -> dict:
    """Value one ticket from its supplied joint outcome probability mass.

    ``cost`` and ``fee`` are total ticket dollars, not per-leg values. Payouts
    are gross ticket dollars. ``REMOVE_LEG`` requires a payout for every active
    index tuple encountered without a losing leg, including ``()`` when all
    legs push/void. No full refund or fee refund is inferred in that case.

    Up to 28 decimal digits and absolute scale 28 are admitted. Expectations
    and variance are exact at an internal precision sufficient for this bound;
    square-root SD is a rounded 60-significant-digit diagnostic.
    """
    if not isinstance(leg_ids, (tuple, list)) or not leg_ids:
        raise ValueError("leg_ids: nonempty list or tuple required")
    legs = tuple(_identifier(value, "leg_id") for value in leg_ids)
    if len(set(legs)) != len(legs):
        raise ValueError("leg_ids: duplicate identity")
    if not isinstance(rules, ParlayRules):
        raise ValueError("rules: ParlayRules required")
    _identifier(rules.rules_id, "rules_id")
    if type(rules.push_policy) is not str or rules.push_policy not in {"REJECT", "REFUND_TICKET", "REMOVE_LEG"}:
        raise ValueError("push_policy: unsupported policy")
    if not isinstance(scenarios, (tuple, list)) or not scenarios:
        raise ValueError("scenarios: nonempty supplied joint-scenario sequence required")
    if not isinstance(payout_by_active_legs, Mapping):
        raise ValueError("payout_by_active_legs: mapping required")
    payouts = {}
    for key, value in payout_by_active_legs.items():
        if (
            not isinstance(key, tuple)
            or any(type(index) is not int or index < 0 or index >= len(legs) for index in key)
            or tuple(sorted(set(key))) != key
        ):
            raise ValueError("payout key: unique increasing valid leg indices required")
        payouts[key] = _decimal(value, "gross_payout")
    all_indices = tuple(range(len(legs)))
    if all_indices not in payouts:
        raise ValueError("full-ticket gross payout required")
    entry_cost = _decimal(cost, "cost")
    entry_fee = _decimal(fee, "fee")
    parsed = []
    for item in scenarios:
        if not isinstance(item, JointScenario):
            raise ValueError("scenario: JointScenario required")
        weight = _decimal(item.weight, "weight")
        if weight > 1:
            raise ValueError("weight: exceeds one")
        if not isinstance(item.outcomes, (list, tuple)) or len(item.outcomes) != len(legs):
            raise ValueError("outcomes: exactly one outcome per leg required")
        outcomes = tuple(item.outcomes)
        if any(type(outcome) is not str or outcome not in {"WIN", "LOSS", "PUSH", "VOID"} for outcome in outcomes):
            raise ValueError("outcomes: only WIN/LOSS/PUSH/VOID supported")
        parsed.append((weight, outcomes))

    # Each bounded input has at most 56 decimal places from its full range;
    # products for variance need at most 168, with extra room for sum carries.
    with localcontext() as context:
        context.prec = 200 + len(str(len(parsed)))
        mass = sum((weight for weight, _ in parsed), Decimal(0))
        if mass != 1:
            raise ValueError("joint scenario weights must sum exactly to one")
        settlement_mass = {key: Decimal(0) for key in ("WIN", "LOSS", "REFUND", "REDUCED_LEGS", "ALL_VOID")}
        valued = []
        for weight, outcomes in parsed:
            if "LOSS" in outcomes:
                gross, disposition, active = Decimal(0), "LOSS", None
            elif all(outcome == "WIN" for outcome in outcomes):
                gross, disposition, active = payouts[all_indices], "WIN", all_indices
            elif rules.push_policy == "REJECT":
                raise ValueError("PUSH_OR_VOID_UNSUPPORTED")
            elif rules.push_policy == "REFUND_TICKET":
                gross, disposition, active = entry_cost, "REFUND", None
            else:
                active = tuple(index for index, outcome in enumerate(outcomes) if outcome == "WIN")
                if active not in payouts:
                    raise ValueError(f"MISSING_REDUCED_LEG_PAYOUT:{active}")
                gross = payouts[active]
                disposition = "REDUCED_LEGS" if active else "ALL_VOID"
            net = gross - entry_cost - entry_fee
            settlement_mass[disposition] += weight
            valued.append({
                "probability": str(weight), "outcomes": list(outcomes),
                "settlement": disposition, "active_leg_indices": list(active) if active is not None else None,
                "gross_payout": str(gross), "net_payout": str(net),
            })
        expected_gross = sum((Decimal(row["probability"]) * Decimal(row["gross_payout"]) for row in valued), Decimal(0))
        expected_net = expected_gross - entry_cost - entry_fee
        variance = sum((Decimal(row["probability"]) * (Decimal(row["gross_payout"]) - expected_gross) ** 2 for row in valued), Decimal(0))
        with localcontext() as sd_context:
            sd_context.prec = 60
            standard_deviation = variance.sqrt()
        source = {
            "leg_ids": list(legs), "scenarios": [{"weight": str(weight), "outcomes": list(outcomes)} for weight, outcomes in parsed],
            "payout_by_active_legs": [{"indices": list(key), "gross_payout": str(value)} for key, value in sorted(payouts.items())],
            "cost": str(entry_cost), "fee": str(entry_fee),
            "rules": {"rules_id": rules.rules_id, "push_policy": rules.push_policy, "losing_leg_policy": "LOSE_TICKET", "fee_refund": False},
        }
        return {
            "schema": "sports.parlay_research_value.v1", "status": "RESEARCH_ONLY",
            "expected_gross_payout": str(expected_gross), "net_ev": str(expected_net),
            "net_payout_variance": str(variance), "net_payout_standard_deviation": str(standard_deviation),
            "sd_significant_digits": 60, "settlement_probabilities": {key: str(value) for key, value in settlement_mass.items()},
            "scenario_settlements": valued, "input": source,
            "input_sha256": hashlib.sha256(json.dumps(source, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
            "probability_source": "CALLER_SUPPLIED_JOINT_SCENARIOS", "predictive_validation": "NOT_ESTABLISHED",
            "rules_verified": False, "fees_verified": False, "selection_connected": False,
            "order_authorized": False, "action": "OFF", "dose": "0.0",
        }
