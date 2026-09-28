"""State bindings must survive packaging without masquerading as fetched data."""
import unittest

from scripts.prepare_nfl_event import source_fetches


class EventPackageSources(unittest.TestCase):
    def test_receipts_preserve_original_source_hash_and_clock(self):
        receipt = {'source': 'test-only-source', 'source_sha256': 'a' * 64,
                   'retrieved_at_utc': '2026-09-28T05:52:34Z'}
        context = {'personnel': receipt, 'weekly_state': {'store': 'test-only', 'state_id': 'b' * 64},
                   'assimilation': {'state_sha256': 'c' * 64}}
        self.assertEqual(source_fetches(context), [{'source': receipt['source'],
                         'sha256': receipt['source_sha256'], 'fetched_at_utc': receipt['retrieved_at_utc']}])
        self.assertIn('weekly_state', context)
        self.assertIn('assimilation', context)

    def test_malformed_real_source_is_not_silently_dropped(self):
        with self.assertRaises(KeyError):
            source_fetches({'personnel': {'state': {}}})


if __name__ == '__main__':
    unittest.main()
