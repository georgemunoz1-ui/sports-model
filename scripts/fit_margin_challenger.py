#!/usr/bin/env python3
"""Fit the opt-in margin challenger from explicit same-parent OOF records.

Input JSON: {"rows": [...], "league": "nfl", "settlement":
"FULL_GAME_OT_REGULAR", "parent_model_id": "...", "information_set": "...",
"fitted_at": "...+00:00", "scale_features": ["absolute_parent_margin"]}.
Each row follows models.common.discrete_research.fit_residuals' contract.
No model registry/default is changed by this command.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models.common.margin_challenger import fit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('IMMUTABLE_OUTPUT_ALREADY_EXISTS')
    payload = json.loads(args.input.read_text())
    model = fit(**payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        json.dump(model, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps({'model_id': model['model_id'], 'training_n': model['training_n'],
                      'artifact_sha256': model['artifact_sha256'], 'output': str(args.output),
                      'predictive_validation': 'UNVALIDATED', 'action_authority': False}))


if __name__ == '__main__':
    main()
