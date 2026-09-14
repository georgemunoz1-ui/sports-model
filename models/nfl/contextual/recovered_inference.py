"""Portable inference for the recovered fitted NFL model; market-free inputs.

This restores fitted coefficients rather than refitting or copying model opinions.
Personnel capture and fitted personnel impact are separate capabilities.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
TARGETS = ('home_win','home_margin','total_points')

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def utc(value):
    out=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if out.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return out.astimezone(dt.timezone.utc)

def predict(parameters, features):
    if set(features) != set(parameters['feature_names']):
        raise ValueError('EXACT_FEATURE_SCHEMA_REQUIRED')
    raw=np.array([np.nan if features[n] is None else features[n] for n in parameters['feature_names']],dtype=float)
    if np.isinf(raw).any():
        raise ValueError('INFINITE_FEATURE')
    values={};trace={}
    for target in TARGETS:
        head=parameters['heads'][target]
        x=np.where(np.isnan(raw),head['impute'],raw)
        contributions=(x-np.array(head['center']))/np.array(head['scale'])*np.array(head['coefficient'])
        linear=float(np.sum(contributions)+head['intercept'])
        values[target]=1/(1+math.exp(-linear)) if target=='home_win' else linear
        trace[target]={'intercept':head['intercept'],'linear_value':linear,'units':'LOG_ODDS' if target=='home_win' else 'POINTS','features':dict(zip(parameters['feature_names'],map(float,contributions))),'imputed':[n for n,v in zip(parameters['feature_names'],raw) if np.isnan(v)]}
    return {'prediction':values,'contribution_trace':trace}

def bind_context(parameters, baseline, context, cutoff, start):
    """Explicitly admit only fitted dimensions with source and time checks.

    No wholesale merge of a market/provider dictionary into model features.
    """
    if set(context)-{'weather','rest','personnel','travel'}:
        raise ValueError('UNKNOWN_CONTEXT_DIMENSION')
    if utc(cutoff)>=utc(start):
        raise ValueError('NOT_PREGAME')
    features={n:baseline[n] for n in parameters['feature_names']}
    admitted={};before=predict(parameters,features)
    for dimension,record in context.items():
        if not record.get('source') or not record.get('source_sha256'):
            raise ValueError('SOURCE_REQUIRED:'+dimension)
        if utc(record['retrieved_at_utc'])>utc(cutoff) or utc(record['available_by_utc'])>utc(cutoff):
            raise ValueError('POST_CUTOFF_INPUT:'+dimension)
        if record.get('published_at_utc') and utc(record['published_at_utc'])>utc(cutoff):
            raise ValueError('POST_CUTOFF_PUBLICATION:'+dimension)
        if record.get('event_id')!=baseline.get('game_id'):
            raise ValueError('EVENT_MISMATCH:'+dimension)
        if dimension=='weather':
            if utc(record['valid_from_utc'])>utc(start) or utc(start)>=utc(record['valid_to_utc']):
                raise ValueError('WEATHER_NOT_VALID_FOR_KICKOFF')
            if record['temperature_kind']!='HOURLY_FORECAST' or record['wind_kind']!='SUSTAINED':
                raise ValueError('WEATHER_QUANTITY_MISMATCH')
            for key in ('temperature_f','wind_mph'):
                if not math.isfinite(record[key]):
                    raise ValueError('INVALID_WEATHER')
                features[key]=record[key]
            features['weather_missing']=0.0
            admitted[dimension]={'status':'APPLIED_FITTED_FEATURES','spatial_scope':record['spatial_scope'],'input_fields':['temperature_f','wind_mph','weather_missing']}
        elif dimension=='rest':
            features['rest_days_diff']=record['home_rest']-record['away_rest'];features['rest_missing']=0.0
            admitted[dimension]={'status':'APPLIED_FITTED_FEATURES','definition':record['definition'],'input_fields':['rest_days_diff','rest_missing']}
        else:
            admitted[dimension]={'status':'BOUND_NO_RECOVERED_FITTED_TRANSFORM','state':record['state'],'numeric_adjustment':None}
    after=predict(parameters,features)
    changes={target:{name:after['contribution_trace'][target]['features'][name]-before['contribution_trace'][target]['features'][name] for name in parameters['feature_names'] if after['contribution_trace'][target]['features'][name]!=before['contribution_trace'][target]['features'][name]} for target in TARGETS}
    return {'features':features,'baseline':before,'current':after,'context_admission':admitted,'context_contribution_changes':changes}

def bernoulli_simulation(probability, identity, n=100000):
    seed=int(digest({'id':identity,'kind':'BERNOULLI_WINNER_DIAGNOSTIC','n':n})[:16],16)
    draws=(np.random.default_rng(seed).random(n)<probability).astype('u1')
    return draws,{'seed':seed,'count':n,'home_win_probability':float(draws.mean()),'mc_standard_error_pp':100*math.sqrt(probability*(1-probability)/n),'sha256':hashlib.sha256(draws.tobytes()).hexdigest(),'scope':'BINARY_NON_TIE_DIAGNOSTIC_NOT_INDEPENDENT_MODEL_VALIDATION'}
