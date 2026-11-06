"""Post-price research disclosure chosen after the 2026-11-05 CBB slate."""

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from math import isclose, isfinite

from .cbb_incident_bundle import BundleError, IncidentBundle
from .cbb_quote_chronology import ChronologyError, check_pregame_pair_chronology, parse_utc
from .cbb_quote_evidence import QuoteEvidenceError, verify_quote_source

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


def _spread_sides(event):
    """Match recorded sides structurally, before verifying evidence."""
    contracts = event.get("contracts")
    if not isinstance(contracts, list):
        return None
    rows = [c for c in contracts if isinstance(c, dict) and c.get("market") == "spread"
            and c.get("arm") == "baseline"]
    if len(rows) != 2 or not all(any(c.get("side") == side for c in rows)
                                 for side in ("home", "away")):
        return None
    home, away = sorted(rows, key=lambda c: c["side"], reverse=True)
    for key in ("event_id", "book", "book_event_id", "source_sha256", "settlement"):
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
        if (c.get("quote_status") != "EXACT_PAIR"
                or type(c.get("american")) is not int or abs(c["american"]) < 100
                or not _number(c.get("line"))):
            return None
    return (home, away) if away["line"] == -home["line"] else None


@dataclass(frozen=True)
class VerifiedSpread:
    away: dict
    source_sha256: str
    receipt_sha256: str
    retrieved_utc: str
    tipoff_utc: str
    cutoff_utc: str
    observation_basis: str


def _paired_spread(event, sides, bundle):
    home, away = sides
    stem = event["event_id"].replace(":", "-")
    raw = "market/raw/" + stem
    source = verify_quote_source(
        event, home, away, raw_dir=bundle.root / "market/raw",
        receipt_sha256=bundle.pins.get(raw + ".receipt.json"),
    )
    if source.source_sha256 != bundle.pins.get(raw + ".json"):
        raise BundleError("SOURCE_NOT_BOUND_TO_MANIFEST")
    context = bundle.context(event)
    check = check_pregame_pair_chronology(event, home, away, context=context)
    if parse_utc(source.source_start_utc, "INVALID_VERIFIED_TIPOFF") != context.verified_tipoff_utc:
        raise BundleError("SOURCE_START_MISMATCH")
    if parse_utc(source.retrieved_at_utc, "INVALID_RECEIPT_RETRIEVAL") != check.retrieved_utc:
        raise BundleError("RECEIPT_RETRIEVAL_MISMATCH")
    requested = parse_utc(source.requested_at_utc, "INVALID_RECEIPT_REQUEST")
    if not context.forecast_sealed_utc <= requested <= check.retrieved_utc:
        raise BundleError("RECEIPT_REQUEST_OUT_OF_SEQUENCE")
    for side, observed in ((home, source.observed_at_home), (away, source.observed_at_away)):
        reported = side.get("observed_at_utc")
        if (observed is None) != (reported is None) or (observed is not None and
                parse_utc(observed, "INVALID_VENDOR_OBSERVATION") !=
                parse_utc(reported, "INVALID_VENDOR_OBSERVATION")):
            raise BundleError("SOURCE_OBSERVATION_MISMATCH")
    if source.receipt_observed_at_utc is not None and parse_utc(
            source.receipt_observed_at_utc, "INVALID_VENDOR_OBSERVATION") > check.retrieved_utc:
        raise BundleError("VENDOR_OBSERVATION_AFTER_RETRIEVAL")
    return VerifiedSpread(away, source.source_sha256, source.receipt_sha256,
                          check.retrieved_utc.isoformat(), context.verified_tipoff_utc.isoformat(),
                          context.quote_cutoff_utc.isoformat(), check.observation_basis)


def incident_rows(card):
    """A card alone cannot authenticate prices, schedule or evaluation policy."""
    yield from _rows(card, None, "EVIDENCE_BUNDLE_REQUIRED")


def _rows(card, bundle, bundle_error):
    seen = set()
    for event in card["events"]:
        if event.get("league") != "CBB":
            continue
        eid = event["event_id"]
        if not eid or eid in seen:
            raise ValueError("Missing or duplicate CBB event ID")
        seen.add(eid)
        sides = _spread_sides(event)
        pair = None
        reason = bundle_error
        if sides is None:
            reason = "EXACT_SPREAD_PAIR_UNAVAILABLE"
        elif bundle is not None:
            try:
                pair = _paired_spread(event, sides, bundle)
            except (BundleError, ChronologyError, QuoteEvidenceError) as exc:
                reason = exc.reason
        market_margin = pair.away["line"] if pair else None
        parent = event.get("spread_head_home_margin")
        if parent is None:
            parent = event.get("home_margin")
        home_margin = parent if _number(parent) else None
        c = sides[1] if sides else {}
        ok, flag = cbb_road_dog_review(
            league="CBB", market="spread", side="away", neutral=event.get("neutral"),
            line=market_margin, win_mass=c.get("win"), loss_mass=c.get("loss"),
            push_mass=c.get("push"), has_paired_price=isinstance(pair, VerifiedSpread) and c.get("push") is not None,
        )
        yield {
            "evidence_reason": reason or (None if ok else "INVALID_INCIDENT_INPUTS"),
            "verified_quote": {k: v for k, v in vars(pair).items() if k != "away"} if pair else None,
            "event_id": eid, "side": "away", "arm": "baseline",
            "house_home_margin": home_margin, "market_home_margin": market_margin,
            "home_margin_gap": home_margin - market_margin
            if home_margin is not None and market_margin is not None else None,
            "raw_win": c.get("win"), "raw_push": c.get("push"), "raw_loss": c.get("loss"),
            "decisive_probability": c["win"] / (c["win"] + c["loss"]) if ok else None,
            "incident_evaluable": ok, "incident_review": LABEL if flag else None,
            "qualification": "NO_PICK", "action_authority": False, "allocation_units": 0,
        }


def review_sidecar(data, *, evidence_root=None, manifest_sha256=None):
    """Build the review from the same priced-card bytes checked against the manifest."""
    digest = hashlib.sha256(data).hexdigest()
    card = json.loads(data)
    try:
        bundle = IncidentBundle(evidence_root, manifest_sha256, digest, card)
        reason = None
    except (BundleError, ChronologyError) as exc:
        bundle, reason = None, exc.reason
    return {
        "schema": "sports.cbb.postprice_incident.v2",
        "priced_card_sha256": digest, "evidence_manifest_sha256": manifest_sha256,
        "scope": "Post-price CBB incident review. Research only.",
        "verification_time_utc": bundle.verified_at.isoformat() if bundle else None,
        "threshold_decisive": float(DECISIVE_THRESHOLD),
        "rows": list(_rows(card, bundle, reason)),
    }


def main():
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Write a CBB post-price incident sidecar.")
    parser.add_argument("priced_card", type=Path)
    parser.add_argument("new_review", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--manifest-sha256", help="Independently pinned digest of SHA256SUMS.txt")
    args = parser.parse_args()
    result = review_sidecar(args.priced_card.read_bytes(), evidence_root=args.evidence_root,
                            manifest_sha256=args.manifest_sha256)
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2)
    with args.new_review.open("x", encoding="utf8") as f:
        f.write(encoded + "\n")


if __name__ == "__main__":
    main()
