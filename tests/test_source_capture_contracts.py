"""Synthetic counterexamples for source binding; none are sports evidence."""
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import pytest
from research.source_capture_contracts import bind_observation, bind_manifest, QUOTE_FIELDS
from scripts.capture_operational_inputs import context_summary_specs, context_inventory
from harness.market_capture import make_record, validate_record, consensus, disagreements

STAMP = '2026-10-30T10:00:00Z'


def fixture(kind='quote'):
    if kind == 'quote':
        fields = dict(event_id='event', home_team_id='home', away_team_id='away',
                      selection_id='away', sportsbook='test', market='spread', side='away',
                      line=7.0, american_odds=-105, period='FULL_GAME', settlement_rules_id='fixture-rules')
    else:
        fields = dict(event_id='event', team_id='away', player_id='player', status='Unknown')
    raw = json.dumps({'row': fields}, allow_nan=True).encode()
    receipt = dict(league='nba', url='fixture://test', raw_sha256=hashlib.sha256(raw).hexdigest(),
                   retrieved_at_utc=STAMP, provider_observed_at_utc=None)
    bindings = {k: '/row/' + k for k in fields}
    return raw, receipt, bindings


def call(kind='quote', mutate=None):
    raw, receipt, bindings = fixture(kind)
    if mutate:
        payload = json.loads(raw); mutate(payload['row'])
        raw = json.dumps(payload).encode(); receipt['raw_sha256'] = hashlib.sha256(raw).hexdigest()
        bindings = {k: '/row/' + k for k in payload['row']}
    return bind_observation(raw, receipt, bindings, kind=kind, cutoff=STAMP)


def test_exact_quote_bound_without_authentication_or_usage_claim():
    r = call()
    assert r['observation']['line'] == 7
    assert r['observation']['contract_status'] == 'EXACT_TERMS_BOUND_RULES_NOT_VERIFIED'
    assert r['source']['provider_observed_at_utc'] is None
    assert r['source']['provider_authenticity'] == 'NOT_ASSESSED'
    assert r['model_usage'] == 'NOT_USED' and not r['action_authority']


@pytest.mark.parametrize('field', sorted(QUOTE_FIELDS))
def test_quote_requires_every_bound_contract_field(field):
    raw, receipt, bindings = fixture(); del bindings[field]
    with pytest.raises(ValueError, match='BINDINGS'):
        bind_observation(raw, receipt, bindings, kind='quote', cutoff=STAMP)


@pytest.mark.parametrize('field,value', [('line', True), ('american_odds', False),
    ('american_odds', 0), ('american_odds', 99), ('american_odds', float('nan')),
    ('line', float('inf')), ('selection_id', 'home'), ('home_team_id', 'away'),
    ('side', 'over'), ('market', 'prop'), ('period', ''), ('line', '7')])
def test_bad_quotes_rejected(field, value):
    with pytest.raises(ValueError): call(mutate=lambda row: row.update({field: value}))


def test_unknown_personnel_does_not_become_available_or_zero_minutes():
    r = call('personnel')['observation']
    assert r['status'] == 'UNKNOWN'
    assert r['expected_minutes'] is None and r['participation_state'] == 'UNKNOWN'


@pytest.mark.parametrize('minutes', [True, float('inf'), -1, '20'])
def test_invalid_minutes_rejected(minutes):
    with pytest.raises(ValueError):
        call('personnel', lambda row: row.update(expected_minutes=minutes, minutes_source_or_method='fixture'))


def test_reported_minutes_require_method_and_do_not_prove_fitted_use():
    with pytest.raises(ValueError): call('personnel', lambda r: r.update(expected_minutes=20))
    r = call('personnel', lambda r: r.update(expected_minutes=20, minutes_source_or_method='fixture model'))
    assert r['personnel_transform'] == 'NOT_APPLIED'


@pytest.mark.parametrize('field,value', [('retrieved_at_utc', '2026-10-30T10:00:01Z'),
    ('retrieved_at_utc', '2026-10-30T10:00:00'), ('retrieved_at_utc', True),
    ('requested_at_utc', '2026-10-30T10:00:01Z'),
    ('provider_observed_at_utc', '2026-10-30T10:00:01Z'), ('raw_sha256', '0' * 64)])
def test_bad_receipts_rejected(field, value):
    raw, receipt, bindings = fixture(); receipt[field] = value
    with pytest.raises(ValueError): bind_observation(raw, receipt, bindings, kind='quote', cutoff=STAMP)


def test_source_binding_cannot_claim_field_absent_from_raw():
    raw, receipt, bindings = fixture(); bindings['line'] = '/row/unknown'
    with pytest.raises(ValueError, match='SOURCE_FIELD_MISSING'):
        bind_observation(raw, receipt, bindings, kind='quote', cutoff=STAMP)


def test_offline_cli_binds_raw_and_refuses_overwrite(tmp_path):
    raw, receipt, bindings = fixture('personnel')
    (tmp_path / 'raw.json').write_bytes(raw)
    manifest = {'cutoff_utc': STAMP, 'observations': [{'kind': 'personnel', 'raw_path': 'raw.json', 'receipt': receipt, 'bindings': bindings}]}
    (tmp_path / 'input.json').write_text(json.dumps(manifest))
    command = [sys.executable, 'scripts/bind_source_observations.py', '--capture-root', str(tmp_path), '--manifest', str(tmp_path / 'input.json'), '--output', str(tmp_path / 'output')]
    assert subprocess.run(command, capture_output=True).returncode == 0
    output = (tmp_path / 'output/observations.json').read_bytes()
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert (tmp_path / 'output/observations.json').read_bytes() == output
    manifest['observations'][0]['raw_path'] = '../outside.json'
    with pytest.raises(ValueError, match='SOURCE_PATH_OUTSIDE'):
        bind_manifest(tmp_path, manifest)


def legacy_record(**change):
    kwargs = dict(event_id='e', sportsbook='b', market='spread', line=7, price=-110,
                  timestamp_captured=STAMP, source_url='fixture://test')
    kwargs.update(change)
    return make_record(**kwargs)


@pytest.mark.parametrize('value', [True, False, float('nan'), float('inf'), -float('inf'), 0, -99, 50])
def test_legacy_market_capture_rejects_bad_american_odds(value):
    with pytest.raises(ValueError): legacy_record(price=value)


@pytest.mark.parametrize('change', [{'line': True}, {'line': float('inf')}, {'timestamp_captured': 'nope'},
    {'timestamp_captured': '2026-10-30'}, {'timestamp_source': '2026-10-30T11:00:00Z'},
    {'event_id': None}, {'event_id': True}, {'event_id': 'None'}, {'information_class': 'FORECAST'}])
def test_legacy_bad_capture_rejected(change):
    with pytest.raises(ValueError): legacy_record(**change)


def test_legacy_consensus_cannot_bypass_validation():
    r = legacy_record(); r['price'] = float('nan')
    with pytest.raises(ValueError): consensus([r], 'e', 'spread')
    with pytest.raises(ValueError): disagreements([legacy_record()], 'e', 'spread', threshold=float('nan'))


def test_current_day_context_is_opt_in_and_quarantines_identity_mismatch():
    events = {'nba': {'e': {'event': {'date': '2026-10-31T02:00:00Z'}}}, 'nhl': {}}
    today = dt.date(2026, 10, 30)
    assert not context_summary_specs(events, today, [])
    specs = context_summary_specs(events, today, ['nba'])
    assert len(specs) == 1
    league, kind, url, _ = next(iter(specs.values()))
    receipt = dict(league=league, kind=kind, url=url, status='CAPTURED')
    r = context_inventory([(receipt, {'header': {'id': 'wrong'}, 'injuries': []})])[0]
    assert r['state'] == 'QUARANTINED_EVENT_ID_MISMATCH'
    r = context_inventory([(receipt, {'header': {'id': 'e'}})])[0]
    assert r['availability_state'] == 'UNKNOWN' and r['expected_minutes'] is None
    assert not r['numerically_consumed']


def test_sgo_event_start_is_not_quote_update_time():
    sys.path.insert(0, str(Path('harness').resolve()))
    from market_sportsgameodds import parse_sgo_payload
    payload = {'events': [{'eventID': 'e', 'status': {'startsAt': '2026-10-31T10:00:00Z'},
                          'odds': {'spreads': {'book': {'line': 7, 'price': -110}}}}]}
    row = parse_sgo_payload(payload, STAMP)[0]
    assert 'timestamp_source' not in row


def test_provider_parser_does_not_coerce_boolean_line_to_one():
    sys.path.insert(0, str(Path('harness').resolve()))
    from market_theoddsapi import parse_oddsapi_payload
    from market_sportsgameodds import parse_sgo_payload
    with pytest.raises(ValueError):
        parse_oddsapi_payload([{'id': 'e', 'bookmakers': [{'key': 'b', 'markets': [{'key': 'spreads', 'outcomes': [{'name': 'h', 'price': -110, 'point': True}]}]}]}], STAMP)
    with pytest.raises(ValueError):
        parse_sgo_payload({'events': [{'eventID': 'e', 'odds': {'spreads': {'book': {'line': True, 'price': -110}}}}]}, STAMP)


def test_feed_retrieval_timestamp_is_after_response(monkeypatch):
    sys.path.insert(0, str(Path('harness').resolve()))
    import market_theoddsapi
    monkeypatch.setenv(market_theoddsapi.ENV_KEY, 'SYNTHETIC_TEST_ONLY')
    returned_at = []
    def get(_):
        returned_at.append(dt.datetime.now(dt.timezone.utc))
        return json.dumps([{'id': 'e', 'bookmakers': [{'key': 'b', 'markets': [{'key': 'spreads', 'outcomes': [{'name': 'h', 'price': -110, 'point': 1}]}]}]}])
    rows, _, _ = market_theoddsapi.fetch_odds(get=get)
    assert dt.datetime.fromisoformat(rows[0]['timestamp_captured'].replace('Z', '+00:00')) >= returned_at[0]
