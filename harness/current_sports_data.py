"""Current-slate clock, source receipts, and honest per-league readiness.

No HTTP or model fitting. Acquisition supplies captured evidence; this module
keeps source availability, event time, retrieval time and model freshness apart.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

MODULE_ID = "current_sports_data"
MODULE_VERSION = "1.0.0"

LEAGUES = ('mlb', 'wnba', 'nfl', 'cfb', 'mls', 'nba', 'nhl')
UTC = dt.timezone.utc
DEFAULT_TIMEZONE = 'America/Los_Angeles'


def runtime_readiness(root, as_of=None):
    """Inspect the explicit current snapshot; never infer freshness from mtime."""
    root = Path(root).resolve()
    pointer = root / 'data/current/runtime.json'
    if not pointer.exists():
        return {'status': 'UNACQUIRED', 'leagues': {l:'UNACQUIRED' for l in LEAGUES}}
    config = json.loads(pointer.read_text())
    path = (root / config['status_path']).resolve()
    if not path.is_relative_to(root):
        raise ValueError('STATUS_OUTSIDE_REPOSITORY')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != config['status_sha256']:
        raise ValueError('CURRENT_STATUS_DIGEST_MISMATCH')
    report = json.loads(data)
    now = slate_clock(as_of, timezone=report['clock']['slate_timezone'])
    age = (instant(now['as_of_utc']) - instant(report['clock']['as_of_utc'])).total_seconds()
    if report['clock']['slate_date'] != now['slate_date'] or not 0 <= age <= config.get('ttl_hours', 6)*3600:
        return {'status':'STALE_SNAPSHOT', 'leagues':{l:'STALE_SNAPSHOT' for l in LEAGUES}}
    rows = {r['league']: r for r in report['leagues']}
    ready = len(rows) == len(LEAGUES) and all(r['forecast_ready'] for r in rows.values())
    return {'status':'CURRENT' if ready else 'PARTIAL',
            'leagues':{l:(rows[l]['schedule_status'] + ' / ' + rows[l]['feature_status']) if l in rows else 'UNACQUIRED' for l in LEAGUES}}


def instant(value):
    result = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('TIMESTAMP_REQUIRES_TIMEZONE')
    return result.astimezone(UTC)


def slate_clock(as_of=None, slate_date=None, timezone=DEFAULT_TIMEZONE, historical=False):
    now = instant(as_of) if as_of else dt.datetime.now(UTC)
    zone = ZoneInfo(timezone)
    today = now.astimezone(zone).date()
    day = dt.date.fromisoformat(slate_date) if slate_date else today
    if day < today and not historical:
        raise ValueError('PAST_SLATE_REQUIRES_EXPLICIT_HISTORICAL_MODE')
    start = dt.datetime.combine(day, dt.time(), zone)
    end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), zone)
    return {'as_of_utc': now.isoformat(), 'slate_date': day.isoformat(),
            'slate_timezone': timezone, 'window_start_utc': start.astimezone(UTC).isoformat(),
            'window_end_utc': end.astimezone(UTC).isoformat(),
            'information_regime': 'historical_reconstruction' if historical else 'current'}


def local_date(timestamp, timezone=DEFAULT_TIMEZONE):
    return instant(timestamp).astimezone(ZoneInfo(timezone)).date().isoformat()


def receipt(path, source, retrieved_at, source_available_at=None, representation='tool_extract'):
    data = Path(path).read_bytes()
    retrieved = instant(retrieved_at)
    if source_available_at and instant(source_available_at) > retrieved:
        raise ValueError('SOURCE_AVAILABLE_AFTER_RETRIEVAL')
    return {'path': str(path), 'source': source, 'sha256': hashlib.sha256(data).hexdigest(),
            'bytes': len(data), 'retrieved_at': retrieved.isoformat(),
            'source_available_at': source_available_at, 'representation': representation}


def available_before(record, cutoff):
    """Conservative knowledge time: unknown publication time uses first capture."""
    known = record.get('source_available_at') or record['retrieved_at']
    return instant(known) <= instant(cutoff)


def immutable_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(obj, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('IMMUTABLE_ARTIFACT_ALREADY_EXISTS')
    else:
        with path.open('xb') as f:
            f.write(data)
    return hashlib.sha256(data).hexdigest()


_GAME = re.compile(r'(?P<away>.+?) @ (?P<home>.+?) on (?P<date>\w+, \w+ \d+, \d{4}) at (?P<time>\d+:\d+ [AP]M) (?P<zone>PDT|PST)(?:\. Final score: (?P<a_ab>\w+) (?P<a_score>\d+) - (?P<h_ab>\w+) (?P<h_score>\d+))?$')


def parse_sports_extract(text, league, source_receipt):
    """Strict tool-extract parser. Derived IDs never masquerade as provider IDs.

    Include tip/pitch time in the key so doubleheaders cannot collapse. Pending
    games retain null scores. All unparsed records raise instead of disappearing.
    """
    if league not in LEAGUES:
        raise ValueError('UNKNOWN_LEAGUE')
    text = re.sub(r'\ue200cite\ue202.*?\ue201', '', text)
    events = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _GAME.fullmatch(line.strip())
        if not m:
            raise ValueError('UNPARSED_SCHEDULE_RECORD: ' + line[:100])
        v = m.groupdict()
        start = dt.datetime.strptime(v['date'] + ' ' + v['time'], '%A, %b %d, %Y %I:%M %p').replace(tzinfo=ZoneInfo(DEFAULT_TIMEZONE))
        if start.tzname() != v['zone']:
            raise ValueError('SCHEDULE_TIMEZONE_OFFSET_MISMATCH')
        score = v['a_score'] is not None
        if score and start.astimezone(UTC) > instant(source_receipt['retrieved_at']):
            raise ValueError('FUTURE_GAME_HAS_FINAL_SCORE')
        names = {side: re.sub(r' \(\w+\)$', '', v[side]) for side in ('away', 'home')}
        for side, short in [('away', 'a_ab'), ('home', 'h_ab')]:
            code = re.search(r'\((\w+)\)$', v[side])
            if code and code[1] != v[short]:
                raise ValueError('FINAL_SCORE_TEAM_BINDING_MISMATCH')
        key = '|'.join((league, start.isoformat(), names['away'], names['home']))
        events.append({'event_id': 'derived:' + hashlib.sha256(key.encode()).hexdigest()[:24],
                       'provider_event_id': None, 'league': league, **names,
                       'away_code': v['a_ab'], 'home_code': v['h_ab'],
                       'start_utc': start.astimezone(UTC).isoformat(),
                       'slate_date': start.date().isoformat(), 'date_timezone': DEFAULT_TIMEZONE,
                       'status': 'final' if score else 'scheduled',
                       'away_score': int(v['a_score']) if score else None,
                       'home_score': int(v['h_score']) if score else None,
                       'source_sha256': source_receipt['sha256'],
                       'retrieved_at': source_receipt['retrieved_at'],
                       'source_available_at': None, 'historical_pregame_eligible': False})
    return events


def reconcile(events):
    by_id, conflicts = {}, []
    for event in events:
        key = event['event_id']
        previous = by_id.get(key)
        if previous:
            fields = ('away', 'home', 'start_utc', 'status', 'away_score', 'home_score')
            if any(previous.get(k) != event.get(k) for k in fields):
                conflicts.append({'event_id': key, 'earlier': previous, 'later': event})
                continue
        by_id[key] = event
    return list(by_id.values()), conflicts


def league_status(league, clock, events, coverage, features):
    """A current source capture alone cannot make a forecast ready.

    Coverage must explicitly attest the requested slate/window. Empty pages,
    source errors and missing acquisition never imply zero scheduled games.
    """
    own = [e for e in events if e['league'] == league]
    today = [e for e in own if e['slate_date'] == clock['slate_date']]
    finals = [e for e in own if e['status'] == 'final']
    valid_receipt = coverage.get('source_sha256') and coverage.get('verified_at')
    if valid_receipt:
        age = (instant(clock['as_of_utc']) - instant(coverage['verified_at'])).total_seconds()
        valid_receipt = 0 <= age <= coverage.get('ttl_hours', 24) * 3600
    window_ok = (coverage.get('date_from', '9999') <= clock['slate_date'] <= coverage.get('date_to', '0000'))
    known = bool(valid_receipt and window_ok and coverage.get('complete'))
    expected = coverage.get('expected_slate_count')
    conflicts = coverage.get('conflicts', 0)
    schedule_state = 'ACQUIRED_UNRECONCILED' if own else 'UNACQUIRED'
    if known and expected is not None:
        schedule_state = 'VERIFIED_EMPTY' if expected == len(today) == 0 else ('RECONCILED' if expected == len(today) else 'COVERAGE_MISMATCH')
    if conflicts:
        schedule_state = 'CONFLICT'
    feature_state = features.get('status', 'UNVERIFIED')
    if feature_state == 'CURRENT':
        checked = features.get('verified_at')
        if not checked or not features.get('artifact_sha256'):
            feature_state = 'UNVERIFIED'
        elif not 0 <= (instant(clock['as_of_utc']) - instant(checked)).total_seconds() <= features.get('ttl_hours', 24) * 3600:
            feature_state = 'STALE'
    # Historical or incomplete features cannot be laundered by fresh schedules.
    ready = schedule_state == 'RECONCILED' and feature_state == 'CURRENT' and bool(today)
    return {'league': league, 'slate_date': clock['slate_date'],
            'season': coverage.get('season') if window_ok else None, 'phase': coverage.get('phase', 'UNKNOWN') if window_ok else 'UNKNOWN',
            'league_week': coverage.get('league_week') if window_ok else None, 'calendar_source': coverage.get('source'),
            'schedule_status': schedule_state, 'acquired_slate_games': len(today),
            'expected_slate_games': expected, 'acquired_final_games': len(finals),
            'results_through': max((e['slate_date'] for e in finals), default=None),
            'feature_status': feature_state, 'feature_details': features,
            'forecast_ready': ready, 'coverage': coverage}
