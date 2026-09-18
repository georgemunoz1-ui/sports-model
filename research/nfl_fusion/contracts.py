"""NFL metric/forecast boundary. Observations are not automatically model features."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import re
import numpy as np
import pandas as pd

ALIASES = {'JAC':'JAX','LAR':'LA','OAK':'LV','SD':'LAC','STL':'LA','WSH':'WAS'}
MARKET = ('vegas', 'spread', 'moneyline', 'odds', 'price', 'market', 'implied')
TARGETS = {'home_win':'HOME_NON_TIE_PROBABILITY', 'home_margin':'HOME_MINUS_AWAY_FINAL_POINTS',
           'total_points':'HOME_PLUS_AWAY_FINAL_POINTS'}

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def utc(value):
    stamp=datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if stamp.tzinfo is None: raise ValueError('TIMEZONE_REQUIRED')
    return stamp.astimezone(timezone.utc)

def canonical_team(team):
    if not isinstance(team,str) or not team: raise ValueError('TEAM_ID_REQUIRED')
    return ALIASES.get(team,team)

def fraction(value, unit):
    x=float(value)
    if unit=='PERCENT': x/=100
    elif unit!='FRACTION': raise ValueError('EXPLICIT_RATE_UNIT_REQUIRED')
    if not math.isfinite(x) or not 0<=x<=1: raise ValueError('RATE_OUT_OF_RANGE')
    return x

def home_probability(value,team,home,away):
    p=fraction(value,'FRACTION')
    home,away,team=map(canonical_team,(home,away,team))
    if home==away: raise ValueError('HOME_AWAY_COLLISION')
    if team==home:return p
    if team==away:return 1-p
    raise ValueError('PROBABILITY_TEAM_MISMATCH')

def point_targets(home,away):
    if any(type(x) not in (int,np.int64,np.int32) or x<0 for x in (home,away)):
        raise ValueError('FINAL_INTEGER_SCORES_REQUIRED')
    margin=int(home-away)
    return {'home_win':None if margin==0 else int(margin>0),'home_margin':margin,'total_points':int(home+away)}

def nflverse_spread_to_home_handicap(spread_line):
    """nflverse spread_line positive means HOME is favored; handicap is negative."""
    x=float(spread_line)
    if not math.isfinite(x):raise ValueError('INVALID_SPREAD')
    return -x

def metric_mean(values):
    d=pd.to_numeric(pd.Series(values),errors='coerce')
    good=d[np.isfinite(d)]
    return {'value':float(good.mean()) if len(good) else None,'observed_n':int(len(good)),
            'eligible_n':int(len(d)),'missing_n':int(len(d)-len(good))}

def require_receipt(receipt,cutoff,body=None):
    for k in ('source_url','sha256','retrieved_at_utc'):
        if not receipt.get(k):raise ValueError('SOURCE_RECEIPT_REQUIRED:'+k)
    if re.fullmatch('[a-f0-9]{64}',str(receipt['sha256'])) is None:raise ValueError('INVALID_SOURCE_HASH')
    if utc(receipt['retrieved_at_utc'])>utc(cutoff):raise ValueError('SOURCE_AFTER_CUTOFF')
    for k in ('published_at_utc','available_at_utc'):
        if receipt.get(k) and utc(receipt[k])>utc(cutoff):raise ValueError('SOURCE_AFTER_CUTOFF:'+k)
    if body is not None and hashlib.sha256(body).hexdigest()!=receipt['sha256']:
        raise ValueError('SOURCE_HASH_MISMATCH')

def validate_prediction_packet(packet,event_id,cutoff,target):
    """Mandatory same-event, same-target, same-information-cutoff ensemble admission."""
    if packet.get('event_id')!=event_id:raise ValueError('EVENT_MISMATCH')
    if packet.get('target')!=TARGETS[target]:raise ValueError('TARGET_OR_UNIT_MISMATCH')
    if packet.get('orientation')!='HOME':raise ValueError('ORIENTATION_MISMATCH')
    if packet.get('period')!='FULL_GAME_INCLUDING_OVERTIME':raise ValueError('PERIOD_MISMATCH')
    if utc(packet['information_cutoff_utc'])!=utc(cutoff):raise ValueError('CUTOFF_MISMATCH')
    if utc(packet['created_at_utc'])>=utc(packet['event_start_utc']):raise ValueError('NOT_PREGAME')
    if utc(cutoff)>utc(packet['created_at_utc']):raise ValueError('FUTURE_CUTOFF')
    if packet.get('market_input') is not False:raise ValueError('MARKET_FREE_REQUIRED')
    for k in ('model_artifact_sha256','feature_snapshot_sha256','source_manifest_sha256'):
        if re.fullmatch('[a-f0-9]{64}',str(packet.get(k,''))) is None:raise ValueError('PIN_REQUIRED:'+k)
    x=float(packet['value'])
    if not math.isfinite(x):raise ValueError('FINITE_PREDICTION_REQUIRED')
    if target=='home_win':fraction(x,'FRACTION')
    if target=='total_points' and x<0:raise ValueError('NEGATIVE_TOTAL')
    return x

def select_pbp_scope(pbp,schedule,cutoff,receipt,*,historical_rebuild=False):
    require_receipt(receipt,cutoff)
    required={'game_id','season','week','home_team','away_team','home_score','away_score'}
    if not required.issubset(schedule):raise ValueError('SCHEDULE_SCHEMA')
    if schedule.game_id.isna().any() or schedule.game_id.duplicated().any():raise ValueError('DUPLICATE_SCHEDULE_GAME')
    if pbp[['game_id','play_id']].isna().any().any() or pbp.duplicated(['game_id','play_id']).any():
        raise ValueError('DUPLICATE_OR_MISSING_PLAY_ID')
    complete=schedule[schedule.home_score.notna()&schedule.away_score.notna()]
    ids=set(complete.game_id);extra=sorted(set(pbp.game_id)-ids)
    receipt_scope={'expected_complete_game_ids':sorted(ids),'out_of_scope_game_ids':extra,
                   'accepted_game_count':len(ids & set(pbp.game_id)),'scope':'ONLY_REQUESTED_COMPLETED_GAMES'}
    if historical_rebuild and extra:raise ValueError('OUT_OF_SCOPE_HISTORICAL_PBP')
    selected=pbp[pbp.game_id.isin(ids)].copy()
    if ids-set(selected.game_id):raise ValueError('MISSING_COMPLETED_GAME')
    for game in complete.to_dict('records'):
        rows=selected[selected.game_id==game['game_id']]
        for key in ('season','week','home_team','away_team'):
            values=rows[key].dropna().unique()
            if len(values)!=1:raise ValueError('PBP_GAME_BINDING:'+key)
            left,right=values[0],game[key]
            if 'team' in key:left,right=canonical_team(left),canonical_team(right)
            if left!=right:raise ValueError('PBP_GAME_BINDING:'+key)
        order='order_sequence' if 'order_sequence' in rows else 'play_id'
        ordered=rows.sort_values(order)
        final=ordered[['total_home_score','total_away_score']].dropna()
        if final.empty or tuple(final.iloc[-1])!=(game['home_score'],game['away_score']):raise ValueError('FINAL_SCORE_MISMATCH')
    receipt_scope.update(accepted_rows=len(selected),excluded_rows=len(pbp)-len(selected))
    return selected,receipt_scope

def observations(pbp):
    """Postgame only. EPA is offense perspective; defense good = negative EPA allowed.

    All eligible denominators are retained. Null values are not zero-valued skill.
    No vegas_wp, same-game winner, final drive labels or source xYAC enters an
    automatically active predictive field.
    """
    d=pbp.copy()
    if 'no_play' not in d:d['no_play']=d.play_type.astype('string').str.lower().eq('no_play').fillna(False).astype('int8')
    ok=d.play_type.isin(['pass','run']) & d.no_play.fillna(0).eq(0) & d.qb_kneel.fillna(0).eq(0) & d.qb_spike.fillna(0).eq(0)
    if d.loc[ok,['posteam','defteam']].isna().any().any():raise ValueError('ELIGIBLE_PLAY_TEAM_ID_MISSING')
    d=d[ok].copy();rows=[]
    for (gid,team),p in d.groupby(['game_id','posteam'],sort=True):
        epa=metric_mean(p.epa)
        success=p.loc[p.epa.notna(),'epa'].gt(0).astype(float)
        r={'game_id':gid,'team':canonical_team(team),'offense_epa_per_play':epa,
           'success_rate':{'value':float(success.mean()) if len(success) else None,'observed_n':len(success),'eligible_n':len(p)},
           'pass_plays':int(p.play_type.eq('pass').sum()),'rush_plays':int(p.play_type.eq('run').sum()),
           'active_in_forecast':False,'lifecycle':'DATA_EXISTS_NOT_FITTED_ADDITIONAL_FEATURES'}
        defense=d[(d.game_id==gid)&(d.defteam.map(canonical_team)==canonical_team(team))]
        allowed=metric_mean(defense.epa)
        r['defense_epa_allowed_per_play']=allowed
        r['defense_epa_prevented_per_play']=-allowed['value'] if allowed['value'] is not None else None
        qb=p[p.qb_dropback.eq(1)&p.passer_player_id.notna()] if 'qb_dropback' in p else p.iloc[0:0]
        r['qb_dropback_epa']=metric_mean(qb.epa)
        if 'success' in p:
            m=p.success.notna()&p.epa.notna();r['success_source_mismatches']=int((p.loc[m,'success']!=p.loc[m,'epa'].gt(0).astype(float)).sum())
        rows.append(r)
    return rows

METRIC_DICTIONARY = {
 'epa':{'unit':'POINTS_PER_PLAY_OR_SUM_WITH_DENOMINATOR','perspective':'POSTEAM_OFFENSE','qb_epa_interchangeable':False},
 'success':{'unit':'FRACTION','definition':'EPA > 0; observed denominators retained'},
 'cpoe':{'unit':'PERCENTAGE_POINTS','divide_by_100_only_when_explicit':True},
 'snap_share':{'unit':'FRACTION','range':[0,1],'future_workload_known':False},
 'out_snap_sum':{'unit':'SUM_OF_PRIOR_ROLE_FRACTIONS','upper_bound':None},
 'pace':{'unit':'GAME_CLOCK_SECONDS_BETWEEN_ELIGIBLE_PLAYS','wall_clock_or_POE':False,'reset':['game','quarter','drive']},
 'qb_epa':{'unit':'SOURCE_QB_CREDIT_ADJUSTED_EPA','substitute_for_epa':False},
 'xyac':{'unit':'YARDS','upstream_model_vintage_verified':False},
 'rest':{'unit':'CALENDAR_DAYS','hours_not_days':False},
 'temperature':{'unit':'DEGREES_FAHRENHEIT'},
 'wind':{'unit':'MPH','sustained_not_gust':True},
 'travel':{'unit':'1000_KM_IN_CONTEXT_MODEL','actual_itinerary_verified':False},
 'spread_line':{'unit':'POINTS_HOME_FAVORITE_POSITIVE','feature_input_allowed':False},
 'home_margin':{'unit':'POINTS_HOME_MINUS_AWAY_INCLUDING_OT'},
 'win_probability':{'unit':'FRACTION','orientation':'HOME','tie_policy':'CONDITIONAL_NON_TIE'},
}
