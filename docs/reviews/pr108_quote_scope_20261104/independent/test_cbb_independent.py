"""Independent quote scope, arithmetic, and parent-preservation probes."""
import copy, importlib.util, json, os, sys, hashlib, ast, subprocess
from pathlib import Path
import pytest
REPO=Path(os.environ['VERIFY_REPO']);sys.path.insert(0,str(REPO))
from scripts.capture_cbb_daily import paired_market_quotes as parser, normalize, quote
from scripts.cbb_market_and_grades import market_rows, attach
spec=importlib.util.spec_from_file_location('quote_fixture_setup', REPO/'tests/test_cbb_quote_scope.py')
F=importlib.util.module_from_spec(spec);spec.loader.exec_module(F)

@pytest.mark.parametrize('value',[{},[],True,False,'',-110.5,'not-a-price'])
def test_malformed_odds_refuse_event_without_partial_earlier_quotes(tmp_path,value):
 book=F.offer();book['pointSpread']['home']['close']['odds']=value
 card,raws,recs=F.synthetic_assessment(tmp_path,[book])
 before={p:p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()};parent=copy.deepcopy(card)
 with pytest.raises(ValueError):parser(raws[0])
 result=attach(card,tmp_path,'a'*64)
 assert result['rows'][0]['status']=='QUOTE_UNAVAILABLE' and result['rows'][0]['contracts']==[]
 assert len(result['rows'][1]['contracts'])==6 and card==parent
 assert all(p.read_bytes()==raw for p,raw in before.items())

@pytest.mark.parametrize('bad',[None,{},'bad',{'provider':{}},{'provider':{'name':True}},{'provider':{'name':' '}}])
def test_malformed_provider_alongside_valid_book_refuses(tmp_path,bad):
 card,raws,recs=F.synthetic_assessment(tmp_path,[F.offer(),bad])
 with pytest.raises(ValueError):parser(raws[0])
 assert attach(card,tmp_path,'a'*64)['rows'][0]['contracts']==[]

@pytest.mark.parametrize('kind',['same','line','price'])
@pytest.mark.parametrize('reverse',[False,True])
def test_duplicate_book_is_order_independent_refusal(tmp_path,kind,reverse):
 a=F.offer();b=copy.deepcopy(a)
 if kind=='line':b['pointSpread']['home']['close']['line']='-8';b['pointSpread']['away']['close']['line']='8'
 if kind=='price':b['moneyline']['home']['close']['odds']='-140'
 books=[a,b];books=books[::-1] if reverse else books
 card,raws,recs=F.synthetic_assessment(tmp_path,books)
 with pytest.raises(ValueError,match='AMBIGUOUS_BOOK'):quote(normalize(raws[0]['header'],{'1','2'}),raws[0],recs[0])
 result=attach(card,tmp_path,'a'*64)
 assert result['rows'][0]['contracts']==[] and len(result['rows'][1]['contracts'])==6

def test_absence_and_explicit_off_remain_unquoted():
 assert parser({})==(None,[])
 assert parser({'pickcenter':[{'provider':{'name':'Other'}}]})==(None,[])
 book=F.offer();del book['pointSpread'];book['total']['over']['close']={'odds':'OFF'}
 _,rows=parser({'pickcenter':[book]})
 assert {q['product'] for q in rows}=={'winner'}

def test_quote_probability_matches_independent_event_enumeration(tmp_path):
 card,raws,recs=F.synthetic_assessment(tmp_path,[F.offer()]);f=card['forecasts'][0]
 rows=market_rows(raws[0],f)
 for q in rows:
  if q['product']=='winner':continue
  pmf=f['distributions'][q['product']]
  def value(k):
   if q['product']=='margin':return (k if q['side']=='home' else -k)+q['line']
   return (k-q['line'])*(1 if q['side']=='over' else -1)
  for outcome,fn in [('win',lambda x:x>0),('push',lambda x:x==0),('loss',lambda x:x<0)]:
   expected=sum(p for k,p in zip(pmf['support'],pmf['masses']) if fn(value(k)))
   assert q[outcome]==pytest.approx(expected)

def test_original_scoring_reconciliation_and_identity_functions_unchanged():
 paths={'scripts/cbb_market_and_grades.py':['probability','verified_card','identity','source_json','capture','attach','reconciled_result','grade'], 'scripts/capture_cbb_daily.py':['normalize','reconcile_event','sides','american']}
 for path,names in paths.items():
  prior=subprocess.check_output(['git','-C',str(REPO),'show','655bf57df4f230938374617a5d83161d739c4401:'+path]).decode()
  def nodes(txt):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(txt).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
  old,new=nodes(prior),nodes((REPO/path).read_text())
  for name in names:assert old[name]==new[name],path+':'+name
