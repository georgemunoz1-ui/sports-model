#!/usr/bin/env python3
"""Capture current NBA combination evidence; immutable output, no fit or promotion."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.nba_pregame_capture import run_capture


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", required=True, help="NBA slate date in America/Los_Angeles")
    p.add_argument("--output", type=Path, required=True, help="New directory only")
    p.add_argument("--baseline", type=Path, help="Original explicit frozen point-parent card; copied byte-for-byte")
    p.add_argument("--databallr-dom", type=Path, help="Rendered public DOM export; first observed at import, provider time remains unknown")
    p.add_argument("--dunks-api", action="store_true", help="Use documented v2 endpoint only with configured DUNKS_AND_THREES_API_KEY; never buys access")
    a = p.parse_args()
    report = run_capture(a.output, a.date, baseline=a.baseline, databallr_dom=a.databallr_dom, use_dt_api=a.dunks_api)
    print(json.dumps({k: report[k] for k in ("run_id", "execution_status", "events", "pregame_opportunities", "baseline_preserved", "external_margin_values", "databallr_event_pairs", "source_eligible", "fitting_eligible", "api_status")}))
    return 0 if report["execution_status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
