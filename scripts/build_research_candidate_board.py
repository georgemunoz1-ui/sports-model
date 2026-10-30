#!/usr/bin/env python3
"""Build a probability-ranked exact-contract research board from frozen PMFs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipelines.cards.candidate_board import run_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New directory only")
    args = parser.parse_args(argv)
    try:
        report = run_file(args.input, args.output)
    except (ValueError, KeyError, TypeError, OSError, OverflowError) as exc:
        parser.exit(2, "candidate-board refused: " + str(exc) + "\n")
    print(json.dumps({k: report[k] for k in ("event_count", "candidate_count", "contract_count",
                                           "artifact_sha256", "wagering_authority")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
