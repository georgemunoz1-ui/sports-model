#!/usr/bin/env python3
"""One-date research orchestration; unchanged registered engines and input gates."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.recovery_capture import capture, save_json, ROUTES
from scripts.capture_model_recovery import binary
from models.current import common
from models.nfl.contextual.recovered_inference import bernoulli_simulation, utc
import numpy as np

DATE = '2026-10-02'
LEAGUE = sys.argv[1]
assert LEAGUE in ('cfb', 'nhl')
OUT = ROOT / ('daily-research-20261002-' + LEAGUE)
OUT.mkdir(exist_ok=False)
PROTECTED = ['state.json', 'data/model_selection/defaults_v1.json',
             'docs/releases/official_release_blocker_register.json']
def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def seal(p):
    save_json(p / 'manifest.json', {str(f.relative_to(p)): sha(f) for f in sorted(p.rglob('*')) if f.is_file()})
def fetch(root, spec):
    r, j = capture(root, spec)
    if r['status'] != 'CAPTURED':
        save_json(root / ('failed-' + hashlib.sha256(spec[2].encode()).hexdigest() + '.json'), r)
        r, j = capture(root, spec)
    return r, j
before = {p: sha(ROOT / p) for p in PROTECTED}
save_json(OUT / 'protected-before.json', before)
health = subprocess.run([sys.executable, 'harness/healthcheck.py'], cwd=ROOT, capture_output=True, text=True)
(OUT / 'health.txt').write_text(health.stdout + health.stderr)
save_json(OUT / 'health-status.json', {'exit': health.returncode, 'research_only': True, 'official_release_eligible': False})

try:
    assert dt.datetime.now(dt.timezone.utc).date().isoformat() == DATE, 'WRONG_EXECUTION_DATE'
    current = OUT / 'current'
    current.mkdir()
    spec = (LEAGUE, 'schedule', f'https://site.api.espn.com/apis/site/v2/sports/{ROUTES[LEAGUE]}/scoreboard?dates=20261002&limit=1000' + ('&groups=80' if LEAGUE == 'cfb' else ''), 2)
    sr, sj = fetch(current, spec)
    assert sr['status'] == 'CAPTURED', sr
    events = sj.get('events', [])
    assert len(events) == (3 if LEAGUE == 'cfb' else 5), 'SCHEDULE_COUNT_REVIEW_REQUIRED'
    for e in events:
        assert utc(e['date']) > dt.datetime.now(dt.timezone.utc), 'POST_START'
        assert e['status']['type']['state'] == 'pre', 'NOT_PREGAME'
    save_json(current / 'events.json', {LEAGUE: {str(e['id']): {'event': e, 'source_sha256': sr['raw_sha256'], 'retrieved_at_utc': sr['retrieved_at_utc']} for e in events}})
    save_json(current / 'report.json', {'created_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'sources': [sr]})
    seal(current)
    sources = OUT / 'context'
    sources.mkdir()
    context_specs = [(LEAGUE, 'event_detail', f'https://site.api.espn.com/apis/site/v2/sports/{ROUTES[LEAGUE]}/summary?event={e["id"]}', 2) for e in events]
    if LEAGUE == 'nhl':
        context_specs.append(('nhl', 'official_schedule', 'https://api-web.nhle.com/v1/schedule/2026-10-02', 1))
    with ThreadPoolExecutor(max_workers=6) as pool:
        contexts = list(pool.map(lambda s: fetch(sources, s), context_specs))
    save_json(sources / 'report.json', {'sources': [r for r, j in contexts], 'availability_used_as_model_input': False, 'market_used_as_model_input': False})
    seal(sources)
    if LEAGUE == 'nhl':
        official = next((j for r, j in contexts if r['kind'] == 'official_schedule' and j), None)
        assert official is not None, 'OFFICIAL_NHL_SCHEDULE_REQUIRED'
        games = [g for d in official['gameWeek'] if d['date'] == DATE for g in d['games']]
        assert len(games) == 5 and all(g['gameType'] == 2 for g in games), 'NHL_PHASE_OR_COUNT_CONFLICT'
        official_keys = {(g['awayTeam']['abbrev'], g['homeTeam']['abbrev'], utc(g['startTimeUTC'])) for g in games}
        provider_keys = set()
        for e in events:
            sides = {x['homeAway']: x['team']['abbreviation'] for x in e['competitions'][0]['competitors']}
            provider_keys.add((sides['away'], sides['home'], utc(e['date'])))
        assert official_keys == provider_keys, 'NHL_CANONICAL_SCHEDULE_CONFLICT'
    packages = OUT / 'packages'
    if LEAGUE == 'cfb':
        from scripts.prepare_cfb_current import prepare
        source = OUT / 'cfb-source'
        source.mkdir()
        manifest = json.loads((ROOT / 'data/cfb/model/CFB_V2_ACQUISITION_MANIFEST.json').read_text())
        commit = manifest['source']['commit']
        specs = [(f['path'], 'https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/' + commit + '/' + f['path'], f['sha256']) for f in manifest['files']]
        specs.append(('cfb_current.parquet', 'https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/schedules/parquet/cfb_schedules_2026.parquet', None))
        with ThreadPoolExecutor(max_workers=6) as pool:
            receipts = list(pool.map(lambda s: binary(source, s), specs))
        save_json(source / 'report.json', {'binary_sources': receipts, 'sources': [], 'created_at_utc': dt.datetime.now(dt.timezone.utc).isoformat()})
        seal(source)
        assert all(r['status'] == 'CAPTURED' for r in receipts), 'CFB_SOURCE_FAILURE'
        prepare(source, packages)
    else:
        from scripts import prepare_initial_baselines as initial
        history = OUT / 'history'
        history.mkdir()
        r, j = fetch(history, ('nhl', 'team_directory', 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/teams?limit=1000', 2))
        assert j is not None, r
        specs = [('nhl', 'team_season_schedule', f'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/teams/{t["team"]["id"]}/schedule?season={year}&seasontype=2', 2) for t in j['sports'][0]['leagues'][0]['teams'] for year in range(2021, 2027)]
        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(lambda s: fetch(history, s), specs))
        save_json(history / 'report.json', {'sources': [r] + [rr for rr, jj in responses], 'created_at_utc': dt.datetime.now(dt.timezone.utc).isoformat()})
        seal(history)
        assert all(rr['status'] == 'CAPTURED' for rr, jj in responses), 'NHL_HISTORY_SOURCE_FAILURE'
        initial.IDS = {'nhl': initial.IDS['nhl']}
        initial.prepare(history, current, packages)
    os.environ['SPORTS_RESEARCH_PACKAGE_DIR'] = str(packages)
    package, package_hash = common.load(LEAGUE)
    cutoff = dt.datetime.now(dt.timezone.utc).isoformat()
    common.current(package, cutoff)
    selected = common.schedule(LEAGUE, DATE, cutoff)
    assert {e['event_id'].split(':')[-1] for e in selected} == {str(e['id']) for e in events}, 'PACKAGE_SCHEDULE_IDENTITY_CONFLICT'
    assert all(utc(e['start_time_utc']) > utc(cutoff) for e in selected)
    save_json(OUT / 'source-review-binding.json', {'cutoff_utc': cutoff, 'package_sha256': package_hash, 'events': selected, 'source_hash': sr['raw_sha256'], 'decision': 'LIMITED_FEATURE_RESEARCH_ONLY', 'official_release_eligible': False, 'action_authority': False, 'personnel_weather_goalies_consumed': False, 'market_used_as_model_input': False})
    result_dir = OUT / 'results'
    command = [sys.executable, 'scripts/generate_card_force.py', '--date', DATE, '--league', LEAGUE, '--as-of-utc', cutoff, '--initial-research-baselines', '--simulations', '100000', '--output-dir', str(result_dir)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    (OUT / 'runner.log').write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stderr[-2000:]
    card = json.loads((result_dir / 'diagnostic_card.json').read_text())
    assert len(card['forecasts']) == len(events), 'FORECAST_COUNT'
    checks = []
    for f in card['forecasts']:
        folder = Path(f['simulation']['draw_directory'])
        retained = np.load(folder / 'winner_draws.npy', allow_pickle=False)
        inputs = json.loads((folder / 'inputs.json').read_text())
        replay, metadata = bernoulli_simulation(f['grading']['analytic_p_home'], inputs['identity'], 100000)
        assert np.array_equal(replay, retained) and len(retained) == 100000
        assert all(sha(folder / name) == expected for name, expected in json.loads((folder / 'manifest.json').read_text()).items())
        assert utc(f['start_time_utc']) > dt.datetime.now(dt.timezone.utc), 'POST_START_DURING_RUN'
        checks.append({'event_id': f['event_id'], 'draws': 100000, 'seed_replay': 'EXACT', 'manifest_sha256': sha(folder / 'manifest.json')})
    assert before == {p: sha(ROOT / p) for p in PROTECTED}, 'PROTECTED_FILE_CHANGED'
    quotes = [{'event_id': str(e['id']), 'competition_odds': e['competitions'][0].get('odds', [])} for e in events]
    summary = {'date': DATE, 'league': LEAGUE, 'cutoff_utc': cutoff, 'written_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'code_commit': os.environ.get('GITHUB_SHA'), 'package_sha256': package_hash, 'model_sha256': package['model_sha256'], 'model_lineage': package['model_lineage'], 'forecasts': [{k: f.get(k) for k in ['event_id', 'home_team', 'away_team', 'start_time_utc', 'model_id', 'model_winner', 'model_p', 'sim_p', 'projected_margin', 'projected_total', 'diagnostics', 'model_input_snapshot', 'simulation']} for f in card['forecasts']], 'checks': checks, 'market_reference': quotes, 'market_snapshot_utc': sr['retrieved_at_utc'], 'market_used_as_model_input': False, 'official_release_eligible': False, 'action_authority': False, 'protected_unchanged': True}
    save_json(OUT / 'summary.json', summary)
    print('RESEARCH_SUMMARY_BEGIN', flush=True)
    print(json.dumps(summary, separators=(',', ':')), flush=True)
    print('RESEARCH_SUMMARY_END', flush=True)
    if LEAGUE == 'nhl':
        joint = subprocess.run([sys.executable, 'scripts/run_nhl_joint_score_research.py', '--history', str(history), '--output', str(OUT / 'joint-challenger'), '--dates', DATE], cwd=ROOT, capture_output=True, text=True)
        (OUT / 'joint-runner.log').write_text(joint.stdout + joint.stderr)
        print('JOINT_RUN_EXIT', joint.returncode, flush=True)
        if joint.returncode == 0:
            board = json.loads((OUT / 'joint-challenger/board.json').read_text())
            print('JOINT_BOARD_BEGIN', flush=True)
            print(json.dumps(board, separators=(',', ':')), flush=True)
            print('JOINT_BOARD_END', flush=True)
    seal(OUT)
except Exception as exc:
    save_json(OUT / 'failure.json', {'error': repr(exc), 'traceback': traceback.format_exc(), 'at_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'action_authority': False})
    print(traceback.format_exc(), flush=True)
    raise
