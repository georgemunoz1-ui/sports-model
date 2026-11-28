"""Offline regression tests for the new workflow glue, not model qualification."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from scripts import daily_card_workflow as d


class WorkflowContracts(unittest.TestCase):
    def test_current_pacific_date(self):
        clock = dt.datetime(2026, 11, 29, 3, tzinfo=dt.timezone.utc)
        self.assertEqual(d.validate_date("2026-11-28", clock).isoformat(), "2026-11-28")
        for value in ("2026-11-29", "2026-11-27", "20261128", "../../escape", "today"):
            with self.assertRaises(ValueError):
                d.validate_date(value, clock)

    def test_manifest_detects_tamper_and_extra(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "source").write_bytes(b"original")
            d.write(root / "manifest.json", d.manifest(root))
            d.verify_manifest(root)
            (root / "source").write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                d.verify_manifest(root)
            (root / "source").write_bytes(b"original")
            (root / "extra").write_bytes(b"x")
            with self.assertRaises(ValueError):
                d.verify_manifest(root)

    def test_capture_exclusive_directory_and_artifact_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "artifact"
            output.mkdir()
            def fake(script, flag, dest):
                self.assertEqual(flag, "--output")
                self.assertFalse(dest.exists())
                dest.mkdir()
                d.write(dest / "report.json", {"date": "2026-11-28", "sources": [], "action_authority": False})
                d.write(dest / "manifest.json", d.manifest(dest))
            with patch.object(d, "run", fake):
                for kind in ("operational", "recovery"):
                    self.assertEqual(d.acquire(kind, "2026-11-28", output)["status"], "ACQUIRED")
            self.assertTrue((output / "2026-11-28/operational/manifest.json").is_file())
            self.assertTrue((output / "2026-11-28/recovery/manifest.json").is_file())

    def test_nhl_scope_from_adjacent_raw(self):
        from scripts.nhl_history_applicability import SCOPE_SHA256
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            op = root / "op"
            op.mkdir()
            stamp = "2026-11-28T12:00:00+00:00"
            receipts = []
            for date in ("20261127", "20261128", "20261129"):
                raw = json.dumps({"events": []}, sort_keys=True).encode()
                h = hashlib.sha256(raw).hexdigest()
                path = op / "raw" / (h + ".json")
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(raw)
                receipts.append({"league": "nhl", "kind": "schedule",
                    "url": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates=" + date + "&limit=1000",
                    "status": "CAPTURED", "http_status": 200, "raw_path": str(path.relative_to(op)),
                    "raw_sha256": h, "requested_at_utc": stamp, "retrieved_at_utc": stamp})
            d.write(op / "report.json", {"date": "2026-11-28", "timezone": d.PACIFIC.key,
                                        "action_authority": False, "sources": receipts})
            d.write(op / "manifest.json", d.manifest(op))
            dest = root / "current"
            cutoff = d.instant(stamp)
            d.make_nhl_current(op, "2026-11-28", dest, cutoff)
            d.verify_manifest(dest)
            self.assertEqual(d.read(dest / "report.json")["season_scope_sha256"], SCOPE_SHA256)
            self.assertEqual(d.read(dest / "events.json"), {"nhl": {}})
            self.assertEqual(d.read(dest / "report.json")["covered_dates"], ["2026-11-28"])
            with self.assertRaises(ValueError):
                d.captured_schedule(op, "nba", "2026-11-28", cutoff)

    def test_nhl_lock_excluded_before_native_and_stage_manifests(self):
        from scripts import nhl_atomic_capture as atomic
        from shutil import copytree, ignore_patterns
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stage = root / "stage"
            stage.mkdir()
            history = stage / "history"

            def fake(script, *args):
                self.assertEqual(script, "capture_team_histories")
                self.assertEqual(args[-1], history)
                history.mkdir()
                (history / ".collector.lock").touch()
                (history / "evidence.json").write_bytes(b"source bytes")
                # A real nonhidden lock-named evidence file must not be discarded.
                (history / "dependency.lock").write_bytes(b"retain")
                atomic.manifest(history)
                self.assertTrue((history / ".collector.lock").exists())
                self.assertNotIn(".collector.lock", d.read(history / "manifest.json"))

            with patch.object(d, "run", fake):
                d.capture_nhl_history(history)
            self.assertFalse((history / ".collector.lock").exists())
            d.verify_manifest(history)
            d.write(stage / "stage_manifest.json", d.manifest(stage, "stage_manifest.json"))
            self.assertNotIn("history/.collector.lock", d.read(stage / "stage_manifest.json"))
            self.assertIn("history/dependency.lock", d.read(stage / "stage_manifest.json"))
            # Model the uploader's default omission of hidden files.
            restored = root / "restored"
            copytree(stage, restored, ignore=ignore_patterns(".*"))
            d.verify_manifest(restored, "stage_manifest.json")
            d.verify_manifest(restored / "history")
            (restored / "history/evidence.json").unlink()
            with self.assertRaises(ValueError):
                d.verify_manifest(restored, "stage_manifest.json")

    def test_nhl_failed_capture_preserves_receipts_and_removes_lock(self):
        from scripts import nhl_atomic_capture as atomic
        with tempfile.TemporaryDirectory() as folder:
            history = Path(folder) / "history"

            def fail(script, *args):
                history.mkdir()
                (history / ".collector.lock").touch()
                (history / "report.json").write_bytes(b'{"status":"INCOMPLETE"}')
                atomic.manifest(history)
                raise RuntimeError("capture_team_histories:EXIT_2")

            with patch.object(d, "run", fail):
                with self.assertRaisesRegex(RuntimeError, "EXIT_2"):
                    d.capture_nhl_history(history)
            self.assertFalse((history / ".collector.lock").exists())
            self.assertTrue((history / "report.json").exists())
            d.verify_manifest(history)

    def test_unexpected_hidden_evidence_is_not_silently_excluded(self):
        from shutil import copytree, ignore_patterns
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stage = root / "stage"
            stage.mkdir()
            (stage / ".evidence.json").write_bytes(b"must not disappear")
            (stage / "visible.json").write_bytes(b"source")
            d.write(stage / "stage_manifest.json", d.manifest(stage, "stage_manifest.json"))
            self.assertIn(".evidence.json", d.read(stage / "stage_manifest.json"))
            restored = root / "restored"
            copytree(stage, restored, ignore=ignore_patterns(".*"))
            with self.assertRaises(ValueError):
                d.verify_manifest(restored, "stage_manifest.json")

    def test_nfl_missing_source_is_not_no_games(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises((OSError, ValueError)):
                d.nfl_schedule(root, "2026-11-28")
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ValueError, "BLOCKED_NFL_STATE"):
                    d.restore_state(root, "", "")

    def test_finalize_missing_artifacts_is_partial_and_keeps_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.dict(os.environ, {"GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1",
                                        "JOB_RESULTS": "{}", "DOWNLOAD_OUTCOME": "failure"}):
                self.assertEqual(d.finalize("2026-11-28", root / "missing", root / "final"), 2)
            report = d.read(root / "final/report.json")
            self.assertEqual(report["status"], "PARTIAL_OR_BLOCKED")
            self.assertEqual(len(report["failed_stages"]), 7)
            self.assertFalse(report["action_authority"])
            d.verify_manifest(root / "final")

    def test_workflow_shell_and_paths(self):
        wf = yaml.load((d.ROOT / ".github/workflows/daily-card.yml").read_text(), Loader=yaml.BaseLoader)
        self.assertIn("workflow_dispatch", wf["on"])
        self.assertEqual(wf["permissions"], {"contents": "read"})
        for job in wf["jobs"].values():
            for step in job["steps"]:
                if "run" in step:
                    self.assertNotIn("$" + "{{", step["run"])
                    subprocess.run(["bash", "-n"], input=step["run"], text=True, check=True)
        self.assertEqual(wf["jobs"]["cbb_card"]["needs"], "validate")
        self.assertEqual(wf["jobs"]["basketball_hockey"]["strategy"]["fail-fast"], "false")
        downloads = [s for s in wf["jobs"]["finalize"]["steps"] if s.get("uses") == "actions/download-artifact@v4"]
        self.assertEqual(len(downloads), 1)
        self.assertNotIn("name", downloads[0]["with"])
        self.assertEqual(downloads[0]["with"]["merge-multiple"], "false")


if __name__ == "__main__":
    unittest.main()
