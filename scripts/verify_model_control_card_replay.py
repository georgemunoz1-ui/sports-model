#!/usr/bin/env python3
"""Replay retained NBA/CFB/NHL cards through the shared research CLI.

Uses each original cutoff for numerical reproduction only. It does not claim a
fresh source capture, original PIT eligibility, or prospective registration.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.replay_controls import equivalent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(retained, output):
    retained, output = Path(retained).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    inputs = output / "extension-inputs"
    inputs.mkdir()
    nba_config = inputs / "nba.json"
    nba_config.write_text(json.dumps({"schema": "nba-personnel-shadow.v1", "state":
        {"path": "eligible-fitted-minutes-state-required.json", "sha256": "0" * 64},
        "inputs": {"path": "source-bound-rotations-required.json", "sha256": "0" * 64}}))
    nhl_config = inputs / "nhl.json"
    package = retained / "packages/nhl/package.json"
    nhl_config.write_text(json.dumps({"schema": "sports.nhl_context_config.v1", "action_authority": False,
        "package": {"path": str(package), "sha256": sha(package)}}))
    report = {"schema": "sports.retained_shared_card_replay.v1", "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "entrypoint_sha256": sha(ROOT / "scripts/generate_card_force.py"),
        "verification_script_sha256": sha(__file__), "leagues": {},
        "information_class": "RETAINED_INPUT_DIAGNOSTIC_REPLAY", "new_independent_events": 0,
        "pit_eligibility": "UNRESOLVED", "provider_authenticity": "NOT_AUTHENTICATED",
        "predictive_validation": "NOT_ASSESSED", "canonical_registration": False, "action_authority": False}
    fields = ("model_id", "model_p", "sim_p", "projected_margin", "projected_total", "model_input_snapshot",
              "model_state_config_hash", "input_snapshot_hash")
    for league in ("nba", "cfb", "nhl"):
        original_path = retained / (league + "-parent") / "diagnostic_card.json"
        original_bytes = original_path.read_bytes()
        original = json.loads(original_bytes)
        command = [sys.executable, str(ROOT / "scripts/generate_card_force.py"), "--league", league,
            "--date", original["card_date"], "--as-of-utc", original["as_of_utc"], "--simulations", "100000",
            "--output-dir", str(output / league)]
        if league in {"nba", "nhl"}:
            command.append("--initial-research-baselines")
            command.extend(["--personnel-research-config" if league == "nba" else "--nhl-context-config",
                            str(nba_config if league == "nba" else nhl_config)])
        env = os.environ.copy()
        env["SPORTS_RESEARCH_PACKAGE_DIR"] = str(retained / "packages")
        proc = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
        (output / (league + ".log")).write_text(proc.stdout + proc.stderr)
        new_path = output / league / "diagnostic_card.json"
        if proc.returncode not in (0, 2) or not new_path.exists():
            raise ValueError("SHARED_RUNNER_FAILED:" + league)
        actual = json.loads(new_path.read_bytes())
        expected_rows = {r["event_id"]: r for r in original["forecasts"]}
        actual_rows = {r["event_id"]: r for r in actual["forecasts"]}
        if set(expected_rows) != set(actual_rows):
            raise ValueError("REPLAY_EVENT_COVERAGE_MISMATCH")
        count = 0
        for eid, expected in expected_rows.items():
            current = actual_rows[eid]
            equivalent({k: current.get(k) for k in fields}, {k: expected.get(k) for k in fields})
            old_draws = retained / (league + "-parent") / "draws" / Path(expected["simulation"]["draw_directory"]).name
            new_draws = Path(current["simulation"]["draw_directory"])
            for path in old_draws.glob("*.npy"):
                if sha(path) != sha(new_draws / path.name):
                    raise ValueError("REPLAY_DRAW_BYTES_MISMATCH")
                count += 1
            if current.get("action_authority") is not False:
                raise ValueError("AUTHORITY_DRIFT")
        if original_path.read_bytes() != original_bytes:
            raise ValueError("ORIGINAL_FORECAST_MUTATED")
        extension = None
        if league in {"nba", "nhl"}:
            name = "nba_personnel" if league == "nba" else "nhl_context"
            folder = output / league / name
            extension = {p.name: json.loads(p.read_bytes()) for p in folder.glob("*.json") if p.name != "manifest.json"}
        report["leagues"][league] = {"command": command, "returncode": proc.returncode,
            "events": len(actual_rows), "draw_arrays_equal": count, "original_card_sha256": sha(original_path),
            "replayed_card_sha256": sha(new_path), "numerical_replay": "PASS", "extension": extension}
    (output / "receipt.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retained", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = execute(args.retained, args.output)
    print(json.dumps({"events": sum(x["events"] for x in result["leagues"].values()),
                      "numerical_replay": "PASS", "action_authority": False}))
