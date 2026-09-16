"""Release contract regressions; all input rows below are synthetic."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from harness import module_manifest as mm, ingest_lancebroz as ingest, relay_parser

class ReleaseHealthTests(unittest.TestCase):
    def test_relay_contract(self):
        self.assertTrue(relay_parser.selftest())

    def test_ingestion_contract(self):
        self.assertTrue(ingest.selftest())

    def test_missing_production_source_stays_blocked(self):
        with tempfile.TemporaryDirectory() as td, patch.object(ingest, "DAILY", td), patch.object(ingest, "archive_commit", return_value=""):
            self.assertFalse(ingest.source_health()["ok"])

    def test_capability_pin_and_metadata_are_required(self):
        source = json.loads(Path(mm.MANIFEST_PATH).read_text())
        self.assertEqual(mm.audit()["status"], mm.OK)
        for defect, expected in (("pin", "CAPABILITY_DIGEST_MISMATCH"), ("metadata", "CAPABILITY_METADATA_INCOMPLETE")):
            changed = copy.deepcopy(source)
            entry = changed["capabilities"]["harness/current_sports_data.py"]
            if defect == "pin":
                entry["sha256"] = "0" * 64
            else:
                del entry["version"]
            with tempfile.TemporaryDirectory() as td:
                path = Path(td) / "manifest.json"
                path.write_text(json.dumps(changed))
                self.assertIn(expected, [p["code"] for p in mm.audit(str(path))["problems"]])
