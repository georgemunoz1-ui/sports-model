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
    p.add_argument("--acquisition-profile", choices=("legacy", "dunks-api"), default="legacy",
                   help="dunks-api requests only schedule, D&T methodology and credentialed API; no public game page or Databallr acquisition. Requires separately established usage rights.")
    a = p.parse_args()
    if a.acquisition_profile == "dunks-api" and a.databallr_dom is not None:
        p.error("dunks-api profile excludes Databallr imports; use a separately permitted legacy capture")
    report = run_capture(a.output, a.date, baseline=a.baseline, databallr_dom=a.databallr_dom,
                         use_dt_api=a.dunks_api, acquisition_profile=a.acquisition_profile)
    print(json.dumps({k: report[k] for k in ("run_id", "execution_status", "events", "pregame_opportunities", "baseline_preserved", "external_margin_values", "databallr_event_pairs", "source_eligible", "fitting_eligible", "api_status", "acquisition_profile", "source_eligibility_scope", "source_qualification")}))
    return 0 if report["execution_status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
