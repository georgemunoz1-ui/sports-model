#!/usr/bin/env python3
"""Deliver an explicit pipeline failure as a GitHub issue and verify readback.

This verifies GitHub issue delivery only, not email/push delivery or human receipt.
The workflow token needs issues:write; no new credentials are created.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess


def api(endpoint, payload=None):
    command = ['gh', 'api', endpoint]
    if payload is not None:
        command += ['--method', 'POST', '--input', '-']
    result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                            text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('NOTIFICATION_API_FAILED')
    return json.loads(result.stdout)


def notify(repository, run_id, attempt, phase, *, drill=False, transport=api):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('REPOSITORY_REQUIRED')
    if not re.fullmatch(r'[0-9]+', str(run_id)) or not re.fullmatch(r'[0-9]+', str(attempt)):
        raise ValueError('WORKFLOW_IDENTITY_REQUIRED')
    if phase not in {'pregame', 'postgame', 'failure-drill'}:
        raise ValueError('UNKNOWN_PHASE')
    url = f'https://github.com/{repository}/actions/runs/{run_id}'
    title = ('[DRILL] ' if drill else '') + f'Daily CFB research {phase} failed: {run_id}/{attempt}'
    body = (f'The {phase} execution did not complete all required stages.\n\n'
            f'Run: {url}\nAttempt: {attempt}\n\n'
            'Inspect acquisition, forecast completeness, pre-start registration, artifact upload/readback, '
            'and durable archive steps in that run. Missing cards or grades must not be treated as success.\n\n'
            'Official release OFF. Wagering authority OFF. No forecast is backdated or replaced.\n'
            + ('\nThis is the explicitly labeled injected-failure acceptance drill; no real forecast was failed.\n' if drill else ''))
    created = transport(f'repos/{repository}/issues', {'title': title, 'body': body})
    number = created.get('number')
    if type(number) is not int or number < 1:
        raise ValueError('NOTIFICATION_CREATE_RECEIPT_INVALID')
    readback = transport(f'repos/{repository}/issues/{number}')
    expected_url = f'https://github.com/{repository}/issues/{number}'
    if any(readback.get(k) != v for k, v in {'title': title, 'body': body, 'html_url': expected_url, 'number': number}.items()):
        raise ValueError('NOTIFICATION_READBACK_MISMATCH')
    return {'schema': 'daily.research.notification.v1', 'status': 'GITHUB_ISSUE_READBACK_VERIFIED',
            'issue_url': expected_url, 'run_url': url, 'run_attempt': int(attempt), 'phase': phase,
            'drill': drill, 'delivered_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'email_or_push_delivery_verified': False, 'human_receipt_verified': False,
            'action_authority': False, 'official_release': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--phase', choices=['pregame', 'postgame', 'failure-drill'], required=True)
    p.add_argument('--drill', action='store_true')
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    if a.report.exists():
        raise ValueError('IMMUTABLE_DELIVERY_RECEIPT_EXISTS')
    report = notify(os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_RUN_ID'],
                    os.environ['GITHUB_RUN_ATTEMPT'], a.phase, drill=a.drill)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    with a.report.open('x') as f:
        json.dump(report, f, sort_keys=True, indent=2)
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
