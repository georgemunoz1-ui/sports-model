"""A failed native stage must leave evidence and never overwrite an old attempt."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from scripts.run_research_stage import run


class StageEvidence(unittest.TestCase):
    def test_missing_executable_records_failure_and_retry_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); stage = root / 'stage'
            result = run(stage, root, [str(root / 'missing-runner')])
            self.assertEqual(result['status'], 'SPAWN_FAILED')
            before = (stage / 'receipt.json').read_bytes()
            self.assertEqual(json.loads(before)['exit_code'], 127)
            with self.assertRaises(FileExistsError):
                run(stage, root, [sys.executable, '-c', 'pass'])
            self.assertEqual((stage / 'receipt.json').read_bytes(), before)

    def test_failed_process_and_missing_output_cannot_look_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run(root / 'failed', root, [sys.executable, '-c',
                         "import sys; print('source load failed', file=sys.stderr); sys.exit(7)"])
            self.assertEqual((result['status'], result['exit_code']), ('PROCESS_FAILED', 7))
            self.assertIn('source load failed', (root / 'failed/stderr.log').read_text())
            missing = run(root / 'missing-output', root, [sys.executable, '-c', 'pass'], ['package.json'])
            self.assertEqual(missing['status'], 'EXPECTED_OUTPUT_MISSING')
            self.assertEqual(missing['process_exit_code'], 0)

    def test_complete_stage_binds_actual_output_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = run(root / 'ok', root, [sys.executable, '-c',
                         "from pathlib import Path; Path('package.json').write_bytes(b'forecast')"],
                         ['package.json'])
            self.assertEqual(result['status'], 'COMPLETE')
            self.assertEqual(result['outputs'][0]['sha256'], hashlib.sha256(b'forecast').hexdigest())
            self.assertFalse(result['canonical_registration_created'])

    def test_preexisting_output_is_refused_before_process_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'package.json').write_bytes(b'old forecast')
            result = run(root / 'stage', root, [sys.executable, '-c',
                         "from pathlib import Path; Path('ran').touch()"], ['package.json'])
            self.assertEqual(result['status'], 'EXPECTED_OUTPUT_ALREADY_EXISTS')
            self.assertFalse(result['process_started'])
            self.assertFalse((root / 'ran').exists())
            self.assertEqual((root / 'package.json').read_bytes(), b'old forecast')

    def test_timeout_stops_descendants_before_log_hashes_are_frozen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = "import time; time.sleep(.3); print('late output', flush=True)"
            parent = ('import subprocess,sys,time; '
                      f'subprocess.Popen([sys.executable,"-c",{child!r}]); '
                      'time.sleep(10)')
            result = run(root / 'stage', root, [sys.executable, '-c', parent], timeout_seconds=.1)
            self.assertEqual(result['status'], 'TIMEOUT')
            time.sleep(.35)
            raw = (root / 'stage/stdout.log').read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),result['logs']['stdout.log']['sha256'])
            self.assertNotIn(b'late output',raw)


if __name__ == '__main__':
    unittest.main()
