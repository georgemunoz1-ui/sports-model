"""Arithmetic audits of supplied projections, never a forecasting/selection engine.

Hashing the source establishes byte identity, not authorship, extraction accuracy,
point-in-time availability, roster validity, sampler replay or predictive skill.
"""
from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path

from models.common import discrete_research as D


def _keys(row, allowed):
    if not isinstance(row, dict) or set(row) - set(allowed):
        raise ValueError("PROJECTION_AUDIT_FIELDS_INVALID")


def _rows(rows, key, *, nonempty=False):
    if not isinstance(rows, list) or (nonempty and not rows):
        raise ValueError("PROJECTION_AUDIT_ROWS_REQUIRED")
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("PROJECTION_AUDIT_OBJECT_REQUIRED")
        name = D.identity(row.get(key), key.upper())
        if name in seen:
            raise ValueError("PROJECTION_AUDIT_DUPLICATE_" + key.upper())
        seen.add(name)
    return rows


def _number(value, *, nonnegative=True):
    value = D.finite(value)
    if nonnegative and value < 0:
        raise ValueError("PROJECTION_AUDIT_NEGATIVE_VALUE")
    return value


def _source(spec, root):
    _keys(spec, {"path", "sha256"})
    root = Path(root).resolve()
    relative = Path(D.identity(spec.get("path"), "SOURCE_PATH"))
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root):
        raise ValueError("PROJECTION_AUDIT_SOURCE_OUTSIDE_PACKET")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != D.source_hash(spec.get("sha256")):
        raise ValueError("PROJECTION_AUDIT_SOURCE_HASH_MISMATCH")
    return {**spec, "size_bytes": len(raw), "verification": "BYTES_MATCH; CONTENT_CLAIMS_NOT_AUTHENTICATED"}


def _minutes(row, league):
    _keys(row, {"team_id", "component_id", "basis", "players"})
    D.identity(row.get("team_id"), "TEAM_ID")
    D.identity(row.get("component_id"), "COMPONENT_ID")
    if league not in {"nba", "wnba"} or row.get("basis") != "REGULATION":
        raise ValueError("PROJECTION_AUDIT_MINUTES_SCOPE_UNSUPPORTED")
    maximum = 48 if league == "nba" else 40
    players = _rows(row.get("players"), "entity_id", nonempty=True)
    findings = []
    for player in players:
        _keys(player, {"entity_id", "minutes", "reported_availability"})
        minutes = _number(player.get("minutes"))
        availability = player.get("reported_availability", "UNKNOWN")
        if availability not in {"IN", "OUT", "UNKNOWN"}:
            raise ValueError("PROJECTION_AUDIT_AVAILABILITY_INVALID")
        if minutes > maximum:
            findings.append("PLAYER_MINUTES_EXCEED_REGULATION:" + player["entity_id"])
        if availability == "OUT" and minutes > 0:
            findings.append("REPORTED_OUT_PLAYER_HAS_MINUTES:" + player["entity_id"])
    total = math.fsum(p["minutes"] for p in players)
    if not math.isclose(total, maximum * 5, rel_tol=0, abs_tol=1e-6):
        findings.append("TEAM_MINUTES_BUDGET_MISMATCH")
    return {**copy.deepcopy(row), "sum_minutes": total, "required_minutes": maximum * 5,
            "arithmetic_status": "FAIL" if findings else "PASS", "findings": findings,
            "roster_and_minutes_validity": "NOT_ESTABLISHED", "numerical_use": "NOT_ESTABLISHED"}


def _allocation(row):
    _keys(row, {"check_id", "unit", "source_component_id", "target_component_id",
                "terms", "target", "rounding_step"})
    for key in ("check_id", "unit", "source_component_id", "target_component_id"):
        D.identity(row.get(key), key.upper())
    terms = _rows(row.get("terms"), "entity_id", nonempty=True)
    for term in terms:
        _keys(term, {"entity_id", "value"})
        _number(term.get("value"))
    target = _number(row.get("target"))
    step = _number(row.get("rounding_step", 0))
    if step not in {0, .001, .01, .1, 1}:
        raise ValueError("PROJECTION_AUDIT_ROUNDING_STEP_INVALID")
    # Each displayed term and target may differ by half a rounding unit.
    tolerance = (len(terms) + 1) * step / 2
    total = math.fsum(t["value"] for t in terms)
    gap = total - target
    comparable = row["source_component_id"] == row["target_component_id"]
    status = ("NOT_COMPARABLE_COMPONENTS" if not comparable else
              "PASS" if abs(gap) <= tolerance + 1e-9 else "FAIL")
    return {**copy.deepcopy(row), "sum_terms": total, "sum_minus_target": gap,
            "rounding_tolerance": tolerance, "arithmetic_status": status,
            "note": "Different component totals must not be represented as one coherent player/game projection." if not comparable else
                    "Arithmetic reconciliation only; the input values and their predictive validity are unverified."}


def _contract(contract, *, event_id, league):
    _keys(contract, {"event_id", "league", "product", "settlement", "side", "line"})
    if contract.get("event_id") != event_id or contract.get("league") != league:
        raise ValueError("PROJECTION_AUDIT_CONTRACT_EVENT_MISMATCH")
    product = contract.get("product")
    D.scope(league, "margin" if product == "winner" else product, contract.get("settlement"))
    if product == "winner":
        if contract.get("line") is not None or contract.get("side") not in {"HOME", "AWAY", "DRAW"}:
            raise ValueError("PROJECTION_AUDIT_WINNER_CONTRACT_INVALID")
        if contract["side"] == "DRAW" and not D.SETTLEMENTS[league][contract["settlement"]]:
            raise ValueError("PROJECTION_AUDIT_DRAW_NOT_SUPPORTED")
    else:
        _number(contract.get("line"), nonnegative=product == "total")
        sides = {"HOME", "AWAY"} if product == "margin" else {"OVER", "UNDER"}
        if contract.get("side") not in sides:
            raise ValueError("PROJECTION_AUDIT_SIDE_INVALID")


def _sensitivity(row, *, event_id, league):
    _keys(row, {"sensitivity_id", "contract", "variants"})
    D.identity(row.get("sensitivity_id"), "SENSITIVITY_ID")
    _contract(row.get("contract"), event_id=event_id, league=league)
    variants = _rows(row.get("variants"), "method_id", nonempty=True)
    if len(variants) < 2:
        raise ValueError("PROJECTION_AUDIT_TWO_METHODS_REQUIRED")
    values = []
    for variant in variants:
        _keys(variant, {"method_id", "probability", "contract"})
        # Bind each number to its own contract; line changes are not method sensitivity.
        if variant.get("contract") != row["contract"]:
            raise ValueError("PROJECTION_AUDIT_METHOD_CONTRACT_MISMATCH")
        p = _number(variant.get("probability"))
        if p > 1:
            raise ValueError("PROJECTION_AUDIT_PROBABILITY_INVALID")
        values.append(p)
    return {**copy.deepcopy(row), "method_count_supplied": len(values),
            "minimum_probability": min(values), "maximum_probability": max(values),
            "range_percentage_points": 100 * (max(values) - min(values)),
            "probability_of_failure": None, "predictive_confidence_interval": None,
            "interpretation": "UNWEIGHTED_NAMED_METHOD_SENSITIVITY; NOT A RANDOM_SAMPLE_OR_CALIBRATED_INTERVAL",
            "sampler_replay": "NOT_PERFORMED", "predictive_validation": "NOT_ESTABLISHED"}


def audit_projection(spec, *, event_id, league, root):
    """Validate and summarize caller-extracted claims without trusting them as data."""
    _keys(spec, {"audit_id", "source_artifact", "minutes_budgets", "allocation_checks", "method_sensitivities"})
    D.identity(spec.get("audit_id"), "AUDIT_ID")
    source = _source(spec.get("source_artifact"), root)
    budgets = _rows(spec.get("minutes_budgets", []), "team_id")
    allocations = _rows(spec.get("allocation_checks", []), "check_id")
    sensitivities = _rows(spec.get("method_sensitivities", []), "sensitivity_id")
    if not budgets and not allocations and not sensitivities:
        raise ValueError("PROJECTION_AUDIT_CHECKS_REQUIRED")
    seen = set()
    for budget in budgets:
        for player in _rows(budget.get("players"), "entity_id", nonempty=True):
            key = (budget.get("component_id"), player["entity_id"])
            if key in seen:
                raise ValueError("PROJECTION_AUDIT_PLAYER_ON_TWO_TEAMS")
            seen.add(key)
    result = {"audit_id": spec["audit_id"], "source_artifact": source,
              "minutes_budgets": [_minutes(b, league) for b in budgets],
              "allocation_checks": [_allocation(a) for a in allocations],
              "method_sensitivities": [_sensitivity(s, event_id=event_id, league=league) for s in sensitivities],
              "scope": "SUPPLIED_CLAIM_ARITHMETIC_ONLY", "numerical_forecast_modified": False,
              "source_facts_verified": False, "point_in_time_verified": False,
              "action_authority": False, "predictive_validation": "NOT_ASSESSED"}
    result["arithmetic_failures"] = sum(x["arithmetic_status"] == "FAIL" for x in
                                        result["minutes_budgets"] + result["allocation_checks"])
    return result
