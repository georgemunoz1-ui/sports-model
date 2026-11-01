"""Read-only replay of the owner's October 30 capture archive; no acquisition."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from research.nba_forecast_combination import audit
from research.nba_pregame_capture import verified_raw, verify_capture_source
from scripts.nhl_atomic_capture import atomic, digest, encoded, inside


def replay(root):
    manifest = json.loads((root / "evidence-manifest.json").read_bytes())
    before = {name: digest(inside(root, name).read_bytes()) for name in manifest}
    if before != manifest:
        raise ValueError("ARCHIVE_MANIFEST_MISMATCH")
    runs, union = [], set()
    for run_dir in sorted(root.glob("live-capture-*/")):
        run_manifest = json.loads((run_dir / "manifest.json").read_bytes())
        if any(digest(inside(run_dir, name).read_bytes()) != sha for name, sha in run_manifest.items()):
            raise ValueError("RUN_MANIFEST_MISMATCH")
        dataset = json.loads((run_dir / "dataset.json").read_bytes())
        original = json.loads((run_dir / "report.json").read_bytes())
        for binding in original["captures"].values():
            verified_raw(run_dir, binding)
        rows = dataset["rows"]
        for row in rows:
            verify_capture_source(row["sources"]["B0"]["payload"], row, run_dir)
        stages = {stage: audit(rows, run_dir, stage) for stage in ("C1", "C2")}
        counts = {stage: value["eligible_events"] for stage, value in stages.items()}
        if counts != original["source_eligible"]:
            raise ValueError("ELIGIBILITY_CHANGED")
        union.update(r["event_id"] for r in rows)
        runs.append(dict(run_id=dataset["run_id"], events=len(rows),
            dataset_sha256=digest((run_dir / "dataset.json").read_bytes()),
            baseline_originals_verified=len(rows), raw_receipts_verified=len(original["captures"]),
            external_margin_values=original["external_margin_values"],
            databallr_event_pairs=original["databallr_event_pairs"], source_eligible=counts,
            exclusions={stage: dict(Counter(reason for record in value["records"]
                        for reason in record["exclusions"])) for stage, value in stages.items()}))
    after = {name: digest(inside(root, name).read_bytes()) for name in manifest}
    if before != after:
        raise ValueError("REPLAY_MUTATED_EVIDENCE")
    return dict(schema="nba.acquisition_review_replay.v1", archive_manifest_sha256=digest((root / "evidence-manifest.json").read_bytes()),
                files_verified=len(before), runs=runs, distinct_events=len(union),
                source_files_changed=0, authenticated_acquisition_exercised=False,
                source_qualification="BLOCKED", predictive_validation="NOT_ASSESSED", wagering_authority="OFF")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("evidence_root", type=Path)
    p.add_argument("--output", type=Path, required=True, help="New file outside the retained archive")
    args = p.parse_args()
    if args.output.resolve().is_relative_to(args.evidence_root.resolve()):
        p.error("output must be outside retained evidence")
    result = replay(args.evidence_root)
    atomic(args.output, encoded(result))
    print(json.dumps(result))
