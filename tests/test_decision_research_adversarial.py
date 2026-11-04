"""Independent boundary checks; synthetic inputs are never venue evidence."""
from decimal import Decimal as D, localcontext
import sqlite3

import pytest

from models.common.decision_research.comparisons import BinarySpread, compare_upgrade, payout
from models.common.decision_research.engine import FLAGS, decide_payload
from models.common.decision_research.fees import FeeSchedule, Tier, TieredFees
from models.common.decision_research.numeric import InputError
from models.common.decision_research.repository import SQLiteRepository, RepositoryError


def _payload():
    flags = {key: True for key in FLAGS}
    flags['dominated_by_executable_alternative'] = False
    return dict(flags, price='0.52', quantity=100, total_entry_fee='1.75',
                required_ev_buffer='0.02', expected_payout='0.56', available_quantity=100)


def test_engine_output_actually_persists_without_float_coercion(tmp_path):
    db = sqlite3.connect(tmp_path / 'core.sqlite')
    repo = SQLiteRepository(db)
    repo.migrate()
    repo.add_comparison('c1', _payload())
    decision = repo.evaluate('c1', decide_payload, 'r1')
    assert decision['order_authorized'] is False
    assert decision['production_eligible'] is False
    assert decision['conservative_net_ev'] == '0.0225'
    assert repo.verify_audit()
    assert repo.evaluate('c1', decide_payload, 'r1') == decision
    assert repo.checkpoint()['count'] == 1


@pytest.mark.parametrize('handicap', ['-9.5', '-8.5', '-6.5', '-0.5', '0.5', '6.5', '9.5'])
def test_signed_line_payout_full_boundary(handicap):
    c = BinarySpread('selected', handicap, '0.5')
    for margin in range(-12, 13):
        assert payout(c, margin) == D(int(D(margin) < D(handicap)))


def test_favorite_upgrade_added_set_is_not_decimal_truncation():
    result = compare_upgrade(BinarySpread('c', '-6.5', '0.54'), BinarySpread('b', '-8.5', '0.55'))
    assert result['additional_winning_margins'] == [-8, -7]
    assert result['candidate_dominates'] is True


@pytest.mark.parametrize('candidate,baseline', [('9.5', '8.5'), ('-6.5', '-8.5'), ('-0.5', '0.5'), ('8.5', '8.5')])
@pytest.mark.parametrize('cprice,bprice', [('0.54', '0.55'), ('0.55', '0.54'), ('0.55', '0.55')])
def test_region_dominance_matches_exhaustive_integer_check(candidate, baseline, cprice, bprice):
    c, b = BinarySpread('c', candidate, cprice), BinarySpread('b', baseline, bprice)
    result = compare_upgrade(c, b, quantity=3, candidate_fees=FeeSchedule(minimum='0.02'))
    diff = [3 * (payout(c,m) - payout(b,m)) - (D(result['candidate_total_cost']) - D(result['baseline_total_cost'])) for m in range(-30,31)]
    assert result['candidate_dominates'] == (all(x >= 0 for x in diff) and any(x > 0 for x in diff))


@pytest.mark.parametrize('value', [True, False, 0.52, D('NaN'), D('Infinity'), '-0.01', '1.01'])
def test_invalid_price_cannot_be_saved_as_qualified(value):
    data = _payload(); data['price'] = value
    decision = decide_payload(data)
    assert decision['disposition'] == 'BLOCKED'
    assert decision['order_authorized'] is False


@pytest.mark.parametrize('flag', FLAGS)
def test_string_true_never_grants_core_gate(flag):
    data = _payload(); data[flag] = 'true'
    assert decide_payload(data)['disposition'] == 'BLOCKED'


def test_exact_buffer_total_comparison_not_rounded_per_contract():
    data = _payload(); data.update(quantity=3, available_quantity=3, price='0.5', total_entry_fee='0.01', expected_payout='0.55', required_ev_buffer='0.046666666666666666666666666667')
    assert decide_payload(data)['disposition'] == 'PASS_NO_EDGE'


def test_order_minimum_not_linear_across_order_count():
    schedule = FeeSchedule(rate='0.07')
    assert schedule.total('0.50', 100) == D('1.75')
    assert 100 * schedule.total('0.50', 1) == D('2.00')


def test_tier_boundary_uses_actual_slice_quantity():
    schedule = TieredFees('illustrative', (Tier(100, '0.01','0.07'), Tier(None, '0','0.04')))
    result = schedule.calculate('0.50', 20, 'TAKER', prior_volume=90)
    assert [x['quantity'] for x in result['slices']] == [10,10]
    assert result['total_fee'] == '0.28'
    assert result['venue_schedule_verified'] is False


def test_ambient_decimal_precision_cannot_change_economics():
    with localcontext() as ctx:
        ctx.prec=2
        assert FeeSchedule(rate='0.07').total('0.5',100)==D('1.75')
        assert decide_payload(_payload())['conservative_net_ev']=='0.0225'


def test_raw_sql_missing_authority_flag_rejected(tmp_path):
    db=sqlite3.connect(tmp_path/'constraints.sqlite');repo=SQLiteRepository(db);repo.migrate()
    sha=repo.add_comparison('c1',_payload())
    with pytest.raises(sqlite3.IntegrityError):
        db.execute('INSERT INTO decision_research_audit VALUES (?,?,?,?,?,?,?,?,?)',
          (1,'r1','c1','e1','2026-11-04T03:00:00+00:00',sha,'{}','0'*64,'1'*64))
    db.rollback()
    assert repo.checkpoint()['count']==0


def test_external_checkpoint_detects_full_history_removal(tmp_path):
    db=sqlite3.connect(tmp_path/'audit.sqlite');repo=SQLiteRepository(db);repo.migrate()
    repo.add_comparison('c1',_payload());repo.evaluate('c1',decide_payload,'r1')
    checkpoint=repo.checkpoint()
    # Explicit administrator tamper; ordinary DELETE is blocked separately.
    db.execute('DROP TRIGGER decision_research_audit_no_delete')
    db.execute('DELETE FROM decision_research_audit');db.commit()
    assert repo.verify_audit()  # Empty history alone cannot prove truncation.
    assert not repo.verify_audit(expected_head=checkpoint['head'],expected_count=checkpoint['count'])

@pytest.mark.parametrize('line',['6.500000000000000000000000000001','-6.500000000000000000000000000001'])
def test_near_halfpoint_decimal_never_rounds_into_supported_line(line):
    with pytest.raises(InputError):
        BinarySpread('near-boundary',line,'0.5')


def _evidence_request(tmp_path, *, line='6.5', state_time='2026-11-04T01:00:00+00:00'):
    import hashlib,json
    docs={
      'contract':{'contract_id':'c1','event_id':'e1','league':'CFB','selection_team_id':'t1','period':'FULL_GAME','rules_id':'r1','currency':'USD','line':line,'market_type':'SPREAD','payout_unit':'1'},
      'quote':{'quote_id':'q1','contract_id':'c1','state_id':'s1','venue':'synthetic','fee_schedule_id':'f1','observed_at_utc':'2026-11-04T01:03:00+00:00','retrieved_at_utc':'2026-11-04T01:04:00+00:00','market_open':True,'buy_price':'0.52','available_quantity':100},
      'state':{'state_id':'s1','event_id':'e1','league':'CFB','home_team_id':'t1','away_team_id':'t2','phase':'PRE_GAME','observed_at_utc':state_time,'scheduled_start_utc':'2026-11-04T20:00:00+00:00'},
      'model':{'model_id':'m1','forecast_id':'forecast1','contract_id':'c1','event_id':'e1','state_id':'s1','created_at_utc':'2026-11-04T01:02:00+00:00','cutoff_utc':'2026-11-04T01:01:00+00:00','expected_payout':'0.56'},
      'rules':{'rules_id':'r1','period':'FULL_GAME','currency':'USD','venue':'synthetic','payoff_function_id':'binary_half_spread.v1','payout_unit':'1'},
      'fee_schedule':{'schedule_id':'f1','venue':'synthetic','currency':'USD','effective_at_utc':'2026-11-01T00:00:00+00:00','expires_at_utc':'2026-12-01T00:00:00+00:00','rate':'0.07','minimum':'0','rounding_increment':'0.01'},
      'configuration':{'configuration_id':'config1','max_quote_age_seconds':600,'max_state_age_seconds':600,'required_ev_buffer':'0.02'},
    }
    refs={}
    for kind,value in docs.items():
        raw=json.dumps(value).encode();(tmp_path/f'{kind}.json').write_bytes(raw)
        refs[kind]={'path':f'{kind}.json','sha256':hashlib.sha256(raw).hexdigest()}
    return {'comparison_id':'comparison1','quantity':100,'evidence':refs}


def test_bridge_cannot_round_fractional_line_into_binary_support(tmp_path):
    from datetime import datetime,timezone
    from models.common.decision_research.compatibility import assess
    request=_evidence_request(tmp_path,line='6.500000000000000000000000000001')
    result=assess(request,tmp_path,now=datetime(2026,11,4,1,5,tzinfo=timezone.utc))
    assert not result.get('compatibility',{}).get('binary_contract',False)
    assert result['order_authorized'] is False


def test_state_bound_to_forecast_must_not_arrive_after_cutoff(tmp_path):
    from datetime import datetime,timezone
    from models.common.decision_research.compatibility import assess
    request=_evidence_request(tmp_path,state_time='2026-11-04T01:02:30+00:00')
    result=assess(request,tmp_path,now=datetime(2026,11,4,1,5,tzinfo=timezone.utc))
    assert not result['compatibility']['chronology_and_freshness']


def test_matching_hashes_and_true_flags_do_not_authenticate_fixture(tmp_path):
    from datetime import datetime,timezone
    from models.common.decision_research.compatibility import assess
    request=_evidence_request(tmp_path)
    result=assess(request,tmp_path,now=datetime(2026,11,4,1,5,tzinfo=timezone.utc))
    assert result['disposition']=='BLOCKED'
    assert result['source_authenticity']=='NOT_VERIFIED'
    assert result['candidate'] is None
    assert result['order_authorized'] is False
    request['wagering_enabled']=True
    result=assess(request,tmp_path,now=datetime(2026,11,4,1,5,tzinfo=timezone.utc))
    assert result['disposition']=='BLOCKED'
    assert any('no caller gates' in x for x in result['findings'])


def test_embedded_source_verification_booleans_cannot_grant_trust(tmp_path):
    from datetime import datetime,timezone
    import hashlib,json
    from models.common.decision_research.compatibility import assess
    request=_evidence_request(tmp_path)
    for kind in ('model','rules','fee_schedule','quote'):
        p=tmp_path/f'{kind}.json';value=json.loads(p.read_text())
        value.update(verified=True,valuation_qualified=True,execution_verified=True,wagering_enabled=True)
        raw=json.dumps(value).encode();p.write_bytes(raw)
        request['evidence'][kind]['sha256']=hashlib.sha256(raw).hexdigest()
    result=assess(request,tmp_path,now=datetime(2026,11,4,1,5,tzinfo=timezone.utc))
    assert result['disposition']=='BLOCKED'
    assert result['decision']['production_eligible'] is False
    assert result['decision']['order_authorized'] is False
    assert 'NO_QUALIFIED_VALUATION' in result['findings']


@pytest.mark.parametrize('raw_request',[[],None,'bad'])
def test_cli_nonobject_json_preserves_auditable_refusal(tmp_path,raw_request):
    import json,subprocess,sys
    from pathlib import Path
    source=tmp_path/'request.json';source.write_text(json.dumps(raw_request))
    evidence=tmp_path/'evidence';evidence.mkdir();out=tmp_path/'output'
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,str(root/'scripts/run_contract_decision_research.py'),
        '--request',str(source),'--evidence-root',str(evidence),'--output',str(out)],capture_output=True,text=True)
    assert result.returncode==2,result.stderr
    receipt=json.loads((out/'decision.json').read_text())
    assert receipt['decision']['disposition']=='BLOCKED'
    assert receipt['audit_checkpoint']['count']==1
    assert receipt['order_authorized'] is False
