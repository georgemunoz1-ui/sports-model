#!/usr/bin/env python3
"""Retain and normalize provider finals for immutable research forecasts.

No estimated results, fuzzy team matching, inferred finals, or market inputs.
Provider final scores include overtime and NHL shootout scoring; they cannot
settle regulation, period, spread, or total contracts through this interface.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import urllib.request

ROUTES = {'NFL': 'football/nfl', 'CFB': 'football/college-football',
          'NBA': 'basketball/nba', 'NHL': 'hockey/nhl'}
WNBA_ALIASES = {'LA': 'LAS', 'LV': 'LVA', 'NY': 'NYL', 'WSH': 'WAS',
                'CONN': 'CON', 'SA': 'SAN', 'GS': 'GSV', 'POR': 'PDX', 'PHO': 'PHX'}
NFL_ALIASES = {'LAR': 'LA', 'WSH': 'WAS', 'JAC': 'JAX'}


def stamp(value):
    x = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if x.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return x.astimezone(dt.timezone.utc)


def score(value):
    if isinstance(value, dict):
        value = value.get('value')
    if isinstance(value, bool) or value is None:
        raise ValueError('INVALID_FINAL_SCORE')
    v = float(value)
    if not math.isfinite(v) or v < 0 or int(v) != v:
        raise ValueError('INVALID_FINAL_SCORE')
    return int(v)


def _identity(f):
    league = f['league'].upper()
    if league not in {*ROUTES, 'WNBA'}:
        raise ValueError('UNSUPPORTED_LEAGUE')
    if not f['home_team'] or not f['away_team'] or f['home_team'] == f['away_team']:
        raise ValueError('TEAM_IDENTITY_REQUIRED')
    stamp(f['start_time_utc'])
    eid = str(f['event_id'])
    if league == 'NFL':
        m = re.fullmatch(r'(\d{4})_(\d{2})_([A-Z]+)_([A-Z]+)', eid)
        if not m or (m[3], m[4]) != (f['away_team'], f['home_team']):
            raise ValueError('NFL_EVENT_TEAM_BINDING')
    elif not re.fullmatch(league + r':\d+', eid):
        raise ValueError('PROVIDER_EVENT_ID_REQUIRED')
    return {k: f[k] for k in ('event_id', 'home_team', 'away_team', 'start_time_utc')} | {'league': league}


def _base(f, receipt):
    f = _identity(f)
    if stamp(receipt['fetched_at_utc']) > dt.datetime.now(dt.timezone.utc):
        raise ValueError('FUTURE_RESULT_CAPTURE')
    return {**f, **receipt, 'status': 'PENDING', 'home_score': None, 'away_score': None,
            'score_period': 'FULL_GAME', 'supported_product': 'home_win_binary',
            'tie_policy': 'EXCLUDE_UNSUPPORTED_TIE', 'action_authority': False}


def _team_matches(team, expected, league):
    if league == 'NFL':
        code = team.get('abbreviation')
        return NFL_ALIASES.get(code, code) == expected
    # Explicit exact provider labels only; never substring or fuzzy matching.
    return expected in {team.get('displayName'), team.get('shortDisplayName'), team.get('location')}


def parse_espn(payload, forecast, receipt):
    out = _base(forecast, receipt)
    league = out['league']
    if league not in ROUTES:
        raise ValueError('ESPN_LEAGUE_UNSUPPORTED')
    candidates = []
    if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
        raise ValueError('PROVIDER_SCOREBOARD_SCHEMA')
    events = payload['events']
    for event in events:
        if league != 'NFL' and str(event.get('id')) != out['event_id'].split(':', 1)[1]:
            continue
        competitions = event.get('competitions', [])
        if len(competitions) != 1:
            raise ValueError('AMBIGUOUS_COMPETITION')
        c = competitions[0]
        competitors = c.get('competitors', [])
        sides = {t.get('homeAway'): t for t in competitors}
        if len(competitors) != 2 or set(sides) != {'home', 'away'}:
            raise ValueError('TEAM_SIDE_IDENTITY')
        match = all(_team_matches(sides[s]['team'], out[s + '_team'], league) for s in ('home', 'away'))
        if not match:
            if league != 'NFL':
                raise ValueError('RESULT_TEAM_MISMATCH')
            continue
        if stamp(event['date']) != stamp(out['start_time_utc']):
            if league != 'NFL':
                return {**out, 'reason': 'START_TIME_CHANGED_REQUIRES_RECONCILIATION'}
            continue
        if league == 'NFL':
            parts = out['event_id'].split('_')
            if int(event.get('season', {}).get('year', -1)) != int(parts[0]) or int(event.get('week', {}).get('number', -1)) != int(parts[1]):
                raise ValueError('NFL_PROVIDER_WEEK_BINDING')
        candidates.append((event, c, sides))
    if not candidates:
        return {**out, 'reason': 'EXACT_EVENT_NOT_FOUND'}
    if len(candidates) != 1:
        raise ValueError('AMBIGUOUS_EVENT_MATCH')
    event, competition, sides = candidates[0]
    status = competition.get('status', event.get('status', {}))
    kind = status.get('type', {})
    out.update(provider='ESPN', provider_event_id=str(event['id']),
               provider_final_status=kind.get('name'), provider_period=status.get('period'))
    if not kind.get('completed') or kind.get('state') != 'post':
        return {**out, 'reason': 'PROVIDER_NOT_FINAL'}
    # Completed cancellations/forfeits are not played final score observations.
    if kind.get('name') not in {'STATUS_FINAL', 'STATUS_FINAL_OT', 'STATUS_FINAL_SO'}:
        return {**out, 'reason': 'UNSUPPORTED_TERMINAL_STATUS'}
    if stamp(receipt['fetched_at_utc']) <= stamp(out['start_time_utc']):
        raise ValueError('FINAL_CAPTURE_NOT_AFTER_START')
    h, a = score(sides['home'].get('score')), score(sides['away'].get('score'))
    if h == a and league != 'NFL':
        raise ValueError('BINARY_LEAGUE_TIED_FINAL')
    detail = ' '.join(str(kind.get(k, '')) for k in ('description', 'detail', 'shortDetail'))
    period = status.get('period')
    threshold = 3 if league == 'NHL' else 4
    overtime = bool(isinstance(period, (int, float)) and period > threshold) or bool(re.search(r'\bOT\b|overtime', detail, re.I))
    shootout = league == 'NHL' and (kind.get('name') == 'STATUS_FINAL_SO' or bool(re.search(r'\bSO\b|shootout', detail, re.I)))
    return {**out, 'status': 'FINAL', 'home_score': h, 'away_score': a,
            'overtime': overtime, 'shootout': shootout,
            'settlement': 'FULL_GAME_PROVIDER_FINAL_INCLUDING_OT_AND_SO' if league == 'NHL' else 'FULL_GAME_INCLUDING_OVERTIME',
            'binary_grade_eligible': h != a, 'reason': 'TIE_EXCLUDED' if h == a else 'VERIFIED_PROVIDER_FINAL'}


def parse_wnba(payload, forecast, receipt):
    out = _base(forecast, receipt)
    if out['league'] != 'WNBA':
        raise ValueError('WNBA_LEAGUE_REQUIRED')
    game = payload['game']
    gid = out['event_id'].split(':', 1)[1]
    if str(game['gameId']) != gid:
        raise ValueError('RESULT_EVENT_MISMATCH')
    for side in ('home', 'away'):
        code = game[side + 'Team']['teamTricode']
        if WNBA_ALIASES.get(code, code) != out[side + '_team']:
            raise ValueError('RESULT_TEAM_MISMATCH')
    if stamp(game['gameTimeUTC']) != stamp(out['start_time_utc']):
        return {**out, 'reason': 'START_TIME_CHANGED_REQUIRES_RECONCILIATION'}
    out.update(provider='WNBA_OFFICIAL', provider_event_id=gid, provider_final_status=game.get('gameStatus'))
    if game.get('gameStatus') != 3:
        return {**out, 'reason': 'PROVIDER_NOT_FINAL'}
    if stamp(receipt['fetched_at_utc']) <= stamp(out['start_time_utc']):
        raise ValueError('FINAL_CAPTURE_NOT_AFTER_START')
    h, a = (score(game[s + 'Team']['score']) for s in ('home', 'away'))
    if h == a:
        raise ValueError('BINARY_LEAGUE_TIED_FINAL')
    period = game.get('period')
    return {**out, 'status': 'FINAL', 'home_score': h, 'away_score': a,
            'overtime': isinstance(period, (int, float)) and period > 4,
            'shootout': False, 'settlement': 'FULL_GAME_INCLUDING_OVERTIME',
            'binary_grade_eligible': True, 'reason': 'VERIFIED_PROVIDER_FINAL'}


def source_url(forecast):
    f = _identity(forecast)
    if f['league'] == 'WNBA':
        return 'https://cdn.wnba.com/static/json/liveData/boxscore/boxscore_' + f['event_id'].split(':', 1)[1] + '.json'
    start = stamp(f['start_time_utc'])
    # Provider scoreboards group by their calendar, which can differ from UTC.
    day = (start - dt.timedelta(days=1)).strftime('%Y%m%d') + '-' + (start + dt.timedelta(days=1)).strftime('%Y%m%d')
    return f"https://site.api.espn.com/apis/site/v2/sports/{ROUTES[f['league']]}/scoreboard?dates={day}&limit=1000"


def _fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'sports-model-final-capture/1.0', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        if response.status != 200 or response.url != url:
            raise ValueError('UNEXPECTED_SOURCE_RESPONSE')
        raw = response.read(20_000_001)
    if len(raw) > 20_000_000:
        raise ValueError('SOURCE_SIZE_LIMIT')
    return raw


def acquire_results(forecasts, output_dir, fetcher=None):
    """Independent events continue after failures; all failures remain explicit."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    (root / 'raw').mkdir()
    fetcher = fetcher or _fetch
    cache, rows, seen = {}, [], {}
    for forecast in forecasts:
        f = _identity(forecast)
        key = (f['league'], f['event_id'])
        if key in seen:
            if seen[key] != f:
                raise ValueError('CONFLICTING_FORECAST_EVENT_IDENTITY')
            continue
        seen[key] = f
        try:
            url = source_url(f)
            if url not in cache:
                raw = fetcher(url)
                fetched = dt.datetime.now(dt.timezone.utc).isoformat()
                sha = hashlib.sha256(raw).hexdigest()
                path = root / 'raw' / (sha + '.json')
                if not path.exists():
                    with path.open('xb') as handle:
                        handle.write(raw)
                receipt = {'source_url': url, 'source_sha256': sha, 'raw_path': str(path), 'fetched_at_utc': fetched}
                cache[url] = (json.loads(raw), receipt)
            payload, receipt = cache[url]
            parser = parse_wnba if f['league'] == 'WNBA' else parse_espn
            rows.append(parser(payload, f, receipt))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            rows.append({**f, 'status': 'BLOCKED', 'reason': str(exc), 'action_authority': False})
    report = {'status': 'PARTIAL' if any(r['status'] == 'BLOCKED' for r in rows) else 'COMPLETED',
              'counts': {s: sum(r['status'] == s for r in rows) for s in ('FINAL', 'PENDING', 'BLOCKED')},
              'action_authority': False}
    (root / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    (root / 'results.json').write_text(json.dumps(rows, indent=2, sort_keys=True, allow_nan=False) + '\n')
    (root / 'capture_receipts.json').write_text(json.dumps([r for _, r in cache.values()], indent=2, sort_keys=True) + '\n')
    return rows


def verify_result_source(result, base_dir=None):
    """Recompute normalized outcome from retained provider bytes, not caller flags."""
    if result['source_url'] != source_url(result):
        raise ValueError('RESULT_SOURCE_URL_MISMATCH')
    path = Path(result['raw_path'])
    if not path.is_absolute():
        path = Path(base_dir or '.') / path
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != result['source_sha256']:
        raise ValueError('RESULT_RAW_HASH_MISMATCH')
    receipt = {k: result[k] for k in ('source_url', 'source_sha256', 'raw_path', 'fetched_at_utc')}
    parser = parse_wnba if result['league'] == 'WNBA' else parse_espn
    actual = parser(json.loads(raw), result, receipt)
    if actual != result:
        raise ValueError('NORMALIZED_RESULT_MISMATCH')
    return True


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    registry = json.loads(a.registry.read_text())
    rows = acquire_results(registry.get('forecasts', {}).values(), a.output)
    print(json.dumps({'results': str(a.output / 'results.json'), 'counts': {s: sum(r['status'] == s for r in rows) for s in ('FINAL', 'PENDING', 'BLOCKED')}}))
    return 2 if any(r['status'] == 'BLOCKED' for r in rows) else 0


if __name__ == '__main__':
    raise SystemExit(main())
