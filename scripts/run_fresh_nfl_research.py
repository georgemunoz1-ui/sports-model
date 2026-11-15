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


def _adapter_row_from_trace(trace, sources, recorded_dir):
    """Independently project the frozen NFL adapter contract for exact display verification."""
    from models.nfl.contextual.recovered_inference import digest

    event = trace['event']
    home_p = trace['prediction']['home_win']
    home_leads = home_p >= 0.5
    sim_home = trace['winner_simulation']['home_win_probability']
    analytic = home_p if home_leads else 1 - home_p
    simulated = sim_home if home_leads else 1 - sim_home
    joint = trace['joint_distribution']
    margin = joint['mean_margin'] if joint else None
    return {
        'model_id': trace['model_id'], 'coverage_label': trace['coverage_label'],
        'model_winner': event['home_team'] if home_leads else event['away_team'],
        'model_p': analytic, 'sim_p': simulated, 'analytic_p': analytic, 'stochastic_sim_p': simulated,
        'projected_margin': -margin if margin is not None and not home_leads else margin,
        'projected_total': joint['mean_total'] if joint else None,
        'projected_home_points': joint['mean_home_score'] if joint else None,
        'projected_away_points': joint['mean_away_score'] if joint else None,
        'forecast_tier': 'REDUCED', 'data_quality': 'PARTIAL_CURRENT_CONTEXT_APPLIED',
        'diagnostics': trace, 'model_input_snapshot': trace['features'],
        'input_snapshot_hash': digest(trace['features']), 'model_state_config_hash': trace['model_artifact_sha256'],
        'simulation': {'binary': trace['winner_simulation'], 'joint_scores': trace['score_simulation'],
                       'draw_directory': str(recorded_dir)},
        'warnings': trace['warnings'], 'provenance': {'source_fetches': sources, 'model_id': trace['model_id']},
    }


def verify_inference_traces(card, selected, package, state_id, output, *, recorded_output=None):
    """Read back frozen files and reproduce exactly the rows displayed by this runner."""
    import numpy as np
    from models.nfl.contextual.model import load_artifact
    from models.nfl.contextual.recovered_inference import digest, utc as timestamp
    from pipelines.cards.nfl_flip_integration import attach_diagnostic
    from pipelines.cards.selected import apply_default
    from scripts.generate_card_force import attach_grading, normalize
    from sports.rosters import attach

    output = Path(output).resolve()
    # Relocation affects only the spelling of the captured display path, never where we read.
    recorded_output = output if recorded_output is None else Path(recorded_output)
    if not recorded_output.is_absolute():
        raise ValueError('ABSOLUTE_RECORDED_OUTPUT_REQUIRED')
    rows = card['forecasts']
    events = {event['event_id']: event for event in selected}
    if (not rows or card.get('incidents') or len(rows) != len(selected)
            or len(events) != len(selected) or {row['event_id'] for row in rows} != set(events)
            or any(row.get('forecast_status') != 'FORECAST_GENERATED' for row in rows)):
        raise ValueError('FRESH_INFERENCE_COVERAGE_INCOMPLETE')
    model = load_artifact(output / package['model_path'])
    if digest(model) != package['model_digest']:
        raise ValueError('FROZEN_MODEL_CONSUMPTION_UNVERIFIED')

    traces = []
    expected_rows = []
    for row in rows:
        event = events[row['event_id']]
        relative_dir = Path('draws') / event['event_id'].replace(':', '_')
        draw_dir = (output / relative_dir).resolve()
        recorded_dir = recorded_output / relative_dir
        if (not draw_dir.is_relative_to(output / 'draws') or
                row['simulation'].get('draw_directory') != str(recorded_dir)):
            raise ValueError('RETAINED_INFERENCE_TRACE_REQUIRED')
        manifest_path = retained_file(draw_dir, 'manifest.json')
        files = json.loads(manifest_path.read_text())
        if 'forecast.json' not in files or 'winner_draws.npy' not in files:
            raise ValueError('RETAINED_DRAW_FILES_REQUIRED')
        for relative, expected_hash in files.items():
            if hashlib.sha256(retained_file(draw_dir, relative).read_bytes()).hexdigest() != expected_hash:
                raise ValueError('INFERENCE_TRACE_DIGEST_MISMATCH')
        retained = json.loads((draw_dir / 'forecast.json').read_text())
        if retained['model_id'] != package['selected_model_id']:
            raise ValueError('SELECTED_MODEL_IDENTITY_MISMATCH')
        if retained['model_artifact_sha256'] != package['model_digest']:
            raise ValueError('FROZEN_MODEL_CONSUMPTION_UNVERIFIED')
        if (digest(retained['event']) != digest(event) or retained['cutoff_utc'] != card['as_of_utc']
                or not timestamp(card['as_of_utc']) <= timestamp(card['generated_at_utc']) < timestamp(event['start_time_utc'])):
            raise ValueError('INFERENCE_TRACE_EVENT_OR_CUTOFF_MISMATCH')
        if (retained.get('assimilation') or {}).get('state_id') != state_id:
            raise ValueError('WEEKLY_STATE_CONSUMPTION_UNVERIFIED')
        features = retained.get('features')
        if not isinstance(features, dict) or not features:
            raise ValueError('INFERENCE_FEATURES_REQUIRED')
        sim = retained['winner_simulation']
        draws = np.load(draw_dir / 'winner_draws.npy', allow_pickle=False)
        if (not draws.size or draws.shape != (card['simulation_count'],)
                or sim['count'] != draws.size or hashlib.sha256(draws.tobytes()).hexdigest() != sim['sha256']
                or not np.isin(draws, (0, 1)).all() or float(draws.mean()) != sim['home_win_probability']):
            raise ValueError('INFERENCE_WINNER_DRAW_MISMATCH')

        # The adapter persists the numerical result before selection and presentation.
        # Rebuild both layers from it; never trust or strip fields from the display.
        if {'default_selection', 'arm_feature_references', 'flip_diagnostics'}.intersection(retained):
            raise ValueError('INFERENCE_TRACE_CONTAINS_CARD_METADATA')
        raw = _adapter_row_from_trace(retained, package['source_fetches'], recorded_dir)
        raw = apply_default('nfl', event, raw)
        raw['diagnostics'] = attach_diagnostic(raw['diagnostics'], model)
        expected_rows.append(normalize(event, attach(raw, 'nfl', event, card['as_of_utc'])))
        traces.append({'event_id': event['event_id'], 'model_id': retained['model_id'],
                       'input_snapshot_hash': digest(features),
                       'model_state_config_hash': retained['model_artifact_sha256'],
                       'draw_manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                       'forecast_file_sha256': files['forecast.json'],
                       'display_row_sha256': digest(row)})

    projected = attach_grading({**card, 'forecasts': expected_rows})
    if digest(projected['forecasts']) != digest(rows):
        raise ValueError('INFERENCE_TRACE_CARD_MISMATCH')
    return traces


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
        traces = verify_inference_traces(card, selected, package, state_id, output)
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
