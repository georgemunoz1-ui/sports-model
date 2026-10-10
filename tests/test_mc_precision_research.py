import math
import numpy as np
import pytest
from research.mc_precision_v1 import SemanticStreams, PrecisionPlan, PrecisionMonitor, paired_summary, draw_receipt, digest


def stream(**extra):
    return SemanticStreams(**(dict(experiment_id='synthetic-comparison-v1', event_id='FIXTURE', root_seed=722) | extra))


def test_prefix_and_chunk_invariance():
    a, b = stream(), stream()
    expected = a.uniforms('pace', 100_000)
    observed = np.r_[b.uniforms('pace', 70_000), b.uniforms('pace', 30_000)]
    assert np.array_equal(expected, observed)
    assert a.receipt() == b.receipt()
    c = stream()
    assert np.array_equal(c.uniforms('pace', 150_000)[:100_000], expected)


def test_component_order_and_extra_diagnostic_cannot_perturb():
    a, b = stream(), stream()
    expected = a.uniforms('home_efficiency', 50)
    b.uniforms('unrelated_diagnostic', 10_000)
    assert np.array_equal(expected, b.uniforms('home_efficiency', 50))


def test_event_and_replicate_separate_streams():
    a = stream().uniforms('win', 100)
    assert not np.array_equal(a, stream(event_id='OTHER').uniforms('win', 100))
    assert not np.array_equal(a, stream(replicate=1).uniforms('win', 100))


@pytest.mark.parametrize('plan', [lambda: PrecisionPlan(checkpoints=(50_000,)),
    lambda: PrecisionPlan(checkpoints=(100_000,100_000)),lambda: PrecisionPlan(alpha=float('nan')),
    lambda: PrecisionPlan(checkpoints=(True,)),lambda: PrecisionPlan(tolerance=0)])
def test_invalid_plan(plan):
    with pytest.raises(ValueError): plan()


def test_default_does_not_change_100k():
    assert PrecisionPlan().checkpoints == (100_000,)


def test_adaptive_budget_and_honest_exhaustion():
    u = stream().uniforms('win',400_000)
    plan = PrecisionPlan(checkpoints=(100_000,200_000,400_000), tolerance=.003)
    m = PrecisionMonitor(plan, {'win':(0,1)})
    first = m.update({'win':(u[:100_000]<.5)})
    assert first['status']=='CONTINUE'
    middle = m.update({'win':(u[100_000:200_000]<.5)})
    assert middle['status']=='CONTINUE'
    final = m.update({'win':(u[200_000:]<.5)})
    assert final['status']=='PRECISION_MET'
    rare = PrecisionMonitor(plan, {'win':(0,1)})
    assert rare.update({'win':u[:100_000]<.01})['actual_draws']==100_000
    with pytest.raises(ValueError): rare.update({'win':np.ones(2)})
    tight = PrecisionMonitor(PrecisionPlan(tolerance=1e-9),{'win':(0,1)})
    assert tight.update({'win':u[:100_000]<.5})['status']=='BUDGET_EXHAUSTED_UNRESOLVED'


def test_simultaneous_bounds_spend_over_estimands_and_looks():
    values=np.tile([0.,1.],50_000)
    a=PrecisionMonitor(PrecisionPlan(),{'win':(0,1)}).update({'win':values})
    b=PrecisionMonitor(PrecisionPlan(checkpoints=(100_000,200_000)),{'win':(0,1),'push':(0,1)}).update({'win':values,'push':values})
    assert b['estimands']['win']['max_error_bound'] > a['estimands']['win']['max_error_bound']
    n=len(values);v=values.var(ddof=1);log=math.log(4*2*2/.05)
    expected=math.sqrt(2*v*log/n)+7*log/(3*(n-1))
    assert b['estimands']['win']['max_error_bound']==pytest.approx(expected)


def test_zero_observed_tail_never_zero_error_bound():
    r=PrecisionMonitor(PrecisionPlan(),{'tail':(0,1)}).update({'tail':np.zeros(100_000)})
    lo,hi=r['estimands']['tail']['simultaneous_mc_interval']
    assert lo==0 and hi>0


@pytest.mark.parametrize('design',['RQMC','NESTED_REUSED_PARAMETERS','ANTITHETIC_PATHS'])
def test_dependent_paths_not_iid(design):
    with pytest.raises(ValueError): PrecisionMonitor(PrecisionPlan(),{'win':(0,1)},sampling_design=design)


def test_bad_batches_rejected_before_state_mutates():
    m=PrecisionMonitor(PrecisionPlan(),{'win':(0,1)})
    for x in ({'other':[1]}, {'win':[float('nan')]},{'win':[2]}, {'win':[]}, {'win':np.zeros(100_001)}):
        with pytest.raises(ValueError):m.update(x)
        assert m.n==0


def test_paired_comparison_actual_covariance():
    u=stream().uniforms('win',100_000)
    a,b=u<.51,u<.50
    r=paired_summary(a,b)
    assert r['paired_mc_standard_error'] < r['unpaired_reference_standard_error']/5
    assert paired_summary(a,a)['paired_mc_standard_error']==0
    # Negative covariance can make CRN worse, so never assert it always helps.
    reverse=paired_summary(a,~a)
    assert reverse['paired_mc_standard_error'] > reverse['unpaired_reference_standard_error']


def test_paired_signed_bounded_estimator():
    u=stream().uniforms('win',100_000)
    d=(u<.51).astype(float)-(u<.50).astype(float)
    r=PrecisionMonitor(PrecisionPlan(),{'delta':(-1,1)}).update({'delta':d})
    assert r['estimands']['delta']['simultaneous_mc_interval'][0] < .01 < r['estimands']['delta']['simultaneous_mc_interval'][1]


def test_receipt_binds_arrays_model_and_state():
    s=stream(); draws=(s.uniforms('win',100_000)<.5).astype(float)
    precision=PrecisionMonitor(PrecisionPlan(),{'win':(0,1)}).update({'win':draws})
    args=dict(model_id='synthetic-only.v1',code_commit='46eac8e00414c3dd72253282c4a43b3337d28eb9',
        input_sha256=digest({'fixture':1}),state_sha256=digest({'state':1}),distribution_sha256=digest({'p':.5}),
        stream_receipt=s.receipt(),precision_report=precision)
    a=draw_receipt(draws,**args);b=draw_receipt(draws,**args)
    assert a==b
    changed=draw_receipt(draws,**(args|{'model_id':'other.v1'}))
    assert changed['receipt_sha256']!=a['receipt_sha256']
    assert changed['draw_bytes_sha256']==a['draw_bytes_sha256']
    assert not a['action_authority']
    with pytest.raises(ValueError):draw_receipt(draws[:-1],**args)


def test_caller_cannot_mutate_predeclared_bounds():
    bounds={'win':[0,1]}
    m=PrecisionMonitor(PrecisionPlan(),bounds)
    bounds['win'][1]=100
    bounds['extra']=[0,1]
    assert dict(m.bounds)=={'win':(0,1)}
    with pytest.raises(TypeError):m.bounds['win']=(0,100)
    with pytest.raises(ValueError):m.update({'win':[2]})


def test_paired_rejects_dependent_design():
    with pytest.raises(ValueError):paired_summary([0,1],[1,0],sampling_design='RQMC')
