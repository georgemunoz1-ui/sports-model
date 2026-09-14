from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
from research.news_information.replay_official_pilot import replay

EVIDENCE = Path(__file__).resolve().parents[1] / 'pilot_evidence/2026-09-08/official_pilot_4331269.zip'


class RealSourceReplayTests(unittest.TestCase):
    def test_archived_source_replays(self):
        result = replay(EVIDENCE)
        self.assertEqual(result['source_hashes_verified'], 32)
        self.assertEqual(result['games_retained'], 15)
        self.assertEqual(result['nfl_reparsed_rows'], 11)
        self.assertFalse(result['canonical_prospective_eligible'])

    def test_changed_raw_bytes_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / 'tampered.zip'
            with ZipFile(EVIDENCE) as src, ZipFile(changed, 'w') as dest:
                for name in src.namelist():
                    raw = src.read(name)
                    dest.writestr(name, raw + b' ' if '/raw/' in name else raw)
            with self.assertRaisesRegex(ValueError, 'raw source hash/length mismatch'):
                replay(changed)
