"""Offline synthetic provider fixtures; no sports result or validity claims."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import canonical_results as R


def forecast(league='NBA'):
    return {'league': league, 'event_id': league + ':123', 'home_team': 'Home Team',
            'away_team': 'Away Team', 'start_time_utc': '2026-01-01T02:00:00Z'}


def espn(f=None):
    f = f or forecast()
    teams = [{'homeAway': side, 'team': {'id': str(i), 'displayName': f[side + '_team'],
              'abbreviation': f[side + '_team']}, 'score': points}
             for i, (side, points) in enumerate([('home', '101'), ('away', '99')])]
    return {'events': [{'id': '123', 'date': f['start_time_utc'], 'season': {'year': 2026},
            'week': {'number': 1}, 'competitions': [{'competitors': teams,
            'status': {'period': 4, 'type': {'completed': True, 'state': 'post',
            'name': 'STATUS_FINAL', 'detail': 'Final'}}}]}]}


def receipt(f):
    return {'source_url': R.source_url(f), 'source_sha256': 'a' * 64,
            'raw_path': '/unused-fixture', 'fetched_at_utc': '2026-01-02T00:00:00Z'}


def test_final_and_market_free():
    f = forecast(); payload = espn(f); payload['events'][0]['odds'] = {'value': 'ignore'}
    r = R.parse_espn(payload, f, receipt(f))
    assert r['status'] == 'FINAL' and r['home_score'] == 101
    assert 'odds' not in json.dumps(r) and not r['action_authority']


@pytest.mark.parametrize('field,value', [('completed', False), ('state', 'in'), ('name', 'STATUS_CANCELED')])
def test_no_inferred_final(field, value):
    f = forecast(); p = espn(f)
    p['events'][0]['competitions'][0]['status']['type'][field] = value
    assert R.parse_espn(p, f, receipt(f))['status'] == 'PENDING'


def test_team_mismatch_and_ambiguity():
    f = forecast(); p = espn(f)
    p['events'][0]['competitions'][0]['competitors'][0]['team']['displayName'] = 'Other'
    with pytest.raises(ValueError, match='RESULT_TEAM_MISMATCH'): R.parse_espn(p, f, receipt(f))
    p = espn(f); p['events'] *= 2
    with pytest.raises(ValueError, match='AMBIGUOUS_EVENT_MATCH'): R.parse_espn(p, f, receipt(f))


@pytest.mark.parametrize('value', [None, True, '-1', 'nan', '3.5'])
def test_invalid_final_scores(value):
    f = forecast(); p = espn(f)
    p['events'][0]['competitions'][0]['competitors'][0]['score'] = value
    with pytest.raises((ValueError, TypeError)): R.parse_espn(p, f, receipt(f))


def test_nfl_id_week_mapping_and_tie():
    f = forecast('NFL'); f.update(event_id='2026_01_LA_WAS', home_team='WAS', away_team='LA')
    p = espn(f); sides = p['events'][0]['competitions'][0]['competitors']
    sides[0]['team']['abbreviation'] = 'WSH'; sides[1]['team']['abbreviation'] = 'LAR'
    sides[0]['score'] = sides[1]['score'] = '17'
    r = R.parse_espn(p, f, receipt(f))
    assert r['status'] == 'FINAL' and not r['binary_grade_eligible'] and r['reason'] == 'TIE_EXCLUDED'
    p['events'][0]['week']['number'] = 2
    with pytest.raises(ValueError, match='NFL_PROVIDER_WEEK_BINDING'): R.parse_espn(p, f, receipt(f))


def test_nhl_shootout_and_tied_rejection():
    f = forecast('NHL'); p = espn(f)
    status = p['events'][0]['competitions'][0]['status']; status['period'] = 5
    status['type'].update(name='STATUS_FINAL_SO', shortDetail='Final/SO')
    r = R.parse_espn(p, f, receipt(f))
    assert r['shootout'] and r['overtime'] and 'INCLUDING_OT_AND_SO' in r['settlement']
    p['events'][0]['competitions'][0]['competitors'][0]['score'] = '99'
    with pytest.raises(ValueError, match='BINARY_LEAGUE_TIED_FINAL'): R.parse_espn(p, f, receipt(f))


def test_changed_start_is_not_silent_join():
    f = forecast(); p = espn(f); p['events'][0]['date'] = '2026-01-02T02:00:00Z'
    assert R.parse_espn(p, f, receipt(f))['reason'] == 'START_TIME_CHANGED_REQUIRES_RECONCILIATION'


def test_wnba_official_and_aliases():
    f = forecast('WNBA'); f.update(event_id='WNBA:1022600123', home_team='LAS', away_team='PHX')
    p = {'game': {'gameId': '1022600123', 'gameTimeUTC': f['start_time_utc'], 'gameStatus': 3,
                 'period': 5, 'homeTeam': {'teamTricode': 'LA', 'score': 88},
                 'awayTeam': {'teamTricode': 'PHO', 'score': 83}}}
    r = R.parse_wnba(p, f, receipt(f)); assert r['status'] == 'FINAL' and r['overtime']
    p['game']['gameId'] = '999'
    with pytest.raises(ValueError, match='RESULT_EVENT_MISMATCH'): R.parse_wnba(p, f, receipt(f))


def test_capture_verify_and_tamper(tmp_path):
    f = forecast(); body = json.dumps(espn(f)).encode()
    rows = R.acquire_results([f, f], tmp_path / 'capture', lambda url: body)
    assert len(rows) == 1 and R.verify_result_source(rows[0])
    changed = copy.deepcopy(rows[0]); changed['home_score'] += 1
    with pytest.raises(ValueError, match='NORMALIZED_RESULT_MISMATCH'): R.verify_result_source(changed)
    Path(rows[0]['raw_path']).write_bytes(b'{}')
    with pytest.raises(ValueError, match='RESULT_RAW_HASH_MISMATCH'): R.verify_result_source(rows[0])


def test_independent_provider_failure(tmp_path):
    a = forecast(); b = forecast('NHL')
    def fetch(url):
        if '/nhl/' in url: raise OSError('source unavailable')
        return json.dumps(espn(a)).encode()
    rows = R.acquire_results([a, b], tmp_path / 'capture', fetch)
    assert [r['status'] for r in rows] == ['FINAL', 'BLOCKED']
    assert json.loads((tmp_path / 'capture/report.json').read_text())['status'] == 'PARTIAL'


def test_date_range_crosses_utc_calendar():
    assert 'dates=20251231-20260102' in R.source_url(forecast())


def test_cfb_requires_id_and_names():
    f = forecast('CFB'); p = espn(f)
    assert R.parse_espn(p, f, receipt(f))['status'] == 'FINAL'
    p['events'][0]['id'] = '456'
    assert R.parse_espn(p, f, receipt(f))['status'] == 'PENDING'


def test_future_capture_rejected():
    f = forecast(); r = receipt(f); r['fetched_at_utc'] = '2099-01-01T00:00:00Z'
    with pytest.raises(ValueError, match='FUTURE_RESULT_CAPTURE'): R.parse_espn(espn(f), f, r)


def test_error_payload_is_not_empty_schedule():
    f = forecast()
    with pytest.raises(ValueError, match='PROVIDER_SCOREBOARD_SCHEMA'):
        R.parse_espn({'error': 'unavailable'}, f, receipt(f))
