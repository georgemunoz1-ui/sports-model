"""Synthetic quote-scope regressions; never live prices or forecast evidence."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.capture_cbb_daily import ESPN, normalize, quote
from scripts.cbb_market_and_grades import attach, market_rows


def offer(line=-2, price="-110"):
    return {
        "provider": {"name": "DraftKings"},
        "moneyline": {
            "home": {"close": {"odds": "-150"}},
            "away": {"close": {"odds": "+130"}},
        },
        "pointSpread": {
            "home": {"close": {"line": str(line), "odds": price}},
            "away": {"close": {"line": str(-line), "odds": "-110"}},
        },
        "total": {
            "over": {"close": {"line": "o150", "odds": "-110"}},
            "under": {"close": {"line": "u150", "odds": "-110"}},
        },
    }


def synthetic_assessment(tmp_path, offers):
    now = datetime.now(timezone.utc)
    start = (now + timedelta(days=1)).isoformat()
    retrieved = (now - timedelta(minutes=3)).isoformat()
    forecasts, records, summaries = [], [], []
    rawdir = tmp_path / "raw"
    rawdir.mkdir()
    for eid, books in (("7", offers), ("8", [offer()])):
        teams = [
            {
                "id": team,
                "homeAway": side,
                "team": {"id": team, "displayName": "Synthetic " + team},
            }
            for side, team in (("home", "1"), ("away", "2"))
        ]
        competition = {
            "id": eid,
            "date": start,
            "competitors": teams,
            "neutralSite": False,
            "status": {
                "type": {
                    "name": "STATUS_SCHEDULED",
                    "state": "pre",
                    "completed": False,
                }
            },
        }
        event = {
            "id": eid,
            "date": start,
            "season": {"type": 2},
            "competitions": [competition],
        }
        summary = {"header": event, "pickcenter": books}
        summaries.append(summary)
        encoded = json.dumps(summary).encode()
        sha = hashlib.sha256(encoded).hexdigest()
        (rawdir / (sha + ".json")).write_bytes(encoded)
        records.append(
            {
                "url": ESPN + "summary?event=" + eid,
                "file": "raw/" + sha + ".json",
                "sha256": sha,
                "retrieved_at_utc": retrieved,
            }
        )
        forecasts.append(
            {
                "event_id": "CBB:" + eid,
                "forecast_status": "FORECAST_GENERATED",
                "start_time_utc": start,
                "settlement": "FULL_GAME_INCLUDING_OVERTIME",
                "model_input_snapshot": {"h": "1", "a": "2", "neutral": False},
                "p_home_win": 0.8,
                "distributions": {
                    "margin": {"support": [-5, 5, 10], "masses": [0.2, 0.5, 0.3]},
                    "total": {"support": [140, 150, 160], "masses": [0.2, 0.5, 0.3]},
                },
            }
        )
    (tmp_path / "manifest.json").write_text(json.dumps({"sources": records}))
    card = {
        "schema": "sports.cbb.shadow_card.v1",
        "league": "CBB",
        "market_input": False,
        "action_authority": False,
        "scheduled": 2,
        "forecast_count": 2,
        "date": now.date().isoformat(),
        "as_of_utc": (now - timedelta(minutes=2)).isoformat(),
        "generated_at_utc": (now - timedelta(minutes=1)).isoformat(),
        "forecasts": forecasts,
    }
    return card, summaries, records


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("kind", ["line", "price", "identical"])
def test_duplicate_book_refused_by_both_paths(tmp_path, kind, reverse):
    first = offer()
    second = offer(-8) if kind == "line" else offer(price="-120")
    if kind == "identical":
        second = deepcopy(first)
    offers = [first, second]
    if reverse:
        offers.reverse()
    card, summaries, receipts = synthetic_assessment(tmp_path, offers)
    raw = summaries[0]
    row = normalize(raw["header"], {"1", "2"})
    with pytest.raises(ValueError, match="AMBIGUOUS_BOOK"):
        quote(row, raw, receipts[0])
    with pytest.raises(ValueError, match="AMBIGUOUS_BOOK"):
        market_rows(raw, card["forecasts"][0])
    result = attach(card, tmp_path, "a" * 64)
    rejected, accepted = result["rows"]
    assert rejected["status"] == "QUOTE_UNAVAILABLE"
    assert rejected["detail"] == "AMBIGUOUS_BOOK"
    assert rejected["contracts"] == []
    assert accepted["status"] == "DIAGNOSTIC_RETRIEVAL_TIME_ONLY"
    assert len(accepted["contracts"]) == 6


@pytest.mark.parametrize(
    "missing",
    [
        ("provider",),
        ("provider", "name"),
        ("pointSpread", "away"),
        ("pointSpread", "away", "close"),
        ("pointSpread", "away", "close", "line"),
        ("pointSpread", "away", "close", "odds"),
    ],
)
def test_missing_scope_rejects_entire_attachment(tmp_path, missing):
    incomplete = offer()
    value = incomplete
    for key in missing[:-1]:
        value = value[key]
    del value[missing[-1]]
    card, summaries, receipts = synthetic_assessment(tmp_path, [incomplete])
    raw = summaries[0]
    with pytest.raises(ValueError, match="QUOTE_SCOPE_MISSING"):
        quote(normalize(raw["header"], {"1", "2"}), raw, receipts[0])
    with pytest.raises(ValueError, match="QUOTE_SCOPE_MISSING"):
        market_rows(raw, card["forecasts"][0])
    result = attach(card, tmp_path, "a" * 64)
    # Even the valid moneyline preceding the incomplete spread must not escape.
    assert result["rows"][0]["status"] == "QUOTE_UNAVAILABLE"
    assert result["rows"][0]["contracts"] == []
    assert len(result["rows"][1]["contracts"]) == 6


@pytest.mark.parametrize("unavailable", ["OFF", None])
def test_absent_products_and_explicit_unavailable_prices_remain_unquoted(
    tmp_path, unavailable
):
    partial = offer()
    del partial["pointSpread"]
    partial["moneyline"]["home"]["close"]["odds"] = unavailable
    card, summaries, receipts = synthetic_assessment(tmp_path, [partial])
    raw = summaries[0]
    captured = quote(normalize(raw["header"], {"1", "2"}), raw, receipts[0])
    attached = attach(card, tmp_path, "a" * 64)["rows"][0]
    assert captured["home_spread"] is captured["home_ml_price"] is None
    assert captured["total"] == 150
    assert {r["product"] for r in attached["contracts"]} == {"total"}


@pytest.mark.parametrize("malformed", [{}, [], True, False, "", -110.5, "not-a-price"])
def test_malformed_price_refuses_all_event_contracts(tmp_path, malformed):
    invalid = offer()
    invalid["pointSpread"]["home"]["close"]["odds"] = malformed
    card, summaries, receipts = synthetic_assessment(tmp_path, [invalid])
    raw = summaries[0]
    with pytest.raises(ValueError, match="INVALID_QUOTE_PRICE"):
        quote(normalize(raw["header"], {"1", "2"}), raw, receipts[0])
    with pytest.raises(ValueError, match="INVALID_QUOTE_PRICE"):
        market_rows(raw, card["forecasts"][0])
    result = attach(card, tmp_path, "a" * 64)
    assert result["rows"][0]["status"] == "QUOTE_UNAVAILABLE"
    assert result["rows"][0]["detail"] == "INVALID_QUOTE_PRICE"
    assert result["rows"][0]["contracts"] == []
    assert len(result["rows"][1]["contracts"]) == 6


def test_cli_freezes_no_partial_contracts_and_preserves_originals(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    card, _, _ = synthetic_assessment(inputs, [offer(-2), offer(-8)])
    cardpath = tmp_path / "card.json"
    cardpath.write_text(json.dumps(card))
    originals = {
        path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    }
    parent_sha = hashlib.sha256(originals[cardpath]).hexdigest()
    output = tmp_path / "market-new.json"
    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "scripts/cbb_market_and_grades.py"),
        "attach",
        "--card", str(cardpath),
        "--card-sha", parent_sha,
        "--inputs", str(inputs),
        "--output", str(output),
    ]
    issued = subprocess.run(command, capture_output=True, text=True, check=False)
    assert issued.returncode == 0, issued.stderr
    frozen = output.read_bytes()
    attachment = json.loads(frozen)
    assert attachment["frozen_parent_sha256"] == parent_sha
    assert attachment["action_authority"] is False
    assert attachment["rows"][0]["contracts"] == []
    assert attachment["rows"][0]["status"] == "QUOTE_UNAVAILABLE"
    assert len(attachment["rows"][1]["contracts"]) == 6
    retry = subprocess.run(command, capture_output=True, text=True, check=False)
    assert retry.returncode != 0 and output.read_bytes() == frozen
    assert all(path.read_bytes() == before for path, before in originals.items())
