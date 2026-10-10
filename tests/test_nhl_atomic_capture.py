"""Interruption and resume controls for synthetic NHL transport only."""
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import nhl_atomic_capture as atomic

ROOT = Path(__file__).resolve().parents[1]
SCOPE = ROOT / 'research/nhl-season-scope-2026-27-v2.json'
NOW = '2026-10-10T01:00:00+00:00'


class Interrupted(BaseException):
    pass


class AtomicCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.plan = atomic.history_plan(atomic.load_scope(SCOPE))
        self.spec = self.plan['sources'][0]
        self.calls = 0

    def tearDown(self):
        self.temp.cleanup()

    def transport(self, spec):
        self.calls += 1
        body = {'team': {'id': spec['team_id']}, 'requestedSeason': {'year': spec['provider_season']}, 'events': []}
        return atomic.Response(atomic.encoded(body), 200, {}, spec['url'])

    def capture(self, hook=None, clock=lambda: NOW, transport=None):
        return atomic.capture_one(self.root, self.spec, transport or self.transport, clock, hook)

    def test_interruptions_never_invent_receipts_for_orphan_raw(self):
        for stage in ('before_raw_commit', 'after_raw_commit', 'before_receipt_commit', 'after_receipt_commit'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                def interrupt(point, path):
                    if point == stage:raise Interrupted(stage)
                with self.assertRaises(Interrupted):
                    atomic.capture_one(root, self.spec, self.transport, lambda: NOW, interrupt)
                saved, errors = atomic.reuse(root, self.spec, NOW, 6)
                if stage == 'after_receipt_commit':
                    self.assertIsNotNone(saved)
                else:
                    self.assertIsNone(saved)
                    new = atomic.capture_one(root, self.spec, self.transport, lambda: NOW)
                    self.assertIsNotNone(atomic.reuse(root, self.spec, NOW, 6)[0])
                    if stage != 'before_raw_commit':
                        self.assertEqual(len(list((root / 'raw').rglob('body.json'))), 2)
                self.assertFalse(errors)

    def test_atomic_write_never_overwrites_evidence(self):
        path = self.root / 'raw.json'; atomic.atomic(path, b'original')
        with self.assertRaises(FileExistsError):atomic.atomic(path, b'changed')
        self.assertEqual(path.read_bytes(), b'original')

    def test_failed_transport_has_no_fabricated_retrieval_timestamp(self):
        def fail(spec):raise OSError('synthetic transport failure')
        row = self.capture(transport=fail)
        self.assertEqual(row['status'], 'FAILED')
        self.assertIsNone(row['retrieved_at_utc']); self.assertEqual(row['failed_at_utc'], NOW)
        self.assertNotIn('raw_path', row)
        self.assertEqual(len(list((self.root / 'journal').rglob('*.json'))), 1)

    def test_stale_or_corrupt_receipts_are_preserved_not_reused(self):
        for corruption in ('stale', 'raw', 'receipt', 'url', 'timestamp'):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                row = atomic.capture_one(root, self.spec, self.transport, lambda: NOW)
                journal = root / 'journal' / self.spec['id'] / (row['attempt_id'] + '.json')
                check_time = '2026-10-10T07:00:01+00:00' if corruption == 'stale' else NOW
                if corruption == 'raw':(root / row['raw_path']).write_bytes(b'partial')
                if corruption == 'receipt':journal.write_text('{')
                if corruption in ('url', 'timestamp'):
                    edited = copy.deepcopy(row)
                    edited['url' if corruption == 'url' else 'retrieved_at_utc'] = 'https://site.api.espn.com/incorrect' if corruption == 'url' else '2026-10-10T01:00:01Z'
                    journal.write_text(json.dumps(edited))
                before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
                saved, invalid = atomic.reuse(root, self.spec, check_time, 6)
                self.assertIsNone(saved); self.assertTrue(invalid)
                self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()})
                new = atomic.capture_one(root, self.spec, self.transport, lambda: check_time)
                self.assertNotEqual(row['attempt_id'], new['attempt_id'])
                self.assertEqual(atomic.reuse(root, self.spec, check_time, 6)[0]['attempt_id'], new['attempt_id'])

    def test_resume_keeps_original_exact_times_and_never_refetches_success(self):
        root = self.root / 'run'; small = copy.deepcopy(self.plan); small['sources'] = small['sources'][:2]
        with patch.object(atomic, 'history_plan', return_value=small):
            first = atomic.collect_history(root, SCOPE, transport=self.transport, clock=lambda: NOW)
            self.assertEqual(self.calls, 2)
            resumed = atomic.collect_history(root, SCOPE, resume=True, transport=self.transport, clock=lambda: '2026-10-10T02:00:00+00:00')
            self.assertEqual(self.calls, 2)
            self.assertEqual(first['sources'], resumed['sources'])

    def test_resume_reacquires_missing_receipt_with_new_attempt(self):
        root = self.root / 'run'; small = copy.deepcopy(self.plan); small['sources'] = small['sources'][:2]
        def interrupt(stage, path):
            if stage == 'after_raw_commit':raise Interrupted()
        with patch.object(atomic, 'history_plan', return_value=small):
            with self.assertRaises(Interrupted):atomic.collect_history(root, SCOPE, transport=self.transport, clock=lambda: NOW, hook=interrupt)
            orphan = next((root / 'raw').rglob('body.json')); before = orphan.read_bytes()
            report = atomic.collect_history(root, SCOPE, resume=True, transport=self.transport, clock=lambda: NOW)
        self.assertEqual(report['status'], 'COMPLETE'); self.assertEqual(self.calls, 3)
        self.assertEqual(orphan.read_bytes(), before)
        self.assertEqual(len(list((root / 'raw').rglob('body.json'))), 3)

    def test_resume_after_committed_receipt_skips_that_transport(self):
        root = self.root / 'run'; small = copy.deepcopy(self.plan); small['sources'] = small['sources'][:2]
        def interrupt(stage, path):
            if stage == 'after_receipt_commit':raise Interrupted()
        with patch.object(atomic, 'history_plan', return_value=small):
            with self.assertRaises(Interrupted):atomic.collect_history(root, SCOPE, transport=self.transport, clock=lambda: NOW, hook=interrupt)
            before = next((root / 'journal').rglob('*.json')).read_bytes()
            report = atomic.collect_history(root, SCOPE, resume=True, transport=self.transport, clock=lambda: NOW)
        self.assertEqual(self.calls, 2); self.assertEqual(report['status'], 'COMPLETE')
        self.assertIn(before, [p.read_bytes() for p in (root / 'journal').rglob('*.json')])

    def test_resume_reacquires_expired_receipts_without_retimestamping_them(self):
        root = self.root / 'run'; small = copy.deepcopy(self.plan); small['sources'] = small['sources'][:2]
        with patch.object(atomic, 'history_plan', return_value=small):
            first = atomic.collect_history(root, SCOPE, transport=self.transport, clock=lambda: NOW)
            late = atomic.collect_history(root, SCOPE, resume=True, transport=self.transport, clock=lambda: '2026-10-10T07:00:01+00:00')
        self.assertEqual(self.calls, 4); self.assertEqual(len(late['invalid_previous_receipts']), 2)
        for old in first['sources']:
            path = root / 'journal' / old['spec_id'] / (old['attempt_id'] + '.json')
            self.assertEqual(json.loads(path.read_text()), old)
        self.assertEqual({r['retrieved_at_utc'] for r in late['sources']}, {'2026-10-10T07:00:01+00:00'})

    def test_403_is_preserved_and_resume_does_not_retry_it(self):
        root = self.root / 'denied'; small = copy.deepcopy(self.plan); small['sources'] = small['sources'][:2]
        def denied(spec):
            self.calls += 1
            return atomic.Response(b'forbidden', 403, {}, spec['url'])
        with patch.object(atomic, 'history_plan', return_value=small):
            report = atomic.collect_history(root, SCOPE, transport=denied, clock=lambda: NOW)
            self.assertEqual(report['status'], 'INCOMPLETE'); self.assertEqual(self.calls, 1)
            with self.assertRaisesRegex(PermissionError, 'SOURCE_ACCESS_DENIED_REQUIRES_REVIEW'):
                atomic.collect_history(root, SCOPE, resume=True, transport=denied, clock=lambda: NOW)
        self.assertEqual(self.calls, 1)
        self.assertEqual(report['sources'][0]['http_status'], 403)

    def test_json_null_list_or_scalar_journal_is_skipped_as_corrupt(self):
        for corrupt in (None, [], 123, 'invalid receipt'):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / 'run'; small = copy.deepcopy(self.plan); small['sources'] = small['sources'][:1]
                with patch.object(atomic, 'history_plan', return_value=small):
                    atomic.collect_history(root, SCOPE, transport=self.transport, clock=lambda: NOW)
                    journal = next((root / 'journal').rglob('*.json')); journal.write_text(json.dumps(corrupt))
                    before = self.calls
                    resumed = atomic.collect_history(root, SCOPE, resume=True, transport=self.transport, clock=lambda: NOW)
                    self.assertEqual(self.calls, before + 1)
                    self.assertEqual(resumed['status'], 'COMPLETE')
                    self.assertEqual(json.loads(journal.read_text()), corrupt)

    def test_proxy_403_without_http_status_is_not_retried_on_resume(self):
        import urllib.error
        root = self.root / 'proxy'; small = copy.deepcopy(self.plan); small['sources'] = small['sources'][:1]
        def denied(spec):
            self.calls += 1
            raise urllib.error.URLError('Tunnel connection failed: 403 Forbidden')
        with patch.object(atomic, 'history_plan', return_value=small):
            report = atomic.collect_history(root, SCOPE, transport=denied, clock=lambda: NOW)
            receipt = report['sources'][0]
            self.assertIsNone(receipt['http_status']); self.assertIsNone(receipt['retrieved_at_utc'])
            self.assertTrue(atomic.access_denied(receipt))
            with self.assertRaisesRegex(PermissionError, 'SOURCE_ACCESS_DENIED_REQUIRES_REVIEW'):
                atomic.collect_history(root, SCOPE, resume=True, transport=denied, clock=lambda: NOW)
        self.assertEqual(self.calls, 1)
        self.assertFalse(atomic.access_denied({'status': 'FAILED', 'error': '<urlopen error temporary DNS failure>'}))

    def test_resume_refuses_changed_plan(self):
        root = self.root / 'run'; small = copy.deepcopy(self.plan); small['sources'] = small['sources'][:1]
        with patch.object(atomic, 'history_plan', return_value=small):
            atomic.collect_history(root, SCOPE, transport=self.transport, clock=lambda: NOW)
        with self.assertRaisesRegex(ValueError, 'RESUME_PLAN_MISMATCH'):
            atomic.collect_history(root, SCOPE, resume=True, transport=self.transport, clock=lambda: NOW)


if __name__ == '__main__':unittest.main()
