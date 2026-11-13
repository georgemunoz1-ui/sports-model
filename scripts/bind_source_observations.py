#!/usr/bin/env python3
"""Bind retained quote/personnel bytes to typed observations; no network or forecast."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.source_capture_contracts import bind_manifest
from scripts.recovery_capture import save_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture-root', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    raw = args.manifest.read_bytes()
    report = bind_manifest(args.capture_root, json.loads(raw))
    report['input_manifest_sha256'] = hashlib.sha256(raw).hexdigest()
    report['parser_sha256'] = hashlib.sha256((ROOT / 'research/source_capture_contracts.py').read_bytes()).hexdigest()
    args.output.mkdir(parents=True, exist_ok=False)
    save_json(args.output / 'observations.json', report)
    save_json(args.output / 'manifest.json', {'observations.json': hashlib.sha256((args.output / 'observations.json').read_bytes()).hexdigest()})
    print(json.dumps({'observations': len(report['observations']), 'model_usage': 'NOT_USED', 'action_authority': False}))


if __name__ == '__main__':
    main()
