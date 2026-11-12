#!/usr/bin/env python3
"""Read-only scenario-aware event-exposure tool; prints research JSON to stdout."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.event_exposure_shadow import review_exposure_book


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",required=True,type=Path,help="JSON input; never changed")
    args=parser.parse_args(argv)
    packet=json.loads(args.input.read_text(encoding="utf-8"))
    output=review_exposure_book(
        packet.get("positions"),
        event_scenarios=packet.get("event_scenarios"),
        action_authority=packet.get("action_authority", False),
        official_stake_units=packet.get("official_stake_units",0),
    )
    print(json.dumps(output,sort_keys=True,indent=2))

if __name__=="__main__": main()
