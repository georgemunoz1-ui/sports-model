import hashlib
import json
from urllib.parse import urlencode

import pytest

from pipelines.cards.cbb_quote_evidence import QuoteEvidenceError, verify_quote_source


def _write(path, value):
    data = json.dumps(value).encode()
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def make_source_fixture(raw_dir, espn_id="1"):
    """A synthetic two-sided offer in the retained November 6 ESPN summary format."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    tip = "2026-11-06T18:00Z"
    event_id = "CBB:" + espn_id
    book_id = str(122 + int(espn_id))
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={espn_id}"
    retrieved = "2026-11-06T10:00Z"
    event = dict(event_id=event_id, espn_id=espn_id, league="CBB", neutral=False, home_margin=1.5,
                 home="H" + espn_id, home_id=str(10 + int(espn_id)),
                 away="A" + espn_id, away_id=str(21 + int(espn_id)), start_time_utc=tip, contracts=[])
    game = dict(id=espn_id, date=tip, neutralSite=False, competitors=[],
                status={"type": {"state":"pre", "name":"STATUS_SCHEDULED", "completed":False}})
    spread = dict(displayName="Spread", shortDisplayName="Spread")
    book = dict(provider={"id":"100", "name":"DraftKings"}, header={"text":"Game Odds"}, pointSpread=spread)
    for side, line, win, loss in (("away", "+3", .72, .18), ("home", "-3", .18, .72)):
        ident = event[side+"_id"]
        team = event[side]
        game["competitors"].append(dict(homeAway=side, id=ident,
                                     team=dict(id=ident, displayName=team, abbreviation=team)))
        book[side+"TeamOdds"] = {"teamId":ident}
        outcome_id = side + str(2 + int(espn_id))
        dest = f"https://sportsbook.draftkings.com/event/{book_id}?outcomes={outcome_id}"
        tags = dict(league="mens-college-basketball", sport="basketball", gameId=int(espn_id),
                    betType="straight", betDetails=f"Spread:{team}{line}")
        spread[side] = {"close":{"line":line, "odds":"-110",
                                 "link":{"rel":[side+"Spread", "desktop", "bets"],
                                         "href":"https://sportsbook.draftkings.com/gateway?" +
                                                urlencode({"preurl":dest}),
                                         "tracking":{"tags":tags}}}}
        event["contracts"].append(dict(event_id=event_id, espn_id=espn_id, league="CBB", market="spread",
                  side=side, line=int(line), american=-110, home=event["home"], away=event["away"],
                  book="DraftKings", book_event_id=book_id, book_outcome_id=outcome_id,
                  settlement="FULL_GAME_INCLUDING_OVERTIME", source_url=url, arm="baseline",
                  quote_status="EXACT_PAIR", quote_retrieved_utc=retrieved, retrieved_at_utc=retrieved,
                  observed_at_utc=None, start_time_utc=tip, win=win, push=.1, loss=loss))
    data = dict(header=dict(league={"slug":"mens-college-basketball"}, id=espn_id, competitions=[game]), pickcenter=[book])
    digest = _write(raw_dir/f"CBB-{espn_id}.json", data)
    for row in event["contracts"]:
        row["source_sha256"] = digest
    receipt = dict(url=url, http_status=200, requested_at_utc="2026-11-06T09:59:59Z",
                   retrieved_at_utc=retrieved, provider_observed_at_utc=None, sha256=digest)
    return event, _write(raw_dir/f"CBB-{espn_id}.receipt.json", receipt)


def _verify(directory, event, pin):
    sides = {row["side"]:row for row in event["contracts"]}
    return verify_quote_source(event, sides["home"], sides["away"], raw_dir=directory, receipt_sha256=pin)


def test_pinned_retained_spread(tmp_path):
    event, pin = make_source_fixture(tmp_path)
    evidence = _verify(tmp_path, event, pin)
    assert evidence.receipt_sha256 == pin
    assert evidence.source_sha256 == event["contracts"][0]["source_sha256"]
    assert evidence.retrieved_at_utc == "2026-11-06T10:00Z"
    assert evidence.source_start_utc == event["start_time_utc"]
    assert evidence.observed_at_home is evidence.observed_at_away is None


@pytest.mark.parametrize("problem,reason", [
    ("malformed", "INVALID_SOURCE_DIGEST"), ("missing", "SOURCE_PAYLOAD_MISSING"),
    ("wrong_bytes", "SOURCE_DIGEST_MISMATCH"), ("wrong_digest", "SOURCE_DIGEST_MISMATCH"),
    ("bad_receipt", "SOURCE_RECEIPT_DIGEST_MISMATCH"), ("no_receipt", "SOURCE_RECEIPT_MISSING"),
    ("wrong_pin", "SOURCE_RECEIPT_DIGEST_MISMATCH"), ("bad_pin_format", "INVALID_SOURCE_RECEIPT_DIGEST"),
])
def test_fail_closed_on_unbound_source(tmp_path, problem, reason):
    event, pin = make_source_fixture(tmp_path)
    path = tmp_path/"CBB-1.json"
    receipt = tmp_path/"CBB-1.receipt.json"
    if problem in {"malformed", "wrong_digest"}:
        for row in event["contracts"]:
            row["source_sha256"] = "invalid" if problem == "malformed" else "0"*64
    elif problem == "missing":
        path.unlink()
    elif problem == "wrong_bytes":
        path.write_bytes(path.read_bytes() + b" ")
    elif problem == "bad_receipt":
        receipt.write_bytes(receipt.read_bytes() + b" ")
    elif problem == "no_receipt":
        receipt.unlink()
    elif problem == "wrong_pin":
        pin = "0"*64
    else:
        pin = "invalid"
    with pytest.raises(QuoteEvidenceError) as err:
        _verify(tmp_path, event, pin)
    assert err.value.reason == reason


@pytest.mark.parametrize("field,bad_value,reason", [
    (("header","id"), "8", "SOURCE_EVENT_MISMATCH"),
    (("header","competitions",0,"id"), "8", "SOURCE_EVENT_MISMATCH"),
    (("header","competitions",0,"status","type","state"), "post", "SOURCE_EVENT_NOT_PREGAME"),
    (("header","competitions",0,"neutralSite"), True, "SOURCE_EVENT_MISMATCH"),
    (("header","competitions",0,"competitors",0,"team","id"), "77", "SOURCE_TEAM_MISMATCH"),
    (("pickcenter",0,"awayTeamOdds","teamId"), "11", "SOURCE_TEAM_MISMATCH"),
    (("pickcenter",0,"header","text"), "First Half", "SOURCE_CONTRACT_MISMATCH"),
    (("pickcenter",0,"provider","name"), "Other book", "SOURCE_BOOK_MISMATCH"),
    (("pickcenter",0,"pointSpread","away","close","odds"), "-115", "SOURCE_CONTRACT_MISMATCH"),
    (("pickcenter",0,"pointSpread","away","close","line"), "-3", "SOURCE_CONTRACT_MISMATCH"),
    (("pickcenter",0,"pointSpread","away","close","link","rel"), ["homeSpread","bets"], "SOURCE_CONTRACT_MISMATCH"),
    (("pickcenter",0,"pointSpread","away","close","link","tracking","tags","gameId"), 9, "SOURCE_CONTRACT_MISMATCH"),
    (("pickcenter",0,"pointSpread","away","close","link","href"),
     "https://sportsbook.draftkings.com/gateway?preurl=https://sportsbook.draftkings.com/event/987?outcomes=away3",
     "SOURCE_CONTRACT_MISMATCH"),
    (("pickcenter",0,"pointSpread","away","close","link","href"),
     "https://sportsbook.draftkings.com/gateway?preurl=https://sportsbook.draftkings.com/event/123?outcomes=home3",
     "SOURCE_CONTRACT_MISMATCH"),
])
def test_correct_hash_wrong_event_or_contract(tmp_path, field, bad_value, reason):
    event, _ = make_source_fixture(tmp_path)
    raw = tmp_path/"CBB-1.json"
    receipt = tmp_path/"CBB-1.receipt.json"
    data = json.loads(raw.read_bytes())
    node = data
    for key in field[:-1]:
        node = node[key]
    node[field[-1]] = bad_value
    source_digest = _write(raw, data)
    for row in event["contracts"]:
        row["source_sha256"] = source_digest
    pin = _write(receipt, json.loads(receipt.read_bytes()) | {"sha256":source_digest})
    with pytest.raises(QuoteEvidenceError) as err:
        _verify(tmp_path, event, pin)
    assert err.value.reason == reason
