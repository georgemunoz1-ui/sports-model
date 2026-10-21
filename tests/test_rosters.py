"""Personnel evidence and failure boundaries; synthetic examples are not forecasts."""
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.prepare_rosters import capture_or_resume, write_once
from sports.rosters import (ROUTES, SCHEMA, assess, attach, digest, load_bundle,
                            membership_delta, normalize_team, seal, validate_rotation)

CUTOFF = "2026-10-20T22:30:00Z"
EVENT = {"event_id": "test:1", "home_team": "Home", "away_team": "Away", "start_time_utc": "2026-10-21T02:00:00Z"}


def source(root, obj, url):
    raw = json.dumps(obj).encode()
    sha = hashlib.sha256(raw).hexdigest()
    write_once(root / 'raw' / (sha + '.json'), raw)
    return {"url": url, "final_url": url, "raw_path": 'raw/' + sha + '.json', "raw_sha256": sha,
            "status": "CAPTURED", "http_status": 200, "retrieved_at_utc": "2026-10-20T22:00:00Z"}


def make_bundle(root, sport='nba', grouped=False, duplicate_player=False):
    root.mkdir(exist_ok=True)
    teams = [{"id": str(i), "displayName": name, "location": name} for i, name in [(1, 'Home'), (2, 'Away')]]
    directory = {"sports": [{"leagues": [{"teams": [{"team": t} for t in teams]}]}]}
    base = f'https://site.api.espn.com/apis/site/v2/sports/{ROUTES[sport]}'
    census = source(root, directory, base + '/teams?limit=1000')
    league = {'census_status': 'CAPTURED', 'census_source': census, 'scope': 'ALL_PROVIDER_TEAMS',
              'requested_team_ids': ['1', '2'], 'teams': [], 'membership_conflicts': {}}
    for t in teams:
        players = [{"id": f'{t["id"]}{n}', "displayName": f'Player {n}', "position": {"abbreviation": 'G'},
                    "status": {"name": 'Active'}, "injuries": []} for n in range(5)]
        if duplicate_player and t['id'] == '2':
            players[0]['id'] = '10'
        data = {'team': t, 'timestamp': '2026-10-20T21:59:00Z', 'season': {'year': 2026},
                'athletes': [{'position': 'group', 'items': players}] if grouped else players}
        receipt = source(root, data, base + '/teams/' + t['id'] + '/roster?limit=1000')
        s = normalize_team(sport, t, data, receipt)
        league['teams'].append({'provider_team_id': t['id'], 'status': 'PARSED', 'snapshot': s})
    if duplicate_player:
        league['membership_conflicts'] = {f'espn:{sport}:10': [f'espn:{sport}:1', f'espn:{sport}:2']}
    bundle = seal({'schema': SCHEMA, 'sports': {sport: league}, 'action_authority': False})
    (root / 'bundle.json').write_text(json.dumps(bundle))
    return bundle


@pytest.mark.parametrize('sport', list(ROUTES))
@pytest.mark.parametrize('grouped', [False, True])
def test_source_rebuild_all_sports(tmp_path, sport, grouped):
    make_bundle(tmp_path, sport, grouped)
    bundle = load_bundle(tmp_path / 'bundle.json')
    report = assess(sport, EVENT, CUTOFF, bundle)
    assert report['status'] == 'AVAILABLE_NOT_USED'
    assert not report['roster_inputs_numerically_used']
    assert not report['roster_aware_forecast_eligible']
    assert report['teams']['home']['player_count'] == 5


def test_resealed_fabricated_normalization_is_rejected(tmp_path):
    b = make_bundle(tmp_path)
    b['sports']['nba']['teams'][0]['snapshot']['players'][0]['event_availability'] = 'CONFIRMED'
    (tmp_path / 'bundle.json').write_text(json.dumps(seal(b)))
    with pytest.raises(ValueError, match='NORMALIZATION_MISMATCH'):
        load_bundle(tmp_path / 'bundle.json')


def test_default_capped_endpoint_is_rejected(tmp_path):
    b = make_bundle(tmp_path, 'cfb', True)
    row = b['sports']['cfb']['teams'][0]['snapshot']
    row['source']['url'] = row['source']['url'].split('?')[0]
    (tmp_path / 'bundle.json').write_text(json.dumps(seal(b)))
    with pytest.raises(ValueError, match='SOURCE_IDENTITY_MISMATCH'):
        load_bundle(tmp_path / 'bundle.json')


def test_at_explicit_response_limit_requires_pagination(tmp_path):
    b = make_bundle(tmp_path)
    s = b['sports']['nba']['teams'][0]['snapshot']
    receipt = s['source']
    data = json.loads((tmp_path / receipt['raw_path']).read_bytes())
    data['athletes'] = [{'id': str(i), 'displayName': 'Player'} for i in range(1000)]
    with pytest.raises(ValueError, match='AT_LIMIT'):
        normalize_team('nba', data['team'], data, receipt)


def test_raw_tampering_rejected(tmp_path):
    b = make_bundle(tmp_path)
    p = tmp_path / b['sports']['nba']['teams'][0]['snapshot']['source']['raw_path']
    p.write_bytes(b'{}')
    with pytest.raises(ValueError, match='HASH_MISMATCH'):
        load_bundle(tmp_path / 'bundle.json')


def test_census_cannot_silently_drop_team(tmp_path):
    b = make_bundle(tmp_path)
    b['sports']['nba']['teams'].pop()
    b['sports']['nba']['requested_team_ids'].pop()
    (tmp_path / 'bundle.json').write_text(json.dumps(seal(b)))
    with pytest.raises(ValueError, match='CENSUS_TRUNCATED'):
        load_bundle(tmp_path / 'bundle.json')


@pytest.mark.parametrize('cutoff,reason', [('2026-10-20T21:00:00Z', 'STALE_OR_FUTURE'),
                                          ('2026-10-21T05:00:00Z', 'POST_START')])
def test_chronology_rejected(tmp_path, cutoff, reason):
    b = make_bundle(tmp_path)
    assert reason in str(assess('nba', EVENT, cutoff, b)['reasons'])


def test_stale_even_if_bundle_rebuilt_now(tmp_path):
    b = make_bundle(tmp_path)
    event = dict(EVENT, start_time_utc='2026-10-22T00:00:00Z')
    b['created_at_utc'] = '2026-10-21T07:00:00Z'
    assert 'STALE_OR_FUTURE' in str(assess('nba', event, b['created_at_utc'], b)['reasons'])


def test_wrong_season_and_explicit_id_name_mismatch(tmp_path):
    b = make_bundle(tmp_path)
    assert 'SEASON_MISMATCH' in str(assess('nba', dict(EVENT, season=2025), CUTOFF, b)['reasons'])
    assert 'ID_NAME_MISMATCH' in str(assess('nba', dict(EVENT, home_roster_team_id='espn:nba:2'), CUTOFF, b)['reasons'])


def test_two_team_membership_fails_closed(tmp_path):
    make_bundle(tmp_path, duplicate_player=True)
    b = load_bundle(tmp_path / 'bundle.json')
    assert 'MULTIPLE_TEAM_MEMBERSHIP' in str(assess('nba', EVENT, CUTOFF, b)['reasons'])


def test_roster_active_does_not_imply_playing(tmp_path):
    b = make_bundle(tmp_path)
    player = b['sports']['nba']['teams'][0]['snapshot']['players'][0]
    assert player['roster_status'] == 'Active'
    assert player['event_availability'] == 'UNCONFIRMED'
    assert player['expected_exposure'] is None


def test_full_roster_claim_blocked_but_parent_probability_unchanged(tmp_path):
    b = make_bundle(tmp_path)
    raw = {'model_id': 'frozen', 'model_p': .52, 'model_state_config_hash': 'abc', 'input_snapshot_hash': 'xyz'}
    out = attach(raw, 'nba', EVENT, CUTOFF, b)
    assert out['model_p'] == raw['model_p']
    assert out['roster_coverage']['forecast_binding']['input_snapshot_hash'] == 'xyz'
    assert 'roster_coverage' not in raw
    with pytest.raises(ValueError, match='AWARE_FORECAST_UNAVAILABLE'):
        attach(raw, 'nba', EVENT, CUTOFF, b, True)


def test_missing_bundle_explicit_for_every_sport():
    for sport in ROUTES:
        r = assess(sport, EVENT, CUTOFF)
        assert r['status'] == 'ACQUIRE_REQUIRED'
        assert r['unmet_model_requirements']


def rotation(tmp_path, sport='nba'):
    b = make_bundle(tmp_path, sport)
    s = b['sports'][sport]['teams'][0]['snapshot']
    allocation = [{'player_id': p['player_id'], 'exposure': 48 if sport == 'nba' else 40,
                   'scenario_status': 'ASSUMED_AVAILABLE'} for p in s['players']]
    return s, allocation


@pytest.mark.parametrize('sport,total', [('nba',240), ('wnba',200)])
def test_basketball_minutes_conserved(tmp_path, sport, total):
    s, a = rotation(tmp_path, sport)
    r = validate_rotation(s, a, sport=sport, unit='minutes', total=total)
    assert r['scenario_probability'] is None and r['numerically_used'] is False
    a[0]['exposure'] -= 1
    with pytest.raises(ValueError, match='NOT_CONSERVED'):
        validate_rotation(s, a, sport=sport, unit='minutes', total=total)


@pytest.mark.parametrize('change,reason', [('duplicate','MEMBERSHIP'), ('nan','INVALID'), ('out','UNAVAILABLE'),
                                        ('confirmed','NOT_IMPLEMENTED'), ('too_many','EXCEEDS_GAME')])
def test_bad_rotation_rejected(tmp_path, change, reason):
    s, a = rotation(tmp_path)
    if change == 'duplicate':a[0]['player_id'] = a[1]['player_id']
    if change == 'nan':a[0]['exposure'] = float('nan')
    if change == 'out':s['players'][0]['reported_injuries'] = [{'status': 'Out'}]
    if change == 'confirmed':a[0]['scenario_status'] = 'CONFIRMED_AVAILABLE'
    if change == 'too_many':a[0]['exposure'] = 49
    with pytest.raises(ValueError, match=reason):
        validate_rotation(s, a, sport='nba', unit='minutes', total=240)


@pytest.mark.parametrize('sport,unit,group', [('nfl','snaps','offense'),('cfb','snaps','defense'),
                                           ('nhl','minutes','goalies'),('mlb','outs',None),('mls','minutes',None)])
def test_other_sport_units(tmp_path, sport, unit, group):
    s, a = rotation(tmp_path, sport)
    validate_rotation(s, a, sport=sport, unit=unit, total=200, group=group)
    with pytest.raises(ValueError, match='UNIT_OR_SPORT'):
        validate_rotation(s, a, sport=sport, unit='wrong', total=200, group=group)


def test_snapshot_difference_requires_chronology(tmp_path):
    b = make_bundle(tmp_path)
    s = b['sports']['nba']['teams'][0]['snapshot']
    newer = copy.deepcopy(s)
    newer['source']['retrieved_at_utc'] = CUTOFF
    newer['players'].pop()
    assert len(membership_delta(s, newer)['removed']) == 1
    with pytest.raises(ValueError, match='CHRONOLOGY'):
        membership_delta(newer, s)


def test_resume_preserves_bytes_and_timestamp(tmp_path):
    b = make_bundle(tmp_path)
    r = b['sports']['nba']['teams'][0]['snapshot']['source']
    write_once(tmp_path / 'receipts/nba/team-1.json', r)
    with patch('scripts.prepare_rosters.capture', side_effect=AssertionError('must not recapture')):
        assert capture_or_resume(tmp_path, 'nba', 'team-1', r['url']) == r
    with pytest.raises(ValueError, match='IMMUTABLE_CONFLICT'):
        write_once(tmp_path / r['raw_path'], b'partial')
    assert not list(tmp_path.rglob('.pending-*'))


def test_failed_team_stays_in_coverage_ledger(tmp_path):
    b = make_bundle(tmp_path)
    b['sports']['nba']['teams'][1] = {'provider_team_id':'2','status':'FAILED','reason':'source offline'}
    (tmp_path/'bundle.json').write_text(json.dumps(seal(b)))
    loaded = load_bundle(tmp_path/'bundle.json')
    r = assess('nba', EVENT, CUTOFF, loaded)
    assert r['status'] == 'BLOCKED' and 'home' in r['teams'] and 'away' not in r['teams']


def test_cfb_scope_rebuild_rejects_removed_team(tmp_path):
    import pandas as pd
    b = make_bundle(tmp_path, 'cfb')
    path = tmp_path/'scope.parquet'
    pd.DataFrame([{'season':2026,'home_id':1,'home_team':'Home','home_division':'fbs',
                   'away_id':2,'away_team':'Away','away_division':'fbs'}]).to_parquet(path)
    l = b['sports']['cfb']
    l.update(scope='FBS_SCHEDULE_ID_AND_NAME_MATCH', scope_evidence={'path':'scope.parquet',
             'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'season':2026})
    (tmp_path/'bundle.json').write_text(json.dumps(seal(b)))
    assert load_bundle(tmp_path/'bundle.json')
    l['requested_team_ids'].pop(); l['teams'].pop()
    (tmp_path/'bundle.json').write_text(json.dumps(seal(b)))
    with pytest.raises(ValueError, match='FBS_SCOPE_INCOMPLETE'):
        load_bundle(tmp_path/'bundle.json')


def test_saved_card_audit_does_not_rewrite_forecast(tmp_path):
    from scripts.audit_roster_cards import audit
    make_bundle(tmp_path)
    path = tmp_path/'card.json'
    card = {'league':'NBA','as_of_utc':'2026-10-20T20:00:00Z',
            'forecasts':[dict(EVENT, model_id='old-parent', model_p=.55)]}
    before = json.dumps(card).encode(); path.write_bytes(before)
    r = audit(tmp_path/'bundle.json', [path], CUTOFF)
    assert path.read_bytes() == before
    assert r['new_forecasts_generated'] == 0
    e = r['events'][0]
    assert e['original_cutoff_assessment']['status'] == 'BLOCKED'
    assert e['current_assessment']['status'] == 'AVAILABLE_NOT_USED'
    with pytest.raises(ValueError, match='DUPLICATE_CARD'):
        audit(tmp_path/'bundle.json', [path,path], CUTOFF)


def test_nfl_cli_preserves_selected_arm_and_adds_roster_report(tmp_path):
    import scripts.run_nfl_integrated as cli
    from datetime import datetime, timezone
    from types import SimpleNamespace
    make_bundle(tmp_path, 'nfl')
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):return datetime.fromisoformat(CUTOFF.replace('Z','+00:00'))
    context = {'package':{'event_inputs':{EVENT['event_id']:{'base':{},'context':{}}}},
               'model':{'design':{}},'recovered':{}}
    result = {'model_id':'nfl.integrated_context.qb.v1.research','features':{'qb_difference':1.0},
              'model_artifact_sha256':'frozen','identity':'original','selected_arm':'qb',
              'capability_report':{'rows':[{'feature':'qb_difference','active_in_run':True}]},
              'prediction':{'home_win':.6},'winner_simulation':{},'score_simulation':{}}
    result.update(schema='nfl.integrated_context_forecast.v1', mode='research_pregame',
                  event=EVENT, cutoff_utc=CUTOFF)
    def persist_fixture(folder, saved, *args):
        folder.mkdir(parents=True)
        (folder/'registration.jsonl').write_text(json.dumps({'created_at_utc': CUTOFF}))
        (folder/'forecast.json').write_text(json.dumps(saved))
    args = ['run_nfl_integrated.py','--date','2026-10-20','--model-id',result['model_id'],
            '--output',str(tmp_path/'out'),'--roster-bundle',str(tmp_path/'bundle.json')]
    with patch.object(cli, 'dt', SimpleNamespace(datetime=Clock,timezone=timezone)), \
         patch.object(cli.nfl,'load_schedule',return_value=[EVENT]), \
         patch.object(cli.nfl,'build_context',return_value=context), \
         patch.object(cli,'run',return_value=(result,None,None)) as runner, \
         patch.object(cli,'persist_run',side_effect=persist_fixture) as persist, patch('sys.argv',args):
        cli.main()
        saved = persist.call_args.args[1]
        assert saved['selected_arm'] == 'qb' and saved['identity'] == 'original'
        assert saved['roster_coverage']['existing_parent_personnel_evidence'] == result['capability_report']
        assert saved['roster_coverage']['forecast_binding']['input_snapshot_hash'] == digest(result['features'])
        from pipelines.cards.distribution_research import nfl_card
        report = json.loads((tmp_path/'out'/EVENT['event_id']/'disclosures/disclosures.json').read_text())
        assert report['parent_card_sha256'] == digest(nfl_card(saved, CUTOFF))
        assert report['events'][0]['decision'] == 'PASS'
        assert not report['events'][0]['action_authority']
        runner.reset_mock()
        with patch('sys.argv',args+['--require-roster-aware']):
            with pytest.raises(ValueError,match='ROSTER_AWARE_FORECAST_UNAVAILABLE'):cli.main()
        runner.assert_not_called()


def test_shared_card_preserves_report_and_required_gate_precedes_simulation(tmp_path):
    import scripts.generate_card_force as card
    from types import SimpleNamespace
    b = make_bundle(tmp_path)
    raw = {'model_id':'test','model_p':.55,'sim_p':.55,'dose':0,'forecast_tier':'REDUCED','model_winner':'Home'}
    seen = []
    adapter = SimpleNamespace(load_schedule=lambda *a:[EVENT], build_context=lambda *a:{},
                              forecast_event=lambda *a:seen.append(True) or raw)
    with patch.object(card, 'load_adapter', return_value=adapter), patch.object(card, 'now_utc', return_value=card.dt(CUTOFF)), \
         patch('pipelines.cards.selected.apply_default', side_effect=lambda league,event,raw:raw):
        result = card.generate('2026-10-20','nba',CUTOFF,10,None,tmp_path/'bundle.json')
        assert result['forecasts'][0]['roster_coverage']['status'] == 'AVAILABLE_NOT_USED'
        seen.clear()
        blocked = card.generate('2026-10-20','nba',CUTOFF,10,None,tmp_path/'bundle.json',True)
        assert seen == []
        assert 'ROSTER_AWARE_FORECAST_UNAVAILABLE' in blocked['incidents'][0]['detail']
