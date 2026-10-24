from unittest.mock import patch

from scripts import audit_latest_model_capabilities as audit


def test_selection_and_files_do_not_certify_execution_or_validation():
    defaults = {'profiles': {f'{sport}:winner': {'default_model_id': 'declared-only'}
                             for sport in audit.SPORTS}}
    with patch.object(audit, 'DEFAULTS', defaults), patch.object(audit, 'present', return_value=True):
        report = audit.build_ledger()
    assert not report['all_models_capability_complete']
    for sport in report['sports'].values():
        assert sport['overall']['DEFAULT']
        assert sport['overall']['CONTROL_VALID'] is None
        assert sport['blocking_obligations']
        for target in sport['targets'].values():
            for result in target.values():
                assert not result['EXECUTED'] and not result['VALIDATED']
                assert result['status'] != 'PASS'
        assert sport['targets']['winner_probability']['analytic']['DECLARED']
        assert not sport['targets']['winner_probability']['calibrated']['DECLARED']
        assert not sport['targets']['margin']['point_estimate']['DECLARED']


def test_empty_registry_keeps_capability_gate_closed():
    with patch.object(audit, 'DEFAULTS', {}), patch.object(audit, 'present', return_value=False):
        report = audit.build_ledger()
    assert not report['all_models_capability_complete']
    assert all(not value['overall']['DEFAULT'] and not value['overall']['PROMOTION_ELIGIBLE']
               for value in report['sports'].values())
