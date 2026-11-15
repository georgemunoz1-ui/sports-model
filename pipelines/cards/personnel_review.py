"""Presentation-only personnel review of frozen cards and their attributable grades."""
from __future__ import annotations
import hashlib
import json
import hmac
from datetime import datetime, timezone
from pathlib import Path

from research.personnel_events import review_fixture


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _board_cutoff(row):
    # Quotes, publication and kickoff are not evidence of a model's information cutoff.
    stamps = set()
    for arms in (row.get('markets') or {}).values():
        for arm in arms:
            cutoff = arm.get('cutoff')
            if not cutoff:
                return None
            t = datetime.fromisoformat(cutoff.replace('Z','+00:00'))
            if t.tzinfo is None or t.utcoffset() is None:
                return None
            stamps.add(t.astimezone(timezone.utc))
    return next(iter(stamps)).isoformat() if len(stamps) == 1 else None


def _fixtures(card):
    if isinstance(card.get('forecasts'), list):
        for row in card['forecasts']:
            event = dict(row)
            if card.get('league', '').upper() == 'CBB':
                snapshot = row.get('model_input_snapshot') or {}
                for short, side in [('a','away'), ('h','home')]:
                    if event.get(side + '_id') is None and snapshot.get(short) is not None:
                        event[side + '_id'] = str(snapshot[short])
            forecast = row if row.get('forecast_status') in (None, 'FORECAST_GENERATED') else None
            yield card['league'], event, card.get('as_of_utc'), forecast
    elif card.get('schema') in {'nfl.integrated_context_forecast.v1','nfl.enhanced_pregame_forecast.v1'}:
        yield 'NFL', card['event'], card.get('cutoff_utc'), card
    elif card.get('schema') == 'mlb.reviewed_research_board.v1':
        table = Path(__file__).resolve().parents[2] / 'data/backfill/mlb/2026/_win/teams_abbrev.txt'
        clubs = dict(line.split('|') for line in table.read_text().splitlines() if line)
        for row in card['events']:
            event = {'event_id':row['event_id'], 'start_time_utc':row.get('start_time_utc')}
            for side in ('away', 'home'):
                club = (row.get('teams') or {}).get(side) or {}
                starter = club.get('starter') or {}
                event[side + '_team'] = clubs.get(club.get('team'), club.get('team'))
                event[side + '_pitcher_id'] = starter.get('id')
                event[side + '_starter'] = starter.get('fullName')
            forecast = row.get('forecast') or None
            if forecast is not None and (forecast.get('model_input_snapshot') or {}).get('package_sha256') != card.get('package_sha256'):
                event['personnel_parent_warning'] = 'Forecast and reviewed MLB board refer to different packages.'
                forecast = {}  # A forecast exists, but this view cannot prove which inputs it used.
            yield 'MLB', event, row.get('cutoff_utc'), forecast
    elif isinstance(card.get('rows'), list):
        for row in card['rows']:
            teams = row.get('teams') or {}
            event = {'event_id': row['event_id'], 'start_time_utc': row.get('start', row.get('start_time_utc'))}
            for side in ('away','home'):
                team = teams.get(side) or {}
                event[side + '_team'] = row.get(side + '_team') or row.get(side) or team.get('displayName')
                event[side + '_id'] = row.get(side + '_team_id') or team.get('id')
            # A decision-board row can have several arms; none proves player feature use.
            try:
                cutoff = _board_cutoff(row)
            except (AttributeError, TypeError, ValueError):
                cutoff = None
            forecast = row if any((row.get('markets') or {}).values()) or row.get('simulations', 0) else None
            yield row['league'], event, cutoff, forecast
    else:
        raise ValueError('UNSUPPORTED_PERSONNEL_REVIEW_PARENT')


def build_review(card, observations=()):
    items = []
    seen = set()
    for league, event, cutoff, forecast in _fixtures(card):
        key = (league.upper(), event['event_id'])
        if key in seen:
            raise ValueError('DUPLICATE_PERSONNEL_FIXTURE')
        seen.add(key)
        result = review_fixture(key[0], event, cutoff, forecast=forecast, observations=observations)
        if event.get('personnel_parent_warning'):
            result['caveats'].append(event['personnel_parent_warning'])
        # Individual role evidence cannot certify team-wide personnel coverage.
        items.append({**result, 'league': key[0], 'event_id': key[1], 'personnel_disposition':'HOLD'})
    return {'schema':'sports.personnel_card_review.v1', 'parent_card_sha256':digest(card),
            'events':items, 'action_authority':False, 'canonical_registration':False}


def load_pregame_review(path, card, source_sha, expected_sha=None):
    raw = Path(path).read_bytes()
    review_sha = hashlib.sha256(raw).hexdigest()
    if expected_sha is not None and not hmac.compare_digest(review_sha, expected_sha):
        raise ValueError('PERSONNEL_REVIEW_DIGEST_MISMATCH')
    review = json.loads(raw)
    if review.get('schema') == 'sports.card_disclosures.research.v1':
        if (digest({k:v for k,v in review.items() if k != 'artifact_sha256'}) != review.get('artifact_sha256')
                or review.get('source_parent_sha256') != digest(card)
                or review.get('action_authority') is not False):
            raise ValueError('PERSONNEL_DISCLOSURE_HASH_MISMATCH')
        review = {'schema':'sports.personnel_card_review.v1', 'action_authority':False,
                  'parent_card_sha256':review['source_parent_sha256'],
                  'parent_file_sha256':review.get('parent_file_sha256'), 'canonical_registration':False,
                  'events':[r['personnel_review'] for r in review['events']]}
    if (review.get('schema') != 'sports.personnel_card_review.v1'
            or review.get('parent_file_sha256') != source_sha
            or review.get('parent_card_sha256') != digest(card)
            or review.get('action_authority') is not False
            or 'grades_file_sha256' in review):
        raise ValueError('PERSONNEL_REVIEW_PARENT_MISMATCH')
    actual = [(item['league'], item['event_id']) for item in review['events']]
    expected = [(league.upper(), event['event_id']) for league, event, _, _ in _fixtures(card)]
    if len(set(actual)) != len(actual) or set(actual) != set(expected):
        raise ValueError('PERSONNEL_REVIEW_FIXTURE_MISMATCH')
    review['prior_review_digest_status'] = 'MATCHES_SUPPLIED_PIN' if expected_sha else 'NO_INDEPENDENT_PIN_SUPPLIED'
    review['registration_status'] = 'NO_VERIFIED_PREGAME_REGISTRATION'
    return review, review_sha


def bind_grades(review, grades, card_sha):
    """Attach grade status only when the grader pinned the same serialized parent."""
    if not isinstance(grades, dict):
        raise ValueError('PERSONNEL_GRADES_REQUIRE_HASH_BOUND_PARENT')
    if grades.get('schema') == 'research.descriptive_postgame_assessment.v2':
        parent = grades.get('forecast_board_sha256')
        rows = [(r['league'].upper(), r['event_id'], r) for r in grades['grades']]
    elif grades.get('schema') == 'sports.cbb.grades.shadow.v2':
        parent = grades.get('frozen_parent_sha256')
        rows = [('CBB', r['event_id'], r) for r in grades['rows']]
    else:
        raise ValueError('UNSUPPORTED_PERSONNEL_GRADE_SCHEMA')
    if parent != card_sha:
        raise ValueError('PERSONNEL_GRADES_PARENT_MISMATCH')
    by_event = {(r['league'],r['event_id']):r for r in review['events']}
    seen = set()
    for league, eid, grade in rows:
        key = (league, eid)
        if key in seen or key not in by_event:
            raise ValueError('PERSONNEL_GRADE_FIXTURE_MISMATCH')
        seen.add(key)
        by_event[key]['grade_status'] = grade.get('status') or ('GRADED' if type(grade.get('winner_correct')) is bool else 'UNKNOWN')
    for key in by_event.keys() - seen:
        by_event[key]['grade_status'] = 'NO_MATCHING_GRADE'
    review['interpretation'] = 'Retain the ordinary grade. Single-game outcomes cannot establish a personnel effect.'
    return review
