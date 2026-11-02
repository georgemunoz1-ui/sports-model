#!/usr/bin/env python3
"""Append research evidence to a separate Git branch and read it from the remote.

Git retention is versioned repository storage, not WORM storage. A fresh clone
verifies remotely served bytes; this does not establish provider authenticity.
No main-branch files, previous run directories, or frozen forecasts are replaced.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

BRANCH = 'research/daily-cfb-archive-v1'
_CREDENTIAL = '!f() { printf "%s\\n" "username=x-access-token" "password=$GH_TOKEN"; }; f'


def git(args, cwd=None, *, check=True):
    command = ['git', '-c', 'credential.helper=', '-c', 'credential.helper=' + _CREDENTIAL]
    result = subprocess.run(command + list(args), cwd=cwd, capture_output=True, text=True)
    if check and result.returncode:
        # No environment or credential-bearing command is included in the error.
        raise RuntimeError('GIT_OPERATION_FAILED:' + args[0] + ':' + result.stderr[-2000:])
    return result


def files(root):
    root = Path(root)
    result = {}
    if root.is_symlink():
        raise ValueError('SYMLINK_FORBIDDEN')
    for path in sorted(root.rglob('*')):
        if '.git' in path.relative_to(root).parts:
            continue
        if path.is_symlink():
            raise ValueError('SYMLINK_FORBIDDEN')
        if path.is_file():
            raw = path.read_bytes()
            if len(raw) >= 100_000_000:
                raise ValueError('GIT_FILE_SIZE_LIMIT:' + str(path.relative_to(root)))
            result[path.relative_to(root).as_posix()] = hashlib.sha256(raw).hexdigest()
    return result


def restore(remote, checkout, branch=BRANCH):
    checkout = Path(checkout)
    if checkout.exists():
        raise ValueError('FRESH_CHECKOUT_REQUIRED')
    probe = git(['ls-remote', '--exit-code', '--heads', remote, 'refs/heads/' + branch], check=False)
    if probe.returncode == 0:
        git(['clone', '--single-branch', '--branch', branch, remote, str(checkout)])
        return git(['rev-parse', 'HEAD'], checkout).stdout.strip()
    if probe.returncode != 2:
        raise RuntimeError('REMOTE_ARCHIVE_LOOKUP_FAILED')
    checkout.mkdir(parents=True)
    git(['init', '-b', branch], checkout)
    git(['remote', 'add', 'origin', remote], checkout)
    return None


def validate_registry_extension(previous, successor):
    previous, successor = Path(previous), Path(successor)
    old_files, new_files = files(previous), files(successor)
    for relative, old_hash in old_files.items():
        if relative.endswith('.lock'):
            continue
        if relative not in new_files:
            raise ValueError('REGISTRY_FILE_DELETED:' + relative)
        if old_hash == new_files[relative]:
            continue
        before, after = previous / relative, successor / relative
        if relative == 'registry.json':
            a, b = json.loads(before.read_text()), json.loads(after.read_text())
            if set(a) != set(b) or any(a[k] != b[k] for k in a if k != 'forecasts'):
                raise ValueError('REGISTRY_SCHEMA_CHANGED')
            if any(b['forecasts'].get(k) != v for k, v in a['forecasts'].items()):
                raise ValueError('FROZEN_REGISTRATION_CHANGED')
        elif relative in {'ledger.jsonl', 'selection_ledger.jsonl'}:
            if not after.read_bytes().startswith(before.read_bytes()):
                raise ValueError('GRADE_LEDGER_PREFIX_CHANGED')
        elif relative != 'summary.json':
            raise ValueError('FROZEN_REGISTRY_FILE_CHANGED:' + relative)


def publish(checkout, source, registry, run_key, *, branch=BRANCH):
    checkout, source, registry = map(Path, (checkout, source, registry))
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', run_key):
        raise ValueError('INVALID_RUN_KEY')
    if not re.fullmatch(r'research/[a-z0-9][a-z0-9/-]+', branch):
        raise ValueError('RESEARCH_BRANCH_REQUIRED')
    from scripts.daily_research_archive import verify_directory
    verify_directory(source, source / 'manifest.json')
    old = files(checkout)
    destination = checkout / 'runs' / run_key
    if destination.exists():
        raise ValueError('IMMUTABLE_RUN_ALREADY_EXISTS')
    if (checkout / 'registry').exists():
        validate_registry_extension(checkout / 'registry', registry)
    shutil.copytree(source, destination)
    target = checkout / 'registry'
    target.mkdir(exist_ok=True)
    for relative in files(registry):
        if relative.endswith('.lock'):
            continue
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(registry / relative, path)
    new = files(checkout)
    for relative, digest in old.items():
        if not relative.startswith('registry/') and new.get(relative) != digest:
            raise ValueError('ARCHIVE_HISTORY_CHANGED')
    git(['config', 'user.name', 'sports-model-research-archive'], checkout)
    git(['config', 'user.email', 'actions@users.noreply.github.com'], checkout)
    additions = ['runs/' + run_key]
    if any(not p.endswith('.lock') for p in files(registry)):
        additions.append('registry')
    git(['add', '--', *additions], checkout)
    git(['commit', '-m', 'Retain research execution ' + run_key], checkout)
    commit = git(['rev-parse', 'HEAD'], checkout).stdout.strip()
    # No force push: concurrent updates must fail and be reconciled explicitly.
    git(['push', 'origin', 'HEAD:refs/heads/' + branch], checkout)
    remote = git(['remote', 'get-url', 'origin'], checkout).stdout.strip()
    with tempfile.TemporaryDirectory(prefix='research-remote-readback-') as work:
        fresh = Path(work) / 'readback'
        git(['clone', '--single-branch', '--branch', branch, remote, str(fresh)])
        read_commit = git(['rev-parse', 'HEAD'], fresh).stdout.strip()
        if read_commit != commit or files(fresh) != new:
            raise ValueError('REMOTE_COMMIT_OR_BYTE_READBACK_MISMATCH')
        verify_directory(fresh / 'runs' / run_key, source / 'manifest.json')
    return {'schema': 'daily.research.git_archive.v1', 'status': 'REMOTE_BYTES_VERIFIED',
            'archive_commit': commit, 'archive_branch': branch, 'run_key': run_key,
            'verified_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'files_verified': len(new), 'retention': 'VERSIONED_GIT_NO_AUTOMATIC_EXPIRY',
            'worm_storage': False, 'provider_authenticity_established': False,
            'official_release': False, 'action_authority': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=['restore', 'publish'])
    p.add_argument('--checkout', type=Path, required=True)
    p.add_argument('--source', type=Path)
    p.add_argument('--registry', type=Path)
    p.add_argument('--run-key')
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('GITHUB_REPOSITORY_REQUIRED')
    remote = 'https://github.com/' + repo + '.git'
    if a.report.exists():
        raise ValueError('IMMUTABLE_REPORT_EXISTS')
    if a.operation == 'restore':
        head = restore(remote, a.checkout)
        report = {'status': 'RESTORED' if head else 'NEW_EMPTY_ARCHIVE', 'archive_commit': head,
                  'action_authority': False}
    else:
        if not a.source or not a.registry or not a.run_key:
            p.error('publish requires --source, --registry and --run-key')
        report = publish(a.checkout, a.source, a.registry, a.run_key)
        report['repository'] = repo
        report['commit_url'] = 'https://github.com/' + repo + '/commit/' + report['archive_commit']
    a.report.parent.mkdir(parents=True, exist_ok=True)
    with a.report.open('x') as f:
        json.dump(report, f, sort_keys=True, indent=2, allow_nan=False)
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
