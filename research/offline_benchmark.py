"""Offline evaluation primitives. No production imports, downloads, or promotion authority."""
import datetime as dt
import hashlib
import json
import math
import random
import re
import statistics as S


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def instant(value):
    x = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if x.tzinfo is None:
        raise ValueError('timezone required')
    return x.astimezone(dt.timezone.utc)


def finite(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError('finite numeric value required')
    return x


def validate_rows(rows, feature_names):
    """Flat numeric/null contract; timestamps apply to each feature, including missingness."""
    if not rows or not feature_names or len(set(feature_names)) != len(feature_names):
        raise ValueError('nonempty rows and unique features required')
    for name in feature_names:
        if re.search(r'odds|moneyline|spread|price|vig|market|outcome|label|result|closing', name, re.I):
            raise ValueError('forbidden feature: ' + name)
    seen = set()
    for row in rows:
        if row['id'] in seen:
            raise ValueError('duplicate event')
        seen.add(row['id'])
        cutoff, start = instant(row['cutoff']), instant(row['start'])
        if not cutoff < start:
            raise ValueError('cutoff must precede start')
        if set(row['features']) != set(feature_names) or set(row['known_at']) != set(feature_names):
            raise ValueError('feature contract mismatch')
        for key, value in row['features'].items():
            if instant(row['known_at'][key]) > cutoff:
                raise ValueError('post-cutoff feature')
            if value is not None:
                finite(value)
        finite(row['target'])
        if instant(row['target_known_at']) < start:
            raise ValueError('target available before event')
    return digest(rows)


def rolling_folds(rows, origins, horizon_days, holdout_start):
    """Expanding training; labels must be known strictly before each origin.

    All test cutoffs are in nonoverlapping UTC windows before the final holdout.
    Holdout rows are never returned. Origins and horizon must be predeclared.
    """
    if not isinstance(horizon_days, int) or horizon_days <= 0:
        raise ValueError('positive integer horizon required')
    points = [instant(x) for x in origins]
    end = instant(holdout_start)
    folds, used = [], set()
    for origin in points:
        stop = origin + dt.timedelta(days=horizon_days)
        if stop > end:
            raise ValueError('development window touches holdout')
        train = [r['id'] for r in rows if instant(r['cutoff']) < origin
                 and instant(r['target_known_at']) < origin]
        test = [r['id'] for r in rows if origin <= instant(r['cutoff']) < stop]
        if not train or not test or used.intersection(test):
            raise ValueError('empty or overlapping fold')
        used.update(test)
        folds.append({'origin': origin.isoformat(), 'train': train, 'test': test})
    if not folds or points != sorted(set(points)):
        raise ValueError('unique chronological origins required')
    return {'folds': folds, 'sha256': digest(folds), 'holdout_start': holdout_start}


def probability_scores(targets, probabilities):
    """Multiclass log loss/Brier; classes must have predeclared order (e.g. H/D/A).

    Brier is the SUM over classes (binary value is twice the home-only convention).
    Zero probability of the realized class is rejected rather than silently clipped.
    """
    if not targets or len(targets) != len(probabilities):
        raise ValueError('population mismatch')
    losses, briers = [], []
    width = len(probabilities[0])
    for y, p in zip(targets, probabilities):
        if width < 2 or len(p) != width or type(y) is not int or not 0 <= y < width:
            raise ValueError('class contract mismatch')
        if any(not 0 <= finite(v) <= 1 for v in p) or not math.isclose(sum(p), 1, abs_tol=1e-9):
            raise ValueError('invalid simplex')
        if p[y] == 0:
            raise ValueError('infinite log loss; explicit failure, no clipping')
        losses.append(-math.log(p[y]))
        briers.append(sum((v - int(j == y)) ** 2 for j, v in enumerate(p)))
    return {'n': len(targets), 'log_loss': S.mean(losses), 'brier_sum': S.mean(briers),
            'per_row_log_loss': losses}


def state_scores(targets, means, quantiles):
    if not targets or len(targets) != len(means) or len(targets) != len(quantiles):
        raise ValueError('population mismatch')
    errors, pinballs = [], []
    coverage, widths = {q: [] for q in (50, 80, 90)}, {q: [] for q in (50, 80, 90)}
    required = (.05, .1, .25, .5, .75, .9, .95)
    for y, mu, qs in zip(targets, means, quantiles):
        y, mu = finite(y), finite(mu)
        values = [finite(qs[q]) for q in required]
        if values != sorted(values):
            raise ValueError('crossing quantiles')
        errors.append(y - mu)
        for q, value in zip(required, values):
            e = y - value
            pinballs.append(max(q * e, (q - 1) * e))
        for c, lo, hi in ((50, .25, .75), (80, .1, .9), (90, .05, .95)):
            coverage[c].append(int(qs[lo] <= y <= qs[hi]))
            widths[c].append(qs[hi] - qs[lo])
    return {'n': len(errors), 'mae': S.mean(map(abs, errors)),
            'rmse': math.sqrt(S.mean(e * e for e in errors)), 'pinball': S.mean(pinballs),
            'coverage': {c: S.mean(v) for c, v in coverage.items()},
            'interval_width': {c: S.mean(v) for c, v in widths.items()}}


def paired_day_bootstrap(ids, dates, baseline, challenger, seed, draws=2000):
    """Paired date-cluster bootstrap; not a serial-correlation block bootstrap."""
    if len(set(ids)) != len(ids) or not ids or set(ids) != set(baseline) or set(ids) != set(challenger) or set(ids) != set(dates):
        raise ValueError('identical complete population required; failures may not be dropped')
    if type(draws) is not int or draws < 100:
        raise ValueError('at least 100 bootstrap draws required')
    groups = {}
    for key in ids:
        day = dt.date.fromisoformat(dates[key]).isoformat()
        groups.setdefault(day, []).append(finite(challenger[key]) - finite(baseline[key]))
    if len(groups) < 2:
        raise ValueError('at least two date clusters required')
    keys, rng, samples = sorted(groups), random.Random(seed), []
    for _ in range(draws):
        values = [v for key in rng.choices(keys, k=len(keys)) for v in groups[key]]
        samples.append(S.mean(values))
    samples.sort()
    return {'delta': S.mean(v for vs in groups.values() for v in vs),
            'ci95': [samples[int(.025 * (draws - 1))], samples[int(.975 * (draws - 1))]],
            'seed': seed, 'draws': draws, 'n_dates': len(keys), 'promotion_authority': False}


def intake_defects(record):
    required = ('model_id', 'checkpoint_id', 'revision', 'weights_sha256', 'license',
                'inference_code_revision', 'dependency_lock_sha256', 'feature_contract')
    bad = ['missing:' + key for key in required if not record.get(key)]
    for key in ('weights_sha256', 'dependency_lock_sha256'):
        if not re.fullmatch('[0-9a-f]{64}', str(record.get(key, ''))):
            bad.append('invalid_hash:' + key)
    for key in ('commercial_use_review', 'redistribution_review', 'data_handling_review'):
        if record.get(key) != 'PASS':
            bad.append('pending:' + key)
    if record.get('operational_use_approved') is not False:
        bad.append('operational access forbidden')
    return bad
