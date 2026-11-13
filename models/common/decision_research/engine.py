"""Pure binary-$1 contract decision arithmetic for engineering/research only.

Caller flags are assertions, not evidence of operational qualification. The
separate evidence bridge must resolve IDs and authority; this core cannot order.
"""
from collections.abc import Mapping
from decimal import Decimal, localcontext
from .numeric import InputError, decimal_value, decimal_text, whole_quantity

FLAGS = (
    "identity_valid", "settlement_verified", "state_aligned", "quote_fresh", "market_open",
    "dominated_by_executable_alternative", "execution_verified", "sufficient_size", "fees_verified",
    "valuation_qualified", "risk_limits_pass", "wagering_enabled",
)


def decide_payload(payload: dict) -> dict:
    result = {"schema": "research.binary_decision.v1", "disposition": "BLOCKED", "reasons": [],
              "findings": [], "order_authorized": False, "action": "OFF", "dose": 0,
              "qualification_source": "CALLER_ASSERTIONS_UNVERIFIED", "production_eligible": False,
              "conservative_net_ev": None}
    errors = []
    if not isinstance(payload, Mapping):
        result["reasons"] = result["findings"] = ["INVALID_INPUT: payload must be a mapping"]
        return result
    for name in FLAGS:
        if name not in payload or type(payload[name]) is not bool:
            errors.append(f"INVALID_INPUT: {name}: required boolean")
    values = {}
    fields = {"price": (0, 1), "total_entry_fee": (0, None), "required_ev_buffer": (0, None)}
    for name, (minimum, maximum) in fields.items():
        try:
            values[name] = decimal_value(payload.get(name), name, minimum, maximum)
        except InputError as exc:
            errors.append("INVALID_INPUT: " + str(exc))
    for name, allow_zero in (("quantity", False), ("available_quantity", True)):
        try:
            values[name] = None if name == "available_quantity" and payload.get(name) is None else whole_quantity(payload.get(name), name, allow_zero)
        except InputError as exc:
            errors.append("INVALID_INPUT: " + str(exc))
    try:
        values["expected_payout"] = None if payload.get("expected_payout") is None else decimal_value(payload["expected_payout"], "expected_payout", 0, 1)
    except InputError as exc:
        errors.append("INVALID_INPUT: " + str(exc))
    if errors:
        result["reasons"] = list(errors)
        result["findings"] = list(errors)
        return result
    gates = []
    hard = [reason for name, reason in (
        ("identity_valid", "IDENTITY_INVALID"), ("settlement_verified", "SETTLEMENT_UNVERIFIED"),
        ("state_aligned", "GAME_STATE_MISMATCH"), ("quote_fresh", "STALE_QUOTE"), ("market_open", "MARKET_NOT_OPEN"),
    ) if not payload[name]]
    gates.append(("BLOCKED", hard))
    gates.append(("PASS_NO_EDGE", ["DOMINATED_BY_ALTERNATIVE"] if payload["dominated_by_executable_alternative"] else []))
    execution = [reason for name, reason in (("execution_verified", "EXECUTION_UNVERIFIED"), ("fees_verified", "FEES_UNVERIFIED")) if not payload[name]]
    if not payload["sufficient_size"] or values["available_quantity"] is None or values["available_quantity"] < values["quantity"]:
        execution.append("INSUFFICIENT_OR_UNKNOWN_SIZE")
    gates.append(("VERIFY_QUOTE", execution))
    gates.append(("RESEARCH_ONLY", ["NO_QUALIFIED_VALUATION"] if not payload["valuation_qualified"] or values["expected_payout"] is None else []))
    if values["expected_payout"] is not None:
        with localcontext() as ctx:
            ctx.prec = 256
            # Compare total economics exactly before division for display. This
            # avoids a repeating per-contract fee changing strict-buffer gates.
            net_total = values["quantity"] * (values["expected_payout"] - values["price"]) - values["total_entry_fee"]
            net = net_total / values["quantity"]
            clears = net_total > values["quantity"] * values["required_ev_buffer"]
        result["conservative_net_ev"] = decimal_text(net)
        result["net_ev_total"] = decimal_text(net_total)
        gates.append(("PASS_NO_EDGE", [] if clears else ["EV_DOES_NOT_CLEAR_BUFFER"]))
    gates.append(("PASS_RISK_LIMIT", [] if payload["risk_limits_pass"] else ["EXPOSURE_OR_LIQUIDITY_LIMIT"]))
    gates.append(("ACTION_DISABLED", [] if payload["wagering_enabled"] else ["WAGERING_AUTHORITY_OFF"]))
    result["findings"] = [reason for _, reasons in gates for reason in reasons]
    for disposition, reasons in gates:
        if reasons:
            result["disposition"], result["reasons"] = disposition, reasons
            break
    else:
        result["disposition"] = "QUALIFIED_CANDIDATE"
    return result
