"""Explicit postseason winner challenger; never selected by the default adapter.

Reuses frozen V13 nine-inning draws. Replaces ONLY tied-score winner handling
with independent empty-base extra innings at inherited relief/offense/park rates.
This is a probability model, not a validated baseball play/score simulator.
"""
import datetime as dt
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'harness'))
from pipelines.cards.adapters.mlb import capture_sim
import run_v13_historical as V

MODEL_ID = 'mlb.postseason.v13_empty_base_extras.research.v1'
POSTSEASON_TYPES = {'F', 'D', 'L', 'W'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def instant(s):
    t = dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
    if t.tzinfo is None:
        raise ValueError('NAIVE_TIME')
    return t


def save_once(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
    return sha(path)


def validate_inputs(x):
    if x['game_type'] not in POSTSEASON_TYPES:
        raise ValueError('NOT_POSTSEASON')
    if x['home_team'] == x['away_team']:
        raise ValueError('TEAM_IDENTITY')
    if x['through_date'] >= x['slate_date']:
        raise ValueError('SAME_DAY_OR_FUTURE_FEATURES')
    for name in ('away_form', 'home_form'):
        for key in ('rf', 'ra', 'games'):
            v = x[name][key]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
                raise ValueError('INVALID_TEAM_STATE')
    for name in ('sp_away', 'sp_home'):
        s = x[name]
        if s.get('treatment') or not s.get('observed_game_ids'):
            raise ValueError('OBSERVED_STARTER_REQUIRED')
        for key in ('era', 'gs', 'k', 'bb'):
            v = s[key]
            if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or v < 0:
                raise ValueError('INVALID_STARTER')
        if s['k'] + s['bb'] > 100 or s['gs'] < 1:
            raise ValueError('INVALID_STARTER_RATES')
    if not 0.5 <= x['park_factor'] <= 1.5:
        raise ValueError('PARK_RANGE')


def simulate(x, n, seed):
    validate_inputs(x)
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 1000000:
        raise ValueError('DRAW_COUNT')
    a, h = x['away_form'], x['home_form']
    base, d = capture_sim(V, x['sp_away'], x['sp_home'], a['rf'], a['ra'], h['rf'], h['ra'], x['park_factor'], seed, n)
    # No arbitrary playoff multiplier. Relief strength is the SAME inherited
    # V13 team-RA blend. Generic league K/BB gives neutral BIP scaling in extras.
    away_rate = (0.55*h['ra'] + 0.45*V.LG_RPG) * (a['rf']/V.LG_RPG) * x['park_factor']/9
    home_rate = (0.55*a['ra'] + 0.45*V.LG_RPG) * (h['rf']/V.LG_RPG) * x['park_factor']*V.HFA/9
    rng = np.random.default_rng(np.random.SeedSequence([seed, 1]))
    home_win = d['rh'] > d['ra']
    remaining = np.flatnonzero(d['rh'] == d['ra'])
    extra_innings = np.zeros(n, dtype=np.int16)
    for inning in range(1, 201):
        if not len(remaining):
            break
        ar = rng.poisson(away_rate, len(remaining))
        hr = rng.poisson(home_rate, len(remaining))
        extra_innings[remaining] += 1
        resolved = ar != hr
        home_win[remaining[resolved]] = hr[resolved] > ar[resolved]
        remaining = remaining[~resolved]
    if len(remaining):
        raise ValueError('EXTRA_INNINGS_TAIL_UNRESOLVED')
    p = float(home_win.mean())
    se = math.sqrt(p*(1-p)/n)
    draws = {'nine_inning_away_runs': d['ra'], 'nine_inning_home_runs': d['rh'], 'baseline_home_win': d['hw'], 'postseason_home_win': home_win, 'extra_innings': extra_innings}
    result = {'model_id': MODEL_ID, 'estimator': 'MONTE_CARLO_ONLY', 'analytic_probability': None, 'home_win_probability': p, 'away_win_probability': 1-p, 'n': n, 'seed': seed, 'rng': 'NumPy PCG64; extra stream SeedSequence([seed,1])', 'mc_standard_error': se, 'mc_95_interval_home': [max(0,p-1.96*se),min(1,p+1.96*se)], 'interval_meaning': 'NUMERICAL_SAMPLING_ERROR_ONLY_NOT_MODEL_UNCERTAINTY', 'baseline_home_win_probability': base['p_home'], 'paired_extra_handling_delta': p-base['p_home'], 'nine_inning_tie_frequency': float(np.mean(d['ra']==d['rh'])), 'extra_inning_rates': {'away': away_rate, 'home': home_rate}, 'unresolved_paths': 0, 'score_total_runline_outputs': None, 'predictive_validation': 'UNVALIDATED', 'official_release_eligible': False, 'action_authority': False, 'dose': 0.0}
    return result, draws


def run_event(x, output, package_path, contract_path, review_path, *, diagnostic=False):
    now = instant(stamp())
    package = json.loads(Path(package_path).read_text())
    contract = json.loads(Path(contract_path).read_text())
    review = json.loads(Path(review_path).read_text())
    if contract['model_id'] != MODEL_ID or package['model_id'] != MODEL_ID:
        raise ValueError('MODEL_IDENTITY')
    if x not in package['events'] or review['package_sha256'] != sha(package_path) or x['event_id'] not in review['reviewed_event_ids']:
        raise ValueError('PACKAGE_OR_AGENT_REVIEW_MISMATCH')
    if instant(review['reviewed_at_utc']) > now:
        raise ValueError('FUTURE_REVIEW')
    if not package.get('source_receipts') or not contract.get('code_pins'):
        raise ValueError('SOURCE_AND_CODE_PINS_REQUIRED')
    for name, h in contract['code_pins'].items():
        if sha(ROOT/name) != h:
            raise ValueError('CODE_PIN_MISMATCH:'+name)
    for rec in package['source_receipts']:
        if rec.get('status') != 'CAPTURED':
            raise ValueError('FAILED_SOURCE')
        if not 0 <= (now-instant(rec['retrieved_at_utc'])).total_seconds() <= 21600:
            raise ValueError('STALE_OR_FUTURE_SOURCE')
        if sha(Path(package_path).parent/'sources'/rec['raw_path']) != rec['raw_sha256']:
            raise ValueError('SOURCE_HASH_MISMATCH')
    post = instant(x['start_time_utc']) <= now or x['captured_status'] != 'Preview'
    if post and not diagnostic:
        raise ValueError('POST_START')
    cutoff = stamp()
    identity = digest({'input': x, 'package': sha(package_path), 'contract': sha(contract_path), 'review': sha(review_path), 'cutoff': cutoff, 'n': 100000})
    seed = int(identity[:16], 16)
    result, draws = simulate(x, 100000, seed)
    replay, replay_draws = simulate(x, 100000, seed)
    if result != replay or any(not np.array_equal(v, replay_draws[k]) for k,v in draws.items()):
        raise ValueError('REPLAY_MISMATCH')
    output = Path(output)/identity
    output.mkdir(parents=True, exist_ok=False)
    for name, value in draws.items():
        np.save(output/(name+'.npy'),value,allow_pickle=False)
    result.update(event_id=x['event_id'],away=x['away_team'],home=x['home_team'],start_time_utc=x['start_time_utc'],cutoff_utc=cutoff,created_at_utc=stamp(),disposition='POST_START_DIAGNOSTIC' if post else 'PRE_START_PROVISIONAL',input_sha256=digest(x),package_sha256=sha(package_path),contract_sha256=sha(contract_path),review_sha256=sha(review_path),replay='EXACT',used_inputs=x)
    save_once(output/'forecast.json',result)
    hashes={p.name:sha(p) for p in output.iterdir() if p.is_file()}
    registered = stamp()
    crossed = instant(registered) >= instant(x['start_time_utc'])
    receipt={'run_id':identity,'writer_clock_utc':registered,'artifact_hashes':hashes,'pregame_research_capture':not post and not crossed,'canonical_registration':False,'prospective_grade_eligible':False,'official_release_eligible':False,'array_encoding':'NPY; native dtype/shape in each file header','status':'POST_START' if post or crossed else 'PRE_START_DIAGNOSTIC_FREEZE'}
    save_once(output/'receipt.json',receipt)
    return {'result':result,'receipt':receipt,'path':str(output)}
