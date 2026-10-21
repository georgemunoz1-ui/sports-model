#!/usr/bin/env python3
"""Create an immutable disclosure sidecar without rewriting a frozen card."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipelines.cards.disclosures import write_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--card", type=Path, required=True)
    parser.add_argument("--disclosures", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = write_report(json.loads(args.card.read_text()), args.output, args.disclosures)
    print(json.dumps({"execution_status": report["execution_status"],
                      "artifact_sha256": report["artifact_sha256"], "errors": report["errors"]}))
    if report["errors"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
