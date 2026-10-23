"""Explicit NBA acquisition rollover bound to captured provider season metadata.

No calendar-month heuristic is used. Reacquiring a 2026 schedule in October 2026
does not make 2026-27 state current: the current scoreboard must identify 2027.
This module plans/verifies acquisition only; it neither fits nor promotes models.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from scripts.nhl_history_applicability import receipt, timestamp

BASE = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
SCHEMA = 'nba.source_bound_acquisition_scope.v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def current_season(current, cutoff):
    """Read a current provider season from exact, pre-cutoff scoreboard captures."""
    current = Path(current)
    cutoff = timestamp(cutoff) if isinstance(cutoff, str) else cutoff
    report = json.loads((current / 'report.json').read_text())
    witnesses = []
    seasons = set()
    for rec in report['sources']:
        if rec.get('league') != 'nba' or rec.get('kind') != 'schedule':
            continue
        parsed = urlparse(rec['url'])
        if parsed.scheme + '://' + parsed.netloc + parsed.path != BASE + '/scoreboard':
            raise ValueError('NBA_CURRENT_SOURCE_URL')
        data = receipt(current, rec, cutoff)
        for event in data.get('events', []):
            start = timestamp(event['date'])
            # Guard stale April or distant future events being passed as current.
            if not cutoff - dt.timedelta(days=1) <= start <= cutoff + dt.timedelta(days=8):
                continue
            season = event.get('season', {})
            year = season.get('year')
            if isinstance(year, bool) or not isinstance(year, int):
                raise ValueError('NBA_PROVIDER_SEASON_REQUIRED')
            if season.get('type') != 2 and season.get('slug') != 'regular-season':
                continue
            if year not in {cutoff.year, cutoff.year + 1}:
                raise ValueError('NBA_PROVIDER_SEASON_DATE_CONFLICT')
            seasons.add(year)
            witnesses.append({'event_id': 'NBA:' + str(event['id']), 'provider_season': year,
                              'start_time_utc': start.isoformat(), 'source_sha256': rec['raw_sha256'],
                              'retrieved_at_utc': rec['retrieved_at_utc']})
    if len(seasons) != 1:
        raise ValueError('NBA_CURRENT_SEASON_UNPROVEN_OR_CONFLICTED')
    return seasons.pop(), sorted(witnesses, key=lambda row: (row['event_id'], row['source_sha256']))


def build_scope(current, directory_root, directory_receipt, cutoff_utc):
    cutoff = timestamp(cutoff_utc)
    if directory_receipt.get('league') != 'nba' or directory_receipt.get('kind') != 'team_directory':
        raise ValueError('NBA_TEAM_DIRECTORY_REQUIRED')
    u = urlparse(directory_receipt['url'])
    if u.scheme + '://' + u.netloc + u.path != BASE + '/teams':
        raise ValueError('NBA_TEAM_DIRECTORY_URL')
    data = receipt(Path(directory_root), directory_receipt, cutoff)
    entries = data['sports'][0]['leagues'][0]['teams']
    ids = [str(entry['team']['id']) for entry in entries]
    if len(ids) != 30 or len(set(ids)) != len(ids):
        raise ValueError('NBA_TEAM_DIRECTORY_CENSUS_REVIEW_REQUIRED')
    year, witnesses = current_season(current, cutoff)
    scope = {'schema': SCHEMA, 'league': 'nba', 'first_provider_season': 2021,
             'last_provider_season': year, 'team_ids': sorted(ids), 'cutoff_utc': cutoff.isoformat(),
             'team_directory_source_sha256': directory_receipt['raw_sha256'],
             'season_witnesses': witnesses, 'historical_availability_proven': False,
             'purpose': 'ACQUISITION_REPAIR_ONLY_NO_DEFAULT_PROMOTION', 'action_authority': False}
    scope['scope_sha256'] = digest(scope)
    return scope


def load_scope(path):
    scope = json.loads(Path(path).read_text())
    identity = scope.get('scope_sha256')
    if identity != digest({k: v for k, v in scope.items() if k != 'scope_sha256'}):
        raise ValueError('NBA_SCOPE_DIGEST_MISMATCH')
    if scope.get('schema') != SCHEMA or scope.get('league') != 'nba' or scope.get('action_authority') is not False:
        raise ValueError('NBA_SCOPE_CONTRACT')
    first, last = scope['first_provider_season'], scope['last_provider_season']
    if type(first) is not int or type(last) is not int or first != 2021 or not first <= last <= timestamp(scope['cutoff_utc']).year + 1:
        raise ValueError('NBA_SCOPE_SEASON_RANGE')
    if len(set(scope['team_ids'])) != 30 or len(scope['team_ids']) != 30:
        raise ValueError('NBA_SCOPE_TEAM_CENSUS')
    return scope


def history_urls(scope):
    return {f'{BASE}/teams/{team}/schedule?season={year}&seasontype=2'
            for team in scope['team_ids']
            for year in range(scope['first_provider_season'], scope['last_provider_season'] + 1)}


def history_sources(root, report, scope, cutoff):
    if report.get('nba_acquisition_scope_sha256') != scope['scope_sha256'] or report.get('action_authority') is not False:
        raise ValueError('NBA_HISTORY_SCOPE_BINDING')
    if report.get('pending_requests', 0) != 0 or report.get('status') != 'COMPLETE':
        raise ValueError('NBA_HISTORY_CAPTURE_INCOMPLETE')
    directories = [r for r in report['sources'] if r.get('kind') == 'team_directory' and r.get('league') == 'nba']
    if len(directories) != 1 or directories[0].get('raw_sha256') != scope['team_directory_source_sha256']:
        raise ValueError('NBA_TEAM_DIRECTORY_SCOPE_BINDING')
    directory = receipt(Path(root), directories[0], cutoff)
    actual_teams = [str(x['team']['id']) for x in directory['sports'][0]['leagues'][0]['teams']]
    if sorted(actual_teams) != scope['team_ids']:
        raise ValueError('NBA_TEAM_DIRECTORY_CENSUS_MISMATCH')
    rows = [r for r in report['sources'] if r.get('kind') == 'team_season_schedule']
    urls = [r['url'] for r in rows]
    if len(set(urls)) != len(urls) or set(urls) != history_urls(scope):
        raise ValueError('NBA_HISTORY_REQUEST_CENSUS')
    for rec in rows:
        if rec.get('league') != 'nba':
            raise ValueError('NBA_HISTORY_LEAGUE')
        payload = receipt(Path(root), rec, cutoff)
        url = urlparse(rec['url'])
        team = url.path.split('/teams/')[1].split('/')[0]
        year = int(parse_qs(url.query)['season'][0])
        if str(payload.get('team', {}).get('id')) != team or payload.get('requestedSeason', {}).get('year') != year:
            raise ValueError('NBA_HISTORY_PAYLOAD_IDENTITY')
        for event in payload.get('events', []):
            if event.get('season', {}).get('year') != year:
                raise ValueError('NBA_REQUESTED_SEASON_MISMATCH')
            sides = event['competitions'][0]['competitors']
            if team not in {str(s['team']['id']) for s in sides}:
                raise ValueError('NBA_HISTORY_EVENT_TEAM_IDENTITY')
    return rows


def verify_current_events(current, event_records, cutoff):
    """Bind the actual forecast event packet to the retained current source bytes."""
    current = Path(current)
    report = json.loads((current / 'report.json').read_text())
    originals = {}
    observed_ids = set()
    for rec in report['sources']:
        if rec.get('league') != 'nba' or rec.get('kind') != 'schedule':
            continue
        data = receipt(current, rec, cutoff)
        entries = data.get('events', [])
        if len({str(e['id']) for e in entries}) != len(entries):
            raise ValueError('NBA_DUPLICATE_CURRENT_EVENT')
        originals[rec['raw_sha256']] = (rec, {str(e['id']): e for e in entries})
        observed_ids.update(str(e['id']) for e in entries)
    if not originals or set(map(str, event_records)) != observed_ids:
        raise ValueError('NBA_CURRENT_SOURCE_EVENT_COVERAGE')
    for eid, packet in event_records.items():
        rec, events = originals.get(packet.get('source_sha256'), ({}, {}))
        if events.get(str(eid)) != packet.get('event') or packet.get('retrieved_at_utc') != rec.get('retrieved_at_utc'):
            raise ValueError('NBA_CURRENT_EVENT_SOURCE_BINDING')
