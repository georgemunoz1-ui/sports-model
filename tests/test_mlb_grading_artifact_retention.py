"""Exercise the workflow's shell and upload expression against retention cases."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest


class GradingArtifactRetentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow = Path(__file__).resolve().parents[1] / '.github/workflows/mlb-calibration-grading.yml'
        # Read the named scalar/block fields without adding a CI dependency.
        cls.steps = []
        for block in workflow.read_text().split('      - name: ')[1:]:
            name, body = block.split('\n', 1)
            step = {'name': name}
            for key in ('id', 'if', 'run', 'continue-on-error'):
                match = re.search(r'^        ' + key + r': (.+)$', body, re.M)
                if match:
                    step[key] = match[1]
            if step.get('run') == '|':
                step['run'] = textwrap.dedent(body.split('        run: |\n', 1)[1])
            if name == 'Upload grading report':
                step['with'] = {
                    'retention-days': int(re.search(r'retention-days: (\d+)', body)[1]),
                    'path': textwrap.dedent(body.split('          path: |\n', 1)[1].split('          if-no-files-found:', 1)[0]),
                }
            cls.steps.append(step)
        cls.persist = next(s for s in cls.steps if s.get('id') == 'persist')
        cls.upload = next(s for s in cls.steps if s.get('name') == 'Upload grading report')

    def persist_case(self, report, changed=False, push_failure=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def git(*args):
                return subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)
            git('init', '-q')
            git('config', 'user.name', 'test-only')
            git('config', 'user.email', 'test@example.invalid')
            registry = root / 'data/grading/mlb/registry.json'
            registry.parent.mkdir(parents=True)
            registry.write_text('{}\n')
            git('add', '.')
            git('commit', '-qm', 'fixture')
            if changed:
                registry.write_text('{"changed":true}\n')
            path = root / 'output/mlb_grading/registry_grade_run.json'
            path.parent.mkdir(parents=True)
            if report is not None:
                path.write_text(report if isinstance(report, str) else json.dumps(report))
            output = root / 'github-output'
            # No remote is configured: changed state exercises a failed push.
            result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', self.persist['run']],
                                    cwd=root, env={**os.environ, 'GITHUB_OUTPUT': str(output),
                                                   'GITHUB_REF_NAME': 'test-only', 'GRADE_DATE': ''},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode != 0, push_failure, result.stderr)
            outputs = dict(line.split('=', 1) for line in output.read_text().splitlines()) if output.exists() else {}
            return outputs.get('noop', '')

    def uploads(self, noop='', event='schedule', grade='success', persist='success', failed=False, cancelled=False):
        # Evaluate the exact scalar Actions expression, including outcome versus
        # continue-on-error conclusion. Unsupported expression syntax fails here.
        expr = self.upload['if'].removeprefix('${{').removesuffix('}}').strip()
        values = {'always()': True, 'failure()': failed, 'cancelled()': cancelled,
                  'github.event_name': event, 'steps.grade.outcome': grade,
                  'steps.persist.outcome': persist, 'steps.persist.outputs.noop': noop}
        for key, value in values.items():
            expr = expr.replace(key, repr(value))
        return eval(expr.replace('&&', ' and ').replace('||', ' or '), {'__builtins__': {}}, {})

    @staticmethod
    def empty():
        return {'status': 'NO_ELIGIBLE_FORECASTS', 'selected_count': 0,
                'grade_count': 0, 'added_count': 0, 'errors': [], 'results': [], 'success': False}

    def test_successful_empty_schedule_skips_upload(self):
        noop = self.persist_case(self.empty())
        self.assertEqual(noop, 'true')
        self.assertFalse(self.uploads(noop))

    def test_explicit_runs_retain_even_empty_evidence(self):
        for event in ('workflow_dispatch', 'push'):
            with self.subTest(event=event):
                self.assertTrue(self.uploads('true', event=event))

    def test_selected_pending_graded_and_replayed_results_retain(self):
        for fields in ({'selected_count': 1}, {'grade_count': 1}, {'added_count': 1},
                       {'status': 'GRADED'}, {'results': [{'duplicate_grades': ['id']}]}):
            with self.subTest(fields=fields):
                self.assertTrue(self.uploads(self.persist_case({**self.empty(), **fields})))

    def test_missing_malformed_or_inconsistent_report_retains(self):
        for report in (None, '{', [], {}, {**self.empty(), 'selected_count': False},
                       {**self.empty(), 'errors': ['UNREGISTERED_CARD_DATE']},
                       {**self.empty(), 'errors': None}):
            with self.subTest(report=report):
                self.assertTrue(self.uploads(self.persist_case(report)))

    def test_durable_change_or_push_failure_retains(self):
        noop = self.persist_case(self.empty(), changed=True, push_failure=True)
        self.assertNotEqual(noop, 'true')
        self.assertTrue(self.uploads(noop, persist='failure', failed=True))
        self.assertTrue(self.uploads(noop))  # same output after a successful push

    def test_failures_skips_and_cancellation_cannot_suppress_evidence(self):
        for override in ({'grade': 'failure'}, {'grade': 'skipped'}, {'persist': 'failure'},
                         {'persist': 'skipped'}, {'failed': True}, {'cancelled': True}):
            with self.subTest(override=override):
                self.assertTrue(self.uploads('true', **override))
        self.assertTrue(self.uploads())

    def test_retention_paths_and_grading_failure_gate_preserved(self):
        self.assertEqual(self.upload['with']['retention-days'], 90)
        self.assertEqual(self.upload['with']['path'].splitlines(), [
            'output/mlb_grading/', 'data/grading/mlb/registry.json',
            'data/grading/mlb/calibration_ledger.jsonl', 'data/grading/mlb/calibration_summary.json'])
        self.assertNotIn('continue-on-error', self.upload)
        gate = next(s for s in self.steps if s.get('name') == 'Fail unsuccessful grading')
        self.assertEqual(gate['if'], "${{ steps.grade.outcome == 'failure' }}")
        self.assertEqual(gate['run'], 'exit 1')


if __name__ == '__main__':
    unittest.main()
