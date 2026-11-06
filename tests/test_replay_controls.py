"""Synthetic control/semantic fixtures; not predictive or provider validation."""
import copy
import json
import math
from pathlib import Path

import pytest
import pandas as pd
from scipy.special import ndtr, expit

from research.replay_controls import equivalent, write_snapshot, read_snapshot, REPORT_KINDS
from research.distribution_replay_adapter import inference_payload, predict_payload, reconstruct
from tests.test_cross_sport_distributions import fitted, H, CUTOFF


@pytest.mark.parametrize('bad', [True, False, '1e-6', None, -1., float('nan'), float('inf'), -float('inf')])
@pytest.mark.parametrize('field', ['abs_tol', 'rel_tol'])
def test_invalid_tolerance_rejected_even_for_equal_metadata(bad, field):
    with pytest.raises(ValueError, match='INVALID_COMPARISON_CONFIGURATION'):
        equivalent('same', 'same', **{field: bad})


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_operands_cannot_match_themselves(bad):
    with pytest.raises(ValueError, match='INVALID_COMPARISON_VALUE'):
        equivalent({'x': bad}, {'x': bad})


@pytest.mark.parametrize('a,b', [(True, 1.0), (True, 1), (1, True), (1.0, True)])
def test_boolean_not_numeric(a, b):
    with pytest.raises(ValueError):
        equivalent(a, b)


def test_types_and_support_exact_float_tolerance_limited():
    equivalent({'active': False, 'null': None, 'x': 1.0+1e-12}, {'active': False, 'null': None, 'x': 1.0})
    with pytest.raises(ValueError, match='REPLAY_IDENTITY'):
        equivalent([1.00001], [1], abs_tol=1)
    with pytest.raises(ValueError, match='REPLAY_NUMERIC'):
        equivalent(.500001, .5)


def row():
    return dict(predicted_mean=5., event_id='fixture-future', forecast_cutoff=CUTOFF,
                parent_model_id='parent.v1', information_set='PREGAME',
                forecast_sha256=H, scale_features={}, observed=999,
                expected={'support': [999]}, result_source_sha256=H)


def test_copy_adapter_cannot_find_checkpoint_in_supplied_inputs():
    payload = inference_payload(fitted(), [row()])
    assert 'expected' not in payload and 'expected' not in payload['rows'][0]
    assert 'observed' not in payload['rows'][0]
    def copy_adapter(inputs):
        return inputs['expected']
    with pytest.raises(KeyError):
        copy_adapter(payload)
    payload['expected'] = {'support': [999]}
    with pytest.raises(ValueError, match='ADAPTER_INPUT_BOUNDARY'):
        predict_payload(payload)


def test_checkpoint_in_row_refused():
    payload = inference_payload(fitted(), [row()]); payload['rows'][0]['expected'] = 5
    with pytest.raises(ValueError, match='ADAPTER_INPUT_BOUNDARY'):
        predict_payload(payload)


def test_independent_semantic_fixture_actual_subprocess():
    laws, receipt = reconstruct(fitted(), [row()])
    # The synthetic residual population is -3,-2,-1,+1,+2,+3 repeated ten times.
    # A mean of 5 therefore implies six equal masses at 2,3,4,6,7,8.
    assert laws[0]['support'] == [2, 3, 4, 6, 7, 8]
    assert laws[0]['masses'] == pytest.approx([1/6]*6)
    assert receipt['event_count'] == 1
    assert receipt['expected_checkpoints_supplied'] is False


def reports(run_id='fixture-run'):
    return {k: {'kind': k, 'run_id': run_id, 'verdict': 'PASS' if k == 'replay' else 'UNRESOLVED',
                'evidence': {'fixture': True, 'reason': 'Synthetic report binding test'}} for k in REPORT_KINDS}


def test_snapshot_separates_replay_and_pit_and_is_idempotent(tmp_path):
    path = write_snapshot(tmp_path, run_id='fixture-run', reports=reports())
    assert write_snapshot(tmp_path, run_id='fixture-run', reports=reports()) == path
    loaded = read_snapshot(tmp_path, path)
    assert loaded['reports']['replay']['verdict'] == 'PASS'
    assert loaded['reports']['pit']['verdict'] == 'UNRESOLVED'
    assert loaded['snapshot']['wagering_authority'] == 'OFF'


def test_tampered_report_detected_on_read_and_rewrite(tmp_path):
    path = write_snapshot(tmp_path, run_id='fixture-run', reports=reports())
    snapshot = json.loads(path.read_text())
    target = tmp_path / snapshot['reports']['pit']['path']
    target.write_text('{}')
    with pytest.raises(ValueError, match='EVIDENCE_REPORT_DRIFT'):
        read_snapshot(tmp_path, path)
    with pytest.raises(ValueError, match='IMMUTABLE_EVIDENCE_CONFLICT'):
        write_snapshot(tmp_path, run_id='fixture-run', reports=reports())


def test_snapshot_requires_bound_reports_not_pass_strings(tmp_path):
    bad = reports(); bad['replay'] = 'PASS'
    with pytest.raises(ValueError, match='EVIDENCE_REPORT_BINDING'):
        write_snapshot(tmp_path, run_id='fixture-run', reports=bad)
    assert not list(tmp_path.iterdir())
    bad = reports(); bad['pit']['run_id'] = 'another-run'
    with pytest.raises(ValueError, match='EVIDENCE_REPORT_BINDING'):
        write_snapshot(tmp_path, run_id='fixture-run', reports=bad)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('field', ['predicted_margin', 'p_home_raw', 'p_home_calibrated'])
@pytest.mark.parametrize('bad', [float('nan'), float('inf')])
def test_real_candidate_replay_rejects_nonfinite_checkpoint(tmp_path, field, bad):
    from research.candidate_methods.replay import replay
    (tmp_path / 'manifest.json').write_text(json.dumps({'artifacts': {}}))
    pd.DataFrame([{'game_id': 'fixture', 'x': 1.}]).to_csv(tmp_path / 'nfl_historical_features.csv', index=False)
    model = {'imputation_statistics': [0.], 'missing_indicator_columns': [],
             'scale_mean': [0.], 'scale_scale': [1.], 'coef': [1.], 'intercept': 0.}
    (tmp_path / 'model.json').write_text(json.dumps(model))
    folds = [{'test_season': 2025, 'arms': {'ridge': {'features': ['x'], 'model_path': 'model.json',
              'train_residual_sigma': 1., 'calibration_coefficient': 1., 'calibration_intercept': 0.}}}]
    (tmp_path / 'folds.json').write_text(json.dumps(folds))
    expected = dict(game_id='fixture', season=2025, arm='ridge', predicted_margin=1.,
                    p_home_raw=float(ndtr(1.)), p_home_calibrated=float(expit(1.)))
    pd.DataFrame([expected]).to_csv(tmp_path / 'predictions.csv', index=False)
    assert replay(tmp_path)['status'] == 'PASS'
    expected[field] = bad
    pd.DataFrame([expected]).to_csv(tmp_path / 'predictions.csv', index=False)
    with pytest.raises(ValueError, match='INVALID_COMPARISON_VALUE'):
        replay(tmp_path)
