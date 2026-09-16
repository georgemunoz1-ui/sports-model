#!/usr/bin/env python3
"""Validate point-in-time provenance on a diagnostic card.

Default behavior is warning-only so DIAGNOSTIC_SHADOW continues to print a
numerical card while clearly refusing a false replay claim. Use --enforce to
turn PIT_STALE/PIT_REPLAY_INVALID/PIT_UNKNOWN into a non-zero exit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--card", required=True)
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()

    card = json.loads(Path(args.card).read_text())
    pit = card.get("pit_provenance") or {}
    status = pit.get("pit_status", "PIT_UNKNOWN")
    result = {
        "artifact": args.card,
        "league": card.get("league"),
        "card_date": card.get("card_date"),
        "requested_as_of_utc": card.get("requested_as_of_utc", card.get("as_of_utc")),
        "actual_data_vintage_utc": pit.get("actual_data_vintage_utc"),
        "pit_delta_seconds": pit.get("pit_delta_seconds"),
        "pit_status": status,
        "pit_reason": pit.get("pit_reason"),
        "pit_gate": pit.get("pit_gate", "WARN"),
        "pit_reconstruction_supported": pit.get("pit_reconstruction_supported"),
        "data_vintage_basis": pit.get("data_vintage_basis"),
        "action_authority": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))

    if args.enforce and status in {"PIT_STALE", "PIT_REPLAY_INVALID", "PIT_UNKNOWN"}:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
