#!/usr/bin/env python3
"""Prepare a new NFL package from verified state, then run frozen default inference.

No acquisition, fitting, default change, registration, publication, or betting.
Requires already captured raw schedule bytes and independently pinned weekly state.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.source_attestation import attest_sources, retained_file
from scripts.recovery_capture import save_json, utc


def run(store, state_id, seed_id, source_bundles, date, output, simulations=100000):
    from scripts.prepare_nfl_weekly_events import build
    from scripts.generate_card_force import generate
    if not 1 <= simulations <= 1000000:
        raise ValueError('DRAW_COUNT_RANGE')
    # The seed must already be pinned independently; never set it from the input.
    if os.environ.get('NFL_WEEKLY_STATE_SEED_SHA256') != seed_id:
        raise ValueError('INDEPENDENT_OPERATOR_SEED_PIN_REQUIRED')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'nfl.fresh_frozen_inference.v1', 'requested_date': date,
              'date_basis': 'NFL_PACKAGE_GAMEDAY_AMERICA_NEW_YORK',
              'state_id': state_id, 'seed_id': seed_id,
              'forecast_consumption_verified': False, 'model_refitted': False,
              'defaults_changed': False, 'market_overlay_enabled': False,
              'action_authority': False, 'status': 'BLOCKED'}
    try:
        package_path = output / 'event_package.json'
        package = build(Path(store), state_id, seed_id, package_path)
        if date not in package['covered_dates']:
            raise ValueError('REQUESTED_DATE_NOT_IN_VERIFIED_WEEKLY_PACKAGE')
        selected = [e for e in package['events'] if e['gameday'] == date]
        if not selected:
            raise ValueError('EMPTY_PACKAGE_DATE_NOT_AUTHORITATIVE_ZERO_GAME_PROOF')
        cutoff = utc()
        attestation = attest_sources(package['source_fetches'], source_bundles, cutoff)
        package_hash = hashlib.sha256(package_path.read_bytes()).hexdigest()
        report['package_sha256'] = package_hash
        report['source_attestation'] = attestation
        # Explicit environment binding avoids the archived/default package path.
        with patch.dict(os.environ, {'NFL_CONTEXT_PACKAGE': str(package_path),
                                    'SPORTS_RESEARCH_DRAW_OUTPUT': str(output / 'draws'),
                                    'SPORTS_SOURCE_BUNDLES': json.dumps([str(Path(p).resolve()) for p in source_bundles])}):
            card = generate(date, 'nfl', cutoff, simulations, None)
        if hashlib.sha256(package_path.read_bytes()).hexdigest() != package_hash:
            raise ValueError('PACKAGE_CHANGED_DURING_INFERENCE')
        save_json(output / 'diagnostic_card.json', card)
        rows = [r for r in card['forecasts'] if r.get('forecast_status') == 'FORECAST_GENERATED']
        if card.get('incidents') or {r['event_id'] for r in rows} != {e['event_id'] for e in selected}:
            raise ValueError('FRESH_INFERENCE_COVERAGE_INCOMPLETE')
        traces = []
        for row in rows:
            if row.get('model_id') != package['selected_model_id']:
                raise ValueError('SELECTED_MODEL_IDENTITY_MISMATCH')
            draw_dir = Path(row['simulation']['draw_directory']).resolve()
            if not draw_dir.is_relative_to(output) or not (draw_dir / 'manifest.json').is_file():
                raise ValueError('RETAINED_INFERENCE_TRACE_REQUIRED')
            if not row.get('input_snapshot_hash') or not row.get('model_state_config_hash'):
                raise ValueError('INFERENCE_BINDING_REQUIRED')
            diagnostics = row.get('diagnostics') or {}
            features = diagnostics.get('features')
            if not isinstance(features, dict) or not features:
                raise ValueError('INFERENCE_FEATURES_REQUIRED')
            feature_hash = hashlib.sha256(json.dumps(features, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            if row['input_snapshot_hash'] != feature_hash or row.get('model_input_snapshot') != features:
                raise ValueError('INFERENCE_FEATURE_DIGEST_MISMATCH')
            if (diagnostics.get('assimilation') or {}).get('state_id') != state_id:
                raise ValueError('WEEKLY_STATE_CONSUMPTION_UNVERIFIED')
            if row['model_state_config_hash'] != package['model_digest']:
                raise ValueError('FROZEN_MODEL_CONSUMPTION_UNVERIFIED')
            files = json.loads((draw_dir / 'manifest.json').read_text())
            if 'forecast.json' not in files or 'winner_draws.npy' not in files:
                raise ValueError('RETAINED_DRAW_FILES_REQUIRED')
            for relative, expected_hash in files.items():
                if hashlib.sha256(retained_file(draw_dir, relative).read_bytes()).hexdigest() != expected_hash:
                    raise ValueError('INFERENCE_TRACE_DIGEST_MISMATCH')
            retained = json.loads((draw_dir / 'forecast.json').read_text())
            if retained != diagnostics:
                raise ValueError('INFERENCE_TRACE_CARD_MISMATCH')
            traces.append({'event_id': row['event_id'], 'model_id': row['model_id'],
                           'input_snapshot_hash': row['input_snapshot_hash'],
                           'model_state_config_hash': row['model_state_config_hash'],
                           'draw_manifest_sha256': hashlib.sha256((draw_dir / 'manifest.json').read_bytes()).hexdigest()})
        report.update(status='FRESH_RESEARCH_INFERENCE_GENERATED',
                      forecast_consumption_verified=True, inference_traces=traces,
                      card_sha256=hashlib.sha256((output / 'diagnostic_card.json').read_bytes()).hexdigest())
    except Exception as exc:
        report.update(error_type=type(exc).__name__, reason=str(exc))
    save_json(output / 'fresh_run_receipt.json', report)
    save_json(output / 'manifest.json', {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(output.rglob('*')) if p.is_file()})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--state-id', required=True)
    parser.add_argument('--seed-id', required=True)
    parser.add_argument('--source-bundles', type=Path, nargs='+', required=True)
    parser.add_argument('--date', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--simulations', type=int, default=100000)
    args = parser.parse_args()
    report = run(args.store, args.state_id, args.seed_id, args.source_bundles, args.date, args.output, args.simulations)
    print(json.dumps(report, indent=2))
    return 0 if report['forecast_consumption_verified'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
