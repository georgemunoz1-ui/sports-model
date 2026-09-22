#!/usr/bin/env python3
"""Replay fresh captured NFL bytes into an isolated store and retain refusal evidence.

Success means weekly state validation, not a forecast, model promotion or release.
Neither source conflicts nor missing evidence are silently corrected here.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from models.nfl.contextual import weekly_state as ws
from models.nfl.contextual.model import load_artifact
from scripts.verify_nfl_weekly_sources import manifest


def starter_conflicts(schedule_path, pbp_path, season, week):
    games = pd.read_csv(schedule_path, low_memory=False)
    raw = pd.read_csv(pbp_path, low_memory=False)
    games = games[(games.season == season) & (games.game_type == 'REG') & (games.week == week)]
    d = raw[(raw.season_type == 'REG') & (raw.qb_dropback == 1)
            & (raw.qb_kneel != 1) & (raw.qb_spike != 1)
            & raw.epa.notna() & raw.passer_player_id.notna()]
    conflicts = []
    for game in games.to_dict('records'):
        for side in ('home', 'away'):
            team = game[side + '_team']
            observed = d[(d.game_id == game['game_id']) & (d.posteam == team)]
            q = game[side + '_qb_id']
            if q not in set(observed.passer_player_id):
                conflicts.append({'game_id': game['game_id'], 'team': team,
                    'schedule_qb_id': q if isinstance(q, str) else None,
                    'qualifying_pbp_passer_ids': sorted(set(observed.passer_player_id)),
                    'disposition': 'RECONCILE_SOURCE_CONFLICT; NO_AUTOMATIC_SUBSTITUTION'})
    return conflicts


def validate(frozen, capture, output, target_week, adjudications=None):
    output.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'nfl.current_weekly_acceptance.v1', 'target_completed_week': target_week,
              'forecast_consumption_verified': False, 'action_authority': False,
              'production_promotion': False, 'code': ws.code_identity()}
    try:
        report['frozen_manifest_entries'] = manifest(frozen, 'completed_manifest.json')
        report['capture_manifest_entries'] = manifest(capture, 'manifest.json')
        receipts = {r['filename']: r for r in json.loads((capture/'nfl/receipt.json').read_text())}
        seed_data = json.loads((frozen/'historical_state.json').read_text())
        season = seed_data['season']
        schedule_path = capture/'nfl/games.csv'
        pbp_path = capture/f'nfl/play_by_play_{season}.csv'
        schedule = ws.capture(schedule_path, receipts['games.csv'])
        pbp = ws.capture(pbp_path, receipts[pbp_path.name])
        report['source_sha256'] = {'schedule': schedule['receipt']['sha256'], 'pbp': pbp['receipt']['sha256']}
        model = load_artifact(ROOT/'data/nfl/contextual_v1/model_packed.json')
        cutoff = dt.datetime.now(dt.timezone.utc).isoformat()
        report['cutoff_utc'] = cutoff
        store = output/'state'
        seed = ws.initialize(store, seed_data, schedule, model, cutoff, starter_adjudications=adjudications)
        report['starter_adjudication_count'] = len(adjudications or [])
        report['seed_id'] = seed
        parent = seed
        report['transitions'] = []
        for week in range(1, target_week + 1):
            before_head = (store/'HEAD').read_bytes()
            before_objects = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (store/'objects').iterdir()}
            try:
                key = ws.advance(store, parent, seed, model, schedule, pbp, week, cutoff)
            except ValueError as exc:
                report.update(status='REFUSED', failed_week=week, refusal=str(exc),
                    head_preserved=(store/'HEAD').read_bytes() == before_head,
                    objects_preserved=before_objects == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (store/'objects').iterdir()},
                    starter_conflicts=starter_conflicts(schedule_path, pbp_path, season, week))
                if not report['head_preserved'] or not report['objects_preserved']:
                    raise AssertionError('REJECTED_UPDATE_MUTATED_STORE')
                break
            state = ws.load_verified(store, key, model, cutoff, seed)
            assert ws.advance(store, parent, seed, model, schedule, pbp, week, cutoff) == key
            report['transitions'].append({'completed_week': week, 'state_id': key,
                'consumed_game_count': len(state['consumed_game_ids']), 'replay_verified': True,
                'identical_retry_verified': True})
            parent = key
        else:
            report['status'] = 'WEEKLY_STATE_VERIFIED'
        report['published_state_id'] = (store/'HEAD').read_text().strip()
    except Exception as exc:
        report.update(status='ERROR', error_type=type(exc).__name__, error=str(exc))
    (output/'acceptance.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frozen', type=Path, required=True)
    p.add_argument('--capture', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--through-week', type=int, required=True)
    p.add_argument('--starter-adjudications', type=Path)
    a = p.parse_args()
    if not 1 <= a.through_week <= 18:
        p.error('through-week must be 1..18')
    report = validate(a.frozen, a.capture, a.output, a.through_week,
                      json.loads(a.starter_adjudications.read_text()) if a.starter_adjudications else None)
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'WEEKLY_STATE_VERIFIED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
