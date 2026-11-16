"""Regression for PR #117: interrupted receipt write must not strand the forecast.

At e4085c6d, persist() writes the forecast with "xb" and then the sidecar. A
receipt write that fails mid-way leaves the forecast present but its receipt
unreadable, and the retry guard then raises DIAGNOSTIC_OUTPUT_ALREADY_EXISTS.

This test injects a fault during receipt writing, asserts the failed attempt
leaves no complete pair, removes the fault, retries the same command, and
requires verify() to succeed. A further invocation must preserve both files.
"""
import json
import sys
from pathlib import Path

import pytest

from pipelines.cards import legacy_cli_missingness as cli_audit
from pipelines.cards.missingness import seal_audit


def _monkeypatch_fault(monkeypatch, fault_at):
    original = seal_audit

    def faulty(*args, **kwargs):
        if fault_at == "receipt":
            # Simulate OSError [Errno 27] File too large mid-receipt.
            raise OSError(27, "File too large")
        return original(*args, **kwargs)

    monkeypatch.setattr(cli_audit, "seal_audit", faulty)


def test_interrupted_receipt_then_retry_recovers(tmp_path, monkeypatch):
    from models.mlb import monte_carlo_v1 as native

    inputs = {
        "event_id": "SYNTHETIC_MLB",
        "home_sp": {"era": 3.5, "gs": 20, "k": 25, "bb": 7},
        "away_sp": {},
        "home_rf_pg": 4.7,
        "away_rf_pg": 4.4,
        "home_ra_pg": 4.1,
    }
    state = {"version": "fixture"}
    source = tmp_path / "snapshot.json"
    source.write_text(json.dumps(inputs))
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state))
    output = tmp_path / "forecast.json"

    monkeypatch.setattr(sys, "argv", [native.__file__, "--snapshot", str(source),
                                      "--config", str(state_path), "--output", str(output),
                                      "--simulations", "50000"])

    # First attempt: fault during receipt write.
    _monkeypatch_fault(monkeypatch, "receipt")
    with pytest.raises(OSError, match="File too large"):
        native.main()

    # Neither final path may be a complete, verifiable pair.
    sidecar = Path(str(output) + ".missingness.json")
    assert output.exists() or sidecar.exists()
    assert not (output.exists() and sidecar.exists())
    with pytest.raises((ValueError, OSError, json.JSONDecodeError)):
        cli_audit.verify(output)

    # Remove the fault and retry the same command. The retry must complete
    # without overwriting the existing forecast.
    monkeypatch.undo()
    native.main()

    # Both files must exist and verify cleanly.
    assert output.exists() and sidecar.exists()
    record = cli_audit.verify(output)
    assert record["missingness_audit"]["release_status"] == "HOLD_PENDING_SCOPE_REVIEW"

    original_forecast = output.read_bytes()
    original_receipt = sidecar.read_bytes()

    # A further invocation of the same command must preserve both files.
    with pytest.raises(FileExistsError):
        native.main()
    assert output.read_bytes() == original_forecast
    assert sidecar.read_bytes() == original_receipt