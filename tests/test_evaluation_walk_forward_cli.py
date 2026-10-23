"""Synthetic signed refit-policy CLI exercise; no performance qualification."""
import base64
import hashlib
import json
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives import serialization

from pipelines.cards.research_selection import (
    content_hash, seal_forecast, select_research, selector_config_artifact, target_family,
)
from scripts.evaluate_research_selections import build_evaluation
from tests.test_procedure_lineage import make_refit_policy_fixture


def packet(root):
    f = make_refit_policy_fixture(root / "store")
    config = {"schema": "research-selector-config-v1", "objective": "unconditional_win",
              "threshold": .6, "require_quality_receipt": True}
    forecasts, decisions, states, population, outcomes = [], [], [], [], []
    for row in f["rows"]:
        target = {"event_id": row["event_id"], "league": "nba", "product": "winner", "period": "full_game",
                  "side": "home", "line": None, "settlement_rules_id": "TEST_ONLY_OT",
                  "starts_at_utc": row["starts_at_utc"]}
        forecast = seal_forecast({"schema": "research-forecast-v1", "procedure_id": row["procedure_id"],
            "input_snapshot_sha256": "a" * 64, "target": target,
            "probabilities": {"win": .6, "loss": .4, "push": 0., "void": 0.},
            "forecast_cutoff_utc": row["training_data_cutoff_utc"],
            "forecast_created_at_utc": row["forecast_created_at_utc"]})
        decision = select_research(forecast, config, decision_at_utc=row["decision_at_utc"])
        forecasts.append(forecast); decisions.append(decision)
        states.append({"event_id": row["event_id"], "forecast": forecast,
            "fitted_state_id": row["fitted_state_id"], "control_fitted_state_id": None,
            "training_data_cutoff_utc": row["training_data_cutoff_utc"]})
        population.append({"event_id": row["event_id"], "target_id": decision["target_id"], "slate_id": row["slate_id"]})
        outcomes.append({"event_id": row["event_id"], "target_id": decision["target_id"], "outcome": "WIN",
            "status": "FINAL", "observed_at_utc": "2026-10-08T00:00:00Z", "settled_at_utc": "2026-10-07T00:00:00Z",
            "source_sha256": "b" * 64, "source_ref": "TEST_ONLY_SYNTHETIC_OUTCOME"})
    policy = f["store"].read(f["plan"].plan_id)
    policy.update(target_family_id=content_hash(target_family(forecasts[0]["target"])),
                  population_id=content_hash(population), selector_config_id=f["store"].put(selector_config_artifact(config)))
    plan_id = f["store"].put(policy)
    registration = f["sign"](plan_id, "walk_forward_registration", "TEST_ONLY_witness", "2026-10-01T00:00:00Z")
    envelopes = []
    for payload, witnessed in f["fit_payloads"]:
        payload = dict(payload, plan_id=plan_id)
        payload_id = f["store"].put(payload)
        signed = f["sign"](payload_id, "walk_forward_fit", "TEST_ONLY_witness", witnessed)
        envelopes.append(f["store"].put({"fit_payload_id": payload_id, "fit_receipt_id": signed}))
    trust = {"schema": "research-validation-trust-v1", "public_keys_b64": {
        name: base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,
              serialization.PublicFormat.Raw)).decode() for name, key in f["keys"].items()}}
    (root / "trust.json").write_text(json.dumps(trust))
    runtime = {"schema": "research-walk-forward-runtime-v1", "store_directory": "store", "trust_file": "trust.json",
        "plan_id": plan_id, "registration_receipt_id": registration, "realized_fit_receipt_ids": envelopes}
    (root / "runtime.json").write_text(json.dumps(runtime))
    manifest = {"schema": "research-selection-evaluation-input-v1", "evidence_scope": "SHADOW"}
    for name, value in {"decisions": decisions, "population": population, "outcomes": outcomes, "forecast_states": states}.items():
        path = root / (name + ".json")
        path.write_text(json.dumps(value))
        manifest[name] = {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path, root / "runtime.json"


def test_runtime_cli_adapter_resolves_dynamic_fit_policy_read_only(tmp_path):
    manifest, runtime = packet(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = build_evaluation(manifest, walk_forward_config=runtime, bootstrap_samples=20,
                             executed_at=datetime(2026, 10, 23, tzinfo=timezone.utc))
    assert result["report"]["walk_forward_plan"]["plan_id"] == json.loads(runtime.read_text())["plan_id"]
    assert len({r["procedure_id"] for r in result["evaluation_rows"]}) == 2
    assert result["report"]["n_selected"] == 0
    assert not result["publication_allowed"]
    assert any("registry_artifact" in r.get("roles", []) for r in result["source_receipts"])
    assert all(p.read_bytes() == raw for p, raw in before.items())


def test_runtime_refuses_absent_trust_or_unplanned_states(tmp_path):
    manifest, runtime = packet(tmp_path)
    trust = tmp_path / "trust.json"
    trust.write_text(json.dumps({"schema": "research-validation-trust-v1", "public_keys_b64": {}}))
    with pytest.raises(ValueError, match="UNTRUSTED_SIGNER"):
        build_evaluation(manifest, walk_forward_config=runtime, bootstrap_samples=20)
    with pytest.raises(ValueError, match="WALK_FORWARD_REQUIRES_EXACT_FORECAST_STATE_RECEIPTS"):
        build_evaluation(manifest, bootstrap_samples=20)
