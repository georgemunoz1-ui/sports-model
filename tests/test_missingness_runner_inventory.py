"""Coverage mutation probes and actual legacy/native CLI invocation checks."""
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import sys

import pytest

from pipelines.cards.runner_inventory import discover, validate
from pipelines.cards import legacy_cli_missingness as cli_audit

ROOT = Path(__file__).resolve().parents[1]


def _registry(root):
    return {"schema": "sports.missingness_entrypoints.v1", "entrypoints": {
        path: {"role": "review", "reason": "Synthetic inventory coverage fixture.",
               "official_release_eligible": False} for path in discover(root)}}


def _write(root, path, text):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return target


def test_all_discovered_entries_classified_and_audits_bound():
    registry = json.loads((ROOT / "data/model_selection/missingness/entrypoints.json").read_bytes())
    result = validate(ROOT, registry)
    assert result["inventory_status"] == "PASS"
    assert result["runtime_invocation_verified_by_inventory"] is False
    legacy = json.loads((ROOT / "data/model_selection/missingness/runner_inventory.json").read_bytes())
    assert legacy["entrypoint_registry"] == "data/model_selection/missingness/entrypoints.json"
    assert all(registry["entrypoints"][path]["role"] == "audited_forecast"
               for path in legacy["active_research"])
    for path in ["models/cfb/monte_carlo_v1.py", "models/mlb/monte_carlo_v1.py",
                 "models/nfl/contextual/margin_distribution.py", "sportsim/__main__.py"]:
        assert path in result["discovery"]
        assert registry["entrypoints"][path]["role"] == "audited_forecast"


@pytest.mark.parametrize("path", ["scripts/predict_new.py", "models/nhl/forecast.py",
                                  "research/new_arm/cli.py", "pipelines/new_model.py"])
def test_non_run_filename_cannot_escape_inventory(tmp_path, path):
    before = _registry(tmp_path)
    _write(tmp_path, path, "if '__main__' == __name__:\n    print('new entry')\n")
    with pytest.raises(ValueError, match="ENTRYPOINT_INVENTORY_DRIFT"):
        validate(tmp_path, before)


def test_console_function_without_main_guard_is_inventoried(tmp_path):
    _write(tmp_path, "models/custom_cli.py", "def main():\n    pass\n")
    before = _registry(tmp_path)
    _write(tmp_path, "pyproject.toml", '[project.scripts]\nforecast = "models.custom_cli:main"\n')
    with pytest.raises(ValueError, match="ENTRYPOINT_INVENTORY_DRIFT"):
        validate(tmp_path, before)


def test_workflow_commands_outside_scan_roots_are_inventoried(tmp_path):
    _write(tmp_path, "ops/new_forecast.py", "print('fixture')\n")
    before = _registry(tmp_path)
    _write(tmp_path, ".github/workflows/forecast.yml",
           "jobs:\n  model:\n    steps:\n      - working-directory: ops\n        run: python -u new_forecast.py\n")
    with pytest.raises(ValueError, match="ENTRYPOINT_INVENTORY_DRIFT"):
        validate(tmp_path, before)


def test_inline_workflow_forecast_cannot_escape_path_inventory(tmp_path):
    before = _registry(tmp_path)
    _write(tmp_path, ".github/workflows/inline.yml",
           "jobs:\n  model:\n    steps:\n      - run: |\n          python - <<'PY'\n          print('fixture forecast')\n          PY\n")
    with pytest.raises(ValueError, match="INLINE_WORKFLOW_REVIEW_REQUIRED"):
        validate(tmp_path, before)


def test_audit_label_requires_existing_boundary_and_invocation_test(tmp_path):
    _write(tmp_path, "models/new.py", "if __name__ == '__main__':\n    pass\n")
    registry = _registry(tmp_path)
    registry["entrypoints"]["models/new.py"]["role"] = "audited_forecast"
    with pytest.raises(ValueError, match="ENTRYPOINT_INVOCATION_EVIDENCE_REQUIRED"):
        validate(tmp_path, registry)


def _inputs(league):
    if league == "mlb":
        return {"event_id":"SYNTHETIC_MLB", "home_sp":{"era":3.5,"gs":20,"k":25,"bb":7},
                "away_sp":{}, "home_rf_pg":4.7,"away_rf_pg":4.4,"home_ra_pg":4.1}, {"version":"fixture"}
    return {"game_id":"SYNTHETIC_CFB", "start_date":"2030-09-05T00:00:00Z", "home_team":"H", "away_team":"A",
            "home_division":"fbs", "away_division":"fbs", "week":"1", "home_pregame_elo":"1600",
            "away_pregame_elo":"1500", "neutral_site":"", "conference_game":"FALSE"}, {
                "model_id":"cfb.margin_distribution.fixture", "version":"fixture", "code_commit":"fixture",
                "parameters":{"intercept":6.4,"elo_diff_coefficient":.068,"neutral_site_coefficient":1.8,
                              "conference_game_coefficient":-7.7},
                "residual_model":{"global_sigma":18.1,"segment_sigma_by_week":{}}}


@pytest.mark.parametrize("league", ["mlb", "cfb"])
def test_actual_monte_carlo_cli_retains_native_output_and_audited_sidecar(tmp_path, monkeypatch, league):
    from importlib import import_module
    native = import_module("models." + league + ".monte_carlo_v1")
    inputs, state = _inputs(league)
    state_path = _write(tmp_path, "state.json", json.dumps(state))
    output = tmp_path / "forecast.json"
    if league == "mlb":
        source = _write(tmp_path, "snapshot.json", json.dumps(inputs))
        expected = native.run(inputs, state, 50000)
        argv = [native.__file__, "--snapshot", str(source), "--config", str(state_path)]
    else:
        source = tmp_path / "schedule.csv"
        with source.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(inputs)); writer.writeheader(); writer.writerow(inputs)
        elo_path = _write(tmp_path, "elo.json", '{}')
        expected = native.run(native.build_snapshot(inputs, {}), state, 50000)
        argv = [native.__file__, "--event-id", inputs["game_id"], "--schedule", str(source),
                "--model-state", str(state_path), "--elo-state", str(elo_path)]
    monkeypatch.setattr(sys, "argv", argv + ["--output", str(output), "--simulations", "50000"])
    native.main()
    actual = json.loads(output.read_bytes())
    for row in (expected, actual):
        row.pop("generated_at_utc")
    assert actual == expected
    receipt = cli_audit.verify(output)["missingness_audit"]
    assert receipt["release_status"] == "HOLD_PENDING_SCOPE_REVIEW"
    details = receipt["details"]
    assert details["source_observation_state"] == "UNRESOLVED_IDENTITY_OR_COVERAGE"
    if league == "mlb":
        assert details["features"]["away_sp.gs"]["fallback_applied"] is True
        assert details["features"]["away_ra_pg"]["consumed_value"] == 4.45
    else:
        assert details["global_sigma_fallback"] is True
        assert details["schedule_boolean_defaults"]["neutral_site"]["missing_source_value"] is True
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        native.main()
    assert output.read_bytes() == original
    changed = json.loads(original); changed["projection"]["home_win_p_sim"] += .001
    output.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="READBACK_FAILED"):
        cli_audit.verify(output)


@pytest.mark.parametrize("defect", ["missing_event", "timeout", "duplicate"])
def test_direct_mlb_cli_refuses_source_failure_before_kernel(tmp_path, monkeypatch, defect):
    from models.mlb import monte_carlo_v1 as native
    snapshot, state = _inputs("mlb")
    if defect == "missing_event":
        snapshot.pop("event_id")
    elif defect == "timeout":
        snapshot["source_fetches"] = [{"status":"TIMEOUT"}]
    else:
        snapshot["consumed_game_ids"] = [1, "1"]
    source = _write(tmp_path, "snapshot.json", json.dumps(snapshot))
    state_path = _write(tmp_path, "state.json", json.dumps(state))
    output = tmp_path / "forecast.json"
    monkeypatch.setattr(sys, "argv", [native.__file__, "--snapshot", str(source), "--config", str(state_path),
                                     "--output", str(output)])
    monkeypatch.setattr(native, "run", lambda *a: pytest.fail("failed source reached kernel"))
    with pytest.raises(ValueError):
        native.main()
    assert not output.exists()


@pytest.mark.parametrize("defect", ["empty_schedule", "duplicate_event", "failed_elo_capture"])
def test_direct_cfb_cli_refuses_source_defects_before_kernel(tmp_path, monkeypatch, defect):
    from models.cfb import monte_carlo_v1 as native
    row, state = _inputs("cfb")
    schedule = tmp_path / "schedule.csv"
    with schedule.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row)); writer.writeheader()
        if defect != "empty_schedule":
            writer.writerow(row)
        if defect == "duplicate_event":
            writer.writerow(row)
    elo = {"source_fetches":[{"ok":False}]} if defect == "failed_elo_capture" else {}
    ep = _write(tmp_path, "elo.json", json.dumps(elo))
    sp = _write(tmp_path, "state.json", json.dumps(state))
    output = tmp_path / "forecast.json"
    monkeypatch.setattr(sys, "argv", [native.__file__, "--event-id", row["game_id"], "--schedule", str(schedule),
                                     "--elo-state", str(ep), "--model-state", str(sp), "--output", str(output)])
    monkeypatch.setattr(native, "run", lambda *a: pytest.fail("failed source reached kernel"))
    with pytest.raises((ValueError, SystemExit)):
        native.main()
    assert not output.exists()


def test_actual_native_margin_cli_writes_child_receipt(tmp_path, monkeypatch):
    from models.nfl.contextual import margin_distribution as native
    from models.common import discrete_research as D
    from test_nfl_margin_distribution import configured, fitted, write
    config_path, _, forecast, _ = configured(tmp_path, fitted(), monkeypatch)
    parent = tmp_path / "frozen"; parent.mkdir()
    write(parent / "forecast.json", forecast)
    registration = {"forecast_identity":forecast["identity"], "created_at_utc":forecast["cutoff_utc"]}
    registration["record_hash"] = D.digest(registration)
    write(parent / "registration.jsonl", registration)
    write(parent / "manifest.json", {name:hashlib.sha256((parent/name).read_bytes()).hexdigest()
                                      for name in ("forecast.json", "registration.jsonl")})
    output = tmp_path / "child"
    monkeypatch.setattr(sys, "argv", [native.__file__, "--forecast-dir", str(parent), "--margin-model", str(config_path),
                                     "--output", str(output), "--simulations", "100"])
    native.main()
    receipt = json.loads((output / "missingness_audit.json").read_bytes())
    assert receipt["products"] == ["full_game_spread"]
    assert receipt["details"]["comparison_status"] == "CHILD_SENSITIVITY_NOT_ESTABLISHED"
    assert receipt["release_status"] == "HOLD_PENDING_SCOPE_REVIEW"


def test_missing_native_margin_audit_call_fails_the_cli(tmp_path, monkeypatch):
    """Deleting/bypassing the mandatory hook is observable on the real route."""
    from models.nfl.contextual import margin_distribution as native
    from pipelines.cards import nfl_missingness
    from test_nfl_margin_distribution import configured, fitted
    config_path, _, forecast, _ = configured(tmp_path, fitted(), monkeypatch)
    monkeypatch.setattr(native, "read_frozen_forecast", lambda _: forecast)
    monkeypatch.setattr(sys, "argv", [native.__file__, "--forecast-dir", str(tmp_path), "--margin-model", str(config_path),
                                     "--output", str(tmp_path / "child"), "--simulations", "100"])
    def refuse(*args, **kwargs):
        raise ValueError("TEST_MANDATORY_MISSINGNESS_CHECK")
    monkeypatch.setattr(nfl_missingness, "persist_child_review", refuse)
    with pytest.raises(ValueError, match="TEST_MANDATORY_MISSINGNESS_CHECK"):
        native.main()
