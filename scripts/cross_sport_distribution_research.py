#!/usr/bin/env python3
"""Fit/calibrate/score opt-in distribution challengers; never select defaults."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.common import discrete_research as D
from models.common import discrete_calibration as C
from pipelines.cards.distribution_research import build, load_config
from research.evaluate_discrete_products import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fitting = commands.add_parser("fit")
    fitting.add_argument("--input", required=True, help="JSON with rows and fit configuration")
    fitting.add_argument("--output", required=True)
    calibrating = commands.add_parser("calibrate")
    calibrating.add_argument("--input", required=True, help="JSON: rows, fitted_at")
    calibrating.add_argument("--output", required=True)
    grading = commands.add_parser("evaluate")
    grading.add_argument("--input", required=True, help="JSON: rows, baseline_id, challenger_id")
    grading.add_argument("--output", required=True)
    card = commands.add_parser("card")
    card.add_argument("--card", required=True)
    card.add_argument("--config", required=True)
    card.add_argument("--output", required=True)
    card.add_argument("--simulations", type=int, default=100000)
    args = parser.parse_args()
    if args.command == "card":
        result = build(json.loads(Path(args.card).read_text()), load_config(args.config), args.output,
                       simulations=args.simulations)
        print(json.dumps({"coverage": result["coverage"], "output": str(Path(args.output)/"distribution_report.json")}, indent=2))
        return 2 if any(r["status"] != "COMPLETED" for r in result["coverage"]) else 0
    payload = json.loads(Path(args.input).read_text())
    if args.command == "fit":
        result = D.fit_residuals(**payload)
    elif args.command == "calibrate":
        result = C.fit(**payload)
    else:
        result = evaluate(**payload)
    path = Path(args.output); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"output": str(path), "status": result.get("status", "DIAGNOSTIC"), "action_authority": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
