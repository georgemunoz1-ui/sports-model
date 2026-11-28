"""Synthetic transport/forecast fixtures; no predictive or source-auth evidence."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from scripts import canonical_forecasts as canonical
from scripts import daily_research_postgame as postgame
from scripts.daily_research_archive import verify_directory


class DailyPostgameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "registry"
        self.card_path = self.base / "card/diagnostic_card.json"
        self.card_path.parent.mkdir()
        self.card = {"league": "CFB", "card_date": "2026-09-20",
            "requested_as_of_utc": "2026-09-20T10:00:00Z", "generated_at_utc": "2026-09-20T10:01:00Z",
            "pit_provenance": {"pit_status": "PIT_ORDERED", "max_source_timestamp_utc": "2026-09-20T09:59:00Z",
                "source_fetches": [{"fetched_at_utc": "2026-09-20T09:59:00Z"}]},
            "action_authority": False, "forecasts": []}
        self.artifact = {"id": 1, "digest": "sha256:" + "a"*64, "run_id": 1,
                         "created_at": "2026-09-20T10:02:00Z"}
        self.add_event("1")
        self.register()

    def add_event(self, eid):
        draws = np.array([1, 0, 1, 1], dtype="u1")
        folder = self.card_path.parent / "draws" / ("CFB_" + eid)
        folder.mkdir(parents=True)
        np.save(folder / "winner_draws.npy", draws, allow_pickle=False)
        self.card["forecasts"].append({"event_id": "CFB:" + eid, "model_id": "synthetic.cfb.fixture",
            "home_team": "HOME", "away_team": "AWAY", "start_time_utc": "2026-09-20T18:00:00Z",
            "forecast_status": "FORECAST_GENERATED", "model_winner": "HOME", "analytic_p": .7,
            "stochastic_sim_p": .75, "input_snapshot_hash": "fixture-input", "model_state_config_hash": "fixture-state",
            "simulation": {"binary": {"count": 4, "seed": 1, "sha256": hashlib.sha256(draws.tobytes()).hexdigest(), "home_win_probability": .75}},
            "grading": {"eligible_for_prospective_grading": False, "eligibility_reason": "REGISTRATION_ATTESTATION_REQUIRED"},
            "action_authority": False})

    def register(self, now="2026-09-20T10:03:00Z"):
        self.card_path.write_text(json.dumps(self.card))
        with patch.object(canonical, "utcnow", return_value=now):
            canonical.register(self.card_path, self.root, 1, self.artifact)

    def payload(self, *, final=True, home="HOME", event_id="1"):
        return json.dumps({"events": [{"id": event_id, "date": "2026-09-20T18:00:00Z", "competitions": [{
            "competitors": [{"homeAway": "home", "team": {"displayName": home}, "score": "30"},
                            {"homeAway": "away", "team": {"displayName": "AWAY"}, "score": "20"}],
            "status": {"period": 4, "type": {"completed": final, "state": "post" if final else "in", "name": "STATUS_FINAL" if final else "STATUS_IN_PROGRESS"}}
        }]}]}).encode()

    def run_once(self, name="attempt", fetcher=None):
        return postgame.run_postgame(self.root, self.base / name, "2026-09-20", fetcher=fetcher or (lambda _: self.payload()))

    def test_complete_capture_grade_and_sealed_evidence(self):
        report = self.run_once()
        self.assertEqual(report["status"], "COMPLETED")
        self.assertEqual(report["new_grade_count"], 1)
        self.assertTrue(report["settlement_performed"])
        self.assertEqual(report["transport"], "TEST_INJECTED_FETCHER")
        self.assertFalse(report["independent_source_authentication"])
        self.assertFalse(report["provider_signed_attestation"])
        self.assertEqual(verify_directory(self.base / "attempt")["status"], "VERIFIED")
        ledger = (self.root / "ledger.jsonl").read_bytes()
        row = json.loads(ledger)
        self.assertEqual(row["evaluation_cohort"], "PROSPECTIVE_RESEARCH_SOURCE_UNVERIFIED")
        self.assertFalse(row["certified_calibration_eligible"])
        again = self.run_once("retry", lambda _: self.fail("already settled source must not be refetched"))
        self.assertEqual(again["status"], "ALREADY_GRADED")
        self.assertFalse(again["settlement_performed"])
        self.assertEqual((self.root / "ledger.jsonl").read_bytes(), ledger)

    def test_empty_registry_is_waiting_not_successful_grading_or_defect(self):
        self.root = self.base / "absent"
        report = self.run_once()
        self.assertEqual(report["status"], "AWAITING_FIRST_PROSPECTIVE_REGISTRATION")
        self.assertFalse(report["failures"])
        self.assertFalse(report["settlement_performed"])
        self.assertFalse(self.root.exists())

    def test_missing_target_date_is_failure(self):
        report = postgame.run_postgame(self.root, self.base / "early", "2026-09-19")
        self.assertEqual(report["status"], "NO_REGISTRATIONS_THROUGH_REQUESTED_DATE")
        self.assertFalse(report["settlement_performed"])

    def test_nonfinal_wrong_team_and_acquisition_failures_explicit(self):
        cases = [lambda _: self.payload(final=False), lambda _: self.payload(home="WRONG"),
                 lambda _: (_ for _ in ()).throw(OSError("source unavailable"))]
        for index, fetcher in enumerate(cases):
            report = self.run_once(str(index), fetcher)
            self.assertEqual(report["status"], "INCOMPLETE")
            self.assertTrue(report["pending"] or report["failures"])
            self.assertEqual(report["new_grade_count"], 0)
            self.assertFalse((self.root / "ledger.jsonl").exists())

    def test_mutated_frozen_forecast_rejected_before_fetch(self):
        path = next((self.root / "cards").glob("*.json"))
        path.write_text("{}")
        report = self.run_once(fetcher=lambda _: self.fail("must reject before transport"))
        self.assertEqual(report["status"], "FAILED")
        self.assertIn("REGISTERED_CARD_HASH_MISMATCH", report["failures"][0]["reason"])
        self.assertFalse((self.root / "ledger.jsonl").exists())

    def test_retained_result_source_tamper_rejected_on_retry(self):
        self.run_once()
        ledger = (self.root / "ledger.jsonl").read_bytes()
        old = json.loads(ledger)
        (self.root / old["result_source"]["raw_path"]).write_text("{}")
        report = self.run_once("retry")
        self.assertEqual(report["status"], "FAILED")
        self.assertIn("RESULT_RAW_HASH_MISMATCH", report["failures"][0]["reason"])
        self.assertEqual((self.root / "ledger.jsonl").read_bytes(), ledger)

    def test_poststart_registration_never_admitted(self):
        self.root = self.base / "late"
        with self.assertRaisesRegex(ValueError, "REGISTRATION_NOT_PREGAME"):
            self.register("2026-09-20T18:00:00Z")
        report = self.run_once()
        self.assertEqual(report["status"], "AWAITING_FIRST_PROSPECTIVE_REGISTRATION")

    def test_existing_output_cannot_be_overwritten(self):
        self.run_once()
        before = (self.base / "attempt/report.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_once()
        self.assertEqual((self.base / "attempt/report.json").read_bytes(), before)

    def test_existing_grade_payload_tamper_cannot_claim_already_graded(self):
        self.run_once()
        ledger = self.root / "ledger.jsonl"
        row = json.loads(ledger.read_bytes())
        row["home_score"] = 99
        ledger.write_text(json.dumps(row) + "\n")
        tampered = ledger.read_bytes()
        report = self.run_once("retry")
        self.assertEqual(report["status"], "FAILED")
        self.assertIn("IMMUTABLE_GRADE_CONFLICT", report["failures"][0]["reason"])
        self.assertEqual(ledger.read_bytes(), tampered)

    def test_repository_relative_sources_replay_after_fresh_checkout(self):
        import os
        import shutil
        original_cwd = Path.cwd()
        source_workspace = self.base / "workspace"
        source_workspace.mkdir()
        shutil.copytree(self.root, source_workspace / "state")
        try:
            os.chdir(source_workspace)
            report = postgame.run_postgame(Path("state"), Path("runs/first"), "2026-09-20", fetcher=lambda _: self.payload())
            self.assertEqual(report["status"], "COMPLETED")
            row = json.loads(Path("state/ledger.jsonl").read_bytes())
            self.assertFalse(Path(row["result_source"]["raw_path"]).is_absolute())
            self.assertEqual(row["result_source"]["raw_path_base"], "CANONICAL_REGISTRY")
            restored = self.base / "independent_checkout"
            restored.mkdir()
            shutil.copytree(source_workspace / "state", restored / "state")
            os.chdir(restored)
            shutil.rmtree(source_workspace)
            retry = postgame.run_postgame(Path("state"), Path("runs/retry"), "2026-09-20", fetcher=lambda _: self.fail("no refetch"))
            self.assertEqual(retry["status"], "ALREADY_GRADED")
        finally:
            os.chdir(original_cwd)

    def test_present_empty_registry_retains_expected_waiting_state(self):
        self.root = self.base / "empty"
        self.root.mkdir()
        (self.root / "registry.json").write_text(json.dumps({"schema": canonical.SCHEMA, "forecasts": {}}))
        report = self.run_once(fetcher=lambda _: self.fail("empty registry must not fetch"))
        self.assertEqual(report["status"], "AWAITING_FIRST_PROSPECTIVE_REGISTRATION")
        self.assertFalse(report["failures"])

    def test_malformed_registry_is_failure(self):
        (self.root / "registry.json").write_text(json.dumps({"schema": "wrong", "forecasts": {}}))
        report = self.run_once(fetcher=lambda _: self.fail("invalid registry must not fetch"))
        self.assertEqual(report["status"], "FAILED")
        self.assertIn("CANONICAL_REGISTRY_SCHEMA_INVALID", report["failures"][0]["reason"])

    def test_canonical_raw_source_symlink_is_refused(self):
        target = self.base / "external"
        target.mkdir()
        (self.root / "result_sources").symlink_to(target, target_is_directory=True)
        report = self.run_once()
        self.assertEqual(report["status"], "FAILED")
        self.assertIn("RESULT_SOURCE_SYMLINK_REFUSED", report["failures"][0]["reason"])
        self.assertFalse(list(target.iterdir()))
        self.assertFalse((self.root / "ledger.jsonl").exists())

    def test_unknown_existing_grade_identity_is_refused(self):
        self.run_once()
        ledger = self.root / "ledger.jsonl"
        row = json.loads(ledger.read_text())
        row["receipt_id"] = row["grade_id"] = "unknown"
        ledger.write_text(json.dumps(row) + "\n")
        before = ledger.read_bytes()
        report = self.run_once("retry")
        self.assertEqual(report["status"], "FAILED")
        self.assertIn("EXISTING_GRADE_IDENTITY_MISMATCH", report["failures"][0]["reason"])
        self.assertEqual(ledger.read_bytes(), before)

    def test_waiting_cli_succeeds_without_claiming_settlement(self):
        output = self.base / "waiting"
        result = postgame.main(["--root", str(self.base / "not-yet-created"),
                                "--output", str(output), "--through-date", "2026-09-20"])
        self.assertEqual(result, 0)
        report = json.loads((output / "report.json").read_text())
        self.assertEqual(report["status"], "AWAITING_FIRST_PROSPECTIVE_REGISTRATION")
        self.assertFalse(report["settlement_performed"])
