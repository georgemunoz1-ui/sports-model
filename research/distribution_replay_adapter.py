"""Checkpoint-free subprocess boundary for the retained distribution replay.

Only allowlisted inference values cross this API. This is a data-flow boundary
for trusted repository code, not an OS sandbox for a malicious adapter.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FIELDS = frozenset({"predicted_mean", "event_id", "forecast_cutoff",
                    "parent_model_id", "information_set", "forecast_sha256", "scale_features"})


def inference_payload(model, rows):
    return {"model": model, "rows": [{key: row[key] for key in FIELDS} for row in rows]}


def predict_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {"model", "rows"}:
        raise ValueError("ADAPTER_INPUT_BOUNDARY")
    if not isinstance(payload["rows"], list) or not payload["rows"]:
        raise ValueError("ADAPTER_ROWS_REQUIRED")
    from models.common import discrete_research as D
    predictions = []
    for row in payload["rows"]:
        if not isinstance(row, dict) or set(row) != FIELDS:
            raise ValueError("ADAPTER_INPUT_BOUNDARY")
        predictions.append(D.predict(payload["model"], mean=row["predicted_mean"],
            event_id=row["event_id"], cutoff=row["forecast_cutoff"],
            parent_model_id=row["parent_model_id"], information_set=row["information_set"],
            parent_forecast_sha256=row["forecast_sha256"], scale_features=row["scale_features"]))
    return predictions


def reconstruct(model, rows):
    payload = inference_payload(model, rows)
    raw = json.dumps(payload, sort_keys=True, allow_nan=False).encode()
    with tempfile.TemporaryDirectory(prefix="distribution-replay-inputs-") as scratch:
        completed = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--worker"],
            input=raw, capture_output=True, cwd=scratch,
            env={"PATH": os.defpath, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
            timeout=300, check=False)
    if completed.returncode:
        raise ValueError("REPLAY_ADAPTER_FAILED:" + completed.stderr.decode()[-2000:])
    predictions = json.loads(completed.stdout)
    if not isinstance(predictions, list) or len(predictions) != len(rows):
        raise ValueError("REPLAY_ADAPTER_OUTPUT_COUNT")
    receipt = {"schema": "sports.checkpoint_free_adapter.v1",
        "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "kernel_sha256": hashlib.sha256((ROOT / "models/common/discrete_research.py").read_bytes()).hexdigest(),
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "output_sha256": hashlib.sha256(completed.stdout).hexdigest(),
        "event_count": len(rows), "expected_checkpoints_supplied": False,
        "isolation_scope": "ALLOWLISTED_INPUTS_FRESH_PROCESS_NOT_OS_SANDBOX"}
    return predictions, receipt


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("internal worker requires --worker")
    sys.path.insert(0, str(ROOT))
    result = predict_payload(json.loads(sys.stdin.buffer.read()))
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
