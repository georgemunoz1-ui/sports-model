"""Observe independently fitted base/QB arms without changing either forecast.

Strict unrounded 0.5 comparisons define picks. Contribution differences describe
fitted terms, not causal QB effects. The local hash chain is diagnostics-only and
is deliberately independent of the canonical forecast/grading ledgers.
"""
from __future__ import annotations

import copy
import datetime as dt
import fcntl
import hashlib
import json
import math
import numbers
import os
from pathlib import Path

VERSION = 'nfl.base_qb_flip_diagnostics.v1'
QB_FEATURES = frozenset({'qb_quality_diff', 'qb_quality_sum', 'qb_experience_diff',
                         'qb_change_diff', 'qb_unknown_count'})


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def reporter_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _finite(value):
    return isinstance(value, numbers.Real) and not isinstance(value, bool) and math.isfinite(value)


def _safe(value):
    """Keep malformed inputs inspectable while never emitting JSON NaN/Infinity."""
    if isinstance(value, float) and not math.isfinite(value):
        return {'invalid_nonfinite_number': str(value)}
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    return copy.deepcopy(value)


def _probability(arm):
    prediction = arm.get('prediction') if isinstance(arm, dict) else None
    value = prediction.get('home_win') if isinstance(prediction, dict) else None
    return float(value) if _finite(value) and 0 <= value <= 1 else None


def _pick(probability, home, away):
    if probability is None or probability == .5:
        return None
    return home if probability > .5 else away


def _trace(arm, probability):
    traces = arm.get('contribution_trace') if isinstance(arm, dict) else None
    trace = traces.get('home_win') if isinstance(traces, dict) else None
    if not isinstance(trace, dict):
        return None
    features = trace.get('features')
    if (not isinstance(features, dict) or not features or
            not all(isinstance(k, str) and _finite(v) for k, v in features.items()) or
            not _finite(trace.get('intercept')) or not _finite(trace.get('linear_value')) or
            trace.get('units') != 'LOG_ODDS'):
        return None
    try:
        linear = float(trace['intercept']) + math.fsum(features.values())
    except OverflowError:
        return None
    if not math.isfinite(linear):
        return None
    if not math.isclose(linear, trace['linear_value'], rel_tol=1e-9, abs_tol=1e-9):
        return None
    # Stable sigmoid, including numerically saturated endpoint probabilities.
    projected = 1 / (1 + math.exp(-linear)) if linear >= 0 else math.exp(linear) / (1 + math.exp(linear))
    if probability is None or not math.isclose(projected, probability, rel_tol=1e-8, abs_tol=1e-10):
        return None
    return trace


def _contributions(base, qb, base_p, qb_p):
    result = {'status': 'INCOMPLETE', 'units': 'LOG_ODDS',
              'qb_group_signed': None, 'shared_feature_shift': None,
              'intercept_shift': None, 'trace_logit_difference': None,
              'qb_absolute_share': None, 'qb_absolute_sum': None,
              'absolute_feature_sum': None, 'denominator_excludes_intercept': True,
              'interpretation': 'Fitted-term decomposition, not causal QB attribution or a recovered base.'}
    b, q = _trace(base, base_p), _trace(qb, qb_p)
    if b is None or q is None:
        return result
    bf, qf = b['features'], q['features']
    if QB_FEATURES & set(bf) or not QB_FEATURES <= set(qf) or set(qf) - QB_FEATURES != set(bf):
        return result
    try:
        qb_sum = math.fsum(qf[name] for name in sorted(QB_FEATURES))
        shared = {name: qf[name] - bf[name] for name in sorted(bf)}
        denom = math.fsum(abs(v) for v in qf.values())
        qb_abs = math.fsum(abs(qf[name]) for name in sorted(QB_FEATURES))
        shift = float(q['intercept']) - float(b['intercept'])
        shared_sum = math.fsum(shared.values())
        difference = qb_sum + shared_sum + shift
    except (OverflowError, ValueError):
        return result
    if not all(math.isfinite(v) for v in (qb_sum, denom, qb_abs, shift, shared_sum, difference)):
        return result
    result.update(status='COMPLETE', qb_group_signed=qb_sum,
                  shared_feature_shift=shared_sum,
                  shared_feature_differences=shared, qb_feature_contributions={n: qf[n] for n in sorted(QB_FEATURES)},
                  intercept_shift=shift, trace_logit_difference=difference,
                  qb_absolute_share=qb_abs / denom if denom else None,
                  qb_absolute_sum=qb_abs, absolute_feature_sum=denom)
    if denom == 0:
        result['share_status'] = 'ZERO_ABSOLUTE_FEATURE_SUM'
    else:
        result['share_status'] = 'DEFINED'
    return result


def build_flip_diagnostics(bundle, arm_model_ids=None, gap_threshold_pp=10.0):
    """Return a deterministic JSON-safe observation; never mutate ``bundle``.

    Arms inherit the enclosing event, forecast, cutoff and artifact identities.
    Explicit contradictory arm metadata makes the comparison fail-visible.
    Exact 50% is neutral, so it never manufactures a pick or a pick flip.
    """
    if not _finite(gap_threshold_pp) or gap_threshold_pp < 0:
        raise ValueError('INVALID_GAP_THRESHOLD_PP')
    if not isinstance(bundle, dict):
        raise ValueError('FORECAST_BUNDLE_REQUIRED')
    event = bundle.get('event') if isinstance(bundle.get('event'), dict) else {}
    arms = bundle.get('arms') if isinstance(bundle.get('arms'), dict) else {}
    models = dict(arm_model_ids or {})
    for name in ('base', 'qb'):
        arm = arms.get(name)
        if isinstance(arm, dict) and name not in models:
            models[name] = arm.get('model_id')
    source = {'event_id': event.get('event_id'), 'home_team': event.get('home_team'),
              'away_team': event.get('away_team'), 'start_time_utc': event.get('start_time_utc'),
              'forecast_identity': bundle.get('identity'), 'cutoff_utc': bundle.get('cutoff_utc'),
              'model_artifact_sha256': bundle.get('model_artifact_sha256'),
              'selected_model_id': bundle.get('model_id'), 'arm_model_ids': models,
              'mode': _safe(bundle.get('mode')), 'market_input': _safe(bundle.get('market_input')),
              'source_ids': _safe(bundle.get('source_ids')),
              'source_hashes': _safe(bundle.get('source_hashes')),
              'assimilation': _safe(bundle.get('assimilation')),
              'forecast_code_hashes': _safe(bundle.get('code_hashes'))}
    errors = []
    for key in ('event_id', 'home_team', 'away_team', 'forecast_identity', 'cutoff_utc', 'model_artifact_sha256', 'selected_model_id'):
        if not isinstance(source[key], str) or not source[key].strip():
            errors.append('MISSING_SOURCE_IDENTITY:' + key)
    for name in ('base', 'qb'):
        if not isinstance(models.get(name), str) or not models[name].strip():
            errors.append('MISSING_ARM_MODEL_ID:' + name)
    if source['mode'] != 'research_pregame':
        errors.append('UNSUPPORTED_SOURCE_MODE')
    if source['market_input'] is not False:
        errors.append('SOURCE_NOT_VERIFIED_MARKET_BLIND')
    if source['home_team'] == source['away_team']:
        errors.append('INVALID_TEAM_ORIENTATION')
    probabilities = {}
    for name in ('base', 'qb'):
        arm = arms.get(name)
        probabilities[name] = _probability(arm)
        if not isinstance(arm, dict):
            errors.append('MISSING_ARM:' + name)
            continue
        if probabilities[name] is None:
            errors.append('INVALID_PROBABILITY:' + name)
        checks = {'event_id': source['event_id'], 'home_team': source['home_team'],
                  'away_team': source['away_team'], 'identity': source['forecast_identity'],
                  'forecast_identity': source['forecast_identity'], 'cutoff_utc': source['cutoff_utc'],
                  'model_artifact_sha256': source['model_artifact_sha256']}
        for key, expected in checks.items():
            if key in arm and arm[key] != expected:
                errors.append('ARM_IDENTITY_MISMATCH:' + name + ':' + key)
        if 'event' in arm:
            if not isinstance(arm['event'], dict):
                errors.append('ARM_IDENTITY_MISMATCH:' + name + ':event')
            else:
                for key in ('event_id', 'home_team', 'away_team', 'start_time_utc'):
                    if key in arm['event'] and arm['event'][key] != event.get(key):
                        errors.append('ARM_IDENTITY_MISMATCH:' + name + ':event.' + key)
        if arm.get('model_id') is not None and models.get(name) != arm['model_id']:
            errors.append('ARM_IDENTITY_MISMATCH:' + name + ':model_id')
        if bundle.get('selected_arm') == name and models.get(name) and models[name] != bundle.get('model_id'):
            errors.append('ARM_IDENTITY_MISMATCH:' + name + ':selected_model_id')
    base_p, qb_p = probabilities['base'], probabilities['qb']
    valid = not errors
    flags = list(errors)
    base_pick = _pick(base_p, source['home_team'], source['away_team']) if valid else None
    qb_pick = _pick(qb_p, source['home_team'], source['away_team']) if valid else None
    flip = bool(base_pick and qb_pick and base_pick != qb_pick) if valid else None
    delta_pp = (qb_p - base_p) * 100 if valid else None
    delta_logit = None
    if valid:
        if flip:
            flags.append('PICK_FLIP')
        if abs(delta_pp) >= gap_threshold_pp:
            flags.append('LARGE_PROBABILITY_GAP')
        if base_p == .5 or qb_p == .5:
            flags.append('NEUTRAL_PROBABILITY')
        if base_p in (0., 1.) or qb_p in (0., 1.):
            flags.append('LOGIT_UNAVAILABLE_AT_ENDPOINT')
        else:
            delta_logit = math.log(qb_p) - math.log1p(-qb_p) - math.log(base_p) + math.log1p(-base_p)
    contributions = _contributions(arms.get('base', {}), arms.get('qb', {}), base_p, qb_p) if valid else {'status': 'UNAVAILABLE_NOT_COMPARABLE'}
    if contributions['status'] == 'INCOMPLETE':
        flags.append('INCOMPLETE_CONTRIBUTION_TRACE')
    # Only inference/source fields are hashed: adding this report to a bundle
    # must not change its own identity on replay.
    source_projection = {k: v for k, v in bundle.items() if k != 'flip_diagnostics'}
    report = {'schema': VERSION, 'reporter_sha256': reporter_hash(),
              'status': 'COMPARABLE' if valid else 'NOT_COMPARABLE', 'source': _safe(source),
              'source_projection_sha256': _digest(_safe(source_projection)),
              'source_hash_scope': 'Canonical JSON of input bundle excluding flip_diagnostics; not a raw-file hash.',
              'gap_threshold_pp': float(gap_threshold_pp),
              'base': {'home_win_probability': base_p, 'pick': base_pick},
              'qb': {'home_win_probability': qb_p, 'pick': qb_pick},
              'pick_flip': flip, 'delta_pp': delta_pp, 'delta_logit': delta_logit,
              'flags': flags, 'contributions': contributions,
              'source_tags': _safe(bundle.get('tags', [])),
              'source_warnings': _safe(bundle.get('warnings', [])),
              'research_only': True, 'promotion_eligible': False, 'canonical_prospective_eligible': False,
              'market_input': False, 'market_input_scope': 'Diagnostic performs no market calculations; original source scope is preserved under source.',
              'action_authority': False,
              'interpretation': 'Diagnostics only; no probability, model selection, forecast or simulation changes.'}
    report['diagnostic_identity'] = _digest({'schema': VERSION, 'reporter_sha256': report['reporter_sha256'],
                                            'source': report['source'], 'gap_threshold_pp': float(gap_threshold_pp)})
    report['content_sha256'] = _digest(report)
    return report


def _validate_diagnostic(diagnostic):
    if not isinstance(diagnostic, dict) or diagnostic.get('schema') != VERSION:
        raise ValueError('DIAGNOSTIC_SCHEMA')
    payload = {k: v for k, v in diagnostic.items() if k != 'content_sha256'}
    if diagnostic.get('content_sha256') != _digest(payload):
        raise ValueError('DIAGNOSTIC_CONTENT_HASH')
    identity = _digest({'schema': VERSION, 'reporter_sha256': diagnostic.get('reporter_sha256'),
                        'source': diagnostic.get('source'), 'gap_threshold_pp': diagnostic.get('gap_threshold_pp')})
    if diagnostic.get('diagnostic_identity') != identity:
        raise ValueError('DIAGNOSTIC_IDENTITY_HASH')
    if (diagnostic.get('promotion_eligible') is not False or
            diagnostic.get('canonical_prospective_eligible') is not False or
            diagnostic.get('action_authority') is not False or diagnostic.get('market_input') is not False or
            diagnostic.get('research_only') is not True):
        raise ValueError('DIAGNOSTIC_SCOPE')


def append_flip_diagnostic(path, diagnostic):
    """Append once under a lock; reject conflicts/corruption before writing.

    The actual write time is evidence creation time, never backdated pregame
    registration. Retrospective observations are allowed and remain diagnostic.
    """
    _validate_diagnostic(diagnostic)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+', encoding='utf-8') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        previous, existing, seen = None, None, set()
        try:
            for line in handle:
                if not line.endswith('\n'):
                    raise ValueError('TRUNCATED_DIAGNOSTIC_RECORD')
                row = json.loads(line)
                claimed = row.get('record_hash')
                unsigned = {k: v for k, v in row.items() if k != 'record_hash'}
                if row.get('previous_hash') != previous or _digest(unsigned) != claimed:
                    raise ValueError('DIAGNOSTIC_CHAIN_INVALID')
                _validate_diagnostic(row['diagnostic'])
                key = row['diagnostic']['diagnostic_identity']
                if key in seen:
                    raise ValueError('DUPLICATE_DIAGNOSTIC_IDENTITY')
                seen.add(key)
                if key == diagnostic['diagnostic_identity']:
                    if row['diagnostic'] != diagnostic:
                        raise ValueError('DIAGNOSTIC_IDENTITY_CONFLICT')
                    existing = row
                previous = claimed
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError('DIAGNOSTIC_CHAIN_INVALID') from exc
        # Validate the *entire* stream before accepting an idempotent replay.
        if existing is not None:
            return {'appended': False, 'record': existing}
        now = dt.datetime.now(dt.timezone.utc)
        record = {'schema': 'nfl.flip_diagnostic_stream.v1', 'created_at_utc': now.isoformat(),
                  'evidence_role': 'DIAGNOSTIC_OBSERVATION_NOT_FORECAST_REGISTRATION',
                  'promotion_eligible': False, 'canonical_prospective_eligible': False,
                  'diagnostic': copy.deepcopy(diagnostic), 'previous_hash': previous}
        record['record_hash'] = _digest(record)
        handle.seek(0, os.SEEK_END)
        handle.write(json.dumps(record, sort_keys=True, allow_nan=False) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
        return {'appended': True, 'record': record}
