#!/usr/bin/env python3
"""Create an additive all-sports research margin/cover card from retained PMFs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", default=[], type=Path,
                        help="Retained distribution_report.json or explicit margin-system input; repeatable")
    parser.add_argument("--output", required=True, type=Path,
                        help="A new directory; existing directories are refused")
    parser.add_argument("--events", type=Path,
                        help="Optional metadata JSON with an events or forecasts list")
    parser.add_argument("--parent-card", action="append", default=[], type=Path,
                        help="Explicit margin point heads; requires a bound challenger config")
    parser.add_argument("--challenger-config", type=Path,
                        help="Hash-pinned fitted challenger configuration")
    parser.add_argument("--draws", type=int, default=100_000)
    parser.add_argument("--home-spreads", type=str,
                        help="Comma-separated hypothetical home handicaps; default is a sport-specific ladder")
    args = parser.parse_args(argv)
    from pipelines.cards.margin_system import build
    try:
        lines = None if args.home_spreads is None else [float(v) for v in args.home_spreads.split(",")]
        report = build(args.input, args.output, events_path=args.events,
                       draws=args.draws, home_spreads=lines,
                       parent_card_paths=args.parent_card, challenger_config_path=args.challenger_config)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f"margin-system refused: {exc}\n")
    print(json.dumps({"output": str(args.output.resolve()), "rows": len(report["results"]),
                      "artifact_sha256": report["artifact_sha256"],
                      "action_authority": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
