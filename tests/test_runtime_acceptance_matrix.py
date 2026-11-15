"""Contract fixtures exercise the verifier. No fixture constitutes a league forecast."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from scripts import verify_all_current_runtimes as matrix


def test_missing_sources_account_for_every_league_and_cli_refuses(tmp_path, monkeypatch):
    missing = str(tmp_path / 'missing')
    out = tmp_path / 'audit'
    monkeypatch.setattr(sys, 'argv', ['verify', '--recovery', missing, '--current', missing,
                                      '--history', missing, '--output', str(out)])
    assert matrix.main() == 2
    result = json.loads((out / 'acceptance.json').read_bytes())
    assert set(result['unverified_required_leagues']) == set(matrix.LEAGUES)
    assert {k for k, v in result['leagues'].items() if v['status'] == 'BLOCKED'} == {*matrix.SHARED, 'nfl'}
    assert result['leagues']['cbb']['status'] == 'UNSUPPORTED'
    assert 'EXPLICIT_NFL_PACKAGE_DATE_STATE_AND_SEED_REQUIRED' in result['leagues']['nfl']['reason']
    assert result['action_authority'] is False


def test_one_failed_runtime_preserves_other_runtime_evidence(tmp_path, monkeypatch):
    def acceptance(league, *_):
        if league == 'cfb':
            raise ValueError('invalid schedule fixture')
        return {'status': 'VERIFIED', 'forecasts': 1}
    monkeypatch.setattr(matrix, 'shared_run', acceptance)
    result = matrix.verify(None, None, None, tmp_path / 'audit', required=matrix.SHARED)
    assert result['unverified_required_leagues'] == ['cfb']
    assert result['leagues']['mls']['status'] == 'VERIFIED'
    assert result['leagues']['nfl']['status'] == 'NOT_RUN'


def nfl_inputs(tmp_path):
    p = tmp_path / 'package.json'
    p.write_text(json.dumps({'model_digest': 'd'*64, 'events': [{'event_id': '2026_09_LV_SF', 'gameday': '2026-11-08',
                             'home_team': 'SF', 'away_team': 'LV', 'start_time_utc': '2026-11-08T21:25:00Z'}],
                             'covered_dates': ['2026-11-08']}))
    return dict(package=p, sha256=matrix.sha(p), date='2026-11-08',
                state_store=tmp_path, state_id='b' * 64, seed_id='c' * 64)


@pytest.mark.parametrize('change,reason', [('date', 'NFL_DATE_NOT_CAPTURED'), ('sha256', 'NFL_PACKAGE_HASH_MISMATCH')])
def test_nfl_requires_exact_dated_package_before_run(tmp_path, monkeypatch, change, reason):
    inputs = nfl_inputs(tmp_path)
    inputs[change] = '2026-11-09' if change == 'date' else 'a' * 64
    monkeypatch.setattr(matrix, 'run_cli', lambda *args: pytest.fail('executed on mismatched evidence'))
    with pytest.raises(ValueError, match=reason):
        matrix.nfl_run(inputs, tmp_path)


@pytest.mark.parametrize('defect', [None, 'blocked', 'substitution', 'hash', 'state', 'blank_html', 'wrong_display'])
def test_nfl_binds_dedicated_process_and_its_receipt(tmp_path, monkeypatch, defect):
    inputs = nfl_inputs(tmp_path)
    key = '2026_09_LV_SF'

    def fake_run(args, env, _):
        assert Path(args[1]).name == 'run_nfl_integrated.py'
        assert args[args.index('--event-package') + 1] == str(inputs['package'])
        assert args[args.index('--event-package-sha256') + 1] == inputs['sha256']
        assert args[args.index('--date') + 1] == inputs['date']
        assert env['NFL_WEEKLY_STATE_SEED_SHA256'] == inputs['seed_id']
        dest = Path(args[args.index('--output') + 1])
        f = dest / key / 'forecast.json'
        f.parent.mkdir(parents=True)
        from pipelines.cards.nfl_runner_contract import read_forecast
        from pipelines.cards.recipient_card import write_recipient_card
        from pipelines.cards.selection import select
        package = json.loads(inputs['package'].read_text())
        fixture = package['events'][0]
        model_id = select('nfl')['default_model_id']
        cutoff = '2026-11-08T12:00:00Z'
        draws = np.ones(matrix.N, dtype=np.uint8)
        draw_path = f.parent / 'winner_draws.npy'
        np.save(draw_path, draws)
        forecast = {'assimilation': {'state_id': inputs['state_id']}, 'selected_arm': 'qb',
                    'schema': 'nfl.integrated_context_forecast.v1', 'market_input': False,
                    'model_artifact_sha256': package['model_digest'], 'event': fixture,
                    'model_id': model_id, 'cutoff_utc': cutoff, 'action_authority': False,
                    'canonical_prospective_eligible': False,
                    'winner_simulation': {'count': matrix.N, 'home_win_probability': 1.0,
                                          'sha256': hashlib.sha256(draws.tobytes()).hexdigest()},
                    'prediction': {'home_win': 0.7, 'home_margin': 4.3, 'total_points': 42.1}}
        from pipelines.cards.nfl_missingness import audit, seal_native_card_row
        forecast['identity'] = 'a' * 64
        forecast['missingness_audit'] = audit(forecast, None)
        f.write_text(json.dumps(forecast))
        manifest = {p.name: matrix.sha(p) for p in (f, draw_path)}
        (f.parent/'manifest.json').write_text(json.dumps(manifest))
        native = read_forecast(dest, fixture, matrix.N, model_id, inputs['state_id'],
                               matrix.utc(cutoff), package['model_digest'])
        card = {'league': 'nfl', 'card_date': inputs['date'], 'as_of_utc': cutoff,
                'action_authority': False, 'forecasts': [{**fixture, **native, 'action_authority': False}]}
        row = card['forecasts'][0]
        row['missingness_audit'] = seal_native_card_row(row, cutoff, {'status':'NATIVE_FIXTURE'})
        if defect == 'wrong_display':
            card['forecasts'][0]['sim_p'] = 0.3
        cp, hp = dest/'diagnostic_card.json', dest/'diagnostic_card.html'
        cp.write_text(json.dumps(card))
        write_recipient_card(card,hp)
        if defect == 'blank_html':
            hp.write_text('<html></html>')
        if defect == 'state':
            forecast['assimilation']['state_id'] = 'wrong'
            f.write_text(json.dumps(forecast))
            manifest[f.name] = matrix.sha(f)
            (f.parent/'manifest.json').write_text(json.dumps(manifest))
        receipt = {'status': 'BLOCKED' if defect == 'blocked' else 'COMPLETED',
                   'schema': 'nfl.runner_receipt.v1', 'league': 'nfl', 'date': inputs['date'],
                   'cutoff_utc': cutoff, 'card_sha256': matrix.sha(cp), 'html_sha256': matrix.sha(hp),
                   'package_sha256': inputs['sha256'], 'events': [
                       {'event_id': 'another' if defect == 'substitution' else key, 'status': 'COMPLETED',
                        'forecast_sha256': 'wrong' if defect == 'hash' else matrix.sha(f),
                        'draw_file_sha256': matrix.sha(draw_path)}]}
        (dest / 'nfl_runner_receipt.json').write_text(json.dumps(receipt))
    monkeypatch.setattr(matrix, 'run_cli', fake_run)
    if defect:
        with pytest.raises(ValueError, match='NFL_|RECIPIENT_'):
            matrix.nfl_run(inputs, tmp_path)
    else:
        result = matrix.nfl_run(inputs, tmp_path)
        assert result['status'] == 'VERIFIED' and result['forecasts'] == 1


@pytest.mark.parametrize('league', matrix.SHARED)
def test_league_specific_draw_checks_and_corruption(tmp_path, league):
    row = {'model_winner': 'Draw' if league == 'mls' else 'H', 'sim_p': 1.0,
           'home_team': 'H', 'away_team': 'A'}
    folder = tmp_path / 'draws' / 'event'
    folder.mkdir(parents=True)
    row['simulation'] = {'draw_directory': str(folder)}
    ones = np.ones(matrix.N, dtype=np.uint8)
    if league == 'mls':
        arrays = {'away_goals': ones, 'home_goals': ones}
        row['diagnostics'] = {'simulation_probabilities': [0.0, 1.0, 0.0]}
    else:
        arrays = {'hw' if league == 'mlb' else 'winner_draws': ones}
    for name, arr in arrays.items():
        np.save(folder / name, arr)
    (folder/'manifest.json').write_text(json.dumps({f.name: matrix.sha(f) for f in folder.glob('*.npy')}))
    matrix.verify_draws(league, row, tmp_path)
    row['sim_p'] = 0.9
    with pytest.raises(ValueError, match='PROBABILITY_NOT_RETAINED_DRAW_MEAN'):
        matrix.verify_draws(league, row, tmp_path)


def test_six_native_clis_preserve_draws_and_rendered_rows(tmp_path, monkeypatch):
    """Only replace acquisition. Invoke the six actual producers and replay their saved draws."""
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    from tests.semantic_identity_fixtures import package

    def fixture(league, directory):
        p = package(league)
        captured = datetime.now(timezone.utc)
        start = captured + timedelta(days=1)
        day = start.astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat()
        p['events'][0].update(start_time_utc=start.isoformat(), slate_date=day)
        p['captured_at_utc'] = p['source_fetches'][0]['fetched_at_utc'] = captured.isoformat()
        p['covered_dates'] = [day]
        matrix.save(directory / league / 'package.json', p)

    monkeypatch.setattr(matrix, 'mlb', lambda r, p: fixture('mlb', p))
    monkeypatch.setattr(matrix, 'cfb', lambda r, p: fixture('cfb', p))
    monkeypatch.setattr(matrix, 'wnba', lambda r, c, p: fixture('wnba', p))
    monkeypatch.setattr(matrix, 'initial', lambda h, c, p, leagues: fixture(leagues[0], p))
    out = tmp_path / 'audit'
    result = matrix.verify(None, None, None, out, required=matrix.SHARED)
    assert result['unverified_required_leagues'] == [], result['leagues']
    for league in matrix.SHARED:
        row = result['leagues'][league]
        assert row['status'] == 'VERIFIED' and row['forecasts'] == 1
        assert row['winner_or_score_pairs'] == 100000
        assert row['deterministic_replay']['identical_draw_files'] >= 1
    assert result['leagues']['nfl']['status'] == 'NOT_RUN'
    assert result['leagues']['cbb']['status'] == 'UNSUPPORTED'
