import datetime as dt
import hashlib
import json

import pytest

from scripts.capture_cbb_daily import (
    daily,
    ncaa_events,
    ncaa_url,
    normalize,
    quote,
    reconcile_event,
)


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
        "id": "12345",
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


@pytest.mark.parametrize("conflicting_ncaa", [False, True])
def test_pacific_date_overlapping_boards_and_failed_price(tmp_path, conflicting_ncaa):
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
            contest = dict(official)
            if conflicting_ncaa and url == ncaa_url(day + dt.timedelta(days=1)):
                contest["gameState"] = "F"
            data = {"data": {"contests": [contest]}}
        return json.dumps(data).encode(), {
            "url": url,
            "file": "fixture",
            "sha256": "a" * 64,
            "retrieved_at_utc": "2026-11-04T10:00Z",
        }

    path = tmp_path / "new"
    result = daily(day, path, fixture)
    assert (
        json.loads((path / "manifest.json").read_bytes())["coverage_sha256"]
        == hashlib.sha256((path / "coverage.json").read_bytes()).hexdigest()
    )
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
    assert result["events"][0]["status"] == (
        "FINAL_RECONCILIATION_REQUIRED" if conflicting_ncaa else "PENDING"
    )
    assert result["events"][0]["ncaa_contest_id"] == 55


@pytest.mark.parametrize(
    "espn_status,ncaa_state,home_points,offset,expected",
    [
        ("STATUS_FINAL", "F", 80, 0, "FINAL_RECONCILED"),
        ("STATUS_FINAL", "F", 79, 0, "FINAL_RECONCILIATION_REQUIRED"),
        ("STATUS_FINAL", "P", 80, 0, "FINAL_RECONCILIATION_REQUIRED"),
        ("STATUS_SCHEDULED", "F", 80, 0, "FINAL_RECONCILIATION_REQUIRED"),
        ("STATUS_SCHEDULED", "P", 80, 0, "PENDING"),
        ("STATUS_FINAL", "F", 80, 300, "TIP_RECONCILIATION_REQUIRED"),
        ("STATUS_FINAL", "F", 79, 300, "FINAL_RECONCILIATION_REQUIRED"),
    ],
)
def test_reconciled_evidence(espn_status, ncaa_state, home_points, offset, expected):
    e = event(espn_status)
    espn = {"url": "espn-board", "sha256": "a" * 64}
    ncaa = {"url": "ncaa-board", "sha256": "c" * 64}
    c = {
        "contestId": 55,
        "gameState": ncaa_state,
        "startTimeEpoch": int(dt.datetime.fromisoformat(e["date"]).timestamp())
        + offset,
        "teams": [
            {"isHome": True, "nameShort": "LMU (CA)", "score": home_points},
            {"isHome": False, "nameShort": "Queens (NC)", "score": 65},
        ],
    }
    record = reconcile_event(e, espn, c, ncaa)
    assert record["event_id"] == "CBB:12345"
    assert record["espn_scoreboard_sha256"] == espn["sha256"]
    assert record["ncaa_scoreboard_sha256"] == ncaa["sha256"]
    assert record["status"] == expected
    if offset and home_points != 80:
        assert set(record["issues"]) == {
            "FINAL_RECONCILIATION_REQUIRED",
            "TIP_RECONCILIATION_REQUIRED",
        }
    assert (record["home_score"], record["away_score"]) == (
        (80, 65) if expected == "FINAL_RECONCILED" else (None, None)
    )
