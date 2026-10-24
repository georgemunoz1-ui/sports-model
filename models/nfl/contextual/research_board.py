"""Always-visible post-freeze market comparison; never a predictive input."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import numpy as np
from . import qb_margin as base, qb_margin_calibration as cal
from .recovered_inference import digest, utc


def implied(odds):
    if isinstance(odds, bool) or not isinstance(odds, (int, float)) or not np.isfinite(odds) or abs(odds) < 100:
        raise ValueError('AMERICAN_ODDS_REQUIRED')
    return -odds/(100-odds) if odds < 0 else 100/(100+odds)


def board(parent, margin=None, draws=None, *, market=None, home_handicaps=()):
    now = dt.datetime.now(dt.timezone.utc)
    if parent.get('market_input') is not False or parent.get('action_authority') is not False:
        raise ValueError('BOARD_MARKET_BLIND_PARENT_REQUIRED')
    if margin is not None:
        if margin['model_id'] not in {base.MODEL_ID, cal.MODEL_ID} or margin['binding']['reference_forecast_digest'] != digest(parent):
            raise ValueError('BOARD_PARENT_BINDING')
        if draws is None or draws.dtype != np.dtype('<i2') or draws.shape != (margin['simulation']['n'],) or hashlib.sha256(draws.tobytes()).hexdigest() != margin['simulation']['raw_sha256']:
            raise ValueError('BOARD_DRAW_BINDING')
    quotes = [] if market is None else market.get('spreads', [])
    status = 'UNAVAILABLE_NO_QUOTE_SUPPLIED'
    if market is not None:
        if market.get('event_id') != parent['event']['event_id'] or market.get('source_type') != 'USER_SUPPLIED_MARKET_SNAPSHOT':
            raise ValueError('BOARD_MARKET_EVENT_OR_SOURCE')
        if not market.get('source') or not market.get('raw_sha256') or any(len(h) != 64 for h in market['raw_sha256']):
            raise ValueError('BOARD_MARKET_SOURCE_HASH_REQUIRED')
        captured = market.get('captured_at_utc')
        if captured and utc(captured) > now:
            raise ValueError('BOARD_FUTURE_QUOTE')
        status = 'SNAPSHOT_TIME_UNKNOWN' if not captured else 'SUPPLIED_SNAPSHOT_NOT_LIVE_VERIFIED'
    lines = list(dict.fromkeys([*home_handicaps, *[q['home_handicap'] for q in quotes]]))
    rows = []
    for line in lines:
        # Validate lines even if the selected model has no margin distribution.
        base.price([0], [1.0], line)
        matches = [q for q in quotes if q['home_handicap'] == line]
        for q in matches or [None]:
            probs = {s: implied(q[s.lower()+'_american_odds']) for s in ['HOME', 'AWAY']} if q else None
            for side in ['HOME', 'AWAY']:
                exact = base.price(margin['margin_support'], margin['margin_weights'], line, side=side) if margin else None
                sim = base.price(draws, np.full(len(draws), 1/len(draws)), line, side=side) if margin else None
                rows.append({'team': parent['event'][side.lower()+'_team'], 'side': side,
                    'handicap': line if side == 'HOME' else -line,
                    'model_cover_probability': exact['cover'] if exact else None,
                    'sim_cover_probability': sim['cover'] if sim else None,
                    'model_settlement': exact, 'sim_settlement': sim,
                    'cover_status': 'AVAILABLE' if margin else 'UNSUPPORTED_SELECTED_WINNER_ONLY_MODEL',
                    'american_odds': q[side.lower()+'_american_odds'] if q else None,
                    'break_even_probability': probs[side] if probs else None,
                    'proportional_no_vig_probability': probs[side]/sum(probs.values()) if probs else None,
                    'quote_source': q.get('source', market['source']) if q else None,
                    'quote_status': status if q else 'UNAVAILABLE_NO_QUOTE_FOR_LINE'})
    winner_rows = []
    ml = market.get('moneyline') if market else None
    ml_probs = {team: implied(ml[team]) for team in [parent['event']['home_team'], parent['event']['away_team']]} if ml else None
    for side in ['HOME', 'AWAY']:
        team = parent['event'][side.lower()+'_team']; home = side == 'HOME'
        sim_home = parent.get('winner_simulation', {}).get('home_win_probability')
        winner_rows.append({'team': team, 'model_win_probability': parent['prediction']['home_win'] if home else 1-parent['prediction']['home_win'],
            'sim_win_probability': (sim_home if home else 1-sim_home) if sim_home is not None else None,
            'american_odds': ml[team] if ml else None, 'break_even_probability': ml_probs[team] if ml_probs else None,
            'proportional_no_vig_probability': ml_probs[team]/sum(ml_probs.values()) if ml_probs else None,
            'scope': 'REGISTERED_QB_BINARY_WINNER_HEAD; margin distribution retains explicit tie mass'})
    return {'schema': 'nfl.research_board.v1', 'created_at_utc': now.isoformat(), 'event': parent['event'],
        'winner_model_id': parent['model_id'], 'margin_model_id': margin['model_id'] if margin else None,
        'parent_forecast_sha256': digest(parent), 'margin_forecast_sha256': digest(margin) if margin else None,
        'margin_draw_sha256': margin['simulation']['raw_sha256'] if margin else None,
        'winner_model_prediction': parent['prediction'], 'winner_simulation': parent['winner_simulation'],
        'winner_rows': winner_rows, 'spread_rows': rows, 'market_overlay': {'display_enabled': True, 'predictive_input_enabled': False,
            'status': status, 'packet': market, 'packet_sha256': digest(market) if market else None,
            'note': 'Market comparison only; supplied snapshots are not verified live quotes.'},
        'unsupported_products': ['TOTAL', 'TEAM_TOTAL', 'FIRST_HALF'],
        'research_grading_enabled': bool(margin), 'action_authority': False}


def persist_board(folder, value, *, stem='board'):
    folder = Path(folder)
    with (folder/(stem+'.json')).open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False); f.write('\n')
    lines = ['# NFL model and simulation board', '', f"Market comparison: **{value['market_overlay']['status']}**. Display ON; predictive market features OFF; action authority OFF.", '',
        '| Team | Handicap | Model cover | Sim cover | Odds | Break-even | No-vig |',
        '|---|---:|---:|---:|---:|---:|---:|']
    pct = lambda v: 'Unavailable' if v is None else f'{100*v:.2f}%'
    for r in value['spread_rows']:
        lines.append(f"| {r['team']} | {r['handicap']:+g} | {pct(r['model_cover_probability'])} | {pct(r['sim_cover_probability'])} | {r['american_odds'] or 'Unavailable'} | {pct(r['break_even_probability'])} | {pct(r['proportional_no_vig_probability'])} |")
    lines += ['', '| Team | Model win | Sim win | Moneyline | Break-even | No-vig |', '|---|---:|---:|---:|---:|---:|']
    for r in value['winner_rows']:
        lines.append(f"| {r['team']} | {pct(r['model_win_probability'])} | {pct(r['sim_win_probability'])} | {r['american_odds'] or 'Unavailable'} | {pct(r['break_even_probability'])} | {pct(r['proportional_no_vig_probability'])} |")
    lines += ['', 'Win probabilities come from the registered QB binary head; the margin distribution also retains an explicit tie probability.']
    if not value['spread_rows']:
        lines += ['', 'Spread quote unavailable. No line or price was supplied.']
    lines += ['', 'Totals, team totals and first-half probabilities are unavailable from this margin-only distribution.']
    with (folder/(stem+'.md')).open('x') as f: f.write('\n'.join(lines)+'\n')
