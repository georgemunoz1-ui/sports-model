"""Hash-bound, pregame binary-contract compatibility diagnostics.

This checks supplied bytes and semantics; it is not a venue authenticator or a
qualification authority. No caller-provided verification flag is promoted.
"""
from datetime import datetime, timezone
from decimal import localcontext
from hashlib import sha256
import json
from pathlib import Path

from .engine import decide_payload
from .fees import FeeSchedule
from .numeric import decimal_value, whole_quantity

KINDS = ("contract", "quote", "state", "model", "rules", "fee_schedule", "configuration")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def decode(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate JSON key: " + key)
            out[key] = value
        return out
    def reject(value):
        raise ValueError("use decimal strings, not floating/nonfinite JSON numbers")
    return json.loads(raw, object_pairs_hook=pairs, parse_float=reject, parse_constant=reject)


def utc(value):
    if not isinstance(value, str):
        raise ValueError("timestamp string required")
    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone required")
    return value.astimezone(timezone.utc)


def _nonempty(obj, key):
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(key + ": nonempty string required")
    return value


def load_evidence(request, evidence_root):
    root = Path(evidence_root).resolve(strict=True)
    refs = request.get("evidence")
    if not isinstance(refs, dict) or set(refs) != set(KINDS):
        raise ValueError("exact contract/quote/state/model/rules/fee_schedule/configuration references required")
    values, bindings = {}, {}
    for kind in KINDS:
        ref = refs[kind]
        if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
            raise ValueError("invalid evidence reference: " + kind)
        path = (root / ref["path"]).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("evidence path outside root or not a file")
        raw = path.read_bytes()
        actual = sha256(raw).hexdigest()
        if actual != ref["sha256"]:
            raise ValueError("evidence hash mismatch: " + kind)
        value = decode(raw)
        if not isinstance(value, dict):
            raise ValueError("evidence object required: " + kind)
        values[kind] = value
        bindings[kind] = {"path": str(path.relative_to(root)), "sha256": actual}
    return values, bindings


def assess(request, evidence_root, *, now=None):
    """Return a non-actionable receipt; actual CLI owns the evaluation clock."""
    now = datetime.now(timezone.utc) if now is None else now
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("aware evaluation time required")
    result = {"schema": "research.contract_compatibility.v1", "disposition": "BLOCKED",
              "order_authorized": False, "action": "OFF", "dose": 0,
              "production_eligible": False, "evaluated_at_utc": now.isoformat(),
              "findings": [], "bindings": {}, "source_authenticity": "NOT_VERIFIED",
              "qualification": "NOT_ESTABLISHED", "candidate": None}
    try:
        if not isinstance(request, dict) or set(request) != {"comparison_id", "quantity", "evidence"}:
            raise ValueError("request permits only comparison_id, quantity and evidence; no caller gates")
        result["comparison_id"] = _nonempty(request, "comparison_id")
        n = whole_quantity(request["quantity"], "quantity")
        values, result["bindings"] = load_evidence(request, evidence_root)
        c, q, s, m, rules, fees, config = (values[k] for k in KINDS)
        for obj, keys in ((c, ("contract_id", "event_id", "league", "selection_team_id", "period", "rules_id", "currency")),
                          (q, ("quote_id", "contract_id", "state_id", "venue", "fee_schedule_id")),
                          (s, ("state_id", "event_id", "phase", "home_team_id", "away_team_id", "league")),
                          (m, ("model_id", "forecast_id", "contract_id", "event_id", "state_id")),
                          (rules, ("rules_id", "period", "currency", "venue", "payoff_function_id")),
                          (fees, ("schedule_id", "venue", "currency")),
                          (config, ("configuration_id",))):
            for key in keys:
                _nonempty(obj, key)
        line = decimal_value(c.get("line"), "line")
        with localcontext() as ctx:
            ctx.prec = 256
            doubled = line * 2
        binary = (c.get("market_type") == "SPREAD" and doubled == doubled.to_integral_value()
                  and int(doubled) % 2 != 0 and c.get("payout_unit") == "1"
                  and rules.get("payout_unit") == "1"
                  and rules["payoff_function_id"] == "binary_half_spread.v1")
        identities = (c["league"] in ("NFL", "CFB", "NBA", "WNBA", "MLB", "NHL", "MLS")
                      and c["league"] == s["league"] and s["home_team_id"] != s["away_team_id"]
                      and c["selection_team_id"] in (s["home_team_id"], s["away_team_id"])
                      and q["contract_id"] == c["contract_id"] == m["contract_id"]
                      and c["event_id"] == s["event_id"] == m["event_id"]
                      and c["rules_id"] == rules["rules_id"] and c["period"] == rules["period"]
                      and c["currency"] == rules["currency"] == fees["currency"]
                      and q["venue"] == rules["venue"] == fees["venue"]
                      and q["fee_schedule_id"] == fees["schedule_id"])
        state_aligned = q["state_id"] == s["state_id"] == m["state_id"] and s["phase"] == "PRE_GAME"
        observed, retrieved, state_time = (utc(q["observed_at_utc"]), utc(q["retrieved_at_utc"]), utc(s["observed_at_utc"]))
        created, cutoff, start = utc(m["created_at_utc"]), utc(m["cutoff_utc"]), utc(s["scheduled_start_utc"])
        age = whole_quantity(config["max_quote_age_seconds"], "max_quote_age_seconds")
        state_age = whole_quantity(config["max_state_age_seconds"], "max_state_age_seconds")
        fresh = (state_time <= cutoff <= created <= observed <= retrieved <= now < start
                 and (now - observed).total_seconds() <= age
                 and (now - state_time).total_seconds() <= state_age)
        if type(q.get("market_open")) is not bool:
            raise ValueError("market_open must be boolean")
        effective, expires = utc(fees["effective_at_utc"]), utc(fees["expires_at_utc"])
        fees_current = effective <= observed <= now < expires
        schedule = FeeSchedule(rate=fees["rate"], minimum=fees["minimum"],
                               rounding_increment=fees["rounding_increment"], schedule_id=fees["schedule_id"])
        fee = schedule.calculate(q["buy_price"], n)
        payload = {"price": q["buy_price"], "quantity": n, "total_entry_fee": fee["total_fee"],
                   "expected_payout": m.get("expected_payout"), "required_ev_buffer": config["required_ev_buffer"],
                   "available_quantity": q.get("available_quantity"), "identity_valid": identities and binary,
                   "settlement_verified": False, "state_aligned": state_aligned, "quote_fresh": fresh,
                   "market_open": q["market_open"], "dominated_by_executable_alternative": False,
                   "execution_verified": False, "sufficient_size": q.get("available_quantity") is not None,
                   "fees_verified": False, "valuation_qualified": False,
                   "risk_limits_pass": False, "wagering_enabled": False}
        decision = decide_payload(payload)
        result.update({"decision": decision, "disposition": decision["disposition"], "fee_calculation": fee,
                       "compatibility": {"identity": identities, "binary_contract": binary,
                                         "state_alignment": state_aligned, "chronology_and_freshness": fresh,
                                         "fee_effective_window": fees_current},
                       "findings": decision["findings"] + ["VENUE_RULES_AUTHORITY_NOT_CONFIGURED",
                                   "QUOTE_AUTHENTICATION_NOT_CONFIGURED", "QUALIFICATION_REGISTRY_NOT_BOUND",
                                   "NO_EXECUTABLE_ALTERNATIVE_VERIFIED"]})
        if not fees_current:
            result["findings"].append("FEE_SCHEDULE_OUTSIDE_EFFECTIVE_WINDOW")
        result["claim_boundary"] = "Identity checks establish declared ID/team consistency only. Hash equality and declared rule consistency do not authenticate a source or qualify a forecast."
    except (ValueError, TypeError, KeyError, OSError, OverflowError) as exc:
        result["findings"].append("INVALID_OR_UNBOUND_EVIDENCE: " + str(exc))
    return result
