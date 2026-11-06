"""Reprice retained PMFs and rank supplied research contracts, never forecasts.

This is an opt-in downstream report. It cannot fit a model, acquire prices,
authenticate providers, create prospective registration, or authorize a wager.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from models.common import discrete_research as D
from models.common.settlement_risk import finite_real, payoff_moments

INPUT_SCHEMA = "sports.research_candidate_board_input.v1"
SCHEMA = "sports.research_candidate_board.v1"
OBJECTIVE = "UNCONDITIONAL_FULL_WIN_PROBABILITY"
_BINDINGS = {"event_id", "league", "product", "settlement", "cutoff",
             "parent_forecast_sha256", "orientation", "orientation_evidence_sha256"}
_QUOTE_FIELDS = {"source_class", "source_sha256", "book", "retrieved_at_utc",
                 "provider_updated_at_utc"}
_CONTRACT_FIELDS = {"event_id", "league", "product", "period", "settlement", "side",
                    "line", "distribution_sha256", "odds", "odds_format", "quote"}


def _exact_fields(value, fields, label):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("INVALID_" + label + "_FIELDS")


def _bound_distribution(entry):
    _exact_fields(entry, {"distribution", "binding"}, "DISTRIBUTION_ENTRY")
    distribution, binding = entry["distribution"], entry["binding"]
    _exact_fields(binding, _BINDINGS, "DISTRIBUTION_BINDING")
    if not isinstance(distribution, dict) or not isinstance(distribution.get("provenance"), dict):
        raise ValueError("DISTRIBUTION_AND_PROVENANCE_REQUIRED")
    D.validate(distribution)
    for name in ("league", "product", "settlement"):
        if distribution.get(name) != binding[name]:
            raise ValueError("DISTRIBUTION_HEAD_BINDING_MISMATCH")
    prov = distribution["provenance"]
    for name in ("event_id", "cutoff", "parent_forecast_sha256"):
        if prov.get(name) != binding[name]:
            raise ValueError("DISTRIBUTION_SOURCE_BINDING_MISMATCH")
    D.identity(binding["event_id"], "EVENT_ID")
    D.stamp(binding["cutoff"])
    D.source_hash(binding["parent_forecast_sha256"])
    D.source_hash(binding["orientation_evidence_sha256"])
    orientation = "HOME_MINUS_AWAY" if binding["product"] == "margin" else "HOME_PLUS_AWAY"
    if binding["orientation"] != orientation or prov.get("orientation", orientation) != orientation:
        raise ValueError("DISTRIBUTION_ORIENTATION_MISMATCH")
    # Orientation is explicit in the external binding. Legacy distributions are
    # never edited or resealed to insert a missing provenance field.
    return copy.deepcopy(distribution), copy.deepcopy(binding)


def _quote(value):
    _exact_fields(value, _QUOTE_FIELDS, "QUOTE")
    D.identity(value["source_class"], "SOURCE_CLASS")
    D.source_hash(value["source_sha256"])
    # Metadata alone cannot bind parsed terms or house rules to raw bytes. This
    # diagnostic reader never upgrades them merely because the fields are full.
    missing = ["QUOTE_TERMS_RAW_BINDING_UNVERIFIED", "SETTLEMENT_RULES_UNVERIFIED"]
    if value["book"] is None:
        missing.append("QUOTE_BOOK_UNKNOWN")
    else:
        D.identity(value["book"], "BOOK")
    for field in ("retrieved_at_utc", "provider_updated_at_utc"):
        if value[field] is None:
            missing.append("QUOTE_" + field.upper() + "_UNKNOWN")
        else:
            D.stamp(value[field])
    if value["retrieved_at_utc"] is not None and value["provider_updated_at_utc"] is not None:
        if D.stamp(value["provider_updated_at_utc"]) > D.stamp(value["retrieved_at_utc"]):
            raise ValueError("QUOTE_PROVIDER_TIME_AFTER_RETRIEVAL")
    return copy.deepcopy(value), missing


def build_board(payload):
    """Select one full-win probability maximum per supplied event, then rank.

    All exact contract sides and alternative quotes must be supplied explicitly.
    No opposite-side price is invented. Ties use canonical contract ID, with no
    EV tie-break. The input inventory makes unsupported/missing events visible.
    """
    _exact_fields(payload, {"schema", "events", "distributions", "contracts"}, "BOARD_INPUT")
    if payload["schema"] != INPUT_SCHEMA:
        raise ValueError("UNSUPPORTED_BOARD_INPUT_SCHEMA")
    if not all(isinstance(payload[k], list) for k in ("events", "distributions", "contracts")):
        raise ValueError("BOARD_LISTS_REQUIRED")
    events, distributions, heads = {}, {}, set()
    for event in payload["events"]:
        _exact_fields(event, {"event_id", "league", "matchup"}, "EVENT")
        for key in event:
            D.identity(event[key], key.upper())
        eid = event["event_id"]
        if eid in events:
            raise ValueError("DUPLICATE_EVENT")
        if event["league"] not in D.SETTLEMENTS:
            raise ValueError("UNSUPPORTED_LEAGUE")
        events[eid] = copy.deepcopy(event)
    for entry in payload["distributions"]:
        distribution, binding = _bound_distribution(entry)
        eid = binding["event_id"]
        if eid not in events or events[eid]["league"] != binding["league"]:
            raise ValueError("DISTRIBUTION_EVENT_NOT_IN_INVENTORY")
        did = distribution["distribution_sha256"]
        if did in distributions:
            raise ValueError("DUPLICATE_DISTRIBUTION")
        head = (eid, binding["product"], binding["settlement"])
        if head in heads:
            raise ValueError("MULTIPLE_DISTRIBUTIONS_REQUIRE_EXPLICIT_UPSTREAM_MODEL_SELECTION")
        heads.add(head)
        distributions[did] = (distribution, binding)
    rows, seen = [], set()
    for contract in payload["contracts"]:
        _exact_fields(contract, _CONTRACT_FIELDS, "CONTRACT")
        eid, did = contract["event_id"], contract["distribution_sha256"]
        if eid not in events or did not in distributions:
            raise ValueError("CONTRACT_EVENT_OR_DISTRIBUTION_UNKNOWN")
        distribution, binding = distributions[did]
        for key in ("event_id", "league", "product", "settlement"):
            if contract[key] != binding[key]:
                raise ValueError("CONTRACT_HEAD_BINDING_MISMATCH")
        expected_period = "regulation" if contract["settlement"] in {"REGULATION", "REGULATION_90_STOPPAGE"} else "full_game"
        if contract["period"] != expected_period:
            raise ValueError("CONTRACT_PERIOD_SETTLEMENT_MISMATCH")
        line = finite_real(contract["line"], "CONTRACT_LINE")
        quote, missing = _quote(contract["quote"])
        probabilities = D.price(distribution, line, contract["side"])
        risk = payoff_moments(probabilities, odds=contract["odds"], odds_format=contract["odds_format"])
        # Contract identity deliberately excludes price; a price refresh cannot
        # change selection or turn a single contract into multiple alternatives.
        identity = {k: contract[k] for k in _CONTRACT_FIELDS - {"odds", "odds_format", "quote"}}
        cid = D.digest(identity)
        if cid in seen:
            raise ValueError("DUPLICATE_CONTRACT_CHOOSE_EXPLICIT_QUOTE_VINTAGE")
        seen.add(cid)
        row = {**events[eid], "contract_id": cid, "contract": copy.deepcopy(contract),
               "model_id": distribution["model_id"], "distribution_binding": binding,
               "probabilities": risk["probabilities"],
               "winning_settlement_probability": probabilities["win"],
               "positive_return_probability": probabilities["win"] + probabilities["half_win"],
               "objective": OBJECTIVE, "risk": risk, "quote": quote,
               "line_basis": "HOME_HANDICAP" if contract["product"] == "margin" else "TOTAL_THRESHOLD",
               "side_line": -line if contract["side"] == "AWAY" else line,
               "missing_inputs": missing,
               "research_only": True, "selection_eligibility": "RESEARCH_ONLY",
               "predictive_validation": "NOT_ASSESSED", "pit_eligibility": "NOT_ASSESSED",
               "provider_authenticity": "NOT_ASSESSED", "runner_replay": "NOT_RUN",
               "binding_verification": "CONSISTENCY_ONLY_NOT_INDEPENDENT_AUTHENTICATION",
               "action_authority": False, "allocation": 0.}
        rows.append(row)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["event_id"]].append(row)
    chosen, coverage = [], []
    for eid, event in events.items():
        alternatives = grouped.get(eid, [])
        if not alternatives:
            coverage.append({**event, "status": "NO_SUPPORTED_CANDIDATE", "candidate": None,
                             "reason": "NO_EXPLICIT_DISTRIBUTION_BOUND_CONTRACT"})
            continue
        winner = min(alternatives, key=lambda r: (-r["winning_settlement_probability"], r["contract_id"]))
        chosen.append(copy.deepcopy(winner))
        coverage.append({**event, "status": "RESEARCH_CANDIDATE", "contract_id": winner["contract_id"],
                         "supplied_contract_count": len(alternatives)})
    chosen.sort(key=lambda r: (r["league"], -r["winning_settlement_probability"], r["contract_id"]))
    ranks = defaultdict(int)
    for row in chosen:
        ranks[row["league"]] += 1
        row["league_rank"] = ranks[row["league"]]
    report = {"schema": SCHEMA, "input_sha256": D.digest(payload),
              "objective": OBJECTIVE, "ranking_tie_break": "CANONICAL_CONTRACT_ID_NOT_PRICE",
              "candidate_scope": "SUPPLIED_CONTRACTS_ONLY_NOT_ALL_MARKET_OPTIMIZATION",
              "rows": chosen, "all_contracts": rows, "coverage": coverage,
              "event_count": len(events), "candidate_count": len(chosen),
              "contract_count": len(rows), "execution_status": "COMPLETED",
              "predictive_validation": "NOT_ASSESSED", "publication_eligibility": "INELIGIBLE",
              "wagering_authority": "OFF", "allocation": 0., "action_authority": False}
    report["artifact_sha256"] = D.digest(report)
    return report


def run_file(input_path, output_dir):
    """Validate before writing; refuse an existing output directory."""
    path, output = Path(input_path).resolve(), Path(output_dir).resolve()
    raw = path.read_bytes()
    report = build_board(json.loads(raw))
    report["input_file_sha256"] = hashlib.sha256(raw).hexdigest()
    report.pop("artifact_sha256")
    report["artifact_sha256"] = D.digest(report)
    output.mkdir(parents=True, exist_ok=False)
    (output / "candidate_board.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return report
