"""Real discrete-module and retained shared-card report compatibility, no promotion."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
import pytest
from models.common import discrete_research as D
from research.discrete_mc_v1 import run, select_distribution, write_run, ENGINE_ID
from research.mc_precision_v1 import PrecisionPlan

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=Path(__file__).parent/'fixtures/mc_precision/retained_cfb_distribution_report.json'


def law(league='cfb',product='margin',model_id='fixture.margin.v1',event='FIXTURE',cutoff='2026-10-01T12:00:00Z'):
    settlement=next(iter(D.SETTLEMENTS[league]))
    values=[-3,1,3] if product=='margin' else [1,3,5]
    return D.make_distribution(values,[.2,.3,.5],league=league,product=product,settlement=settlement,
       model_id=model_id,provenance={'event_id':event,'cutoff':cutoff,'fixture':True})


@pytest.mark.parametrize('league',list(D.SETTLEMENTS))
def test_all_sports_use_real_discrete_contract_without_source_changes(league):
    d=law(league);before=copy.deepcopy(d)
    old,old_meta=D.simulate(d)
    paths,r=run([d],line=-1,side='HOME',experiment_id='fixture',root_seed=722)
    after,after_meta=D.simulate(d)
    assert d==before and np.array_equal(old,after) and old_meta==after_meta
    assert r['actual_draws']==100_000 and len(paths[0])==100_000
    assert r['exact_law_probabilities']==[D.price(d,-1,'HOME')]
    for state,p in r['exact_law_probabilities'][0].items():
        lo,hi=r['looks'][-1]['estimands']['arm_0.'+state]['simultaneous_mc_interval']
        assert lo <= p <= hi
    assert not r['action_authority'] and not r['prospective_grade_eligible']
    assert r['engine_id']==ENGINE_ID


def test_actual_retained_card_report_selector_and_cli(tmp_path):
    raw=FIXTURE.read_bytes();payload=json.loads(raw)
    d=payload['results'][0]['distribution']
    with pytest.raises(ValueError):select_distribution(payload)
    selected=select_distribution(payload,event_id=d['provenance']['event_id'],model_id=d['model_id'],product=d['product'])
    assert selected==d
    out=tmp_path/'new-output'
    command=[sys.executable,str(ROOT/'scripts/run_mc_precision_research.py'),'--distribution',str(FIXTURE),
       '--event-id',d['provenance']['event_id'],'--model-id',d['model_id'],'--line','-3',
       '--side','HOME','--experiment-id','retained-cfb-readonly','--seed','722','--output',str(out)]
    result=subprocess.run(command,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    r=json.loads((out/'report.json').read_text())
    assert r['source_files'][0]['file_sha256']==hashlib.sha256(raw).hexdigest()
    assert r['actual_draws']==100_000 and np.load(out/'arm_0_draws.npy').shape==(100_000,)
    assert FIXTURE.read_bytes()==raw
    refused=subprocess.run(command,text=True,capture_output=True)
    assert refused.returncode==2 and 'File exists' in refused.stderr


def test_paired_semantic_samples_preserve_identity_and_prefix():
    a,b=law(),law(model_id='fixture.margin.v2')
    paths,r=run([a,b],line=-1,side='HOME',experiment_id='paired',root_seed=1)
    assert np.array_equal(*paths)
    assert r['arms'][0]['research_simulation_id']!=r['arms'][1]['research_simulation_id']
    assert all(r['looks'][-1]['estimands']['delta_0_minus_1.'+s]['mean']==0 for s in D.STATES)
    larger,_=run([a,b],line=-1,side='HOME',experiment_id='paired',root_seed=1,
                  plan=PrecisionPlan((100_000,200_000),tolerance=1e-8))
    assert np.array_equal(paths[0],larger[0][:100_000])


@pytest.mark.parametrize('other',[lambda:law(event='OTHER'),lambda:law(cutoff='2026-10-01T13:00:00Z'),
    lambda:law('nba'),lambda:law(product='total')])
def test_incompatible_pair_refused(other):
    with pytest.raises(ValueError):run([law(),other()],line=-1,side='HOME',experiment_id='x',root_seed=1)


def test_invalid_authority_hash_and_reports_refused():
    d=law();d['action_authority']=True
    with pytest.raises(ValueError):run([d],line=0,side='HOME',experiment_id='x',root_seed=1)
    report=json.loads(FIXTURE.read_text());report['results'][0]['distribution']['masses'][0]=.2
    with pytest.raises(ValueError,match='CARD_REPORT_HASH_MISMATCH'):select_distribution(report)
    with pytest.raises(ValueError):run([law(),law()],line=0,side='HOME',experiment_id='x',root_seed=1)


def test_mls_quarter_line_and_total_contracts():
    d=law('mls');paths,r=run([d],line=-.75,side='HOME',experiment_id='quarter',root_seed=1)
    assert r['exact_law_probabilities'][0]['half_win']==pytest.approx(.3)
    d=law('nba',product='total')
    _,r=run([d],line=3,side='OVER',experiment_id='total',root_seed=1)
    assert r['exact_law_probabilities'][0]['push']==pytest.approx(.3)


def test_cli_default_and_below_minimum_refusal(tmp_path):
    p=tmp_path/'law.json';p.write_text(json.dumps(law()))
    result=subprocess.run([sys.executable,str(ROOT/'scripts/run_mc_precision_research.py'),'--distribution',str(p),
        '--line','0','--side','HOME','--experiment-id','x','--seed','1','--checkpoints','99999',
        '--output',str(tmp_path/'out')],text=True,capture_output=True)
    assert result.returncode==2 and 'MINIMUM_100K_REQUIRED' in result.stderr
    assert not (tmp_path/'out').exists()
