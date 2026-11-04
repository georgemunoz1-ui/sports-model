import hashlib
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from scripts.capture_cbb_daily import ESPN, STANDINGS, daily, ncaa_url
from scripts.cbb_market_and_grades import (
    digest,
    grade,
    market_rows,
    parse_price,
    probability,
)


def test_handicaps_are_in_selected_side_orientation():
    m = {"support": [-2, 2, 5], "masses": [0.2, 0.5, 0.3]}
    assert probability(m, 1, -2) == {"win": 0.3, "push": 0.5, "loss": 0.2}
    assert probability(m, -1, 2) == {"win": 0.2, "push": 0.5, "loss": 0.3}
    with pytest.raises(ValueError):
        probability({"support": [2], "masses": [float("nan")]}, 1, -2)
    assert parse_price("OFF") is None


def test_quote_types_and_two_sided_price_requirement():
    fc = {
        "p_home_win": 0.8,
        "distributions": {"total": {"support": [150, 152], "masses": [0.4, 0.6]}},
    }
    odds = {
        "provider": {"name": "DraftKings"},
        "total": {
            "over": {"close": {"line": "o150", "odds": "-110"}},
            "under": {"close": {"line": "u150", "odds": "-110"}},
        },
        "moneyline": {
            "home": {"close": {"odds": "OFF"}},
            "away": {"close": {"odds": "+200"}},
        },
    }
    out = market_rows({"pickcenter": [odds]}, fc)
    assert [(x["side"], x["win"], x["push"]) for x in out] == [
        ("over", 0.6, 0.4),
        ("under", 0.0, 0.4),
    ]


PARENT_PIN = "d" * 64
MARKET_PIN = "e" * 64
DAY = date(2020, 1, 1)
START = "2020-01-02T00:00Z"


def setup_assessment(
    path,
    *,
    ncaa_score=80,
    espn_final=True,
    ncaa_final=True,
    summary_score=80,
    summary_final=True,
    ncaa_sides_swapped=False,
):
    # Two events on the same provider pages. Only the first is varied.
    pairs = [("1", "2"), ("3", "4")]

    def event(i, score=80, final=True):
        home, away = pairs[i]
        eid = str(7 + i)
        teams = [
            {
                "homeAway": side,
                "id": tid,
                "team": {"id": tid, "displayName": "Team " + tid},
                "score": str(val),
            }
            for side, tid, val in [("home", home, score), ("away", away, 76)]
        ]
        st = (
            {"completed": True, "state": "post", "name": "STATUS_FINAL"}
            if final
            else {"completed": False, "state": "in", "name": "STATUS_IN_PROGRESS"}
        )
        return {
            "id": eid,
            "date": START,
            "season": {"type": 2},
            "competitions": [
                {
                    "id": eid,
                    "date": START,
                    "neutralSite": False,
                    "competitors": teams,
                    "status": {"type": st},
                }
            ],
        }

    def contest(i):
        home, away = pairs[i]
        return {
            "contestId": 17 + i,
            "startTimeEpoch": int(datetime.fromisoformat(START).timestamp()),
            "gameState": "F" if i or ncaa_final else "L",
            "teams": [
                {
                    "isHome": bool(i or not ncaa_sides_swapped),
                    "nameShort": "Team " + home,
                    "score": 80 if i else ncaa_score,
                },
                {
                    "isHome": not (i or not ncaa_sides_swapped),
                    "nameShort": "Team " + away,
                    "score": 76,
                },
            ],
        }

    def get(out, url):
        if url.startswith(STANDINGS):
            obj = {
                "season": {"year": 2020},
                "children": [
                    {
                        "standings": {
                            "entries": [{"team": {"id": str(i)}} for i in range(301)]
                        }
                    }
                ],
            }
        elif url.startswith(ESPN + "scoreboard"):
            obj = {
                "events": [event(0, final=espn_final), event(1)]
                if "dates=20200101" in url
                else []
            }
        elif url.startswith(ESPN + "summary"):
            obj = {
                "header": event(0, summary_score, summary_final)
                if url.endswith("=7")
                else event(1)
            }
        else:
            obj = {
                "data": {
                    "contests": [contest(0), contest(1)] if url == ncaa_url(DAY) else []
                }
            }
        body = json.dumps(obj).encode()
        sha = hashlib.sha256(body).hexdigest()
        dest = out / "raw" / (sha + ".json")
        dest.parent.mkdir(exist_ok=True)
        dest.write_bytes(body)
        return body, {
            "url": url,
            "file": str(dest.relative_to(out)),
            "sha256": sha,
            "retrieved_at_utc": "2020-01-02T03:00Z",
        }

    daily(DAY, path, get)
    predictions = [
        {
            "event_id": "CBB:" + str(7 + i),
            "forecast_status": "FORECAST_GENERATED",
            "start_time_utc": START,
            "home_margin": 6,
            "total": 140,
            "p_home_win": 0.7,
            "model_input_snapshot": {"h": h, "a": a, "neutral": False},
        }
        for i, (h, a) in enumerate(pairs)
    ]
    card = {
        "schema": "sports.cbb.shadow_card.v1",
        "league": "CBB",
        "market_input": False,
        "action_authority": False,
        "scheduled": 2,
        "date": DAY.isoformat(),
        "forecasts": predictions,
        "forecast_count": 2,
        "as_of_utc": "2020-01-01T18:00Z",
        "generated_at_utc": "2020-01-01T18:01Z",
    }
    market = {
        "schema": "sports.cbb.market.shadow.v1",
        "date": card["date"],
        "frozen_parent_sha256": PARENT_PIN,
        "action_authority": False,
        "created_at_utc": "2020-01-01T18:02Z",
        "rows": [
            {
                "event_id": r["event_id"],
                "quote_retrieved_at_utc": "2020-01-01T17:59Z",
                "contracts": [
                    {
                        "product": "margin",
                        "side": "away",
                        "line": 4,
                        "win": 0.60,
                        "push": 0.02,
                    },
                    {
                        "product": "margin",
                        "side": "home",
                        "line": -4,
                        "win": 0.38,
                        "push": 0.02,
                    },
                ],
            }
            for r in predictions
        ],
    }
    return card, market


def run(path, card, market):
    return grade(
        card,
        market,
        path,
        PARENT_PIN,
        digest(path / "manifest.json"),
        market_sha=MARKET_PIN,
    )


def repin_coverage(path, coverage):
    covpath, manpath = path / "coverage.json", path / "manifest.json"
    covpath.write_text(json.dumps(coverage))
    manifest = json.loads(manpath.read_bytes())
    manifest["coverage_sha256"] = digest(covpath)
    manpath.write_text(json.dumps(manifest))


@pytest.mark.parametrize(
    "issue,blocking",
    [
        ("QUOTE_SOURCE_UNAVAILABLE", False),
        ("TIP_RECONCILIATION_REQUIRED", True),
        ("IDENTITY_NOT_CROSS_CHECKED", True),
        ("UNRECOGNIZED_RESULT_ISSUE", True),
    ],
)
def test_recorded_issue_respects_event_and_product_scope(tmp_path, issue, blocking):
    path = tmp_path / "capture"
    card, market = setup_assessment(path)
    coverage = json.loads((path / "coverage.json").read_bytes())
    coverage.update(
        status="REQUIRES_REVIEW", issues=[{"event_id": "CBB:7", "issue": issue}]
    )
    repin_coverage(path, coverage)
    result = run(path, card, market)
    first, clean = result["rows"]
    assert result["reconciliation"]["sha256"] == digest(path / "coverage.json")
    assert result["reconciliation"]["status"] == "REQUIRES_REVIEW"
    assert clean["status"] == "FINAL"
    if blocking:
        assert first["reason"] == issue and first["products"] == []
        assert result["finals"] == 1 and not result["complete"]
    else:
        assert (
            first["status"] == "FINAL" and result["complete"] and result["finals"] == 2
        )


@pytest.mark.parametrize("empty_slate", [False, True])
def test_pinned_blocked_coverage_never_reports_complete(tmp_path, empty_slate):
    path = tmp_path / "capture"
    card, market = setup_assessment(path)
    repin_coverage(
        path, {"date": "20200101", "status": "BLOCKED", "reason": "source unavailable"}
    )
    if empty_slate:
        card.update(forecasts=[], forecast_count=0, scheduled=0)
        market["rows"] = []
    result = run(path, card, market)
    assert result["reconciliation"]["status"] == "BLOCKED"
    assert result["finals"] == 0 and not result["complete"]
    assert all(
        result[k] is None
        for k in ("graded_margin_mae", "graded_total_mae", "graded_winner_brier")
    )
    for r in result["rows"]:
        assert r["status"] == "RECONCILIATION_REQUIRED"
        assert (
            r["reason"] == "COVERAGE_BLOCKED:source unavailable" and not r["products"]
        )


def test_missing_and_wrong_date_coverage_are_refused(tmp_path):
    path = tmp_path / "capture"
    card, market = setup_assessment(path)
    covpath = path / "coverage.json"
    coverage = json.loads(covpath.read_bytes())
    repin_coverage(path, {**coverage, "date": "20200102"})
    with pytest.raises(ValueError, match="COVERAGE_DATE_MISMATCH"):
        run(path, card, market)
    covpath.unlink()
    with pytest.raises(FileNotFoundError):
        run(path, card, market)


@pytest.mark.parametrize(
    "options",
    [
        {"ncaa_score": 81},
        {"espn_final": False},
        {"ncaa_final": False},
        {"ncaa_sides_swapped": True},
        {"summary_score": 81},
        {"summary_final": False},
        {"ncaa_final": False, "espn_final": False},
    ],
)
def test_disputed_event_excluded_without_suppressing_clean_event(tmp_path, options):
    path = tmp_path / "capture"
    card, market = setup_assessment(path, **options)
    result = run(path, card, market)
    disputed, clean = result["rows"]
    assert result["finals"] == 1 and not result["complete"]
    assert (
        disputed["status"] == "FINAL_RECONCILIATION_REQUIRED"
        and disputed["products"] == []
    )
    assert not set(disputed) & {
        "margin_error",
        "total_error",
        "home_win_brier",
        "home_score",
        "away_score",
    }
    assert clean["status"] == "FINAL" and clean["products"][0]["result"] == "push"
    assert clean["products"][0]["conditional_brier"] is None
    assert result["graded_margin_mae"] == 2 and result["graded_total_mae"] == 16
    assert result["graded_winner_brier"] == pytest.approx(0.09)
    assert (
        result["coverage_sha256"] == digest(path / "coverage.json")
        and result["frozen_market_sha256"] == MARKET_PIN
    )
    assert clean["reconciliation"]["ncaa_contest_id"] == 18


def test_matching_pending_sources_are_ungraded(tmp_path):
    path = tmp_path / "capture"
    card, market = setup_assessment(
        path, espn_final=False, ncaa_final=False, summary_final=False
    )
    assert run(path, card, market)["rows"][0]["status"] == "PENDING"


def test_coverage_and_source_tampering(tmp_path):
    path = tmp_path / "capture"
    card, market = setup_assessment(path)
    assert run(path, card, market)["complete"]
    manpath = path / "manifest.json"
    covpath = path / "coverage.json"
    manifest = json.loads(manpath.read_bytes())
    coverage = json.loads(covpath.read_bytes())
    with pytest.raises(ValueError, match="SHA-256"):
        grade(card, market, path, PARENT_PIN, "0" * 64, market_sha=MARKET_PIN)
    coverage["events"][0]["home_score"] = 81
    covpath.write_text(json.dumps(coverage))
    with pytest.raises(ValueError, match="SHA-256"):
        run(path, card, market)
    # A rehashed summary assertion still must replay from its named scoreboards.
    manifest["coverage_sha256"] = digest(covpath)
    manpath.write_text(json.dumps(manifest))
    assert run(path, card, market)["finals"] == 1
    manifest.pop("coverage_sha256")
    manpath.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="SHA-256"):
        run(path, card, market)


def test_bound_source_and_forecast_identity(tmp_path):
    path = tmp_path / "capture"
    card, market = setup_assessment(path)
    card["forecasts"][0]["model_input_snapshot"]["neutral"] = True
    assert run(path, card, market)["finals"] == 1
    card["forecast_count"] = 1
    with pytest.raises(ValueError, match="forecast count"):
        run(path, card, market)
    card["forecast_count"] = 2
    official = next(
        r
        for r in json.loads((path / "manifest.json").read_bytes())["sources"]
        if r["url"] == ncaa_url(DAY)
    )
    (path / official["file"]).write_text("{}")
    assert run(path, card, market)["finals"] == 0


def test_correction_appends_and_links_frozen_inputs(tmp_path):
    first = tmp_path / "first"
    later = tmp_path / "later"
    card, market = setup_assessment(first, ncaa_score=81)
    setup_assessment(later)
    parent_path = tmp_path / "parent.json"
    market_path = tmp_path / "market.json"
    parent_path.write_text(json.dumps(card))
    market["frozen_parent_sha256"] = digest(parent_path)
    market_path.write_text(json.dumps(market))
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "scripts/cbb_market_and_grades.py"),
        "grade",
        "--card",
        str(parent_path),
        "--card-sha",
        digest(parent_path),
        "--market",
        str(market_path),
        "--market-sha",
        digest(market_path),
    ]

    def issue(capture, output, *args):
        return subprocess.run(
            cmd
            + [
                "--inputs",
                str(capture),
                "--manifest-sha",
                digest(capture / "manifest.json"),
                "--output",
                str(output),
                *args,
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    orig = tmp_path / "grade-01.json"
    fixed = tmp_path / "grade-02.json"
    assert issue(first, orig).returncode == 2
    orig_sha = digest(orig)
    prev = ["--previous-grade", str(orig), "--previous-grade-sha", orig_sha]
    assert issue(later, orig, *prev).returncode != 0
    assert issue(later, fixed, *prev).returncode == 0
    rec = json.loads(fixed.read_bytes())
    assert rec["previous_grade_sha256"] == orig_sha == digest(orig)
    assert rec["previous_market_binding"] == "VERIFIED"
    assert (
        rec["complete"]
        and rec["finals"] == 2
        and rec["frozen_market_sha256"] == digest(market_path)
    )
    assert (
        issue(later, tmp_path / "should-not-exist", *prev[:-1], "0" * 64).returncode
        != 0
    )
    assert not (tmp_path / "should-not-exist").exists()
