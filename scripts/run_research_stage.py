#!/usr/bin/env python3
"""Execute one approved research command with an immutable stage receipt.

This is process evidence, not model qualification or forecast registration.
Callers still select the native runner and supply its source/identity checks.
The command is an argv array, never shell text. Do not pass secrets as argv.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(stage, cwd, command, expected_files=(), timeout_seconds=None):
    stage, cwd = Path(stage).resolve(), Path(cwd).resolve()
    if not command:
        raise ValueError('RESEARCH_STAGE_COMMAND_REQUIRED')
    if not cwd.is_dir():
        raise ValueError('RESEARCH_STAGE_CWD_MISSING')
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError('RESEARCH_STAGE_TIMEOUT_MUST_BE_POSITIVE')
    # A retry must use a new directory, preserving the prior attempt exactly.
    stage.mkdir(parents=True, exist_ok=False)
    expected = [Path(p) if Path(p).is_absolute() else cwd / p for p in expected_files]
    receipt = {
        'schema': 'sports.research_execution_stage.v1',
        'command': list(command), 'cwd': str(cwd),
        'started_at_utc': stamp(), 'timeout_seconds': timeout_seconds,
        'expected_files': [str(p) for p in expected],
        'stage_runner_sha256': sha256(__file__),
        'authority_granted': False, 'canonical_registration_created': False,
        'output_policy': 'REQUIRE_NEW_FILES',
    }
    (stage / 'started.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    existing = [{'path': str(p), 'sha256': sha256(p) if p.is_file() else None}
                for p in expected if p.exists()]
    if existing:
        receipt.update(exit_code=2, status='EXPECTED_OUTPUT_ALREADY_EXISTS',
                       process_started=False, existing_outputs=existing,
                       completed_at_utc=stamp(), logs={}, outputs=[])
        (stage / 'receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
        return receipt
    try:
        with (stage / 'stdout.log').open('xb') as out, (stage / 'stderr.log').open('xb') as err:
            process = subprocess.Popen(command, cwd=cwd, stdout=out, stderr=err,
                                       start_new_session=True)
            receipt.update(process_started=True, process_group_id=process.pid)
            try:
                code = process.wait(timeout=timeout_seconds)
                receipt.update(exit_code=code, status='COMPLETE' if code == 0 else 'PROCESS_FAILED')
            except subprocess.TimeoutExpired:
                # Stop descendants before freezing log hashes. Killing only the
                # direct child can leave grandchildren writing into those logs.
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(process.pid, sig)
                    except ProcessLookupError:
                        pass
                process.wait()
                code = 124
                receipt.update(exit_code=code, process_exit_code=process.returncode,
                               status='TIMEOUT', timeout_process_group_terminated=True)
    except OSError as exc:
        code = 127
        receipt.update(exit_code=code, status='SPAWN_FAILED',
                       error_type=type(exc).__name__, error_errno=exc.errno, error=str(exc))
    receipt['completed_at_utc'] = stamp()
    receipt['logs'] = {p.name: {'sha256': sha256(p), 'bytes': p.stat().st_size}
                       for p in sorted(stage.glob('*.log'))}
    receipt['outputs'] = []
    for path in expected:
        item = {'path': str(path), 'exists': path.is_file()}
        if item['exists']:
            item.update(sha256=sha256(path), bytes=path.stat().st_size)
        receipt['outputs'].append(item)
    if code == 0 and any(not item['exists'] for item in receipt['outputs']):
        code = 2
        receipt.update(exit_code=code, process_exit_code=0, status='EXPECTED_OUTPUT_MISSING')
    (stage / 'receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--cwd', type=Path, required=True)
    parser.add_argument('--expect-file', type=Path, action='append', default=[])
    parser.add_argument('--timeout-seconds', type=float)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    receipt = run(args.stage, args.cwd, command, args.expect_file, args.timeout_seconds)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    code = receipt['exit_code']
    raise SystemExit(code if code >= 0 else 128 - code)


if __name__ == '__main__':
    main()
