"""Synthetic persistence/chronology regressions; no model performance claims."""
import copy
import hashlib
import io
import json
import tempfile
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import accumulate_mlb_calibration as acc
from scripts import grade_mlb_registry as runner
from scripts import register_mlb_calibration as writer


class CalibrationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = self.root / "registry.json"
        self.ledger = self.root / "ledger.jsonl"
        self.summary = self.root / "summary.json"
        self.card_path = self.root / "diagnostic_card.json"
        self.results_path = self.root / "results.json"
        self.card = {
            "league": "MLB", "card_date": "2026-09-04", "requested_as_of_utc": "2026-09-04T09:59:00Z",
            "generated_at_utc": "2026-09-04T10:00:00Z",
            "pit_provenance": {"pit_status": "PIT_ALIGNED", "max_source_timestamp_utc": "2026-09-04T09:59:00Z"},
            "action_authority": False, "market_overlay_enabled": False,
            "forecasts": [self.forecast("1", .7, .6), self.forecast("2", .3, .4)],
        }
        self.artifact = {"id": 101, "name": "test-only", "run_id": 10, "digest": "sha256:" + "a" * 64,
                         "created_at": "2026-09-04T10:01:00Z"}
        self.write(self.card_path, self.card)
        self.write(self.results_path, self.schedule([self.game("1", 4, 2), self.game("2", 1, 5)]))
        with patch.object(writer, "utcnow", return_value="2026-09-04T10:02:00Z"):
            writer.register(self.card_path, self.registry, 10, self.artifact)

    def forecast(self, event, analytic, sim):
        return {"event_id": event, "forecast_status": "FORECAST_GENERATED", "home_team": "Home " + event,
                "away_team": "Away " + event, "start_time_utc": "2026-09-04T18:00:00Z",
                "grading": {"eligible_for_prospective_grading": False, "eligibility_reason": "REGISTRATION_ATTESTATION_REQUIRED",
                            "analytic_p_home": analytic, "stochastic_sim_p_home": sim},
                "provenance": {"output_hash": "test-only:" + event, "model_id": "test-model", "model_version": "1"},
                "input_snapshot_hash": "test-input", "model_state_config_hash": "test-state", "action_authority": False}

    def game(self, event, home, away, final=True):
        return {"gamePk": event, "status": {"abstractGameState": "Final" if final else "Live",
                "detailedState": "Final" if final else "In Progress"},
                "teams": {"home": {"score": home, "team": {"name": "Home " + event}},
                          "away": {"score": away, "team": {"name": "Away " + event}}}}

    def schedule(self, games):
        return {"dates": [{"date": "2026-09-04", "games": games}]}

    def write(self, path, data):
        path.write_text(json.dumps(data))

    def run_grade(self, date="2026-09-04", include=False, output="output"):
        args = ["--registry", str(self.registry), "--ledger", str(self.ledger), "--summary", str(self.summary),
                "--output-dir", str(self.root / output)]
        if date:
            args.extend(["--grade-date", date, "--results-json", str(self.results_path)])
        if include:
            args.append("--include-graded")
        with redirect_stdout(io.StringIO()):
            return runner.main(args)

    def durable(self):
        return {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()
                and (p in (self.registry, self.ledger, self.summary) or p.parent.name == "cards")}

    def test_completed_card_persists_metrics_and_replay_is_byte_identical(self):
        frozen = self.card_path.read_bytes()
        self.assertEqual(self.run_grade(), 0)
        metrics = json.loads(self.summary.read_text())["metrics"]
        self.assertEqual(metrics["n"], 2)
        self.assertAlmostEqual(metrics["brier_analytic"], .09)
        self.assertAlmostEqual(metrics["brier_sim"], .16)
        self.assertEqual(json.loads(self.registry.read_text())["cards"]["2026-09-04"]["status"], "GRADED")
        before = self.durable()
        self.assertEqual(self.run_grade(include=True, output="replay"), 0)
        self.assertEqual(self.durable(), before)
        self.assertEqual(self.card_path.read_bytes(), frozen)
        report = json.loads((self.root / "replay/registry_grade_run.json").read_text())
        self.assertEqual(report["added_count"], 0)
        self.assertEqual(len(report["results"][0]["duplicate_grades"]), 2)
        self.assertTrue(all(r["forecast_card_sha256"] == hashlib.sha256(frozen).hexdigest() for r in acc.load_ledger(self.ledger)))

    def test_pending_later_final_appends_without_rewriting_prefix(self):
        self.write(self.results_path, self.schedule([self.game("1", 4, 2), self.game("2", 1, 5, False)]))
        self.assertEqual(self.run_grade(), 0)
        prefix = self.ledger.read_bytes()
        self.assertEqual(json.loads(self.registry.read_text())["cards"]["2026-09-04"]["status"], "PARTIALLY_GRADED")
        self.write(self.results_path, self.schedule([self.game("1", 4, 2), self.game("2", 1, 5)]))
        self.assertEqual(self.run_grade(output="later"), 0)
        self.assertTrue(self.ledger.read_bytes().startswith(prefix))
        self.assertEqual(len(acc.load_ledger(self.ledger)), 2)

    def test_unknown_date_fails_without_timestamp_commit(self):
        before = self.durable()
        self.assertEqual(self.run_grade("2026-09-22"), 2)
        self.assertEqual(self.durable(), before)
        no_selection = json.loads((self.root / "output/registry_grade_run.json").read_text())
        self.assertEqual(no_selection["status"], "NO_ELIGIBLE_FORECASTS")
        self.assertFalse(no_selection["success"])
        self.assertEqual(no_selection["grade_count"], 0)
        self.assertEqual(no_selection["grading_state"], "NO_PREGAME_REGISTRATION")
        self.assertIn("UNREGISTERED_CARD_DATE", (self.root / "output/registry_grade_run.json").read_text())

    def test_all_pending_selection_revisits_old_date(self):
        outcomes = acc.outcome_map("2026-09-04", self.results_path)
        with patch.object(acc, "outcome_map", return_value=outcomes):
            self.assertEqual(self.run_grade(date=None), 0)
        self.assertEqual(json.loads(self.summary.read_text())["metrics"]["n"], 2)
        before = self.durable()
        self.assertEqual(self.run_grade(date=None, output="empty"), 0)
        self.assertEqual(self.durable(), before)
        self.assertEqual(json.loads((self.root / "empty/registry_grade_run.json").read_text())["status"], "NO_ELIGIBLE_FORECASTS")

    def test_result_conflict_rejects_entire_batch_without_mutation(self):
        self.assertEqual(self.run_grade(), 0)
        before = self.durable()
        self.write(self.results_path, self.schedule([self.game("1", 2, 4), self.game("2", 1, 5)]))
        self.assertEqual(self.run_grade(include=True, output="conflict"), 2)
        self.assertEqual(self.durable(), before)

    def test_late_invariant_failure_never_appends(self):
        before = self.durable()
        with patch.object(runner, "verify_invariants", return_value={"status": "FAIL", "failures": ["TEST_ONLY_FAILURE"]}):
            self.assertEqual(self.run_grade(), 2)
        self.assertEqual(self.durable(), before)

    def test_missing_or_tampered_frozen_card_fails_without_mutation(self):
        entry = json.loads(self.registry.read_text())["cards"]["2026-09-04"]
        path = Path(entry["card_path"])
        for content in (b"{}", None):
            with self.subTest(content=content):
                if content is None:
                    path.unlink()
                else:
                    path.write_bytes(content)
                before = self.durable()
                self.assertEqual(self.run_grade(), 2)
                self.assertEqual(self.durable(), before)

    def test_result_team_mismatch_rejects_without_mutation(self):
        games = [self.game("1", 4, 2), self.game("2", 1, 5)]
        games[1]["teams"]["home"]["team"]["name"] = "Wrong team"
        self.write(self.results_path, self.schedule(games))
        before = self.durable()
        self.assertEqual(self.run_grade(), 2)
        self.assertEqual(self.durable(), before)

    def test_invalid_final_and_duplicate_result_refused(self):
        for games in ([self.game("1", True, 2)], [self.game("1", 1, 1)], [self.game("1", 4, 2)] * 2):
            with self.subTest(games=games):
                self.write(self.results_path, self.schedule(games))
                before = self.durable()
                self.assertEqual(self.run_grade(), 2)
                self.assertEqual(self.durable(), before)

    def test_registration_refuses_post_start_other_exclusions_and_conflicts(self):
        for change in ("late", "pit", "exclusion", "authority", "probability"):
            with self.subTest(change=change):
                card = copy.deepcopy(self.card)
                if change == "pit": card["pit_provenance"]["pit_status"] = "PIT_MISMATCH"
                if change == "exclusion": card["forecasts"][0]["grading"]["eligibility_reason"] = "SOURCE_AFTER_CUTOFF"
                if change == "authority": card["action_authority"] = True
                if change == "probability": card["forecasts"][0]["grading"]["analytic_p_home"] = float("nan")
                self.write(self.card_path, card)
                dest = self.root / change / "registry.json"
                now = "2026-09-04T18:00:00Z" if change == "late" else "2026-09-04T10:02:00Z"
                with patch.object(writer, "utcnow", return_value=now), self.assertRaises(ValueError):
                    writer.register(self.card_path, dest, 10, self.artifact)
                self.assertFalse(dest.exists())
                self.assertFalse((dest.parent / "cards").exists())
        self.write(self.card_path, self.card)
        before = self.durable()
        with self.assertRaisesRegex(ValueError, "IMMUTABLE"):
            writer.register(self.card_path, self.registry, 11, self.artifact)
        self.assertEqual(self.durable(), before)

    def test_exact_registration_lookup_allowed_after_start_without_retimestamp(self):
        before = self.durable()
        with patch.object(writer, "utcnow", return_value="2026-09-24T00:00:00Z"):
            self.assertEqual(writer.register(self.card_path, self.registry, 10, self.artifact), "ALREADY_REGISTERED")
        self.assertEqual(self.durable(), before)

    def test_historical_rows_are_not_reordered_or_replaced(self):
        rows = [{"grade_id": "z", "card_date": "2026-09-05"}]
        self.ledger.write_text(json.dumps(rows[0], indent=None) + "\n")
        prefix = self.ledger.read_bytes()
        acc.save_ledger(self.ledger, rows + [{"grade_id": "a", "card_date": "2026-09-04"}])
        self.assertTrue(self.ledger.read_bytes().startswith(prefix))
        before = self.ledger.read_bytes()
        with self.assertRaises(ValueError): acc.save_ledger(self.ledger, rows)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_concurrent_retries_append_each_grade_once(self):
        processes = []
        for i in range(2):
            args = [sys.executable, str(Path(runner.__file__)), "--registry", str(self.registry),
                    "--ledger", str(self.ledger), "--summary", str(self.summary),
                    "--grade-date", "2026-09-04", "--include-graded", "--results-json", str(self.results_path),
                    "--output-dir", str(self.root / f"concurrent-{i}")]
            processes.append(subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, stdout + stderr)
        self.assertEqual(len(acc.load_ledger(self.ledger)), 2)
        self.assertEqual(json.loads(self.summary.read_text())["metrics"]["n"], 2)

    def test_retry_recovers_after_append_before_summary_publication(self):
        original = runner.atomic_json
        def interrupted(path, value):
            if Path(path) == self.summary:
                raise OSError("TEST_ONLY_INTERRUPTED_PUBLICATION")
            return original(path, value)
        with patch.object(runner, "atomic_json", side_effect=interrupted), self.assertRaises(OSError):
            self.run_grade()
        prefix = self.ledger.read_bytes()
        self.assertEqual(self.run_grade(output="recovered"), 0)
        self.assertEqual(self.ledger.read_bytes(), prefix)
        self.assertEqual(json.loads(self.summary.read_text())["metrics"]["n"], 2)

    def test_registration_artifact_and_date_binding(self):
        entry = json.loads(self.registry.read_text())["cards"]["2026-09-04"]
        for field, value in (("run_id", 11), ("created_at", "2026-09-04T18:01:00Z")):
            broken = copy.deepcopy(entry)
            broken["artifact"][field] = value
            with self.assertRaises(ValueError):
                writer.validate_registration(self.card_path, broken, "2026-09-04")
        with self.assertRaisesRegex(ValueError, "IDENTITY"):
            writer.validate_registration(self.card_path, entry, "2026-09-22")

    def test_full_identity_changes_key_and_generated_at_start_rejects(self):
        f = self.card["forecasts"][0]
        initial = acc.bound_grade_identity(self.card, f, "1", "frozen")
        for field, value in (("event_id", "other"), ("provenance", {**f["provenance"], "model_version": "2"}),
                             ("provenance", {**f["provenance"], "output_hash": "other"})):
            changed = {**f, field: value}
            self.assertNotEqual(initial, acc.bound_grade_identity(self.card, changed, "1", "frozen"))
        self.assertNotEqual(initial, acc.bound_grade_identity({**self.card, "requested_as_of_utc": "2026-09-04T09:58:00Z"}, f, "1", "frozen"))
        late = copy.deepcopy(self.card)
        late["generated_at_utc"] = "2026-09-04T18:00:00Z"
        with self.assertRaises(ValueError):
            writer.validate_card(late, "2026-09-04", "2026-09-04T18:00:00Z")

    def test_download_failure_is_not_green(self):
        # Pinned local cards remove runtime download dependence; an unavailable pinned card fails.
        registry = json.loads(self.registry.read_text())
        registry["cards"]["2026-09-04"].pop("card_path")
        self.write(self.registry, registry)
        before = self.durable()
        self.assertEqual(self.run_grade(), 2)
        self.assertEqual(self.durable(), before)


if __name__ == "__main__":
    unittest.main()
