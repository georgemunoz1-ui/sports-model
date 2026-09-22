#!/usr/bin/env python3
"""Prepare next-week research events from a verified published weekly state.

Schedule QB assignments are explicitly provisional. Weather and injury reports
are missing, not fabricated. The tested QB arm remains the selected default.
"""
import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from models.nfl.contextual import weekly_state as ws, base_features as bf
from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.recovered_inference import digest, utc
from models.nfl.contextual.runtime import live_features
from pipelines.cards.selection import select


def build(store, state_id, seed_id, output):
    model_path = ROOT/'data/nfl/contextual_v1/model_packed.json'
    recovered_path = ROOT/'data/nfl/contextual_v1/recovered_parameters.json'
    model = load_artifact(model_path); recovered = json.loads(recovered_path.read_text())
    cutoff = dt.datetime.now(dt.timezone.utc).isoformat()
    if os.environ.get('NFL_WEEKLY_STATE_SEED_SHA256') != seed_id:
        raise ValueError('INDEPENDENT_OPERATOR_SEED_PIN_REQUIRED')
    state = ws.load_verified(store, state_id, model, cutoff, seed_id)
    source = state['schedule_source']; receipt = source['receipt']
    age = (utc(cutoff) - utc(receipt['retrieved_at_utc'])).total_seconds()
    if not 0 <= age <= 6*3600:
        raise ValueError('CURRENT_SCHEDULE_REFRESH_REQUIRED')
    schedule = ws._schedule(source, state['season'], cutoff)
    games = schedule[schedule.week == state['completed_week']+1]
    if games.empty: raise ValueError('NO_NEXT_WEEK_SCHEDULE')
    events = []; inputs = {}
    for row in games.to_dict('records'):
        start = dt.datetime.fromisoformat(row['gameday']+'T'+row['gametime']).replace(tzinfo=ZoneInfo('America/New_York')).astimezone(dt.timezone.utc)
        if utc(cutoff) >= start: raise ValueError('NEXT_WEEK_ALREADY_STARTED')
        event = {'event_id': row['game_id'], 'home_team': row['home_team'], 'away_team': row['away_team'],
                 'gameday': row['gameday'], 'gametime': row['gametime'], 'location': row['location'],
                 'start_time_utc': start.isoformat()}
        # Future realized weather/scores must never enter even if a provider fills them.
        row.update(home_score=None, away_score=None, temp=None, wind=None)
        import pandas as pd
        base = bf._feature_row(pd.Series(row), bf.TeamState(**state['team_state'][row['home_team']]),
                              bf.TeamState(**state['team_state'][row['away_team']]))
        base = {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k,v in base.items()}
        shared = {'source': receipt['source_url'], 'source_sha256': receipt['sha256'],
                  'retrieved_at_utc': receipt['retrieved_at_utc'], 'available_by_utc': receipt['retrieved_at_utc'],
                  'event_id': row['game_id']}
        qbs = {}
        for side in ('home', 'away'):
            q = row.get(side+'_qb_id')
            qbs[row[side+'_team']] = {'id': q if isinstance(q,str) else None,
                'game_status': 'UNKNOWN', 'confirmation': 'SCHEDULE_ASSIGNMENT_ONLY_NOT_CONFIRMED_ACTIVE'}
        context = {'weekly_state': {'store': str(store.resolve()), 'state_id': state_id},
                   'personnel': {**shared, 'state': {'quarterbacks': qbs,
                       'report_status': 'NOT_ACQUIRED', 'final_inactives': 'PENDING'}}}
        if all(isinstance(row.get(s+'_rest'), (int,float)) and math.isfinite(row[s+'_rest']) for s in ('home','away')):
            context['rest'] = {**shared, 'home_rest': row['home_rest'], 'away_rest': row['away_rest'],
                               'definition': 'Nflverse schedule rest days, captured before kickoff'}
        packet = ws.bind_packet({'base': base, 'context': context}, model, event, cutoff, store, state_id)
        live_features(model, recovered, packet['base'], packet['context'], event, cutoff)
        events.append(event); inputs[event['event_id']] = packet
    package = {'schema': 'nfl.event_package.v1', 'captured_at_utc': cutoff,
        'covered_dates': sorted({e['gameday'] for e in events}), 'events': events, 'event_inputs': inputs,
        'model_path': os.path.relpath(model_path, output.parent), 'model_digest': digest(model),
        'recovered_parameters_path': os.path.relpath(recovered_path, output.parent),
        'selected_model_id': select('nfl')['default_model_id'], 'research_only': True,
        'action_authority': False, 'scope': 'NEXT_WEEK_SCHEDULE_WITH_VERIFIED_WEEKLY_STATE',
        'limitations': ['SCHEDULE_QBS_UNCONFIRMED', 'INJURY_REPORTS_NOT_ACQUIRED', 'WEATHER_NOT_ACQUIRED', 'FINAL_INACTIVES_PENDING'],
        'source_fetches': [{'source': receipt['source_url'], 'sha256': receipt['sha256'], 'fetched_at_utc': receipt['retrieved_at_utc']}]}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as f: json.dump(package, f, indent=2, allow_nan=False)
    return package


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--store', required=True, type=Path); p.add_argument('--state-id', required=True)
    p.add_argument('--seed-id', required=True); p.add_argument('--output', required=True, type=Path)
    a = p.parse_args(); package = build(a.store, a.state_id, a.seed_id, a.output)
    print(json.dumps({'events': len(package['events']), 'selected_model_id': package['selected_model_id'], 'limitations': package['limitations']}))


if __name__ == '__main__': main()
