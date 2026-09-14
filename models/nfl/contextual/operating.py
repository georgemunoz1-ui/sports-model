"""Explicit information regime and model selection; never a promotion registry."""
from __future__ import annotations
import math

RESEARCH_MODE = 'research_pregame'
MODE_STATUS = {
    RESEARCH_MODE: 'AVAILABLE_UNVALIDATED_RESEARCH',
    'official_pregame': 'NO_VALIDATED_MODEL_REGISTERED',
    'enhanced_pregame': 'NO_FITTED_MARKET_AWARE_MODEL_REGISTERED',
    'live': 'NO_FITTED_LIVE_MODEL_REGISTERED',
    'postgame_research': 'SEPARATE_HISTORICAL_EVALUATION_COMMANDS_ONLY',
}

def select(artifact, model_id, mode):
    if mode != RESEARCH_MODE:
        raise ValueError('MODE_UNAVAILABLE:' + str(mode) + ':' + MODE_STATUS.get(mode, 'UNKNOWN_MODE'))
    matches = [name for name, params in artifact['arms'].items() if params['model_id'] == model_id]
    if len(matches) != 1:
        raise ValueError('EXACT_MODEL_ID_REQUIRED_NO_FALLBACK:' + str(model_id))
    return matches[0]

def coverage(params, features, audit):
    names = params['feature_names']
    imputed = [n for n in names if features[n] is None or math.isnan(float(features[n]))]
    return {
        'matrix_columns_declared': len(names),
        'matrix_columns_supplied': len(names),
        'finite_before_imputation': len(names) - len(imputed),
        'imputed_feature_names': imputed,
        'fitted_nonzero_coefficients_by_head': {
            target: sum(float(v) != 0 for v in head['coefficient'])
            for target, head in params['heads'].items()
        },
        'matrix_coverage_is_not_source_completeness': True,
        'current_final_inactives': audit['final_inactives'],
        'workload_source': audit['workload'],
        'travel_source': audit['travel'],
        'missingness_indicators': {
            n: features[n] for n in names if any(s in n for s in ('missing', 'unknown'))
        },
    }
