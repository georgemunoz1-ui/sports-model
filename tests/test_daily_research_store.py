"""Real local Git remote integration; synthetic evidence, never a live forecast."""
import json
from pathlib import Path
import subprocess
import pytest
from scripts.daily_research_archive import seal_directory
from scripts.daily_research_store import restore, publish, validate_registry_extension, files
from scripts.daily_research_notify import notify


def test_git_remote_publication_readback_and_immutability(tmp_path):
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
    checkout = tmp_path / 'checkout'
    assert restore(str(remote), checkout) is None
    source = tmp_path / 'run'
    source.mkdir()
    (source / 'card.json').write_text('{"TEST_ONLY":true}')
    seal_directory(source)
    registry = tmp_path / 'registry'
    registry.mkdir()
    (registry / 'registry.json').write_text(json.dumps({'schema': 'fixture', 'forecasts': {}}))
    report = publish(checkout, source, registry, 'fixture-run-1')
    assert report['status'] == 'REMOTE_BYTES_VERIFIED'
    assert report['worm_storage'] is False
    new_checkout = tmp_path / 'new'
    assert restore(str(remote), new_checkout) == report['archive_commit']
    assert files(new_checkout) == files(checkout)
    with pytest.raises(ValueError, match='IMMUTABLE_RUN_ALREADY_EXISTS'):
        publish(checkout, source, registry, 'fixture-run-1')


def test_frozen_registry_changes_and_grade_prefix_refused(tmp_path):
    before, after = tmp_path / 'before', tmp_path / 'after'
    before.mkdir(); after.mkdir()
    old = {'schema': 'fixture', 'forecasts': {'frozen': {'p': .7}}}
    for p in (before, after):
        (p / 'registry.json').write_text(json.dumps(old))
    (after / 'registry.json').write_text(json.dumps({**old, 'forecasts': {'frozen': {'p': .8}}}))
    with pytest.raises(ValueError, match='FROZEN_REGISTRATION_CHANGED'):
        validate_registry_extension(before, after)
    (after / 'registry.json').write_text(json.dumps(old))
    (before / 'ledger.jsonl').write_text('{"grade":1}\n')
    (after / 'ledger.jsonl').write_text('{"grade":2}\n')
    with pytest.raises(ValueError, match='GRADE_LEDGER_PREFIX_CHANGED'):
        validate_registry_extension(before, after)


def test_notification_delivery_readback_and_mismatch():
    messages = []
    def transport(endpoint, payload=None):
        if payload:
            messages.append(payload)
            return {'number': 123}
        return {**messages[-1], 'number': 123, 'html_url': 'https://github.com/o/r/issues/123'}
    result = notify('o/r', 1, 1, 'failure-drill', drill=True, transport=transport)
    assert result['status'] == 'GITHUB_ISSUE_READBACK_VERIFIED'
    assert not result['human_receipt_verified']
    def corrupt(endpoint, payload=None):
        return {'number': 1} if payload else {'number': 1, 'body': 'changed'}
    with pytest.raises(ValueError, match='NOTIFICATION_READBACK_MISMATCH'):
        notify('o/r', 1, 1, 'pregame', transport=corrupt)
