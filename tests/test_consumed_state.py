import copy
from datetime import timedelta
import json

import pytest
from research import consumed_state as gate
from sports.rosters import digest, utc


def sample():
    t = "2030-01-03T15:00:00Z"
    start = "2030-01-03T21:00:00Z"
    event = {"event_id": "g1", "away_team": "A", "home_team": "H", "start_time_utc": start, "model_id": "test"}
    teams = {"A": ["p1"], "H": ["p2"]}
    schedule = {"id":"g1", "known_at":t, "start_utc":start, "status":"SCHEDULED", "teams":["A","H"]}
    records = {c: [schedule] if c == "schedule" else [] for c in gate.CHANNELS}
    trace = {c: {"read_at":t, "events":copy.deepcopy(v)} for c, v in records.items()}
    snap = {"consumed_channels":trace, "consumed_starters":teams,
            "consumed_fixture":{**event, "league":"CBB", "cutoff_utc":t, "start_utc":start}}
    del snap["consumed_fixture"]["start_time_utc"]
    card = {"league":"CBB", "as_of_utc":t, "forecasts":[{**event, "input_snapshot_hash":digest(snap),
            "model_input_snapshot":snap,"model_p":0.55}]}
    census = {c: {"league":"CBB","scope":"g1","channel":c,"captured_at":t,"complete_through":t,
                  "complete":True,"population":"LEAGUE_SEASON_TO_DATE","events":v} for c,v in records.items()}
    census["rosters"]["confirmed_starters"] = copy.deepcopy(teams)
    return card, {("CBB","g1"):census}, utc(t)


def test_bound_freeze_and_rechecks():
    card, inv, now = sample()
    run = lambda: gate.evaluate(card, inv, (), now, 60)[0]
    assert run()["reasons"] == []
    feeds = inv["CBB","g1"]
    feeds["rosters"]["events"].append({"id":"move","kind":"TRADE","player_id":"p1","known_at":now.isoformat(),"teams":["A","B"]})
    assert "PERSONNEL_REFREEZE_REQUIRED" in run()["reasons"]
    assert run()["consumed_state"]["rosters"]["unconsumed_by_team"] == {"A":["move"], "H":[]}
    feeds["rosters"]["confirmed_starters"]["H"] = ["p3"]
    assert "STARTER_MISMATCH_OR_UNCONFIRMED" in run()["reasons"]
    feeds["results"]["events"].append({"id":"prior","known_at":now.isoformat(),"teams":["H","B"]})
    assert run()["consumed_state"]["results"]["unconsumed_count"] == 1
    feeds["schedule"]["events"][0]["status"] = "POSTPONED"
    assert "SCHEDULE_RECONCILIATION_REQUIRED" in run()["reasons"]


def test_scheduled_versus_completed():
    card, inv, now = sample()
    feeds = inv["CBB","g1"]
    feeds["schedule"]["events"].append({"id":"tonight","known_at":now.isoformat(),"status":"SCHEDULED",
                                        "start_utc":(now+timedelta(hours=1)).isoformat()})
    row = gate.evaluate(card, inv, (), now, 60)[0]
    assert row["consumed_state"]["results"]["unconsumed_count"] == 0
    assert "INTERVENING_FIXTURE_RECHECK_REQUIRED" in row["reasons"]
    assert "CENSUS_FRESHNESS_UNVERIFIED_RESULTS" in gate.evaluate(card, inv, (), now+timedelta(seconds=61), 60)[0]["reasons"]


def test_missing_future_tampered_and_duplicate():
    card, inv, now = sample()
    del inv["CBB","g1"]["quotes"]
    assert "WATERMARK_UNVERIFIED_QUOTES" in gate.evaluate(card, inv, (), now, 60)[0]["reasons"]
    card["forecasts"][0]["input_snapshot_hash"] = "x"
    assert all("error" in v for v in gate.evaluate(card, inv, (), now, 60)[0]["consumed_state"].values())
    card["forecasts"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        gate.evaluate(card, inv, (), now, 60)


def test_cli_refusal_immutable(tmp_path):
    parent = tmp_path / "parent.json"
    parent.write_text(json.dumps(sample()[0]))
    out = tmp_path / "freeze.json"
    assert gate.main(["freeze", str(parent), str(out)]) == 2
    assert not out.exists()
    receipt = json.loads((tmp_path/"freeze.json.refusal.json").read_text())
    assert receipt["parent_file_sha256"] == gate.file_hash(parent.read_bytes())
    with pytest.raises(FileExistsError):
        gate.main(["freeze", str(parent), str(out)])


def test_journal_initial_conflict_and_successor(tmp_path, monkeypatch):
    card, inv, clock = sample()
    class Clock:
        @staticmethod
        def now(tz):
            return clock
    monkeypatch.setattr(gate, "datetime", Clock)
    parent, manifest, journal = (tmp_path / n for n in ("parent", "manifest", "journal"))
    def write_inputs():
        parent.write_text(json.dumps(card))
        refs = {}
        for c, v in inv["CBB","g1"].items():
            p = tmp_path / c
            p.write_text(json.dumps(v))
            refs[c] = {"path":c, "sha256":gate.file_hash(p.read_bytes())}
        manifest.write_text(json.dumps({"schema":"sports.fixture_channel_census.v1","fixtures":[
            {"league":"CBB","event_id":"g1","channels":refs}]}))
    def freeze(name):
        return gate.run("freeze", parent, tmp_path/name, manifest, max_age=60, journal=journal)
    write_inputs()
    assert freeze("first") == 0
    original = (tmp_path/"first").read_bytes()
    assert freeze("duplicate") == 2
    feeds = inv["CBB","g1"]
    clock += timedelta(minutes=1)
    move = {"id":"qb1","teams":["A"], "kind":"STARTER_CHANGE","player_id":"new_p1","known_at":clock.isoformat()}
    feeds["rosters"]["events"].append(move)
    for feed in feeds.values():
        feed["captured_at"] = feed["complete_through"] = clock.isoformat()
    write_inputs()
    assert gate.run("recheck", parent, tmp_path/"late", manifest, max_age=60, journal=journal) == 2
    assert json.loads((tmp_path/"late").read_bytes())["fixtures"][0]["invalidates_freeze_sha256"] == gate.file_hash(original)
    clock += timedelta(seconds=1)
    for feed in feeds.values():
        feed["captured_at"] = feed["complete_through"] = clock.isoformat()
    snapshot = card["forecasts"][0]["model_input_snapshot"]
    card["as_of_utc"] = snapshot["consumed_fixture"]["cutoff_utc"] = clock.isoformat()
    feeds["rosters"]["confirmed_starters"]["A"] = ["new_p1"]
    snapshot["consumed_starters"]["A"] = ["new_p1"]
    snapshot["consumed_channels"]["rosters"] = {"read_at":clock.isoformat(), "events":[move]}
    card["forecasts"][0]["input_snapshot_hash"] = digest(snapshot)
    write_inputs()
    assert freeze("replacement") == 0
    record = json.loads((tmp_path/"replacement").read_bytes())
    assert record["kind"] == "SHADOW_REFREEZE"
    assert record["fixtures"][0]["prior_freeze_sha256"] == gate.file_hash(original)
    assert original == (tmp_path/"first").read_bytes()
