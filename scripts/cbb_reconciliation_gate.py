"""Bind a new CBB research freeze to independently captured schedule evidence.

No market fields enter numerical inputs. A pinned capture is byte-verified and
replayed; unverified venue, duplicate identities and unresolved tips stay held.
The historical replay path is not a registration or retroactive admission API.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import tempfile
from pathlib import Path
from scripts import capture_cbb_daily as collector


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('CLOCK_MISSING')
    instant = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('CLOCK_TIMEZONE_REQUIRED')
    return instant.astimezone(dt.timezone.utc)


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError('NONFINITE_JSON')


def parse(raw):
    return json.loads(raw, object_pairs_hook=_strict_object, parse_constant=_nonfinite)


def _pinned(path, expected):
    if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('SHA256_PIN_REQUIRED')
    raw = path.read_bytes()
    if sha(raw) != expected:
        raise ValueError('EVIDENCE_HASH_MISMATCH')
    return raw


def load_evidence(root, expected_manifest, day, as_of):
    """Verify a completed capture with the current collector, never re-label old captures."""
    root = Path(root).resolve()
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('AS_OF_TIMEZONE_REQUIRED')
    manifest = parse(_pinned(root / 'manifest.json', expected_manifest))
    if manifest['date'] != day.strftime('%Y%m%d'):
        raise ValueError('WRONG_CAPTURE_SLATE')
    finished = timestamp(manifest['finished_at_utc'])
    if not dt.timedelta(0) <= as_of - finished <= dt.timedelta(hours=6):
        raise ValueError('STALE_OR_FUTURE_RECONCILIATION_CAPTURE')
    saved = parse(_pinned(root / 'coverage.json', manifest['coverage_sha256']))
    sources = {}
    for receipt in manifest['sources']:
        url = receipt['url']
        if url in sources or receipt.get('status', 200) != 200:
            raise ValueError('AMBIGUOUS_OR_FAILED_SOURCE_RECEIPT')
        pin = receipt['sha256']
        if receipt['file'] != 'raw/' + pin + '.json':
            raise ValueError('RAW_SOURCE_PATH_MISMATCH')
        path = (root / receipt['file']).resolve()
        if path.parent != (root / 'raw').resolve():
            raise ValueError('RAW_SOURCE_PATH_ESCAPE')
        raw = _pinned(path, pin)
        parse(raw)  # Duplicate keys and non-finite values refuse the input.
        if timestamp(receipt['retrieved_at_utc']) > finished:
            raise ValueError('SOURCE_AFTER_CAPTURE_FINISH')
        sources[url] = (raw, receipt)
    # Use the native full-slate mapper, including its candidate-claim accounting.
    # Raw responses are reused verbatim; this creates no new source observation.
    def get(_output, url):
        return sources[url]
    with tempfile.TemporaryDirectory() as tmp:
        replayed = collector.daily(day, Path(tmp) / 'replay', get=get)
    if replayed.get('status') == 'BLOCKED' or replayed != saved:
        raise ValueError('RECONCILIATION_REPLAY_MISMATCH')
    records = {}
    for row in replayed['events']:
        eid = row['event_id']
        if eid in records:
            raise ValueError('DUPLICATE_RECONCILIATION_EVENT')
        records[eid] = row
    return {'manifest_sha256': expected_manifest, 'coverage_sha256': manifest['coverage_sha256'],
            'records': records, 'sources': {url: rec for url, (_, rec) in sources.items()}}


def target_gate(target, evidence, at):
    """Return (hold reason, verified timing proof). No caller-provided cutoff accepted."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError('GATE_CLOCK_TIMEZONE_REQUIRED')
    row = evidence['records'].get('CBB:' + target['id'])
    if row is None:
        return 'RECONCILIATION_EVENT_MISSING', None
    if (row['home_id'], row['away_id']) != (target['h'], target['a']) or (
        row['neutral_site'] is not target['neutral'] or timestamp(row['start_time_utc']) != timestamp(target['utc'])
    ):
        return 'RECONCILIATION_TARGET_IDENTITY_MISMATCH', None
    if row['status'] != 'PENDING' or row['issues'] or row['espn_status'] != 'STATUS_SCHEDULED' or row['ncaa_status'] != 'P':
        return 'RECONCILIATION_HOLD:' + row['status'], None
    if row.get('tip_accepted') is not True or row.get('candidate_contest_ids') != [row['ncaa_contest_id']]:
        return 'RECONCILIATION_TIP_OR_CANDIDATE_UNVERIFIED', None
    espn = timestamp(row['start_time_utc'])
    ncaa = timestamp(row['ncaa_start_time_utc'])
    deadline = min(espn, ncaa)
    if timestamp(row['pregame_cutoff_utc']) != deadline:
        return 'RECONCILIATION_CUTOFF_MISMATCH', None
    for provider in ('espn', 'ncaa'):
        receipt = evidence['sources'].get(row[provider + '_scoreboard_url'])
        if receipt is None or receipt['sha256'] != row[provider + '_scoreboard_sha256']:
            return 'RECONCILIATION_SOURCE_UNBOUND', None
        retrieved = timestamp(receipt['retrieved_at_utc'])
        if not retrieved <= at or not retrieved < deadline or at - retrieved > dt.timedelta(hours=6):
            return 'RECONCILIATION_SOURCE_NOT_PRETIP_OR_STALE', None
    proof = {'pregame_cutoff_utc': deadline.isoformat(), 'ncaa_start_time_utc': ncaa.isoformat(),
             'ncaa_contest_id': row['ncaa_contest_id'], 'tip_policy': row['tip_policy'],
             'reconciliation_record_sha256': sha(json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()),
             'capture_manifest_sha256': evidence['manifest_sha256'], 'coverage_sha256': evidence['coverage_sha256']}
    return ('NOT_SCHEDULED_PRE_START' if at >= deadline else None), proof


def forecast_deadline(card, row):
    """Legacy readers may inspect old cards; a new bound card must carry its proof."""
    start = timestamp(row['start_time_utc'])
    binding = card.get('reconciliation_manifest_sha256')
    if binding is None:
        if 'pregame_cutoff_utc' in row or 'schedule_reconciliation' in row:
            raise ValueError('UNBOUND_RECONCILIATION_CUTOFF')
        return start  # Legacy diagnostic card only, never new freeze or registration.
    proof = row.get('schedule_reconciliation')
    if not isinstance(proof, dict) or proof.get('capture_manifest_sha256') != binding or proof.get('coverage_sha256') != card.get('reconciliation_coverage_sha256'):
        raise ValueError('UNBOUND_RECONCILIATION_CUTOFF')
    early = min(start, timestamp(proof['ncaa_start_time_utc']))
    if timestamp(row['pregame_cutoff_utc']) != early or timestamp(proof['pregame_cutoff_utc']) != early:
        raise ValueError('INVALID_EARLIEST_CUTOFF')
    return early
