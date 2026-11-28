"""Engineering fixtures only; no observed sports probabilities or venue rules."""

from decimal import Decimal, localcontext
import json

import pytest

from models.common.decision_research.parlays import JointScenario, ParlayRules, parlay_value

D = Decimal


def value(scenarios=None, policy="REJECT", payouts=None, **kwargs):
    return parlay_value(
        leg_ids=kwargs.pop("leg_ids", ["a", "b"]),
        scenarios=scenarios if scenarios is not None else [JointScenario("0.6", ("WIN", "WIN")), JointScenario("0.4", ("LOSS", "LOSS"))],
        payout_by_active_legs=payouts if payouts is not None else {(0, 1): "1"},
        cost=kwargs.pop("cost", "0.40"), fee=kwargs.pop("fee", "0.01"),
        rules=kwargs.pop("rules", ParlayRules("fixture-only", policy)), **kwargs,
    )


def test_supplied_correlated_joint_is_not_product_of_marginals():
    result = value()
    assert D(result["expected_gross_payout"]) == D("0.6")
    assert D(result["net_ev"]) == D("0.19")
    assert D(result["net_payout_variance"]) == D("0.24")
    assert D(result["settlement_probabilities"]["WIN"]) == D("0.6")
    assert D(result["expected_gross_payout"]) != D("0.6") ** 2
    assert result["order_authorized"] is False
    assert result["selection_connected"] is False
    assert result["rules_verified"] is False
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("policy", ["REJECT", "REFUND_TICKET", "REMOVE_LEG"])
def test_losing_leg_overrides_push_and_void(policy):
    result = value([JointScenario("1", ("LOSS", "VOID"))], policy)
    assert D(result["net_ev"]) == D("-0.41")
    assert D(result["settlement_probabilities"]["LOSS"]) == 1


@pytest.mark.parametrize("outcomes", [("WIN", "PUSH"), ("VOID", "VOID"), ("VOID", "PUSH")])
def test_reject_policy_refuses_nonlosing_push_or_void(outcomes):
    with pytest.raises(ValueError, match="PUSH_OR_VOID_UNSUPPORTED"):
        value([JointScenario("1", outcomes)])


def test_refund_does_not_refund_fee():
    result = value([JointScenario("1", ("WIN", "PUSH"))], "REFUND_TICKET")
    assert D(result["expected_gross_payout"]) == D("0.40")
    assert D(result["net_ev"]) == D("-0.01")
    assert D(result["settlement_probabilities"]["REFUND"]) == 1


def test_surviving_leg_identity_changes_payout():
    result = value([JointScenario("0.5", ("WIN", "PUSH")), JointScenario("0.5", ("VOID", "WIN"))], "REMOVE_LEG", {(0, 1): "1", (0,): "0.65", (1,): "0.80"})
    assert D(result["expected_gross_payout"]) == D("0.725")
    assert D(result["net_ev"]) == D("0.315")
    assert D(result["settlement_probabilities"]["REDUCED_LEGS"]) == 1


def test_all_void_remove_requires_explicit_empty_key():
    scenarios = [JointScenario("1", ("VOID", "PUSH"))]
    with pytest.raises(ValueError, match="MISSING_REDUCED_LEG_PAYOUT"):
        value(scenarios, "REMOVE_LEG")
    result = value(scenarios, "REMOVE_LEG", {(0, 1): "1", (): "0.40"})
    assert D(result["net_ev"]) == D("-0.01")
    assert D(result["settlement_probabilities"]["ALL_VOID"]) == 1


def test_missing_surviving_tuple_refuses():
    with pytest.raises(ValueError, match="MISSING_REDUCED_LEG_PAYOUT"):
        value([JointScenario("1", ("WIN", "VOID"))], "REMOVE_LEG", {(0, 1): "1", (1,): ".8"})


@pytest.mark.parametrize("bad", [True, False, 0.5, "NaN", "Infinity", "-Infinity", "-0.1", None, "garbage"])
def test_invalid_money_rejected(bad):
    with pytest.raises(ValueError):
        value(cost=bad)


@pytest.mark.parametrize("bad", [True, 0.5, "NaN", "Infinity", "-0.1", "1.1", None])
def test_invalid_probability_rejected(bad):
    with pytest.raises(ValueError):
        value([JointScenario(bad, ("WIN", "WIN"))])


@pytest.mark.parametrize("weights", [("0.4", "0.5"), ("0.7", "0.4"), ("0", "0"), ("1", "0.0000000000000000000000000001")])
def test_probability_mass_must_equal_one_exactly(weights):
    with pytest.raises(ValueError, match="sum exactly"):
        value([JointScenario(weights[0], ("WIN", "WIN")), JointScenario(weights[1], ("LOSS", "LOSS"))])


@pytest.mark.parametrize("outcomes", [("HALF_WIN", "WIN"), ("CASHOUT", "WIN"), (True, "WIN"), ("WIN",), "WIN", ("WIN", "LOSS", "WIN")])
def test_unsupported_or_malformed_outcomes(outcomes):
    with pytest.raises(ValueError):
        value([JointScenario("1", outcomes)])


@pytest.mark.parametrize("key", [(1, 0), (0, 0), (True,), (-1,), (2,), "0,1", (0.0,)])
def test_malformed_payout_index_mapping(key):
    with pytest.raises(ValueError, match="payout key"):
        value(payouts={(0, 1): "1", key: "0.5"})


@pytest.mark.parametrize("legs", [[], "a", ["a", "a"], ["", "b"], [True, "b"], [" a", "b"]])
def test_leg_ids_must_be_distinct_actual_strings(legs):
    with pytest.raises(ValueError):
        value(leg_ids=legs)


@pytest.mark.parametrize("rules", [None, ParlayRules("", "REJECT"), ParlayRules("fixture", "IGNORE"), ParlayRules(True, "REJECT"), ParlayRules("fixture", [])])
def test_rules_must_be_named_and_supported(rules):
    with pytest.raises(ValueError):
        value(rules=rules)


def test_missing_full_payout_and_negative_payout_refuse():
    with pytest.raises(ValueError, match="full-ticket"):
        value(payouts={})
    with pytest.raises(ValueError, match="nonnegative"):
        value(payouts={(0, 1): "-1"})


def test_precision_bound_rejects_instead_of_rounding_mass():
    with pytest.raises(ValueError, match="maximum 28"):
        value([JointScenario("1", ("WIN", "WIN")), JointScenario("1e-100", ("LOSS", "LOSS"))])


def test_result_does_not_depend_on_caller_decimal_precision():
    expected = value()
    with localcontext() as context:
        context.prec = 2
        actual = value()
    assert actual == expected


def test_repeat_is_deterministic_and_inputs_bound():
    first = value()
    assert first == value()
    changed = value(fee="0.02")
    assert changed["input_sha256"] != first["input_sha256"]
    assert D(changed["net_payout_variance"]) == D(first["net_payout_variance"])
    assert D(changed["net_ev"]) == D(first["net_ev"]) - D("0.01")


def test_zero_probability_malformed_settlement_does_not_bypass_rules():
    with pytest.raises(ValueError, match="PUSH_OR_VOID_UNSUPPORTED"):
        value([JointScenario("1", ("WIN", "WIN")), JointScenario("0", ("WIN", "PUSH"))])


def test_partition_covers_all_declared_remove_leg_outcomes():
    result = value([
        JointScenario("0.4", ("WIN", "WIN")), JointScenario("0.2", ("LOSS", "VOID")),
        JointScenario("0.3", ("WIN", "PUSH")), JointScenario("0.1", ("VOID", "VOID")),
    ], "REMOVE_LEG", {(0, 1): "1", (0,): "0.6", (): "0.4"})
    assert sum(map(D, result["settlement_probabilities"].values())) == 1
    assert D(result["expected_gross_payout"]) == D("0.62")
    assert D(result["net_ev"]) == D("0.21")
