"""Append-only QB-margin research grades, separate from canonical/weekly state.

Immutable hash-addressed records + atomic HEAD under an exclusive lock. A grade
requires matching nflverse final scores/starters and an official ESPN final.
"""
import datetime as dt
import fcntl
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import numpy as np
import pandas as pd
from . import qb_margin as base, qb_margin_calibration as cal
from .recovered_inference import digest, utc
from .weekly_state import _put, _get, _head, _publish, _frame, SCHEDULE_URL


def records(store):
    key = _head(store); result = []; seen = set()
    while key:
        if key in seen: raise ValueError('RESEARCH_LEDGER_CYCLE')
        seen.add(key); r = _get(store, key)
        if r.get('schema') != 'nfl.qb_margin_research_record.v1' or r.get('kind') not in {'REGISTER', 'GRADE'}:
            raise ValueError('RESEARCH_LEDGER_SCHEMA')
        result.append(r); key = r['parent']
    return list(reversed(result))


def _append(store, kind, identity, payload):
    store = Path(store); store.mkdir(parents=True, exist_ok=True)
    with (store/'LOCK').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        history = records(store)
        prior = [r for r in history if r['kind'] == kind and r['forecast_identity'] == identity]
        if prior:
            if prior[0]['payload'] != payload: raise ValueError('RESEARCH_LEDGER_CONFLICT')
            return {'status': 'ALREADY_RECORDED', 'head': _head(store)}
        if kind == 'GRADE' and not any(r['kind'] == 'REGISTER' and r['forecast_identity'] == identity for r in history):
            raise ValueError('RESEARCH_GRADE_UNREGISTERED')
        now = dt.datetime.now(dt.timezone.utc)
        if kind == 'REGISTER' and now >= utc(payload['forecast']['event']['start_time_utc']):
            raise ValueError('RESEARCH_REGISTRATION_AFTER_START')
        r = {'schema': 'nfl.qb_margin_research_record.v1', 'parent': _head(store), 'kind': kind,
             'forecast_identity': identity, 'written_at_utc': now.isoformat(), 'payload': payload}
        key = _put(store, r); _publish(store, key)
        return {'status': 'APPENDED', 'head': key}


def register(store, folder, parent, *, quarterback_conditions, home_handicaps=()):
    folder = Path(folder); manifest = json.loads((folder/'manifest.json').read_text())
    if not {'forecast.json', 'margin_draws.npy', 'registration.jsonl'} <= manifest.keys():
        raise ValueError('RESEARCH_FREEZE_MANIFEST_REQUIRED')
    for name, expected in manifest.items():
        if Path(name).name != name or base.file_sha(folder/name) != expected:
            raise ValueError('RESEARCH_FREEZE_HASH')
    f = json.loads((folder/'forecast.json').read_text()); d = np.load(folder/'margin_draws.npy', allow_pickle=False)
    from .research_board import board
    board(parent, f, d, home_handicaps=home_handicaps)  # Independent source/draw/line firewall.
    old = json.loads((folder/'registration.jsonl').read_text()); old_hash = old.pop('record_hash')
    if digest(old) != old_hash or old['forecast_identity'] != f['identity'] or old['model_id'] != f['model_id']:
        raise ValueError('RESEARCH_REGISTRATION_BINDING')
    now = dt.datetime.now(dt.timezone.utc)
    if not utc(f['information_cutoff_utc']) <= utc(old['created_at_utc']) <= now or utc(old['created_at_utc']) >= utc(f['event']['start_time_utc']):
        raise ValueError('RESEARCH_REGISTRATION_CHRONOLOGY')
    if f['market_input'] is not False or f['action_authority'] is not False or f['canonical_prospective_eligible'] is not False:
        raise ValueError('RESEARCH_ONLY_FIREWALL')
    # Reconstruct the exact registered distribution and identity, independently of files.
    if f['model_id'] == cal.MODEL_ID:
        rebuilt, replay = cal.build(parent, n=len(d))
    elif f['model_id'] == base.MODEL_ID:
        rebuilt, replay = base.build(parent, n=len(d))
    else: raise ValueError('UNREGISTERED_MARGIN_MODEL')
    if rebuilt['identity'] != f['identity'] or rebuilt['margin_support'] != f['margin_support'] or rebuilt['margin_weights'] != f['margin_weights'] or not np.array_equal(replay, d):
        raise ValueError('RESEARCH_FORECAST_REPLAY')
    teams = {f['event']['home_team'], f['event']['away_team']}
    if set(quarterback_conditions) != teams or any(not isinstance(x, str) or not x.startswith('00-') for x in quarterback_conditions.values()):
        raise ValueError('SOURCE_BOUND_QB_CONDITIONS_REQUIRED')
    unique, counts = np.unique(d, return_counts=True)
    payload = {'forecast': f, 'forecast_file_sha256': manifest['forecast.json'],
        'freeze_manifest': manifest, 'parent_forecast_sha256': digest(parent),
        'quarterback_conditions': quarterback_conditions, 'home_handicaps': sorted(set(home_handicaps)),
        'simulation_counts': {'support': unique.tolist(), 'counts': counts.tolist()},
        'canonical_prospective_eligible': False, 'primary_model_grading': False,
        'research_grading_enabled': True, 'action_authority': False}
    return _append(store, 'REGISTER', f['identity'], payload)


def _official_final(raw, receipt, event, now):
    if hashlib.sha256(raw).hexdigest() != receipt['sha256'] or utc(receipt['retrieved_at_utc']) > now:
        raise ValueError('OFFICIAL_FINAL_SOURCE_HASH_TIME')
    url = urlparse(receipt['source_url'])
    if url.scheme != 'https' or url.hostname != 'site.api.espn.com' or url.path != '/apis/site/v2/sports/football/nfl/summary' or not parse_qs(url.query).get('event'):
        raise ValueError('OFFICIAL_FINAL_SOURCE_IDENTITY')
    data = json.loads(raw)
    if str(data['header']['id']) != parse_qs(url.query)['event'][0]: raise ValueError('OFFICIAL_FINAL_EVENT_ID')
    comp = data['header']['competitions'][0]
    if not comp['status']['type']['completed'] or comp['status']['type']['state'] != 'post':
        raise ValueError('OFFICIAL_EVENT_NOT_FINAL')
    if utc(comp['date']) != utc(event['start_time_utc']): raise ValueError('OFFICIAL_EVENT_START_MISMATCH')
    scores = {}
    for team in comp['competitors']:
        side = team['homeAway']; abbreviation = team['team']['abbreviation']
        if side not in {'home', 'away'} or abbreviation != event[side+'_team'] or side in scores:
            raise ValueError('OFFICIAL_FINAL_TEAM_MISMATCH')
        score = float(team['score'])
        if not np.isfinite(score) or score < 0 or score != int(score): raise ValueError('OFFICIAL_FINAL_SCORE')
        scores[side] = int(score)
    if set(scores) != {'home', 'away'}: raise ValueError('OFFICIAL_FINAL_TEAM_COVERAGE')
    return scores


def grade_event(store, event_id, schedule_raw, schedule_receipt, official_raw, official_receipt):
    now = dt.datetime.now(dt.timezone.utc)
    registrations = [r for r in records(store) if r['kind'] == 'REGISTER' and r['payload']['forecast']['event']['event_id'] == event_id]
    if not registrations: raise ValueError('NO_REGISTERED_EVENT')
    event = registrations[0]['payload']['forecast']['event']
    if now <= utc(event['start_time_utc']): raise ValueError('EVENT_NOT_STARTED')
    for receipt in [schedule_receipt, official_receipt]:
        if not utc(event['start_time_utc']) < utc(receipt['retrieved_at_utc']) <= now:
            raise ValueError('FINAL_SOURCE_MUST_BE_POST_START')
    frame = _frame({'text': schedule_raw.decode(), 'receipt': schedule_receipt}, now.isoformat(), SCHEDULE_URL)
    rows = frame[frame.game_id == event_id]
    if len(rows) != 1: raise ValueError('FINAL_EVENT_NOT_UNIQUE')
    row = rows.iloc[0]; official = _official_final(official_raw, official_receipt, event, now)
    qbs = {}
    for side in ['home', 'away']:
        if row[side+'_team'] != event[side+'_team'] or pd.isna(row[side+'_score']) or float(row[side+'_score']) != official[side]:
            raise ValueError('FINAL_SOURCES_DISAGREE')
        qb = row[side+'_qb_id']
        if not isinstance(qb, str) or not qb.startswith('00-'): raise ValueError('FINAL_QB_UNCONFIRMED')
        qbs[event[side+'_team']] = qb
    margin = official['home']-official['away']; pending = []
    # All checks above are read-only. Retain exact source bytes in immutable objects.
    sources = {'schedule': {'receipt': schedule_receipt, 'text': schedule_raw.decode()},
               'official': {'receipt': official_receipt, 'text': official_raw.decode()}}
    for r in registrations:
        p = r['payload']; f = p['forecast']; s = np.asarray(f['margin_support']); w = np.asarray(f['margin_weights'])
        empirical = p['simulation_counts']; ds = np.asarray(empirical['support']); dw = np.asarray(empirical['counts'])/f['simulation']['n']
        contracts = []
        for line in p['home_handicaps']:
            exact = base.price(s, w, line); simulated = base.price(ds, dw, line)
            outcome = 'cover' if margin+line > 0 else 'push' if margin+line == 0 else 'loss'
            contracts.append({'home_handicap': line, 'outcome': outcome, 'model': exact, 'simulation': simulated,
                'model_brier': sum((v-float(k == outcome))**2 for k, v in exact.items()),
                'simulation_brier': sum((v-float(k == outcome))**2 for k, v in simulated.items())})
        matched = p['quarterback_conditions'] == qbs
        # CRPS = E|M-y| - sum(w_i*w_j*|m_i-m_j|)/2.
        crps = float(np.sum(w*np.abs(s-margin))-.5*np.sum(w[:, None]*w[None, :]*np.abs(s[:, None]-s[None, :])))
        result = {'event_id': event_id, 'final_scores': official, 'actual_home_margin': margin,
            'actual_quarterbacks': qbs, 'scenario_matches_actual': matched,
            'cohort': 'MATCHED_QB_RESEARCH' if matched else 'COUNTERFACTUAL_QB_EXCLUDED_FROM_MATCHED_COHORT',
            'contracts': contracts, 'margin_crps': crps, 'source_bundle_sha256': digest(sources),
            'source_receipts': {'schedule': schedule_receipt, 'official': official_receipt},
            'canonical_grade': False, 'weekly_state_advanced': False, 'action_authority': False}
        pending.append((r['forecast_identity'], result))
    # Validate the entire batch under one lock; publish HEAD only after all objects
    # are durable. A conflict cannot partly grade a set of conditional forecasts.
    store = Path(store)
    with (store/'LOCK').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        old_grades = {r['forecast_identity']: r['payload'] for r in records(store) if r['kind'] == 'GRADE'}
        for identity, result in pending:
            if identity in old_grades and old_grades[identity] != result:
                raise ValueError('RESEARCH_LEDGER_CONFLICT')
        new = [(identity, result) for identity, result in pending if identity not in old_grades]
        if not new: return {'status': 'ALREADY_RECORDED', 'head': _head(store)}
        _put(store, sources); head = _head(store)
        for identity, result in new:
            head = _put(store, {'schema': 'nfl.qb_margin_research_record.v1', 'kind': 'GRADE',
                'parent': head, 'forecast_identity': identity, 'payload': result,
                'written_at_utc': dt.datetime.now(dt.timezone.utc).isoformat()})
        _publish(store, head)
        return {'status': 'APPENDED', 'grades': len(new), 'head': head}



def status(store):
    history = records(store); registered = [r for r in history if r['kind'] == 'REGISTER']; grades = [r for r in history if r['kind'] == 'GRADE']
    graded = {r['forecast_identity'] for r in grades}
    return {'schema': 'nfl.qb_margin_grading_state.v1', 'enabled': True, 'scope': 'SEPARATE_APPEND_ONLY_RESEARCH',
        'head': _head(store), 'registered_forecasts': len(registered), 'graded_forecasts': len(grades),
        'pending_forecasts': len(registered)-len(graded), 'matched_qb_grades': sum(r['payload']['scenario_matches_actual'] for r in grades),
        'canonical_grading_changed': False, 'weekly_state_advanced': False, 'action_authority': False}
