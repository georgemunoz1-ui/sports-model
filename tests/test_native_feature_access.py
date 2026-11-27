"""Native-constructor regression tests; synthetic basketball/CFB are not sports evidence."""
import copy
import json
from pathlib import Path

import pytest

from models.experiments import nba_efficiency as nba, cfb_efficiency as cfb
from research import native_feature_access as access
from research.efficiency import runner
from scripts.source_attestation import sha256
from test_nba_possession_efficiency import games
from test_cfb_efficiency_experiment import history

DATA = Path(__file__).resolve().parents[1] / "data/nfl/contextual_v1"


def replay(tmp_path, league, doc, event):
    p = tmp_path / (league + ".json")
    p.write_text(json.dumps(doc))
    return access.replay_efficiency_access(league, p, sha256(p.read_bytes()), event)


def test_native_nfl_common_view():
    paths = [DATA / p for p in ("event_package_v2.json", "model_packed.json", "recovered_parameters.json")]
    args = [v for p in paths for v in (p, sha256(p.read_bytes()))]
    r = access.replay_nfl_access(*args, "2026_01_DEN_KC", "2026-09-14T12:00:00Z")
    assert len(r["fields"]) == 100
    assert len(access.diagnostic_values(r)) <= 100
    assert sum(f["native_arm_usage"]["qb"]["matrix_member"] for f in r["fields"]) == 23
    assert all(not f["verified_pit_eligible"] for f in r["fields"])
    with pytest.raises(ValueError, match="PIT_ADMISSION_NOT_IMPLEMENTED"):
        access.verified_pit_values(r)
    assert r["event"]["home_id"] == "KC" and not r["action_authority"]


def test_nba_native_features_visible_without_personnel(tmp_path):
    doc = {"history": games(12)}
    native = nba.prepare_examples(doc["history"])[-1]
    r = replay(tmp_path, "nba", doc, native["event_id"])
    assert len(r["fields"]) == len(nba.FEATURE_NAMES) + len(nba.PERSONNEL_FEATURES)
    assert access.diagnostic_values(r) == native["features"]
    assert all(f["value"] is None for f in r["fields"] if f["family"] == "PERSONNEL")
    assert "targets" not in r and "actual_total" not in r
    assert r["dependency_groups"]["history"]["sources"][0]["timing"] == "LATER_RECONSTRUCTION"
    assert not r["training_ready"]


def test_nba_personnel_native_gate_does_not_remove_base(tmp_path):
    doc = {"history": games(12)}
    event = doc["history"][-1]
    event["personnel"] = {"home_impact_per100": 1.5, "away_impact_per100": -.5,
                          "available_at_utc": "2030-01-01T00:00:00Z", "sources": event["sources"]}
    r = replay(tmp_path, "nba", doc, event["event_id"])
    assert len(access.diagnostic_values(r)) == len(nba.FEATURE_NAMES)
    assert "NBA_PERSONNEL_INPUT_AFTER_CUTOFF" in r["native_gate_reasons"]
    event["personnel"]["available_at_utc"] = "2020-01-01T00:00:00Z"
    r = replay(tmp_path, "nba", doc, event["event_id"])
    assert access.diagnostic_values(r)["home_personnel_impact_per100"] == 1.5
    assert not r["field_level_pit_verified"]


def test_cfb_native_features_and_personnel_missing(tmp_path):
    doc = history()
    native = cfb.prepare_examples(doc)[-1]
    r = replay(tmp_path, "cfb", doc, native["event_id"])
    assert len(r["fields"]) == len(cfb.FEATURES) + len(cfb.PERSONNEL_FEATURES)
    assert access.diagnostic_values(r) == native["features"]
    assert not r["training_ready"]
    assert all(f["value"] is None for f in r["fields"] if f["family"] == "PERSONNEL")
    assert r["bindings"]["native_state_sha256"] == native["component_state_sha256"]


def test_target_result_does_not_enter_numeric_view(tmp_path):
    doc = {"history": games(12)}
    event = doc["history"][-1]
    before = replay(tmp_path, "nba", doc, event["event_id"])
    event["home_stats"]["ftm"] += 1
    event["home_score"] += 1
    after = replay(tmp_path, "nba", doc, event["event_id"])
    assert access.diagnostic_values(before) == access.diagnostic_values(after)
    assert before["bindings"]["history_artifact_sha256"] != after["bindings"]["history_artifact_sha256"]


def test_warmup_preserved_without_guessed_features(tmp_path):
    doc = {"history": games(3)}
    r = replay(tmp_path, "nba", doc, doc["history"][0]["event_id"])
    assert access.diagnostic_values(r) == {}
    assert len(r["fields"]) == 29
    assert "HOME_INSUFFICIENT_PRIOR_GAMES" in r["native_gate_reasons"]


def test_bad_pin_and_tamper(tmp_path):
    doc = {"history": games(12)}
    r = replay(tmp_path, "nba", doc, doc["history"][-1]["event_id"])
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        access.replay_efficiency_access("nba", tmp_path / "nba.json", "0"*64, doc["history"][-1]["event_id"])
    r["fields"][0]["value"] = 999
    with pytest.raises(ValueError, match="DIGEST_MISMATCH"):
        access.diagnostic_values(r)


def test_rehash_cannot_certify_pit(tmp_path):
    doc = {"history": games(12)}
    r = replay(tmp_path, "nba", doc, doc["history"][-1]["event_id"])
    for f in r["fields"]:
        f["verified_pit_eligible"] = True
    r["training_ready"] = True
    r["snapshot_sha256"] = runner.digest({k:v for k,v in r.items() if k != "snapshot_sha256"})
    with pytest.raises(ValueError, match="PIT_ADMISSION_NOT_IMPLEMENTED"):
        access.verified_pit_values(r)


def test_exclusive_runtime_receipt(tmp_path, capsys):
    doc = {"history": games(12)}
    path = tmp_path / "archive.json"
    path.write_text(json.dumps(doc))
    out = tmp_path / "receipt.json"
    args = ["nba", "--history", str(path), "--history-sha", sha256(path.read_bytes()),
            "--event-id", doc["history"][-1]["event_id"], "--output", str(out)]
    assert access.main(args) == 0
    raw = out.read_bytes()
    receipt = json.loads(raw)
    assert "NATIVE_FEATURE_ACCESS_RECEIPT_SHA256=" + sha256(raw) in capsys.readouterr().out
    assert receipt["diagnostic_feature_count"] == 27
    assert receipt["verified_pit_feature_count"] == 0
    assert not receipt["training_ready"] and not receipt["prospective_registration_verified"]
    with pytest.raises(FileExistsError):
        access.main(args)
    assert out.read_bytes() == raw
