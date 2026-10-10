#!/usr/bin/env python3
"""Restore an explicitly supplied immutable package, never acquire or refit one.

Existing runners still enforce source freshness, model pins, population scope and
state consumption. Archive integrity is not source authentication or PIT proof.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

INITIAL = {'nba', 'nhl'}
LEAGUES = {'mlb', 'nfl', 'cfb', 'wnba', 'nba', 'nhl'}


def validate_request(league, artifact_id='', archive_sha256='', initial_research=False):
    if league not in LEAGUES:
        raise ValueError('UNSUPPORTED_WORKFLOW_LEAGUE')
    if league in INITIAL and not initial_research:
        raise ValueError('EXPLICIT_INITIAL_RESEARCH_OPT_IN_REQUIRED')
    if initial_research and league not in INITIAL:
        raise ValueError('INITIAL_RESEARCH_OPT_IN_SCOPE')
    if bool(artifact_id) != bool(archive_sha256):
        raise ValueError('PACKAGE_ARTIFACT_AND_SHA256_REQUIRED_TOGETHER')
    if not artifact_id:
        if league != 'mlb':
            raise ValueError('CURRENT_PACKAGE_ACQUIRE_REQUIRED')
        return
    if not re.fullmatch(r'[1-9][0-9]*', str(artifact_id)):
        raise ValueError('INVALID_PACKAGE_ARTIFACT_ID')
    if not re.fullmatch(r'[a-f0-9]{64}', archive_sha256):
        raise ValueError('INVALID_PACKAGE_ARCHIVE_SHA256')


def restore(archive, expected_sha256, destination, league):
    archive, destination = Path(archive), Path(destination)
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise ValueError('PACKAGE_ARCHIVE_HASH_MISMATCH')
    # Complete validation happens before any extraction. Existing destinations are
    # refused: retries may not overwrite an earlier immutable input snapshot.
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        if not entries or len(entries) > 10000 or sum(e.file_size for e in entries) > 1024**3:
            raise ValueError('PACKAGE_ARCHIVE_SIZE_LIMIT')
        names = set()
        for entry in entries:
            p = PurePosixPath(entry.filename)
            kind = stat.S_IFMT(entry.external_attr >> 16)
            if (p.is_absolute() or '\\' in entry.filename or '..' in p.parts
                    or not p.parts or p.parts[0] != 'packages'
                    or any(ord(c) < 32 for c in entry.filename)
                    or kind not in {0, stat.S_IFREG, stat.S_IFDIR}
                    or str(p) in names):
                raise ValueError('UNSAFE_PACKAGE_ARCHIVE_ENTRY')
            names.add(str(p))
        package_name = f'packages/{league}/package.json'
        if package_name not in names:
            raise ValueError('LEAGUE_PACKAGE_MISSING')
        package = json.loads(bundle.read(package_name))
        if league == 'nfl':
            if package.get('schema') != 'nfl.event_package.v1':
                raise ValueError('NFL_PACKAGE_SCHEMA')
        elif (package.get('schema') != 'sports.current_research_package.v1'
              or package.get('league') != league or package.get('action_authority') is not False):
            raise ValueError('RESEARCH_PACKAGE_IDENTITY')
        destination.mkdir(parents=True, exist_ok=False)
        bundle.extractall(destination)
    root = (destination / 'packages').resolve()
    package_path = root / league / 'package.json'
    if league == 'nfl':
        for key in ('model_path', 'recovered_parameters_path'):
            dependency = (package_path.parent / package[key]).resolve()
            if not dependency.is_relative_to(root) or not dependency.is_file():
                raise ValueError('NFL_PACKAGE_DEPENDENCY_OUTSIDE_ARCHIVE_OR_MISSING')
        environment = {'NFL_CONTEXT_PACKAGE': str(package_path)}
    else:
        environment = {'SPORTS_RESEARCH_PACKAGE_DIR': str(root)}
    return environment, {'archive_sha256': actual, 'league': league,
                         'package_sha256': hashlib.sha256(package_path.read_bytes()).hexdigest(),
                         'package_path': str(package_path),
                         'source_authentication': 'NOT_ESTABLISHED_BY_ARCHIVE_HASH',
                         'freshness_and_model_validation': 'DEFERRED_TO_UNCHANGED_RUNNER',
                         'acquisition_performed': False, 'refit_performed': False,
                         'action_authority': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--league', required=True)
    parser.add_argument('--artifact-id', default='')
    parser.add_argument('--sha256', default='')
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--initial-research', action='store_true')
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    validate_request(args.league, args.artifact_id, args.sha256, args.initial_research)
    if args.validate_only or not args.artifact_id:
        return
    if not all((args.archive, args.destination, args.receipt)):
        parser.error('archive, destination and receipt required for restore')
    environment, receipt = restore(args.archive, args.sha256, args.destination, args.league)
    receipt['artifact_id'] = args.artifact_id
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.receipt.open('x') as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
    with open(os.environ['GITHUB_ENV'], 'a') as stream:
        for key, value in environment.items():
            if '\n' in value or '\r' in value:
                raise ValueError('UNSAFE_ENVIRONMENT_PATH')
            stream.write(f'{key}={value}\n')


if __name__ == '__main__':
    main()
