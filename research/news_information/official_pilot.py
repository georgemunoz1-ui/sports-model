"""Explicit public-source pilot. Run in a network-enabled research worker, not forecasting.

MLB structured schedule/rosters -> official IDs and probable-state observations.
NFL report -> immutable HTML only until a provider-specific parser is validated.
No model download, outcome grading, predictive adjustment, or action interface.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from research.news_information.contracts import digest, sha256_bytes, write_immutable_json
from research.news_information.state_reducer import reduce_claims


def now():
    return datetime.now(timezone.utc).isoformat()


def capture(url, root):
    if urlsplit(url).hostname not in {'statsapi.mlb.com', 'www.nfl.com'}:
        raise ValueError('unapproved source host')
    started = now()
    with urlopen(Request(url, headers={'User-Agent': 'SportsModelResearch/1.0'}), timeout=30) as response:
        if urlsplit(response.url).hostname not in {'statsapi.mlb.com', 'www.nfl.com'}:
            raise ValueError('unexpected redirect host')
        raw = response.read(10_000_001)
        if len(raw) > 10_000_000:
            raise ValueError('source exceeds capture size limit')
        meta = {'url': url, 'final_url': response.url, 'http_status': response.status,
                'content_type': response.headers.get('Content-Type'),
                'source_date_header': response.headers.get('Date'),
                'request_started_at_utc': started, 'retrieved_at_utc': now(),
                'published_at_utc': None, 'raw_sha256': sha256_bytes(raw), 'bytes': len(raw)}
    target = root / 'raw' / meta['raw_sha256']
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != raw:
            raise ValueError('raw archive collision')
    else:
        with target.open('xb') as f:
            f.write(raw)
    write_immutable_json(root / 'receipts' / (digest(meta) + '.json'), meta)
    return raw, meta


def parse_schedule(payload, observed):
    games, teams, players, claims = [], {}, {}, []
    for day in payload['dates']:
        for g in day['games']:
            eid = 'mlb:' + str(g['gamePk'])
            if any(x['event_id'] == eid for x in games):
                raise ValueError('duplicate official game ID')
            game = {'event_id': eid, 'canonical_event_id': eid, 'league': 'MLB',
                    'official_provider_event_id': str(g['gamePk']), 'start_utc': g['gameDate'],
                    'official_date': g['officialDate'], 'event_identity_status': 'RESOLVED',
                    'source_sha256': observed['raw_sha256'], 'starter_slots': {}}
            for side in ('away', 'home'):
                slot = g['teams'][side]; team = slot['team']; tid = 'mlb:' + str(team['id'])
                teams[tid] = {'canonical_team_id': tid, 'league': 'MLB', 'name': team['name'],
                              'aliases': [], 'valid_from_utc': observed['retrieved_at_utc'],
                              'source_sha256': observed['raw_sha256']}
                game[side + '_team_id'] = tid
                p = slot.get('probablePitcher')
                game['starter_slots'][side] = {'status': 'PROBABLE' if p else 'UNRESOLVED',
                                              'player_id': 'mlb:' + str(p['id']) if p else None}
                if p:
                    pid = 'mlb:' + str(p['id'])
                    # Schedule appearance is not proof of active roster membership.
                    players[pid] = {'canonical_player_id': pid, 'league': 'MLB',
                                    'name': p['fullName'], 'aliases': [], 'team_assignments': [],
                                    'valid_from_utc': observed['retrieved_at_utc'],
                                    'identity_source': 'SCHEDULE_PROBABLE_ONLY'}
                    c = {'league': 'MLB', 'event_id': eid, 'subject_id': tid,
                         'state_dimension': 'probable_starter', 'previous_state': None,
                         'new_state': pid, 'supersedes_claim_id': None, 'source_id': 'MLB_STATSAPI',
                         'effective_at_utc': observed['retrieved_at_utc'],
                         'effective_time_basis': 'FIRST_OBSERVED_NOT_PROVIDER_EFFECTIVE_TIME',
                         'published_at_utc': None, 'retrieved_at_utc': observed['retrieved_at_utc'],
                         'evidence_set_hash': digest([observed['raw_sha256']])}
                    claims.append({**c, 'claim_id': digest(c)})
            if game['home_team_id'] == game['away_team_id']:
                raise ValueError('identical home and away identity')
            games.append(game)
    if payload.get('totalGames') != len(games):
        raise ValueError('schedule total mismatch')
    return games, teams, players, claims


def apply_roster(payload, team_id, observed, players):
    if not isinstance(payload.get('roster'), list) or not payload['roster']:
        raise ValueError('empty or invalid roster')
    seen = set()
    for row in payload['roster']:
        person = row['person']; pid = 'mlb:' + str(person['id'])
        if pid in seen:
            raise ValueError('duplicate roster identity')
        seen.add(pid)
        existing = players.get(pid)
        if existing and existing.get('team_assignments'):
            raise ValueError('conflicting roster membership: ' + pid)
        players[pid] = {'canonical_player_id': pid, 'league': 'MLB', 'name': person['fullName'],
                        'aliases': [], 'valid_from_utc': observed['retrieved_at_utc'],
                        'team_assignments': [{'team_id': team_id,
                                             'valid_from_utc': observed['retrieved_at_utc'],
                                             'valid_to_utc': None}],
                        'source_sha256': observed['raw_sha256'], 'identity_source': 'OFFICIAL_ROSTER'}
    return len(seen)


def run(root, date):
    root = Path(root)
    captures, failures = [], []
    games, teams, players, claims = [], {}, {}, []
    roster_teams = []
    url = 'https://statsapi.mlb.com/api/v1/schedule?' + urlencode(
        {'sportId': 1, 'date': date, 'hydrate': 'probablePitcher'})
    schedule_ok = False
    try:
        raw, receipt = capture(url, root); captures.append(receipt)
        games, teams, players, claims = parse_schedule(json.loads(raw), receipt)
        schedule_ok = True
    except Exception as exc:
        failures.append({'scope': 'MLB_SCHEDULE', 'error': str(exc)})
    for tid in sorted(teams):
        url = f'https://statsapi.mlb.com/api/v1/teams/{tid.split(":")[1]}/roster?rosterType=active&date={date}'
        try:
            raw, receipt = capture(url, root); captures.append(receipt)
            candidate = json.loads(json.dumps(players))
            apply_roster(json.loads(raw), tid, receipt, candidate)
            players = candidate; roster_teams.append(tid)
        except Exception as exc:
            failures.append({'scope': 'MLB_ROSTER', 'team_id': tid, 'error': str(exc)})
    try:
        raw, receipt = capture('https://www.nfl.com/injuries/', root); captures.append(receipt)
        if b'<html' not in raw.lower():
            raise ValueError('unexpected NFL content format')
    except Exception as exc:
        failures.append({'scope': 'NFL_REPORT_CAPTURE', 'error': str(exc)})
    cutoff = now()
    for g in games:
        g['forecast_cutoff_utc'] = cutoff
        g['forecast_status'] = 'NO_FORECAST_INFORMATION_PILOT'
        g['information_completeness'] = 'LOW'
        g['missing_inputs'] = ['CONFIRMED_STARTER', 'OFFICIAL_LINEUP', 'BULLPEN', 'WEATHER_ROOF']
        if any(g[s + '_team_id'] not in roster_teams for s in ('home', 'away')):
            g['missing_inputs'].append('ROSTER')
        g['pregame_at_capture'] = datetime.fromisoformat(g['start_utc'].replace('Z', '+00:00')) > datetime.fromisoformat(cutoff)
    registry = {'schema_version': 'sports_entity_registry.v1', 'teams': list(teams.values()),
                'players': list(players.values()), 'events': games}
    registry['registry_sha256'] = digest(registry)
    verified = sum(sha256_bytes((root / 'raw' / r['raw_sha256']).read_bytes()) == r['raw_sha256'] for r in captures)
    report = {'schema_version': 'official_information_pilot.v1', 'slate_date': date,
              'slate_timezone': 'PROVIDER_OFFICIAL_DATE', 'cutoff_utc': cutoff,
              'schedule_reconciled': schedule_ok, 'scheduled_games': len(games) if schedule_ok else None,
              'games_retained': len(games), 'roster_teams_expected': len(teams),
              'roster_teams_parsed': len(roster_teams), 'player_ids': len(players),
              'official_roster_player_ids': sum(p.get('identity_source') == 'OFFICIAL_ROSTER' for p in players.values()),
              'capture_count': len(captures), 'raw_hashes_verified': verified,
              'captures': captures, 'failures': failures, 'nfl_state': 'CAPTURE_ONLY_PARSER_NOT_VALIDATED',
              'roster_identity_accuracy': None, 'extraction_accuracy': None,
              'forecast_adjustment_enabled': False, 'action_authority': 'OFF',
              'canonical_prospective_eligible': False, 'status': 'RESEARCH_CAPTURE_ONLY'}
    bundle = {'report': report, 'registry': registry, 'claims': claims,
              'state_snapshot': reduce_claims(claims, cutoff), 'full_slate': games}
    target = root / 'runs' / digest(bundle)
    for name, value in bundle.items():
        write_immutable_json(target / (name + '.json'), value)
    print(json.dumps({'output_path': str(target), 'report': report}, sort_keys=True))
    return 1 if failures else 0


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--date', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    datetime.strptime(args.date, '%Y-%m-%d')
    raise SystemExit(run(args.output, args.date))
