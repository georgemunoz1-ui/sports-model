"""Source-bound, replayable weekly research state. No model fitting or promotion.

A store has immutable content-addressed objects and one atomically replaced HEAD.
The seed pin is an operator trust input, not a self-authenticating packet field.
"""
from __future__ import annotations
import copy
import datetime as dt
import fcntl
import hashlib
import io
import json
import math
import os
from pathlib import Path
import tempfile
import pandas as pd
from . import base_features as bf
from .assimilation import advance_states, reconcile_game_coverage, serialize_states
from .qb_assimilation import prior
from .recovered_inference import digest, utc

SCHEMA = 'nfl.weekly_state.v1'
SCHEDULE_URL = 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv'


def code_identity():
    return {p: hashlib.sha256(Path(__file__).with_name(p).read_bytes()).hexdigest()
            for p in ('weekly_state.py', 'assimilation.py', 'base_features.py', 'qb_assimilation.py', 'starter_adjudication.py')}


def _put(store, value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    key = hashlib.sha256(raw).hexdigest()
    folder = Path(store) / 'objects'; folder.mkdir(parents=True, exist_ok=True)
    target = folder / (key + '.json')
    fd, name = tempfile.mkstemp(dir=folder)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(raw); f.flush(); os.fsync(f.fileno())
        try:
            os.link(name, target)
        except FileExistsError:
            if target.read_bytes() != raw: raise ValueError('IMMUTABLE_OBJECT_CONFLICT')
        directory = os.open(folder, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        os.unlink(name)
    return key


def _get(store, key):
    if not isinstance(key, str) or len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
        raise ValueError('INVALID_OBJECT_ID')
    raw = (Path(store) / 'objects' / (key + '.json')).read_bytes()
    if hashlib.sha256(raw).hexdigest() != key: raise ValueError('OBJECT_HASH_MISMATCH')
    return json.loads(raw)


def _head(store):
    p = Path(store) / 'HEAD'
    return p.read_text().strip() if p.exists() else None


def _publish(store, key):
    fd, name = tempfile.mkstemp(dir=store)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(key + '\n'); f.flush(); os.fsync(f.fileno())
        os.replace(name, Path(store) / 'HEAD')
        fd = os.open(store, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if os.path.exists(name): os.unlink(name)


def capture(path, receipt):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt['sha256']: raise ValueError('RAW_HASH_MISMATCH')
    return {'text': raw.decode('utf-8'), 'receipt': copy.deepcopy(receipt)}


def _frame(source, cutoff, url):
    r = source['receipt']; raw = source['text'].encode('utf-8')
    if hashlib.sha256(raw).hexdigest() != r['sha256']: raise ValueError('SOURCE_HASH_MISMATCH')
    if r['source_url'] != url: raise ValueError('SOURCE_IDENTITY_MISMATCH')
    for k in ('retrieved_at_utc', 'source_published_at_utc', 'available_at_utc'):
        if k == 'retrieved_at_utc' or r.get(k):
            if utc(r[k]) > utc(cutoff): raise ValueError('SOURCE_AFTER_CUTOFF')
    return pd.read_csv(io.StringIO(source['text']), low_memory=False)


def _schedule(source, season, cutoff):
    d = _frame(source, cutoff, SCHEDULE_URL)
    d = d[(d.season == season) & (d.game_type == 'REG')].copy()
    # Current 32-team, 17-game regular-season contract. Different formats need review.
    if len(d) != 272 or d.game_id.duplicated().any(): raise ValueError('FULL_SEASON_SCHEDULE_REQUIRED')
    teams = pd.concat([d.home_team, d.away_team])
    if teams.nunique() != 32 or not teams.value_counts().eq(17).all(): raise ValueError('SEASON_TEAM_COVERAGE')
    if set(d.week) != set(range(1, 19)): raise ValueError('SEASON_WEEK_COVERAGE')
    for week, g in d.groupby('week'):
        t = pd.concat([g.home_team, g.away_team])
        if t.duplicated().any(): raise ValueError('DUPLICATE_TEAM_WEEK')
        for row in g.to_dict('records'):
            if row['game_id'] != f"{season}_{int(week):02d}_{row['away_team']}_{row['home_team']}":
                raise ValueError('SCHEDULE_EVENT_BINDING')
    return d


def initialize(store, historical_seed, schedule_source, artifact, cutoff, *, starter_adjudications=None):
    """Retain reconstructed Week1 seed and independent full-season schedule anchor.

    Caller must review/pin the returned seed ID before using it at inference.
    Hashes establish identity, not authentic historical availability.
    """
    season = int(historical_seed['season'])
    if historical_seed.get('schema') != 'nfl.reconstructed_week_start_state.v1' or historical_seed['week'] != 1:
        raise ValueError('WEEK1_RECONSTRUCTED_SEED_REQUIRED')
    states = historical_seed['states']
    if digest(states) != historical_seed['state_sha256']: raise ValueError('SEED_STATE_HASH_MISMATCH')
    if historical_seed['base_feature_code_sha256'] != code_identity()['base_features.py']:
        raise ValueError('SEED_TRANSFORM_MISMATCH')
    if not historical_seed.get('source_receipts'): raise ValueError('SEED_SOURCE_LINEAGE_REQUIRED')
    games = _schedule(schedule_source, season, cutoff)
    if set(states) != set(games.home_team) | set(games.away_team): raise ValueError('SEED_TEAM_COVERAGE')
    for s in states.values():
        bf.TeamState(**s)
        if any(not math.isfinite(v) for v in s.values() if isinstance(v, (float, int))):
            raise ValueError('NONFINITE_SEED')
    if utc(cutoff) > dt.datetime.now(dt.timezone.utc): raise ValueError('FUTURE_CUTOFF')
    node = {'schema': SCHEMA, 'kind': 'seed', 'season': season, 'completed_week': 0,
            'model_sha256': digest(artifact), 'code': code_identity(), 'cutoff_utc': cutoff,
            'historical_seed': historical_seed, 'schedule_source': schedule_source,
            'starter_adjudications': copy.deepcopy(starter_adjudications or []),
            'team_state': states, 'qb_state': prior(artifact, season), 'consumed_game_ids': [],
            'research_only': True, 'action_authority': False}
    Path(store).mkdir(parents=True, exist_ok=True)
    with (Path(store) / 'LOCK').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if _head(store) is not None: raise ValueError('STORE_ALREADY_INITIALIZED')
        key = _put(store, node); _publish(store, key)
    return key


def _reduce(parent, seed, schedule_source, pbp_source, week, cutoff):
    season = seed['season']
    if week != parent['completed_week'] + 1: raise ValueError('NONCONTIGUOUS_WEEK')
    if utc(cutoff) < utc(parent['cutoff_utc']): raise ValueError('CUTOFF_ROLLBACK')
    schedule = _schedule(schedule_source, season, cutoff)
    anchor = _schedule(seed['schedule_source'], season, cutoff)
    fields = ['game_id', 'home_team', 'away_team', 'week']
    if not schedule[fields].sort_values('game_id').reset_index(drop=True).equals(anchor[fields].sort_values('game_id').reset_index(drop=True)):
        raise ValueError('SCHEDULE_REVISION_REQUIRES_REVIEW')
    if parent['kind'] == 'weekly':
        old = _schedule(parent['schedule_source'], season, cutoff)
        consumed = parent['consumed_game_ids']
        final_fields = fields + ['home_score', 'away_score', 'home_qb_id', 'away_qb_id']
        select = lambda d: d[d.game_id.isin(consumed)][final_fields].sort_values('game_id').reset_index(drop=True)
        if not select(old).equals(select(schedule)):
            raise ValueError('CONSUMED_FINAL_REVISION_REBUILD_REQUIRED')
    games = schedule[schedule.week == week].sort_values('game_id').copy()
    if games.empty: raise ValueError('EMPTY_WEEK')
    ids = games.game_id.tolist()
    if set(ids) & set(parent['consumed_game_ids']): raise ValueError('ALREADY_CONSUMED_GAME')
    raw = _frame(pbp_source, cutoff, f'https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.csv')
    # Scope both team and QB transforms before filtering or aggregating.
    p = raw[raw.game_id.isin(ids)].copy()
    if 'no_play' not in p: p['no_play'] = p.play_type.astype('string').str.lower().eq('no_play').fillna(False).astype('int8')
    r = {**pbp_source['receipt'], 'snapshot_id': pbp_source['receipt']['sha256']}
    cov = reconcile_game_coverage(p, games, r, cutoff)
    if not cov['weekly_state_update_eligible']: raise ValueError('WEEK_INCOMPLETE_OR_CONFLICTED:' + json.dumps(cov['rows']))
    # Terminal clock and finite score support are additional to legacy reconciliation.
    for game in games.to_dict('records'):
        part = p[p.game_id == game['game_id']].sort_values('order_sequence' if 'order_sequence' in p else 'play_id')
        last = part.iloc[-1]
        # Sudden-death overtime can finish with time remaining. Require the
        # provider's explicit terminal marker for that case, plus score match.
        terminal = last.game_seconds_remaining == 0 or (last.qtr > 4 and str(last.get('desc', '')).strip() == 'END GAME')
        if last.qtr < 4 or not terminal: raise ValueError('TERMINAL_GAME_BOUNDARY_REQUIRED')
        for side in ('home', 'away'):
            score = game[side + '_score']
            if not math.isfinite(score) or score < 0 or int(score) != score: raise ValueError('INVALID_FINAL_SCORE')
    required = {'season_type', 'qb_dropback', 'passer_player_id'}
    if not required.issubset(p): raise ValueError('QB_COLUMNS_REQUIRED')
    d = p[(p.season_type == 'REG') & (p.qb_dropback == 1) & (p.qb_kneel != 1) & (p.qb_spike != 1)
          & p.epa.notna() & p.passer_player_id.notna()]
    if not d.epa.map(math.isfinite).all():
        raise ValueError('QB_METRICS_MISSING')
    qb = copy.deepcopy(parent['qb_state'])
    aggregates = d.groupby(['game_id', 'passer_player_id']).epa.agg(epa_sum='sum', dropbacks='count').reset_index()
    for row in aggregates.to_dict('records'):
        value = qb['qb_ratings'].setdefault(row['passer_player_id'], {'sum': 0., 'n': 0.})
        value['sum'] += row['epa_sum']; value['n'] += row['dropbacks']
    from .starter_adjudication import apply as adjudicate_starters
    resolved_games = adjudicate_starters(games, p, seed.get('starter_adjudications', []), cutoff)
    for row in resolved_games.to_dict('records'):
        for side in ('home', 'away'):
            q = row.get(side + '_active_qb_id')
            if not isinstance(q, str) or not q: raise ValueError('COMPLETED_STARTER_ID_REQUIRED')
            if d[(d.game_id == row['game_id']) & (d.passer_player_id == q) & (d.posteam == row[side + '_team'])].empty:
                raise ValueError('STARTER_DROPBACK_BINDING')
            qb['last_qb'][row[side + '_team']] = q
    states = {t: bf.TeamState(**s) for t, s in parent['team_state'].items()}
    after, qa = advance_states(states, games, p)
    return {'team_state': serialize_states(after), 'qb_state': qb,
            'consumed_game_ids': sorted(parent['consumed_game_ids'] + ids),
            'starter_adjudications_applied': [{'game_id': r['game_id'], 'team': r['team'],
                'original_qb_id': r['expected_schedule_qb_id'], 'resolved_qb_id': r['qb_id'],
                'resolution_kind': r.get('resolution_kind', 'STALE_SCHEDULE_STARTER'),
                'nominal_starter_preserved': r.get('resolution_kind') == 'NOMINAL_STARTER_NO_DROPBACKS',
                'resolution_sha256': digest(r), 'source_sha256': r['evidence']['receipt']['sha256']}
                for r in seed.get('starter_adjudications', []) if r['game_id'] in ids],
            'coverage': cov, 'qualifying_play_audit': qa}


def load_verified(store, tip, artifact, cutoff, seed_pin):
    """Recompute every transition from retained bytes; never trust a state flag."""
    chain = []; key = tip; seen = set()
    while True:
        if key in seen or len(chain) > 18: raise ValueError('STATE_CHAIN_CYCLE_OR_LENGTH')
        seen.add(key); n = _get(store, key)
        if n['schema'] != SCHEMA or n['model_sha256'] != digest(artifact): raise ValueError('STATE_MODEL_BINDING')
        if n['code'] != code_identity(): raise ValueError('STATE_TRANSFORM_CHANGED_REBUILD_REQUIRED')
        if utc(n['cutoff_utc']) > utc(cutoff): raise ValueError('STATE_AFTER_CUTOFF')
        if n['kind'] == 'seed': break
        if n['kind'] != 'weekly': raise ValueError('UNKNOWN_STATE_KIND')
        chain.append(n); key = n['parent_id']
    if not seed_pin or key != seed_pin: raise ValueError('TRUSTED_SEED_PIN_REQUIRED')
    seed = n
    if n['completed_week'] != 0 or n['consumed_game_ids']: raise ValueError('INVALID_SEED')
    if digest(n['team_state']) != n['historical_seed']['state_sha256'] or n['qb_state'] != prior(artifact, n['season']):
        raise ValueError('INVALID_SEED_STATE')
    for child in reversed(chain):
        actual = _reduce(n, seed, child['schedule_source'], child['pbp_source'], child['completed_week'], child['cutoff_utc'])
        for field, value in actual.items():
            if digest(child[field]) != digest(value): raise ValueError('STATE_REPLAY_MISMATCH:' + field)
        n = child
    return n


def advance(store, parent_id, seed_pin, artifact, schedule_source, pbp_source, week, cutoff):
    """CAS publication; identical retries return original ID, conflicting retries fail."""
    if utc(cutoff) > dt.datetime.now(dt.timezone.utc): raise ValueError('FUTURE_CUTOFF')
    with (Path(store) / 'LOCK').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = _head(store)
        # Retry identity excludes invocation time, but binds all source bytes/receipts.
        update = digest({'parent': parent_id, 'schedule': schedule_source, 'pbp': pbp_source, 'week': week})
        if current != parent_id:
            head = load_verified(store, current, artifact, cutoff, seed_pin)
            if head.get('update_id') == update: return current
            raise ValueError('STALE_PARENT_OR_CONFLICTING_REPLAY')
        parent = load_verified(store, parent_id, artifact, cutoff, seed_pin)
        seed = _get(store, seed_pin)
        reduced = _reduce(parent, seed, schedule_source, pbp_source, week, cutoff)
        node = {'schema': SCHEMA, 'kind': 'weekly', 'season': seed['season'], 'completed_week': week,
                'model_sha256': digest(artifact), 'code': code_identity(), 'cutoff_utc': cutoff,
                'created_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'parent_id': parent_id,
                'update_id': update, 'schedule_source': schedule_source, 'pbp_source': pbp_source,
                **reduced, 'research_only': True, 'action_authority': False}
        key = _put(store, node); _publish(store, key)
        return key


def for_event(context, artifact, event, cutoff):
    ev = context.get('weekly_state')
    if not ev: raise ValueError('WEEKLY_STATE_EVIDENCE_REQUIRED')
    # A crash can leave a fully written, unpublished object. It is not live state.
    cursor = _head(ev['store']); seen = set()
    while cursor != ev['state_id']:
        if not cursor or cursor in seen or len(seen) > 18: raise ValueError('STATE_NOT_IN_PUBLISHED_CHAIN')
        seen.add(cursor); cursor = _get(ev['store'], cursor).get('parent_id')
    pin = os.environ.get('NFL_WEEKLY_STATE_SEED_SHA256')
    state = load_verified(ev['store'], ev['state_id'], artifact, cutoff, pin)
    season, week = map(int, event['event_id'].split('_')[:2])
    if (state['season'], state['completed_week']) != (season, week - 1): raise ValueError('WRONG_WEEK_STATE')
    seed = _get(ev['store'], pin)
    schedule = _schedule(seed['schedule_source'], season, cutoff)
    g = schedule[schedule.game_id == event['event_id']]
    if len(g) != 1 or (g.iloc[0].home_team, g.iloc[0].away_team) != (event['home_team'], event['away_team']):
        raise ValueError('FORECAST_EVENT_SCHEDULE_BINDING')
    return state


def require_features(base, state, event):
    from .week2 import STATE_FEATURES
    if (int(base['season']), int(base['week'])) != (state['season'], state['completed_week'] + 1):
        raise ValueError('BASE_WEEK_STATE_BINDING')
    game = pd.Series({'home_score': None, 'away_score': None, 'roof': None, 'temp': None,
                      'wind': None, 'home_rest': None, 'away_rest': None,
                      **base, 'gameday': event['gameday'], 'gametime': event['gametime'],
                      'location': event.get('location', 'Home')})
    expected = bf._feature_row(game, bf.TeamState(**state['team_state'][event['home_team']]),
                               bf.TeamState(**state['team_state'][event['away_team']]))
    for key in STATE_FEATURES:
        if not math.isclose(float(base[key]), float(expected[key]), rel_tol=1e-8, abs_tol=1e-8):
            raise ValueError('WEEKLY_STATE_NOT_ACTIVE_IN_RUN:' + key)
    return {'status': 'VERIFIED_RESEARCH_WEEKLY_STATE_FLOW', 'completed_week': state['completed_week'],
            'team_state_sha256': digest(state['team_state']), 'qb_state_sha256': digest(state['qb_state']),
            'consumed_game_ids': state['consumed_game_ids'], 'state_feature_values': {k: float(expected[k]) for k in STATE_FEATURES},
            'source_pbp_sha256': state['pbp_source']['receipt']['sha256'],
            'starter_adjudications_applied': state.get('starter_adjudications_applied', []),
            'schedule_sha256': state['schedule_source']['receipt']['sha256'], 'official_gamebook_clearance': False}


def bind_packet(packet, artifact, event, cutoff, store, state_id):
    """Opt-in CLI consumption; reconstruct only the nine state-derived features."""
    from .week2 import STATE_FEATURES
    result = copy.deepcopy(packet)
    result['context']['weekly_state'] = {'store': str(Path(store).resolve()), 'state_id': state_id}
    state = for_event(result['context'], artifact, event, cutoff)
    base = result['base']
    game = pd.Series({'home_score': None, 'away_score': None, 'roof': None, 'temp': None,
                      'wind': None, 'home_rest': None, 'away_rest': None, **base,
                      'gameday': event['gameday'], 'gametime': event['gametime'],
                      'location': event.get('location', 'Home')})
    row = bf._feature_row(game, bf.TeamState(**state['team_state'][event['home_team']]),
                         bf.TeamState(**state['team_state'][event['away_team']]))
    for key in STATE_FEATURES: base[key] = float(row[key])
    return result

