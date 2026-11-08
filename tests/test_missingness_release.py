"""Release and study controls exercised independently of the card writer."""
import base64
from copy import deepcopy
import json
from datetime import timedelta

import pytest
from harness import release_gate
from pipelines.cards.missingness import content_digest, factorial_attribution, observation_state
from research import missingness_review as review
from research.validation_registry import RegistryError, _time
from test_validation_registry import make_registry_fixture


def test_missing_does_not_mean_verified_empty():
    values = dict(acquired=True, published=True, identity_resolved=True, complete=True, count=0)
    assert observation_state(**values) == "VERIFIED_ABSENCE"
    for key, expected in [('acquired','ACQUISITION_FAILURE'), ('published','NOT_YET_PUBLISHED'),
                          ('identity_resolved','UNRESOLVED_IDENTITY_OR_COVERAGE'),
                          ('complete','UNRESOLVED_IDENTITY_OR_COVERAGE')]:
        assert observation_state(**{**values, key:False}) == expected
    assert observation_state(**{**values,'count':1}) == 'VERIFIED_OBSERVATION'


def test_nonlinear_interaction_and_unavailable_counterfactual():
    res = factorial_attribution(original=3, sporting_only=5, reporting_only=6, refreshed=12)
    assert [res[k] for k in ('sporting','missingness_imputation','interaction')]==[2,3,4]
    assert factorial_attribution(original=.5, sporting_only=None, reporting_only=.6, refreshed=.7)['interaction'] is None


@pytest.fixture
def study(tmp_path):
    f=make_registry_fixture(tmp_path/'objects')
    s=f['store']
    policy_id=f['protocol']['missingness_policy_id']; results_id=f['evidence']['missingness_evaluation_id']
    result=s.read(results_id); key=next(iter(result['strata']))
    return f,s,policy_id,results_id,key


@pytest.mark.parametrize('field,value', [('registered_at_utc','2026-01-02T00:01:00Z'), ('model_loss',-1),
                                         ('model_loss',.9),('missing_rate',.123),('head_shift',0),('report_group','missing')])
def test_hash_consistent_altered_forward_row_is_rejected(study,field,value):
    f,s,pid,rid,key=study; res=s.read(rid); data=s.read(res['strata'][key])
    data['events'][0][field]=value; res['strata'][key]=s.put(data)
    with pytest.raises(RegistryError):
        review.validate_study(s,pid,s.put(res),f['procedure_id'],f['target'],_time(f['protocol']['evaluation_start_utc']),
                              _time(f['protocol']['evaluation_end_utc']),verifier=f['verifier'])


def test_signed_inventory_and_exact_product_before_release(study, tmp_path, monkeypatch):
    f,s,pid,rid,key=study
    p=f['protocol']; gate_time=f['at_utc']
    record={"procedure_id":f['procedure_id'],"target":f['target'],"author":"TEST_ONLY_author","reviewer":"TEST_ONLY_reviewer",
            "policy_frozen_utc":p['development_end_utc'],"confirmation_start_utc":p['evaluation_start_utc'],
            "confirmation_end_utc":p['evaluation_end_utc'],"reviewed_utc":f['evidence']['computed_at_utc'],
            "expires_utc":"2026-12-31T00:00:00Z","policy_id":pid,"results_id":rid}
    review_id=s.put(record); model=s.read(pid)['model_id']; scope={"target":f['target'],"procedure_id":f['procedure_id'],
                                                               "review_id":review_id,"model_id":model}
    keys={k:base64.b64encode(v.public_key().public_bytes_raw()).decode() for k,v in f['keys'].items()}
    (tmp_path/'approved.json').write_text(json.dumps({"approved_review_ids":[review_id],"witness_keys":keys,
                                                      "inventory_witnesses":["TEST_ONLY_witness"]}))
    monkeypatch.setattr(review,"REVIEW_DIR",tmp_path)
    fr=s.read(s.read(s.read(rid)['strata'][key])['events'][0]['forecast_id'])
    receipt=s.read(s.read(s.read(rid)['strata'][key])['events'][0]['receipt_id'])
    sport=f['target']['league']
    out={"forecast":fr,"products":receipt['products'],"missingness_audit":receipt,
         "model_id":model,"procedure_id":f['procedure_id'],"target":f['target'],"start_utc":"2026-12-31T15:00:00Z"}
    def signed_inventory(league,events):
        el={r['event_key']:[{**{k:o[k] for k in ('model_id','procedure_id','target','start_utc')},
                                'forecast_sha256':content_digest(o['forecast']), 'receipt_sha256':o['missingness_audit']['receipt_sha256']}
                              for o in r['model_outputs']] for r in events}
        i=s.put({"league":league,"state":"VERIFIED_OBSERVATION" if events else "VERIFIED_ABSENCE",
                 "event_products":el,"cutoff_utc":gate_time,"expires_utc":(_time(gate_time)+timedelta(hours=2)).isoformat()})
        return {"inventory_id":i,"inventory_witness_id":f["sign"](i,"missingness_release_inventory","TEST_ONLY_witness",gate_time)}
    sports={}
    for league in release_gate.SPORTS:
        events=[{"event_key":receipt['event_id'],"disposition":"COMPLETE","model_outputs":[out]}] if league==sport else []
        sports[league]={"expected_event_count":len(events),"events":events,"gates":{g:{"status":"PASS"} for g in release_gate.REQUIRED_GATES},
                        "missingness_reviews":[scope] if events else [], **signed_inventory(league,events)}
    e={"decision_time_utc":gate_time,"enabled_sports":list(release_gate.SPORTS),"sports":sports}
    assert release_gate.evaluate(e)['global_status']=='HEALTHY'
    bad=deepcopy(e); bad['sports'][sport]['events'][0]['model_outputs'][0]['target']['period']='some other period'
    assert release_gate.evaluate(bad)['sports'][sport]['status']=='BLOCKED'
    del e['sports']['nba']['inventory_witness_id']
    v=release_gate.evaluate(e)
    assert v['sports']['nba']['status']=='BLOCKED' and v['sports'][sport]['status']=='HEALTHY'


def test_inventory_accounts_for_every_run_command():
    from pathlib import Path
    repo=Path(__file__).resolve().parents[1]
    registry=json.loads((repo/'data/model_selection/missingness/runner_inventory.json').read_bytes())
    registered=set(registry['active_research']) | set(registry['other_run_commands'])
    assert not set(registry['active_research']) & set(registry['other_run_commands'])
    assert all((repo/name).is_file() for name in registered)
    assert {p.relative_to(repo).as_posix() for p in (repo/'scripts').glob('run_*.py')} <= registered


def test_legacy_release_can_be_read_back_but_cannot_be_gated_as_current():
    from pathlib import Path
    repo=Path(__file__).resolve().parents[1]
    historical,problems=release_gate.verify_artifact(repo/'data/acquisition/2026-09-03_update.json',
                                                       repo/'data/releases/2026-09-03_release.json')
    assert not problems
    assert historical['schema']=='ops.release_manifest.v1'
    fresh=release_gate.evaluate(json.loads((repo/'data/acquisition/2026-09-03_update.json').read_bytes()))
    assert fresh['schema']=='ops.release_manifest.v2' and fresh['global_status']=='BLOCKED'
