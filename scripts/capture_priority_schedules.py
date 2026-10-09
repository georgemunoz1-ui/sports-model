#!/usr/bin/env python3
"""Acquire immutable, explicitly scoped schedule evidence for priority leagues.

Does not refresh fitted state, overwrite packages, or produce a forecast. Provider
IDs are namespaced and never silently substituted for NFL/CFB/WNBA official IDs.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.recovery_capture import ROUTES, capture, save_json, digest, utc
from scripts.source_attestation import instant, retained_file

LEAGUES = ('nfl', 'cfb', 'wnba', 'nba', 'nhl')
SCOPES = {'preseason': 1, 'regular': 2, 'postseason': 3}


def requests_for(league, day, scopes):
    """Query adjacent provider dates too; resolve slate membership by local time."""
    day = dt.date.fromisoformat(day)
    specs = []
    for offset in (-1, 0, 1):
        date = day + dt.timedelta(days=offset)
        for scope in scopes:
            url = (f'https://site.api.espn.com/apis/site/v2/sports/{ROUTES[league]}/scoreboard'
                   f'?dates={date:%Y%m%d}&seasontype={SCOPES[scope]}&limit=1000')
            if league == 'cfb':
                url += '&groups=80'  # Explicit ESPN FBS group, not all college football.
            specs.append((league, 'schedule', url, 2))
    return specs


def parse_event(event, league, timezone):
    competitions = event['competitions']
    if len(competitions) != 1:
        raise ValueError('AMBIGUOUS_EVENT_COMPETITIONS')
    competition = competitions[0]
    sides = {c['homeAway']: c for c in competition['competitors']}
    if len(competition['competitors']) != 2 or set(sides) != {'home', 'away'}:
        raise ValueError('TEAM_SIDE_IDENTITY')
    season_type = event['season']['type']
    if season_type not in SCOPES.values():
        raise ValueError('SEASON_SCOPE_UNKNOWN')
    start = instant(event['date'])
    result = {'event_id': f'espn:{league}:{event["id"]}',
              'provider': 'ESPN', 'provider_event_id': str(event['id']),
              'official_event_id': None, 'canonical_model_event_id': None,
              'identity_status': 'PROVIDER_ID_ONLY_REQUIRES_MODEL_JOIN',
              'start_time_utc': start.isoformat(),
              'slate_date': start.astimezone(ZoneInfo(timezone)).date().isoformat(),
              'season': int(event['season']['year']), 'season_type': season_type,
              'season_scope': next(k for k, v in SCOPES.items() if v == season_type),
              'status': competition.get('status', event.get('status', {})).get('type', {}),
              'neutral_site': bool(competition.get('neutralSite', False))}
    for side, competitor in sides.items():
        team = competitor['team']
        if not str(team['id']).strip() or not team['displayName'].strip():
            raise ValueError('TEAM_IDENTITY_REQUIRED')
        result[side + '_provider_id'] = str(team['id'])
        result[side + '_team'] = team['displayName']
        result[side + '_provider_abbreviation'] = team.get('abbreviation')
    if result['home_provider_id'] == result['away_provider_id']:
        raise ValueError('SELF_MATCH')
    return result


def build_schedule(root, league, day, timezone, scopes, results):
    """Fail closed on partial requests, malformed payloads, and provider revisions."""
    expected = {s[2] for s in requests_for(league, day, scopes)}
    received = {r['url'] for r, _ in results}
    if received != expected or len(results) != len(expected):
        raise ValueError('REQUEST_COVERAGE_INCOMPLETE')
    by_id = {}
    excluded = set()
    for receipt, payload in results:
        if receipt.get('status') != 'CAPTURED' or not isinstance(payload, dict):
            raise ValueError('SCHEDULE_ACQUIRE_REQUIRED')
        if 'events' not in payload or not isinstance(payload['events'], list):
            raise ValueError('SCHEDULE_SHAPE_INVALID')
        # A response equal to the requested limit may be truncated.
        if len(payload['events']) >= 1000:
            raise ValueError('SCHEDULE_PAGINATION_UNVERIFIED')
        raw = retained_file(root, receipt['raw_path']).read_bytes()
        if digest(raw) != receipt['raw_sha256'] or json.loads(raw) != payload:
            raise ValueError('SOURCE_PAYLOAD_BINDING_MISMATCH')
        instant(receipt['retrieved_at_utc'])
        for source_event in payload['events']:
            event = parse_event(source_event, league, timezone)
            if event['slate_date'] != day or event['season_scope'] not in scopes:
                excluded.add(event['event_id'])
                continue
            identity = event['event_id']
            if identity in by_id and by_id[identity]['event'] != event:
                raise ValueError('PROVIDER_EVENT_REVISION:' + identity)
            entry = by_id.setdefault(identity, {'event': event, 'source_sha256': []})
            if receipt['raw_sha256'] not in entry['source_sha256']:
                entry['source_sha256'].append(receipt['raw_sha256'])
    return {'league': league, 'requested_date': day, 'timezone': timezone,
            'season_scopes': list(scopes),
            'division_scope': 'ESPN_FBS_GROUP_80' if league == 'cfb' else None,
            'schedule_status': 'PROVIDER_SCHEDULE_CAPTURED',
            'authoritative_complete_census_verified': False,
            'no_games_verified': False,
            'events': sorted(by_id.values(), key=lambda r: (r['event']['start_time_utc'], r['event']['event_id'])),
            'out_of_scope_event_ids': sorted(excluded),
            'model_input_status': 'ACQUIRE_REQUIRED',
            'required_before_forecast': ['MODEL_EVENT_AND_TEAM_ID_JOIN', 'CURRENT_REQUIRED_FEATURES',
                                         'FITTED_STATE_INPUT_BINDING', 'MODEL_SCOPE_ELIGIBILITY'],
            'market_overlay_enabled': False, 'action_authority': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True)
    parser.add_argument('--timezone', default='America/Los_Angeles')
    parser.add_argument('--leagues', nargs='+', choices=LEAGUES, default=list(LEAGUES))
    parser.add_argument('--scopes', nargs='+', choices=SCOPES, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    dt.date.fromisoformat(args.date)
    ZoneInfo(args.timezone)
    if len(set(args.leagues)) != len(args.leagues) or len(set(args.scopes)) != len(args.scopes):
        parser.error('Duplicate leagues or scopes')
    args.output.mkdir(parents=True, exist_ok=False)
    sources, leagues = [], {}
    for league in args.leagues:
        results = [capture(args.output, s) for s in requests_for(league, args.date, args.scopes)]
        sources.extend(r for r, _ in results)
        try:
            leagues[league] = build_schedule(args.output, league, args.date, args.timezone, args.scopes, results)
        except (KeyError, TypeError, ValueError) as exc:
            leagues[league] = {'schedule_status': 'SCHEDULE_UNKNOWN', 'model_input_status': 'ACQUIRE_REQUIRED',
                               'reason': str(exc), 'no_games_verified': False}
    report = {'schema': 'sports.priority_schedule_capture.v1', 'requested_date': args.date,
              'timezone': args.timezone, 'season_scopes': args.scopes,
              'created_at_utc': utc(), 'sources': sources, 'leagues': leagues,
              'source_capture_only': True, 'market_overlay_enabled': False, 'action_authority': False}
    save_json(args.output / 'report.json', report)
    save_json(args.output / 'manifest.json', {str(p.relative_to(args.output)): digest(p.read_bytes())
              for p in sorted(args.output.rglob('*')) if p.is_file()})
    print(json.dumps({'output': str(args.output), 'leagues': leagues}, indent=2))
    if any(row['schedule_status'] == 'SCHEDULE_UNKNOWN' for row in leagues.values()):
        raise SystemExit(2)


if __name__ == '__main__':
    main()
