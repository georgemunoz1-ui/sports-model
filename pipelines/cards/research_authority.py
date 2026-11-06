"""Produce a deny-only typed sidecar for a sports.pregame_full_research_card.v2.

python -m pipelines.cards.research_authority INPUT.json NEW_SIDECAR.json

Consumers must require the supported output schema, matching input byte hash,
and an actual Boolean action_authority. Errors or missing data deny action.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path


class AuthorityError(ValueError):
    """The source cannot be represented by this research-only schema."""


def require(condition, path):
    if not condition:
        raise AuthorityError(f"Invalid or missing research control: {path}")


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def reject_constant(value):
    raise AuthorityError(f"Nonfinite JSON constant: {value}")


def off(value):
    return value is False or value == "OFF"


def zero(value):
    return type(value) in (int, float) and value == 0


def require_fields(row, path, *fields):
    require(isinstance(row, dict), path)
    for name in fields:
        require(name in row, f"{path}/{name}")


def check_explicit_controls(node, path=""):
    """Validate explicit authority controls wherever they occur in the source."""
    if isinstance(node, list):
        for i, child in enumerate(node):
            check_explicit_controls(child, f"{path}/{i}")
    elif isinstance(node, dict):
        for key, value in node.items():
            field = f"{path}/{key}"
            if key == "authority":
                require(off(value), field)
            elif key in {"action_authority", "official_selection", "official_recommendation",
                         "release_eligible", "official_release_eligible", "release_override"}:
                require(value is False, field)
            elif key in {"authorized_for_wagering", "wagering_enabled", "action_enabled"}:
                require(value is False, field)
            elif key == "wagering_authority":
                require(off(value), field)
            elif key in {"qualified_selections", "official_selections"}:
                require(isinstance(value, list) and not value, field)
            elif key in {"allocation_units", "allocated_units", "stake_units", "official_stake_units"}:
                require(zero(value), field)
            elif key in {"qualification", "book_qualification"}:
                require(value == "NO_PICK", field)
            check_explicit_controls(value, field)


MARKET_SIDES = {"winner": ("away", "home"), "spread": ("away", "home"),
                "total": ("under", "over")}


def controls():
    return {"action_authority": False, "qualification": "NO_PICK",
            "official_selection": False, "allocated_units": 0}


def contract_rows(records, path, event_id, arm):
    require(isinstance(records, list), path)
    out = []
    seen = set()
    for i, c in enumerate(records):
        loc = f"{path}/{i}"
        require_fields(c, loc, "action_authority", "qualification", "official_selection",
                       "allocation_units", "event_id", "arm", "market", "side")
        require(c["event_id"] == event_id and c["arm"] == arm, loc)
        market, side = c["market"], c["side"]
        require(isinstance(market, str) and side in MARKET_SIDES.get(market, ()), loc)
        require((market, side) not in seen, loc)
        seen.add((market, side))
        out.append({"market": market, "side": side, **controls()})
    expected_markets = MARKET_SIDES if arm == "baseline" else {market for market, _ in seen}
    expected = {(market, side) for market in expected_markets for side in MARKET_SIDES[market]}
    require(seen == expected, path)
    return out


def normalized_sidecar(raw):
    card = json.loads(raw, object_pairs_hook=unique_keys, parse_constant=reject_constant)
    require_fields(card, "/", "schema", "authority", "release_eligible", "allocated_units",
                   "qualified_selections", "events", "health", "league_schedule_counts")
    require(card["schema"] == "sports.pregame_full_research_card.v2", "/schema")
    check_explicit_controls(card)
    require_fields(card["health"], "/health", "action_authority", "official_release_eligible",
                   "release_override")
    require(isinstance(card["events"], list) and card["events"], "/events")
    require(isinstance(card["league_schedule_counts"], dict) and all(
        type(n) is int and n >= 0 for n in card["league_schedule_counts"].values()
    ), "/league_schedule_counts")
    events = []
    league_counts = Counter()
    seen = set()
    for i, e in enumerate(card["events"]):
        path = f"/events/{i}"
        require_fields(e, path, "event_id", "league", "action_authority", "qualification",
                       "allocated_units", "contracts", "challengers")
        league, eid = e["league"], e["event_id"]
        require(isinstance(league, str) and league and isinstance(eid, str)
                and eid.startswith(league + ":") and len(eid) > len(league) + 1
                and eid not in seen, path)
        seen.add(eid)
        league_counts[league] += 1
        # Missing legacy event authority is acceptable only with the three
        # explicit event controls above present and checked by check_explicit_controls.
        if "nhl_joint" in e:
            require_fields(e["nhl_joint"], path + "/nhl_joint", "authority")
        baseline = contract_rows(e["contracts"], path + "/contracts", eid, "baseline")
        require(isinstance(e["challengers"], list), path + "/challengers")
        arms = []
        arm_ids = set()
        for ai, a in enumerate(e["challengers"]):
            loc = f"{path}/challengers/{ai}"
            require_fields(a, loc, "arm", "model_id", "action_authority", "contracts")
            name, model_id = a["arm"], a["model_id"]
            require(isinstance(name, str) and name.strip() and name != "baseline"
                    and name not in arm_ids and isinstance(model_id, str) and model_id.strip(), loc)
            arm_ids.add(name)
            arms.append({"arm": name, "model_id": model_id, **controls(),
                         "contracts": contract_rows(a["contracts"], loc + "/contracts", eid, name)})
        events.append({"event_id": eid, **controls(), "baseline_contracts": baseline,
                       "challengers": arms})
    require(league_counts == Counter(card["league_schedule_counts"]), "/league_schedule_counts")
    return {"schema": "sports.research_authority_sidecar.v1",
            "source_schema": card["schema"], "source_sha256": sha256(raw).hexdigest(),
            **controls(), "events": events}


def write_sidecar(source, target):
    result = normalized_sidecar(source.read_bytes())
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    with target.open("x", encoding="utf-8") as f:
        f.write(encoded)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("new_sidecar", type=Path)
    args = parser.parse_args()
    write_sidecar(args.input, args.new_sidecar)
