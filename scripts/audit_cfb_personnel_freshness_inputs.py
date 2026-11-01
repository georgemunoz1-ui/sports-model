#!/usr/bin/env python3
"""Audit retained event-context captures without inferring personnel observations."""
from pathlib import Path
import argparse
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models.experiments.cfb_personnel import values
from research.efficiency.cfb_personnel_freshness import time
from research.efficiency.runner import write


def audit(source_index):
    source_index = Path(source_index).resolve(strict=True)
    raw_index = source_index.read_bytes()
    rows = json.loads(raw_index)
    results = []
    for row in rows:
        event, source = row["event"], row["source"]
        raw = (source_index.parent / source["raw_path"]).read_bytes()
        bound = hashlib.sha256(raw).hexdigest() == source["raw_sha256"]
        parsed = json.loads(raw)
        if parsed != row["data"]:
            raise ValueError("CAPTURE_INDEX_RAW_VALUE_MISMATCH")
        # Exercise the existing admission check on only the retained payload.
        # No availability, snap ratio, or participation assumption is invented.
        try:
            values({"event_id": event["event_id"], "personnel_evidence": parsed.get("personnel_evidence")})
            admission = "UNEXPECTED_ADMISSION_REQUIRES_REVIEW"
        except (ValueError, KeyError, TypeError) as exc:
            admission = str(exc)
        results.append({"event_id": event["event_id"], "source_url": source["url"],
            "raw_sha256": source["raw_sha256"], "bytes_hash_verified": bound,
            "retrieved_at_utc": source["retrieved_at_utc"],
            "provider_observed_at_utc": source.get("provider_observed_at_utc"),
            "retrieved_before_start": time(source["retrieved_at_utc"]) < time(event["start_time_utc"]),
            "normalized_personnel_v2_present": isinstance(parsed.get("personnel_evidence"), dict),
            "injury_groups_present": bool(parsed.get("injuries")), "admission": admission,
            "current_source_qualified": False})
    return {"schema": "cfb.retained-personnel-freshness-audit.v1",
        "source_index": str(source_index), "source_index_sha256": hashlib.sha256(raw_index).hexdigest(),
        "capture_count": len(results), "unique_event_count": len({r["event_id"] for r in results}),
        "byte_verified_count": sum(r["bytes_hash_verified"] for r in results),
        "missing_provider_observed_time_count": sum(r["provider_observed_at_utc"] is None for r in results),
        "personnel_admitted_count": 0, "predictive_evaluation_event_count": 0,
        "scope": "Retained supplied context captures only; not a new provider acquisition or a complete historical corpus census.",
        "missing_inputs": ["source-bound expected QB and prior pass-attempt shares",
            "offensive and defensive returning-snap counts", "pre-cutoff participation assumptions",
            "source-native observation times and revisions", "independent pre-cutoff snapshot anchors",
            "authentic eligible personnel-v2 training/evaluation cohort and fitted parent"],
        "rows": results, "predictive_validation": "NOT_ASSESSED", "action_authority": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.source_index)
    write(args.output, report)
    print(json.dumps({k: report[k] for k in ("capture_count", "byte_verified_count", "personnel_admitted_count")}))


if __name__ == "__main__":
    main()
