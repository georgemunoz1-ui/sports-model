"""Independent mathematical and lineage challenges; all observations synthetic."""
import copy
import hashlib
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__import__('os').environ['VERIFY_REPO'])
sys.path.insert(0, str(REPO))
from models.common import discrete_research as D
from models.common import volatility_matrix_v1 as V
from models.common import volatility_scoring_v2 as S

def dist(event, pairs, weights, model='independent.synthetic'):
    return V.make_joint([p[0] for p in pairs], [p[1] for p in pairs], weights,
        league='mls', settlement='REGULATION_90_STOPPAGE', model_id=model,
        provenance={'event_id':event,'parent_forecast_sha256':'f'*64,
                    'cutoff':'2026-01-01T00:00:00Z','start_time_utc':'2026-01-01T03:00:00Z'})

def result(d, h=4, a=2):
    return S.account_result(d, actual_home=h, actual_away=a,
        result_source_sha256='a'*64,result_available_at='2026-01-01T06:00:00Z')

def seal(r):
    r.pop('artifact_sha256', None)
    r['artifact_sha256']=D.digest(r)
    return r

def reference(d, y):
    pairs=list(zip(d['home_scores'],d['away_scores']))
    weights=d['masses']
    first=math.fsum(w*math.dist(x,y) for x,w in zip(pairs,weights))
    second=math.fsum(w*v*math.dist(x,z) for x,w in zip(pairs,weights) for z,v in zip(pairs,weights))
    return first-.5*second

@pytest.mark.parametrize('pairs,weights,observed',[
    ([(0,0)],[1],(2,3)),
    ([(0,1),(2,3),(9,4)],[.2,.3,.5],(4,2)),
    ([(1,9),(2,8),(8,2),(9,1)],[.1,.2,.3,.4],(5,5)),
])
def test_raw_energy_matches_independent_euclidean_sum(pairs,weights,observed):
    d=dist('sum',pairs,weights)
    assert S.energy_score(d,*observed)['energy_score']==pytest.approx(reference(d,observed),abs=1e-12)

def test_coordinate_permutation_and_translation_equivariance():
    pairs=[(0,1),(2,3),(9,4)];weights=[.2,.3,.5];y=(4,2)
    base=S.energy_score(dist('base',pairs,weights),*y)['energy_score']
    swapped=S.energy_score(dist('swap',[(a,h) for h,a in pairs],weights),y[1],y[0])['energy_score']
    translated=S.energy_score(dist('translation',[(h+11,a+7) for h,a in pairs],weights),y[0]+11,y[1]+7)['energy_score']
    scaled=S.energy_score(dist('scale',[(2*h,2*a) for h,a in pairs],weights),2*y[0],2*y[1])['energy_score']
    assert swapped==pytest.approx(base)
    assert translated==pytest.approx(base)
    assert scaled==pytest.approx(2*base)

def test_expected_score_minimized_by_known_joint_law_on_candidate_grid():
    pairs=[(1,0),(2,3),(5,1)];truth=[.2,.3,.5]
    true=dist('truth',pairs,truth)
    def expectation(d):
        return math.fsum(p*S.energy_score(d,*y)['energy_score'] for y,p in zip(pairs,truth))
    optimum=expectation(true)
    for i in range(11):
        for j in range(11-i):
            mass=[i/10,j/10,(10-i-j)/10]
            assert expectation(dist('candidate',pairs,mass))>=optimum-1e-12

@pytest.mark.parametrize('field,value',[
    ('event_id','other'),('parent_forecast_sha256','0'*64),
    ('forecast_cutoff','2026-01-01T00:01:00Z'),
    ('start_time_utc','2026-01-01T04:00:00Z'),
    ('parent_joint_distribution_sha256','0'*64),
])
def test_rehashed_legacy_wrong_parent_refuses(field,value):
    d=dist('original',[(2,1),(4,3)],[.5,.5])
    prior=V.account_result(d,actual_home=4,actual_away=2,
        result_source_sha256='a'*64,result_available_at='2026-01-01T06:00:00Z')
    bad=copy.deepcopy(prior);bad[field]=value;seal(bad)
    with pytest.raises(ValueError):S.rescore_legacy(d,bad)

def test_legacy_numeric_value_is_not_implicitly_included():
    d1=dist('e1',[(0,0),(8,8)],[.5,.5]);d2=dist('e2',[(0,0),(8,8)],[.5,.5])
    prior=V.account_result(d1,actual_home=4,actual_away=2,
        result_source_sha256='a'*64,result_available_at='2026-01-01T06:00:00Z')
    encoded=D.digest(prior);dist_hash=D.digest(d1)
    with pytest.raises(ValueError):S.evaluate([prior,result(d2)],evaluated_at='2026-01-02T00:00:00Z')
    successor=S.rescore_legacy(d1,prior)
    assert successor['joint_energy_score']['energy_score']==pytest.approx(reference(d1,(4,2)))
    assert successor['rescoring_parent']['artifact_sha256']==prior['artifact_sha256']
    assert successor['independent_event_evidence_added'] is False
    assert D.digest(prior)==encoded and D.digest(d1)==dist_hash

@pytest.mark.parametrize('mutation',[ 'metric_version','fixed_scale','metric_digest','score_code','league','model','duplicate','late'])
def test_rehashed_incompatible_v2_record_refuses(mutation):
    records=[result(dist(e,[(1,0),(3,1)],[.5,.5])) for e in ('e1','e2')]
    r=records[1]
    if mutation=='metric_version':r['joint_energy_score']['metric']['version']=1
    elif mutation=='fixed_scale':r['joint_energy_score']['metric']['component_scale']=[2,2]
    elif mutation=='metric_digest':r['joint_energy_score']['metric']['metric_contract_sha256']='0'*64
    elif mutation=='score_code':r['joint_energy_score']['scoring_code_sha256']='0'*64
    elif mutation=='league':r['league']='nba'
    elif mutation=='model':r['model_id']='different-model'
    elif mutation=='duplicate':r['event_id']='e1'
    else:r['result_available_at']='2026-01-02T00:00:00Z'
    seal(r)
    with pytest.raises(ValueError):S.evaluate(records,evaluated_at='2026-01-02T00:00:00Z')
