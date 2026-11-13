"""Verify November 6 ESPN summary / DraftKings full-game point-spread bytes."""
import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


class QuoteEvidenceError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class VerifiedQuoteSource:
    """Source-only proof. Timestamp strings still require receipt-bound chronology."""
    source_sha256: str
    receipt_sha256: str
    requested_at_utc: str
    retrieved_at_utc: str
    source_start_utc: str
    observed_at_home: str | None
    observed_at_away: str | None
    receipt_observed_at_utc: str | None


def _require(ok, reason):
    if not ok:
        raise QuoteEvidenceError(reason)


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "SOURCE_JSON_AMBIGUOUS")
        result[key] = value
    return result


def _reject_nonfinite(_):
    raise QuoteEvidenceError("SOURCE_JSON_NONFINITE")


def _read_json(path, digest, kind):
    _require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest),
             "INVALID_SOURCE_DIGEST" if kind == "PAYLOAD" else "INVALID_SOURCE_RECEIPT_DIGEST")
    try:
        _require(path.is_file() and not path.is_symlink(), f"SOURCE_{kind}_MISSING")
        data = path.read_bytes()
    except OSError as exc:
        raise QuoteEvidenceError(f"SOURCE_{kind}_MISSING") from exc
    _require(hashlib.sha256(data).hexdigest() == digest,
             "SOURCE_DIGEST_MISMATCH" if kind == "PAYLOAD" else "SOURCE_RECEIPT_DIGEST_MISMATCH")
    try:
        parsed = json.loads(data, object_pairs_hook=_unique_fields, parse_constant=_reject_nonfinite)
    except QuoteEvidenceError:
        raise
    except (ValueError, RecursionError) as exc:
        raise QuoteEvidenceError(f"SOURCE_{kind}_INVALID") from exc
    _require(isinstance(parsed, dict), f"SOURCE_{kind}_INVALID")
    return parsed


def _check_link(link, side, espn_id, abbreviation, line, row):
    reason = "SOURCE_CONTRACT_MISMATCH"
    tags = link["tracking"]["tags"]
    rel = link["rel"]
    _require(isinstance(rel, list) and "bets" in rel and
             {r for r in rel if r in ("homeSpread", "awaySpread")} == {side + "Spread"} and
             tags["league"] == "mens-college-basketball" and tags["sport"] == "basketball" and
             tags["betType"] == "straight" and str(tags["gameId"]) == espn_id and
             tags["betDetails"] == f"Spread:{abbreviation}{line}", reason)
    gateway = urlsplit(link["href"])
    host = "sportsbook.draftkings.com"
    _require((gateway.scheme, gateway.netloc, gateway.path) == ("https", host, "/gateway"), reason)
    destinations = parse_qs(gateway.query, keep_blank_values=True).get("preurl", [])
    _require(len(destinations) == 1, reason)
    dest = urlsplit(destinations[0])
    event_match = re.fullmatch(r"/event/([0-9]+)/?", dest.path)
    outcomes = parse_qs(dest.query, keep_blank_values=True).get("outcomes", [])
    _require((dest.scheme, dest.netloc) == ("https", host) and event_match and
             event_match[1] == row["book_event_id"] and len(outcomes) == 1 and
             re.fullmatch(r"[A-Za-z0-9_-]+", outcomes[0]) and outcomes[0] == row["book_outcome_id"], reason)


def _match_provider(event, home, away, espn_id, source, url):
    header = source["header"]
    _require(header["league"]["slug"] == "mens-college-basketball" and
             str(header["id"]) == espn_id and len(header["competitions"]) == 1, "SOURCE_EVENT_MISMATCH")
    game = header["competitions"][0]
    _require(str(game["id"]) == espn_id and type(game["neutralSite"]) is bool and
             game["neutralSite"] is event["neutral"], "SOURCE_EVENT_MISMATCH")
    status = game["status"]["type"]
    _require(status["state"] == "pre" and status["completed"] is False and
             status["name"] == "STATUS_SCHEDULED", "SOURCE_EVENT_NOT_PREGAME")
    teams = {t["homeAway"]: t for t in game["competitors"]}
    _require(len(game["competitors"]) == 2 and set(teams) == {"home", "away"} and
             teams["home"]["id"] != teams["away"]["id"], "SOURCE_TEAM_MISMATCH")
    books = [b for b in source["pickcenter"] if
             b["provider"].get("name") == "DraftKings" or str(b["provider"].get("id")) == "100"]
    _require(len(books) == 1, "SOURCE_BOOK_MISMATCH")
    book = books[0]
    _require(str(book["provider"]["id"]) == "100" and book["provider"]["name"] == "DraftKings",
             "SOURCE_BOOK_MISMATCH")
    market = book["pointSpread"]
    # ESPN's full-game Game Odds / pointSpread product maps to the CBB full-game OT settlement.
    _require(book["header"]["text"] == "Game Odds" and
             market["displayName"] == market["shortDisplayName"] == "Spread", "SOURCE_CONTRACT_MISMATCH")
    observed = []
    for side, row in (("home", home), ("away", away)):
        team = teams[side]["team"]
        _require(str(teams[side]["id"]) == str(team["id"]) == str(book[side+"TeamOdds"]["teamId"])
                 == event[side+"_id"] and team["displayName"] == event[side] == home[side] == away[side],
                 "SOURCE_TEAM_MISMATCH")
        _require(event["event_id"] == row["event_id"] and row["espn_id"] == espn_id and
                 row["league"] == "CBB" and row["source_url"] == url, "SOURCE_EVENT_MISMATCH")
        _require(row["book"] == "DraftKings" and row["side"] == side and row["market"] == "spread" and
                 row["settlement"] == "FULL_GAME_INCLUDING_OVERTIME", "SOURCE_CONTRACT_MISMATCH")
        tick = market[side]["close"]
        raw_line = tick["line"]
        line = raw_line.strip().upper().replace("−", "-")
        value = Decimal("0" if line in {"PK", "PICK"} else line)
        odds = str(tick["odds"]).strip().upper().replace("−", "-")
        price = 100 if odds == "EVEN" else int(odds)
        _require(type(row["line"]) in (float, int) and value.is_finite() and
                 value == Decimal(str(row["line"])) and type(row["american"]) is int and
                 abs(price) >= 100 and row["american"] == price, "SOURCE_CONTRACT_MISMATCH")
        _check_link(tick["link"], side, espn_id, team["abbreviation"], raw_line, row)
        dates = {tick[k] for k in ("observedAt", "asOf", "lastUpdated", "updatedAt") if tick.get(k) is not None}
        _require(len(dates) <= 1, "SOURCE_OBSERVATION_AMBIGUOUS")
        observed.append(next(iter(dates), None))
    _require(home["book_event_id"] == away["book_event_id"] and
             home["book_outcome_id"] != away["book_outcome_id"] and
             home["line"] == -away["line"], "SOURCE_CONTRACT_MISMATCH")
    return game["date"], observed


def verify_quote_source(event, home, away, *, raw_dir: Path, receipt_sha256: str) -> VerifiedQuoteSource:
    """Resolve fixed event paths. The caller supplies the independently pinned receipt digest."""
    espn_id = event.get("espn_id")
    _require(isinstance(espn_id, str) and re.fullmatch(r"[0-9]+", espn_id) and
             event.get("event_id") == "CBB:" + espn_id and event.get("league") == "CBB",
             "SOURCE_EVENT_MISMATCH")
    root = Path(raw_dir)
    _require(not root.is_symlink(), "SOURCE_RECEIPT_MISSING")
    receipt = _read_json(root / f"CBB-{espn_id}.receipt.json", receipt_sha256, "RECEIPT")
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={espn_id}"
    _require(receipt.get("url") == url and receipt.get("http_status") == 200 and
             not receipt.get("error"), "SOURCE_RECEIPT_INVALID")
    for digest in (home.get("source_sha256"), away.get("source_sha256"), receipt.get("sha256")):
        _require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest), "INVALID_SOURCE_DIGEST")
    digest = receipt["sha256"]
    _require(home["source_sha256"] == away["source_sha256"] == digest, "SOURCE_DIGEST_MISMATCH")
    source = _read_json(root / f"CBB-{espn_id}.json", digest, "PAYLOAD")
    try:
        start, observed = _match_provider(event, home, away, espn_id, source, url)
    except QuoteEvidenceError:
        raise
    except (KeyError, ValueError, TypeError, IndexError, AttributeError, InvalidOperation) as exc:
        raise QuoteEvidenceError("SOURCE_PAYLOAD_INVALID") from exc
    return VerifiedQuoteSource(digest, receipt_sha256, receipt.get("requested_at_utc"),
                               receipt.get("retrieved_at_utc"), start, *observed,
                               receipt.get("provider_observed_at_utc"))
