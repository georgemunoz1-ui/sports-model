#!/usr/bin/env python3
"""Audit retained study PMF tails without refitting or selecting a successor."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.distribution_diagnostics import audit_groups


def execute(study, output):
    study = Path(study).resolve()
    portable_path = study / "portable_replay_manifest.json"
    portable = json.loads(portable_path.read_bytes())
    reports, sources = {}, {}
    for path in sorted(study.glob("*/*_frozen_distributions.json.gz")):
        relative = str(path.relative_to(study))
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if portable["files"].get(relative) != sha:
            raise ValueError("FROZEN_DISTRIBUTION_HASH_MISMATCH:" + relative)
        sources[relative] = sha
        reports[relative] = audit_groups(json.loads(gzip.decompress(path.read_bytes())))
    if not reports:
        raise ValueError("NO_RETAINED_DISTRIBUTIONS")
    report = {"schema": "sports.distribution_tail_audit.v1", "reports": reports, "source_hashes": sources,
              "portable_manifest_sha256": hashlib.sha256(portable_path.read_bytes()).hexdigest(),
              "new_forecasts": 0, "new_fits": 0, "prospective_validation": "NOT_RUN",
              "provider_authenticity": "NOT_ESTABLISHED", "action_authority": False}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as f:
        json.dump(report, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    report = execute(args.study, args.output)
    print(json.dumps({"products": len(report["reports"]), "new_fits": 0, "new_forecasts": 0}))
