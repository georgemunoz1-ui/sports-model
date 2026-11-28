"""Fitted-artifact-bound reporting-regime admission; no feature substitution.

Only the original NFL integrated-context artifact has a recovered support
certificate here. A new fit using this indicator requires its own certificate.
A support pass is not personnel completeness, calibration or release authority.
"""
from __future__ import annotations
import hashlib
import json
import math

FEATURE = 'report_missing_count'
SCHEMA = 'nfl.report_regime_support.v1'
MODEL_SHA256 = 'c1cdf49dbb1a98bbf2b3d4286042a316c132dc7d472f3138c3bbbb1e0cb1c3cd'
SOURCE_ARCHIVE_SHA256 = 'e55d1f2bee4620c816e3ac28e96dedaa0ecb0568b1d59db3e42a069e83cb76f3'
FEATURE_TABLE_SHA256 = '4e85683269768322d50d00966d432c37d4179d95bac76cd41fa5933d94ff4e5b'
FIT_COUNTS = {'0': 2877, '1': 8, '2': 0}
FIT_N = 2885
CERTIFIED_ARMS = ('availability', 'combined')
PASS = 'PASS_SUPPORT_CHECK_ONLY'
NA = 'NOT_APPLICABLE_TO_INDICATOR_FREE_ARM'


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def valid_count(value):
    return type(value) in (int, float) and math.isfinite(value) and value in (0, 1, 2)


def report_support(artifact, features):
    """Bind training support to exact fitted bytes, not caller-supplied counts."""
    model_hash = _digest(artifact)
    value = features.get(FEATURE)
    count = int(value) if valid_count(value) else None
    by_arm = {}
    for name, params in artifact['arms'].items():
        used = FEATURE in params['feature_names']
        bound = (model_hash == MODEL_SHA256 and name in CERTIFIED_ARMS and
                 params['model_id'] == 'nfl.integrated_context.' + name + '.v1.research' and
                 params['training_rows'] == FIT_N)
        if not used:
            status = NA
        elif not bound:
            status = 'REFUSE_UNBOUND_REPORTING_SUPPORT'
        elif count is None:
            status = 'REFUSE_INVALID_REPORT_MISSING_COUNT'
        elif FIT_COUNTS[str(count)] == 0:
            status = 'REFUSE_UNSEEN_REPORTING_REGIME'
        elif count > 0:
            status = 'REFUSE_UNQUALIFIED_MISSING_REPORT_REGIME'
        else:
            status = PASS
        by_arm[name] = {'model_id': params['model_id'], 'status': status,
                        'admitted': status in (PASS, NA), 'uses_indicator': used,
                        'fit_support_counts': dict(FIT_COUNTS) if used and bound else None,
                        'fit_n': FIT_N if used and bound else None}
    return {'schema': SCHEMA, 'model_artifact_sha256': model_hash,
            'report_missing_count': count, 'source_archive_sha256': SOURCE_ARCHIVE_SHA256,
            'feature_table_sha256': FEATURE_TABLE_SHA256, 'arms': by_arm,
            'action_authority': False, 'personnel_completeness_verified': False,
            'predictive_qualification': 'NOT_ASSESSED'}


def require_selected_support(report, selected, event_id, cutoff):
    arm = report['arms'][selected]
    if not arm['admitted']:
        raise ValueError(arm['status'] + ':' + json.dumps({
            'event_id': event_id, 'cutoff_utc': cutoff, 'selected_arm': selected,
            'model_id': arm['model_id'], 'model_artifact_sha256': report['model_artifact_sha256'],
            'report_missing_count': report['report_missing_count'],
            'fit_support_counts': arm['fit_support_counts'],
            'disposition': 'REFUSED_NO_SUBSTITUTION_NO_FALLBACK'}, sort_keys=True))
    return arm
