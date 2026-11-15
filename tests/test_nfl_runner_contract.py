"""Focused regressions for the dated package path, including a real, labelled retained replay."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from pipelines.cards.nfl_runner_contract import read_forecast
from models.nfl.contextual.recovered_inference import utc

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT/'data/nfl/personnel_resolution_20260914/event_package.json'
CUTOFF='2026-09-15T00:12:00Z'
DAY='2026-09-14'
GOOD='2026_01_DEN_KC'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(output, package, pin=None, day=DAY, cutoff=CUTOFF, replay=True):
    return subprocess.run([sys.executable,str(ROOT/'scripts/run_nfl_integrated.py'),'--date',day,
        '--output',str(output),'--simulations','100','--event-package',str(package),'--event-package-sha256',
        pin or sha(package.read_bytes()),'--replay-cutoff-utc' if replay else '--as-of-utc',cutoff],
        cwd=ROOT,capture_output=True,text=True)


def receipt(path):
    return json.loads((path/'nfl_runner_receipt.json').read_bytes())


def test_frozen_week_one_replay_and_distinct_partial_refusal(tmp_path):
    pkg=json.loads(PACKAGE.read_bytes())
    for name in ('model_path','recovered_parameters_path'):
        pkg[name]=str((PACKAGE.parent/pkg[name]).resolve())
    missing=dict(pkg['events'][0],event_id='2026_01_BUF_NYJ',away_team='BUF',home_team='NYJ')
    pkg['events'].insert(0,missing)
    file=tmp_path/'fixture.json'
    file.write_text(json.dumps(pkg))
    folder=tmp_path/'run'
    res=run(folder,file)
    assert res.returncode==2,res.stderr
    r=receipt(folder)
    assert r['status']=='PARTIAL' and r['events'][0]['reason']=='NFL_EVENT_INPUT_MISSING'
    assert r['events'][1]['status']=='COMPLETED' and r['events'][1]['event_id']==GOOD
    assert r['card_sha256']==sha((folder/'diagnostic_card.json').read_bytes())
    assert r['html_sha256']==sha((folder/'diagnostic_card.html').read_bytes())
    card=json.loads((folder/'diagnostic_card.json').read_bytes())
    assert card['execution_mode']=='RETROSPECTIVE_DIAGNOSTIC'
    assert card['canonical_prospective_eligible'] is r['canonical_prospective_eligible'] is False
    assert card['forecast_count']==1 and card['scheduled_game_count']==2
    assert card['forecasts'][0]['refusal_reason']=='NFL_EVENT_INPUT_MISSING'
    from pipelines.cards.runner_contract import verify_shared_card
    counts=verify_shared_card(card,pkg['events'],league='nfl',card_date=DAY,as_of=CUTOFF,simulations=100)
    assert counts['BLOCKED']==counts['FORECAST_GENERATED']==1
    f=json.loads((folder/GOOD/'forecast.json').read_bytes())
    draws=np.load(folder/GOOD/'winner_draws.npy',allow_pickle=False)
    row=card['forecasts'][1]
    # The dated card must retain all native attribution fields for presentation,
    # including paired sampling/model evidence when a prior is supplied.
    assert row['missingness_audit']['details']['native'] == f['missingness_audit']
    from pipelines.cards.missingness_presentation import audit_view
    assert audit_view(row)['summary'] == audit_view(f)['summary']
    home=row['model_winner']==f['event']['home_team']
    assert row['model_p']==(f['prediction']['home_win'] if home else 1-f['prediction']['home_win'])
    assert row['sim_p']==(draws.mean() if home else 1-draws.mean())
    assert r['events'][1]['forecast_sha256']==sha((folder/GOOD/'forecast.json').read_bytes())
    (folder/GOOD/'winner_draws.npy').write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='NFL_DRAW_FILE_HASH_MISMATCH'):
        read_forecast(folder,f['event'],100,f['model_id'],None,utc(CUTOFF),f['model_artifact_sha256'])


@pytest.mark.parametrize(('pin','day','reason'), [('7'*64,DAY,'NFL_PACKAGE_HASH_MISMATCH'),
    (None,'2026-11-08','NFL_DATE_NOT_CAPTURED')])
def test_bad_explicit_inputs_block_before_model(tmp_path,pin,day,reason):
    d=tmp_path/'output'
    res=run(d,PACKAGE,pin=pin,day=day)
    assert res.returncode==2
    r=receipt(d)
    assert r['status']=='BLOCKED' and r['reason'].startswith(reason)
    assert not list(d.glob('*/forecast.json'))


def test_covered_date_with_no_event_cannot_pass(tmp_path):
    pkg=json.loads(PACKAGE.read_bytes())
    pkg['events'].clear()
    f=tmp_path/'empty.json'; f.write_text(json.dumps(pkg))
    d=tmp_path/'run'
    assert run(d,f).returncode==2
    assert receipt(d)['reason']=='NFL_EMPTY_DATED_PACKAGE'


def test_old_asof_does_not_revive_a_started_event(tmp_path):
    d=tmp_path/'run'
    assert run(d,PACKAGE,replay=False).returncode==2
    r=receipt(d)
    assert r['status']=='BLOCKED' and r['events'][0]['reason']=='POST_START'
    assert not (d/GOOD/'forecast.json').exists()


def test_bound_handoff_rejects_swapped_base_and_start(tmp_path):
    pkg=json.loads(PACKAGE.read_bytes())
    for variant, key, expected in [('teams','home_team','NFL_EVENT_INPUT_BINDING'),
                                   ('time','gametime','NFL_START_TIME_BINDING')]:
        modified=json.loads(json.dumps(pkg))
        if variant=='teams':
            modified['event_inputs'][GOOD]['base'][key]='SF'
        else:
            modified['events'][0][key]='19:45'
        file=tmp_path/(variant+'.json')
        file.write_text(json.dumps(modified))
        d=tmp_path/variant
        assert run(d,file).returncode==2
        assert receipt(d)['events']==[{'event_id':GOOD,'reason':expected,'status':'BLOCKED'}]


def test_runner_returning_no_files_cannot_create_completed_rows(tmp_path):
    from types import SimpleNamespace
    from pipelines.cards.nfl_runner_contract import run_bound
    args=SimpleNamespace(output=tmp_path/'no-files',event_package=PACKAGE,
        event_package_sha256=sha(PACKAGE.read_bytes()),date=DAY,as_of_utc=None,mode='research_pregame',
        replay_cutoff_utc=CUTOFF,simulations=100,event_id=None,weekly_state_id=None,model_id=None,home_spread=None,disclosures=None)
    assert run_bound(args, lambda *_: None)==2
    r=receipt(args.output)
    assert r['events'][0]['event_id']==GOOD and r['events'][0]['status']=='BLOCKED'
    assert 'manifest.json' in r['events'][0]['reason'] and r['status']=='BLOCKED'


def test_weekly_store_and_pin_are_independent_inputs(monkeypatch):
    from types import SimpleNamespace
    from pipelines.cards.nfl_runner_contract import validate_event
    from models.nfl.contextual.weekly_state import SCHEDULE_URL
    p=json.loads(PACKAGE.read_bytes())
    p['source_fetches']=[{'source':SCHEDULE_URL,'fetched_at_utc':CUTOFF}]
    state='a'*64
    p['event_inputs'][GOOD]['context']['weekly_state']={'store':'not-trusted','state_id':state}
    args=SimpleNamespace(weekly_state_store=None,weekly_state_id=None,replay_cutoff_utc=CUTOFF)
    with pytest.raises(ValueError, match='NFL_EXPLICIT_WEEKLY_STORE_AND_ID_REQUIRED'):
        validate_event(p['events'][0],args,p,utc(CUTOFF))
    args.weekly_state_store=Path('/explicit/store'); args.weekly_state_id='b'*64
    with pytest.raises(ValueError, match='NFL_PACKAGE_WEEKLY_STATE_MISMATCH'):
        validate_event(p['events'][0],args,p,utc(CUTOFF))
    args.weekly_state_id=state
    monkeypatch.delenv('NFL_WEEKLY_STATE_SEED_SHA256',raising=False)
    with pytest.raises(ValueError, match='INDEPENDENT_OPERATOR_SEED_PIN_REQUIRED'):
        validate_event(p['events'][0],args,p,utc(CUTOFF))
    monkeypatch.setenv('NFL_WEEKLY_STATE_SEED_SHA256','c'*64)
    p['source_fetches'][0]['fetched_at_utc']='2026-09-14T00:00:00Z'
    with pytest.raises(ValueError, match='CURRENT_SCHEDULE_REFRESH_REQUIRED'):
        validate_event(p['events'][0],args,p,utc(CUTOFF))


def test_bound_snapshot_is_the_object_consumed_by_inference(monkeypatch,tmp_path):
    from scripts import run_nfl_integrated as runner
    pkg=json.loads(PACKAGE.read_bytes())
    for name in ('model_path','recovered_parameters_path'):
        pkg[name]=str((PACKAGE.parent/pkg[name]).resolve())
    f=tmp_path/'bound.json'; f.write_text(json.dumps(pkg))
    d=tmp_path/'run'
    execute=runner._execute
    def replace_disk_copy(args, parser, snapshot):
        f.write_text('{}')
        return execute(args,parser,snapshot)
    monkeypatch.setattr(runner,'_execute',replace_disk_copy)
    monkeypatch.setenv('NFL_CONTEXT_PACKAGE',str(tmp_path/'wrong.json'))
    monkeypatch.setattr(sys,'argv',['run_nfl_integrated.py','--date',DAY,
        '--output',str(d),'--simulations','100','--event-package',str(f),
        '--event-package-sha256',sha(f.read_bytes()),'--replay-cutoff-utc',CUTOFF])
    runner.main()
    r=receipt(d)
    assert r['status']=='COMPLETED' and r['package_sha256']!=sha(f.read_bytes())


def test_single_handicap_cannot_be_applied_to_an_entire_package(tmp_path):
    from types import SimpleNamespace
    from pipelines.cards.nfl_runner_contract import load_package
    pkg=json.loads(PACKAGE.read_bytes())
    pkg['events'].append(dict(pkg['events'][0],event_id='2026_01_BUF_NYJ',away_team='BUF',home_team='NYJ'))
    file=tmp_path/'two.json'; file.write_text(json.dumps(pkg))
    args=SimpleNamespace(event_package=file,event_package_sha256=sha(file.read_bytes()),date=DAY,
                         mode='research_pregame',simulations=100,event_id=None,home_spread=[3.5],disclosures=None)
    with pytest.raises(ValueError,match='SPREAD_OVERLAY_REQUIRES_SINGLE_EVENT_SELECTION'):
        load_package(args,utc(CUTOFF),{})
