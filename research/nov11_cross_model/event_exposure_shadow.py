"""Research-only event-cluster exposure diagnostics.

Never computes portfolio variance across independent events by assuming leg independence.
Accepts a supplied common *event-level joint scenario* table only. It does not fit
joint distributions, invent prices/odds, register selections or authorize wagers.
"""
from __future__ import annotations

MODULE_ID = "event_exposure_shadow_v1"

from collections import defaultdict
import math

SCHEMA = "sports.event_exposure_shadow.v1"
SETTLEMENTS = {"WIN", "LOSS", "PUSH", "VOID"}


class ExposureError(ValueError):
    """Unsupported/malformed reference exposure; fail closed."""


def _real(value, field, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(float(value)):
        raise ExposureError(f"{field} must be a finite number")
    result = float(value)
    if positive and result <= 0:
        raise ExposureError(f"{field} must be positive")
    return result


def _payout(price):
    if isinstance(price, bool) or not isinstance(price, int) or (-100 < price < 100):
        raise ExposureError("American odds must be an integer <=-100 or >=100")
    return price / 100.0 if price >= 100 else 100.0 / abs(price)


def _classify(first, second, first_wins, second_wins):
    """Compare mutually exclusive *event* outcomes, not independent bet probabilities."""
    if not first_wins or not second_wins:
        return "SCENARIO_WITH_NO_WIN_SUPPORT"
    overlap = first_wins & second_wins
    same_orientation = first["orientation"] == second["orientation"]
    if not same_orientation and overlap:
        return "OPPOSING_MIDDLE_WINDOW"
    if first_wins == second_wins:
        return "DUPLICATE_WIN_SUPPORT"
    if first_wins < second_wins or second_wins < first_wins:
        return "NESTED_STACK" if same_orientation else "OPPOSING_OVERLAP"
    if overlap:
        return "OVERLAPPING_NONNESTED"
    return "OPPOSING_NO_MIDDLE" if not same_orientation else "DISJOINT_WIN_SUPPORT"


def review_event_exposure(positions, *, event_scenarios=None, action_authority=False,
                          official_stake_units=0.0):
    """One event, one declared joint probability law, N hypothetical contracts.

    Position fields: event_id, contract_id, orientation HOME/AWAY/OVER/UNDER/OTHER,
    market, american, reference_stake_units, optional settlements:{scenario_id:result}.
    Outcomes must be complete and consistent with the same joint scenario IDs.
    The caller must supply the scenario law; merely supplying marginal bet
    probabilities is not enough for correlation, middle or risk claims.
    """
    if action_authority is not False or official_stake_units != 0:
        raise ExposureError("shadow exposure cannot authorize wagers")
    if not isinstance(positions, list) or not positions:
        raise ExposureError("nonempty positions required")
    if not all(isinstance(p, dict) for p in positions):
        raise ExposureError("positions must be objects")
    ids = [p.get("contract_id") for p in positions]
    if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        raise ExposureError("unique nonempty contract_id required")
    events = {p.get("event_id") for p in positions}
    if len(events) != 1 or None in events or "" in events:
        raise ExposureError("each exposure review must cover one event")
    event = next(iter(events))
    stakes = {}
    rewards = {}
    for p in positions:
        if p.get("orientation") not in {"HOME", "AWAY", "OVER", "UNDER", "OTHER"}:
            raise ExposureError("explicit orientation required")
        if not p.get("market") or not isinstance(p["market"], str):
            raise ExposureError("market identity required")
        stakes[p["contract_id"]] = _real(p.get("reference_stake_units"), "reference_stake_units", positive=True)
        rewards[p["contract_id"]] = _payout(p.get("american"))
    result = {
        "schema": SCHEMA,
        "event_id": event,
        "n_contracts": len(positions),
        "reference_gross_risk_units": sum(stakes.values()),
        "research_only": True,
        "official_stake_units": 0.0,
        "action_authority": False,
        "event_cluster": True,
        "portfolio_cross_event_variance": None,
    }
    if event_scenarios is None:
        if any(p.get("settlements") for p in positions):
            raise ExposureError("settlements provided without a common event scenario law")
        result.update({
            "dependence_status": "UNASSESSED_NO_COMMON_JOINT_LAW",
            "pairwise_structure": None,
            "expected_event_return_units": None,
            "event_return_sd_units": None,
            "event_loss_probability": None,
            "event_worst_case_units": None,
        })
        return result
    if not isinstance(event_scenarios, dict) or event_scenarios.get("event_id") != event:
        raise ExposureError("joint scenario law must bind exact event_id")
    law_id = event_scenarios.get("law_id")
    if not isinstance(law_id, str) or not law_id:
        raise ExposureError("joint law identity required")
    scenario_rows = event_scenarios.get("scenarios")
    if not isinstance(scenario_rows, list) or not scenario_rows:
        raise ExposureError("nonempty joint scenario rows required")
    probs = {}
    for s in scenario_rows:
        if not isinstance(s, dict) or not isinstance(s.get("id"), str) or not s["id"]:
            raise ExposureError("each joint scenario requires an id")
        if s["id"] in probs:
            raise ExposureError("duplicate joint scenario")
        probability = _real(s.get("probability"), "scenario.probability")
        if probability < 0 or probability > 1:
            raise ExposureError("scenario probabilities must be in [0,1]")
        probs[s["id"]] = probability
    if not math.isclose(sum(probs.values()), 1.0, rel_tol=0, abs_tol=1e-9):
        raise ExposureError("joint scenario probabilities must sum to one")
    payouts = {scenario: 0.0 for scenario in probs}
    win_sets = {}
    for p in positions:
        settlements = p.get("settlements")
        if not isinstance(settlements, dict) or set(settlements) != set(probs):
            raise ExposureError("complete settlements for the common scenarios required")
        if not all(status in SETTLEMENTS for status in settlements.values()):
            raise ExposureError("only full win/loss/push/void are supported")
        key = p["contract_id"]
        wins = set()
        for scenario, status in settlements.items():
            if status == "WIN":
                payouts[scenario] += stakes[key] * rewards[key]
                wins.add(scenario)
            elif status == "LOSS":
                payouts[scenario] -= stakes[key]
            # PUSH and VOID refund the entire reference stake, so zero net P&L.
        win_sets[key] = wins
    pairwise=[]
    for i,a in enumerate(positions):
        for b in positions[i+1:]:
            pairwise.append({
                "first_contract_id": a["contract_id"],
                "second_contract_id": b["contract_id"],
                "relationship": _classify(a,b,win_sets[a["contract_id"]],win_sets[b["contract_id"]]),
            })
    ev = sum(probs[k]*payouts[k] for k in probs)
    variance = sum(probs[k]*(payouts[k]-ev)**2 for k in probs)
    result.update({
        "dependence_status": "COMMON_EVENT_LAW_SUPPLIED_NOT_INDEPENDENTLY_ATTESTED",
        "joint_law_id": law_id,
        "pairwise_structure": pairwise,
        "expected_event_return_units": ev,
        "event_return_sd_units": math.sqrt(max(variance,0.0)),
        "event_loss_probability": sum(probs[k] for k in probs if payouts[k] < -1e-12),
        "event_worst_case_units": min(payouts.values()),
        "event_best_case_units": max(payouts.values()),
        "scenario_returns": {key: {"probability": probs[key], "net_units": payouts[key]}
                             for key in sorted(probs)},
    })
    return result


def review_exposure_book(positions, *, event_scenarios=None, action_authority=False,
                         official_stake_units=0.0):
    """Aggregate *positions* by unique event without assigning cross-event risk.

    The sum of reference stakes is an accounting total, not a Kelly allocation.
    A same-event law can score the joint event; no assumption of independence
    between distinct games (or legs) is permitted by this interface.
    """
    if action_authority is not False or official_stake_units != 0:
        raise ExposureError("shadow book cannot authorize wagers")
    if not isinstance(positions, list):
        raise ExposureError("positions must be an array")
    groups = defaultdict(list)
    for pos in positions:
        if not isinstance(pos, dict):
            raise ExposureError("positions must be objects")
        groups[pos.get("event_id")].append(pos)
    laws = event_scenarios or {}
    if not isinstance(laws, dict):
        raise ExposureError("event_scenarios must be keyed by event_id")
    if set(laws) - set(groups):
        raise ExposureError("unused event scenario law is not an eligible event")
    reports = [review_event_exposure(group, event_scenarios=laws.get(event),
                                    action_authority=False, official_stake_units=0)
               for event,group in sorted(groups.items())]
    return {
        "schema": SCHEMA,
        "unique_events": len(reports),
        "contract_rows": len(positions),
        "event_reports": reports,
        "reference_gross_risk_units": sum(r["reference_gross_risk_units"] for r in reports),
        "cross_event_portfolio_ev": None,
        "cross_event_portfolio_sd": None,
        "cross_event_portfolio_risk_status": "NOT_ASSESSED_NO_MULTI_EVENT_JOINT_LAW",
        "official_stake_units": 0.0,
        "action_authority": False,
    }
