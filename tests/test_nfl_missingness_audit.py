"""Known November 8 case, source failure controls and fitted-predictor preservation."""
import copy
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from models.nfl.contextual.features import availability_features, prepare_reports
from models.nfl.contextual.model import load_artifact
from models.nfl.contextual.recovered_inference import predict
from pipelines.cards.nfl_missingness import audit, comparison, read_prior, report_states, verify

ROOT = Path(__file__).resolve().parents[1]
CASE = json.loads((ROOT/'tests/fixtures/nfl_missingness/cin_atl.json').read_text())


@pytest.fixture(scope='module')
def model():
    return load_artifact(ROOT/'data/nfl/contextual_v1/model_packed.json')


def test_paired_retained_madrid_regression(model):
    new, old = copy.deepcopy(CASE['refresh']), CASE['prior']
    before = copy.deepcopy(new['prediction'])
    sealed = audit(new, model, old)
    new['missingness_audit'] = sealed
    assert new['prediction'] == before and verify(new)
    assert sealed['action_authority'] is False
    evidence = sealed['details']
    assert not evidence['unmapped_features'] and evidence['comparison_status'] == 'PAIRED'
    for arm, c in [('combined', -8.013630686687792), ('availability', -7.811039163250151)]:
        v = evidence['arms'][arm]
        assert list(v['features']) == model['arms'][arm]['feature_names']
        support = v['report_count_support']
        assert support['counts_by_missing_teams'] == {'0':2877,'1':8,'2':0}
        assert support['training_count_at_prior'] == 0 and support['training_count_at_current'] == 2877
        margin = v['changes']['home_margin']
        assert margin['reporting_state_dominated']
        assert margin['reporting_presence_delta'] == pytest.approx(c)
        assert sum(margin[k] for k in ('missingness_imputation','observed_feature_change','observation_or_reporting_interaction')) == pytest.approx(margin['linear_delta'])
        assert margin['after'] == pytest.approx(new['arms'][arm]['prediction']['home_margin'])
    for head in evidence['arms']['qb']['changes'].values():
        assert head['output_delta'] == 0 and head['changed_features'] == []
    assert sealed['details']['simulation']['winner_before']['sha256'] != sealed['details']['simulation']['winner_after']['sha256']
    new['display_annotation'] = 'presentation-only caption'
    assert verify(new)
    new['prediction']['home_win'] += .01
    assert not verify(new)


def test_missing_prior_or_model_drift_is_visible(model):
    new = CASE['refresh']
    assert audit(new,model)['details']['comparison_status']=='PRIOR_NOT_SUPPLIED'
    old = {**CASE['prior'], 'model_artifact_sha256': 'f'*64}
    changed = audit(new,model,old)['details']
    assert changed['comparison_status']=='MODEL_OR_MODE_CHANGED'
    assert 'changes' not in changed['arms']['qb']
    old = dict(CASE['prior'], event={**CASE['prior']['event'],'away_team':'KC'})
    assert audit(new, model, old)['details']['comparison_status']=='PRIOR_EVENT_OR_CHRONOLOGY_MISMATCH'


def test_head_imputation_transition_replays_separately(model):
    actual = copy.deepcopy(CASE['refresh'])
    previous = copy.deepcopy(actual)
    previous['features']['temperature_f'] = None
    actual['features']['temperature_f'] = 22.
    for b in (actual, previous):
        for arm, params in model['arms'].items():
            b['arms'][arm] = predict(params, {name:b['features'][name] for name in params['feature_names']})
    d = audit(actual, model, previous)['details']['arms']['qb']
    for head, changed in d['changes'].items():
        assert changed['changed_features'][0]['group']=='missingness_imputation'
        assert changed['missingness_imputation']==pytest.approx(changed['linear_delta'])
        assert d['features']['temperature_f']['heads'][head]['median'] is not None


def test_verified_empty_final_list_distinct_from_feed_failure_and_missing_role():
    f = copy.deepcopy(CASE['refresh'])
    state = {'report_status':'TIMEOUT', 'injury_observations':[]}
    f['audit']={'recovered_model':{'context_admission':{'personnel':{'state':state}}},
                'final_availability':{'status':'VERIFIED','players':[]}}
    o=report_states(f)
    assert o['team_reports']['CIN']['coverage_state']=='ACQUISITION_FAILURE'
    assert not o['team_reports']['CIN']['complete_team_absence_verified']
    assert o['final_inactive_lists']['CIN']['state']=='VERIFIED_ABSENCE'
    state.update(report_status='NOT_YET_PUBLISHED')
    assert report_states(f)['team_reports']['CIN']['coverage_state']=='NOT_YET_PUBLISHED'
    state.update(report_status='NOT_ACQUIRED')
    assert report_states(f)['team_reports']['CIN']['coverage_state']=='UNRESOLVED_IDENTITY_OR_COVERAGE'


def test_duplicate_aliases_and_ids_fail_closed():
    f = copy.deepcopy(CASE['refresh'])
    observations=[{'team':'ATL','player':'Brian Robinson Jr.', 'player_id':'x'}]
    state = {'injury_observations':observations, 'reserve_absences':[{'team':'ATL','player':'Brian Robinson'}]}
    f['audit']={'recovered_model':{'context_admission':{'personnel':{'state':state}}}}
    with pytest.raises(ValueError,match='DUPLICATE_PERSONNEL_OBSERVATION'):
        report_states(f)


def test_historical_and_inference_availability_transform_order_and_alias_parity():
    row={'home_team':'JAX','away_team':'NYG','gameday':'2026-10-09','gametime':'19:00'}
    rows=[{'team':'JAC','full_name':n,'gsis_id':n,'position':pos,'report_status':'OUT','practice_status':'DNP',
           'date_modified':'2026-10-09T05:00:00Z'} for n,pos in [('A Player','TE'),('B Other','OL')]]
    pre,late,unknown=prepare_reports(pd.DataFrame(rows),row)
    assert (late,unknown)==(0,0)
    historical,player_audit=availability_features(row,pre,{})
    live,_=availability_features(row,{'JAX':list(reversed(rows))},{})
    assert historical==live and live['report_missing_count']==1
    assert live['out_role_unknown_count']==2 and live['OL_out_snap_sum']==0
    assert all(x['prior_snap_share'] is None for x in player_audit)


def test_metadata_only_keeps_fitted_heads_and_law(model):
    old = copy.deepcopy(CASE['refresh'])
    new = copy.deepcopy(old)
    new.update(evidence_annotation='new local capture annotation')
    new['audit']={'recovered_model':{'context_admission':{'personnel':{'state':{'reference_url':'https://example.org/metadata'}}}}}
    details=audit(new,model,old)['details']
    assert all(head['output_delta']==0 for a in details['arms'].values() for head in a['changes'].values())
    assert details['simulation']['score_law_after']==details['simulation']['score_law_before']


def test_unbound_prior_rejected(tmp_path):
    path=tmp_path/'old.json'
    path.write_text('{}')
    with pytest.raises(ValueError, match='PRIOR_HASH_MISMATCH'):
        read_prior(path, 'f'*64)


def test_separate_child_binds_its_own_product_without_parent_review(tmp_path):
    from pipelines.cards.nfl_missingness import persist_child_review
    parent = CASE['prior']
    child = {'model_id':'child.test','prediction':{'spread':.55}}
    report = persist_child_review(tmp_path,parent,child,['full_game_spread'])
    assert report['release_status'] == 'HOLD_PENDING_SCOPE_REVIEW'
    assert not report['details']['parent_receipt_verified']
    assert report['products'] == ['full_game_spread']
    with pytest.raises(FileExistsError):
        persist_child_review(tmp_path,parent,child,['full_game_spread'])


def test_market_blend_compares_terms_in_its_own_prediction_units():
    old = copy.deepcopy(CASE['prior'])
    old.update(mode='enhanced_pregame', model_id='nfl.ensemble.test',
               prediction={'home_win': 0.50}, contribution_trace={'home_win':{'football_term':.25,'market_term':.25}})
    new = copy.deepcopy(old)
    new.update(prediction={'home_win':.65}, contribution_trace={'home_win':{'football_term':.24,'market_term':.41}})
    changes = audit(new,None,old)['details']['ensemble_changes']['home_win']
    assert changes['football_delta'] == pytest.approx(-.01)
    assert changes['market_delta'] == pytest.approx(.16)


@pytest.mark.parametrize('key', ['sampling_seed','draw_count','state_id','final_inactives','procedure'])
def test_native_receipt_binds_full_sampling_and_consumed_source_evidence(model,key):
    native = copy.deepcopy(CASE['refresh'])
    native['missingness_audit'] = audit(native, model)
    if key == 'sampling_seed':
        native['winner_simulation']['seed'] += 1
    elif key == 'draw_count':
        native['winner_simulation']['count'] -= 1
    elif key == 'state_id':
        native['assimilation'] = {'state_id':'substitution'}
    elif key == 'final_inactives':
        native['audit'] = {'final_inactives':'pending'}
    else:
        native['forecast_procedure_id'] = 'substitute'
    assert not verify(native)
