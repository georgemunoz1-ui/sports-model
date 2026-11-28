"""Strict decimal parsing shared by research calculations.

No floats, booleans, non-finite numbers, or ambient-context rounding are accepted.
"""
from decimal import Decimal, InvalidOperation
from typing import Any


class InputError(ValueError):
    """Malformed research input; never coerced into a passing value."""


def decimal_value(value: Any, name: str, minimum=None, maximum=None) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, str, int)):
        raise InputError(f"{name}: expected Decimal, decimal string, or integer")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise InputError(f"{name}: invalid decimal") from exc
    if not result.is_finite():
        raise InputError(f"{name}: finite value required")
    # Bound resource use and arithmetic precision explicitly. Financial fixtures
    # have far smaller magnitudes; rejection is preferable to silent rounding.
    if len(result.as_tuple().digits) > 40 or abs(result.as_tuple().exponent) > 30:
        raise InputError(f"{name}: decimal precision exceeds supported range")
    if minimum is not None and result < Decimal(minimum):
        raise InputError(f"{name}: below minimum {minimum}")
    if maximum is not None and result > Decimal(maximum):
        raise InputError(f"{name}: above maximum {maximum}")
    return result


def whole_quantity(value: Any, name: str = "quantity", allow_zero: bool = False) -> int:
    result = decimal_value(value, name, minimum=0 if allow_zero else 1)
    if result != result.to_integral_value():
        raise InputError(f"{name}: whole quantity required")
    if result > 10**12:
        raise InputError(f"{name}: quantity exceeds supported range")
    return int(result)


def decimal_text(value: Decimal) -> str:
    return format(value, "f")
