#!/usr/bin/env python3
"""Strict, read-only winner identity correction for descriptive assessments.

Provider labels are aliases only within the exact league/event and competitor.
No fuzzy matching, global mascot map, forecast rewrite, or canonical ledger writes.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import re

LABEL_FIELDS = ('displayName', 'shortDisplayName', 'location', 'abbreviation')
PROVIDER_LEAGUES = {'CFB': ('23', 'college-football'), 'NBA': ('46', 'nba'),
                    'NHL': ('90', 'nhl'), 'WNBA': ('59', 'wnba'), 'MLS': ('770', 'usa.1')}
FINAL_STATUSES = {'STATUS_FINAL', 'STATUS_FINAL_OT', 'STATUS_FINAL_SO'}


def normalized(value):
    if not isinstance(value, str) or not value.strip():
        return None
    return ' '.join(value.split()).casefold()


def team_labels(team):
    return {normalized(team.get(k)) for k in LABEL_FIELDS} - {None}


def bind_side(label, sides, *, team_id=None):
    """IDs bind first; a supplied label must agree. Unknown/ambiguous fails closed."""
    if label is not None and (not isinstance(label, str) or not label.strip()):
        raise ValueError('INVALID_TEAM_LABEL')
    token = normalized(label)
    label_hits = [s for s, c in sides.items() if token and token in team_labels(c['team'])]
    if team_id is not None:
        matches = [s for s, c in sides.items() if str(c['team'].get('id')) == str(team_id)]
        if len(matches) != 1:
            raise ValueError('TEAM_ID_MISMATCH_OR_AMBIGUOUS')
        if token and label_hits != matches:
            raise ValueError('TEAM_ID_LABEL_CONFLICT')
        return matches[0]
    if len(label_hits) != 1:
        raise ValueError('TEAM_LABEL_UNRESOLVED' if not label_hits else 'TEAM_LABEL_AMBIGUOUS')
    return label_hits[0]


def final_event(payload, league, event_id):
    if not re.fullmatch(re.escape(league) + r':\d+', event_id):
        raise ValueError('LEAGUE_EVENT_BINDING_REQUIRED')
    if not isinstance(payload, dict) or not isinstance(payload.get('events'), list):
        raise ValueError('PROVIDER_SCOREBOARD_SCHEMA')
    hits = [e for e in payload['events'] if str(e.get('id')) == event_id.split(':', 1)[1]]
    if len(hits) != 1:
        raise ValueError('EXACT_EVENT_NOT_FOUND' if not hits else 'AMBIGUOUS_EVENT_MATCH')
    expected = PROVIDER_LEAGUES.get(league)
    declared = [(str(x.get('id')), x.get('slug')) for x in payload.get('leagues', [])]
    if expected is None or declared != [expected]:
        raise ValueError('PROVIDER_LEAGUE_BINDING_REQUIRED')
    events = hits[0].get('competitions', [])
    if len(events) != 1:
        raise ValueError('AMBIGUOUS_COMPETITION')
    event = events[0]
    kind = event.get('status', hits[0].get('status', {})).get('type', {})
    allowed_statuses = {'STATUS_FULL_TIME'} if league == 'MLS' else FINAL_STATUSES
    if kind.get('completed') is not True or kind.get('state') != 'post' or kind.get('name') not in allowed_statuses:
        raise ValueError('PROVIDER_NOT_PLAYED_FINAL')
    competitors = event.get('competitors', [])
    sides = {c.get('homeAway'): c for c in competitors}
    if len(competitors) != 2 or set(sides) != {'home', 'away'}:
        raise ValueError('TEAM_SIDE_IDENTITY')
    ids = [str(c['team'].get('id', '')) for c in sides.values()]
    if any(not re.fullmatch(r'\d+', v) for v in ids) or len(set(ids)) != 2:
        raise ValueError('DISTINCT_PROVIDER_TEAM_IDS_REQUIRED')
    return sides


def final_score(competitor):
    value = competitor.get('score')
    if isinstance(value, dict):
        value = value.get('value')
    if isinstance(value, bool) or value is None:
        raise ValueError('INVALID_FINAL_SCORE')
    try:
        number = float(value)
        if not number.is_integer() or number < 0:
            raise ValueError()
    except (TypeError, ValueError, OverflowError):
        raise ValueError('INVALID_FINAL_SCORE') from None
    return int(number)


def winner_identity(row, payload):
    """Resolve one stored pick using retained provider identity, not string equality."""
    league, eid = row['league'], row['event_id']
    sides = final_event(payload, league, eid)
    for side in ('home', 'away'):
        if bind_side(row[side + '_team'], sides, team_id=row.get(side + '_team_id')) != side:
            raise ValueError('RESULT_TEAM_SIDE_MISMATCH')
    home, away = (final_score(sides[s]) for s in ('home', 'away'))
    if row.get('final_score') != f'{away}-{home}':
        raise ValueError('STORED_RESULT_SCORE_MISMATCH')
    pick = row['model_pick']
    if league == 'MLS' and normalized(pick) in {'draw', 'tie'}:
        if row.get('model_pick_team_id') is not None:
            raise ValueError('DRAW_TEAM_ID_CONFLICT')
        picked_side = 'draw'
    else:
        picked_side = bind_side(pick, sides, team_id=row.get('model_pick_team_id'))
    if home == away and league != 'MLS':
        raise ValueError('UNSUPPORTED_TIED_FINAL')
    won = 'home' if home > away else 'away' if away > home else 'draw'
    return {
        'winner_correct': picked_side == won,
        'identity_binding': {
            'provider': 'ESPN', 'league': league, 'provider_event_id': eid.split(':', 1)[1],
            'home_team_id': str(sides['home']['team']['id']),
            'away_team_id': str(sides['away']['team']['id']),
            'model_pick_side': picked_side, 'winner_side': won,
            'method': 'EXACT_EVENT_SCOPED_PROVIDER_ID_AND_LABELS',
        },
    }


def correct_assessment(original, sources):
    """Append-only successor; preserve predictions and non-winner scores verbatim.

    sources: league -> raw ESPN scoreboard bytes. Source hashes must match those
    stored by the original assessment, preventing a different final from silently
    replacing the previously graded result. This is not a full forecast replay.
    """
    if original.get('canonical_ledger_changed') is not False or original.get('eligibility') != 'DESCRIPTIVE_ONLY_NOT_CANONICAL_GRADE':
        raise ValueError('DESCRIPTIVE_ASSESSMENT_REQUIRED')
    out = copy.deepcopy(original)
    payloads = {}
    for league, raw in sources.items():
        sha = hashlib.sha256(raw).hexdigest()
        if original.get('source_hashes', {}).get(league) != sha:
            raise ValueError('RESULT_SOURCE_HASH_MISMATCH:' + league)
        payloads[league] = (json.loads(raw), sha)
    changes, blocked, seen = [], [], set()
    for row in out['grades']:
        if 'winner_correct' not in row:
            continue
        key = (row['league'], row['event_id'])
        if key in seen:
            raise ValueError('DUPLICATE_ASSESSMENT_EVENT')
        seen.add(key)
        old = row['winner_correct']
        try:
            if row['league'] not in payloads:
                raise ValueError('RESULT_SOURCE_REQUIRED')
            payload, sha = payloads[row['league']]
            if row.get('result_source_sha256') != sha:
                raise ValueError('ROW_SOURCE_HASH_MISMATCH')
            resolved = winner_identity(row, payload)
            row.update(resolved)
            row.pop('identity_status', None)
            row.pop('identity_reason', None)
            if old != row['winner_correct']:
                changes.append({'event_id': row['event_id'], 'old': old, 'new': row['winner_correct']})
        except (ValueError, KeyError, TypeError) as exc:
            row['winner_correct'] = None
            row['identity_status'] = 'BLOCKED'
            row['identity_reason'] = str(exc)
            blocked.append({'event_id': row['event_id'], 'reason': str(exc)})
    graded = [g for g in out['grades'] if type(g.get('winner_correct')) is bool]
    out['summary']['winner_correct'] = sum(g['winner_correct'] for g in graded)
    out['summary']['winner_accuracy'] = sum(g['winner_correct'] for g in graded) / len(graded) if graded else None
    out['summary']['winner_graded_count'] = len(graded)
    out['summary']['winner_blocked_count'] = len(blocked)
    for league in {g.get('league') for g in out['grades']}:
        if league in out['summary']:
            rows = [g for g in graded if g['league'] == league]
            out['summary'][league]['correct'] = sum(g['winner_correct'] for g in rows)
            out['summary'][league]['winner_graded_count'] = len(rows)
    out['correction'] = {
        'schema': 'diagnostic.winner_identity_correction.v1',
        'created_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'status': 'PARTIAL' if blocked else 'COMPLETED', 'changes': changes, 'blocked': blocked,
        'scope': 'WINNER_IDENTITY_ONLY_NOT_FULL_FORECAST_REPLAY',
        'non_winner_metrics': 'PRESERVED_NOT_RECOMPUTED',
        'action_authority': False,
    }
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--assessment', type=Path, required=True)
    p.add_argument('--scoreboard', action='append', default=[], metavar='LEAGUE=PATH')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    sources = {}
    for item in a.scoreboard:
        league, path = item.split('=', 1)
        if league in sources:
            p.error('duplicate league source')
        sources[league] = Path(path).read_bytes()
    raw = a.assessment.read_bytes()
    out = correct_assessment(json.loads(raw), sources)
    out['correction']['supersedes_assessment_sha256'] = hashlib.sha256(raw).hexdigest()
    # Exclusive create rejects original-path writes and retries that would overwrite.
    with a.output.open('x') as handle:
        json.dump(out, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')
    print(json.dumps(out['correction'], sort_keys=True))
    return 2 if out['correction']['blocked'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
