import pytest
from scripts import run_nfl_integrated as cli


@pytest.mark.parametrize('product', ['--qb-margin', '--qb-margin-calibrated'])
def test_replay_cannot_enter_qb_research_registration(monkeypatch, tmp_path, product):
    monkeypatch.setattr('sys.argv', ['run_nfl_integrated.py', '--date', '2026-09-14',
        '--output', str(tmp_path / 'never-written'), '--replay-cutoff-utc',
        '2026-09-14T12:00:00Z', product])
    with pytest.raises(SystemExit) as raised:
        cli.main()
    assert raised.value.code == 2
    assert not (tmp_path / 'never-written').exists()
