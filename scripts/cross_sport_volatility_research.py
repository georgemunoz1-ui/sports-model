#!/usr/bin/env python3
"""Fit, build, and grade opt-in joint volatility-matrix research artifacts."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.common import volatility_matrix_v1 as V
from pipelines.cards.volatility_research import build, load_config


def _write(path, result):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"output": str(path), "status": result.get("status", "DIAGNOSTIC"),
                      "action_authority": False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fitting = commands.add_parser("fit")
    fitting.add_argument("--input", required=True, help="JSON with rows and fit configuration")
    fitting.add_argument("--output", required=True)
    card = commands.add_parser("card")
    card.add_argument("--card", required=True)
    card.add_argument("--config", required=True)
    card.add_argument("--output", required=True)
    card.add_argument("--simulations", type=int, default=100000)
    grading = commands.add_parser("grade")
    grading.add_argument("--distribution", required=True)
    grading.add_argument("--input", required=True, help="JSON result identity and observed paired score")
    grading.add_argument("--output", required=True)
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--input", required=True, help="JSON with luck record paths and evaluated_at")
    evaluation.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "card":
        result = build(json.loads(Path(args.card).read_text()), load_config(args.config), args.output,
                       simulations=args.simulations)
        print(json.dumps({"coverage": result["coverage"],
                          "output": str(Path(args.output) / "volatility_report.json")}, indent=2))
        return 2 if any(r["status"] != "COMPLETED" for r in result["coverage"]) else 0
    if args.command == "fit":
        _write(args.output, V.fit(**json.loads(Path(args.input).read_text())))
    elif args.command == "grade":
        distribution = json.loads(Path(args.distribution).read_text())
        _write(args.output, V.account_result(distribution, **json.loads(Path(args.input).read_text())))
    else:
        payload = json.loads(Path(args.input).read_text())
        records = [json.loads(Path(path).read_text()) for path in payload["records"]]
        _write(args.output, V.evaluate(records, evaluated_at=payload["evaluated_at"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
