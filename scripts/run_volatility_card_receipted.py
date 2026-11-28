#!/usr/bin/env python3
"""Run an explicit joint child with the same receipt as the shared card CLI."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from pipelines.cards.volatility_routing import run_joint_route, render_route


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--card", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--simulations", type=int, default=100000)
    args = parser.parse_args()
    receipt = run_joint_route(args.card, args.config, args.output,
                              simulations=args.simulations, repo_root=ROOT)
    print(render_route(receipt))
    return 0 if receipt["status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
