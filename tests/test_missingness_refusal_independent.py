"""Independent TEST_ONLY adversarial review of versioned refusal semantics."""
import base64
from copy import deepcopy
import json

import pytest

from harness import release_gate
from pipelines.cards.missingness import seal_audit, content_digest
from research import missingness_review as review
from research.validation_registry import RegistryError
from test_missingness_release import release_case
from test_missingness_refusal_policy import make_refusal_study, resign, validate
from test_validation_registry import make_registry_fixture


def reseal(case, row, *, forecast=None, mutate=None, products=None):
    fixture, _, _, key, _ = case
    store = fixture['store']
    receipt = store.read(row['receipt_id'])
    forecast = store.read(row['forecast_id']) if forecast is None else forecast
    if mutate:
        mutate(receipt['details']['monitored_strata'][key])
    row['forecast_id'] = store.put(forecast)
    row['receipt_id'] = store.put(seal_audit(
        league=receipt['league'], event_id=receipt['event_id'], model_id=receipt['model_id'],
        products=products or receipt['products'], forecast=forecast, details=receipt['details']))
    resign(fixture, row)


def approve(case, root, monkeypatch):
    """Create new ephemeral protocol/review anchors, never production authority."""
    fixture, policy_id, result, key, data = case
    store = fixture['store']
    validate(case)
    protocol = deepcopy(fixture['protocol'])
    protocol['missingness_policy_id'] = policy_id
    protocol_id = store.put(protocol)
    registration_id = fixture['sign'](protocol_id, 'preregistration', 'TEST_ONLY_witness', '2026-01-01T12:00:00Z')
    record = {
        'procedure_id': fixture['procedure_id'], 'target': fixture['target'],
        'author': 'TEST_ONLY_author', 'reviewer': 'TEST_ONLY_reviewer',
        'protocol_id': protocol_id, 'registration_receipt_id': registration_id,
        'policy_frozen_utc': '2026-01-01T12:00:00Z',
        'confirmation_start_utc': protocol['evaluation_start_utc'],
        'confirmation_end_utc': protocol['evaluation_end_utc'],
        'reviewed_utc': fixture['evidence']['computed_at_utc'],
        'expires_utc': '2026-12-31T00:00:00Z', 'policy_id': policy_id,
        'results_id': store.put(result),
    }
    review_id = store.put(record)
    keys = {k: base64.b64encode(v.public_key().public_bytes_raw()).decode() for k,v in fixture['keys'].items()}
    (root/'approved.json').write_text(json.dumps({
        'approved_review_ids':[review_id], 'witness_keys':keys,
        'protocol_witnesses':['TEST_ONLY_witness'], 'inventory_witnesses':['TEST_ONLY_witness']}))
    monkeypatch.setattr(review, 'REVIEW_DIR', root)
    scope = {'procedure_id':fixture['procedure_id'], 'model_id':store.read(policy_id)['model_id'],
             'target':fixture['target'], 'review_id':review_id}
    return scope, (fixture, store, policy_id, store.put(result), key)


def test_supported_case_cannot_be_resigned_as_refusal(tmp_path):
    case = make_refusal_study(tmp_path)
    row = case[-1]['events'][0]
    row.update(disposition='REFUSED', head_shift=None, model_loss=None, reason_codes=['REPORT_GROUP_UNSUPPORTED:complete'])
    def remove_heads(measure):
        measure.pop('head_after'); measure.pop('same_fit_reporting_control_head')
    reseal(case,row,forecast={'status':'REFUSED','reason_codes':row['reason_codes']},
           mutate=remove_heads, products=['coverage'])
    with pytest.raises(RegistryError, match='REFUSAL_NOT_SUPPORTED_BY_POLICY'):
        validate(case)


@pytest.mark.parametrize('kind', ['incumbent', 'independent'])
def test_refused_candidate_still_rejects_late_comparator(tmp_path,kind):
    case = make_refusal_study(tmp_path)
    fixture, _, _, _, data = case
    row = data['events'][1]
    comparator = fixture['store'].read(row[kind+'_forecast_id'])
    comparator['frozen_utc'] = row['result_available_utc']
    row[kind+'_forecast_id'] = fixture['store'].put(comparator)
    resign(fixture,row)
    with pytest.raises(RegistryError, match='COMPARATOR_BINDING'):
        validate(case)


def test_refused_candidate_still_rejects_wrong_settlement_identity(tmp_path):
    case = make_refusal_study(tmp_path)
    fixture, _, _, _, data = case
    row = data['events'][1]
    result = fixture['store'].read(row['result_id'])
    result['event_id'] = 'different-game'
    row['result_id'] = fixture['store'].put(result)
    row['result_witness_id'] = fixture['sign'](row['result_id'], 'missingness_result_reconciliation',
                                               'TEST_ONLY_witness', row['result_available_utc'])
    with pytest.raises(RegistryError, match='SETTLEMENT_BINDING'):
        validate(case)


def test_v2_policy_passes_full_review_and_restricts_future_release(tmp_path,monkeypatch):
    case = make_refusal_study(tmp_path)
    scope, study = approve(case,tmp_path,monkeypatch)
    evidence, sport = release_case.__wrapped__(study,scope)
    assert release_gate.evaluate(evidence)['global_status']=='HEALTHY'
    fixture, store, policy_id, _, key = study
    output = evidence['sports'][sport]['events'][0]['model_outputs'][0]
    receipt = deepcopy(output['missingness_audit'])
    measure = receipt['details']['monitored_strata'][key]
    measure['source_states'] = dict.fromkeys(measure['source_states'],'ACQUISITION_FAILURE')
    measure['same_fit_reporting_control_head'] = measure['head_after']
    output['missingness_audit'] = seal_audit(
        league=receipt['league'],event_id=receipt['event_id'],model_id=receipt['model_id'],
        products=receipt['products'],forecast=output['forecast'],details=receipt['details'])
    block = evidence['sports'][sport]
    inventory = store.read(block['inventory_id'])
    entry = inventory['event_products'][evidence['sports'][sport]['events'][0]['event_key']]['model_outputs'][0]
    entry['receipt_sha256'] = output['missingness_audit']['receipt_sha256']
    block['inventory_id'] = store.put(inventory)
    block['inventory_witness_id'] = fixture['sign'](block['inventory_id'],'missingness_release_inventory',
                                                    'TEST_ONLY_witness',evidence['decision_time_utc'])
    result = release_gate.evaluate(evidence)
    assert result['sports'][sport]['status']=='BLOCKED'
    assert 'MISSINGNESS_EVENT_RECEIPT_OR_SCOPE_INVALID' in result['sports'][sport]['reason_codes']
    assert result['sports']['mls']['status']=='HEALTHY'


def test_legacy_complete_only_limitation_is_preserved_and_v2_is_explicit(tmp_path):
    fixture = make_registry_fixture(tmp_path/'legacy'/'objects')
    store = fixture['store']
    policy_id = fixture['protocol']['missingness_policy_id']
    result = store.read(fixture['evidence']['missingness_evaluation_id'])
    key = next(iter(result['strata']))
    data = store.read(result['strata'][key])
    for row in data['events']:
        receipt = store.read(row['receipt_id'])
        measure = receipt['details']['monitored_strata'][key]
        measure['source_states'] = dict.fromkeys(measure['source_states'],'VERIFIED_OBSERVATION')
        row.update(report_group='complete',missing_rate=0.)
        row['receipt_id'] = store.put(seal_audit(
            league=receipt['league'],event_id=receipt['event_id'],model_id=receipt['model_id'],
            products=receipt['products'],forecast=store.read(row['forecast_id']),details=receipt['details']))
        registration = store.read(row['registration_id'])
        registration['receipt_id'] = row['receipt_id']
        row['registration_id'] = store.put(registration)
        row['registration_witness_id'] = fixture['sign'](
            row['registration_id'],'missingness_pregame_registration','TEST_ONLY_witness',row['registered_at_utc'])
    with pytest.raises(RegistryError, match='INSUFFICIENT_FORWARD_COVERAGE'):
        validate((fixture,policy_id,result,key,data))
    explicit_v2 = make_refusal_study(tmp_path/'v2',all_complete=True)
    assert validate(explicit_v2)['schema']=='sports.missingness_policy.v2'

