#!/usr/bin/env python3
"""Execute the explicit NBA projected-minutes research experiment or card sidecar."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.efficiency.nba_personnel_runner import experiment, shadow_from_card


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Experiment manifest, or sidecar config when --card is supplied")
    parser.add_argument("--card", help="Existing immutable NBA diagnostic_card.json")
    parser.add_argument("--output", required=True, help="New output directory; overwrite is refused")
    args = parser.parse_args()
    report = shadow_from_card(args.card, args.input, args.output) if args.card else experiment(args.input, args.output)
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 2 if report.get("status") == "BLOCKED" or (args.card and report["completed_count"] == 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
