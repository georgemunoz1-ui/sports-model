#!/usr/bin/env python3
"""Read-only acceptance of PR46's recovered cohort; replays use isolated copies."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.register_mlb_calibration import validate_registration


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    evidence = ROOT / 'docs/releases/2026-09-24-mlb-grading'
    saved = json.loads((evidence / 'verification.json').read_text())
    protected = saved['after_replay_sha256']
    assert all(sha(ROOT / path) == expected for path, expected in protected.items()), 'RECOVERY_BYTES_CHANGED'
    directory = ROOT / 'data/grading/mlb'
    registry = json.loads((directory / 'registry.json').read_text())
    entry = registry['cards']['2026-09-04']
    card_path = ROOT / entry['card_path']
    card, registered_ids = validate_registration(card_path, entry, '2026-09-04')
    rows = [r for r in card['forecasts'] if r['forecast_status'] == 'FORECAST_GENERATED']
    ledger = [json.loads(line) for line in (directory / 'calibration_ledger.jsonl').read_text().splitlines()]
    grades = {r['event_id']: r for r in ledger if r['forecast_card_sha256'] == sha(card_path)}
    assert len(rows) == len(registered_ids) == len(grades) == 16
    assert {r['event_id'] for r in rows} == registered_ids == set(grades)
    assert card['forecast_count'] == card['scheduled_game_count'] == 16
    source_receipt = json.loads((evidence / 'source_receipt.json').read_text())
    result_path = directory / 'results' / (source_receipt['raw_sha256'] + '.json')
    assert sha(result_path) == source_receipt['raw_sha256']
    results = json.loads(result_path.read_text())
    games = {str(g['gamePk']): g for day in results['dates'] if day['date'] == '2026-09-04' for g in day['games']}
    assert set(games) == registered_ids, 'FROZEN_COHORT_COVERAGE_GAP'
    bindings, analytic, sim = [], [], []
    for f in rows:
        g = games[f['event_id']]
        assert g['status']['abstractGameState'] == 'Final'
        actual = grades[f['event_id']]['actual_result']
        assert (actual['home_score'], actual['away_score']) == (g['teams']['home']['score'], g['teams']['away']['score'])
        y = int(actual['home_score'] > actual['away_score'])
        # Independently orient the preserved legacy card; do not call grader math.
        pa = f['analytic_p'] if f['model_winner'] == f['home_team'] else 1-f['analytic_p']
        ps = f['stochastic_sim_p'] if f['model_winner'] == f['home_team'] else 1-f['stochastic_sim_p']
        analytic.append((pa-y)**2)
        sim.append((ps-y)**2)
        assert abs(grades[f['event_id']]['analytic_p_home']-pa) < 1e-15
        assert abs(grades[f['event_id']]['stochastic_sim_p_home']-ps) < 1e-15
        bindings.append({'event_id': f['event_id'], 'generated_at': card['generated_at_utc'],
                         'event_start': f['start_time_utc'], 'cutoff': card['requested_as_of_utc'],
                         'model_id': f['provenance']['model_id'], 'model_version': f['provenance']['model_version'],
                         'probability_orientation': 'home', 'analytic_p_home': pa, 'sim_p_home': ps,
                         'frozen_output_hash': f['provenance']['output_hash'],
                         'input_snapshot_hash': f['input_snapshot_hash'],
                         'model_state_config_hash': f['model_state_config_hash']})
    metrics = json.loads((directory / 'calibration_summary.json').read_text())['metrics']
    assert metrics['n'] == 16
    assert math.isclose(sum(analytic)/16, metrics['brier_analytic'], abs_tol=1e-15)
    assert math.isclose(sum(sim)/16, metrics['brier_sim'], abs_tol=1e-15)
    replay = []
    with tempfile.TemporaryDirectory() as td:
        temp = Path(td)
        shutil.copytree(directory, temp / 'state', ignore=shutil.ignore_patterns('registry.lock'))
        for attempt in range(2):
            paths = [temp/'state'/x for x in ('registry.json','calibration_ledger.jsonl','calibration_summary.json')]
            before = [sha(p) for p in paths]
            args = [sys.executable, str(ROOT/'scripts/grade_mlb_registry.py'), '--registry',str(paths[0]),
                    '--ledger',str(paths[1]), '--summary',str(paths[2]), '--grade-date','2026-09-04',
                    '--include-graded','--results-json',str(result_path), '--output-dir',str(temp/f'replay-{attempt}')]
            subprocess.run(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            report = json.loads((temp/f'replay-{attempt}'/'registry_grade_run.json').read_text())
            assert report['added_count'] == 0 and report['durable_ledger_count'] == 16
            assert before == [sha(p) for p in paths]
            replay.append({'added_count':0,'duplicate_count':len(report['results'][0]['duplicate_grades']), 'bytes_preserved':True})
        # First ingestion in an isolated test store; never rebuild the real ledger.
        paths[1].write_text('')
        paths[2].unlink()
        subprocess.run(args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        fresh = json.loads(paths[2].read_text())['metrics']
        assert fresh == metrics
        fresh_report = json.loads((temp/'replay-1/registry_grade_run.json').read_text())
        assert fresh_report['added_count'] == 16
    assert all(sha(ROOT/path) == expected for path, expected in protected.items()), 'REPLAY_MUTATED_REPOSITORY'
    return {'status':'PASS','registered_count':16,'graded_count':16,'excluded_september4_count':0,
            'first_ingestion_added_count':16,'fresh_worker_replays':replay,
            'brier_analytic':metrics['brier_analytic'],'brier_sim':metrics['brier_sim'],
            'output_hashes':protected,'forecast_bindings':bindings,
            'excluded_dates':{d:{'status':'NO_PREGAME_REGISTRATION','grading':'EXCLUDED','counted_as_outcome':False}
                              for d in ('2026-09-21','2026-09-22') if d not in registry['cards']},
            'immutable_backup_commit':'e4ad413145a49a418eb99e055f148ff24effbbb3',
            'market_overlay_enabled':False,'action_authority':False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    report = verify()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')
    print('MLB_CALIBRATION_ACCEPTANCE='+json.dumps(report, sort_keys=True, separators=(',',':')))


if __name__ == '__main__':
    main()
