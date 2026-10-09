"""Verify retained source bytes against capture receipts, without asserting historic PIT.

A matching local receipt proves byte retention and recorded chronology only. It is
not an authenticated provider signature or evidence that a model used a feature.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

SCHEMA = 'sports.source_retention_attestation.v1'


def instant(value):
    stamp = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError('SOURCE_TIMESTAMP_TIMEZONE_REQUIRED')
    return stamp.astimezone(dt.timezone.utc)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def retained_file(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('SOURCE_PATH_OUTSIDE_BUNDLE_OR_MISSING')
    return path


def receipt_index(roots):
    index = {}
    reports = []
    for root in roots:
        root = Path(root)
        raw = (root / 'report.json').read_bytes()
        report = json.loads(raw)
        reports.append({'report_sha256': sha256(raw)})
        rows = report.get('sources', []) + report.get('binary_sources', [])
        # Operational NFL captures retain their own source_url/filename receipts.
        for row in report.get('nfl_sources', []):
            rows.append({**row, 'status': str(row.get('status', '')).upper(),
                         'url': row.get('source_url'),
                         'path': 'nfl/' + str(row.get('filename', ''))})
        for row in rows:
            if row.get('status') != 'CAPTURED':
                continue
            url = row.get('url')
            digest = row.get('raw_sha256', row.get('sha256'))
            stamp = row.get('retrieved_at_utc')
            path = row.get('raw_path', row.get('path'))
            if not url or not digest or not stamp or not path:
                continue  # Incomplete records cannot prove retention.
            instant(stamp)
            if row.get('requested_at_utc') and instant(row['requested_at_utc']) > instant(stamp):
                raise ValueError('CAPTURE_CHRONOLOGY_INVALID')
            data = retained_file(root, path).read_bytes()
            if sha256(data) != digest:
                raise ValueError('SOURCE_BYTES_DIGEST_MISMATCH')
            key = (url, digest, instant(stamp))
            index[key] = {'source': url, 'sha256': digest, 'fetched_at_utc': stamp,
                          'byte_count': len(data), 'report_sha256': sha256(raw)}
    return index, reports


def attest_sources(source_fetches, roots, cutoff):
    """Fail closed when even one declared source lacks matching retained bytes."""
    if not source_fetches:
        raise ValueError('SOURCE_RECEIPTS_REQUIRED')
    cutoff = instant(cutoff)
    index, reports = receipt_index(roots)
    verified = []
    for source in source_fetches:
        stamp = instant(source['fetched_at_utc'])
        if stamp > cutoff:
            raise ValueError('SOURCE_CAPTURE_AFTER_CUTOFF')
        key = (source.get('source'), source.get('sha256'), stamp)
        if key not in index:
            raise ValueError('SOURCE_RETENTION_UNVERIFIED:' + str(source.get('source')))
        verified.append(index[key])
    return {'schema': SCHEMA, 'status': 'RAW_BYTES_AND_RECEIPTS_VERIFIED',
            'sources': verified, 'reports': reports,
            'historical_pit_validity_proven': False,
            'provider_authenticity_proven': False,
            'model_input_usage_proven': False,
            'certified_calibration_eligible': False,
            'market_overlay_enabled': False, 'action_authority': False}
