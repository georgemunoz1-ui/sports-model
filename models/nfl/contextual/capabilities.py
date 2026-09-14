"""Inference-derived capability evidence. Contributions are diagnostics, not causes."""
from __future__ import annotations
import math
from pathlib import Path
import hashlib
from .recovered_inference import digest, utc

VERSION = 'nfl.capabilities.v1'
METHODS = {'exact_centered_linear_term', 'exact_weighted_ensemble_term',
           'paired_monte_carlo_counterfactual', 'exact_deterministic_counterfactual', 'not_applied'}

def reporter_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def group(name):
    if name.startswith('qb_'): return 'qb_history'
    if name.startswith('away_') or name == 'travel_unknown': return 'travel_proxy'
    if name[0].isupper() or name in {'report_missing_count','out_role_unknown_count'}: return 'personnel_workload_proxy'
    if name in {'temperature_f','wind_mph','weather_missing'}: return 'weather'
    if name in {'rest_days_diff','rest_missing','neutral_site','roof_indoor','location_missing','roof_missing'}: return 'rest_venue'
    return 'historical_team_state'

def validate_report(report):
    if report['reporter_sha256'] != reporter_hash(): raise ValueError('REPORTER_HASH_MISMATCH')
    if len({r['feature'] for r in report['rows']}) != len(report['rows']): raise ValueError('DUPLICATE_CAPABILITY')
    for r in report['rows']:
        if r['contribution_method'] not in METHODS: raise ValueError('CONTRIBUTION_METHOD')
        if r['active_in_run']:
            if not r['implemented'] or not r['fitted_artifact_available']: raise ValueError('ACTIVE_WITHOUT_FITTED_IMPLEMENTATION')
            if r['value_status'] in {'missing','rejected','captured_not_numeric'}: raise ValueError('ACTIVE_MISSING_VALUE')
            if not r['pregame_eligible']: raise ValueError('ACTIVE_INELIGIBLE_INPUT')
            if not r['contribution'] or r['contribution_method']=='not_applied': raise ValueError('ACTIVE_WITHOUT_CONTRIBUTION')
            if not all(math.isfinite(float(x)) for x in r['contribution'].values()): raise ValueError('NONFINITE_CONTRIBUTION')
        elif not r.get('exclusion_reason'): raise ValueError('INACTIVE_WITHOUT_REASON')
        if r['contribution_method']=='paired_monte_carlo_counterfactual':
            u=r.get('uncertainty') or {}
            if not u.get('paired'): raise ValueError('PAIRED_MC_UNCERTAINTY_REQUIRED')
            if u.get('estimator') != 'mean_paired_outcome_difference': raise ValueError('MC_ESTIMATOR_REQUIRED')
            if type(u.get('n_draws')) is not int or u['n_draws'] < 2: raise ValueError('MC_DRAW_COUNT_REQUIRED')
            se=u.get('standard_error')
            if not isinstance(se,dict) or set(se)!=set(r['contribution']): raise ValueError('MC_STANDARD_ERROR_REQUIRED')
            if any(not math.isfinite(float(v)) or float(v)<0 for v in se.values()): raise ValueError('MC_STANDARD_ERROR_INVALID')
            if u.get('uncertainty_scope') != 'monte_carlo_only': raise ValueError('MC_UNCERTAINTY_SCOPE_REQUIRED')
    digest(report)  # Reject non-JSON/nonfinite evidence.
    return report

def describe_run_capabilities(params, features, context, base, cutoff, event, artifact_hash, trace):
    rows=[]
    for name in params['feature_names']:
        g=group(name); source_key={'weather':'weather','rest_venue':'rest','qb_history':'personnel','personnel_workload_proxy':'personnel','travel_proxy':'travel'}.get(g)
        source=context.get(source_key,{}) if source_key else {}
        age=(utc(cutoff)-utc(source['retrieved_at_utc'])).total_seconds() if source else None
        eligible=all(utc(source[t])<=utc(cutoff) for t in ['retrieved_at_utc','available_by_utc','published_at_utc'] if source.get(t))
        missing=features[name] is None or not math.isfinite(float(features[name]))
        status='imputed' if missing else ('proxy' if g in {'travel_proxy','personnel_workload_proxy'} else 'derived')
        fresh=None if age is None else age <= (21600 if g=='weather' else 86400)
        terms={t:trace[t]['features'][name] for t in trace}
        rows.append({'feature':name,'feature_group':g,'implemented':True,'transform_version':'nfl.integrated_context.v1',
          'fitted_artifact_available':True,'source_available':bool(source) or g=='historical_team_state','source_fresh':fresh,
          'pregame_eligible':eligible,'value_status':status,'raw_value':None if missing else features[name],
          'active_in_run':True,'contribution_method':'exact_centered_linear_term','contribution':terms,
          'contribution_units':{'home_win':'log_odds','home_margin':'points','total_points':'points'},
          'uncertainty':{'monte_carlo_error':0,'parameter_uncertainty':'not_estimated'},'exclusion_reason':None,
          'source_age_seconds':age,'freshness_policy':'weather_6h_other_current_24h; historical states use weekly eligibility',
          'lineage':{'source_sha256':source.get('source_sha256'),'model_artifact_sha256':artifact_hash,
          'feature_value_sha256':digest(features[name] if not missing else None),'base_state_row_sha256':digest(base),
          'state_reconstruction':base.get('state_lineage') if g=='historical_team_state' else None},
          'limitations':['historical EPA state uses prior completed weeks'] if g=='historical_team_state' else []})
    rows.append({'feature':'confirmed_future_workload','feature_group':'personnel_workload_proxy','implemented':False,
      'fitted_artifact_available':False,'source_available':False,'source_fresh':None,'pregame_eligible':False,
      'value_status':'missing','active_in_run':False,'contribution_method':'not_applied','contribution':None,
      'exclusion_reason':'prior_snap_proxy_is_not_confirmed_future_workload'})
    return validate_report({'schema':VERSION,'reporter_sha256':reporter_hash(),'model_id':params['model_id'],
      'event_id':event['event_id'],'cutoff_utc':cutoff,'rows':rows,'matrix_features':len(params['feature_names']),
      'active_matrix_features':sum(r['active_in_run'] for r in rows),'stale_active_features':[r['feature'] for r in rows if r['active_in_run'] and r['source_fresh'] is False],
      'freshness_enforcement':'reported; existing research admission policy retained',
      'source_completeness_verified':False,'simulation_contract_contributions':'not_estimated',
      'interpretation':'Centered coefficient terms; exact for fitted linear/logistic heads, not causal effects or cover-probability contributions.'})

def describe_ensemble(football_report, model, prediction, market, event, cutoff):
    rows=[]
    for source in ['football','market']:
        terms={t:(model['weights'][t] if source=='football' else 1-model['weights'][t])*(prediction[t] if source=='football' else market[t]) for t in prediction}
        rows.append({'feature':source,'feature_group':source,'implemented':True,'fitted_artifact_available':True,
          'source_available':True,'source_fresh':None,'pregame_eligible':True,'value_status':'derived','active_in_run':True,
          'contribution_method':'exact_weighted_ensemble_term','contribution':terms,'exclusion_reason':None,
          'contribution_units':{'home_win':'probability','home_margin':'points','total_points':'points'}})
    return validate_report({'schema':VERSION,'reporter_sha256':reporter_hash(),'model_id':model['model_id'],
      'event_id':event['event_id'],'cutoff_utc':cutoff,'rows':rows,'upstream_football_report':football_report,
      'football_weights':model['weights'],'interpretation':'Zero football weights mean no incremental football influence on that head.'})
