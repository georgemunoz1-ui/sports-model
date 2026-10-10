"""Validate the reviewed NHL acquisition scope and unchanged source receipts."""
import datetime as dt
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse


SCOPE_SHA256 = '12410ec50d94654cdbda6207f5a638968ae065156774445176ecf5574e65e45f'
TEAM_IDS = frozenset(map(str, list(range(1, 24)) + list(range(25, 31)) + [37, 124292, 129764]))
SEASONS = range(2021, 2028)
EXCLUDED = {('124292', 2021), *(('129764', y) for y in range(2021, 2025))}
BASE = 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl'


def load_scope(path):
    """Only the reviewed 2026-27 v2 profile is admitted; edits need a new review."""
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SCOPE_SHA256:
        raise ValueError('UNREVIEWED_NHL_SEASON_SCOPE')
    return json.loads(raw)


def history_urls():
    return {f'{BASE}/teams/{team}/schedule?season={year}&seasontype=2'
            for team in TEAM_IDS for year in SEASONS if (team, year) not in EXCLUDED}


def inside(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root):
        raise ValueError('SOURCE_PATH_ESCAPE')
    return path


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('EXACT_SOURCE_TIMESTAMP_REQUIRED')
    stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('SOURCE_TIMEZONE_REQUIRED')
    return stamp.astimezone(dt.timezone.utc)


def receipt(root, source, cutoff=None):
    if source.get('status') != 'CAPTURED' or source.get('http_status') != 200:
        raise ValueError('SOURCE_CAPTURE_INCOMPLETE')
    requested = timestamp(source.get('requested_at_utc'))
    retrieved = timestamp(source.get('retrieved_at_utc'))
    if requested > retrieved:
        raise ValueError('SOURCE_RECEIPT_CLOCK_ORDER')
    if source.get('capture_interval_utc') or source.get('retrieval_interval_utc'):
        raise ValueError('EXACT_SOURCE_RECEIPT_REQUIRED')
    if cutoff is not None and not dt.timedelta(0) <= cutoff - retrieved <= dt.timedelta(hours=6):
        raise ValueError('SOURCE_NOT_AVAILABLE_AND_CURRENT_AT_CUTOFF')
    raw = inside(root, source['raw_path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != source['raw_sha256']:
        raise ValueError('SOURCE_RAW_DIGEST_MISMATCH')
    return json.loads(raw)


def history_sources(root, report, scope, cutoff=None):
    """The 219 applicable requests are complete; exclusions are never receipts."""
    if report.get('season_scope_sha256') != SCOPE_SHA256 or report.get('action_authority') is not False:
        raise ValueError('HISTORY_SCOPE_BINDING')
    if report.get('inapplicable_team_seasons') != scope['nonexistent_team_seasons']:
        raise ValueError('INAPPLICABLE_SCOPE_MISMATCH')
    if report.get('status', 'COMPLETE') != 'COMPLETE':
        raise ValueError('HISTORICAL_CAPTURE_INCOMPLETE')
    if report.get('pending_requests', 0) != 0:
        raise ValueError('HISTORICAL_SOURCE_PENDING')
    sources = [r for r in report['sources'] if r.get('kind') == 'team_season_schedule']
    urls = [r['url'] for r in sources]
    if len(urls) != len(set(urls)) or set(urls) != history_urls():
        raise ValueError('APPLICABLE_HISTORY_REQUEST_CENSUS')
    for source in sources:
        if source.get('league') != 'nhl':
            raise ValueError('HISTORY_LEAGUE')
        data = receipt(root, source, cutoff)
        url = urlparse(source['url'])
        team = url.path.split('/teams/')[1].split('/')[0]
        year = int(parse_qs(url.query)['season'][0])
        if str(data.get('team', {}).get('id')) != team or (data.get('requestedSeason') or {}).get('year') != year:
            raise ValueError('APPLICABLE_PAYLOAD_IDENTITY')
        for event in data.get('events', []):
            if event.get('season', {}).get('year') != year:
                raise ValueError('REQUESTED_SEASON_MISMATCH')
            sides = event['competitions'][0]['competitors']
            if team not in {str(side['team']['id']) for side in sides}:
                raise ValueError('HISTORY_EVENT_TEAM_IDENTITY')
    return sources
