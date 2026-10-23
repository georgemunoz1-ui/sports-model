"""Real CLI round trips; signed fixtures are fabricated TEST_ONLY research data."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from cryptography.hazmat.primitives import serialization

from pipelines.cards.research_selection import (
    content_hash, seal_forecast, seal_quality_receipt, selector_config_artifact,
    target_id, verify_selection_record,
)
from tests.test_validation_registry import make_registry_fixture


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_research_selection.py"
AT = "2026-10-22T21:00:00Z"


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def inputs(tmp_path, *, required_quality=False):
    forecast = seal_forecast({
        "schema": "research-forecast-v1", "procedure_id": "a" * 64,
        "input_snapshot_sha256": "b" * 64,
        "target": {"event_id": "TEST_ONLY-NE-CHI", "league": "nfl", "product": "spread",
                   "period": "full_game", "side": "away", "line": 3.0,
                   "settlement_rules_id": "full-game-ot-push-refund-v1",
                   "starts_at_utc": "2026-10-22T23:00:00Z"},
        "probabilities": {"win": .6, "loss": .3, "push": .1, "void": 0.},
        "forecast_cutoff_utc": "2026-10-22T19:00:00Z",
        "forecast_created_at_utc": "2026-10-22T20:00:00Z",
    })
    config = {"schema": "research-selector-config-v1", "objective": "unconditional_win",
              "threshold": .6, "require_quality_receipt": required_quality}
    manifest = {"schema": "research-selection-manifest-v1", "entries": [
        {"entry_id": "TEST_ONLY", "forecast": "forecast.json", "config": "config.json"}]}
    write(tmp_path / "forecast.json", forecast)
    write(tmp_path / "config.json", config)
    write(tmp_path / "manifest.json", manifest)
    return forecast, config, manifest


def run(tmp_path, *, output="output", extra=(), at=AT):
    command = [sys.executable, "-B", str(SCRIPT), "--manifest", str(tmp_path / "manifest.json"),
               "--output-dir", str(tmp_path / output)]
    if at is not None:
        command += ["--decision-at-utc", at]
    return subprocess.run(command + list(extra), cwd=tmp_path, text=True, capture_output=True)


def test_no_registry_is_blocked_with_real_execution_and_source_receipts(tmp_path):
    inputs(tmp_path)
    originals = {p: p.read_bytes() for p in tmp_path.iterdir()}
    before = datetime.now(timezone.utc)
    result = run(tmp_path)
    after = datetime.now(timezone.utc)
    assert result.returncode == 0, result.stderr
    board = json.loads((tmp_path / "output/decisions.json").read_text())
    executed = datetime.fromisoformat(board["created_at_utc"].replace("Z", "+00:00"))
    assert before <= executed <= after
    assert board["execution_mode"] == "RETROSPECTIVE_DIAGNOSTIC"
    decision = board["decisions"][0]
    verify_selection_record(decision)
    assert decision["decision_class"] == "BLOCKED"
    assert decision["selection_probability"] is None
    assert decision["raw_probability"] == .6
    assert "MISSING_VALIDATION_REGISTRY" in decision["blocking_reasons"]
    assert decision["replay_at_utc"] == board["created_at_utc"]
    assert decision["decision_at_utc"] == AT
    assert board["source_manifest_sha256"] == hashlib.sha256(originals[tmp_path / "manifest.json"]).hexdigest()
    assert board["source_manifest_id"] == content_hash(json.loads(originals[tmp_path / "manifest.json"]))
    for source in board["source_receipts"]:
        assert hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest() == source["sha256"]
    receipt = json.loads((tmp_path / "output/execution_receipt.json").read_text())
    assert receipt["outputs"][0]["sha256"] == hashlib.sha256((tmp_path / "output/decisions.json").read_bytes()).hexdigest()
    assert all(p.read_bytes() == raw for p, raw in originals.items())


def test_signed_registry_round_trip_and_price_independence(tmp_path):
    forecast, config, manifest = inputs(tmp_path, required_quality=True)
    fixture = make_registry_fixture(tmp_path / "registry", config_artifact=selector_config_artifact(config))
    payload = {k: v for k, v in forecast.items() if k != "forecast_id"}
    payload["procedure_id"] = fixture["procedure_id"]
    forecast = seal_forecast(payload)
    write(tmp_path / "forecast.json", forecast)
    quality = seal_quality_receipt({"forecast_id": forecast["forecast_id"],
        "input_snapshot_sha256": forecast["input_snapshot_sha256"], "created_at_utc": AT,
        "blocking_reasons": [], "review_notes": ["TEST_ONLY fabricated fixture"]})
    write(tmp_path / "quality.json", quality)
    sibling = seal_forecast(dict(payload, probabilities={"win": .55, "loss": .35, "push": .1, "void": 0.}))
    write(tmp_path / "sibling.json", sibling)
    for filename, decimal in (("price.json", 2.), ("poor-price.json", 1.1)):
        write(tmp_path / filename, {"target_id": target_id(forecast["target"]),
                                   "decimal_odds": decimal, "quoted_at_utc": AT})
    manifest["entries"][0].update(quality_receipt="quality.json", price="price.json", components=["sibling.json"])
    manifest["entries"].append(dict(manifest["entries"][0], entry_id="TEST_ONLY-poor-price", price="poor-price.json"))
    manifest["registry"] = {"record_ids": [fixture["record_id"]], "revocation_ids": []}
    write(tmp_path / "manifest.json", manifest)
    write(tmp_path / "trust.json", {"schema": "research-validation-trust-v1", "public_keys_b64": {
        name: base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,
                                serialization.PublicFormat.Raw)).decode()
        for name, key in fixture["keys"].items()}})
    originals = {p: p.read_bytes() for p in tmp_path.rglob("*.json")}
    result = run(tmp_path, extra=("--registry-store", str(tmp_path / "registry"),
                                 "--trust-file", str(tmp_path / "trust.json")))
    assert result.returncode == 0, result.stderr
    board = json.loads((tmp_path / "output/decisions.json").read_text())
    first, second = board["decisions"]
    assert first["decision_class"] == second["decision_class"] == "SHADOW_SELECTED"
    assert first["decision_id"] == second["decision_id"]
    assert first["price_diagnostics_id"] != second["price_diagnostics_id"]
    assert first["estimated_value"] > 0 > second["estimated_value"]
    assert first["quality_receipt_id"] == quality["receipt_id"]
    assert len(first["same_target_components"]) == 1
    for decision in board["decisions"]:
        verify_selection_record(decision)
        assert decision["publication_allowed"] is False
        assert decision["action_authority"] is False
        assert decision["official_release"] is False
        assert decision["wagering_status"] == "OFF"
    assert any("registry_artifact" in x["roles"] for x in board["source_receipts"])
    assert all(p.read_bytes() == raw for p, raw in originals.items())
    assert sorted((tmp_path / "registry").iterdir()) == sorted(p for p in originals if p.parent == tmp_path / "registry")
    write(tmp_path / "trust.json", {"schema": "research-validation-trust-v1", "public_keys_b64": {}})
    result = run(tmp_path, output="untrusted", extra=("--registry-store", str(tmp_path / "registry"),
                                                     "--trust-file", str(tmp_path / "trust.json")))
    assert result.returncode == 0, result.stderr
    untrusted = json.loads((tmp_path / "untrusted/decisions.json").read_text())["decisions"][0]
    assert untrusted["decision_class"] == "BLOCKED"
    assert "UNTRUSTED_SIGNER" in untrusted["validation"]["reasons"]


def test_refuses_existing_directory_and_preserves_completed_output(tmp_path):
    inputs(tmp_path)
    assert run(tmp_path).returncode == 0
    original = (tmp_path / "output/decisions.json").read_bytes()
    result = run(tmp_path)
    assert result.returncode == 2
    assert "OUTPUT_DIRECTORY_ALREADY_EXISTS" in result.stderr
    assert (tmp_path / "output/decisions.json").read_bytes() == original
    (tmp_path / "empty").mkdir()
    assert run(tmp_path, output="empty").returncode == 2


def test_forecast_tamper_and_missing_orientation_are_not_repaired(tmp_path):
    forecast, _, _ = inputs(tmp_path)
    forecast["probabilities"]["win"] = .7
    forecast["probabilities"]["loss"] = .2
    write(tmp_path / "forecast.json", forecast)
    result = run(tmp_path)
    assert result.returncode == 2 and "FORECAST_ID_MISMATCH" in result.stderr
    assert not (tmp_path / "output").exists()
    del forecast["target"]["side"]
    write(tmp_path / "forecast.json", forecast)
    assert run(tmp_path).returncode == 2


def test_strict_json_and_registry_configuration_fail_before_output(tmp_path):
    _, _, manifest = inputs(tmp_path)
    (tmp_path / "manifest.json").write_text('{"schema":"a","schema":"b","entries":[]}')
    result = run(tmp_path)
    assert result.returncode == 2 and "DUPLICATE_JSON_KEY" in result.stderr
    write(tmp_path / "manifest.json", manifest)
    result = run(tmp_path, extra=("--registry-store", str(tmp_path)))
    assert result.returncode == 2 and "REGISTRY_REQUIRES" in result.stderr
    assert not (tmp_path / "output").exists()


def test_actual_clock_mode_and_future_cutoff_rejection(tmp_path):
    forecast, _, _ = inputs(tmp_path)
    payload = {k: v for k, v in forecast.items() if k != "forecast_id"}
    payload["target"]["starts_at_utc"] = "2099-01-01T00:00:00Z"
    write(tmp_path / "forecast.json", seal_forecast(payload))
    result = run(tmp_path, at=None)
    assert result.returncode == 0, result.stderr
    board = json.loads((tmp_path / "output/decisions.json").read_text())
    decision = board["decisions"][0]
    assert decision["execution_mode"] == "UNREGISTERED_RESEARCH"
    assert decision["decision_at_utc"] == board["created_at_utc"]
    assert decision["replay_at_utc"] is None
    assert decision["prospective_registration_verified"] is False
    result = run(tmp_path, output="future", at="2099-01-01T00:00:00Z")
    assert result.returncode == 2 and "FUTURE_DECISION_TIMESTAMP" in result.stderr


def test_help_documents_explicit_inputs_and_no_authority():
    result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--help"], text=True, capture_output=True)
    assert result.returncode == 0
    for phrase in ("research-selection-manifest-v1", "public_keys_b64", "read-only", "wagering OFF", "retrospective"):
        assert phrase in result.stdout
