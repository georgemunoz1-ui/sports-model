#!/usr/bin/env python3
"""Fit and evaluate separate CFB/NBA research challengers against real controls."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.efficiency.runner import experiment, shadow_from_card


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--league", choices=["cfb", "nba"], required=True)
    p.add_argument("--history", type=Path, help="Normalized source-bound history; historical archives are reconstructed diagnostics.")
    p.add_argument("--stages", nargs="+", choices=["efficiency", "personnel", "joint"], default=["efficiency", "personnel", "joint"])
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--bootstrap-count", type=int, default=2000)
    p.add_argument("--source-card", type=Path)
    p.add_argument("--shadow-config", type=Path)
    p.add_argument("--simulations", type=int, default=100000)
    a = p.parse_args()
    if a.source_card or a.shadow_config:
        if not (a.source_card and a.shadow_config) or a.history:
            p.error("SHADOW requires source-card and shadow-config, without history")
        report = shadow_from_card(a.source_card, a.shadow_config, a.output_dir, simulations=a.simulations)
        print(json.dumps({"run_id": report["run_id"], "logged_count": report["logged_count"], "canonical_prospective_eligible": False, "action_authority": False}))
    else:
        if not a.history:
            p.error("historical evaluation requires --history")
        report = experiment(a.league, a.history, a.output_dir, stages=a.stages, bootstrap_count=a.bootstrap_count)
        print(json.dumps({"run_id": report["run_id"], "coverage": {k: v for k, v in report["coverage"].items() if not isinstance(v, list)},
                          "stages": {k: {f: v.get(f) for f in ("status", "model_id", "n_predictions", "reason")} for k, v in report["stages"].items()}, "action_authority": False}))


if __name__ == "__main__":
    main()
