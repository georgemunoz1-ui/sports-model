"""Independent read-only preservation audit of targeted PR repair worktrees."""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path('/workspace/scratch/4d9e36f4eb71')
BASES = {
    95: '5acf5972bc448b4e5c03b65ee69ecd38033765c0',
    105: '629ed150612a56f2dabaecdecaab7019af3e7630',
    106: '335820332d884a3d9e66b5aeaa0f15fa933e2607',
    108: '655bf57df4f230938374617a5d83161d739c4401',
}

def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])

def protected(path):
    return (path.startswith(('data/', 'forecasts/', 'artifacts/', 'reports/', 'state/'))
            or path in {'state.json', 'AUTHORIZATIONS.md',
                        'models/common/volatility_matrix_v1.py'}
            or 'defaults' in path.lower()
            or path.startswith('docs/history/'))

def audit(n, base):
    repo = ROOT / f'repair-{n}'
    tree = git(repo, 'ls-tree', '-r', '-z', base)
    originals = {}
    for item in tree.split(b'\0'):
        if not item:
            continue
        metadata, path = item.split(b'\t', 1)
        mode, kind, sha = metadata.decode().split()
        if kind == 'blob':
            originals[path.decode()] = sha
    checked, violations = 0, []
    for path, expected in originals.items():
        if not protected(path):
            continue
        checked += 1
        actual = repo / path
        if not actual.is_file():
            violations.append({'path': path, 'problem': 'ORIGINAL_MISSING'})
            continue
        raw = actual.read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        if blob != expected:
            violations.append({'path': path, 'problem': 'ORIGINAL_BYTES_CHANGED',
                               'expected_blob': expected, 'actual_blob': blob})
    journal = 'docs/progress.md'
    if journal in originals:
        original = git(repo, 'show', f'{base}:{journal}')
        current = (repo / journal).read_bytes()
        if not current.startswith(original):
            violations.append({'path': journal, 'problem': 'JOURNAL_PREFIX_CHANGED'})
    return {'pr': n, 'base': base, 'current_head': git(repo, 'rev-parse', 'HEAD').decode().strip(),
            'protected_original_files_checked': checked,
            'violations': violations,
            'changed_paths_from_original_head': git(repo, 'diff', '--name-only', base).decode().splitlines(),
            'untracked_paths': git(repo, 'ls-files', '--others', '--exclude-standard').decode().splitlines()}

if __name__ == '__main__':
    reports = [audit(n, base) for n, base in BASES.items()]
    print(json.dumps(reports, indent=2))
    raise SystemExit(any(r['violations'] for r in reports))
