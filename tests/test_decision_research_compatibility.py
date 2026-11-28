"""Synthetic evidence fixtures; never an authenticated sports/venue dataset."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from models.common.decision_research.compatibility import assess, decode
from models.common.decision_research.repository import SQLiteRepository

ROOT = Path(__file__).resolve().parents[1]


def make_fixture(root, now=None, league="CFB"):
    now = datetime.now(timezone.utc) if now is None else now
    ts = lambda seconds: (now + timedelta(seconds=seconds)).isoformat()
    objects = {
        "contract": {"contract_id": "synthetic-contract", "event_id": "synthetic-event", "league": league,
                     "selection_team_id": "synthetic-team", "period": "FULL_GAME", "rules_id": "rules-v1",
                     "currency": "USD", "market_type": "SPREAD", "line": "-6.5", "payout_unit": "1"},
        "quote": {"quote_id": "synthetic-quote", "contract_id": "synthetic-contract", "state_id": "state-v1",
                  "venue": "SYNTHETIC", "fee_schedule_id": "fees-v1", "buy_price": "0.52", "available_quantity": 100,
                  "observed_at_utc": ts(-10), "retrieved_at_utc": ts(-5), "market_open": True},
        "state": {"state_id": "state-v1", "event_id": "synthetic-event", "phase": "PRE_GAME",
                  "league": league, "home_team_id": "synthetic-team", "away_team_id": "other-team",
                  "observed_at_utc": ts(-40), "scheduled_start_utc": ts(3600)},
        "model": {"model_id": "synthetic-model", "forecast_id": "synthetic-forecast", "contract_id": "synthetic-contract",
                  "event_id": "synthetic-event", "state_id": "state-v1", "expected_payout": "0.56",
                  "created_at_utc": ts(-20), "cutoff_utc": ts(-30)},
        "rules": {"rules_id": "rules-v1", "period": "FULL_GAME", "currency": "USD", "venue": "SYNTHETIC",
                  "payoff_function_id": "binary_half_spread.v1", "payout_unit": "1"},
        "fee_schedule": {"schedule_id": "fees-v1", "venue": "SYNTHETIC", "currency": "USD", "rate": "0.07",
                         "minimum": "0", "rounding_increment": "0.01", "effective_at_utc": ts(-1000), "expires_at_utc": ts(1000)},
        "configuration": {"configuration_id": "synthetic-config", "max_quote_age_seconds": 60,
                          "max_state_age_seconds": 60, "required_ev_buffer": "0.01"},
    }
    return write_fixture(root, objects), objects, now


def write_fixture(root, objects):
    root.mkdir(parents=True, exist_ok=True)
    request = {"comparison_id": "SYNTHETIC-001", "quantity": 100, "evidence": {}}
    for kind, value in objects.items():
        p = root / (kind + ".json")
        raw = json.dumps(value, sort_keys=True).encode()
        p.write_bytes(raw)
        request["evidence"][kind] = {"path": p.name, "sha256": sha256(raw).hexdigest()}
    return request


@pytest.mark.parametrize("league", ["NFL", "CFB", "NBA", "WNBA", "MLB", "NHL", "MLS"])
def test_evidence_integrity_never_grants_qualification(tmp_path, league):
    request, _, now = make_fixture(tmp_path, league=league)
    result = assess(request, tmp_path, now=now)
    assert all(result["compatibility"].values())
    assert result["decision"]["conservative_net_ev"] == "0.0225"
    assert result["disposition"] == "BLOCKED"
    assert result["candidate"] is None
    assert result["order_authorized"] is False
    assert "VENUE_RULES_AUTHORITY_NOT_CONFIGURED" in result["findings"]


@pytest.mark.parametrize("kind,key,value,check", [
    ("quote", "contract_id", "other", "identity"),
    ("rules", "period", "FIRST_HALF", "identity"),
    ("fee_schedule", "currency", "CAD", "identity"),
    ("model", "event_id", "other", "identity"),
    ("contract", "selection_team_id", "nonparticipant", "identity"),
    ("state", "league", "OTHER", "identity"),
    ("state", "phase", "LIVE", "state_alignment"),
    ("model", "state_id", "old", "state_alignment"),
    ("contract", "line", "-6", "binary_contract"),
    ("contract", "line", "6.25", "binary_contract"),
    ("contract", "payout_unit", "2", "binary_contract"),
    ("contract", "market_type", "SPORTSBOOK_SPREAD", "binary_contract"),
])
def test_bound_semantic_mismatch(tmp_path, kind, key, value, check):
    _, objects, now = make_fixture(tmp_path)
    objects[kind][key] = value
    result = assess(write_fixture(tmp_path, objects), tmp_path, now=now)
    assert result["compatibility"][check] is False
    assert result["disposition"] == "BLOCKED"


@pytest.mark.parametrize("kind,key,seconds", [
    ("quote", "observed_at_utc", 10), ("quote", "retrieved_at_utc", 10),
    ("model", "created_at_utc", 10), ("model", "cutoff_utc", 10),
    ("state", "scheduled_start_utc", -1), ("state", "observed_at_utc", -500),
    ("quote", "observed_at_utc", -500),
])
def test_chronology_and_freshness(tmp_path, kind, key, seconds):
    _, objects, now = make_fixture(tmp_path)
    objects[kind][key] = (now + timedelta(seconds=seconds)).isoformat()
    result = assess(write_fixture(tmp_path, objects), tmp_path, now=now)
    assert result["compatibility"]["chronology_and_freshness"] is False


def test_hash_mismatch(tmp_path):
    request, _, now = make_fixture(tmp_path)
    (tmp_path / "model.json").write_text('{}')
    result = assess(request, tmp_path, now=now)
    assert "hash mismatch" in result["findings"][0]


def test_path_escape(tmp_path):
    root = tmp_path / "root"
    request, _, now = make_fixture(root)
    outside = tmp_path / "outside.json"
    outside.write_text('{}')
    request["evidence"]["contract"] = {"path": "../outside.json", "sha256": sha256(b'{}').hexdigest()}
    result = assess(request, root, now=now)
    assert "outside root" in result["findings"][0]


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":0.5}'])
def test_strict_json(raw):
    with pytest.raises(ValueError): decode(raw)


def test_caller_cannot_override_gates(tmp_path):
    request, _, now = make_fixture(tmp_path)
    request["valuation_qualified"] = True
    result = assess(request, tmp_path, now=now)
    assert result["disposition"] == "BLOCKED"
    assert "no caller gates" in result["findings"][0]


def test_expired_fee_window_visible(tmp_path):
    _, objects, now = make_fixture(tmp_path)
    objects["fee_schedule"]["expires_at_utc"] = now.isoformat()
    result = assess(write_fixture(tmp_path, objects), tmp_path, now=now)
    assert "FEE_SCHEDULE_OUTSIDE_EFFECTIVE_WINDOW" in result["findings"]


def test_cli_real_sqlite_receipt_and_no_overwrite(tmp_path):
    evidence = tmp_path / "evidence"
    request, _, _ = make_fixture(evidence)
    source = tmp_path / "request.json"
    source.write_text(json.dumps(request))
    out = tmp_path / "run"
    command = [sys.executable, str(ROOT / 'scripts/run_contract_decision_research.py'), '--request', str(source),
               '--evidence-root', str(evidence), '--output', str(out)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 2, result.stderr
    saved = json.loads((out / 'decision.json').read_text())
    assert saved['decision']['disposition'] == 'BLOCKED'
    assert saved['audit_checkpoint']['count'] == 1
    assert saved['observed_checkout']
    manifest = json.loads((out / 'manifest.json').read_text())
    for path, digest in manifest.items():
        assert sha256((out / path).read_bytes()).hexdigest() == digest
    before = (out / 'decision.json').read_bytes()
    repeat = subprocess.run(command, capture_output=True, text=True)
    assert repeat.returncode != 0
    assert (out / 'decision.json').read_bytes() == before
    conn = sqlite3.connect(out / 'research.sqlite')
    try:
        repo = SQLiteRepository(conn)
        assert repo.verify_audit(expected_head=saved['audit_checkpoint']['head'], expected_count=1)
    finally:
        conn.close()
