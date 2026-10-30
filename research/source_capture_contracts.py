"""Strict retained-source observation bindings; never forecast or authentication evidence.

Native provider adapters supply JSON pointers, rather than detached asserted values.
An exact quote requires every contract field. Incomplete captures remain evidence,
not executable contracts. Workload estimation belongs to a separate transform.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from numbers import Real
from pathlib import Path

SCHEMA = 'sports.source_bound_observation.v1'
QUOTE_FIELDS = {'event_id', 'home_team_id', 'away_team_id', 'selection_id',
                'sportsbook', 'market', 'side', 'line', 'american_odds',
                'period', 'settlement_rules_id'}
PERSONNEL_FIELDS = {'event_id', 'team_id', 'player_id', 'status'}
PERSONNEL_OPTIONAL = {'expected_minutes', 'minutes_source_or_method', 'scenario_assumptions', 'status_effective_at_utc'}


def instant(value):
    if not isinstance(value, str):
        raise ValueError('INVALID_CAPTURE_TIMESTAMP')
    try:
        value = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('INVALID_CAPTURE_TIMESTAMP') from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('CAPTURE_TIMEZONE_REQUIRED')
    return value.astimezone(dt.timezone.utc)


def finite(value, field):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError('INVALID_FINITE_NUMBER:' + field)
    return float(value)


def text_id(value, field):
    if not isinstance(value, str) or not value.strip() or value in {'TBD', 'None'}:
        raise ValueError('INVALID_IDENTITY:' + field)
    return value


def pointer_value(payload, pointer):
    """Resolve RFC6901 object/list pointers; no expressions or arbitrary transforms."""
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise ValueError('JSON_POINTER_REQUIRED')
    value = payload
    try:
        for token in pointer[1:].split('/'):
            token = token.replace('~1', '/').replace('~0', '~')
            if isinstance(value, list):
                if not token.isdigit() or (len(token) > 1 and token[0] == '0'):
                    raise ValueError('INVALID_ARRAY_POINTER')
                value = value[int(token)]
            elif isinstance(value, dict):
                value = value[token]
            else:
                raise ValueError('POINTER_TRAVERSES_SCALAR')
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError('SOURCE_FIELD_MISSING:' + pointer) from exc
    return value


def verify_receipt(raw_bytes, receipt, cutoff):
    if not isinstance(raw_bytes, bytes):
        raise ValueError('RAW_BYTES_REQUIRED')
    sha = hashlib.sha256(raw_bytes).hexdigest()
    if receipt.get('raw_sha256') != sha:
        raise ValueError('SOURCE_BYTES_DIGEST_MISMATCH')
    text_id(receipt.get('url'), 'source_url')
    text_id(receipt.get('league'), 'league')
    retrieved = instant(receipt.get('retrieved_at_utc'))
    end = instant(cutoff)
    if retrieved > end:
        raise ValueError('SOURCE_CAPTURE_AFTER_CUTOFF')
    requested = receipt.get('requested_at_utc')
    if requested is not None and instant(requested) > retrieved:
        raise ValueError('CAPTURE_CHRONOLOGY_INVALID')
    observed = receipt.get('provider_observed_at_utc')
    if observed is not None and instant(observed) > retrieved:
        raise ValueError('PROVIDER_TIME_AFTER_CAPTURE')
    return {'source_url': receipt['url'], 'raw_sha256': sha,
            'retrieved_at_utc': receipt['retrieved_at_utc'],
            'provider_observed_at_utc': observed,
            'timestamp_policy': 'PROVIDER_AND_RETRIEVAL' if observed is not None else 'RETRIEVAL_BOUND_ONLY',
            'cutoff_utc': cutoff, 'provider_authenticity': 'NOT_ASSESSED',
            'original_historical_pit_proven': False}


def bind_observation(raw_bytes, receipt, bindings, *, kind, cutoff):
    """Bind typed observations to literal values in the retained response.

    Bindings map canonical field names to JSON pointers. No caller-supplied value
    can replace a missing source field. A missing provider timestamp remains null.
    """
    source = verify_receipt(raw_bytes, receipt, cutoff)
    if kind not in {'quote', 'personnel'}:
        raise ValueError('UNKNOWN_OBSERVATION_KIND')
    required = QUOTE_FIELDS if kind == 'quote' else PERSONNEL_FIELDS
    optional = set() if kind == 'quote' else PERSONNEL_OPTIONAL
    if not isinstance(bindings, dict) or set(bindings) - required - optional or required - set(bindings):
        raise ValueError('OBSERVATION_BINDINGS_INCOMPLETE_OR_UNKNOWN')
    payload = json.loads(raw_bytes, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE_SOURCE_JSON')))
    row = {field: pointer_value(payload, ptr) for field, ptr in bindings.items()}
    for field in required - {'line', 'american_odds'}:
        text_id(row[field], field)
    if kind == 'quote':
        if row['home_team_id'] == row['away_team_id']:
            raise ValueError('DUPLICATE_TEAM_IDENTITY')
        if row['market'] not in {'moneyline', 'spread', 'total'}:
            raise ValueError('UNSUPPORTED_MARKET')
        line = finite(row['line'], 'line')
        price = finite(row['american_odds'], 'american_odds')
        if abs(price) < 100:
            raise ValueError('INVALID_AMERICAN_ODDS')
        if row['market'] in {'spread', 'moneyline'}:
            if row['side'] not in {'home', 'away'}:
                raise ValueError('INVALID_TEAM_SIDE')
            expected = row[row['side'] + '_team_id']
            if row['selection_id'] != expected:
                raise ValueError('SELECTION_TEAM_MISMATCH')
            if row['market'] == 'moneyline' and line != 0:
                raise ValueError('MONEYLINE_LINE_MUST_BE_ZERO')
        elif row['side'] not in {'over', 'under'} or row['selection_id'] != row['side'] or line < 0:
            raise ValueError('INVALID_TOTAL_SELECTION')
        row['contract_status'] = 'EXACT_TERMS_BOUND_RULES_NOT_VERIFIED'
    else:
        # Preserve literal status; interpretation is source/league specific.
        row['reported_status'] = row.pop('status')
        row['status'] = row['reported_status'].upper()
        row.setdefault('expected_minutes', None)
        row.setdefault('minutes_source_or_method', None)
        row.setdefault('scenario_assumptions', None)
        if row['expected_minutes'] is not None:
            minutes = finite(row['expected_minutes'], 'expected_minutes')
            if minutes < 0:
                raise ValueError('INVALID_EXPECTED_MINUTES')
            text_id(row['minutes_source_or_method'], 'minutes_source_or_method')
        row['participation_state'] = 'UNKNOWN' if row['expected_minutes'] is None else 'SOURCE_REPORTED_NOT_EVALUATED'
        if row.get('status_effective_at_utc') is not None:
            if instant(row['status_effective_at_utc']) > instant(source['retrieved_at_utc']):
                raise ValueError('STATUS_TIME_AFTER_CAPTURE')
    result = {'schema': SCHEMA, 'kind': kind, 'league': receipt['league'],
              'observation': row, 'field_bindings': dict(bindings), 'source': source,
              'data_capture': 'PARSED_SOURCE_BOUND', 'model_usage': 'NOT_USED',
              'personnel_transform': 'NOT_APPLIED', 'selection_eligibility': 'NOT_EVALUATED',
              'predictive_validation': 'NOT_ASSESSED', 'market_overlay_enabled': False,
              'action_authority': False}
    result['observation_sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return result


def bind_manifest(root, manifest):
    """Bind an offline capture package without claiming a new source retrieval."""
    root = Path(root).resolve()
    rows = []
    for item in manifest['observations']:
        path = (root / item['raw_path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('SOURCE_PATH_OUTSIDE_BUNDLE_OR_MISSING')
        rows.append(bind_observation(path.read_bytes(), item['receipt'], item['bindings'],
                                    kind=item['kind'], cutoff=manifest['cutoff_utc']))
    return {'schema': 'sports.source_bound_capture_bundle.v1', 'observations': rows,
            'source_capture_only': True, 'model_input_usage_proven': False,
            'provider_authenticity': 'NOT_ASSESSED', 'action_authority': False}
