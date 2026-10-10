#!/usr/bin/env python3
"""Explicitly opt-in, market-free NBA efficiency shadow; never the selected adapter."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models.nba.efficiency_monte_carlo_shadow_v1_1 import run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-research', action='store_true', required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--model-state', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--simulations', type=int, default=100000)
    args = parser.parse_args(argv)
    snapshot = json.loads(args.snapshot.read_text())
    state = json.loads(args.model_state.read_text())
    result = run(snapshot, state, args.simulations)
    envelope = {'schema': 'nba-efficiency-shadow-report.v1',
                'research_only': True, 'canonical_eligible': False,
                'action_authority': False, 'result': result,
                'limitations': ['Synthetic direction/engineering repair; predictive validation unestablished.',
                                'No fitted state supplied by repository; caller must supply explicit fitted parameters.',
                                'Inherited one-point random tie-break is not a fitted overtime model.']}
    # Exclusive creation preserves any prior artifact. Input/config hashes live in result.
    with args.output.open('x') as stream:
        stream.write(json.dumps(envelope, sort_keys=True, indent=2, allow_nan=False) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
