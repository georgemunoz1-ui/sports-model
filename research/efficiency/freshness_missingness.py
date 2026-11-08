"""Missing-input evidence for the separate CFB personnel freshness procedure."""
import math
from pipelines.cards.missingness import seal_audit, verify_audit

PRODUCTS = ['p_home', 'home_margin']


def scope(receipt):
    component = receipt['component_receipt']
    return dict(league='cfb', event_id=receipt['event']['event_id'], model_id=component['model_id'],
                products=PRODUCTS, forecast={k:v for k,v in receipt.items()
                                             if k not in ('missingness_audit','receipt_sha256')})


def review(receipt, fitted, previous):
    forecast = receipt['component_receipt']['forecast']
    weekly = receipt['component_receipt']['inputs']['weekly_features']
    strict = receipt['freshness']['feature_values']
    features = forecast['input_snapshot']
    if set(features) != set(fitted['feature_names']) or any(features[k] != v for k,v in strict.items()):
        raise ValueError('CFB_FRESHNESS_MISSINGNESS_FEATURE_BINDING')
    registry = {}
    for i, name in enumerate(fitted['feature_names']):
        registry[name] = {'source':'EVENT_PERSONNEL' if name in strict else 'WEEKLY_TEAM_STATE',
            'value':features[name], 'imputed':features[name] is None,
            'fallback':'REFUSE_MISSING_PERSONNEL_EVIDENCE' if name in strict else 'WEEKLY_PRIOR_THEN_TRAINING_MEDIAN_IF_NULL',
            'median_by_head':{head:p['impute'][i] for head,p in fitted['fitted_model'].items()}}
    details = {'historical_support_by_source_season':None, 'reviewed_limits':None,
               'features':registry,'required_source_versions':receipt['freshness']['source_versions'],
               'comparison_status':'FIRST_REFRESH_NO_PAIRED_PREDECESSOR', 'model_version_delta':None,
               'simulation':'NO_SCORE_OR_SETTLEMENT_SAMPLER', 'calibration':'UNVALIDATED'}
    if previous is not None:
        old = previous['component_receipt']['forecast']
        if old['model_state_sha256'] != forecast['model_state_sha256'] or previous['component_receipt']['inputs']['weekly_features'] != weekly:
            raise ValueError('CFB_FRESHNESS_MISSINGNESS_PREDECESSOR_STATE_DRIFT')
        deltas = {}
        for head, product in [('winner','p_home'),('margin','home_margin')]:
            old_components, new_components = old['components'],forecast['components']
            intercept = head+'_intercept'
            if new_components[intercept] != old_components[intercept]:
                raise ValueError('CFB_FRESHNESS_MISSINGNESS_MODEL_DRIFT')
            changes = {'substantive':0., 'imputation_transition':0., 'unresolved':0.}
            before=after=new_components[intercept]
            for key in fitted['feature_names']:
                term=head+'_contribution_'+key
                a,b=old_components[term], new_components[term]
                before+=a
                after+=b
                if key in strict:
                    kind='substantive'
                elif old['input_snapshot'][key] is None or features[key] is None:
                    kind='imputation_transition'
                else:
                    kind='unresolved'
                changes[kind]+=b-a
            for x,pred in [(before,old[product]),(after,forecast[product])]:
                value=1/(1+math.exp(-x)) if head=='winner' else x
                if not math.isclose(value,pred,abs_tol=1e-10,rel_tol=0):
                    raise ValueError('CFB_FRESHNESS_MISSINGNESS_HEAD_REPLAY')
            deltas[product]={'units':'home_log_odds' if head=='winner' else 'points', **changes,
                             'before':old[product],'after':forecast[product],'linear_delta':after-before}
        details.update(comparison_status='SAME_FIT_SOURCE_BOUND_REFRESH', model_version_delta=0., heads=deltas)
    return seal_audit(**scope(receipt),details=details)


def check(receipt):
    if not verify_audit(receipt.get('missingness_audit'), **scope(receipt)):
        raise ValueError('CFB_FRESHNESS_MISSINGNESS_READBACK_FAILED')
