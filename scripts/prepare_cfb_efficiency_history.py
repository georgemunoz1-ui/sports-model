#!/usr/bin/env python3
"""Prepare source-reconciled CFB efficiency history without altering input bytes."""
import argparse
import datetime as dt
import hashlib
import json
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from models.experiments.cfb_efficiency import aggregate_pbp, canonical_game, clean, utc


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)


def within(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('SOURCE_PATH_OUTSIDE_CAPTURE')
    return path


def prepare(source_dir, schedule_dir, output_dir, asof):
    if output_dir.exists():
        raise FileExistsError('IMMUTABLE_OUTPUT_DIRECTORY_EXISTS')
    cutoff = utc(asof)
    capture = json.loads((source_dir / 'report.json').read_text())
    raw = [r for r in capture['sources'] if r.get('league') == 'cfb' and r.get('dataset') == 'classic_epa_pbp' and r.get('status') == 'CAPTURED']
    if not raw:
        raise ValueError('CFB_PLAY_SOURCES_REQUIRED')
    source_by_path = {str(within(source_dir, r['path'])): {
        'source': r['url'], 'sha256': r['sha256'], 'retrieved_at_utc': r['retrieved_at_utc'],
        'historical_observation_proof': False} for r in raw}
    schedule_capture = json.loads((schedule_dir / 'report.json').read_text())
    schedule_sources, frames = [], []
    for row in schedule_capture['binary_sources']:
        if row.get('status') != 'CAPTURED' or not row['path'].endswith('.parquet'):
            continue
        path = within(schedule_dir, row['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('CFB_SCHEDULE_HASH_MISMATCH:' + row['path'])
        frames.append(pd.read_parquet(path))
        schedule_sources.append({'source': row['url'], 'sha256': row['sha256'],
                                 'retrieved_at_utc': row['retrieved_at_utc']})
    if not frames:
        raise ValueError('CFB_SCHEDULE_SOURCES_REQUIRED')
    frame = pd.concat(frames, ignore_index=True)
    frame['kick'] = pd.to_datetime(frame.start_date, utc=True, format='mixed')
    final = frame.completed & frame.home_points.notna() & frame.away_points.notna() & (frame.kick < cutoff)
    pending = (~frame.completed) & (frame.kick > cutoff) & (frame.kick < cutoff + pd.Timedelta(days=7))
    frame = frame[final | pending].sort_values(['kick', 'game_id'])
    games = [canonical_game(clean(row)) for row in frame.drop(columns='kick').to_dict('records')]
    if len({g['event_id'] for g in games}) != len(games):
        raise ValueError('DUPLICATE_SCHEDULE_EVENT')
    aggregated = aggregate_pbp(list(source_by_path), games, source_by_path)
    history = {'schema': 'cfb-matchup-efficiency-history-v1', 'games': games,
               'team_games': aggregated.pop('team_games'), 'schedule_sources': schedule_sources,
               'limitations': aggregated['limitations'], 'evidence_scope': aggregated['evidence_scope']}
    output_dir.mkdir(parents=True, exist_ok=False)
    write(output_dir / 'history.json', history)
    aggregated.update(schema='cfb-efficiency-preparation-receipt-v1',
                      created_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                      asof_utc=cutoff.isoformat(), schedule_games=len(games),
                      history_sha256=hashlib.sha256((output_dir / 'history.json').read_bytes()).hexdigest(),
                      source_capture_sha256=hashlib.sha256((source_dir / 'report.json').read_bytes()).hexdigest(),
                      schedule_capture_sha256=hashlib.sha256((schedule_dir / 'report.json').read_bytes()).hexdigest(),
                      code_sha256={p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in
                                   ['models/experiments/cfb_efficiency.py', 'scripts/prepare_cfb_efficiency_history.py']},
                      source_bindings=list(source_by_path.values()) + schedule_sources, action_authority=False)
    write(output_dir / 'preparation_receipt.json', aggregated)
    write(output_dir / 'manifest.json', {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output_dir.iterdir())})
    return {'output_dir': str(output_dir), 'history_sha256': aggregated['history_sha256'],
            'schedule_games': len(games), 'matched_events': aggregated['matched_events'],
            'incident_counts': dict(Counter(r['reason'] for r in aggregated['incidents'])),
            'exact_duplicate_rows_collapsed': sum(r['removed_rows'] for r in aggregated['normalizations'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--schedule-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--as-of-utc', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source_dir, args.schedule_dir, args.output_dir, args.as_of_utc), sort_keys=True))
