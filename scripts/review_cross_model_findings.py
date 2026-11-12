#!/usr/bin/env python3
"""Opt-in read-only research audit for named frozen contract receipts.

Input: {"observations": [{...}]}; output: group-separated JSON. This tool does
not write model state, canonical grading, registry files or any production card.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.cross_model_learning_review import cohort_summary, ReviewError


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, help="Optional research JSON, never canonical registration")
    args = ap.parse_args(argv)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("observations"), list):
        raise SystemExit("Input requires an observations array")
    try:
        result = cohort_summary(payload["observations"])
    except ReviewError as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc
    text = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
