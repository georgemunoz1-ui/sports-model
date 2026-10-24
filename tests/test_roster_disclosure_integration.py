"""Both contracts on the actual CLI paths; all forecasts here are synthetic."""
import copy
import datetime as dt
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pipelines.cards import disclosures as C
from pipelines.cards.distribution_research import nfl_card
from sports.rosters import ROUTES, digest
from test_rosters import CUTOFF, EVENT, make_bundle


def packet(model_id, input_hash, mutation=None):
    event = {"event_id": EVENT['event_id'], "parent_model_id": model_id,
             "parent_input_sha256": input_hash,
             "availability_scenarios": [{"scenario_id": "conditional-in",
                 "conditions": [{"entity_id": "synthetic-player", "availability": "IN"}],
                 "rationale": "Conditional only; no playing probability."}]}
    if mutation == 'wrong-parent':
        event['parent_model_id'] = 'wrong-arm'
    if mutation == 'invented-weight':
        event['availability_scenarios'][0]['weight'] = .5
    return {"schema": C.INPUT_SCHEMA, "action_authority": False, "events": [event]}


def assert_reports(parent, report, coverage, status, error):
    assert report['parent_card_sha256'] == digest(parent)
    assert bool(report['errors']) is error
    assert coverage['status'] == status
    assert not coverage['roster_inputs_numerically_used']
    assert not coverage['roster_aware_forecast_eligible']
    assert not coverage['action_authority']
    assert coverage['coverage_sha256'] == digest({k: v for k, v in coverage.items() if k != 'coverage_sha256'})
    row = report['events'][0]
    assert row['decision'] == 'PASS' and not row['action_authority']
    assert any(reason['detail'] == 'ROSTER:' + status for reason in row['pass_reasons'])
    if not error:
        assert row['availability_scenarios'][0]['weight'] is None
        assert row['availability_scenarios'][0]['probability_of_playing'] is None


CASES = [('valid', 'AVAILABLE_NOT_USED', False), ('conflict', 'BLOCKED', False),
         ('future-source', 'BLOCKED', False), ('wrong-parent', 'AVAILABLE_NOT_USED', True),
         ('invented-weight', 'AVAILABLE_NOT_USED', True)]


@pytest.mark.parametrize('sport', list(ROUTES))
@pytest.mark.parametrize('case,status,error', CASES)
def test_shared_cli_keeps_both_contracts(tmp_path, monkeypatch, sport, case, status, error):
    from scripts import generate_card_force as runner
    from pipelines.cards import selected
    # Restore process-wide output variables after this test.
    for key in ('SPORTS_RESEARCH_DRAW_OUTPUT', 'MLB_DRAW_OUTPUT'):
        monkeypatch.setenv(key, str(tmp_path/'unused'))
    make_bundle(tmp_path/'rosters', sport, duplicate_player=case == 'conflict')
    cutoff = '2026-10-20T21:00:00Z' if case == 'future-source' else CUTOFF
    raw = {'model_id': 'synthetic.parent.v1', 'model_p': .6, 'sim_p': .601,
           'dose': 0, 'model_winner': 'Home', 'input_snapshot_hash': 'a'*64,
           'model_state_config_hash': 'b'*64, 'model_input_snapshot': {'prior_only': 1}}
    original = copy.deepcopy(raw)
    simulation = Mock(side_effect=lambda *a: copy.deepcopy(raw))
    adapter = SimpleNamespace(load_schedule=lambda *a: [EVENT], build_context=lambda *a: {},
                              forecast_event=simulation)
    monkeypatch.setattr(runner, 'load_adapter', lambda *a: adapter)
    monkeypatch.setattr(runner, 'now_utc', lambda: runner.dt(cutoff))
    monkeypatch.setattr(selected, 'apply_default', lambda league, event, row: row)
    p = tmp_path/'packet.json'; p.write_text(json.dumps(packet(raw['model_id'], raw['input_snapshot_hash'], case)))
    out = tmp_path/'out'
    argv = ['card', '--date', '2026-10-20', '--league', sport, '--as-of-utc', cutoff,
            '--identity-semantics', 'legacy.v1', '--roster-bundle', str(tmp_path/'rosters/bundle.json'), '--disclosures', str(p), '--output-dir', str(out)]
    monkeypatch.setattr(sys, 'argv', argv)
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == (2 if error else 0)
    parent_path = out/'diagnostic_card.json'; before = parent_path.read_bytes()
    parent = json.loads(before); row = parent['forecasts'][0]
    report = json.loads((out/'disclosures/disclosures.json').read_text())
    assert_reports(parent, report, row['roster_coverage'], status, error)
    assert row['analytic_p'] == .6 and row['sim_p'] == .601 and raw == original
    assert not parent['actionable'] and not row['action_authority']
    simulation.assert_called_once()
    # A valid packet cannot promote a full-roster-required forecast.
    simulation.reset_mock()
    blocked = runner.generate('2026-10-20', sport, cutoff, 10, None, tmp_path/'rosters/bundle.json', True)
    simulation.assert_not_called()
    assert blocked['forecast_count'] == 0
    assert 'ROSTER_AWARE_FORECAST_UNAVAILABLE' in blocked['incidents'][0]['detail']
    assert parent_path.read_bytes() == before
    with pytest.raises(FileExistsError):
        C.write_report(parent, out/'disclosures', p)
    assert parent_path.read_bytes() == before


@pytest.mark.parametrize('case,status,error', CASES)
def test_nfl_cli_keeps_selected_arm_and_both_contracts(tmp_path, monkeypatch, case, status, error):
    from scripts import run_nfl_integrated as runner
    from models.nfl.contextual import week2
    make_bundle(tmp_path/'rosters', 'nfl', duplicate_player=case == 'conflict')
    cutoff = '2026-10-20T21:00:00Z' if case == 'future-source' else CUTOFF
    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None): return dt.datetime.fromisoformat(cutoff.replace('Z', '+00:00'))
    monkeypatch.setattr(runner, 'dt', SimpleNamespace(datetime=Clock, timezone=dt.timezone))
    selected_id = json.loads((runner.nfl.DATA/'runtime.json').read_text())['default_research_model']
    bundle = {'schema': 'nfl.integrated_context_forecast.v1', 'mode': 'research_pregame',
              'model_id': selected_id, 'identity': 'synthetic-unchanged-identity', 'selected_arm': 'qb',
              'event': EVENT, 'cutoff_utc': cutoff, 'model_artifact_sha256': 'b'*64,
              'features': {'qb_difference': 1.0}, 'capability_report': {'synthetic': 'selected-qb'},
              'prediction': {'home_win': .6}, 'winner_simulation': {'p_home': .601},
              'score_simulation': {'status': 'UNAVAILABLE_FOR_SELECTED_ARM'},
              'research_only': True, 'canonical_prospective_eligible': False, 'action_authority': False}
    original = copy.deepcopy(bundle)
    context = {'model': {'design': {}}, 'recovered': {},
               'package': {'event_inputs': {EVENT['event_id']: {'base': {}, 'context': {}}}}}
    monkeypatch.setattr(runner.nfl, 'load_schedule', lambda *a: [EVENT])
    monkeypatch.setattr(runner.nfl, 'build_context', lambda *a, **kw: context)
    monkeypatch.setattr(week2, 'applies', lambda *a: False)
    simulation = Mock(side_effect=lambda *a, **kw: (copy.deepcopy(bundle), [1, 0], None))
    monkeypatch.setattr(runner, 'run', simulation)
    def persist_fixture(folder, result, *args):
        folder.mkdir(parents=True, exist_ok=False)
        (folder/'forecast.json').write_text(json.dumps(result))
        (folder/'registration.jsonl').write_text(json.dumps({'created_at_utc': cutoff}))
    persist = Mock(side_effect=persist_fixture)
    monkeypatch.setattr(runner, 'persist_run', persist)
    p = tmp_path/'packet.json'; p.write_text(json.dumps(packet(selected_id, digest(bundle['features']), case)))
    out = tmp_path/'out'
    argv = ['nfl', '--date', '2026-10-20', '--event-id', EVENT['event_id'], '--output', str(out),
            '--identity-semantics', 'legacy.v1', '--roster-bundle', str(tmp_path/'rosters/bundle.json'), '--disclosures', str(p)]
    monkeypatch.setattr(sys, 'argv', argv)
    if error:
        with pytest.raises(SystemExit) as exc: runner.main()
        assert exc.value.code == 2
    else:
        runner.main()
    saved_path = out/EVENT['event_id']/'forecast.json'; before = saved_path.read_bytes()
    saved = json.loads(before)
    report = json.loads((saved_path.parent/'disclosures/disclosures.json').read_text())
    assert_reports(nfl_card(saved, cutoff), report, saved['roster_coverage'], status, error)
    assert {k: saved[k] for k in bundle} == original == bundle
    assert simulation.call_args.kwargs['model_id'] == selected_id
    assert saved['roster_coverage']['existing_parent_personnel_evidence'] == bundle['capability_report']
    assert saved['roster_coverage']['forecast_binding']['forecast_identity'] == bundle['identity']
    simulation.reset_mock(); persist.reset_mock()
    monkeypatch.setattr(sys, 'argv', argv + ['--require-roster-aware'])
    with pytest.raises(ValueError, match='ROSTER_AWARE_FORECAST_UNAVAILABLE'): runner.main()
    simulation.assert_not_called(); persist.assert_not_called()
    assert saved_path.read_bytes() == before


@pytest.mark.parametrize('extra', [[], ['--event-id', 'event-1', '--mode', 'live']])
def test_nfl_disclosure_cli_restrictions_survive_merge(tmp_path, monkeypatch, extra):
    from scripts import run_nfl_integrated as runner
    load = Mock(side_effect=AssertionError('invalid arguments must fail before acquisition'))
    monkeypatch.setattr(runner.nfl, 'load_schedule', load)
    monkeypatch.setattr(sys, 'argv', ['nfl', '--date', '2026-10-20', '--output', str(tmp_path/'out'),
                                    '--disclosures', str(tmp_path/'packet.json')] + extra)
    with pytest.raises(SystemExit) as exc: runner.main()
    assert exc.value.code == 2
    load.assert_not_called()
