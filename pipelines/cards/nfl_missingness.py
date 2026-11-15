"""Pregame NFL missing-input audit outside the pinned numerical model and RNG.

All five linear arms share the same captured football inputs. Audit the fields
each head actually consumes; keep exact logit differences on the log-odds scale.
"""
from __future__ import annotations

import hashlib
import json
import math

from models.nfl.contextual.base_features import MODEL_FEATURES
from models.nfl.contextual.features import AVAIL_FEATURES, QB_FEATURES, TRAVEL_FEATURES, canonical, name_key
from models.nfl.contextual.recovered_inference import TARGETS, digest, predict, utc
from pipelines.cards.missingness import seal_audit, verify_audit

INDICATORS = {'rest_missing', 'location_missing', 'roof_missing', 'weather_missing',
              'report_missing_count', 'out_role_unknown_count', 'qb_unknown_count', 'travel_unknown'}
SCHEDULE = {'rest_days_diff', 'neutral_site', 'roof_indoor', 'temperature_f', 'wind_mph',
            'rest_missing', 'location_missing', 'roof_missing', 'weather_missing'}
FAMILIES = {
    'team_history': ('Weekly team state derived from completed games and plays',
                     'State prior, offseason decay and effective-history defaults'),
    'quarterback': ('Schedule QB identity and verified weekly QB state',
                    'Unseen identity gets zero sample, shrunk rating, and no change without prior identity'),
    'availability': ('Team injury and practice lists, supported reserves and prior same-team snap history',
                     'Missing reports yield zero counts and a separate report_missing_count; unknown role adds no snap weight'),
    'schedule': ('Cutoff-eligible schedule, or separately bound weather and rest observations',
                 'Incomplete rest, weather or venue can leave null inputs plus explicit indicators'),
    'travel': ('Schedule and registered airport lookup at the game date',
               'Unavailable route/body-clock inputs can yield zeroes plus travel_unknown'),
}


def family(name):
    if name in AVAIL_FEATURES:
        return 'availability'
    if name in QB_FEATURES:
        return 'quarterback'
    if name in TRAVEL_FEATURES:
        return 'travel'
    if name in SCHEDULE:
        return 'schedule'
    if name in MODEL_FEATURES:
        return 'team_history'
    return 'UNMAPPED'


def binding(bundle):
    """Small, reproducible binding to the actual numeric state and target laws."""
    fields = (
        'event', 'cutoff_utc', 'mode', 'model_id', 'identity', 'identity_semantics',
        'model_artifact_sha256', 'code_hashes', 'mode_code_hashes', 'forecast_procedure_id',
        'feature_procedure_id', 'calibration_procedure_id', 'numerical_identity',
        'features', 'arms', 'selected_arm', 'prediction', 'score_centers', 'contribution_trace',
        'audit', 'assimilation', 'market_input', 'market_snapshot', 'live_snapshot',
        'market_benchmark', 'football_reference', 'joint_distribution', 'score_simulation',
        'winner_simulation', 'action_authority', 'canonical_prospective_eligible',
    )
    return dict(league='nfl', event_id=bundle['event']['event_id'], model_id=bundle['model_id'],
                products=sorted(bundle['prediction']), forecast={k:bundle.get(k) for k in fields})



def read_prior(path, sha256):
    if not path and not sha256:
        return None
    if not path or not sha256:
        raise ValueError('NFL_MISSINGNESS_PRIOR_AND_PIN_REQUIRED')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha256:
        raise ValueError('NFL_MISSINGNESS_PRIOR_HASH_MISMATCH')
    return json.loads(raw)


def compare_context(current, prior):
    if prior is None:
        return 'PRIOR_NOT_SUPPLIED'
    if prior['event'] != current['event'] or utc(prior['cutoff_utc']) > utc(current['cutoff_utc']):
        return 'PRIOR_EVENT_OR_CHRONOLOGY_MISMATCH'
    if (prior.get('model_id'), prior.get('mode'), prior.get('model_artifact_sha256')) != (
            current['model_id'], current.get('mode'), current['model_artifact_sha256']):
        return 'MODEL_OR_MODE_CHANGED'
    if (prior.get('code_hashes'), prior.get('mode_code_hashes')) != (current.get('code_hashes'), current.get('mode_code_hashes')):
        return 'FEATURE_OR_MODEL_PROCEDURE_CHANGED'
    return 'PAIRED'


def report_states(bundle):
    admission = bundle.get('audit', {}).get('recovered_model', {}).get('context_admission', {})
    personnel = admission.get('personnel', {}).get('state', {})
    sources = personnel.get('injury_observations') or []
    reserves = personnel.get('reserve_absences') or []
    by_team = {}
    names, ids = set(), set()
    for row in [*sources, *reserves]:
        name = (canonical(row['team']), name_key(row['player']))
        player_id = (name[0], row.get('player_id'))
        if name in names or (player_id[1] is not None and player_id in ids):
            raise ValueError('NFL_MISSINGNESS_DUPLICATE_PERSONNEL_OBSERVATION')
        names.add(name)
        ids.add(player_id)
    source_state = personnel.get('report_status')
    for team in (bundle['event']['home_team'], bundle['event']['away_team']):
        observed = sum(canonical(r['team']) == canonical(team) for r in sources)
        reserve = sum(canonical(r['team']) == canonical(team) for r in reserves)
        state = 'UNRESOLVED_IDENTITY_OR_COVERAGE'
        if source_state in {'ACQUISITION_FAILURE', 'TIMEOUT', 'NOT_ACQUIRED'}:
            state = 'ACQUISITION_FAILURE' if source_state != 'NOT_ACQUIRED' else 'UNRESOLVED_IDENTITY_OR_COVERAGE'
        elif source_state == 'NOT_YET_PUBLISHED':
            state = source_state
        by_team[team] = {'observations': observed, 'reserves': reserve, 'coverage_state': state,
                         'records_received': bool(observed or reserve),
                         'complete_team_absence_verified': False}
    final = bundle.get('audit', {}).get('final_availability', {})
    final_states = {}
    for team in by_team:
        if final.get('status') == 'VERIFIED':
            listed = sum(row['team'] == team for row in final['players'])
            final_states[team] = {'state': 'VERIFIED_OBSERVATION' if listed else 'VERIFIED_ABSENCE',
                                  'listed_count': listed, 'evidence_scope':'NATIVE_VALIDATED_INACTIVE_LIST_ONLY'}
        else:
            final_states[team] = {'state': 'UNRESOLVED_IDENTITY_OR_COVERAGE', 'listed_count': None}
    return {'team_reports': by_team, 'final_inactive_lists': final_states, 'supplied_report_status': personnel.get('report_status'),
            'inactive_list_status': bundle.get('audit', {}).get('final_inactives'),
            'verified_empty_team_report': 'REQUIRES_SEPARATE_COMPLETE_SOURCE_EVIDENCE',
            'source_failure_or_missing_report_implies_healthy': False}


def arm_evidence(bundle, params, arm):
    names = params['feature_names']
    raw = {name: bundle['features'][name] for name in names}
    recalculated = predict(params, raw)
    stored = bundle['arms'][arm]
    if any(not math.isclose(recalculated['prediction'][t], stored['prediction'][t], abs_tol=1e-12, rel_tol=0)
           for t in TARGETS):
        raise ValueError('NFL_MISSINGNESS_HEAD_REPLAY_MISMATCH:' + arm)
    return raw, recalculated


def driver_group(name, before, after, current, prior):
    if name in INDICATORS or before is None or after is None:
        return 'missingness_imputation'
    if family(name) == 'availability' and any(
        current['features'][k] != prior['features'][k] for k in ('report_missing_count', 'out_role_unknown_count')):
        return 'observation_or_reporting_interaction'
    if family(name) in {'quarterback','travel','team_history','UNMAPPED'}:
        return 'observation_or_reporting_interaction'
    return 'observed_feature_change'


def comparison(params, raw, now, previous_raw, previous, current, prior):
    out = {}
    for head in TARGETS:
        groups = {'missingness_imputation': 0., 'observation_or_reporting_interaction': 0., 'observed_feature_change': 0.}
        changes = []
        for name in params['feature_names']:
            a, b = previous_raw[name], raw[name]
            if a == b:
                continue
            group = driver_group(name, a, b, current, prior)
            change = now['contribution_trace'][head]['features'][name] - previous['contribution_trace'][head]['features'][name]
            changes.append({'feature': name, 'from': a, 'to': b, 'contribution_delta': change, 'group': group})
            groups[group] += change
        delta = now['contribution_trace'][head]['linear_value'] - previous['contribution_trace'][head]['linear_value']
        if not math.isclose(sum(groups.values()), delta, rel_tol=0, abs_tol=1e-10):
            raise ValueError('NFL_MISSINGNESS_DECOMPOSITION_FAILED:' + head)
        presence = sum(c['contribution_delta'] for c in changes if c['feature'] == 'report_missing_count')
        # Compare the indicator to all other terms NET, allowing cancellation. This
        # is not an approved sensitivity limit or a model-release criterion.
        dominated = presence * delta > 0 and abs(presence) > abs(delta - presence)
        out[head] = {'units': 'home_log_odds' if head == 'home_win' else 'points',
                     'before': previous['prediction'][head], 'after': now['prediction'][head],
                     'output_delta': now['prediction'][head] - previous['prediction'][head],
                     'linear_delta': delta, 'model_version_delta': 0., **groups,
                     'reporting_presence_delta': presence, 'reporting_state_dominated': dominated,
                     'gross_abs_feature_change': sum(abs(c['contribution_delta']) for c in changes),
                     'changed_features': changes}
    return out


def report_count_support(params, current, prior):
    """Recover integer counts of 0/1/2 missing team reports from fitted moments.

    The training constructor emits this count on every row. StandardScaler
    stores a population SD, replacing zero with 1 for a constant dimension.
    Only publish counts when they uniquely reproduce both stored moments.
    """
    name = 'report_missing_count'
    if name not in params['feature_names']:
        return None
    i = params['feature_names'].index(name)
    n = params['training_rows']
    head = params['heads']['home_win']
    mu, scale = head['center'][i], head['scale'][i]
    # E[X(X-1)] = 2 P(X=2). Check also the possible constant case.
    solutions = set()
    for variance in ([0., 1.] if scale == 1 else [scale ** 2]):
        n2 = round(n * (variance + mu ** 2 - mu) / 2)
        n1 = round(n * mu - 2 * n2)
        counts = (n - n1 - n2, n1, n2)
        if min(counts) < 0:
            continue
        m = (n1 + 2*n2)/n
        sd = math.sqrt(sum(c*(k-m)**2 for k,c in enumerate(counts))/n)
        if math.isclose(m,mu,abs_tol=1e-12,rel_tol=0) and math.isclose(sd or 1.,scale,abs_tol=1e-12,rel_tol=0):
            solutions.add(counts)
    if len(solutions) != 1:
        return {'status':'UNIDENTIFIED_FROM_FITTED_MOMENTS'}
    counts, = solutions
    def training_count(value):
        return counts[int(value)] if value in (0, 1, 2) else None
    return {'status':'RECONSTRUCTED_FROM_BOUND_TRAINING_MOMENTS', 'training_rows':n,
            'training_seasons':params['training_seasons'], 'mean':mu, 'scaler_scale':scale,
            'counts_by_missing_teams':dict(zip(('0','1','2'),counts)),
            'current_value':current, 'training_count_at_current':training_count(current),
            'prior_value':prior, 'training_count_at_prior':training_count(prior)}


def details_for(bundle, artifact, previous=None):
    paired = compare_context(bundle, previous)
    details = {'comparison_status': paired, 'method': 'EXACT_FITTED_LINEAR_TERMS_WITH_INVERSE_LOGIT_WINNER',
               'prediction_scope': bundle.get('mode'), 'selected_arm': bundle.get('selected_arm'),
               'joint_law_attribution':'Separate nonlinear score kernel; no additive attribution or inherited settlement qualification.',
               'prior_identity': previous.get('identity') if previous else None,
               'prior_artifact_sha256': previous.get('model_artifact_sha256') if previous else None,
               'current_artifact_sha256': bundle['model_artifact_sha256'], 'sources': report_states(bundle),
               'historical_missingness_by_source_season': None, 'reviewed_product_limits': None,
               'freshness': 'Week-bound pregame state; admitted input available by cutoff. Separate source freshness limits require review.',
               'fitted_imputation': 'Per-head training median (SimpleImputer), applied before scaling. Raw null and effective median are separate.',
               'fallback_policy': 'Retain the independent research forecast. Product review pending.',
               'feature_families': FAMILIES, 'arms': {}, 'unmapped_features': [],
               'dominance_definition': 'Reporting-presence contribution is aligned with net movement and exceeds the absolute net movement of the remaining terms; descriptive only.'}
    mode = bundle.get('mode')
    if mode == 'live':
        details.update(method='STRICT_FULL_STATE_NO_LIVE_INPUT_IMPUTATION', comparison_status='LIVE_INTERACTIONS_UNRESOLVED',
                       required_state={name: value for name,value in bundle['features'].items()},
                       source_policy='Pregame two-sided market and complete authenticated PRE_PLAY state; stale, partial or missing fields refuse.',
                       current_contract='Categorical final outcome including overtime; no live spread or total head.',
                       historical_support=None, unresolved_interactions='Tree decision paths and changes in score/time/possession are joint. No attribution estimated.')
        return details
    if mode == 'enhanced_pregame':
        terms = bundle['contribution_trace']
        details.update(method='EXACT_WEIGHTED_FOOTBALL_AND_MARKET_INPUTS', comparison_status=paired,
                       components=terms, source_policy='Exact pregame moneyline pair, spread and total required. No dropped ensemble member fallback.',
                       historical_support=None,
                       unresolved_interactions='Football term includes fitted missingness effects; internal shares require a bound football-only comparison.')
        if paired == 'PAIRED':
            details['ensemble_changes']={}
            for target, term in terms.items():
                old = previous['contribution_trace'][target]
                football = term['football_term'] - old['football_term']
                market = term['market_term'] - old['market_term']
                delta = bundle['prediction'][target] - previous['prediction'][target]
                if not math.isclose(delta, football + market, abs_tol=1e-10, rel_tol=0):
                    raise ValueError('NFL_ENSEMBLE_ATTRIBUTION_NOT_RECONCILED')
                details['ensemble_changes'][target]={'total_delta':delta, 'football_delta':football, 'market_delta':market}
        return details
    if mode != 'research_pregame' or not artifact or digest(artifact) != bundle.get('model_artifact_sha256'):
        details.update(comparison_status='MODE_OR_FIT_UNSUPPORTED', method='DECOMPOSITION_UNAVAILABLE')
        return details
    for arm, params in artifact['arms'].items():
        raw, fitted = arm_evidence(bundle, params, arm)
        registry = {}
        for i, name in enumerate(params['feature_names']):
            group = family(name)
            if group == 'UNMAPPED':
                details['unmapped_features'].append([arm, name])
            # At the fitted head's center a derivative times one unit isolates
            # that input. Never interpret such a perturbation as a player effect.
            registry[name] = {'family': group, 'indicator': name in INDICATORS,
                              'raw': raw[name], 'imputed': raw[name] is None,
                              'heads': {target: {'median': params['heads'][target]['impute'][i],
                                 'training_center_after_imputation': params['heads'][target]['center'][i],
                                 'training_scale_after_imputation': params['heads'][target]['scale'][i],
                                 'unit_shift_on_linear_scale': params['heads'][target]['coefficient'][i] / params['heads'][target]['scale'][i]}
                                        for target in TARGETS}}
        data = {'model_id': params['model_id'], 'features': registry,
                'report_count_support':report_count_support(params,raw.get('report_missing_count'),
                          previous['features'].get('report_missing_count') if paired == 'PAIRED' else None)}
        if paired == 'PAIRED':
            previous_raw, prev = arm_evidence(previous, params, arm)
            data['changes'] = comparison(params, raw, fitted, previous_raw, prev, bundle, previous)
        details['arms'][arm] = data
    if paired == 'PAIRED':
        details['simulation'] = {'winner_before': previous['winner_simulation'], 'winner_after': bundle['winner_simulation'],
                                 'score_law_before': (previous.get('joint_distribution') or {}).get('measure_sha256'),
                                 'score_law_after': (bundle.get('joint_distribution') or {}).get('measure_sha256')}
    return details


def audit(bundle, artifact, previous=None, *, prior_file_sha256=None):
    evidence = details_for(bundle, artifact, previous)
    evidence['prior_file_sha256'] = prior_file_sha256
    return seal_audit(**binding(bundle), details=evidence)


def verify(bundle):
    return verify_audit(bundle.get('missingness_audit'), **binding(bundle))


def _row_binding(row, cutoff):
    return dict(league='nfl', event_id=row['event_id'], model_id=row.get('model_id') or 'nfl.unavailable',
                products=['home_margin', 'home_win', 'total_points'],
                forecast={'cutoff':utc(cutoff).isoformat(),
                          'row':{k:v for k,v in row.items() if k != 'missingness_audit'}})


def seal_native_card_row(row, cutoff, details):
    return seal_audit(**_row_binding(row, cutoff), details=details)


def verify_native_card_row(row, *, cutoff):
    return verify_audit(row.get('missingness_audit'), **_row_binding(row, cutoff))


def persist_child_review(folder, parent, child, products, *, name='missingness_audit.json'):
    """A child's residual/settlement law has its own release gate.

    A hash-pinned legacy parent can be replayed in research; it cannot furnish
    a checked missingness receipt for a new release.
    """
    model_id = child.get('model_id') or child.get('calibrator_id')
    if not model_id:
        raise ValueError('NFL_CHILD_MODEL_SCOPE_REQUIRED')
    verified_parent = bool(parent.get('missingness_audit')) and verify(parent)
    scope = dict(league='nfl', event_id=parent['event']['event_id'], model_id=model_id,
                 products=products, forecast={'parent_id': parent['identity'], 'child': digest(child)})
    details = {'parent_receipt_verified': verified_parent,
               'parent_receipt_sha256': (parent.get('missingness_audit') or {}).get('receipt_sha256'),
               'comparison_status': 'CHILD_SENSITIVITY_NOT_ESTABLISHED',
               'historical_missingness_by_source_season': None, 'reviewed_product_limits': None,
               'unresolved_interactions':'Residual distribution, score translation and settlement are child-specific.'}
    result = seal_audit(**scope, details=details)
    path = folder / name
    with path.open('x') as out:
        json.dump(result, out, indent=2, allow_nan=False)
    if not verify_audit(json.loads(path.read_bytes()), **scope):
        raise ValueError('NFL_CHILD_MISSINGNESS_READBACK_FAILED')
    return result
