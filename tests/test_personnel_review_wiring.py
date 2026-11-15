import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from pipelines.cards import personnel_review as R

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = '2026-11-15T12:00:00Z'
START = '2026-11-15T18:00:00Z'


def fixture(league):
    return {'league': league, 'event_id': league + ':1', 'away_team':'Away', 'home_team':'Home',
            'away_team_id':'1','home_team_id':'2','start_time_utc':START}


def test_all_eight_board_rows_and_missing_cutoffs(monkeypatch):
    leagues = ('NFL','CFB','NBA','WNBA','MLB','NHL','MLS','CBB')
    board = {'rows':[fixture(league) for league in leagues]}
    for row in board['rows'][:-2]:
        row['markets'] = {'moneyline':[{'cutoff':CUTOFF}], 'spread':[{'cutoff':'2026-11-15T04:00:00-08:00'}]}
    board['rows'][-2]['markets'] = {'moneyline':[{'cutoff':CUTOFF}], 'total':[{'cutoff':'2026-11-14T12:00:00Z'}]}
    original = copy.deepcopy(board)
    calls = []
    def review(league, event, cutoff, *, forecast, observations):
        calls.append((league,event,cutoff,forecast))
        return {'status':'UNVERIFIED'}
    monkeypatch.setattr(R,'review_fixture',review)
    report = R.build_review(board)
    assert len(report['events']) == len(calls) == 8
    assert all(call[2] == '2026-11-15T12:00:00+00:00' for call in calls[:-2])
    assert calls[-1][2] is calls[-2][2] is None
    assert all(call[3] is row for call, row in zip(calls[:-1], board['rows'][:-1]))
    assert calls[-1][3] is None
    assert board == original


def test_postgame_preserves_caveat_and_checks_exact_parent(tmp_path):
    row = fixture('CBB')
    card = {'league':'CBB','schema':'sports.cbb.shadow_card.v2','as_of_utc':CUTOFF,'forecasts':[row]}
    card_file = tmp_path/'card.json'
    card_file.write_text(json.dumps(card))
    card_sha = hashlib.sha256(card_file.read_bytes()).hexdigest()
    prior = tmp_path/'review.json'
    def cli(*args):
        return subprocess.run([sys.executable, str(ROOT/'scripts/review_personnel_events.py'), '--card', str(card_file), *map(str,args)],
                              capture_output=True,text=True)
    assert cli('--output',prior).returncode == 0
    data = json.loads(prior.read_bytes())
    assert data['parent_file_sha256'] == card_sha
    assert data['events'][0]['event_id'] == row['event_id']
    grade = {'schema':'sports.cbb.grades.shadow.v2','frozen_parent_sha256':card_sha,
             'rows':[{'event_id':row['event_id'],'status':'FINAL','products':[{'result':'loss'}]}]}
    grades = tmp_path/'grade.json'
    grades.write_text(json.dumps(grade))
    grade_bytes = grades.read_bytes()
    prior_sha = hashlib.sha256(prior.read_bytes()).hexdigest()
    result_file = tmp_path/'post.json'
    assert cli('--grades',grades,'--pregame-review',prior,'--pregame-review-sha256',prior_sha,'--output',result_file).returncode == 0
    got=json.loads(result_file.read_bytes())
    assert got['events'][0]==dict(data['events'][0],grade_status='FINAL')
    assert got['pregame_review_file_sha256']==prior_sha
    assert got['prior_review_digest_status']=='MATCHES_SUPPLIED_PIN'
    assert grades.read_bytes()==grade_bytes and hashlib.sha256(card_file.read_bytes()).hexdigest()==card_sha
    prior.write_text(prior.read_text()+' ')
    assert 'PERSONNEL_REVIEW_DIGEST_MISMATCH' in cli('--grades',grades,'--pregame-review',prior,'--pregame-review-sha256',prior_sha,'--output',tmp_path/'bad.json').stderr
    grades.write_text(json.dumps(dict(grade,frozen_parent_sha256='0'*64)))
    assert 'PERSONNEL_GRADES_PARENT_MISMATCH' in cli('--grades',grades,'--output',tmp_path/'bad.json').stderr
    assert not (tmp_path/'bad.json').exists()


def test_grade_requires_unique_exact_fixture_and_separates_ungraded():
    report={'events':[{'league':'CBB','event_id':'CBB:1'},{'league':'CBB','event_id':'CBB:2'}]}
    grade={'schema':'sports.cbb.grades.shadow.v2','frozen_parent_sha256':'h','rows':[{'event_id':'CBB:1','status':'FINAL'}]}
    got=R.bind_grades(copy.deepcopy(report),grade,'h')
    assert [x['grade_status'] for x in got['events']]==['FINAL','NO_MATCHING_GRADE']
    for updates in ([{'event_id':'OTHER:1','status':'FINAL'}], grade['rows']*2):
        with pytest.raises(ValueError,match='FIXTURE_MISMATCH'):
            R.bind_grades(copy.deepcopy(report),dict(grade,rows=updates),'h')


def test_postgame_reads_normal_rendered_disclosure_and_blocked_row(tmp_path):
    from pipelines.cards.disclosures import write_report
    parent = {'league':'CFB','as_of_utc':CUTOFF,'forecasts':[
        dict(fixture('CFB'), model_id='parent.v1', input_snapshot_hash='a' * 64,
             forecast_status='POST_START')]}
    card = tmp_path/'card.json'
    card.write_text(json.dumps(parent))
    disclosures = tmp_path/'disclosures'
    result = write_report(parent, disclosures, parent_path=card)
    event = result['events'][0]['personnel_review']
    assert event['status'] == 'NO_FROZEN_FORECAST'
    assert event['personnel_disposition'] == 'HOLD'
    raw_sha = hashlib.sha256(card.read_bytes()).hexdigest()
    loaded, prior_sha = R.load_pregame_review(disclosures/'disclosures.json', parent, raw_sha)
    assert loaded['events'] == [event] and len(prior_sha) == 64
    assert loaded['prior_review_digest_status'] == 'NO_INDEPENDENT_PIN_SUPPLIED'
    with pytest.raises(ValueError, match='PARENT_MISMATCH'):
        R.load_pregame_review(disclosures/'disclosures.json', parent, 'a'*64)


def test_invalid_manifest_holds_and_rejected_prior_preserves_grade(tmp_path):
    from pipelines.cards.disclosures import write_report
    event = dict(fixture('CFB'), model_id='parent.v1', input_snapshot_hash='a' * 64,
                 forecast_status='FORECAST_GENERATED')
    card = {'league':'CFB','as_of_utc':CUTOFF,'forecasts':[event]}
    manifest = tmp_path/'invalid.json'
    manifest.write_text('{}')
    out = write_report(card, tmp_path/'disclosures', personnel_events=manifest)
    assert out['errors'] == [{'source':'personnel_events','reason':'PERSONNEL_INPUT_SCHEMA'}]
    assert out['execution_status'] == 'PARTIAL'
    assert out['events'][0]['personnel_review']['personnel_disposition'] == 'HOLD'
    board_file = tmp_path/'board.json'
    board_file.write_text(json.dumps({'rows':[dict(event, simulations=20)]}))
    grades_file = tmp_path/'grade.json'
    command = [sys.executable, str(ROOT/'scripts/grade_research_board.py'), '--board',str(board_file),
               '--raw-dir',str(tmp_path),'--pregame-personnel-review',str(manifest),
               '--pregame-personnel-review-sha256','f' * 64,'--output',str(grades_file)]
    assert subprocess.run(command, capture_output=True).returncode == 2
    grade = json.loads(grades_file.read_bytes())
    assert grade['personnel_review_status'] == 'REJECTED_PERSONNEL_REVIEW'
    assert grade['personnel_review_reason'] == 'PERSONNEL_REVIEW_DIGEST_MISMATCH'
    assert grade['grades'][0]['reason'] == 'RESULT_SOURCE_REQUIRED'


def test_nfl_raw_bridge_requires_exact_view_and_role_matches_still_hold(tmp_path, monkeypatch):
    from pipelines.cards.disclosures import write_report
    from pipelines.cards.distribution_research import nfl_card
    bundle = {'schema':'nfl.integrated_context_forecast.v1','mode':'research_pregame','event':fixture('NFL'),
              'cutoff_utc':CUTOFF,'model_id':'test','model_artifact_sha256':'a' * 64,'features':{}}
    card = nfl_card(bundle,CUTOFF)
    stored = tmp_path/'raw.json'
    stored.write_text(json.dumps(bundle))
    monkeypatch.setattr(R,'review_fixture',lambda *a, **kw:{'status':'REPORTED_ASSIGNMENT_MATCH','review_required':False})
    emitted = write_report(card, tmp_path/'ok', parent_path=stored)
    assert emitted['events'][0]['personnel_review']['personnel_disposition'] == 'HOLD'
    changed = copy.deepcopy(card)
    changed['forecasts'][0]['model_input_snapshot'] = {'other':'identity'}
    with pytest.raises(ValueError, match='DISCLOSURE_PARENT_FILE_MISMATCH'):
        write_report(changed, tmp_path/'bad', parent_path=stored)


def test_native_mlb_reviewed_board_keeps_blocked_rows_and_resolves_sides():
    away = {'team':'New York Mets','starter':{'id':123,'fullName':'A B'}}
    home = {'team':'Washington Nationals','starter':{'id':456,'fullName':'C D'}}
    row = {'event_id':'MLB:1','start_time_utc':START,'cutoff_utc':CUTOFF,
           'teams':{'away':away,'home':home}, 'forecast':{'model_input_snapshot':{'package_sha256':'test'}}}
    blocked = {k:v for k,v in row.items() if k not in ('forecast','cutoff_utc')}
    board = {'schema':'mlb.reviewed_research_board.v1', 'cutoff_utc':CUTOFF, 'package_sha256':'test',
             'events':[row, dict(blocked, event_id='MLB:2')]}
    first, second = list(R._fixtures(board))
    assert first[0]=='MLB' and first[1]['away_team']=='NYM' and first[1]['home_team']=='WSH'
    assert first[1]['home_pitcher_id']==456 and first[1]['away_starter']=='A B'
    assert first[2]==CUTOFF and first[3] is row['forecast'] and second[2:] == (None,None)
    result=R.build_review(board)
    assert [r['forecast_available'] for r in result['events']] == [True,False]
    row['forecast']['model_input_snapshot']['package_sha256']='different'
    rejected = R.build_review(board)['events'][0]
    assert rejected['roles']==[] and rejected['forecast_available'] and rejected['personnel_disposition']=='HOLD'
    assert any('different packages' in msg for msg in rejected['caveats'])
