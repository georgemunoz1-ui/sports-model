"""Validate issue cards and append-only triage sessions; never grants release clearance."""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = "docs/releases/official_release_blocker_register.json"
LEDGER = "data/governance/health_triage_sessions.jsonl"
STATES = {"RESOLVED", "FIX-IN-PROGRESS", "ACCEPTED-RISK", "DESCOPED", "BLOCKED", "OVERDUE-ESCALATED"}

def stamp(value):
    t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return t.astimezone(dt.timezone.utc)

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def seal(value):
    value = dict(value)
    value.pop("record_sha256", None)
    return dict(value, record_sha256=digest(value))

def validate_card(card, root):
    errors = []
    for field in ("issue_id", "specific", "owner", "why_unresolved", "next_action", "due_at_utc",
                  "closure_criteria", "dependency_assessment", "evidence", "residual_claim"):
        if not card.get(field):
            errors.append("MISSING:" + field)
    status = card.get("status")
    if status not in STATES:
        errors.append("INVALID_DECISION")
    if seal(card)["record_sha256"] != card.get("record_sha256"):
        errors.append("CARD_HASH_MISMATCH")
    for ev in card.get("evidence", []):
        path = (root / ev["path"]).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            errors.append("EVIDENCE_UNAVAILABLE:" + ev["path"])
        elif hashlib.sha256(path.read_bytes()).hexdigest() != ev["sha256"]:
            errors.append("EVIDENCE_HASH_MISMATCH:" + ev["path"])
    if status == "ACCEPTED-RISK" and not all(card.get(k) for k in ("review_at_utc", "rationale", "decision_authority")):
        errors.append("RISK_DECISION_INCOMPLETE")
    if status == "BLOCKED" and not card.get("external_dependency"):
        errors.append("EXTERNAL_DEPENDENCY_UNNAMED")
    if status == "FIX-IN-PROGRESS" and not card.get("physical_action_evidence"):
        errors.append("NO_EXECUTED_STEP")
    if status == "RESOLVED" and not card.get("closure_evidence"):
        errors.append("NO_CLOSURE_EVIDENCE")
    if status == "DESCOPED" and not all(card.get(k) for k in ("rationale", "scope_proof")):
        errors.append("NO_DESCOPE_PROOF")
    if card.get("obligation_kind") == "WNBA_OFFICIAL_AVAILABILITY":
        if status == "RESOLVED" and not all(card.get("unit_binding", {}).get(k) for k in
                                           ("canonical_team_id", "event_date", "canonical_event_id", "official_artifact_path")):
            errors.append("AVAILABILITY_UNIT_BINDING_INCOMPLETE")
        if status == "RESOLVED" and card.get("unit_binding", {}).get("official_artifact_path") not in {e["path"] for e in card.get("evidence", [])}:
            errors.append("AVAILABILITY_ARTIFACT_NOT_VERIFIED")
    for field in ("due_at_utc", "review_at_utc", "opened_at_utc", "last_material_change_at_utc"):
        if card.get(field):
            try:
                stamp(card[field])
            except (ValueError, TypeError):
                errors.append("INVALID_TIMESTAMP:" + field)
    return errors

def effective_status(card, now, blocked_sessions):
    if card["status"] not in ("RESOLVED", "DESCOPED") and card.get("last_material_change_at_utc"):
        if (now - stamp(card["last_material_change_at_utc"])).total_seconds() > 14 * 86400:
            return "OVERDUE-ESCALATED"
    if card["status"] == "BLOCKED" and blocked_sessions > 2:
        return "OVERDUE-ESCALATED"
    if card["status"] == "ACCEPTED-RISK" and stamp(card["review_at_utc"]) <= now:
        return "OVERDUE-ESCALATED"
    if card["status"] == "FIX-IN-PROGRESS" and stamp(card["due_at_utc"]) < now:
        return "OVERDUE-ESCALATED"
    return card["status"]

def read_sessions(path):
    rows = [json.loads(s) for s in path.read_text().splitlines() if s.strip()] if path.exists() else []
    previous = None
    ids = set()
    for row in rows:
        if row.get("previous_record_sha256") != previous or seal(row)["record_sha256"] != row.get("record_sha256"):
            raise ValueError("TRIAGE_CHAIN_INVALID")
        if row["session_id"] in ids:
            raise ValueError("DUPLICATE_SESSION")
        ids.add(row["session_id"])
        previous = row["record_sha256"]
    return rows

def report(register, sessions, now, root=ROOT, for_new_session=False):
    errors, rows = [], []
    seen = set()
    for card in register["issues"]:
        key = card["issue_id"]
        if key in seen:
            errors.append(key + ":DUPLICATE_ISSUE")
        seen.add(key)
        errors.extend(key + ":" + e for e in validate_card(card, root))
        streak = int(for_new_session) if card["status"] == "BLOCKED" else 0
        if card["status"] == "BLOCKED":
            for previous in reversed(sessions):
                old = next((r for r in previous["issues"] if r["issue_id"] == key), None)
                if not old or old["decision"] != "BLOCKED":
                    break
                streak += 1
        age = None
        if card.get("last_material_change_at_utc"):
            age = (now - stamp(card["last_material_change_at_utc"])).total_seconds() / 86400
            if age < 0:
                errors.append(key + ":FUTURE_MATERIAL_CHANGE")
        escalation = card.get("escalation", {})
        if age is not None and age > 14 and card["status"] not in ("RESOLVED", "DESCOPED"):
            required = ("owner_confirmed", "escalation_owner", "blocker", "last_completed_action",
                        "next_action", "next_action_at_utc", "recorded_at_utc", "decision", "rationale")
            if not all(escalation.get(k) for k in required):
                errors.append(key + ":AGED_ESCALATION_INCOMPLETE")
            else:
                if escalation["decision"] not in ("CONTINUE_REMEDIATION", "ACCEPTED-RISK", "BLOCKED_EXTERNALLY", "RECLASSIFY", "RETIRE_OR_SUPERSEDE"):
                    errors.append(key + ":INVALID_ESCALATION_DECISION")
                for field in ("recorded_at_utc", "next_action_at_utc"):
                    try:
                        value = stamp(escalation[field])
                        if field == "recorded_at_utc" and value > now:
                            errors.append(key + ":FUTURE_ESCALATION_RECORD")
                        if field == "next_action_at_utc" and value <= now:
                            errors.append(key + ":ESCALATION_REVIEW_OVERDUE")
                    except (ValueError, TypeError):
                        errors.append(key + ":INVALID_ESCALATION_TIMESTAMP:" + field)
        status = effective_status(card, now, streak) if not validate_card(card, root) else "OVERDUE-ESCALATED"
        rows.append({"issue_id": key, "decision": card["status"], "status": status,
                     "consecutive_blocked_sessions": streak,
                     "days_without_material_change": round(age, 2) if age is not None else None,
                     "trend_included": card.get("trend_included", True),
                     "release_blocking": card.get("release_blocking", True),
                     "owner": card["owner"], "next_action": card["next_action"],
                     "due_at_utc": card["due_at_utc"], "card_sha256": card["record_sha256"]})
        if escalation:
            rows[-1]["escalation"] = escalation
    active = [r for r in rows if r["trend_included"] and r["status"] not in ("RESOLVED", "DESCOPED")]
    aged = sum(r["days_without_material_change"] is not None and r["days_without_material_change"] > 14 for r in active)
    unknown = sum(r["days_without_material_change"] is None for r in active)
    previous = sessions[-1]["trend"]["aged_over_14_days"] if sessions else None
    for group in register.get("obligation_groups", []):
        children = [c for c in register["issues"] if c.get("parent_issue_id") == group["parent_issue_id"]]
        if len(children) != group["expected_units"] or {c.get("unit_ordinal") for c in children} != set(range(1, group["expected_units"] + 1)):
            errors.append(group["parent_issue_id"] + ":OBLIGATION_INVENTORY_INCOMPLETE")
        parent = next((c for c in register["issues"] if c["issue_id"] == group["parent_issue_id"]), None)
        if parent is None or (parent["status"] in ("RESOLVED", "DESCOPED") and any(c["status"] not in ("RESOLVED", "DESCOPED") for c in children)):
            errors.append(group["parent_issue_id"] + ":PARENT_CLOSURE_WITH_UNRESOLVED_UNITS")
    return {"schema": "health.triage.report.v1", "checked_at_utc": now.isoformat(),
            "issues": rows, "validation_errors": errors,
            "trend": {"aged_over_14_days": aged, "unknown_age": unknown,
                      "previous_session_count": previous,
                      "direction": "BASELINE_NOT_AVAILABLE" if previous is None else
                      ("INCREASED_REQUIRES_EXPLANATION" if aged > previous else "NON_INCREASING"),
                      "clock_policy": "material evidence change; a review or status rename does not reset age"},
            "accepted_risks_present": any(c["status"] == "ACCEPTED-RISK" for c in register["issues"]),
            "accepted_risk_release_override": False,
            "official_release_eligible": False, "action_authority": "OFF", "dose": 0.0,
            "note": "Triage status cannot waive mandatory gates; profile-specific clearance is separate."}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--register", default=REGISTER)
    p.add_argument("--ledger", default=LEDGER)
    p.add_argument("--as-of")
    p.add_argument("--append-session")
    args = p.parse_args()
    now = stamp(args.as_of) if args.as_of else dt.datetime.now(dt.timezone.utc)
    sessions = read_sessions(ROOT / args.ledger)
    result = report(json.loads((ROOT / args.register).read_text()), sessions, now,
                    for_new_session=bool(args.append_session))
    if args.append_session:
        if result["validation_errors"]:
            raise ValueError("CANNOT_APPEND_INVALID_CARDS")
        if args.as_of:
            raise ValueError("WRITER_CLOCK_REQUIRED_FOR_APPEND")
        if any(s["session_id"] == args.append_session for s in sessions):
            raise ValueError("DUPLICATE_SESSION")
        result = seal(dict(result, session_id=args.append_session,
                           previous_record_sha256=sessions[-1]["record_sha256"] if sessions else None))
        target = ROOT / args.ledger
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a") as handle:
            handle.write(json.dumps(result, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2))
    return 1 if result["validation_errors"] else 0

if __name__ == "__main__":
    raise SystemExit(main())
