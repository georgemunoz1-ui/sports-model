#!/usr/bin/env python3
"""Descriptive grading for retained research-board rows, never a canonical ledger.

Replaces the untracked grade_oct21.py from the October 22 evidence bundle.
All labels bind to the exact provider event's competitors before scoring.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.diagnostic_winner_grading import final_event, final_score, winner_identity

LEAGUE_FILES = {'NBA': 'nba_prev.json', 'CFB': 'cfb_prev.json', 'NHL': 'nhl_prev.json',
                'WNBA': 'wnba_prev.json', 'MLS': 'mls_prev.json'}


def probability(p):
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
        raise ValueError('INVALID_PROBABILITY')
    return p


def grade_row(row, payload, source_hash):
    league, eid = row['league'], row['event_id']
    sides = final_event(payload, league, eid)
    h, a = (final_score(sides[s]) for s in ('home', 'away'))
    identity = {k: row[k] for k in ('league', 'event_id', 'home_team', 'away_team')}
    identity.update(model_pick=row['named_outcome'], final_score=f'{a}-{h}')
    for key in ('home_team_id', 'away_team_id', 'model_pick_team_id'):
        if key in row:
            identity[key] = row[key]
    resolved = winner_identity(identity, payload)
    picked_home = resolved['identity_binding']['model_pick_side'] == 'home'
    g = {**identity, **resolved,
         'forecast_hash': hashlib.sha256(json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest(),
         'result_source_sha256': source_hash}
    probabilities = row.get('probabilities', {})
    if league == 'MLS':
        label = 2 if h > a else 0 if h < a else 1
        for key, output in [('analytic_vector', 'brier'), ('simulation_vector', 'sim_brier')]:
            values = probabilities[key]
            if len(values) != 3 or abs(sum(probability(p) for p in values) - 1) > 1e-9:
                raise ValueError('INVALID_THREE_WAY_VECTOR')
            g[output] = sum((p - int(i == label)) ** 2 for i, p in enumerate(values))
        g['scoring_product'] = 'three_way_sum_brier'
    else:
        for explicit, fallback, output in [('analytic_home', 'model_probability', 'brier'),
                                           ('simulation_home', 'simulation_probability', 'sim_brier')]:
            if explicit in probabilities:
                p = probability(probabilities[explicit])
            else:
                p = probability(row[fallback])
                p = p if picked_home else 1 - p
            g[output] = (p - int(h > a)) ** 2
        g['scoring_product'] = 'home_win_binary_brier'
    for forecast_key, actual, metric in [('projected_home_margin', h-a, 'margin'), ('projected_total', h+a, 'total')]:
        if row.get(forecast_key) is not None:
            g[metric + '_error'] = float(row[forecast_key] - actual)
            if not math.isfinite(g[metric + '_error']):
                raise ValueError('INVALID_POINT_ESTIMATE')
            g[metric + '_abs_error'] = abs(g[metric + '_error'])
    return g


def grade_board(board, sources):
    payloads = {league: json.loads(raw) for league, raw in sources.items()}
    hashes = {league: hashlib.sha256(raw).hexdigest() for league, raw in sources.items()}
    grades, seen = [], set()
    for row in board['rows']:
        if row.get('simulations', 0) <= 0:
            continue
        key = (row['league'], row['event_id'])
        if key in seen:
            raise ValueError('DUPLICATE_FORECAST_EVENT')
        seen.add(key)
        try:
            if row['league'] not in payloads:
                raise ValueError('RESULT_SOURCE_REQUIRED')
            grades.append(grade_row(row, payloads[row['league']], hashes[row['league']]))
        except (ValueError, KeyError, TypeError) as exc:
            grades.append({'league': row['league'], 'event_id': row['event_id'],
                           'status': 'BLOCKED', 'reason': str(exc)})
    eligible = [g for g in grades if type(g.get('winner_correct')) is bool]
    summary = {'forecast_count': len(seen), 'winner_graded_count': len(eligible),
               'winner_correct': sum(g['winner_correct'] for g in eligible),
               'winner_accuracy': sum(g['winner_correct'] for g in eligible)/len(eligible) if eligible else None,
               'scoring_groups': {}}
    # Binary and three-way scores are not commensurate; never pool them.
    for product in sorted({g['scoring_product'] for g in eligible}):
        rows = [g for g in eligible if g['scoring_product'] == product]
        summary['scoring_groups'][product] = {'n': len(rows),
            'mean_brier': sum(g['brier'] for g in rows)/len(rows),
            'mean_sim_brier': sum(g['sim_brier'] for g in rows)/len(rows)}
    for league in sorted({g['league'] for g in eligible}):
        rows = [g for g in eligible if g['league'] == league]
        summary[league] = {'n': len(rows), 'correct': sum(g['winner_correct'] for g in rows),
                           'mean_brier': sum(g['brier'] for g in rows)/len(rows)}
    return {'schema': 'research.descriptive_postgame_assessment.v2',
            'created_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'source_hashes': hashes, 'summary': summary, 'grades': grades,
            'status': 'PARTIAL' if len(eligible) != len(seen) else 'COMPLETED',
            'blocked_count': len(seen) - len(eligible),
            'eligibility': 'DESCRIPTIVE_ONLY_NOT_CANONICAL_GRADE',
            'canonical_ledger_changed': False, 'action_authority': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--board', type=Path, required=True)
    p.add_argument('--raw-dir', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    raw = args.board.read_bytes()
    sources = {league: (args.raw_dir/name).read_bytes() for league, name in LEAGUE_FILES.items()
               if (args.raw_dir/name).is_file()}
    out = grade_board(json.loads(raw), sources)
    out['forecast_board_sha256'] = hashlib.sha256(raw).hexdigest()
    with args.output.open('x') as handle:
        json.dump(out, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')
    print(json.dumps(out['summary'], sort_keys=True))
    return 2 if out['blocked_count'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
