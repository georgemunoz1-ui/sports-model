"""Fail-closed multi-sport release evaluation.

This module evaluates evidence; it does not fetch, forecast, price, or authorize a wager.
Every enabled sport is evaluated independently and the global state is the worst state.
"""

MODULE_ID = "release_gate"

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.missingness_review import release_reason, release_inventory
from pipelines.cards.missingness import content_digest, verify_audit

LEGACY_SPORTS = ("mlb", "wnba", "nfl", "cfb")
SPORTS = (*LEGACY_SPORTS, "nba", "nhl", "mls", "cbb")
REQUIRED_GATES = (
    "backfill", "event_coverage", "data_contract", "freshness", "point_in_time",
    "forecast_contract", "calibration", "market_mapping", "execution", "evaluation",
    "regression", "monitoring",
)
GATE_STATES = {"PASS", "BLOCKED", "SHADOW_ONLY", "NOT_APPLICABLE"}
EVENT_STATES = {
    "COMPLETE", "EXPLICITLY_BLOCKED", "NOT_APPLICABLE", "CANCELLED", "POSTPONED",
    "SOURCE_CONFLICT",
}


def _utc(value):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must be an ISO-8601 UTC string ending in Z")
    return dt.datetime.fromisoformat(value[:-1] + "+00:00")


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _event_rows(block):
    value = block.get("events")
    return value if isinstance(value, list) else []


def _reason_codes(value):
    return (isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)
            and len(value) == len(set(value)))


def _problems(evidence, leagues):
    problems = []
    if not isinstance(evidence, dict):
        return ["EVIDENCE_OBJECT_REQUIRED"]
    enabled = evidence.get("enabled_sports")
    if enabled != list(leagues):
        problems.append("ENABLED_SPORT_SET_MISMATCH")
    decision_time = evidence.get("decision_time_utc")
    try:
        cutoff = _utc(decision_time)
    except (TypeError, ValueError):
        cutoff = None
        problems.append("DECISION_TIME_INVALID")
    sports = _mapping(evidence.get("sports"))
    if not isinstance(evidence.get("sports"), dict):
        problems.append("SPORT_EVIDENCE_OBJECT_REQUIRED")
    for sport in leagues:
        block = sports.get(sport)
        if not isinstance(block, dict):
            problems.append(f"{sport}:SPORT_EVIDENCE_MISSING")
            continue
        gates = _mapping(block.get("gates"))
        for gate in REQUIRED_GATES:
            row = _mapping(gates.get(gate))
            state = row.get("status")
            if not isinstance(state, str) or state not in GATE_STATES:
                problems.append(f"{sport}:{gate}:GATE_UNCLASSIFIED")
            if "reason_codes" in row and not _reason_codes(row["reason_codes"]):
                problems.append(f"{sport}:{gate}:GATE_REASON_CODES_INVALID")
        events = _event_rows(block)
        if not isinstance(block.get("events"), list):
            problems.append(f"{sport}:EVENTS_LIST_REQUIRED")
        expected = block.get("expected_event_count")
        if type(expected) is not int or expected < 0 or expected != len(events):
            problems.append(f"{sport}:EVENT_COUNT_MISMATCH")
        seen = set()
        for event in events:
            if not isinstance(event, dict):
                problems.append(f"{sport}:EVENT_OBJECT_REQUIRED")
                continue
            key = event.get("event_key")
            if not isinstance(key, str) or not key.strip() or key in seen:
                problems.append(f"{sport}:EVENT_KEY_MISSING_OR_DUPLICATE")
            else:
                seen.add(key)
            disposition = event.get("disposition")
            if not isinstance(disposition, str) or disposition not in EVENT_STATES:
                problems.append(f"{sport}:{key}:EVENT_UNCLASSIFIED")
            if "reason_codes" in event and not _reason_codes(event["reason_codes"]):
                problems.append(f"{sport}:{key}:EVENT_REASON_CODES_INVALID")
            if event.get("disposition") == "EXPLICITLY_BLOCKED" and not event.get("reason_codes"):
                problems.append(f"{sport}:{key}:BLOCK_REASON_MISSING")
            for field in ("available_at_utc", "feature_cutoff_utc", "odds_snapshot_utc"):
                value = event.get(field)
                if value is None:
                    continue
                try:
                    if cutoff is None or _utc(value) > cutoff:
                        problems.append(f"{sport}:{key}:{field}:LOOKAHEAD")
                except (TypeError, ValueError):
                    problems.append(f"{sport}:{key}:{field}:TIMESTAMP_INVALID")
    return problems


def _evaluate(evidence, leagues):
    problems = _problems(evidence, leagues)
    evidence = _mapping(evidence)
    sports_out = {}
    for sport in leagues:
        block = _mapping(_mapping(evidence.get("sports")).get(sport))
        gates = _mapping(block.get("gates"))
        states = [_mapping(gates.get(g)).get("status") for g in REQUIRED_GATES]
        if any(not isinstance(s, str) or s == "BLOCKED" or s not in GATE_STATES for s in states):
            status = "BLOCKED"
        elif any(s == "SHADOW_ONLY" for s in states):
            status = "SHADOW_ONLY"
        else:
            status = "HEALTHY"
        reasons = []
        for gate in REQUIRED_GATES:
            row = _mapping(gates.get(gate))
            state = row.get("status")
            if isinstance(state, str) and state in {"BLOCKED", "SHADOW_ONLY"}:
                codes = row.get("reason_codes")
                reasons.extend(codes if _reason_codes(codes) and codes else [f"{gate.upper()}_{state}"])
        if leagues == SPORTS:
            local_problems = [p for p in problems if p.startswith(sport + ":")]
            if local_problems:
                status = "BLOCKED"
                reasons.extend(local_problems)
            inventory_problem = release_inventory(block, sport, evidence.get("decision_time_utc"))
            if inventory_problem:
                reasons.append(inventory_problem)
                status = "BLOCKED"
            checks = block.get("missingness_reviews")
            coverage = _event_rows(block)
            if not coverage and inventory_problem is None:
                checks = []
            elif not isinstance(checks, list) or not checks:
                reasons.append("MISSINGNESS_REVIEW_REQUIRED")
                status = "BLOCKED"
            else:
                scope_keys = {}
                for review in checks:
                    reason = release_reason(review, evidence.get("decision_time_utc"), league=sport)
                    if reason:
                        reasons.append(reason)
                        status = "BLOCKED"
                    elif (key := (review["model_id"], json.dumps(review["target"], sort_keys=True))) in scope_keys:
                        reasons.append("MISSINGNESS_DUPLICATE_PRODUCT_REVIEW")
                        status = "BLOCKED"
                    else:
                        scope_keys[key] = review
                for event in coverage:
                    if not isinstance(event, dict):
                        continue
                    if event.get("disposition") != "COMPLETE":
                        continue
                    outputs = event.get("model_outputs")
                    if not isinstance(outputs, list) or not outputs:
                        reasons.append("MISSINGNESS_EVENT_RECEIPT_REQUIRED")
                        status = "BLOCKED"
                        continue
                    for out in outputs:
                        if not isinstance(out, dict):
                            reasons.append("MISSINGNESS_EVENT_RECEIPT_INVALID")
                            status = "BLOCKED"
                            continue
                        model = out.get("model_id")
                        products = out.get("products")
                        target = out.get("target")
                        review = scope_keys.get((model, json.dumps(target, sort_keys=True))) if isinstance(model, str) else None
                        if (review is None or out.get("procedure_id") != review.get("procedure_id")
                                or not verify_audit(out.get("missingness_audit"), league=sport, event_id=event.get("event_key"),
                                model_id=model, products=products, forecast=out.get("forecast"))
                                or target["product"] not in products
                                or release_reason(review, evidence.get("decision_time_utc"), league=sport,
                                                  receipt=out["missingness_audit"], forecast=out["forecast"])):
                            reasons.append("MISSINGNESS_EVENT_RECEIPT_OR_SCOPE_INVALID")
                            status = "BLOCKED"
        sports_out[sport] = {
            "status": status,
            "expected_event_count": block.get("expected_event_count"),
            "classified_event_count": len(_event_rows(block)),
            "reason_codes": sorted(set(reasons)),
        }
    if problems:
        global_status = "BLOCKED"
    elif any(v["status"] == "BLOCKED" for v in sports_out.values()):
        global_status = "BLOCKED"
    elif any(v["status"] == "SHADOW_ONLY" for v in sports_out.values()):
        global_status = "SHADOW_ONLY"
    else:
        global_status = "HEALTHY"
    return {
        "schema": "ops.release_manifest.v2" if leagues == SPORTS else "ops.release_manifest.v1",
        "release_id": evidence.get("release_id"),
        "as_of_date": evidence.get("as_of_date"),
        "decision_time_utc": evidence.get("decision_time_utc"),
        "coverage_start": evidence.get("coverage_start"),
        "enabled_sports": list(leagues),
        "enabled_markets": evidence.get("enabled_markets"),
        "global_status": global_status,
        "action_authority": "NO",
        "sports": sports_out,
        "contract_problems": problems,
        "source_evidence": evidence.get("source_evidence"),
    }


def evaluate(evidence):
    return _evaluate(evidence, SPORTS)


def verify_artifact(evidence_path, artifact_path):
    with open(evidence_path, "rb") as handle:
        raw = handle.read()
    evidence = json.loads(raw)
    with open(artifact_path, encoding="utf-8") as handle:
        artifact = json.load(handle)
    if not isinstance(artifact, dict):
        return evaluate(evidence), ["ARTIFACT_OBJECT_REQUIRED"]
    schema = artifact.get("schema")
    leagues = LEGACY_SPORTS if isinstance(schema, str) and schema in {"ops.release_manifest.v1","ops.release_artifact.v1"} else SPORTS
    expected = _evaluate(evidence, leagues)
    problems = []
    if artifact.get("evidence_sha256") != hashlib.sha256(raw).hexdigest():
        problems.append("EVIDENCE_HASH_MISMATCH")
    # Legacy artifacts omitted some descriptive fields. They remain readable,
    # but cannot pass the current --gate. Every current decision field is bound.
    fields = expected.keys() if leagues == SPORTS else (
        "release_id", "global_status", "contract_problems", "action_authority", "sports")
    for field in fields:
        try:
            matches = field in artifact and content_digest(artifact[field]) == content_digest(expected[field])
        except (TypeError, ValueError, OverflowError):
            matches = False
        if not matches:
            problems.append(field.upper() + "_MISMATCH")
    if leagues == SPORTS:
        envelope = {"evidence_sha256", "evidence_path", "generated_utc", "generated_at_utc", "release_note"}
        if set(artifact) - set(expected) - envelope:
            problems.append("UNRECOGNIZED_ARTIFACT_FIELDS")
    return expected, problems


def selftest():
    gate = lambda state: {"status": state, "reason_codes": []}
    base = {
        "release_id": "test", "as_of_date": "2026-09-03",
        "decision_time_utc": "2026-09-03T18:40:16Z", "coverage_start": "2026-08-24",
        "enabled_sports": list(SPORTS), "enabled_markets": ["ML", "SPREAD", "TOTAL"],
        "sports": {s: {"expected_event_count": 0, "events": [],
                        "gates": {g: gate("PASS") for g in REQUIRED_GATES}} for s in SPORTS},
    }
    assert evaluate(base)["global_status"] == "BLOCKED"
    assert "MISSINGNESS_REVIEW_REQUIRED" in evaluate(base)["sports"]["nfl"]["reason_codes"]
    shadow = json.loads(json.dumps(base))
    shadow["sports"]["mlb"]["gates"]["calibration"] = gate("SHADOW_ONLY")
    assert evaluate(shadow)["global_status"] == "BLOCKED"
    blocked = json.loads(json.dumps(base))
    blocked["sports"]["cfb"]["gates"]["event_coverage"] = {
        "status": "BLOCKED", "reason_codes": ["EVENT_ID_UNRESOLVED"]}
    assert evaluate(blocked)["global_status"] == "BLOCKED"
    missing = json.loads(json.dumps(base))
    del missing["sports"]["nfl"]["gates"]["freshness"]
    assert "nfl:freshness:GATE_UNCLASSIFIED" in evaluate(missing)["contract_problems"]
    future = json.loads(json.dumps(base))
    future["sports"]["mlb"]["expected_event_count"] = 1
    future["sports"]["mlb"]["events"] = [{
        "event_key": "MLB_GAMEPK:1", "disposition": "COMPLETE",
        "available_at_utc": "2026-09-03T18:40:17Z"}]
    assert any("LOOKAHEAD" in p for p in evaluate(future)["contract_problems"])
    print("release_gate selftest: OK")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--evidence")
    parser.add_argument("--manifest")
    parser.add_argument("--gate", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    if not args.evidence:
        parser.error("--evidence is required")
    if args.manifest:
        report, artifact_problems = verify_artifact(args.evidence, args.manifest)
        report["artifact_problems"] = artifact_problems
    else:
        with open(args.evidence, encoding="utf-8") as handle:
            report = evaluate(json.load(handle))
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.gate:
        return 0 if (report["schema"] == "ops.release_manifest.v2" and report["global_status"] == "HEALTHY"
                     and not report["contract_problems"]
                     and not report.get("artifact_problems")) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
