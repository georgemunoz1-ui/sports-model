"""Engineering fixtures only; these tests do not attest remote retention."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from scripts.daily_research_archive import seal_directory, verify_directory


class DailyArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "evidence"
        (self.root / "source").mkdir(parents=True)
        (self.root / "card.json").write_text('{"research": true}')
        (self.root / "source/raw.bin").write_bytes(b"real-byte-fixture\x00")

    def test_full_tree_independent_copy_readback(self):
        manifest = seal_directory(self.root)
        target = Path(self.temp.name) / "readback"
        shutil.copytree(self.root, target)
        result = verify_directory(target, self.root / "manifest.json")
        self.assertEqual(result["file_count"], 2)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertFalse(result["durable_archive_verified"])
        self.assertFalse(result["remote_origin_verified"])
        self.assertEqual(verify_directory(target, manifest)["manifest_sha256"], result["manifest_sha256"])

    def test_every_raw_byte_bound(self):
        seal_directory(self.root)
        (self.root / "source/raw.bin").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "READBACK_MISMATCH"):
            verify_directory(self.root)

    def test_missing_extra_and_symlink_members_refused(self):
        seal_directory(self.root)
        extra = self.root / "unlisted"
        extra.write_text("extra")
        with self.assertRaisesRegex(ValueError, "UNMANIFESTED"):
            verify_directory(self.root)
        extra.unlink()
        (self.root / "card.json").unlink()
        with self.assertRaisesRegex(ValueError, "READBACK_MISMATCH"):
            verify_directory(self.root)
        (self.root / "card.json").symlink_to(self.root / "source/raw.bin")
        with self.assertRaisesRegex(ValueError, "SYMLINK"):
            verify_directory(self.root)

    def test_seal_refuses_overwrite_and_symlinks(self):
        seal_directory(self.root)
        old = (self.root / "manifest.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "ALREADY_EXISTS"):
            seal_directory(self.root)
        self.assertEqual((self.root / "manifest.json").read_bytes(), old)
        alias = Path(self.temp.name) / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "SYMLINK"):
            verify_directory(alias)

    def test_bad_manifest_paths_duplicates_authority_counts(self):
        original = seal_directory(self.root)
        cases = []
        for name in ["../escape", "/absolute", "./card.json", "source//raw.bin", "bad\\path"]:
            item = copy.deepcopy(original)
            item["files"][0]["path"] = name
            cases.append(item)
        duplicate = copy.deepcopy(original)
        duplicate["files"].append(duplicate["files"][0])
        cases.append(duplicate)
        for field, value in [("action_authority", True), ("official_release", True), ("file_count", True), ("total_bytes", -1)]:
            item = copy.deepcopy(original)
            item[field] = value
            cases.append(item)
        for item in cases:
            (self.root / "manifest.json").write_text(json.dumps(item))
            with self.assertRaises(ValueError):
                verify_directory(self.root)

    def test_changed_expected_manifest_rejected(self):
        original = seal_directory(self.root)
        altered = copy.deepcopy(original)
        altered["created_at_utc"] = "changed"
        with self.assertRaisesRegex(ValueError, "MANIFEST_READBACK_MISMATCH"):
            verify_directory(self.root, altered)
