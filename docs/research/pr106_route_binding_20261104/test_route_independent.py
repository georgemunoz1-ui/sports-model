"""Independent route-scope/refusal adversarial probes; synthetic inputs only."""
import copy, importlib.util, json, os, sys
from pathlib import Path
import pytest
REPO=Path(os.environ['VERIFY_REPO']);sys.path.insert(0,str(REPO))
from pipelines.cards import volatility_routing as R
spec=importlib.util.spec_from_file_location('route_fixture_setup', REPO/'tests/test_volatility_routing.py')
F=importlib.util.module_from_spec(spec);spec.loader.exec_module(F)

@pytest.mark.parametrize('field,value', [
 ('projected_margin_orientation','AWAY_MINUS_HOME'),
 ('target','WINNER_PROBABILITY'),
 ('information_set','INPLAY_TEST'),
 ('projected_margin_orientation',None),
 ('target',None),('information_set',None),
])
def test_displayed_scope_mismatch_refuses_before_adapter(tmp_path,monkeypatch,field,value):
 card,config=F.inputs(tmp_path,separate=True)
 x=json.loads(card.read_text());x['forecasts'][0][field]=value;card.write_text(json.dumps(x))
 calls=[]
 def draw(*args,**kwargs):calls.append(True);raise RuntimeError('INDEPENDENT_ADAPTER_CALLED')
 monkeypatch.setattr(R.V,'build',draw)
 receipt=R.run_joint_route(card,config,tmp_path/'out',simulations=100)
 assert not calls, f'displayed {field}={value!r} reached adapter'
 assert receipt['status']=='BLOCKED' and not receipt['adapter_invoked']
 assert receipt['actual_joint_draws']==0 and not receipt['fallback_executed']
 assert (tmp_path/'out/route_receipt.json').is_file()

@pytest.mark.parametrize('payload',[{'forecasts':[None]}, {'forecasts':['bad']}, {'forecasts':[3]}, [1], {'forecasts':{'bad':1}}, {'forecasts':[{}]}])
def test_malformed_card_always_retains_refusal_receipt(tmp_path,monkeypatch,payload):
 card,config=F.inputs(tmp_path,separate=True);card.write_text(json.dumps(payload))
 calls=[]
 monkeypatch.setattr(R.V,'build',lambda *a,**kw:calls.append(True))
 receipt=R.run_joint_route(card,config,tmp_path/'out',simulations=100)
 assert not calls and receipt['status']=='BLOCKED'
 assert receipt['actual_joint_draws']==0 and (tmp_path/'out/route_receipt.json').is_file()

@pytest.mark.parametrize('field,value',[('event_id',float('nan')),('unused_input',float('inf'))])
def test_nonfinite_json_refused_and_receipt_retained(tmp_path,monkeypatch,field,value):
 card,config=F.inputs(tmp_path,separate=True);data=json.loads(card.read_text());data['forecasts'][0][field]=value;card.write_text(json.dumps(data))
 calls=[]
 def draw(*a,**kw):calls.append(True);raise RuntimeError('INDEPENDENT_ADAPTER_CALLED')
 monkeypatch.setattr(R.V,'build',draw)
 receipt=R.run_joint_route(card,config,tmp_path/'out',simulations=100)
 assert not calls and receipt['status']=='BLOCKED'
 assert receipt['actual_joint_draws']==0 and (tmp_path/'out/route_receipt.json').is_file()

@pytest.mark.parametrize('field,value',[
 ('home_id','wrong-home'),('away_id','wrong-away'),('team_id_namespace','OTHER'),('event_id_namespace','OTHER'),('settlement','REGULATION_ONLY'),('start_time_utc','2026-02-01T23:00:00Z'),
])
def test_displayed_identity_mismatch_refuses_before_adapter(tmp_path,monkeypatch,field,value):
 card,config=F.inputs(tmp_path,separate=True);data=json.loads(card.read_text());data['forecasts'][0][field]=value;card.write_text(json.dumps(data))
 calls=[]
 def draw(*a,**kw):calls.append(True);raise RuntimeError('INDEPENDENT_ADAPTER_CALLED')
 monkeypatch.setattr(R.V,'build',draw)
 receipt=R.run_joint_route(card,config,tmp_path/'out',simulations=100)
 assert not calls and receipt['status']=='BLOCKED' and receipt['actual_joint_draws']==0
 assert (tmp_path/'out/route_receipt.json').is_file()

def test_compatible_separate_parent_completes_with_exact_frozen_input_bytes(tmp_path):
 card,config=F.inputs(tmp_path,separate=True);before={p:p.read_bytes() for p in tmp_path.glob('*.json')}
 receipt=R.run_joint_route(card,config,tmp_path/'out',simulations=31)
 assert receipt['status']=='COMPLETED' and receipt['actual_joint_draws']==31
 assert not receipt['action_authority'] and not receipt['fallback_executed'] and not receipt['prospective_grade_eligible']
 assert all(p.read_bytes()==raw for p,raw in before.items())
 assert receipt['input_files_unchanged'] and receipt['explicit_separate_parent']
