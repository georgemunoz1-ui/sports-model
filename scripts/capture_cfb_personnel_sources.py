#!/usr/bin/env python3
"""Inspect retained official-report bytes, or capture only with reviewed rights."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.efficiency import cfb_personnel_sources as sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conference", choices=sorted(sources.SOURCES), required=True)
    parser.add_argument("--kind", choices=sorted(sources.ENDPOINTS), default="current")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw", type=Path, help="Inspect existing bytes; never claims a new network retrieval")
    parser.add_argument("--receipt", type=Path, help="Original capture receipt if available")
    args = parser.parse_args()
    if args.receipt and not args.raw:
        parser.error("--receipt requires --raw")
    if args.raw:
        raw = args.raw.read_bytes()
        receipt = (sources.decode(args.receipt.read_bytes()) if args.receipt else
                   sources.imported_receipt(raw, args.conference, args.kind))
        if receipt.get("conference") != args.conference or receipt.get("kind") != args.kind:
            parser.error("Source identity conflicts with receipt")
        report = sources.inspect_retained(raw, receipt)
        args.output.mkdir(parents=True, exist_ok=False)
        sources.exclusive(args.output / "raw.json", raw)
        sources.exclusive(args.output / "capture.json", receipt)
    else:
        try:
            receipt = sources.capture(args.conference, args.kind, args.output)
        except ValueError as exc:
            # A permission refusal happens before creating any network request.
            print(json.dumps({"status": "BLOCKED", "reason": str(exc), "network_requests": 0,
                              "action_authority": False}))
            return 2
        if receipt["status"] != "CAPTURED":
            print(json.dumps(receipt))
            return 2
        report = sources.inspect_retained((args.output / "raw.json").read_bytes(), receipt)
    sources.exclusive(args.output / "inspection.json", report)
    sources.exclusive(args.output / "manifest.json", {
        p.name: sources.raw_hash(p.read_bytes()) for p in args.output.iterdir() if p.is_file()})
    print(json.dumps({key: report.get(key) for key in (
        "conference", "kind", "report_count", "quarterback_row_count", "future_report_count",
        "archive_rows", "admissible_personnel_v2_observations", "source_use_status",
        "model_usage", "action_authority")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
