"""Post-price research disclosure chosen after the 2026-11-05 CBB slate."""

from decimal import Decimal
from math import isclose, isfinite

LABEL = "RESEARCH_ONLY — HIGH_CONFIDENCE_ROAD_DOG_REVIEW"
DECISIVE_THRESHOLD = Decimal("0.80")


def _number(value):
    return type(value) is int or (type(value) is float and isfinite(value))


def cbb_road_dog_review(*, league, market, side, neutral, line, win_mass, loss_mass,
                        has_paired_price, arm="baseline", push_mass=None):
    """Return (evaluable, flagged) for the baseline away CBB spread only.

    has_paired_price must attest exact opposing, same-book full-game prices.
    Use the unrounded decimal input masses for the inclusive threshold.
    """
    if (league, market, side, arm) != ("CBB", "spread", "away", "baseline"):
        return False, False
    if type(neutral) is not bool or has_paired_price is not True or not _number(line):
        return False, False
    if not all(_number(v) and 0 <= v <= 1 for v in (win_mass, loss_mass)):
        return False, False
    if win_mass + loss_mass > 1 + 1e-12 or win_mass + loss_mass == 0:
        return False, False
    if push_mass is not None and not (
        _number(push_mass) and 0 <= push_mass <= 1
        and isclose(win_mass + loss_mass + push_mass, 1, rel_tol=0, abs_tol=1e-12)
    ):
        return False, False
    win, loss = Decimal(str(win_mass)), Decimal(str(loss_mass))
    flagged = not neutral and line > 0 and win >= DECISIVE_THRESHOLD * (win + loss)
    return True, flagged


def _paired_spread(event):
    """Match opposite sides of the same recorded pregame book offer."""
    rows = [c for c in event.get("contracts", []) if c.get("market") == "spread"
            and c.get("arm", "baseline") == "baseline"]
    if len(rows) != 2 or {c.get("side") for c in rows} != {"home", "away"}:
        return None
    home, away = sorted(rows, key=lambda c: c["side"], reverse=True)
    for key in ("event_id", "book", "book_event_id", "source_sha256", "settlement",
                "quote_retrieved_utc"):
        if not home.get(key) or home[key] != away.get(key):
            return None
    if (event.get("event_id") != away["event_id"] or
            away["settlement"] != "FULL_GAME_INCLUDING_OVERTIME"):
        return None
    if not all(event.get(team) and event[team] == home.get(team) == away.get(team)
               for team in ("home", "away")):
        return None
    if not home.get("book_outcome_id") or not away.get("book_outcome_id") or (
        home["book_outcome_id"] == away["book_outcome_id"]
    ):
        return None
    for c in rows:
        if (c.get("quote_status", "EXACT_PAIR") != "EXACT_PAIR"
                or type(c.get("american")) is not int or abs(c["american"]) < 100
                or not _number(c.get("line"))):
            return None
    return away if away["line"] == -home["line"] else None


def incident_rows(card):
    """Generate a read-only sidecar for each CBB matchup, regardless of coverage."""
    seen = set()
    for event in card["events"]:
        if event.get("league") != "CBB":
            continue
        eid = event["event_id"]
        if not eid or eid in seen:
            raise ValueError("Missing or duplicate CBB event ID")
        seen.add(eid)
        away = _paired_spread(event)
        market_margin = away["line"] if away else None
        parent = event.get("spread_head_home_margin")
        if parent is None:
            parent = event.get("home_margin")
        home_margin = parent if _number(parent) else None
        c = away or {}
        ok, flag = cbb_road_dog_review(
            league="CBB", market="spread", side="away", neutral=event.get("neutral"),
            line=market_margin, win_mass=c.get("win"), loss_mass=c.get("loss"),
            push_mass=c.get("push"), has_paired_price=away is not None and c.get("push") is not None,
        )
        yield {
            "event_id": eid, "side": "away", "arm": "baseline",
            "house_home_margin": home_margin, "market_home_margin": market_margin,
            "home_margin_gap": home_margin - market_margin
            if home_margin is not None and market_margin is not None else None,
            "raw_win": c.get("win"), "raw_push": c.get("push"), "raw_loss": c.get("loss"),
            "decisive_probability": c["win"] / (c["win"] + c["loss"]) if ok else None,
            "incident_evaluable": ok, "incident_review": LABEL if flag else None,
            "qualification": "NO_PICK", "action_authority": False, "allocation_units": 0,
        }


def main():
    """python -m pipelines.cards.cbb_incident FROZEN_PRICED_CARD.json NEW_REVIEW.json"""
    import argparse
    import hashlib
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Write a CBB post-price incident sidecar.")
    parser.add_argument("priced_card", type=Path)
    parser.add_argument("new_review", type=Path)
    args = parser.parse_args()
    data = args.priced_card.read_bytes()
    result = {
        "schema": "sports.cbb.postprice_incident.v1",
        "priced_card_sha256": hashlib.sha256(data).hexdigest(),
        "scope": "Incident chosen after 2026-11-05. Research only; no promotion or allocation.",
        "threshold_decisive": float(DECISIVE_THRESHOLD),
        "rows": list(incident_rows(json.loads(data))),
    }
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2)
    with args.new_review.open("x", encoding="utf8") as f:
        f.write(encoded + "\n")


if __name__ == "__main__":
    main()
