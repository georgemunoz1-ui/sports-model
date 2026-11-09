"""Postseason operator sidecar, original kernel pins and refusal cases."""
import json
from pathlib import Path

import pytest
from research.test_mlb_postseason_workflow import fixture
from scripts import mlb_postseason_workflow as workflow
from research.mlb_postseason_v1 import sha
from pipelines.cards.postseason_missingness import check_sidecar
from research import mlb_postseason_context as ctx

ROOT=Path(__file__).resolve().parents[1]


def test_real_postseason_workflow_readback_and_tampered_receipt(tmp_path):
    c,r=fixture(tmp_path)
    run=workflow.run(tmp_path,c,r,tmp_path/'out')['runs'][0]
    folder=Path(run['path']); audit=folder/'missingness_audit.json'
    raw=json.loads(audit.read_bytes())
    assert all(v in ('OBSERVED_STARTER_REQUIRED','INVALID_STARTER') for v in raw['details']['starter_withheld'].values())
    assert len(raw['details']['starter_withheld'])==10
    assert workflow.verify_run(folder)['missingness_audit_sha256']==raw['receipt_sha256']
    audit.unlink()
    with pytest.raises(ValueError,match="POSTSEASON_MISSINGNESS_RECEIPT_REQUIRED"):
        workflow.verify_run(folder)
    raw['details']['historical_support']='PASSED'
    audit.write_text(json.dumps(raw))
    with pytest.raises(ValueError,match="POSTSEASON_MISSINGNESS_RECEIPT_INVALID"):
        check_sidecar(folder,run['result'])


def test_challenger_successor_pins_current_operator_preserves_all_four_fits():
    p=ROOT/'research/registrations/mlb_postseason_context_missingness_v3.json'
    contract=json.loads(p.read_bytes())
    old=ROOT/'research/registrations/mlb_postseason_context_v2.json'
    assert contract['arms']=={str(k):v for k,v in ctx.ARMS.items()}
    assert contract['supersedes_contract_sha256']==sha(old)
    for name,value in contract['code_pins'].items():
        assert value==sha(ROOT/name),name
    assert contract['code_pins']['research/mlb_postseason_context.py']==json.loads(old.read_bytes())['code_pins']['research/mlb_postseason_context.py']


@pytest.mark.parametrize("stage",[1,2,3,4])
def test_each_context_stage_frozen_products_recompute(stage,tmp_path):
    from research.test_mlb_postseason_context import context,event,player
    from pipelines.cards.postseason_missingness import write_sidecar
    e={**event(),"event_id":"MLB:synthetic"}
    features=context()
    for side,record in features.items():
        record["workload"]=ctx.workload(player(),e["slate_date"])
        record["lineup"]={"factor":1.0,"players":{"12":{"pa":0}}} if stage>=2 else None
        record["bullpen"]={"rate":4.2,"members":[{"id":33}]} if stage>=3 else None
    result,draws=ctx.simulate(e,features,stage,128,15,1.1 if stage==4 else None)
    forecast={"model_id":ctx.ARMS[stage],"inputs":e,"context":features,"stage":stage,"result":result}
    pin=write_sidecar(tmp_path,forecast)
    assert check_sidecar(tmp_path,forecast)==pin
    assert draws
    raw=json.loads((tmp_path/"missingness_audit.json").read_bytes())
    if stage>=2:
        assert raw["details"]["applied_context"]["away"]["zero_appearance_lineup_ids"]==["12"]
    assert raw["action_authority"] is False
