"""New implementation's engineering tests; not reproduced external test counts."""
import json
from decimal import Decimal, localcontext
import pytest
from models.common.decision_research.engine import decide_payload, FLAGS
from models.common.decision_research.fees import FeeSchedule, Tier, TieredFees
from models.common.decision_research.comparisons import BinarySpread, payout, compare_upgrade, upgrade, expected_profit, incremental_ev
from models.common.decision_research.numeric import InputError


@pytest.fixture
def valid():
    x = dict.fromkeys(FLAGS, True)
    x['dominated_by_executable_alternative'] = False
    x.update(price='0.52', quantity=100, total_entry_fee='1.75', expected_payout='0.56', required_ev_buffer='0.02', available_quantity=100)
    return x


def test_pure_core_never_authorizes(valid):
    d = decide_payload(valid)
    assert d['disposition'] == 'QUALIFIED_CANDIDATE'
    assert d['conservative_net_ev'] == '0.0225'
    assert d['order_authorized'] is False
    assert d['action'] == 'OFF' and d['dose'] == 0.0
    assert d['production_eligible'] is False
    json.dumps(d, allow_nan=False)


@pytest.mark.parametrize('buffer,disposition', [('0.0224','QUALIFIED_CANDIDATE'),('0.0225','PASS_NO_EDGE'),('0.0226','PASS_NO_EDGE')])
def test_strict_buffer(valid, buffer, disposition):
    valid['required_ev_buffer'] = buffer
    assert decide_payload(valid)['disposition'] == disposition


@pytest.mark.parametrize('field,value', [
    ('price', float('nan')), ('price','NaN'),('price','Infinity'),('price','-0.01'),('price','1.01'),('price',0.5),('price',True),
    ('total_entry_fee','-0.1'),('total_entry_fee',None),('required_ev_buffer','-0.1'),('available_quantity',-1),
    ('quantity',0),('quantity','0.5'),('quantity',True),('quantity',1.0),('quantity',10**13),
    ('expected_payout','-0.1'),('expected_payout','1.1'),('expected_payout',False),('expected_payout','-Infinity'),
    ('wagering_enabled','true'),('fees_verified',1),('identity_valid',None),('price','1e-31')])
def test_invalid_rejected_even_if_dominated(valid, field, value):
    valid['dominated_by_executable_alternative'] = True
    valid[field] = value
    d=decide_payload(valid)
    assert d['disposition']=='BLOCKED'
    assert d['order_authorized'] is False


@pytest.mark.parametrize('field', list(FLAGS)+['price','quantity','total_entry_fee','required_ev_buffer'])
def test_missing_required_is_invalid(valid,field):
    valid.pop(field)
    assert decide_payload(valid)['disposition']=='BLOCKED'


@pytest.mark.parametrize('field,expected', [('identity_valid','BLOCKED'),('settlement_verified','BLOCKED'),('state_aligned','BLOCKED'),('quote_fresh','BLOCKED'),('market_open','BLOCKED'),('execution_verified','VERIFY_QUOTE'),('sufficient_size','VERIFY_QUOTE'),('fees_verified','VERIFY_QUOTE'),('valuation_qualified','RESEARCH_ONLY'),('risk_limits_pass','PASS_RISK_LIMIT'),('wagering_enabled','ACTION_DISABLED')])
def test_each_gate(valid,field,expected):
    valid[field]=False
    assert decide_payload(valid)['disposition']==expected


def test_findings_keep_later_failures(valid):
    valid.update(identity_valid=False, execution_verified=False, valuation_qualified=False, risk_limits_pass=False,wagering_enabled=False)
    d=decide_payload(valid)
    assert d['disposition']=='BLOCKED'
    assert d['reasons']==['IDENTITY_INVALID']
    assert set(d['findings'])=={'IDENTITY_INVALID','EXECUTION_UNVERIFIED','NO_QUALIFIED_VALUATION','EXPOSURE_OR_LIQUIDITY_LIMIT','WAGERING_AUTHORITY_OFF'}


def test_dominance_precedes_valuation_but_not_invalid_identity(valid):
    valid.update(dominated_by_executable_alternative=True,valuation_qualified=False,execution_verified=False)
    assert decide_payload(valid)['disposition']=='PASS_NO_EDGE'
    valid['state_aligned']=False
    assert decide_payload(valid)['disposition']=='BLOCKED'


@pytest.mark.parametrize('available',[None,0,99])
def test_actual_size_cannot_be_overridden_by_true_flag(valid,available):
    valid['available_quantity']=available
    assert decide_payload(valid)['disposition']=='VERIFY_QUOTE'


def test_unknown_payout_research_only(valid):
    valid['expected_payout']=None
    assert decide_payload(valid)['disposition']=='RESEARCH_ONLY'


def test_nonmapping():
    assert decide_payload([])['disposition']=='BLOCKED'


@pytest.mark.parametrize('n,fee',[(1,'0.02'),(3,'0.06'),(100,'1.75')])
def test_order_fee(n,fee):
    assert FeeSchedule(rate='0.07').total('0.5',n)==Decimal(fee)


def test_order_rounding_nonlinear():
    f=FeeSchedule(rate='0.07')
    assert 100*f.total('0.5',1)==Decimal('2.00')
    assert f.total('0.5',100)==Decimal('1.75')


def test_minimum_then_increment():
    f=FeeSchedule(rate='0',minimum='0.026',rounding_increment='0.05')
    assert f.total('0.5',1)==Decimal('0.05')


@pytest.mark.parametrize('kwargs',[{'rate':'-0.1'},{'minimum':'-1'},{'rounding_increment':0},{'rate':True},{'rate':0.07},{'schedule_id':''}])
def test_bad_fee_configuration(kwargs):
    with pytest.raises(InputError):FeeSchedule(**kwargs)


def test_tiered_marginal_fees():
    f=TieredFees('illustrative-v1',(Tier(100,'0.01','0.07'),Tier(None,'0','0.04')))
    r=f.calculate('0.50',20,'TAKER',90)
    assert r['total_fee']=='0.28'
    assert [s['quantity'] for s in r['slices']]==[10,10]
    assert Decimal(r['raw_fee'])==Decimal('0.275')
    assert f.calculate('0.50',20,'MAKER',90)['total_fee']=='0.03'
    assert f.calculate('0.50',20,'TAKER',100)['total_fee']=='0.20'


@pytest.mark.parametrize('tiers',[(Tier(100),),(Tier(None),Tier(None)),(Tier(100),Tier(90),Tier(None)),(Tier(100),Tier(100),Tier(None))])
def test_invalid_tier_topology(tiers):
    with pytest.raises(InputError):TieredFees('x',tiers)


def test_rebates_and_bad_roles_rejected():
    with pytest.raises(InputError):Tier(None,maker_rate='-0.01')
    with pytest.raises(InputError):TieredFees('x',(Tier(None),)).calculate('0.5',1,'taker')


@pytest.mark.parametrize('h,m,p',[('6.5',6,1),('6.5',7,0),('9.5',9,1),('9.5',10,0),('-6.5',-7,1),('-6.5',-6,0),('-6.5',0,0),('-0.5',-1,1),('-0.5',0,0)])
def test_signed_spread_boundaries(h,m,p):
    assert payout(BinarySpread('team',h,'0.5'),m)==p


@pytest.mark.parametrize('h',['0','6','-6','6.25','6.75','-6.25'])
def test_nonhalfpoint_refused(h):
    with pytest.raises(InputError):BinarySpread('team',h,'0.5')


def test_ladder_and_full_outcome_proof():
    a=BinarySpread('team','9.5','0.54');b=BinarySpread('team','8.5','0.55')
    r=compare_upgrade(a,b)
    assert r['dominates'] is True
    assert r['additional_winning_margins']==[9]
    assert r['incremental_all_in_cost']=='-0.01'
    assert min(r['outcome_region_representatives'])<8 and max(r['outcome_region_representatives'])>10
    assert compare_upgrade(a,a)['dominates'] is False


def test_negative_handicap_region_floor_and_nested_set():
    a=BinarySpread('team','-6.5','0.49');b=BinarySpread('team','-7.5','0.50')
    r=compare_upgrade(a,b)
    assert r['additional_winning_margins']==[-7]
    assert r['dominates'] is True
    assert compare_upgrade(b,a)['lost_winning_margins']==[-7]


def test_fees_reverse_dominance():
    r=upgrade('9.5','8.5','0.54','0.55',1,FeeSchedule(minimum='0.02'),FeeSchedule())
    assert r['dominates'] is False
    assert r['required_added_probability']=='0.01'


def test_quantity_specific_dominance():
    f=FeeSchedule(minimum='0.02')
    assert not upgrade('9.5','8.5','0.54','0.55',1,f,FeeSchedule())['dominates']
    assert upgrade('9.5','8.5','0.54','0.55',100,f,FeeSchedule())['dominates']


def test_dominance_is_not_positive_ev():
    a=BinarySpread('team','9.5','0.54');b=BinarySpread('team','8.5','0.55')
    pmf={0:'0.1',20:'0.9'}
    assert compare_upgrade(a,b)['dominates']
    assert expected_profit(a,pmf)==Decimal('-0.44')
    assert incremental_ev(a,b,pmf)==Decimal('0.01')


@pytest.mark.parametrize('pmf',[{}, {1:'0.9'}, {1:'NaN'}, {True:'1'}, {1.0:'1'}, {1:'1.1',2:'-0.1'}])
def test_invalid_pmf(pmf):
    with pytest.raises(InputError):expected_profit(BinarySpread('team','9.5','0.54'),pmf)


def test_ambient_decimal_context_does_not_change_decisions_or_fees(valid):
    expected=decide_payload(valid)
    fee=FeeSchedule('0.07').calculate('0.51',103)
    with localcontext() as ctx:
        ctx.prec=3
        assert decide_payload(valid)==expected
        assert FeeSchedule('0.07').calculate('0.51',103)==fee


def test_total_fee_not_subtracted_percontract(valid):
    d=decide_payload(valid)
    assert d['net_ev_total']=='2.25'
    assert Decimal(d['conservative_net_ev'])*100==Decimal('2.25')


@pytest.mark.parametrize('h',['6.500000000000000000000000000001','-6.500000000000000000000000000001'])
def test_near_half_point_is_not_rounded_into_supported_contract(h):
    with localcontext() as ctx:
        ctx.prec=3
        with pytest.raises(InputError):BinarySpread('team',h,'0.5')
