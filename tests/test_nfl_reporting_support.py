"""Reporting-admission tests, not new predictive or prospective evidence.

Native tests use the pinned fit and retained September fixture. Reporting
perturbations and the CLI refusal package are explicitly synthetic. All output
is temporary; historical forecasts and registrations are not rewritten.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import patch

import numpy as np

from models.nfl.contextual import report_support as R
from models.nfl.contextual.recovered_inference import digest, bernoulli_simulation, utc


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/nfl/contextual_v1"
ORIGINAL_RUNTIME_SHA256 = "8951577d6edd2e2e37b370cafe9f90c205b9de8b6b59d9c1aba961f15760c15d"
PROCEDURE = "nfl.integrated_context.reporting_support.v1"
REPLAY_CUTOFF = "2026-09-15T00:12:00Z"


class Support(unittest.TestCase):
    """Pure helper contracts use a deliberately synthetic artifact binding."""

    def setUp(self):
        self.model = {"arms": {
            name: {
                "model_id": "nfl.integrated_context." + name + ".v1.research",
                "feature_names": ["epa"] + ([R.FEATURE] if name in R.CERTIFIED_ARMS else []),
                "training_rows": R.FIT_N,
            }
            for name in ("base", "qb", "availability", "travel", "combined")
        }}
        self.pin = patch.object(R, "MODEL_SHA256", R._digest(self.model))
        self.pin.start()
        self.addCleanup(self.pin.stop)

    def test_observed_zero_support_only(self):
        out = R.report_support(self.model, {R.FEATURE: 0})
        self.assertEqual(out["arms"]["combined"]["status"], R.PASS)
        self.assertFalse(out["personnel_completeness_verified"])
        self.assertFalse(out["action_authority"])

    def test_one_and_two_refused(self):
        for value, reason in (
            (1, "REFUSE_UNQUALIFIED_MISSING_REPORT_REGIME"),
            (2, "REFUSE_UNSEEN_REPORTING_REGIME"),
        ):
            out = R.report_support(self.model, {R.FEATURE: value})
            for arm in R.CERTIFIED_ARMS:
                with self.subTest(count=value, arm=arm):
                    self.assertEqual(out["arms"][arm]["status"], reason)
                    with self.assertRaisesRegex(ValueError, reason):
                        R.require_selected_support(out, arm, "TEST", "TEST")

    def test_unaffected_selected_arms_continue(self):
        for value in (0, 1, 2, None):
            out = R.report_support(self.model, {R.FEATURE: value})
            for arm in ("base", "qb", "travel"):
                self.assertEqual(R.require_selected_support(out, arm, "TEST", "TEST")["status"], R.NA)

    def test_invalid_values_fail_closed(self):
        for value in (None, True, "0", -1, .5, 3, float("nan"), float("inf")):
            with self.subTest(value=value):
                out = R.report_support(self.model, {R.FEATURE: value})
                self.assertEqual(out["arms"]["combined"]["status"], "REFUSE_INVALID_REPORT_MISSING_COUNT")

    def test_changed_artifact_refused_even_at_zero(self):
        model = copy.deepcopy(self.model)
        model["arms"]["combined"]["training_rows"] += 1
        self.assertEqual(
            R.report_support(model, {R.FEATURE: 0})["arms"]["combined"]["status"],
            "REFUSE_UNBOUND_REPORTING_SUPPORT",
        )

    def test_no_feature_mutation(self):
        features = {R.FEATURE: 2, "epa": .2}
        before = copy.deepcopy(features)
        R.report_support(self.model, features)
        self.assertEqual(features, before)

    def test_certificate_counts(self):
        self.assertEqual(sum(R.FIT_COUNTS.values()), R.FIT_N)
        self.assertEqual(R.FIT_COUNTS, {"0": 2877, "1": 8, "2": 0})


class NativeRuntimeSupport(unittest.TestCase):
    """Native successor execution; report-count perturbations are synthetic."""

    @classmethod
    def setUpClass(cls):
        from models.nfl.contextual.model import load_artifact
        from models.nfl.contextual import runtime_reporting_support_v1

        cls.runtime = runtime_reporting_support_v1
        cls.model = load_artifact(DATA / "model_packed.json")
        cls.recovered = json.loads((DATA / "recovered_parameters.json").read_text())
        cls.base = json.loads((DATA / "mnf_base_row.json").read_text())[0]
        cls.context = json.loads((DATA / "mnf_context_integrated.json").read_text())
        cls.event = json.loads((DATA / "mnf_event.json").read_text())
        cls.cutoff = "2026-09-14T12:00:00Z"

    def args(self):
        return self.model, self.recovered, self.base, self.context, self.event, self.cutoff

    def inputs(self):
        from models.nfl.contextual import runtime as predecessor
        return predecessor.live_features(*self.args())

    def call(self, arm="qb", **kwargs):
        kwargs.setdefault("model_id", self.model["arms"][arm]["model_id"])
        return self.runtime.run(*self.args(), 1000, **kwargs)

    def test_exact_model_certificate(self):
        self.assertEqual(R._digest(self.model), R.MODEL_SHA256)
        out = R.report_support(self.model, {R.FEATURE: 0})
        for arm in R.CERTIFIED_ARMS:
            self.assertEqual(out["arms"][arm]["status"], R.PASS)

    def test_selected_unsupported_refuses_before_prediction(self):
        features, audit = self.inputs()
        for count, reason in (
            (1, "REFUSE_UNQUALIFIED_MISSING_REPORT_REGIME"),
            (2, "REFUSE_UNSEEN_REPORTING_REGIME"),
        ):
            for arm in R.CERTIFIED_ARMS:
                with self.subTest(count=count, arm=arm):
                    with patch.object(self.runtime, "live_features", return_value=({**features, R.FEATURE: count}, audit)), patch.object(self.runtime, "predict") as predict:
                        with self.assertRaisesRegex(ValueError, reason):
                            self.call(arm)
                        predict.assert_not_called()

    def test_selected_qb_preserves_numeric_heads_and_refuses_siblings(self):
        features, audit = self.inputs()
        params = self.model["arms"]["qb"]
        expected = self.runtime.predict(params, {key: features[key] for key in params["feature_names"]})["prediction"]
        with patch.object(self.runtime, "live_features", return_value=({**features, R.FEATURE: 2}, audit)), patch.object(self.runtime, "predict", wraps=self.runtime.predict) as predict:
            bundle, _, scores = self.call("qb")
        self.assertEqual(bundle["prediction"], expected)
        self.assertEqual(bundle["features"][R.FEATURE], 2)
        self.assertIsNone(scores)
        self.assertFalse(bundle["action_authority"])
        for arm in R.CERTIFIED_ARMS:
            self.assertIsNone(bundle["arms"][arm]["prediction"])
            self.assertIsNone(bundle["arms"][arm]["contribution_trace"])
            self.assertEqual(bundle["reporting_support"]["arms"][arm]["status"], "REFUSE_UNSEEN_REPORTING_REGIME")
        self.assertEqual(
            {call.args[0]["model_id"] for call in predict.call_args_list},
            {self.model["arms"][arm]["model_id"] for arm in ("base", "qb", "travel")},
        )

    def test_supported_combined_exact_prediction(self):
        features, _ = self.inputs()
        self.assertEqual(features[R.FEATURE], 0)
        params = self.model["arms"]["combined"]
        expected = self.runtime.predict(params, {key: features[key] for key in params["feature_names"]})["prediction"]
        bundle, _, scores = self.call("combined")
        self.assertEqual(bundle["prediction"], expected)
        self.assertEqual(bundle["reporting_support"]["arms"]["combined"]["status"], R.PASS)
        self.assertIsNotNone(scores)
        self.assertFalse(bundle["action_authority"])

    def test_original_runtime_bytes_preserved(self):
        path = ROOT / "models/nfl/contextual/runtime.py"
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), ORIGINAL_RUNTIME_SHA256)

    def test_explicit_model_required_without_fallback(self):
        with patch.object(self.runtime, "live_features") as features, patch.object(self.runtime, "predict") as predict:
            with self.assertRaises(ValueError):
                self.call(model_id=None)
            features.assert_not_called()
            predict.assert_not_called()

    def test_unknown_model_refused_without_fallback(self):
        with patch.object(self.runtime, "live_features") as features, patch.object(self.runtime, "predict") as predict:
            with self.assertRaisesRegex(ValueError, "EXACT_MODEL_ID_REQUIRED_NO_FALLBACK"):
                self.call(model_id="nfl.integrated_context.does_not_exist")
            features.assert_not_called()
            predict.assert_not_called()

    def test_modes_and_market_inputs_refused_before_features(self):
        for kwargs in (
            {"mode": "enhanced_pregame"}, {"mode": "live"},
            {"market": {}}, {"live_state": {}}, {"mode_artifact": {}},
        ):
            with self.subTest(kwargs=kwargs):
                with patch.object(self.runtime, "live_features") as features, patch.object(self.runtime, "predict") as predict:
                    with self.assertRaises(ValueError):
                        self.call(**kwargs)
                    features.assert_not_called()
                    predict.assert_not_called()

    def test_invalid_selected_indicator_refused_before_prediction(self):
        features, audit = self.inputs()
        for value in (None, True, "0", -.1, float("nan"), float("inf")):
            with self.subTest(value=value):
                with patch.object(self.runtime, "live_features", return_value=({**features, R.FEATURE: value}, audit)), patch.object(self.runtime, "predict") as predict:
                    with self.assertRaisesRegex(ValueError, "REFUSE_INVALID_REPORT_MISSING_COUNT"):
                        self.call("combined")
                    predict.assert_not_called()

    def test_changed_fit_refused_before_prediction(self):
        features, audit = self.inputs()
        args = list(copy.deepcopy(self.args()))
        args[0]["arms"]["combined"]["training_rows"] += 1
        with patch.object(self.runtime, "live_features", return_value=(features, audit)), patch.object(self.runtime, "predict") as predict:
            with self.assertRaisesRegex(ValueError, "REFUSE_UNBOUND_REPORTING_SUPPORT"):
                self.runtime.run(*args, 1000, model_id=self.model["arms"]["combined"]["model_id"])
            predict.assert_not_called()

    def test_one_owned_feature_snapshot_and_unchanged_inputs(self):
        before = copy.deepcopy(self.args())
        original = self.runtime.live_features
        supplied = self.args()

        def observe(*args):
            for received, caller in zip(args[:5], supplied[:5]):
                self.assertIsNot(received, caller)
                self.assertEqual(received, caller)
            return original(*args)

        with patch.object(self.runtime, "live_features", side_effect=observe) as features:
            bundle, _, _ = self.call()
        features.assert_called_once()
        self.assertEqual(self.args(), before)
        self.assertEqual(bundle["feature_snapshot"]["feature_sha256"], digest(bundle["features"]))
        self.assertEqual(bundle["feature_snapshot"]["model_artifact_sha256"], digest(self.model))
        self.assertEqual(bundle["feature_snapshot"]["event_id"], self.event["event_id"])
        self.assertEqual(bundle["feature_snapshot"]["cutoff_utc"], self.cutoff)

    def test_predecessor_never_invoked_and_globals_not_replaced(self):
        from models.nfl.contextual import runtime as predecessor
        functions = predecessor.predict, predecessor.live_features
        with patch.object(predecessor, "run", side_effect=AssertionError("PREDECESSOR_EXECUTED")) as legacy:
            bundle, _, _ = self.call()
            legacy.assert_not_called()
        self.assertEqual((predecessor.predict, predecessor.live_features), functions)
        self.assertEqual(bundle["runtime_procedure_id"], PROCEDURE)
        archive = bundle.get("identity_provenance", {})
        self.assertNotIn("legacy_parent_identity", archive)
        self.assertNotIn("legacy_parent_forecast_sha256", archive)

    def test_identity_and_code_bindings_describe_executed_successor(self):
        bundle, _, _ = self.call()
        self.assertEqual(bundle["identity_semantics"], "market_blind_numeric.v2")
        self.assertEqual(bundle["model_id"], self.model["arms"]["qb"]["model_id"])
        self.assertEqual(bundle["model_artifact_sha256"], digest(self.model))
        self.assertEqual(bundle["runtime_procedure_id"], PROCEDURE)
        identity = copy.deepcopy(bundle["numerical_identity"])
        actual_id = identity.pop("identity_sha256")
        self.assertEqual(actual_id, digest(identity))
        self.assertEqual(bundle["identity"], actual_id)
        self.assertEqual(identity["draw_count"], 1000)
        for name in ("runtime.py", "runtime_reporting_support_v1.py", "report_support.py"):
            expected = hashlib.sha256((ROOT / "models/nfl/contextual" / name).read_bytes()).hexdigest()
            self.assertEqual(bundle["code_hashes"][name], expected)
        provenance = bundle.get("identity_provenance", bundle.get("diagnostics", {}).get("identity_provenance", {}))
        components = provenance["identity_components"]
        calibration = copy.deepcopy(components["calibration"])
        calibration_id = calibration.pop("procedure_id")
        self.assertEqual(calibration_id, digest(calibration))
        self.assertEqual(identity["calibration_procedure_id"], calibration_id)
        prediction_code = calibration["observed_prediction_code_sha256"]
        for name in ("runtime_reporting_support_v1.py", "report_support.py"):
            path = "models/nfl/contextual/" + name
            self.assertEqual(prediction_code[path], hashlib.sha256((ROOT / path).read_bytes()).hexdigest())

    def test_draws_match_actual_identity_for_qb_and_combined(self):
        from models.nfl.contextual.model import simulate_joint
        for arm in ("qb", "combined"):
            with self.subTest(arm=arm):
                bundle, winner, scores = self.call(arm)
                prediction = bundle["prediction"]
                expected, summary = bernoulli_simulation(prediction["home_win"], bundle["identity"], 1000)
                np.testing.assert_array_equal(winner, expected)
                self.assertEqual(bundle["winner_simulation"], summary)
                if arm == "combined":
                    expected_scores, score_summary = simulate_joint(
                        prediction["home_margin"], prediction["total_points"], prediction["home_win"],
                        self.model["final_score_residuals"], self.model["simulation_v2"]["tie_rate"],
                        bundle["identity"], 1000,
                    )
                    np.testing.assert_array_equal(scores, expected_scores)
                    self.assertEqual(bundle["score_simulation"], score_summary)
                else:
                    self.assertIsNone(scores)

    def test_parallel_repeats_are_deterministic_without_input_mutation(self):
        before = copy.deepcopy(self.args())
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.call(), range(2)))
        left, right = results
        self.assertEqual(left[0], right[0])
        np.testing.assert_array_equal(left[1], right[1])
        self.assertIsNone(left[2])
        self.assertIsNone(right[2])
        self.assertEqual(self.args(), before)

    def test_display_market_metadata_does_not_change_numeric_identity(self):
        original, original_draws, _ = self.call()
        args = list(copy.deepcopy(self.args()))
        args[4]["market_quotes"] = {"home_moneyline": -500, "away_moneyline": 400}
        args[4]["presentation_note"] = "SYNTHETIC_DISPLAY_METADATA_ONLY"
        changed, draws, _ = self.runtime.run(*args, 1000, model_id=self.model["arms"]["qb"]["model_id"])
        self.assertEqual(original["identity"], changed["identity"])
        self.assertEqual(original["prediction"], changed["prediction"])
        np.testing.assert_array_equal(original_draws, draws)


class SuccessorCLI(unittest.TestCase):
    """Real subprocess replay; temporary synthetic package only for refusal."""

    def invoke(self, output, *, package=None, extra=(), fail_coverage_write=False):
        env = {**os.environ, "NFL_CONTEXT_PACKAGE": str(package or DATA / "event_package_v2.json")}
        entrypoint = ROOT / "scripts/run_nfl_reporting_supported.py"
        command = [sys.executable, str(entrypoint)]
        if fail_coverage_write:
            # The real entry point and native model still execute. Only the
            # final coverage write fails, after successful event persistence.
            runner = """
import importlib.util
import sys
from unittest.mock import patch
spec = importlib.util.spec_from_file_location("reporting_coverage_fault", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
original_write = module._write
def fail_coverage(path, value):
    if path.name == "coverage.json":
        raise OSError("SYNTHETIC_COVERAGE_WRITE_FAILURE")
    return original_write(path, value)
with patch.object(module, "_write", side_effect=fail_coverage):
    raise SystemExit(module.main(sys.argv[2:]))
"""
            command = [sys.executable, "-c", runner, str(entrypoint)]
        return subprocess.run(
            [*command, "--date", "2026-09-14", "--output", str(output), "--simulations", "1000",
             "--replay-cutoff-utc", REPLAY_CUTOFF, *extra],
            cwd=ROOT, env=env, text=True, capture_output=True, timeout=45,
        )

    def test_coverage_write_failure_preserves_stage_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            output = folder / "retryable"
            failed = self.invoke(output, fail_coverage_write=True)
            self.assertNotEqual(failed.returncode, 0, failed.stdout + failed.stderr)
            self.assertIn("SYNTHETIC_COVERAGE_WRITE_FAILURE", failed.stderr)
            self.assertFalse(output.exists())
            retained = [path for path in folder.iterdir()
                        if path.is_dir() and (path / "incomplete_run.json").is_file()]
            self.assertEqual(len(retained), 1, failed.stdout + failed.stderr)
            stage = retained[0]
            marker = json.loads((stage / "incomplete_run.json").read_text())
            self.assertEqual(marker["status"], "INCOMPLETE_UNPUBLISHED_RUN")
            self.assertEqual(Path(marker["requested_output"]), output)
            self.assertEqual(Path(marker["retained_staging_directory"]), stage)
            self.assertIn(str(stage), failed.stderr)
            self.assertFalse((stage / "coverage.json").exists())
            forecast = stage / "2026_01_DEN_KC/forecast.json"
            self.assertTrue(forecast.is_file(), "Successful event must survive the later coverage failure")
            before = {path.relative_to(stage): path.read_bytes()
                      for path in stage.rglob("*") if path.is_file()}
            original_forecast = forecast.read_bytes()

            retry = self.invoke(output)
            self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
            coverage = json.loads((output / "coverage.json").read_text())
            self.assertEqual(coverage["counts"]["COMPLETED"], 1)
            self.assertFalse((output / "incomplete_run.json").exists())
            self.assertEqual((output / "2026_01_DEN_KC/forecast.json").read_bytes(), original_forecast)
            after = {path.relative_to(stage): path.read_bytes()
                     for path in stage.rglob("*") if path.is_file()}
            self.assertEqual(after, before, "Retry must not modify the retained failed execution")

    def test_empty_or_padded_explicit_arguments_refuse_before_package_loading(self):
        cases = (
            ("--model-id", "", "model_id"),
            ("--model-id", "  ", "model_id"),
            ("--model-id", "nfl.integrated_context.qb.v1.research ", "model_id"),
            ("--event-id", "", "event_id"),
            ("--replay-cutoff-utc", "", "replay_cutoff_utc"),
            ("--weekly-state-id", "", "weekly_state_id"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for index, (flag, value, field) in enumerate(cases):
                with self.subTest(flag=flag, value=value):
                    output = folder / str(index)
                    result = self.invoke(output, package=folder / "nonexistent_package.json",
                                         extra=(flag, value))
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("EMPTY_OR_PADDED_EXPLICIT_ARGUMENT:" + field, result.stderr)
                    self.assertNotIn("NFL_CONTEXT_PACKAGE_MISSING", result.stderr)
                    self.assertFalse(output.exists())
            self.assertEqual(list(folder.iterdir()), [])

    def test_default_qb_replay_has_correct_receipt_and_no_registration(self):
        runtime_path = DATA / "runtime.json"
        before = runtime_path.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "replay"
            started = datetime.now(timezone.utc)
            result = self.invoke(output)
            finished = datetime.now(timezone.utc)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            event_dir = output / "2026_01_DEN_KC"
            bundle = json.loads((event_dir / "forecast.json").read_text())
            self.assertEqual(bundle["selected_arm"], "qb")
            self.assertEqual(bundle["model_id"], json.loads(before)["default_research_model"])
            self.assertEqual(bundle["runtime_procedure_id"], PROCEDURE)
            self.assertEqual(bundle["identity_semantics"], "market_blind_numeric.v2")
            self.assertFalse(bundle["action_authority"])
            self.assertFalse(bundle["canonical_prospective_eligible"])
            receipt = json.loads((event_dir / "execution_receipt.json").read_text())
            self.assertEqual(receipt["execution_mode"], "RETROSPECTIVE_DIAGNOSTIC")
            self.assertEqual(receipt["information_cutoff_utc"], REPLAY_CUTOFF)
            self.assertEqual(receipt["forecast_identity"], bundle["identity"])
            self.assertEqual(receipt["runtime_procedure_id"], PROCEDURE)
            self.assertLessEqual(started, utc(receipt["created_at_utc"]))
            self.assertLessEqual(utc(receipt["created_at_utc"]), finished)
            package = json.loads((DATA / "event_package_v2.json").read_text())
            self.assertEqual(receipt["source_package_sha256"], digest(package))
            self.assertEqual(receipt["forecast_sha256"], hashlib.sha256((event_dir / "forecast.json").read_bytes()).hexdigest())
            self.assertFalse(receipt["prospective_registration_verified"])
            self.assertFalse(receipt["canonical_prospective_eligible"])
            self.assertFalse(receipt["action_authority"])
            coverage = json.loads((output / "coverage.json").read_text())
            self.assertEqual(coverage["schema"], "nfl.reporting_supported_coverage.v1")
            self.assertEqual(coverage["execution_mode"], "RETROSPECTIVE_DIAGNOSTIC")
            self.assertEqual(coverage["counts"], {"COMPLETED": 1, "REFUSED": 0, "POST_START": 0, "FAILED": 0})
            self.assertEqual(len(coverage["events"]), 1)
            row = coverage["events"][0]
            self.assertEqual(row["event_id"], "2026_01_DEN_KC")
            self.assertEqual(row["selected_model_id"], bundle["model_id"])
            self.assertEqual(row["status"], "COMPLETED")
            self.assertEqual(row["forecast_identity"], bundle["identity"])
            manifest = json.loads((event_dir / "manifest.json").read_text())
            self.assertIn("forecast.json", manifest)
            self.assertIn("winner_draws.npy", manifest)
            self.assertIn("execution_receipt.json", manifest)
            for name, expected in manifest.items():
                self.assertEqual(hashlib.sha256((event_dir / name).read_bytes()).hexdigest(), expected)
            self.assertFalse(list(output.rglob("registration.jsonl")))
            self.assertFalse(list(output.rglob("forecast_stream.jsonl")))
            draws = np.load(event_dir / "winner_draws.npy", allow_pickle=False)
            self.assertEqual(len(draws), 1000)
            self.assertEqual(hashlib.sha256(draws.tobytes()).hexdigest(), bundle["winner_simulation"]["sha256"])
        self.assertEqual(runtime_path.read_bytes(), before)

    def test_failed_event_retained_and_successful_peer_still_completes(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            package = json.loads((DATA / "event_package_v2.json").read_text())
            package["model_path"] = str(DATA / "model_packed.json")
            package["recovered_parameters_path"] = str(DATA / "recovered_parameters.json")
            package["scope"] = "SYNTHETIC_TEST_ONLY_POPULATION_FAILURE_NOT_HISTORICAL_EVIDENCE"
            bad_event = copy.deepcopy(package["events"][0])
            bad_event["event_id"] = "SYNTHETIC_MISSING_INPUTS"
            package["events"].insert(0, bad_event)
            path = folder / "synthetic_population.json"
            path.write_text(json.dumps(package, allow_nan=False))
            output = folder / "population"
            result = self.invoke(output, package=path)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            coverage = json.loads((output / "coverage.json").read_text())
            self.assertEqual(coverage["counts"], {"COMPLETED": 1, "REFUSED": 0, "POST_START": 0, "FAILED": 1})
            rows = {row["event_id"]: row for row in coverage["events"]}
            self.assertEqual(set(rows), {"SYNTHETIC_MISSING_INPUTS", "2026_01_DEN_KC"})
            self.assertEqual(rows["SYNTHETIC_MISSING_INPUTS"]["status"], "FAILED")
            self.assertIsNone(rows["SYNTHETIC_MISSING_INPUTS"]["forecast_identity"])
            self.assertIsNone(rows["SYNTHETIC_MISSING_INPUTS"]["forecast_directory"])
            self.assertEqual(rows["2026_01_DEN_KC"]["status"], "COMPLETED")
            self.assertTrue((output / "2026_01_DEN_KC/forecast.json").is_file())
            self.assertFalse((output / "SYNTHETIC_MISSING_INPUTS").exists())

    def test_cli_rejects_live_mode_without_creating_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "live"
            result = self.invoke(output, extra=("--mode", "live"))
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("invalid choice", result.stderr)
            self.assertFalse(output.exists())

    def test_selected_unsupported_has_refusal_ledger_and_no_event_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            package = json.loads((DATA / "event_package_v2.json").read_text())
            package["model_path"] = str(DATA / "model_packed.json")
            package["recovered_parameters_path"] = str(DATA / "recovered_parameters.json")
            package["scope"] = "SYNTHETIC_TEST_ONLY_REPORTS_REMOVED_NOT_HISTORICAL_EVIDENCE"
            personnel = package["event_inputs"]["2026_01_DEN_KC"]["context"]["personnel"]
            personnel["state"]["injury_observations"] = []
            personnel["state"]["reserve_absences"] = []
            personnel["source"] = "SYNTHETIC_UNIT_TEST_ONLY_REPORTS_REMOVED"
            personnel["source_sha256"] = digest(personnel["state"])
            path = folder / "synthetic_package.json"
            path.write_text(json.dumps(package, allow_nan=False))
            output = folder / "refusal"
            model_id = "nfl.integrated_context.combined.v1.research"
            result = self.invoke(output, package=path, extra=("--model-id", model_id))
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            coverage = json.loads((output / "coverage.json").read_text())
            self.assertEqual(coverage["counts"], {"COMPLETED": 0, "REFUSED": 1, "POST_START": 0, "FAILED": 0})
            self.assertEqual(len(coverage["events"]), 1)
            row = coverage["events"][0]
            self.assertEqual(row["event_id"], "2026_01_DEN_KC")
            self.assertEqual(row["selected_model_id"], model_id)
            self.assertEqual(row["status"], "REFUSED")
            self.assertIn("REFUSE_UNSEEN_REPORTING_REGIME", row["reason"])
            self.assertIsNone(row["forecast_identity"])
            self.assertIsNone(row["forecast_directory"])
            self.assertFalse((output / "2026_01_DEN_KC").exists())
            self.assertFalse(list(output.rglob("forecast.json")))
            self.assertFalse(list(output.rglob("registration.jsonl")))


if __name__ == "__main__":
    unittest.main()
