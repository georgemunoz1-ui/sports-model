"""Input/provenance/CLI checks; synthetic fixtures establish no sporting edge."""
from __future__ import annotations
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from models.common import discrete_research as D
from pipelines.cards import margin_system as C

CUTOFF = "2026-10-19T10:00:00Z"
START = "2026-10-19T20:00:00Z"
NOW = "2026-10-19T18:00:00Z"
H = "a" * 64


def distribution(eid="event-1", **provenance):
    return D.make_distribution([-7, 0, 3, 7], [.2, .1, .4, .3], league="nfl", product="margin",
        settlement="FULL_GAME_OT_REGULAR", model_id="fixture.margin",
        provenance={"event_id": eid, "cutoff": CUTOFF, **provenance})


def input_value(d=None):
    return {"schema": C.INPUT_SCHEMA, "action_authority": False,
            "distributions": [{"event_id": "event-1", "distribution": d or distribution(),
                               "home_team": "Home", "away_team": "Away", "start_time_utc": START}]}


class CardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.clock = patch.object(D, "writer_clock", return_value=NOW)
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        self.temp.cleanup()

    def put(self, value, name="input.json"):
        path = self.base / name
        path.write_text(json.dumps(value, indent=2))
        return path

    def run_card(self, value=None, **kwargs):
        path = self.put(value or input_value())
        return C.build([path], self.base / "out", draws=500, home_spreads=[-3., 0., 3.], **kwargs)

    def test_real_draws_hashes_same_pmf_and_all_league_coverage(self):
        before = json.dumps(input_value(), indent=2)
        report = self.run_card()
        row = report["results"][0]
        values = np.load(self.base / "out" / row["simulation"]["file"], allow_pickle=False)
        self.assertEqual(len(values), 500)
        self.assertEqual(hashlib.sha256(values.astype("<i8").tobytes()).hexdigest(), row["simulation"]["draw_sha256"])
        self.assertAlmostEqual(row["summary"]["winner"]["home_win"], .7)
        line = row["cover_ladder"][0]
        self.assertEqual((line["home_handicap"], line["away_handicap"]), (-3., 3.))
        self.assertAlmostEqual(line["home"]["push"], .4)
        self.assertAlmostEqual(line["home"]["win"], line["away"]["loss"])
        self.assertEqual(line["kind"], "HYPOTHETICAL")
        self.assertEqual(len(report["coverage"]), 7)
        self.assertEqual(next(r for r in report["coverage"] if r["league"] == "mlb")["status"], "NO_MARGIN_INPUT")
        self.assertFalse(report["prospective_grade_eligible"])
        self.assertFalse(report["action_authority"])
        self.assertEqual((self.base / "input.json").read_text(), before)
        material = dict(report); digest = material.pop("artifact_sha256")
        self.assertEqual(D.digest(material), digest)
        self.assertIn("HYPOTHETICAL", (self.base / "out/margin_card.html").read_text())

    def test_no_overwrite_even_empty_directory(self):
        path = self.put(input_value()); out = self.base / "out"; out.mkdir()
        with self.assertRaisesRegex(FileExistsError, "OUTPUT_EXISTS"):
            C.build([path], out)
        self.assertEqual(list(out.iterdir()), [])

    def test_hash_tampering_rejected_before_output(self):
        value = input_value(); value["distributions"][0]["distribution"]["masses"][0] = .9
        with self.assertRaisesRegex(ValueError, "DISTRIBUTION_HASH"):
            self.run_card(value)
        self.assertFalse((self.base / "out").exists())

    def test_retained_report_parent_integrity(self):
        value = {"schema": "sports.distribution_card.research.v1", "league": "nfl",
                 "action_authority": False, "results": input_value()["distributions"], "coverage": []}
        value["artifact_sha256"] = D.digest(value)
        report = self.run_card(value)
        self.assertEqual(report["results"][0]["parent_report_sha256"], value["artifact_sha256"])
        value["league"] = "nhl"
        with self.assertRaisesRegex(ValueError, "PARENT_REPORT_HASH"):
            C.build([self.put(value, "tampered.json")], self.base / "bad")

    def test_no_winner_probability_inversion(self):
        value = input_value(); value["distributions"][0].pop("distribution")
        value["distributions"][0]["home_win_p"] = .9
        with self.assertRaisesRegex(ValueError, "EXPLICIT_DISTRIBUTION"):
            self.run_card(value)

    def test_event_binding_and_duplicate_identity_refused(self):
        value = input_value(distribution(eid="wrong"))
        with self.assertRaisesRegex(ValueError, "EVENT_BINDING"):
            self.run_card(value)
        value = input_value(); value["distributions"] *= 2
        with self.assertRaisesRegex(ValueError, "DUPLICATE_EVENT"):
            self.run_card(value)

    def test_completion_clock_marks_crossed_start(self):
        with patch.object(D, "writer_clock", side_effect=[NOW, "2026-10-19T21:00:00Z"]):
            report = self.run_card()
        self.assertEqual(report["execution_started_at_utc"], NOW)
        self.assertEqual(report["results"][0]["time_status"], "CREATED_POST_START_RESEARCH_ONLY")

    def test_provenance_start_is_used_and_conflicts_refused(self):
        value = input_value(distribution(start_time_utc=START))
        value["distributions"][0].pop("start_time_utc")
        report = self.run_card(value)
        self.assertEqual(report["results"][0]["time_status"], "CREATED_BEFORE_START_RESEARCH_ONLY")
        value["distributions"][0]["start_time_utc"] = "2026-10-19T21:00:00Z"
        with self.assertRaisesRegex(ValueError, "START_TIME_CONFLICT"):
            C.build([self.put(value)], self.base / "bad")

    def test_equivalent_metadata_time_and_conflicting_metadata(self):
        metadata = {"events": [{"event_id": "event-1", "start_time_utc": "2026-10-19T13:00:00-07:00"}]}
        report = self.run_card(events_path=self.put(metadata, "events.json"))
        self.assertEqual(report["results"][0]["time_status"], "CREATED_BEFORE_START_RESEARCH_ONLY")
        metadata["events"][0]["start_time_utc"] = "2026-10-20T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "METADATA_CONFLICT"):
            C.build([self.base / "input.json"], self.base / "bad", events_path=self.put(metadata, "events.json"))

    def test_future_cutoff_missing_start_and_html_escape(self):
        value = input_value(distribution(cutoff="2026-10-20T00:00:00Z"))
        with self.assertRaisesRegex(ValueError, "CUTOFF_IN_FUTURE"):
            self.run_card(value)
        value = input_value(); value["distributions"][0].pop("start_time_utc")
        value["distributions"][0]["home_team"] = "<script>alert(1)</script>"
        report = self.run_card(value)
        self.assertEqual(report["results"][0]["time_status"], "START_TIME_UNAVAILABLE")
        self.assertNotIn("<script>", (self.base / "out/margin_card.html").read_text())

    def test_cli_creates_files_and_refuses_second_run(self):
        path = self.put(input_value())
        cmd = [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/run_margin_system.py"),
               "--input", str(path), "--output", str(self.base / "cli"), "--draws", "200", "--home-spreads=-3,0,3"]
        done = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        again = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(again.returncode, 2)
        self.assertIn("OUTPUT_EXISTS", again.stderr)


class PointCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from models.common import margin_challenger as F
        training = []
        for i in range(60):
            day = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=i)
            training.append({"event_id": f"train-{i}", "league": "nfl", "product": "margin",
                "settlement": "FULL_GAME_OT_REGULAR", "parent_model_id": "parent.fixture",
                "information_set": "PREGAME", "market_input": False, "forecast_sha256": H,
                "result_source_sha256": H, "prediction_kind": "CHRONOLOGICAL_OUT_OF_TIME",
                "parent_fit_cutoff": "2024-12-01T00:00:00Z", "forecast_cutoff": day.isoformat(),
                "start_time_utc": (day + dt.timedelta(hours=1)).isoformat(),
                "result_available_at": (day + dt.timedelta(hours=5)).isoformat(),
                "predicted_mean": 3., "observed": [-7, -3, 0, 3, 7, 10][i % 6], "scale_features": {}})
        cls.model = F.fit(training, league="nfl", settlement="FULL_GAME_OT_REGULAR",
                          parent_model_id="parent.fixture", information_set="PREGAME",
                          fitted_at="2026-01-01T00:00:00Z")

    def setup_files(self, base, mutate=None):
        model_path = base / "fit.json"; model_path.write_text(json.dumps(self.model))
        config = {"schema": C.CONFIG_SCHEMA, "action_authority": False, "information_set": "PREGAME",
                  "models": [{"path": "fit.json", "sha256": hashlib.sha256(model_path.read_bytes()).hexdigest()}]}
        config_path = base / "config.json"; config_path.write_text(json.dumps(config))
        row = {"event_id": "future", "model_id": "parent.fixture", "start_time_utc": START,
               "home_team": "Home", "away_team": "Away", "forecast_status": "FORECAST_GENERATED",
               "input_snapshot_hash": H, "model_state_config_hash": H,
               "diagnostics": {"home_margin": 3.5}, "warnings": []}
        if mutate:
            mutate(row)
        card = {"league": "NFL", "as_of_utc": CUTOFF, "generated_at_utc": "2026-10-19T11:00:00Z",
                "information_set": "PREGAME", "settlement": "FULL_GAME_OT_REGULAR", "forecasts": [row]}
        card_path = base / "parent.json"; card_path.write_text(json.dumps(card))
        return card_path, config_path

    def test_real_fitted_point_head_integration_and_parent_binding(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(D, "writer_clock", return_value=NOW):
            base = Path(tmp); parent, config = self.setup_files(base)
            report = C.build([], base / "out", parent_card_paths=[parent], challenger_config_path=config, draws=200, home_spreads=[-3, 3])
            self.assertEqual(len(report["results"]), 1)
            d = report["results"][0]["distribution"]
            self.assertEqual(d["provenance"]["parent_model_id"], "parent.fixture")
            self.assertEqual(d["provenance"]["mean_input"], 3.5)
            self.assertIn("NEW_FIT_CREATED_AFTER_PARENT_CUTOFF_RECONSTRUCTION_ONLY", report["results"][0]["warnings"])

    def test_unmatched_parent_missing_point_market_and_bad_hash_are_visible(self):
        cases = [(lambda r: r.update(model_id="wrong"), "MATCHING_CHALLENGER_FIT_REQUIRED"),
                 (lambda r: r.update(information_set="LIVE"), "PARENT_INFORMATION_SET_MISMATCH"),
                 (lambda r: r.update(settlement="REGULATION"), "PARENT_SETTLEMENT_MISMATCH"),
                 (lambda r: r["diagnostics"].clear(), "POINT_HEAD_UNAVAILABLE"),
                 (lambda r: r["diagnostics"].update(market_input=True), "MARKET_INFORMED_PARENT_REFUSED"),
                 (lambda r: r.update(input_snapshot_hash="missing"), "SHA256_REQUIRED")]
        for mutate, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp, patch.object(D, "writer_clock", return_value=NOW):
                base = Path(tmp); parent, config = self.setup_files(base, mutate)
                report = C.build([], base / "out", parent_card_paths=[parent], challenger_config_path=config, draws=100)
                self.assertEqual(report["results"], [])
                self.assertIn(expected, json.dumps(report["source_coverage"]))

    def test_config_hash_tampering_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); parent, config = self.setup_files(base)
            with (base / "fit.json").open("a") as stream:
                stream.write(" ")
            with self.assertRaisesRegex(ValueError, "MODEL_FILE_HASH"):
                C.build([], base / "out", parent_card_paths=[parent], challenger_config_path=config)
            self.assertFalse((base / "out").exists())


if __name__ == "__main__":
    unittest.main()
