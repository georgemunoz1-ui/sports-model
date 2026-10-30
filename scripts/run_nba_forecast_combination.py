#!/usr/bin/env python3
"""Audit/fit an explicitly supplied research dataset; never imports card runners."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.nba_forecast_combination import audit, fit, predict


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("audit", "fit", "predict"))
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--stage", choices=("C1", "C2"), default="C1")
    p.add_argument("--train-before")
    p.add_argument("--state", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    rows = json.loads(a.dataset.read_text())["rows"]
    protocol = json.loads(a.protocol.read_text())
    root = a.dataset.parent
    if a.command == "audit":
        result = audit(rows, root, a.stage, a.train_before)
    elif a.command == "fit":
        if not a.train_before:
            p.error("fit requires --train-before")
        result = fit(rows, root, protocol, a.train_before, a.stage)
    else:
        if not a.state:
            p.error("predict requires --state")
        state = json.loads(a.state.read_text())
        if state.get("stage") != a.stage:
            p.error("state stage differs from --stage")
        result = {"predictions": [predict(r, root, state, protocol) for r in rows]}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    # A rerun cannot overwrite a prior fitted state or audit.
    with a.output.open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps({"output": str(a.output), "status": result.get("status", "COMPLETED"),
                      "fitted": result.get("fitted", False)}))
    return 2 if result.get("status", "").startswith("BLOCKED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
