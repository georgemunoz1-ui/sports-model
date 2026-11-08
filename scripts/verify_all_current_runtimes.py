#!/usr/bin/env python3
"""Build and exercise all current league packages; coverage errors are fatal."""
import argparse,datetime as dt,hashlib,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import numpy as np
from models.current.common import save
from models.nfl.contextual.recovered_inference import digest, utc
from pipelines.cards.recipient_card import verify_recipient_card
from scripts.prepare_mlb_official_current import prepare as mlb
from scripts.prepare_wnba_current import prepare as wnba
from scripts.prepare_cfb_current import prepare as cfb
from scripts.prepare_initial_baselines import prepare as initial


SHARED = ('mlb', 'wnba', 'cfb', 'nba', 'nhl', 'mls')
LEAGUES = (*SHARED, 'nfl', 'cbb')
N = 100000


def shared_run(league, recovery, current, history, output):
    from pipelines.cards.runner_contract import verify_shared_card

    packages = output / 'packages'
    if league == 'mlb':
        mlb(recovery, packages)
    elif league == 'wnba':
        wnba(recovery, current, packages)
    elif league == 'cfb':
        cfb(recovery, packages)
    else:
        initial(history, current, packages, leagues=[league])

    package_path = packages / league / 'package.json'
    package = json.loads(package_path.read_bytes())
    days = sorted({e['slate_date'] for e in package['events']}) or package['covered_dates']
    package_hash = sha(package_path)
    ids = [e['event_id'] for e in package['events']]
    if not days or not set(days).issubset(package['covered_dates']) or len(ids) != len(set(ids)):
        raise ValueError('PACKAGE_EVENT_OR_DATE_COVERAGE')
    asof = dt.datetime.now(dt.timezone.utc).isoformat()
    env = dict(os.environ, SPORTS_RESEARCH_PACKAGE_DIR=str(packages), SPORTS_INITIAL_BASELINES='1')

    def run_day(day, dest):
        cmd = [sys.executable, str(ROOT / 'scripts/generate_card_force.py'), '--league', league,
               '--date', day, '--as-of-utc', asof, '--simulations', str(N),
               '--output-dir', str(dest), '--initial-research-baselines',
               '--event-package', str(package_path), '--event-package-sha256', package_hash]
        run_cli(cmd, env, dest.with_suffix('.log'))
        card = json.loads((dest / 'diagnostic_card.json').read_bytes())
        if card.get('package_binding') != {'sha256': package_hash, 'date': day, 'league': league}:
            raise ValueError('CARD_PACKAGE_BINDING_MISMATCH')
        verify_recipient_card(card, dest / 'diagnostic_card.html')
        expected = [e for e in package['events'] if e['slate_date'] == day]
        verify_shared_card(card, expected, league=league, card_date=day, as_of=asof, simulations=N)
        if card['incidents'] or card['forecast_count'] != len(expected):
            raise ValueError('CURRENT_COVERAGE_FAILURE:' + league + ':' + json.dumps(card['incidents']))
        return card

    count = 0
    for day in days:
        dest = output / 'cards' / league / day
        card = run_day(day, dest)
        for row in card['forecasts']:
            if row['action_authority'] is not False or row['dose'] != 0 or row['model_id'] != package['model_id']:
                raise ValueError('SELECTION_AUTHORITY_DRIFT')
            verify_draws(league, row, dest)
            count += 1
    replay = None
    if count:
        day = days[0]
        dest = output / 'replay' / league
        run_day(day, dest)
        old = draw_hashes(output / 'cards' / league / day / 'draws')
        new = draw_hashes(dest / 'draws')
        if not old or old != new:
            raise ValueError('DETERMINISTIC_REPLAY_FAILURE:' + league)
        replay = {'identical_draw_files': len(old), 'digest': digest(old)}
    return {'status': 'VERIFIED' if count else 'COVERED_EMPTY_PACKAGE', 'forecasts': count,
            'winner_or_score_pairs': count * N, 'model_id': package['model_id'],
            'package_sha256': package_hash, 'state_sha256': package['model_sha256'],
            'model_lineage': package['model_lineage'], 'dates_checked': days,
            'limitations': package['limitations'], 'deterministic_replay': replay}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def draw_hashes(folder):
    return {str(f.relative_to(folder)): sha(f) for f in folder.rglob('*.npy')}


def verify_draws(league, row, dest):
    folder = Path(row['simulation']['draw_directory']).resolve()
    if not folder.is_relative_to((dest / 'draws').resolve()):
        raise ValueError('DRAW_DIRECTORY_OUTSIDE_RUN')
    manifest = json.loads((folder / 'manifest.json').read_bytes())
    files = sorted(folder.glob('*.npy'))
    if not files or not all(f.name in manifest for f in files):
        raise ValueError('DRAW_MANIFEST_INCOMPLETE')
    for name, expected in manifest.items():
        path = folder / name
        if path.resolve().parent != folder or sha(path) != expected:
            raise ValueError('DRAW_MANIFEST_DRIFT')

    arrays = {f.stem: np.load(f, allow_pickle=False) for f in files}
    if any(values.shape != (N,) for values in arrays.values()):
        raise ValueError('DRAW_COUNT')
    if league == 'mls':
        away, home = arrays['away_goals'], arrays['home_goals']
        probs = [float((away > home).mean()), float((away == home).mean()), float((home > away).mean())]
        if not np.allclose(probs, row['diagnostics']['simulation_probabilities'], rtol=0, atol=1e-12):
            raise ValueError('MLS_PROBABILITY_DRAW_MISMATCH')
        sim = probs[[row['away_team'], 'Draw', row['home_team']].index(row['model_winner'])]
    else:
        winner = arrays['hw' if league == 'mlb' else 'winner_draws']
        if not np.isin(winner, [0, 1]).all() or row['model_winner'] not in (row['home_team'], row['away_team']):
            raise ValueError('INVALID_BINARY_OUTCOMES')
        home = float(winner.mean())
        sim = home if row['model_winner'] == row['home_team'] else 1 - home
    if not np.isclose(sim, row['sim_p'], rtol=0, atol=1e-12):
        raise ValueError('PROBABILITY_NOT_RETAINED_DRAW_MEAN')


def run_cli(cmd, env, log):
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('x') as handle:
        result = subprocess.run(cmd, env=env, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode:
        raise ValueError(f'RUNNER_EXIT_{result.returncode}: see {log.name}')


def nfl_run(inputs, output):
    if not inputs or not all(inputs.values()):
        raise ValueError('EXPLICIT_NFL_PACKAGE_DATE_STATE_AND_SEED_REQUIRED')
    package_path = inputs['package'].resolve()
    package_hash, day = inputs['sha256'], inputs['date']
    if sha(package_path) != package_hash:
        raise ValueError('NFL_PACKAGE_HASH_MISMATCH')
    package = json.loads(package_path.read_bytes())
    if day not in package['covered_dates']:
        raise ValueError('NFL_DATE_NOT_CAPTURED:' + day)
    expected = [e['event_id'] for e in package['events'] if e['gameday'] == day]
    if not expected or len(set(expected)) != len(expected):
        raise ValueError('NFL_SOURCE_EVENT_COHORT_REQUIRED')
    dest = output / 'cards' / 'nfl' / day
    cmd = [sys.executable, str(ROOT / 'scripts/run_nfl_integrated.py'), '--date', day,
           '--output', str(dest), '--event-package', str(package_path), '--event-package-sha256', package_hash,
           '--weekly-state-store', str(inputs['state_store'].resolve()), '--weekly-state-id', inputs['state_id'],
           '--simulations', str(N)]
    env = dict(os.environ, NFL_WEEKLY_STATE_SEED_SHA256=inputs['seed_id'])
    run_cli(cmd, env, dest.with_suffix('.log'))
    receipt_path = dest / 'nfl_runner_receipt.json'
    receipt = json.loads(receipt_path.read_bytes())
    events = receipt['events']
    if (receipt['status'] != 'COMPLETED' or receipt['schema'] != 'nfl.runner_receipt.v1'
            or receipt['league'] != 'nfl' or receipt['date'] != day or receipt['package_sha256'] != package_hash
            or sorted(e['event_id'] for e in events) != sorted(expected)
            or any(e['status'] != 'COMPLETED' for e in events)):
        raise ValueError('NFL_RECEIPT_SCOPE_OR_STATUS')
    from pipelines.cards.nfl_runner_contract import read_forecast
    from pipelines.cards.runner_contract import index
    from pipelines.cards.selection import select
    card_path, html = dest / 'diagnostic_card.json', dest / 'diagnostic_card.html'
    card = json.loads(card_path.read_bytes())
    if (sha(card_path) != receipt['card_sha256'] or sha(html) != receipt['html_sha256']
            or card['league'] != 'nfl' or card['card_date'] != day or card['action_authority'] is not False
            or utc(card['as_of_utc']) != utc(receipt['cutoff_utc'])):
        raise ValueError('NFL_CARD_READBACK_OR_SCOPE')
    verify_recipient_card(card, html)
    shown = index(card['forecasts'])
    fixtures = index([e for e in package['events'] if e['gameday'] == day])
    if shown.keys() != fixtures.keys():
        raise ValueError('NFL_CARD_EVENT_SET_MISMATCH')
    for evidence in events:
        eid = evidence['event_id']
        fixture, row = fixtures[eid], shown[eid]
        native = read_forecast(dest, fixture, N, select('nfl')['default_model_id'],
                               inputs['state_id'], utc(receipt['cutoff_utc']), package['model_digest'])
        if (row.get('action_authority') is not False or row['home_team'] != fixture['home_team']
                or row['away_team'] != fixture['away_team'] or row['start_time_utc'] != fixture['start_time_utc']
                or any(row.get(k) != v for k, v in native.items())
                or any(evidence[k] != native[k] for k in ('forecast_sha256', 'draw_file_sha256'))):
            raise ValueError('NFL_CARD_FORECAST_MISMATCH')
    return {'status': 'VERIFIED', 'dates_checked': [day], 'forecasts': len(events),
            'winner_or_score_pairs': len(events) * N, 'package_sha256': package_hash,
            'state_id': inputs['state_id'], 'receipt_sha256': sha(receipt_path)}


def verify(recovery, current, history, output, *, required=LEAGUES, nfl_inputs=None):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    leagues = {}
    for league in LEAGUES:
        if league == 'cbb':
            leagues[league] = {'status': 'UNSUPPORTED', 'reason': 'NO_REGISTERED_CBB_RUNNER_ON_THIS_REVISION'}
        elif league not in required:
            leagues[league] = {'status': 'NOT_RUN', 'reason': 'OUTSIDE_REQUESTED_RUNTIME_SCOPE'}
        else:
            try:
                leagues[league] = (nfl_run(nfl_inputs, output) if league == 'nfl'
                                   else shared_run(league, recovery, current, history, output))
            except (OSError, ValueError, KeyError, TypeError, AssertionError, RuntimeError) as exc:
                leagues[league] = {'status': 'BLOCKED', 'reason': f'{type(exc).__name__}: {exc}'}

    # A verified empty package accounts for a date scope but exercises no numerical path.
    failed = [l for l in required if leagues[l]['status'] != 'VERIFIED']
    summary = {'schema': 'all_current_research_acceptance.v2',
               'checked_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
               'status': 'BLOCKED' if failed else 'VERIFIED_REQUESTED_RUNTIMES',
               'required_leagues': list(required), 'unverified_required_leagues': failed,
               'simulations_per_event': N, 'leagues': leagues, 'action_authority': False}
    save(output / 'acceptance.json', summary)
    print(json.dumps({l: r['status'] for l, r in leagues.items()}))
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('recovery', 'current', 'history', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--required-leagues', nargs='+', choices=LEAGUES, default=LEAGUES,
                   help='Only explicitly requested numerical runtimes can earn acceptance. All eight are reported.')
    p.add_argument('--nfl-package', type=Path)
    p.add_argument('--nfl-package-sha256')
    p.add_argument('--nfl-date', type=dt.date.fromisoformat)
    p.add_argument('--nfl-state-store', type=Path)
    p.add_argument('--nfl-state-id')
    p.add_argument('--nfl-seed-id')
    a = p.parse_args()
    nfl_inputs = {'package': a.nfl_package, 'sha256': a.nfl_package_sha256,
                  'date': a.nfl_date.isoformat() if a.nfl_date else None, 'state_store': a.nfl_state_store,
                  'state_id': a.nfl_state_id, 'seed_id': a.nfl_seed_id}
    summary = verify(a.recovery, a.current, a.history, a.output,
                     required=a.required_leagues, nfl_inputs=nfl_inputs)
    return 2 if summary['unverified_required_leagues'] else 0


if __name__ == '__main__':
    sys.exit(main())
