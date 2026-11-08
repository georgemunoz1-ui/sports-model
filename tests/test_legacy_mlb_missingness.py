import json
from pathlib import Path

import pytest

from pipelines.cards import derived_missingness as M
from scripts.run_mlb_legacy_tracking import run, run_coordinator, MODEL, PRODUCTS, sha, ROOT


def test_tracking_successor_keeps_frozen_pin_and_isolates_bad_fixture(tmp_path):
    slate=tmp_path/'slate.psv'
    line=(ROOT/'data/mlb/slates/2026-08-27_slate.psv').read_text().splitlines()[1]
    slate.write_text(line+'\nmalformed\n')
    result=run('2026-08-27',slate,tmp_path/'card')
    assert result['status']=='PARTIAL' and result['allocated_units']==0
    assert sha(ROOT/'harness/daily_card.py')==result['native_source_sha256']=='f57980f107287592aca3c9f1245fa04ada84201e474422a61943869adbf4a8ca'
    row,=result['rows']
    assert row['qualification']=='NO_PICK' and row['missingness_audit']['details']['input_observations']['home']['starter_unavailable_uses_registered_cap']
    assert result['coverage'][1]['reason']=='INVALID_SLATE_ROW'
    row['v13']['home_wp']+=.05
    with pytest.raises(ValueError,match='MISSINGNESS_CHILD_READBACK_FAILED'):
        M.check(row,'mlb',row['gamePk'],MODEL,PRODUCTS)


@pytest.mark.parametrize('source', ['empty','duplicate','absent'])
def test_no_failed_slate_becomes_a_verified_empty_day(tmp_path,source):
    path=tmp_path/'slate'
    line='880|SEA|OAK|18:30Z|TBD|TBD'
    if source!='absent':
        path.write_text('' if source=='empty' else line+'\n'+line)
    report=run('2026-09-01',path,tmp_path/'tracked')
    assert report['status']=='BLOCKED' and not report['rows'] and report['reason']
    if source=='duplicate':
        assert all(x['reason']=='DUPLICATE_EVENT_ID' for x in report['coverage'])


def test_coordinator_retains_sibling_and_checks_dose_without_action(tmp_path):
    event={'event':'STL@LAD','away':'STL','home':'LAD','away_starter':'Michael McGreevy',
           'home_starter':'Eric Lauer','market':{'home_ml':300,'away_ml':-340}}
    invalid={'event':'SEA@MISSING_TEAM','home':'MISSING_TEAM','away':'SEA'}
    packet=tmp_path/'relay.json'
    packet.write_text(json.dumps({'date_et':'2026-09-01','relay_events':[event,invalid]}))
    r=run_coordinator('2026-09-01',packet,tmp_path/'c',simulations=100)
    assert r['status']=='PARTIAL' and [x['status'] for x in r['rows']]==['DIAGNOSTIC','BLOCKED']
    good,bad=r['rows']
    assert good['missingness_audit']['details']['input_observations']['information_dose']==good['snapshot']['resolved_information_dose']
    assert good['qualification']=='NO_PICK' and not good['action_authority']
    assert bad['reason'] and bad['missingness_audit']['details']['unresolved_inputs']==[bad['reason']]
