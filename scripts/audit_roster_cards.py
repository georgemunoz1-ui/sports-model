#!/usr/bin/env python3
"""Review roster coverage for preserved cards without regenerating predictions."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_rosters import write_once
from sports.rosters import assess, load_bundle, league_counts


def audit(bundle_path, card_paths, cutoff):
    bundle = load_bundle(bundle_path)
    rows = []
    seen = set()
    for path in card_paths:
        raw = Path(path).read_bytes()
        card = json.loads(raw)
        sport = card['league'].lower()
        for event in card['forecasts']:
            key = (sport, str(event['event_id']), event.get('model_id'))
            if key in seen:
                raise ValueError('ROSTER_DUPLICATE_CARD_EVENT_MODEL')
            seen.add(key)
            original_cutoff = card.get('requested_as_of_utc') or card['as_of_utc']
            current = assess(sport, event, cutoff, bundle)
            original = assess(sport, event, original_cutoff, bundle)
            rows.append({'sport': sport, 'event_id': event['event_id'], 'model_id': event.get('model_id'),
                         'home_team': event['home_team'], 'away_team': event['away_team'],
                         'original_card_sha256': hashlib.sha256(raw).hexdigest(),
                         'original_forecast_cutoff_utc': original_cutoff,
                         'original_cutoff_assessment': original, 'current_assessment': current,
                         'forecast_changed': False, 'retrospective_roster_use_allowed': False})
    return {'schema': 'sports.roster_card_audit.v1', 'reviewed_at_utc': cutoff,
            'bundle_sha256': bundle['bundle_sha256'], 'sports': {sport: {
                'scope': league.get('scope'), 'counts': league_counts(league),
                'membership_conflicts': league['membership_conflicts'],
                'full_roster_impact_fitted': False} for sport, league in bundle['sports'].items()},
            'events': rows, 'new_forecasts_generated': 0, 'action_authority': False,
            'status_axes': {'EXECUTION_STATUS': 'COMPLETED', 'PREDICTIVE_VALIDATION': 'NOT_ASSESSED',
                            'PUBLICATION_ELIGIBILITY': 'INELIGIBLE', 'WAGERING_AUTHORITY': 'OFF'}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--card', type=Path, action='append', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    report = audit(a.bundle, a.card, datetime.now(timezone.utc).isoformat())
    write_once(a.output, report)
    print(json.dumps({'output': str(a.output), 'events': len(report['events']), 'sports': report['sports']}, indent=2))


if __name__ == '__main__':
    main()
