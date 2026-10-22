"""Presentation-only research disclosures. Never select wagers or alter forecasts.

Reported probabilities, retained-draw arithmetic, sampler replay and predictive
validation are separate evidence levels. No caller flag can promote one to another.
"""
from __future__ import annotations

import copy
import hashlib
import html
import json
import math
from pathlib import Path

import numpy as np

from models.common import discrete_research as D
from pipelines.cards.projection_audits import audit_projection

INPUT_SCHEMA = "sports.card_disclosures.input.v1"
REPORT_SCHEMA = "sports.card_disclosures.research.v1"


def _object(value, code):
    if not isinstance(value, dict):
        raise ValueError(code)
    return value


def _list(value, code):
    if not isinstance(value, list):
        raise ValueError(code)
    return value


def _unique(rows, key):
    seen = set()
    for row in _list(rows, "DISCLOSURE_LIST_REQUIRED"):
        _object(row, "DISCLOSURE_OBJECT_REQUIRED")
        name = D.identity(row.get(key), key.upper())
        if name in seen:
            raise ValueError("DUPLICATE_" + key.upper())
        seen.add(name)


def _keys(value, allowed):
    if set(value) - set(allowed):
        raise ValueError("UNSUPPORTED_DISCLOSURE_FIELD:" + ",".join(sorted(set(value) - set(allowed))))


def _file(root, spec):
    _object(spec, "ARTIFACT_REFERENCE_REQUIRED")
    _keys(spec, {"path", "sha256"})
    root = Path(root).resolve()
    path = (root / D.identity(spec.get("path"), "ARTIFACT_PATH")).resolve()
    if not path.is_relative_to(root):
        raise ValueError("ARTIFACT_PATH_OUTSIDE_PACKET")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != D.source_hash(spec.get("sha256")):
        raise ValueError("DISCLOSURE_ARTIFACT_HASH_MISMATCH")
    return json.loads(data)


def _source(row, cutoff):
    D.source_hash(row.get("source_sha256"))
    if not D.stamp(row.get("observed_at_utc")) <= D.stamp(row.get("retrieved_at_utc")) <= D.stamp(cutoff):
        raise ValueError("DISCLOSURE_SOURCE_AFTER_CUTOFF")


def _scenario(scenario, row, cutoff, root, league):
    _keys(scenario, {"scenario_id", "conditions", "rationale", "distribution_artifact"})
    D.identity(scenario.get("scenario_id"), "SCENARIO_ID")
    D.identity(scenario.get("rationale"), "SCENARIO_RATIONALE")
    conditions = scenario.get("conditions")
    _unique(conditions, "entity_id")
    if not conditions:
        raise ValueError("SCENARIO_CONDITIONS_REQUIRED")
    for condition in conditions:
        _keys(condition, {"entity_id", "availability"})
        if condition.get("availability") not in {"IN", "OUT"}:
            raise ValueError("SCENARIO_AVAILABILITY_INVALID")
    result = copy.deepcopy(scenario)
    result.update(weight=None, probability_of_playing=None,
                  interpretation="CONDITIONAL_NOT_AVAILABILITY_WEIGHTED",
                  execution_status="NOT_RUN", predictive_validation="NOT_ASSESSED")
    if scenario.get("distribution_artifact"):
        distribution = _object(_file(root, scenario["distribution_artifact"]), "SCENARIO_ARTIFACT_OBJECT_REQUIRED")
        x, p = D.validate(distribution)
        if distribution["league"] != league.lower():
            raise ValueError("SCENARIO_LEAGUE_MISMATCH")
        provenance = _object(distribution["provenance"], "SCENARIO_PROVENANCE_OBJECT_REQUIRED")
        expected = {"event_id": row["event_id"], "cutoff": cutoff,
                    "parent_model_id": row["model_id"],
                    "base_input_sha256": row["input_snapshot_hash"],
                    "scenario_id": scenario["scenario_id"],
                    "scenario_conditions_sha256": D.digest(conditions)}
        if any(provenance.get(k) != v for k, v in expected.items()):
            raise ValueError("SCENARIO_PARENT_OR_CONDITION_MISMATCH")
        result.update(execution_status="ARTIFACT_INSPECTED", model_id=distribution["model_id"],
                      product=distribution["product"], settlement=distribution["settlement"],
                      conditional_mean=float(np.dot(x, p)),
                      distribution_sha256=distribution["distribution_sha256"])
    return result


def event_disclosure(row, cutoff, supplied=None, root=Path("."), *, league):
    supplied = copy.deepcopy(supplied or {})
    reasons = [{"code": "WAGERING_AUTHORITY_OFF", "detail": "Research output; no wager is authorized."},
               {"code": "MARKET_VALUE_NOT_EVALUATED", "detail": "This disclosure layer does not qualify a price or betting edge."},
               {"code": "PREDICTIVE_QUALIFICATION_NOT_ASSESSED", "detail": "Disclosures do not establish predictive qualification."}]
    for warning in row.get("warnings", []):
        reasons.append({"code": "PARENT_WARNING", "detail": str(warning)})
    result = {"event_id": row["event_id"], "parent_model_id": row.get("model_id"),
              "known_inputs": [], "unknown_inputs": [], "assumptions": [],
              "availability_scenarios": [], "projection_audits": [], "decision": "PASS", "pass_reasons": reasons,
              "action_authority": False, "numerical_forecast_modified": False}
    if row.get("forecast_status") != "FORECAST_GENERATED":
        reasons.append({"code": "PARENT_NOT_FORECAST", "detail": row.get("forecast_status", "UNKNOWN")})
    if not supplied:
        result["unknown_inputs"].append({"name": "availability_evidence",
            "reason": "No structured availability disclosure supplied; numerical use is not assessed here."})
        return result
    _keys(supplied, {"event_id", "parent_model_id", "parent_input_sha256", "known_inputs",
                     "unknown_inputs", "assumptions", "availability_scenarios", "pass_reasons", "projection_audits"})
    if (supplied.get("event_id") != row["event_id"] or
            supplied.get("parent_model_id") != row.get("model_id") or
            D.source_hash(supplied.get("parent_input_sha256")) != row.get("input_snapshot_hash")):
        raise ValueError("DISCLOSURE_PARENT_MISMATCH")
    audits = supplied.get("projection_audits", [])
    _unique(audits, "audit_id")
    result["projection_audits"] = [audit_projection(a, event_id=row["event_id"], league=league.lower(), root=root) for a in audits]
    if any(a["arithmetic_failures"] for a in result["projection_audits"]):
        reasons.append({"code": "PROJECTION_ARITHMETIC_FAILURE", "detail": "Supplied minutes/allocation claims do not reconcile; forecasts were not changed."})
    names = set()
    for group in ("known_inputs", "unknown_inputs", "assumptions"):
        records = supplied.get(group, [])
        _unique(records, "name")
        for item in records:
            if item["name"] in names:
                raise ValueError("INPUT_KNOWLEDGE_STATE_CONFLICT")
            names.add(item["name"])
            if group == "known_inputs":
                _keys(item, {"name", "value", "source_sha256", "observed_at_utc", "retrieved_at_utc", "input_path"})
                if "value" not in item or item["value"] is None:
                    raise ValueError("KNOWN_INPUT_VALUE_REQUIRED")
                _source(item, cutoff)
                item["source_verification"] = "REFERENCE_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED"
                item["numerical_use"] = "NOT_ESTABLISHED"
                if item.get("input_path"):
                    value = row.get("model_input_snapshot")
                    for key in _list(item["input_path"], "INPUT_PATH_LIST_REQUIRED"):
                        value = _object(value, "PARENT_INPUT_PATH_MISMATCH").get(key)
                    if D.digest(value) != D.digest(item["value"]):
                        raise ValueError("PARENT_INPUT_VALUE_MISMATCH")
                    item["numerical_use"] = "BOUND_TO_PARENT_INPUT_NOT_CONSUMPTION_PROOF"
            elif group == "unknown_inputs":
                _keys(item, {"name", "reason"})
                D.identity(item.get("reason"), "UNKNOWN_REASON")
            else:
                _keys(item, {"name", "value", "rationale"})
                if "value" not in item or item["value"] is None:
                    raise ValueError("ASSUMPTION_VALUE_REQUIRED")
                D.identity(item.get("rationale"), "ASSUMPTION_RATIONALE")
                item["numerical_use"] = "NOT_ESTABLISHED"
            result[group].append(item)
    scenarios = supplied.get("availability_scenarios", [])
    _unique(scenarios, "scenario_id")
    result["availability_scenarios"] = [_scenario(s, row, cutoff, root, league) for s in scenarios]
    if scenarios:
        reasons.append({"code": "CONDITIONAL_SCENARIOS_UNWEIGHTED",
                        "detail": "Scenario outcomes do not imply probabilities of availability."})
    if result["unknown_inputs"]:
        reasons.append({"code": "UNKNOWN_INPUTS_DISCLOSED", "detail": "See explicitly unknown inputs."})
    extra = supplied.get("pass_reasons", [])
    _unique(extra, "code")
    for item in extra:
        _keys(item, {"code", "detail", "evidence_ref"})
        D.identity(item.get("detail"), "PASS_REASON_DETAIL")
        D.identity(item.get("evidence_ref"), "PASS_EVIDENCE_REFERENCE")
        reasons.append({**item, "evidence_status": "SUPPLIED_NOT_INDEPENDENTLY_VERIFIED"})
    return result


def _constraint(leg):
    """Full-win thresholds, including both halves of MLS quarter contracts."""
    D.scope(leg["league"], leg["product"], leg["settlement"])
    line = D.finite(leg["line"])
    parts = D._line_parts(line, leg["league"])
    side = leg["side"]
    if leg["product"] == "margin" and side in {"HOME", "AWAY"}:
        return ("gt", -min(parts)) if side == "HOME" else ("lt", -max(parts))
    if leg["product"] == "total" and side in {"OVER", "UNDER"} and min(parts) >= 0:
        return ("gt", max(parts)) if side == "OVER" else ("lt", min(parts))
    raise ValueError("CONTRACT_SIDE_OR_LINE_INVALID")


def parlay_disclosure(spec, rows, root=Path("."), *, cutoff, league):
    _object(spec, "PARLAY_OBJECT_REQUIRED")
    _keys(spec, {"parlay_id", "legs", "reported_joint_probability", "report_source_sha256", "joint_draw_artifact"})
    D.identity(spec.get("parlay_id"), "PARLAY_ID")
    legs = copy.deepcopy(spec.get("legs"))
    _unique(legs, "leg_id")
    if not legs:
        raise ValueError("PARLAY_LEGS_REQUIRED")
    groups, bindings, constraints = {}, {}, {}
    for leg in legs:
        _keys(leg, {"leg_id", "event_id", "model_id", "league", "product", "settlement", "side", "line"})
        if leg["event_id"] not in rows:
            raise ValueError("PARLAY_EVENT_NOT_IN_CARD")
        if leg["league"] != league.lower():
            raise ValueError("PARLAY_LEAGUE_MISMATCH")
        D.identity(leg.get("model_id"), "LEG_MODEL_ID")
        direction, threshold = _constraint(leg)
        binding = {k: leg[k] for k in ("event_id", "model_id", "league", "product", "settlement")}
        key = D.digest(binding)
        bindings[key] = binding
        constraints[leg["leg_id"]] = (key, direction, threshold)
        group = groups.setdefault((key, direction), [])
        group.append((threshold, leg["leg_id"]))
    redundant, effective = [], []
    for (key, direction), group in sorted(groups.items()):
        # Tie-break identical legs by ID, independent of input ordering.
        group.sort(key=lambda pair: ((-pair[0] if direction == "gt" else pair[0]), pair[1]))
        effective.append(group[0][1])
        redundant.extend({"leg_id": lid, "implied_by": group[0][1],
                          "proof": "NESTED_FULL_WIN_THRESHOLD_SAME_VARIABLE"} for _, lid in group[1:])
    contradictory = []
    for key in bindings:
        lower = max((x[0] for x in groups.get((key, "gt"), [])), default=-math.inf)
        upper = min((x[0] for x in groups.get((key, "lt"), [])), default=math.inf)
        # All supported sports settle integer margins/totals.
        if math.isfinite(lower) and math.isfinite(upper) and math.floor(lower) + 1 > math.ceil(upper) - 1:
            contradictory.append(bindings[key])
    result = {"parlay_id": spec["parlay_id"], "legs": legs, "nominal_leg_count": len(legs),
              "effective_constraint_count": len(effective), "effective_leg_ids": sorted(effective),
              "redundant_legs": redundant, "contradictory_constraints": contradictory,
              "constraint_reduction_scope": "SAME_VARIABLE_NESTED_THRESHOLDS_ONLY",
              "probability_target": "ALL_LEGS_FULL_WIN_UNCONDITIONAL",
              "push_and_half_win_treatment": "NOT_ALL_FULL_WIN; no payout or void repricing",
              "reported_joint_probability": None, "recomputed_joint_probability": None,
              "naive_independent_product": None, "dependence_effect": None,
              "intersection_status": "NOT_PROVIDED", "sampler_replay_status": "NOT_PERFORMED",
              "predictive_validation": "NOT_ESTABLISHED", "sportsbook_acceptance": "UNVERIFIED",
              "offered_odds": None, "expected_value": None, "decision": "PASS",
              "pass_reasons": ["WAGERING_AUTHORITY_OFF", "PREDICTIVE_VALIDATION_NOT_ESTABLISHED",
                               "PARLAY_PRICE_AND_ACCEPTANCE_UNVERIFIED"], "action_authority": False}
    if spec.get("reported_joint_probability") is not None:
        p = D.finite(spec["reported_joint_probability"])
        if not 0 <= p <= 1:
            raise ValueError("JOINT_PROBABILITY_INVALID")
        D.source_hash(spec.get("report_source_sha256"))
        result.update(reported_joint_probability=p, report_source_sha256=spec["report_source_sha256"],
                      intersection_status="REPORTED_NOT_REPLAYED")
        if contradictory and p > 0:
            raise ValueError("IMPOSSIBLE_JOINT_PROBABILITY")
    if not spec.get("joint_draw_artifact"):
        return result
    artifact = _object(_file(root, spec["joint_draw_artifact"]), "JOINT_DRAW_OBJECT_REQUIRED")
    if artifact.get("schema") != "sports.joint_draw_disclosure.research.v1":
        raise ValueError("JOINT_DRAW_SCHEMA_INVALID")
    expected_parents = {eid: {"model_id": rows[eid].get("model_id"),
                             "input_snapshot_hash": rows[eid].get("input_snapshot_hash")}
                        for eid in sorted({leg["event_id"] for leg in legs})}
    for parent in expected_parents.values():
        D.identity(parent["model_id"], "PARENT_MODEL_ID")
        D.source_hash(parent["input_snapshot_hash"])
    if artifact.get("parent_bindings") != expected_parents or artifact.get("cutoff") != cutoff:
        raise ValueError("JOINT_PARENT_OR_CUTOFF_MISMATCH")
    D.identity(artifact.get("joint_model_id"), "JOINT_MODEL_ID")
    D.source_hash(artifact.get("joint_model_sha256"))
    D.identity(artifact.get("dependence_assumption"), "DEPENDENCE_ASSUMPTION")
    variables = artifact.get("variables")
    _unique(variables, "variable_id")
    vectors = {}
    count = artifact.get("draw_count")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 1000000:
        raise ValueError("JOINT_DRAW_COUNT_INVALID")
    for variable in variables:
        key = D.digest(variable.get("binding"))
        if variable["variable_id"] != key or key not in bindings or key in vectors:
            raise ValueError("JOINT_VARIABLE_IDENTITY_MISMATCH")
        vector = D.vector(variable.get("values", []))
        if len(vector) != count or not np.equal(vector, np.rint(vector)).all():
            raise ValueError("JOINT_DRAW_COUNT_OR_SUPPORT_MISMATCH")
        b = bindings[key]
        if b["product"] == "total" and np.any(vector < 0):
            raise ValueError("NEGATIVE_TOTAL")
        if not D.SETTLEMENTS[b["league"]][b["settlement"]] and np.any(vector == 0):
            raise ValueError("FINAL_TIE_OR_ZERO_TOTAL_UNSUPPORTED")
        vectors[key] = vector
    if set(vectors) != set(bindings):
        raise ValueError("JOINT_VARIABLE_COVERAGE_MISMATCH")
    outcomes = {}
    for key, vector in vectors.items():
        b = bindings[key]
        scope = (b["event_id"], b["league"], b["settlement"])
        products = outcomes.setdefault(scope, {})
        if b["product"] in products and not np.array_equal(products[b["product"]], vector):
            raise ValueError("JOINT_SAME_OUTCOME_MISMATCH")
        products[b["product"]] = vector
    for products in outcomes.values():
        if set(products) == {"margin", "total"}:
            margin, total = products["margin"], products["total"]
            if np.any(np.abs(margin) > total) or np.any(np.remainder(total + margin, 2) != 0):
                raise ValueError("JOINT_SCORE_PARITY_OR_NONNEGATIVITY_VIOLATION")
    # One artifact explicitly declares joint sample rows. Never zip separate
    # marginal artifacts or infer a copula from shared seeds or equal lengths.
    masks = []
    marginals = {}
    for leg in legs:
        key, direction, threshold = constraints[leg["leg_id"]]
        mask = vectors[key] > threshold if direction == "gt" else vectors[key] < threshold
        masks.append(mask)
        marginals[leg["leg_id"]] = float(mask.mean())
    joint = float(np.logical_and.reduce(masks).mean())
    naive = math.prod(marginals.values())
    claimed = result["reported_joint_probability"]
    if claimed is not None and not math.isclose(claimed, joint, rel_tol=0, abs_tol=5e-7):
        raise ValueError("REPORTED_JOINT_DOES_NOT_MATCH_DRAWS")
    result.update(recomputed_joint_probability=joint, naive_independent_product=naive,
                  dependence_effect=joint-naive, marginal_probabilities=marginals,
                  intersection_status="RECOMPUTED_FROM_SUPPLIED_JOINT_DRAWS",
                  draw_count=count, joint_model_id=artifact["joint_model_id"],
                  joint_model_sha256=artifact["joint_model_sha256"],
                  dependence_assumption=artifact["dependence_assumption"],
                  joint_draw_artifact_sha256=spec["joint_draw_artifact"]["sha256"])
    return result


def build_report(card, packet=None, *, root=Path(".")):
    if not card.get("as_of_utc"):
        raise ValueError("DISCLOSURE_PARENT_CUTOFF_REQUIRED")
    D.stamp(card["as_of_utc"])
    rows = card["forecasts"]
    _unique(rows, "event_id")
    by_id = {row["event_id"]: row for row in rows}
    packet = copy.deepcopy(packet if packet is not None else {"schema": INPUT_SCHEMA, "action_authority": False})
    _object(packet, "DISCLOSURE_PACKET_REQUIRED")
    _keys(packet, {"schema", "action_authority", "events", "parlays"})
    if packet.get("schema") != INPUT_SCHEMA or packet.get("action_authority") is not False:
        raise ValueError("DISCLOSURE_SCHEMA_OR_AUTHORITY_INVALID")
    events = packet.get("events", [])
    _unique(events, "event_id")
    supplied = {row["event_id"]: row for row in events}
    if set(supplied) - set(by_id):
        raise ValueError("DISCLOSURE_EVENT_NOT_IN_CARD")
    result = {"schema": REPORT_SCHEMA, "parent_card_sha256": D.digest(card),
              "input_packet_sha256": D.digest(packet), "as_of_utc": card["as_of_utc"],
              "scope": "DISCLOSURE_ONLY", "action_authority": False,
              "predictive_validation": "NOT_ASSESSED", "events": [], "parlays": [], "errors": []}
    for row in rows:
        try:
            item = event_disclosure(row, card["as_of_utc"], supplied.get(row["event_id"]), root, league=card["league"])
        except (ValueError, KeyError, TypeError, OSError) as exc:
            item = event_disclosure(row, card["as_of_utc"], league=card["league"])
            item["pass_reasons"].append({"code": "DISCLOSURE_REJECTED", "detail": str(exc)})
            result["errors"].append({"event_id": row["event_id"], "reason": str(exc)})
        result["events"].append(item)
    parlays = packet.get("parlays", [])
    _unique(parlays, "parlay_id")
    for parlay in parlays:
        try:
            result["parlays"].append(parlay_disclosure(parlay, by_id, root,
                cutoff=card["as_of_utc"], league=card["league"]))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            result["errors"].append({"parlay_id": parlay["parlay_id"], "reason": str(exc)})
    result["execution_status"] = "PARTIAL" if result["errors"] else "COMPLETED"
    result["artifact_sha256"] = D.digest(result)
    return result


def _cell(value):
    return html.escape(str(value)).replace("|", "\\|").replace("\n", " ").replace("`", "\\`")


def render_md(report):
    lines = ["## Input, scenario and decision disclosures", "",
             "Research only. PASS describes wagering disposition, not a failed prediction.", ""]
    for event in report["events"]:
        lines += ["### " + _cell(event["event_id"]), "", "**PASS:** " + "; ".join(
            _cell(r["code"] + ": " + r["detail"]) for r in event["pass_reasons"]), ""]
        for group, title in (("known_inputs", "Reported known inputs"), ("unknown_inputs", "Unknown inputs"),
                             ("assumptions", "Assumptions")):
            lines.append("**" + title + ":**")
            lines.append("")
            for item in event[group]:
                if group == "known_inputs":
                    detail = f"{item['value']} (reported source time {item['observed_at_utc']}; source reference and numerical consumption not independently verified)"
                elif group == "unknown_inputs":
                    detail = item["reason"]
                else:
                    detail = f"{item['value']} — {item['rationale']}"
                lines.append("- " + _cell(item["name"] + ": " + detail))
            if not event[group]:
                lines.append("- None supplied.")
            lines.append("")
        lines.append("**Availability scenarios:** conditional; no availability weights assigned.")
        lines.append("")
        for scenario in event["availability_scenarios"]:
            conditions = ", ".join(c["entity_id"] + " " + c["availability"] for c in scenario["conditions"])
            value = (f"conditional {scenario['product']} mean {scenario['conditional_mean']:.3f}; "
                     "predictive validation not assessed" if "conditional_mean" in scenario else "forecast not run")
            lines.append("- " + _cell(scenario["scenario_id"] + ": " + conditions + "; " + value))
        if not event["availability_scenarios"]:
            lines.append("- None supplied.")
        lines.append("")
        for audit in event.get("projection_audits", []):
            lines += ["**Projection audit: " + _cell(audit["audit_id"]) + "**", "",
                      "Source bytes verified; extracted claims, roster, timing and predictive validity remain unverified. No numeric forecast was changed.", ""]
            for budget in audit["minutes_budgets"]:
                lines.append(f"- {_cell(budget['team_id'])} regulation minutes: {budget['sum_minutes']:g}/{budget['required_minutes']:g}; arithmetic {budget['arithmetic_status']}.")
                lines.extend("  - " + _cell(f) for f in budget["findings"])
            for allocation in audit["allocation_checks"]:
                lines.append(f"- {_cell(allocation['check_id'])}: sum {allocation['sum_terms']:.3f}, target {allocation['target']:.3f} {_cell(allocation['unit'])}; {allocation['arithmetic_status']}; gap {allocation['sum_minus_target']:+.3f}.")
            for sensitivity in audit["method_sensitivities"]:
                lines.append(f"- {_cell(sensitivity['sensitivity_id'])}: {sensitivity['method_count_supplied']} supplied methods, {sensitivity['minimum_probability']:.2%}–{sensitivity['maximum_probability']:.2%}, range {sensitivity['range_percentage_points']:.2f} pp. Unweighted sensitivity, not a confidence interval or failure probability.")
            lines.append("")
    for parlay in report["parlays"]:
        pct = lambda value: "unavailable" if value is None else f"{value:.3%}"
        lines += ["### Parlay " + _cell(parlay["parlay_id"]), "",
                  f"Nominal legs: {parlay['nominal_leg_count']}; effective constraints: {parlay['effective_constraint_count']} "
                  "(same-variable threshold reduction only).", "",
                  "- Redundant legs: " + _cell(json.dumps(parlay["redundant_legs"])),
                  "- Intersection evidence: " + parlay["intersection_status"],
                  "- Reported joint probability: " + pct(parlay["reported_joint_probability"]),
                  "- Recomputed all-full-win probability: " + pct(parlay["recomputed_joint_probability"]),
                  "- Independence product (diagnostic): " + pct(parlay["naive_independent_product"]),
                  "- Dependence assumption: " + _cell(parlay.get("dependence_assumption", "not supplied")),
                  "- Pushes and half wins are excluded from all-full-win probability; this is not payout pricing.",
                  "- Sampler replay: NOT_PERFORMED; predictive validation: NOT_ESTABLISHED.",
                  "- PASS: wagering OFF; actual payout, price, and sportsbook acceptance unverified.", ""]
    if report["errors"]:
        lines += ["**Rejected disclosure evidence:** " + _cell(json.dumps(report["errors"])), ""]
    return "\n".join(lines) + "\n"


def write_report(card, output, packet_path=None):
    packet_path = Path(packet_path) if packet_path else None
    packet = json.loads(packet_path.read_text()) if packet_path else None
    report = build_report(card, packet, root=packet_path.parent if packet_path else Path("."))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "disclosures.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    (output / "disclosures.md").write_text(render_md(report))
    return report
