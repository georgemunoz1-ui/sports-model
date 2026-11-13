"""Illustrative, configurable order fees; no venue schedule is verified here."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, localcontext
from typing import Optional
from .numeric import InputError, decimal_value, decimal_text, whole_quantity


def _fee(raw: Decimal, minimum: Decimal, increment: Decimal) -> Decimal:
    return (max(raw, minimum) / increment).to_integral_value(rounding=ROUND_CEILING) * increment


@dataclass(frozen=True)
class FeeSchedule:
    rate: object = "0"
    minimum: object = "0"
    rounding_increment: object = "0.01"
    schedule_id: str = "illustrative-unverified"

    def __post_init__(self):
        for field in ("rate", "minimum", "rounding_increment"):
            object.__setattr__(self, field, decimal_value(getattr(self, field), field, minimum=0))
        if not self.rounding_increment:
            raise InputError("rounding_increment: must be positive")
        if not isinstance(self.schedule_id, str) or not self.schedule_id.strip():
            raise InputError("schedule_id: nonempty string required")

    def calculate(self, price, quantity) -> dict:
        p = decimal_value(price, "price", minimum=0, maximum=1)
        n = whole_quantity(quantity)
        with localcontext() as ctx:
            ctx.prec = 256
            raw = self.rate * n * p * (1 - p)
            total = _fee(raw, self.minimum, self.rounding_increment)
            return {"schedule_id": self.schedule_id, "quantity": n,
                    "price": decimal_text(p), "raw_fee": decimal_text(raw),
                    "total_fee": decimal_text(total), "per_contract_fee": decimal_text(total / n),
                    "venue_schedule_verified": False, "formula": "rate*n*p*(1-p)"}

    def total(self, price, quantity) -> Decimal:
        return Decimal(self.calculate(price, quantity)["total_fee"])


@dataclass(frozen=True)
class Tier:
    up_to: Optional[object]
    maker_rate: object = "0"
    taker_rate: object = "0"

    def __post_init__(self):
        if self.up_to is not None:
            object.__setattr__(self, "up_to", whole_quantity(self.up_to, "up_to"))
        for field in ("maker_rate", "taker_rate"):
            object.__setattr__(self, field, decimal_value(getattr(self, field), field, minimum=0))


@dataclass(frozen=True)
class TieredFees:
    schedule_id: str
    tiers: tuple[Tier, ...]
    minimum_order_fee: object = "0"
    rounding_increment: object = "0.01"

    def __post_init__(self):
        if not isinstance(self.schedule_id, str) or not self.schedule_id.strip():
            raise InputError("schedule_id: nonempty string required")
        if not isinstance(self.tiers, (list, tuple)) or not self.tiers or not all(isinstance(t, Tier) for t in self.tiers):
            raise InputError("tiers: nonempty Tier sequence required")
        object.__setattr__(self, "tiers", tuple(self.tiers))
        if self.tiers[-1].up_to is not None or any(t.up_to is None for t in self.tiers[:-1]):
            raise InputError("tiers: exactly one unbounded final tier required")
        bounds = [t.up_to for t in self.tiers[:-1]]
        if bounds != sorted(set(bounds)):
            raise InputError("tiers: strictly increasing bounds required")
        object.__setattr__(self, "minimum_order_fee", decimal_value(self.minimum_order_fee, "minimum_order_fee", minimum=0))
        object.__setattr__(self, "rounding_increment", decimal_value(self.rounding_increment, "rounding_increment", minimum=0))
        if not self.rounding_increment:
            raise InputError("rounding_increment: must be positive")

    def calculate(self, price, quantity, role, prior_volume=0) -> dict:
        p = decimal_value(price, "price", minimum=0, maximum=1)
        n = whole_quantity(quantity)
        prior = whole_quantity(prior_volume, "prior_volume", allow_zero=True)
        if role not in ("MAKER", "TAKER"):
            raise InputError("role: MAKER or TAKER required")
        slices = []
        position, remaining = prior, n
        with localcontext() as ctx:
            ctx.prec = 256
            raw = Decimal(0)
            for tier in self.tiers:
                take = remaining if tier.up_to is None else min(remaining, max(0, tier.up_to - position))
                if take:
                    rate = tier.maker_rate if role == "MAKER" else tier.taker_rate
                    piece = rate * take * p * (1 - p)
                    slices.append({"quantity": take, "rate": decimal_text(rate), "raw_fee": decimal_text(piece)})
                    raw += piece
                    position += take
                    remaining -= take
                if not remaining:
                    break
            total = _fee(raw, self.minimum_order_fee, self.rounding_increment)
            return {"schedule_id": self.schedule_id, "quantity": n, "price": decimal_text(p),
                    "role": role, "prior_volume": prior, "volume_unit": "CONTRACTS",
                    "slices": slices, "raw_fee": decimal_text(raw), "total_fee": decimal_text(total),
                    "per_contract_fee": decimal_text(total / n), "venue_schedule_verified": False}
