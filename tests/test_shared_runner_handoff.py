import hashlib
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pipelines.cards.recipient_card import verify_recipient_card, write_recipient_card
from scripts import generate_card_force as runner

DAY = "2099-11-08"
AS_OF = "2099-11-08T12:00:00Z"


def game(event_id):
    return {"event_id": event_id, "away_team": "Visitor", "home_team": "Host",
            "slate_date": DAY, "start_time_utc": "2099-11-09T02:00:00Z"}


def setup_adapter(monkeypatch, events):
    def infer(event, context, simulations):
        if event["event_id"] == "b":
            raise ValueError("MISSING_STARTER")
        return {"model_winner": "Host", "model_id": "fixture-model", "model_p": .64,
                "sim_p": .641, "projected_margin": 3.6, "projected_total": 138, "dose": 0}
    adapter = SimpleNamespace(load_schedule=Mock(return_value=events),
                              build_context=Mock(return_value={"package_sha256":"fixture-pin"}),
                              forecast_event=Mock(side_effect=infer))
    monkeypatch.setattr(runner, "load_adapter", lambda league: adapter)
    monkeypatch.setattr("pipelines.cards.selected.apply_default", lambda league, event, raw: raw)
    monkeypatch.setattr("sports.rosters.attach", lambda raw, *args: raw)
    return adapter


def test_partial_matchups_are_visible_and_exit_nonzero(monkeypatch, tmp_path):
    out = tmp_path / "run"
    post = dict(game("p"), start_time_utc="2000-11-08T20:00:00Z")
    setup_adapter(monkeypatch, [game("a"), game("b"), post])
    monkeypatch.setattr(sys, "argv", ["generate", "--league", "cfb", "--date", DAY,
                        "--as-of-utc", "2026-11-08T08:00:00Z", "--output-dir", str(out),
                        "--identity-semantics", "legacy.v1"])
    with pytest.raises(SystemExit) as rc:
        runner.main()
    assert rc.value.code == 2
    card = json.loads((out/"diagnostic_card.json").read_text())
    assert [(r["event_id"], r["forecast_status"]) for r in card["forecasts"]] == [
        ("a", "FORECAST_GENERATED"), ("b", "BLOCKED"), ("p", "POST_START")]
    assert card["coverage_breach_event_ids"] == ["b"] and card["forecast_count"] == 1
    assert card["forecasts"][0]["model_p"] == .64
    assert card["forecasts"][1]["refusal_reason"] == "ValueError:MISSING_STARTER"
    for fmt in ["csv", "md", "html"]:
        s=(out/f"diagnostic_card.{fmt}").read_text()
        assert "MISSING_STARTER" in s and "BLOCKED" in s and "POST_START" in s
    assert verify_recipient_card(card, out/"diagnostic_card.html")["rows"] == 3


def test_breached_identity_and_context_do_not_run_inference(monkeypatch):
    events = [game("a"), game("a"), dict(game("b"), start_time_utc="bad"), game("c")]
    a = setup_adapter(monkeypatch, events)
    a.build_context.side_effect = ValueError("STALE_GAMES")
    result = runner.generate(DAY, "cfb", AS_OF, 100, None)
    assert [row["refusal_reason"] for row in result["forecasts"]] == [
        "DUPLICATE_SCHEDULE_EVENT_ID", "INVALID_EVENT_START", "ValueError:STALE_GAMES"]
    a.forecast_event.assert_not_called()


@pytest.mark.parametrize("league", ["mlb", "cfb", "wnba", "nba", "nhl", "mls"])
def test_shared_package_binds_digest_league_and_pacific_slate(league, monkeypatch, tmp_path):
    monkeypatch.delenv("SPORTS_RESEARCH_PACKAGE_DIR", raising=False)
    path = tmp_path/league/"package.json"
    path.parent.mkdir()
    package = {"league":league,"schema":"sports.current_research_package.v1","action_authority":False,
               "covered_dates":[DAY],"events":[game("a")]}
    def put():
        path.write_text(json.dumps(package))
        return hashlib.sha256(path.read_bytes()).hexdigest()
    pin = put()
    assert runner.bind_shared_package(path, pin, league, DAY) == package["events"]
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        runner.bind_shared_package(path, "0"*64, league, DAY)
    with pytest.raises(ValueError, match="DATE_NOT_ACQUIRED"):
        runner.bind_shared_package(path, pin, league, "2099-11-07")
    package["events"][0]["slate_date"] = "2099-11-09"
    with pytest.raises(ValueError, match="SLATE_DATE_MISMATCH"):
        runner.bind_shared_package(path, put(), league, DAY)


def test_loaded_context_and_slate_must_match(monkeypatch):
    events = [game("a")]
    a = setup_adapter(monkeypatch, events)
    with pytest.raises(ValueError, match="BOUND_PACKAGE_SCHEDULE_MISMATCH"):
        runner.generate(DAY, "cfb", AS_OF, 100, None, expected_schedule=[])
    card = runner.generate(DAY, "cfb", AS_OF, 100, None, expected_schedule=events, package_sha256="wrong")
    assert card["forecasts"][0]["refusal_reason"].endswith("LOADED_PACKAGE_HASH_MISMATCH")
    a.forecast_event.assert_not_called()


def test_package_refusal_preserves_reason_and_date(monkeypatch, tmp_path):
    out=tmp_path/"new"
    monkeypatch.setattr(sys, "argv", ["generate", "--league", "cfb", "--date", DAY,
                        "--event-package-sha256", "f"*64, "--output-dir", str(out)])
    with pytest.raises(SystemExit) as rc:
        runner.main()
    assert rc.value.code == 2
    receipt=json.loads((out/"runner_failure.json").read_text())
    assert receipt["status"] == "BLOCKED" and receipt["date"] == DAY
    assert "PACKAGE_AND_SHA256_REQUIRED_TOGETHER" in receipt["reason"]
    assert not (out/"diagnostic_card.json").exists()


def test_recipient_readback_rejects_blank_hidden_and_wrong_values(tmp_path):
    row=dict(game("A<&"),forecast_status="FORECAST_GENERATED",model_winner="Host",
             model_p=.701,sim_p=.704,projected_margin=-3.0,projected_total=47.5)
    card={"league":"NFL","card_date":DAY,"forecasts":[row]}
    html=tmp_path/"view.html"
    write_recipient_card(card, html)
    original=html.read_text()
    assert "&lt;&amp;" in original and verify_recipient_card(card, html)["rows"] == 1
    for bad in ["<p>1 forecast</p>", original.replace("<tbody>",'<tbody hidden="">'),
                original.replace("70.10%", "70.11%"), original.replace("Host", "Away")]:
        html.write_text(bad)
        with pytest.raises(ValueError, match="READBACK_MISMATCH"):
            verify_recipient_card(card, html)
