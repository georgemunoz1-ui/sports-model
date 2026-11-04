"""Mathematical binary-spread comparisons, separate from quote eligibility.

Opponent margin is opponent score minus selected-team score. Only half-point
integer-score contracts are supported. The caller/evidence bridge must establish
identical event, team, rules, payout unit, currency and current executable state.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR, localcontext
from collections.abc import Mapping
from .numeric import InputError, decimal_value, decimal_text, whole_quantity
from .fees import FeeSchedule


@dataclass(frozen=True)
class BinarySpread:
    name: str
    handicap: object
    buy_price: object
    entry_fee_per_contract: object = "0"

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise InputError("name: nonempty string required")
        object.__setattr__(self, "handicap", decimal_value(self.handicap, "handicap", -10000, 10000))
        object.__setattr__(self, "buy_price", decimal_value(self.buy_price, "buy_price", 0, 1))
        object.__setattr__(self, "entry_fee_per_contract", decimal_value(self.entry_fee_per_contract, "entry_fee_per_contract", 0))
        with localcontext() as ctx:
            ctx.prec = 256
            half_point = self.handicap - self.handicap.to_integral_value(rounding=ROUND_FLOOR)
        if half_point != Decimal("0.5"):
            raise InputError("half-point line required; push/quarter-line settlement needs a separate adapter")

    @property
    def all_in_cost(self) -> Decimal:
        with localcontext() as ctx:
            ctx.prec = 256
            return self.buy_price + self.entry_fee_per_contract


def payout(contract: BinarySpread, opponent_margin: int) -> Decimal:
    if type(opponent_margin) is not int:
        raise InputError("opponent_margin: integer required")
    return Decimal(int(Decimal(opponent_margin) < contract.handicap))


def _total_cost(contract, quantity, fees):
    if not isinstance(contract, BinarySpread):
        raise InputError("contract: BinarySpread required")
    if fees is not None and not isinstance(fees, FeeSchedule):
        raise InputError("fees: FeeSchedule required")
    if fees is not None and contract.entry_fee_per_contract:
        raise InputError("provide a fee schedule or fixed per-contract fee, not both")
    return quantity * contract.buy_price + (fees.total(contract.buy_price, quantity) if fees else quantity * contract.entry_fee_per_contract)


def compare_upgrade(candidate: BinarySpread, baseline: BinarySpread, quantity=1,
                    candidate_fees: FeeSchedule | None = None,
                    baseline_fees: FeeSchedule | None = None) -> dict:
    n = whole_quantity(quantity)
    with localcontext() as ctx:
        ctx.prec = 256
        cost_c = _total_cost(candidate, n, candidate_fees)
        cost_b = _total_cost(baseline, n, baseline_fees)
        a = int(candidate.handicap.to_integral_value(rounding=ROUND_FLOOR))
        b = int(baseline.handicap.to_integral_value(rounding=ROUND_FLOOR))
        # Every integer-score payoff region has a representative, including
        # both unbounded tails; never infer dominance from an arbitrary PMF.
        regions = sorted({a, a + 1, b, b + 1, min(a, b) - 1, max(a, b) + 2})
        differences = [n * (payout(candidate, m) - payout(baseline, m)) - (cost_c - cost_b) for m in regions]
        dominates = all(d >= 0 for d in differences) and any(d > 0 for d in differences)
        extra = list(range(b + 1, a + 1)) if a > b else []
        lost = list(range(a + 1, b + 1)) if b > a else []
        delta = (cost_c - cost_b) / n
        return {"schema": "research.binary_spread_comparison.v1", "quantity": n,
                "candidate_dominates": dominates, "dominates": dominates,
                "additional_winning_margins": extra, "lost_winning_margins": lost,
                "incremental_all_in_cost": decimal_text(delta),
                "required_added_probability": decimal_text(max(Decimal(0), delta)) if not lost else None,
                "candidate_total_cost": decimal_text(cost_c), "baseline_total_cost": decimal_text(cost_b),
                "outcome_region_representatives": regions,
                "net_payoff_difference_by_region": [decimal_text(d) for d in differences],
                "comparison_scope": "MATHEMATICAL_ONLY_IDENTITIES_UNVERIFIED",
                "order_authorized": False}


def upgrade(candidate_handicap, baseline_handicap, candidate_price, baseline_price,
            quantity=1, candidate_fees=None, baseline_fees=None) -> dict:
    return compare_upgrade(BinarySpread("candidate", candidate_handicap, candidate_price),
                           BinarySpread("baseline", baseline_handicap, baseline_price),
                           quantity, candidate_fees, baseline_fees)


def expected_profit(contract: BinarySpread, margin_pmf: Mapping[int, object], quantity=1,
                    fees: FeeSchedule | None = None) -> Decimal:
    n = whole_quantity(quantity)
    if not isinstance(margin_pmf, Mapping) or not margin_pmf:
        raise InputError("margin_pmf: nonempty mapping required")
    with localcontext() as ctx:
        ctx.prec = 256
        probabilities = []
        expectation = Decimal(0)
        for margin, value in margin_pmf.items():
            p = decimal_value(value, "probability", 0, 1)
            probabilities.append(p)
            expectation += p * payout(contract, margin)
        if sum(probabilities) != Decimal(1):
            raise InputError("margin_pmf: probability mass must equal one")
        return n * expectation - _total_cost(contract, n, fees)


def incremental_ev(candidate: BinarySpread, baseline: BinarySpread, margin_pmf,
                   quantity=1, candidate_fees=None, baseline_fees=None) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 256
        return expected_profit(candidate, margin_pmf, quantity, candidate_fees) - expected_profit(baseline, margin_pmf, quantity, baseline_fees)
