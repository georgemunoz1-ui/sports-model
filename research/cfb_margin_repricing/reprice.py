"""Append-only diagnostics from frozen CFB margin histograms; no model fitting."""
import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

MODEL_ID = 'cfb.team_context_heads.v0_1.research'
METHOD = 'ROUNDED_NORMAL_APPROXIMATION_NOT_DRIVE_SIMULATOR'

def _distribution(row):
    if row.get('simulation_method') != METHOD:
        raise ValueError('UNSUPPORTED_SIMULATION_METHOD')
    model = row['model']
    n = model['n_sims']
    if type(n) is not int or n <= 0:
        raise ValueError('INVALID_SIMULATION_COUNT')
    pairs = []
    for value, count in row['full_margin_histogram'].items():
        if str(int(value)) != value or type(count) is not int or count <= 0:
            raise ValueError('INVALID_HISTOGRAM')
        pairs.append((int(value), count))
    if not pairs or sum(c for _, c in pairs) != n:
        raise ValueError('HISTOGRAM_COUNT_MISMATCH')
    return sorted(pairs), n

def margin_quantiles(row):
    pairs, n = _distribution(row)
    result = {}
    for percent in (10, 25, 50, 75, 90):
        threshold = math.ceil(percent * n / 100)
        cumulative = 0
        for value, count in pairs:
            cumulative += count
            if cumulative >= threshold:
                result['p' + str(percent)] = value
                break
    return {'orientation': 'home_minus_away', 'period': 'full_game',
            'method': 'empirical_inverse_cdf', 'values': result,
            'n_sims': n, 'status': 'DIAGNOSTIC_UNCALIBRATED'}

def reprice_cfb_spread(row, home_line, period='full_game'):
    if period != 'full_game':
        raise ValueError('PERIOD_MISMATCH')
    if isinstance(home_line, bool) or not isinstance(home_line, (int, float)) or not math.isfinite(home_line):
        raise ValueError('INVALID_LINE')
    if home_line % 1 != 0.5:
        raise ValueError('ONLY_HALF_POINT_SPREADS_SUPPORTED')
    pairs, n = _distribution(row)
    mu = row['model']['full_game_home_margin']
    sigma = row['model']['margin_sigma']
    if not math.isfinite(mu) or not math.isfinite(sigma) or sigma <= 0:
        raise ValueError('INVALID_NORMAL_PARAMETERS')
    wins = sum(c for m, c in pairs if m + home_line > 0)
    p_sim = wins / n
    p_model = 0.5 * math.erfc(-(mu + home_line) / (sigma * math.sqrt(2)))
    return {'home_line': home_line, 'period': period,
            'model_home_cover': p_model, 'model_away_cover': 1-p_model,
            'sim_home_cover': p_sim, 'sim_away_cover': 1-p_sim, 'p_push': 0.0,
            'home_cover_count': wins, 'away_cover_count': n-wins,
            'n_sims': n, 'mc_standard_error': math.sqrt(p_sim*(1-p_sim)/n),
            'status': 'DIAGNOSTIC_UNCALIBRATED'}

def reprice_cfb_total(line):
    return {'period': 'full_game', 'line': line, 'status': 'UNSUPPORTED',
            'reason': 'NO_FULL_GAME_TOTAL_MODEL_OR_DRAWS', 'p_over': None, 'p_under': None}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--event-id', required=True)
    p.add_argument('--home-line', type=float, required=True)
    p.add_argument('--total-line', type=float)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    raw = a.bundle.read_bytes()
    b = json.loads(raw)
    if b.get('model_id') != MODEL_ID:
        raise ValueError('UNSUPPORTED_MODEL_ID')
    rows = [r for r in b['rows'] if r['event_id'] == a.event_id]
    if len(rows) != 1:
        raise ValueError('EVENT_NOT_UNIQUE')
    row = rows[0]
    result = {'schema_version': 'cfb_margin_repricing.v1',
              'generated_at_utc': datetime.now(timezone.utc).isoformat(),
              'record_type': 'FROZEN_FORECAST_REPRICING_NOT_NEW_FORECAST',
              'parent_bundle_sha256': hashlib.sha256(raw).hexdigest(),
              'forecast_cutoff': b['cutoff'], 'model_id': b['model_id'],
              'event_id': a.event_id, 'home': row['home'], 'away': row['away'],
              'event_start': row['start'], 'model_home_margin': row['model']['full_game_home_margin'],
              'seed': row['model']['seed'],
              'original_margin_draws_sha256': row['model']['margin_draws_sha256'],
              'market_source': 'USER_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED',
              'market_observed_at_utc': None, 'price': None,
              'margin_quantiles': margin_quantiles(row),
              'spread': reprice_cfb_spread(row, a.home_line),
              'full_game_total': reprice_cfb_total(a.total_line),
              'action_authority': 'OFF', 'canonical_prospective_eligible': False}
    # Exclusive creation: never overwrite a previous derived report or forecast.
    with a.output.open('x') as f:
        f.write(json.dumps(result, indent=2, allow_nan=False)+'\n')
    if a.bundle.read_bytes() != raw:
        raise RuntimeError('PARENT_CHANGED')
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
