import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import zipfile
import pytest
from scripts import capture_cbb_daily as c, cbb_shadow as shadow
from scripts import cbb_reconciliation_gate as gate, cbb_market_and_grades as market

ARCHIVES = Path(os.environ.get('P0A_ARCHIVE_DIR', '/mnt/data/files'))
SOURCES = [(ARCHIVES/'Morning-Refresh-Evidence-2026-11-25.zip','cbb-25'),
           (ARCHIVES/'Source-Capture-2026-11-26.zip','cbb')]

def write_json(p,x):
    p.write_bytes((json.dumps(x, sort_keys=True, indent=2)+'\n').encode())

@pytest.fixture(scope='module',params=SOURCES)
def replay(request,tmp_path_factory):
    path,prefix=request.param
    if not path.is_file() and 'P0A_ARCHIVE_DIR' not in os.environ:
        pytest.skip('Retained archive not supplied; run offline with P0A_ARCHIVE_DIR')
    root=tmp_path_factory.mktemp('capture'); (root/'raw').mkdir()
    with zipfile.ZipFile(path) as z:
        original=z.read(prefix+'/manifest.json'); m=json.loads(original)
        coverage=z.read(prefix+'/coverage.json'); assert gate.sha(coverage)==m['coverage_sha256']
        for r in m['sources']:
            b=z.read(prefix+'/'+r['file']); assert gate.sha(b)==r['sha256']; (root/r['file']).write_bytes(b)
    (root/'manifest.json').write_bytes(original);(root/'coverage.json').write_bytes(coverage)
    day=dt.datetime.strptime(m['date'],'%Y%m%d').date(); at=gate.timestamp(m['finished_at_utc'])+dt.timedelta(seconds=1)
    # Historical coverage must not silently be reinterpreted under changed mapper.
    with pytest.raises(ValueError,match='RECONCILIATION_REPLAY_MISMATCH'):
        gate.load_evidence(root,gate.sha(original),day,at)
    receipts={r['url']:r for r in m['sources']}
    def get(out,url):
        r=receipts[url];return (root/r['file']).read_bytes(),r
    result=c.daily(day,root/'derived-test-only',get=get)
    # Only a disposable replay fixture. Not a prospective capture/registration.
    write_json(root/'coverage.json',result);m['coverage_sha256']=gate.sha((root/'coverage.json').read_bytes())
    write_json(root/'manifest.json',m);pin=gate.sha((root/'manifest.json').read_bytes())
    evidence=gate.load_evidence(root,pin,day,at)
    return root,pin,day,at,evidence,result

def target(row):
    return dict(id=row['event_id'].split(':')[1],h=row['home_id'],a=row['away_id'],neutral=row['neutral_site'],utc=row['start_time_utc'])

def test_real_capture_cutoff_replay_and_hold(replay):
    root,pin,day,at,e,result=replay
    assert len(e['records'])==len(result['events'])
    hold_count=0;passed=0
    for row in result['events']:
        reason,proof=gate.target_gate(target(row),e,at)
        if row['status']=='IDENTITY_NOT_CROSS_CHECKED':
            hold_count+=1;assert reason=='RECONCILIATION_HOLD:IDENTITY_NOT_CROSS_CHECKED' and proof is None
        if reason is None:
            passed+=1;assert gate.timestamp(proof['pregame_cutoff_utc'])>at
            assert gate.timestamp(proof['pregame_cutoff_utc'])==min(gate.timestamp(row['start_time_utc']),gate.timestamp(row['ncaa_start_time_utc']))
    assert hold_count>=6 and passed>0

def test_manifest_pin_and_stale_clock_refused(replay):
    root,pin,day,at,e,result=replay
    with pytest.raises(ValueError,match='HASH_MISMATCH'):
        gate.load_evidence(root,'0'*64,day,at)
    with pytest.raises(ValueError,match='STALE_OR_FUTURE'):
        gate.load_evidence(root,pin,day,at+dt.timedelta(hours=7))
    with pytest.raises(ValueError,match='STALE_OR_FUTURE'):
        gate.load_evidence(root,pin,day,at-dt.timedelta(minutes=1))

def test_raw_mutation_refused(replay):
    root,pin,day,at,e,result=replay
    m=json.loads((root/'manifest.json').read_bytes());f=root/m['sources'][0]['file'];original=f.read_bytes()
    try:
        f.write_bytes(original+b' ')
        with pytest.raises(ValueError,match='HASH_MISMATCH'):
            gate.load_evidence(root,pin,day,at)
    finally:f.write_bytes(original)

def test_admitted_single_event_replay_matches_daily(replay):
    root,pin,day,at,e,result=replay
    row=next(x for x in result['events'] if x['status']=='PENDING')
    er=e['sources'][row['espn_scoreboard_url']];nr=e['sources'][row['ncaa_scoreboard_url']]
    ep=json.loads((root/er['file']).read_bytes());nc=json.loads((root/nr['file']).read_bytes())
    es=next(x for x in ep['events'] if 'CBB:'+x['id']==row['event_id']);ns=next(x for x in nc['data']['contests'] if x['contestId']==row['ncaa_contest_id'])
    assert c.reconcile_event(es,er,ns,nr)==row

@pytest.fixture
def synthetic():
    start=dt.datetime(2026,12,1,20,tzinfo=dt.timezone.utc);early=start-dt.timedelta(seconds=60);seen=early-dt.timedelta(minutes=20)
    row=dict(event_id='CBB:1',home_id='2',away_id='3',neutral_site=True,start_time_utc=start.isoformat(),ncaa_start_time_utc=early.isoformat(),pregame_cutoff_utc=early.isoformat(),status='PENDING',issues=[],espn_status='STATUS_SCHEDULED',ncaa_status='P',tip_accepted=True,ncaa_contest_id=12,candidate_contest_ids=[12],tip_policy='TOLERANCE_60S',espn_scoreboard_url='espn',ncaa_scoreboard_url='ncaa',espn_scoreboard_sha256='a'*64,ncaa_scoreboard_sha256='b'*64)
    e={'manifest_sha256':'c'*64,'coverage_sha256':'d'*64,'records':{'CBB:1':row},'sources':{'espn':{'sha256':'a'*64,'retrieved_at_utc':seen.isoformat()},'ncaa':{'sha256':'b'*64,'retrieved_at_utc':seen.isoformat()}}}
    return target(row),e,early

def test_earliest_writer_clock_boundary(synthetic):
    g,e,t=synthetic;reason,p=gate.target_gate(g,e,t-dt.timedelta(microseconds=1));assert reason is None
    reason,p=gate.target_gate(g,e,t);assert reason=='NOT_SCHEDULED_PRE_START'
    reason,p=gate.target_gate(g,e,t+dt.timedelta(seconds=1));assert reason=='NOT_SCHEDULED_PRE_START'

def test_identity_and_source_binding(synthetic):
    g,e,t=synthetic;bad=copy.deepcopy(g);bad['a']='wrong';assert gate.target_gate(bad,e,t-dt.timedelta(seconds=1))[0]=='RECONCILIATION_TARGET_IDENTITY_MISMATCH'
    e['sources']['ncaa']['retrieved_at_utc']=t.isoformat();assert gate.target_gate(g,e,t-dt.timedelta(seconds=1))[0]=='RECONCILIATION_SOURCE_NOT_PRETIP_OR_STALE'

def test_card_deadline_and_unbound_cutoff(synthetic):
    g,e,t=synthetic;_,proof=gate.target_gate(g,e,t-dt.timedelta(seconds=1));row={'start_time_utc':g['utc'],'pregame_cutoff_utc':proof['pregame_cutoff_utc'],'schedule_reconciliation':proof};card={'reconciliation_manifest_sha256':e['manifest_sha256'],'reconciliation_coverage_sha256':e['coverage_sha256']}
    assert gate.forecast_deadline(card,row)==t
    with pytest.raises(ValueError,match='UNBOUND'):
        gate.forecast_deadline({},row)
    row['pregame_cutoff_utc']=g['utc']
    with pytest.raises(ValueError,match='INVALID_EARLIEST'):
        gate.forecast_deadline(card,row)

def test_shadow_requires_schedule_evidence(tmp_path):
    with pytest.raises(ValueError,match='RECONCILIATION_EVIDENCE_REQUIRED'):
        shadow.issue(tmp_path,dt.date(2026,12,1),tmp_path/'out')
    assert not (tmp_path/'out').exists()

def test_market_attach_refuses_after_early_cutoff(monkeypatch,synthetic,tmp_path):
    g,e,t=synthetic;_,proof=gate.target_gate(g,e,t-dt.timedelta(seconds=1));row={'event_id':'CBB:1','forecast_status':'FORECAST_GENERATED','settlement':'FULL_GAME_INCLUDING_OVERTIME','start_time_utc':g['utc'],'pregame_cutoff_utc':proof['pregame_cutoff_utc'],'schedule_reconciliation':proof};card={'date':'2026-12-01','as_of_utc':(t-dt.timedelta(seconds=5)).isoformat(),'generated_at_utc':(t-dt.timedelta(seconds=4)).isoformat(),'forecasts':[row],'reconciliation_manifest_sha256':e['manifest_sha256'],'reconciliation_coverage_sha256':e['coverage_sha256']}
    monkeypatch.setattr(market,'capture',lambda *_: ({},{'status':{'type':{'state':'pre'}}},{},{'retrieved_at_utc':(t-dt.timedelta(seconds=10)).isoformat()}))
    class Clock(dt.datetime):
        @classmethod
        def now(cls,tz=None):return t
    monkeypatch.setattr(market,'datetime',Clock)
    result=market.attach(card,tmp_path,'a'*64);assert result['rows'][0]['status']=='QUOTE_UNAVAILABLE';assert 'outside pregame' in result['rows'][0]['detail']

@pytest.fixture
def runner_fixture(monkeypatch,synthetic,tmp_path):
    import numpy as np
    from scripts import verify_cbb_shadow as verifier
    g,e,t=synthetic;g.update(hn='Home',an='Away',day='2026-12-01',d1=True,type=2,status='STATUS_SCHEDULED')
    inputs=tmp_path/'inputs';inputs.mkdir();write_json(inputs/'manifest.json',{'synthetic':True})
    games=[{'season':2026,'utc':'2026-11-20T20:00:00+00:00','id':'history'}]
    records=[dict(id='history',day='2026-11-20',margin=3.,total=140.,p_home=.6,actual_margin=4.,actual_total=144.,prior_margin=2.,prior_total=138.,prior_p_home=.55)]
    monkeypatch.setattr(shadow,'load',lambda *_:(games,[g],{'season':2027},{}))
    monkeypatch.setattr(shadow,'fit',lambda *_:({'2':np.array([2.,1.,6.]),'3':np.array([-1.,0.,6.])},(3.,140.),np.array([[2.,-1.],[-2.,2.],[1.,3.],[-3.,-1.]]),records,2027))
    monkeypatch.setattr(shadow,'load_evidence',lambda *_:e)
    monkeypatch.setattr(verifier,'load_evidence',lambda *_:e)
    # Native score projection/draw writer/verifier are exercised using a toy state;
    # no historical model fit or real prospective forecast is issued.
    monkeypatch.setattr(shadow,'N',10000)
    return shadow,verifier,inputs,e,t

def test_native_writer_refuses_crossing_cutoff(monkeypatch,runner_fixture,tmp_path):
    model,verifier,inputs,e,t=runner_fixture;clocks=iter([t-dt.timedelta(seconds=5)]*3+[t]);monkeypatch.setattr(model,'now',lambda:next(clocks))
    dest=tmp_path/'late'
    with pytest.raises(ValueError,match='FORECAST_WRITER_RECONCILIATION_FAILED'):
        model.issue(inputs,dt.date(2026,12,1),dest,reconciliation_inputs=inputs,reconciliation_manifest_sha256=e['manifest_sha256'])
    assert not (dest/'card.json').exists()

def test_native_writer_and_verifier_bound_cutoff(monkeypatch,runner_fixture,tmp_path):
    model,verifier,inputs,e,t=runner_fixture;monkeypatch.setattr(model,'now',lambda:t-dt.timedelta(seconds=5));dest=tmp_path/'on-time'
    model.issue(inputs,dt.date(2026,12,1),dest,reconciliation_inputs=inputs,reconciliation_manifest_sha256=e['manifest_sha256']);raw=(dest/'card.json').read_bytes();card=json.loads(raw)
    assert card['forecasts'][0]['pregame_cutoff_utc']==t.isoformat()
    result=verifier.verify(inputs,dest,gate.sha(raw),reconciliation_inputs=inputs);assert result['forecasts_replayed']==1
    card['generated_at_utc']=t.isoformat();write_json(dest/'card.json',card)
    with pytest.raises(ValueError,match='LATE_OR_WRONG_SCOPE'):
        verifier.verify(inputs,dest,gate.sha((dest/'card.json').read_bytes()),reconciliation_inputs=inputs)
