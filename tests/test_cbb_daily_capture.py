import datetime as dt
import json

import pytest

from scripts.capture_cbb_daily import daily, ncaa_events, normalize, quote


def event(status="STATUS_SCHEDULED"):
    pair = [
        {
            "id": i,
            "homeAway": s,
            "score": "80" if s == "home" else "65",
            "team": {"id": i, "displayName": n},
        }
        for i, s, n in (("2511", "away", "Queens"), ("2351", "home", "LMU"))
    ]
    comp = {
        "date": "2026-11-05T03:00Z",
        "competitors": pair,
        "neutralSite": False,
        "status": {
            "type": {
                "state": "pre" if status == "STATUS_SCHEDULED" else "post",
                "name": status,
                "completed": status != "STATUS_SCHEDULED",
            }
        },
    }
    return {
        "id": "12345",
        "date": comp["date"],
        "competitions": [comp],
        "season": {"type": 2},
    }


def test_cancelled_game_has_no_graded_final():
    row = normalize(event("STATUS_CANCELED"), {"2511", "2351"})
    assert row["both_d1"] and not row["completed"] and row["home_score"] is None


def test_market_identity_times_and_nonstandard_prices():
    e = event()
    row = normalize(e, {"2511", "2351"})
    receipt = {
        "sha256": "a" * 64,
        "file": "raw/a",
        "url": "fixture",
        "retrieved_at_utc": "2026-11-04T12:00Z",
    }
    book = {
        "provider": {"name": "DraftKings"},
        "pointSpread": {
            "home": {"close": {"line": "-6.5", "odds": "-110"}},
            "away": {"close": {"line": "+6.5", "odds": "-110"}},
        },
        "moneyline": {
            "home": {"close": {"odds": "OFF"}},
            "away": {"close": {"odds": "OFF"}},
        },
    }
    data = {"header": e, "pickcenter": [book]}
    q = quote(row, data, receipt)
    assert q["quote_status"] == "CAPTURED_PRETIP" and q["home_spread"] == -6.5
    assert q["provider_quote_observed_at_utc"] is None and q["home_ml_price"] is None
    later = quote(row, data, {**receipt, "retrieved_at_utc": e["date"]})
    assert (
        later["quote_status"] == "NO_PREGAME_OR_FINAL_QUOTE"
        and later["home_spread"] is None
    )
    with pytest.raises(ValueError, match="SCOPE"):
        quote({**row, "away_id": "different"}, data, receipt)
    book["pointSpread"]["away"]["close"]["line"] = "+5.5"
    with pytest.raises(ValueError, match="COMPLEMENTS"):
        quote(row, data, receipt)


def test_failed_source_is_not_an_empty_slate(tmp_path):
    def unavailable(path, url):
        raise OSError("source unavailable")

    path = tmp_path / "new"
    assert daily(dt.date(2026, 11, 4), path, get=unavailable)["status"] == "BLOCKED"
    assert not list(path.glob("schedule*"))
    with pytest.raises(FileExistsError):
        daily(dt.date(2026, 11, 4), path, get=unavailable)
    with pytest.raises(ValueError, match="NCAA"):
        ncaa_events(json.dumps({"errors": ["query failed"]}).encode())


def test_pacific_date_overlapping_boards_and_failed_price(tmp_path):
    from scripts.capture_cbb_daily import ESPN, STANDINGS

    day = dt.date(2026, 11, 4)
    target = event()
    boundary = event()
    boundary.update(id="21321", date="2026-11-04T05:59Z")  # previous Pacific date
    coverage = {
        "season": {"year": 2027},
        "children": [
            {
                "standings": {
                    "entries": [{"team": {"id": str(i)}} for i in range(500)]
                    + [{"team": {"id": "2511"}}, {"team": {"id": "2351"}}]
                }
            }
        ],
    }
    start = int(dt.datetime.fromisoformat(target["date"]).timestamp())
    official = {
        "contestId": 55,
        "startTimeEpoch": start,
        "gameState": "P",
        "teams": [
            {"isHome": True, "nameShort": "LMU (CA)"},
            {"isHome": False, "nameShort": "Queens (NC)"},
        ],
    }

    def fixture(path, url):
        if url.startswith(STANDINGS):
            data = coverage
        elif url.startswith(ESPN + "scoreboard"):
            data = {"events": [target, boundary]}
        elif url.startswith(ESPN + "summary"):
            raise OSError("offline")
        else:
            data = {"data": {"contests": [official]}}
        return json.dumps(data).encode(), {
            "url": url,
            "file": "fixture",
            "sha256": "a" * 64,
            "retrieved_at_utc": "2026-11-04T10:00Z",
        }

    path = tmp_path / "new"
    result = daily(day, path, fixture)
    assert result["status"] == "REQUIRES_REVIEW"
    assert (result["espn_events"], result["ncaa_events"], result["d1_vs_d1"]) == (
        1,
        1,
        1,
    )
    quotes = json.loads((path / "quotes-20261104.json").read_bytes())["quotes"]
    assert (
        quotes[0]["quote_status"] == "QUOTE_SOURCE_UNAVAILABLE"
        and quotes[0]["home_spread"] is None
    )
