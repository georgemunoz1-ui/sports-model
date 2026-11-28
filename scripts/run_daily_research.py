#!/usr/bin/env python3
"""Capture -> selected CFB model -> complete research card (archive/register follow)."""
import argparse
import datetime as dt
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipelines.daily_research import run


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", default=dt.datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat())
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--simulations", type=int, default=100000)
    p.add_argument("--next-slate", action="store_true", help="Discover first future selected CFB slate within six days from retained current source")
    args = p.parse_args()
    result = run(args.date, args.output, args.simulations, args.next_slate)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(1 if result["status"] == "FAILED" else 0)


if __name__ == "__main__":
    main()
