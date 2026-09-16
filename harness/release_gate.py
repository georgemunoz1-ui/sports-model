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

SPORTS = ("mlb", "wnba", "nfl", "cfb")
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


def _problems(evidence):
    problems = []
    enabled = evidence.get("enabled_sports")
    if enabled != list(SPORTS):
        problems.append("ENABLED_SPORT_SET_MISMATCH")
    decision_time = evidence.get("decision_time_utc")
    try:
        cutoff = _utc(decision_time)
    except (TypeError, ValueError):
        cutoff = None
        problems.append("DECISION_TIME_INVALID")
    sports = evidence.get("sports") or {}
    for sport in SPORTS:
        block = sports.get(sport)
        if not isinstance(block, dict):
            problems.append(f"{sport}:SPORT_EVIDENCE_MISSING")
            continue
        gates = block.get("gates") or {}
        for gate in REQUIRED_GATES:
            state = (gates.get(gate) or {}).get("status")
            if state not in GATE_STATES:
                problems.append(f"{sport}:{gate}:GATE_UNCLASSIFIED")
        events = block.get("events") or []
        expected = block.get("expected_event_count")
        if not isinstance(expected, int) or expected != len(events):
            problems.append(f"{sport}:EVENT_COUNT_MISMATCH")
        seen = set()
        for event in events:
            key = event.get("event_key")
            if not key or key in seen:
                problems.append(f"{sport}:EVENT_KEY_MISSING_OR_DUPLICATE")
            seen.add(key)
            if event.get("disposition") not in EVENT_STATES:
                problems.append(f"{sport}:{key}:EVENT_UNCLASSIFIED")
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


def evaluate(evidence):
    problems = _problems(evidence)
    sports_out = {}
    for sport in SPORTS:
        block = (evidence.get("sports") or {}).get(sport) or {}
        gates = block.get("gates") or {}
        states = [(gates.get(g) or {}).get("status") for g in REQUIRED_GATES]
        if any(s == "BLOCKED" or s not in GATE_STATES for s in states):
            status = "BLOCKED"
        elif any(s == "SHADOW_ONLY" for s in states):
            status = "SHADOW_ONLY"
        else:
            status = "HEALTHY"
        reasons = []
        for gate in REQUIRED_GATES:
            row = gates.get(gate) or {}
            if row.get("status") in {"BLOCKED", "SHADOW_ONLY"}:
                reasons.extend(row.get("reason_codes") or [f"{gate.upper()}_{row.get('status')}"])
        sports_out[sport] = {
            "status": status,
            "expected_event_count": block.get("expected_event_count"),
            "classified_event_count": len(block.get("events") or []),
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
        "schema": "ops.release_manifest.v1",
        "release_id": evidence.get("release_id"),
        "as_of_date": evidence.get("as_of_date"),
        "decision_time_utc": evidence.get("decision_time_utc"),
        "coverage_start": evidence.get("coverage_start"),
        "enabled_sports": list(SPORTS),
        "enabled_markets": evidence.get("enabled_markets"),
        "global_status": global_status,
        "action_authority": "NO",
        "sports": sports_out,
        "contract_problems": problems,
        "source_evidence": evidence.get("source_evidence"),
    }


def verify_artifact(evidence_path, artifact_path):
    with open(evidence_path, "rb") as handle:
        raw = handle.read()
    evidence = json.loads(raw)
    with open(artifact_path, encoding="utf-8") as handle:
        artifact = json.load(handle)
    expected = evaluate(evidence)
    problems = []
    if artifact.get("evidence_sha256") != hashlib.sha256(raw).hexdigest():
        problems.append("EVIDENCE_HASH_MISMATCH")
    if artifact.get("release_id") != expected["release_id"]:
        problems.append("RELEASE_ID_MISMATCH")
    if artifact.get("global_status") != expected["global_status"]:
        problems.append("GLOBAL_STATUS_MISMATCH")
    if artifact.get("contract_problems") != expected["contract_problems"]:
        problems.append("CONTRACT_PROBLEMS_MISMATCH")
    for sport in SPORTS:
        if (artifact.get("sports") or {}).get(sport) != expected["sports"][sport]:
            problems.append(f"{sport}:SPORT_RESULT_MISMATCH")
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
    assert evaluate(base)["global_status"] == "HEALTHY"
    shadow = json.loads(json.dumps(base))
    shadow["sports"]["mlb"]["gates"]["calibration"] = gate("SHADOW_ONLY")
    assert evaluate(shadow)["global_status"] == "SHADOW_ONLY"
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
        return 0 if (report["global_status"] == "HEALTHY"
                     and not report["contract_problems"]
                     and not report.get("artifact_problems")) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
