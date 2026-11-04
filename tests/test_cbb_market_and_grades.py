from scripts.cbb_market_and_grades import market_rows, probability, parse_price
import pytest


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


def test_grade_uses_original_side_and_keeps_pushes(tmp_path):
    import hashlib
    import json
    from scripts.cbb_market_and_grades import grade

    stem = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event=7"
    row = {
        "event_id": "CBB:7",
        "forecast_status": "FORECAST_GENERATED",
        "start_time_utc": "2020-01-02T00:00Z",
        "home_margin": 6.0,
        "total": 140.0,
        "p_home_win": 0.7,
        "model_input_snapshot": {"h": "1", "a": "2"},
    }
    parent = {
        "date": "2020-01-01",
        "as_of_utc": "2020-01-01T18:00Z",
        "generated_at_utc": "2020-01-01T18:01Z",
        "forecasts": [row],
        "forecast_count": 1,
    }
    market = {
        "schema": "sports.cbb.market.shadow.v1",
        "date": parent["date"],
        "frozen_parent_sha256": "pin",
        "action_authority": False,
        "created_at_utc": "2020-01-01T18:02Z",
        "rows": [
            {
                "event_id": "CBB:7",
                "quote_retrieved_at_utc": "2020-01-01T17:59Z",
                "contracts": [
                    {
                        "product": "margin",
                        "side": "away",
                        "line": 4.0,
                        "win": 0.60,
                        "push": 0.02,
                    },
                    {
                        "product": "margin",
                        "side": "home",
                        "line": -4.0,
                        "win": 0.38,
                        "push": 0.02,
                    },
                ],
            }
        ],
    }
    final = {
        "header": {
            "id": "7",
            "competitions": [
                {
                    "id": "7",
                    "date": row["start_time_utc"],
                    "status": {"type": {"completed": True, "name": "STATUS_FINAL"}},
                    "competitors": [
                        {"homeAway": "home", "id": "1", "score": "80"},
                        {"homeAway": "away", "id": "2", "score": "76"},
                    ],
                }
            ],
        }
    }
    raw = json.dumps(final).encode()
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw/7.json").write_bytes(raw)
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "url": stem,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "file": "raw/7.json",
                        "retrieved_at_utc": "2020-01-02T03:00Z",
                    }
                ]
            }
        )
    )
    r = grade(parent, market, tmp_path, "pin")
    assert (
        r["complete"]
        and r["graded_margin_mae"] == 2
        and r["rows"][0]["products"][0]["result"] == "push"
    )
    assert r["rows"][0]["products"][0]["conditional_brier"] is None
    row["model_input_snapshot"]["h"] = "3"
    assert grade(parent, market, tmp_path, "pin")["finals"] == 0
