"""Software falsifications, not predictive validation or real pregame evidence."""
import copy
import datetime as dt
import hashlib
import importlib.util
import io
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys

import numpy as np
import unittest
import tempfile
import math
from unittest import mock

from models.common import discrete_research as D
from models.common import margin_challenger as F
from models.nfl.contextual import margin_distribution as N

NOW = dt.datetime(2030, 1, 2, tzinfo=dt.timezone.utc)


def fitted():
    rows = []
    for i in range(70):
        start = dt.datetime(2022, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=i * 3)
        rows.append({"event_id": f"SYNTHETIC:{i}", "league": "nfl", "product": "margin",
                     "settlement": N.SETTLEMENT, "parent_model_id": N.PARENT_ID,
                     "information_set": "SYNTHETIC_SOFTWARE_TEST_ONLY", "market_input": False,
                     "parent_fit_cutoff": "2021-01-01T00:00:00Z",
                     "forecast_cutoff": (start - dt.timedelta(hours=1)).isoformat(),
                     "start_time_utc": start.isoformat(),
                     "result_available_at": (start + dt.timedelta(days=1)).isoformat(),
                     "forecast_sha256": D.digest({"forecast": i}), "result_source_sha256": D.digest({"result": i}),
                     "prediction_kind": "CHRONOLOGICAL_OUT_OF_TIME", "predicted_mean": 7.,
                     "observed": [0, 3, 7, 10, 14, -3, 21][i % 7], "scale_features": {},
                     "source_capture_kind": "SYNTHETIC", "timestamp_basis": "SYNTHETIC",
                     "historical_availability_proven": False})
    return F.fit(rows, league="nfl", settlement=N.SETTLEMENT, parent_model_id=N.PARENT_ID,
                 information_set="SYNTHETIC_SOFTWARE_TEST_ONLY", fitted_at="2023-01-01T00:00:00Z")


def write(path, value):
    path.write_text(json.dumps(value, allow_nan=False))
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def configured(tmp_path, fitted, monkeypatch):
    monkeypatch.setattr(N, "now", lambda: NOW)
    prediction = {"home_margin": 11.01, "home_win": .8164, "total_points": 48.12}
    heads = {target: {"impute": [0.], "center": [0.], "scale": [1.], "coefficient": [0.],
                      "intercept": math.log(value / (1 - value)) if target == "home_win" else value}
             for target, value in prediction.items()}
    parent = {"arms": {"qb": {"model_id": N.PARENT_ID, "feature_names": ["x"], "heads": heads}}}
    evaluation = {"schema": "nfl.qb_margin_evaluation.v1", "model_artifact_sha256": fitted["artifact_sha256"],
                  "evaluated_model_artifact_sha256": fitted["artifact_sha256"], "parent_model_id": N.PARENT_ID,
                  "information_set": fitted["information_set"], "settlement": N.SETTLEMENT,
                  "created_at_utc": "2029-01-01T00:00:00Z", "status": "HOLD",
                  "numerical_validity": "PASS", "execution_status": "COMPLETED"}
    config = {"schema": N.CONFIG_SCHEMA, "created_at_utc": "2029-01-01T00:00:00Z", "parent_model_id": N.PARENT_ID,
              "parent_model_file": write(tmp_path / "parent.json", parent),
              "parent_model_artifact_sha256": D.digest(parent), "parent_runtime_code_sha256": N.runtime_hashes(),
              "information_set": fitted["information_set"], "settlement": N.SETTLEMENT,
              "model": write(tmp_path / "model.json", fitted), "evaluation": write(tmp_path / "evaluation.json", evaluation),
              "home_spreads": [-7.5, -7., 0.], "action_authority": False, "prospective_grade_eligible": False}
    path = tmp_path / "config.json"
    write(path, config)
    forecast = {"schema": "nfl.integrated_context_forecast.v1", "model_id": N.PARENT_ID, "selected_arm": "qb",
                "mode": "research_pregame", "market_input": False, "action_authority": False,
                "model_artifact_sha256": D.digest(parent), "code_hashes": N.runtime_hashes(), "identity": "a" * 64,
                "event": {"event_id": "2030_01_WAS_SF", "home_team": "SF", "away_team": "WAS",
                          "start_time_utc": "2030-01-03T00:00:00Z"},
                "cutoff_utc": "2030-01-01T00:00:00Z", "prediction": prediction, "arms": {"qb": {"prediction": copy.deepcopy(prediction)}},
                "features": {"x": 0.}, "assimilation": {"state_id": "b" * 64}}
    return path, config, forecast, N.load_config(path)


def check_half_integer_push_tie_and_independent_winner(configured):
    _, _, forecast, loaded = configured
    frozen = copy.deepcopy(forecast)
    report, draws = N.build(forecast, loaded, n=2000)
    support, pmf = D.validate(report["distribution"])
    first, opposite, integer, _ = report["contracts"][:4]
    assert first["handicap"] == -7.5 and first["analytic"]["push"] == 0
    assert math.isclose(first["analytic"]["win"], float(pmf[support >= 8].sum()))
    assert opposite["handicap"] == 7.5
    assert math.isclose(first["analytic"]["win"] + opposite["analytic"]["win"], 1.)
    assert integer["handicap"] == -7
    assert math.isclose(integer["analytic"]["push"], float(pmf[support == 7].sum()))
    assert report["margin_report"]["analytics"]["winner"]["draw"] > 0
    assert report["parent_winner_probability_conditional_non_tie"] == .8164
    assert report["parent_winner_is_separate_model_head"] is True
    assert report["total_probabilities"] is None
    assert report["evaluation_status"] == "HOLD" and not report["calibration_established"]
    assert forecast == frozen
    N.validate(report, draws)


def check_invalid_lines_fail_closed(configured, line):
    _, _, forecast, loaded = configured
    with raises(ValueError):
        N.build(forecast, loaded, [line], n=100)


def check_wrong_parent_and_scope_rejected(configured, field, value):
    _, _, forecast, loaded = configured
    forecast[field] = value
    with raises(ValueError):
        N.build(forecast, loaded, [-7.5], n=100)


def check_model_creation_and_post_start_require_retrospective(configured):
    _, _, forecast, loaded = configured
    forecast["cutoff_utc"] = "2024-01-01T00:00:00Z"
    forecast["event"]["start_time_utc"] = "2024-01-02T00:00:00Z"
    with raises(ValueError, match="POST_START"):
        N.build(forecast, loaded, [-7.5], n=100)
    report, draws = N.build(forecast, loaded, [-7.5], n=100, retrospective=True)
    assert report["parent_cutoff_utc"] == forecast["cutoff_utc"]
    assert report["mode"] == "RETROSPECTIVE_RECONSTRUCTION"
    assert report["fitted_artifact_existed_at_parent_cutoff"] is False
    assert report["computed_before_kickoff"] is False
    assert not report["prospective_grade_eligible"]
    report["mode"] = "PREGAME_RESEARCH"
    report.pop("report_sha256")
    report["report_sha256"] = D.digest(report)
    with raises(ValueError, match="FALSE_PREGAME"):
        N.validate(report, draws)


def check_new_fit_after_original_cutoff_rejected_even_before_start(configured):
    _, _, forecast, loaded = configured
    forecast["cutoff_utc"] = "2024-01-01T00:00:00Z"
    with raises(ValueError, match="AFTER_FORECAST_CUTOFF"):
        N.build(forecast, loaded, [-7.5], n=100)


def check_bound_registration_rejections(configured, mutation):
    path, config, _, _ = configured
    if mutation in {"missing_oof", "wrong_settlement", "model_hash"}:
        model = json.loads(Path(config["model"]["path"]).read_text())
        if mutation == "missing_oof":
            model["training_evidence"] = []
            model.pop("artifact_sha256")
            model.pop("model_id")
            model["model_id"] = "nfl.margin.full_support.research." + D.digest(model)[:16]
            model["artifact_sha256"] = D.digest(model)
        elif mutation == "wrong_settlement":
            config["settlement"] = "FULL_GAME_OT_POSTSEASON"
        else:
            model["state"]["residuals"][0] += 1
        config["model"] = write(Path(config["model"]["path"]), model)
    elif mutation == "evaluation_fail":
        ev = json.loads(Path(config["evaluation"]["path"]).read_text())
        ev["status"] = "FAIL"
        config["evaluation"] = write(Path(config["evaluation"]["path"]), ev)
    elif mutation == "runtime_code":
        config["parent_runtime_code_sha256"]["runtime.py"] = "0" * 64
    else:
        ev = json.loads(Path(config["evaluation"]["path"]).read_text())
        ev["parent_model_id" if mutation == "evaluation_parent" else "model_artifact_sha256"] = "wrong"
        config["evaluation"] = write(Path(config["evaluation"]["path"]), ev)
    write(path, config)
    with raises(ValueError):
        N.load_config(path)


def check_resealed_label_or_draw_tamper_rejected(configured):
    _, _, forecast, loaded = configured
    report, draws = N.build(forecast, loaded, [-7.], n=100)
    report["contracts"][0]["conditional_nonpush_label"] = None
    report.pop("report_sha256")
    report["report_sha256"] = D.digest(report)
    with raises(ValueError, match="CONTRACT_MISMATCH"):
        N.validate(report, draws)
    report, draws = N.build(forecast, loaded, [-7.], n=100)
    draws[0] += 1
    with raises(ValueError, match="DRAW_MISMATCH"):
        N.validate(report, draws)


def check_immutable_persistence_and_cross_start_guard(configured, tmp_path, monkeypatch):
    _, _, forecast, loaded = configured
    report, draws = N.build(forecast, loaded, [-7.5], n=100)
    destination = tmp_path / "output"
    N.persist(destination, report, draws)
    original = (destination / "margin_report.json").read_bytes()
    with raises(ValueError, match="ALREADY_EXISTS"):
        N.persist(destination, report, draws)
    assert (destination / "margin_report.json").read_bytes() == original
    monkeypatch.setattr(N, "now", lambda: dt.datetime(2030, 1, 4, tzinfo=dt.timezone.utc))
    with raises(ValueError, match="START_CROSSED"):
        N.persist(tmp_path / "too_late", report, draws)
    assert not (tmp_path / "too_late").exists()


def check_runner_routes_configured_qb_spread_without_legacy_calibration(configured, tmp_path, monkeypatch):
    config_path, _, forecast, _ = configured
    path = Path(__file__).resolve().parents[1] / "scripts/run_nfl_integrated.py"
    spec = importlib.util.spec_from_file_location("test_nfl_integrated_margin", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    write(runtime / "runtime.json", {"default_research_model": N.PARENT_ID, "unused_historical_margin_config": str(config_path)})
    monkeypatch.setattr(module.nfl, "DATA", runtime)
    monkeypatch.setattr(module.nfl, "load_schedule", lambda *a: [forecast["event"]])
    monkeypatch.setattr(module.nfl, "build_context", lambda *a, **kw: {"model": {"design": {}}, "recovered": {},
                        "package": {"event_inputs": {forecast["event"]["event_id"]: {"base": {"season": 2030, "week": 1}, "context": {}}}}})
    monkeypatch.setattr(module, "run", lambda *a, **kw: (forecast, np.zeros(100, dtype=int), None))
    def persist_fixture(folder, *a):
        folder.mkdir(parents=True)
        write(folder / "registration.jsonl", {"created_at_utc": NOW.isoformat()})
    monkeypatch.setattr(module, "persist_run", persist_fixture)
    monkeypatch.setattr(module.nfl, "calibrate_spreads", lambda *a, **kw: fail("legacy combined calibration invoked"))
    from models.nfl.contextual import week2
    monkeypatch.setattr(week2, "applies", lambda *a: False)
    forecast["winner_simulation"] = {}
    forecast["score_simulation"] = {"status": "UNAVAILABLE_FOR_SELECTED_ARM"}
    from types import SimpleNamespace
    from pipelines.cards import selection_integration
    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None): return NOW
    monkeypatch.setattr(module, "dt", SimpleNamespace(datetime=Clock, timezone=dt.timezone))
    monkeypatch.setattr(selection_integration, "datetime", Clock)
    output = tmp_path / "runner"
    monkeypatch.setattr(sys, "argv", [str(path), "--date", "2030-01-03", "--output", str(output), "--home-spread", "-7.5", "--simulations", "100", "--margin-model", str(config_path), "--identity-semantics", "legacy.v1"])
    with redirect_stdout(io.StringIO()):
        module.main()
    saved = json.loads((output / forecast["event"]["event_id"] / "margin_distribution/margin_report.json").read_text())
    assert saved["parent_model_id"] == N.PARENT_ID and saved["mode"] == "PREGAME_RESEARCH"
    assert saved["contracts"][0]["handicap"] == -7.5


class Patches:
    def __init__(self):
        self.stack = []

    def setattr(self, obj, name, value):
        patch = mock.patch.object(obj, name, value)
        patch.start()
        self.stack.append(patch)

    def close(self):
        for patch in reversed(self.stack):
            patch.stop()


def raises(error, match=None):
    case = unittest.TestCase()
    return case.assertRaisesRegex(error, match) if match else case.assertRaises(error)


def fail(message):
    raise AssertionError(message)


class NFLMarginDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fitted = fitted()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.patches = Patches()
        self.addCleanup(self.patches.close)
        self.configured = configured(self.folder, self.fitted, self.patches)

    def test_half_integer_push_tie_and_independent_winner(self):
        check_half_integer_push_tie_and_independent_winner(self.configured)

    def test_invalid_lines_fail_closed(self):
        for line in [float("nan"), float("inf"), True, -7.25]:
            with self.subTest(line=line):
                check_invalid_lines_fail_closed(self.configured, line)

    def test_wrong_parent_and_scope_rejected(self):
        for field, value in [("model_id", "nfl.integrated_context.combined.v1.research"),
                             ("selected_arm", "combined"), ("model_artifact_sha256", "0" * 64),
                             ("code_hashes", {}), ("market_input", True), ("mode", "live")]:
            with self.subTest(field=field):
                check_wrong_parent_and_scope_rejected(copy.deepcopy(self.configured), field, value)

    def test_parent_prediction_recomputed_from_pinned_heads(self):
        for mutation in (lambda f: f["prediction"].update(home_margin=99.),
                         lambda f: f["prediction"].update(home_win=.99),
                         lambda f: f["arms"]["qb"]["prediction"].update(home_margin=99.)):
            changed = copy.deepcopy(self.configured[2])
            mutation(changed)
            with self.assertRaisesRegex(ValueError, "PREDICTION_REPLAY"):
                N.build(changed, self.configured[3], [-7.5], n=100)

    def test_postseason_or_conflicting_event_scope_rejected(self):
        for mutation in (lambda f: f["event"].update(game_type="POST"),
                         lambda f: f["event"].update(event_id="2030_19_WAS_SF"),
                         lambda f: f["event"].update(event_id="2020_18_WAS_SF"),
                         lambda f: f["event"].update(event_id="2030_01_SF_WAS"),
                         lambda f: f["event"].update(week=1.5)):
            changed = copy.deepcopy(self.configured[2])
            mutation(changed)
            with self.assertRaises(ValueError):
                N.build(changed, self.configured[3], [-7.5], n=100)

    def test_model_creation_and_post_start_require_retrospective(self):
        check_model_creation_and_post_start_require_retrospective(self.configured)

    def test_config_registered_after_cutoff_is_retrospective_only(self):
        path, config, forecast, _ = self.configured
        config["created_at_utc"] = "2030-01-01T12:00:00Z"
        write(path, config)
        loaded = N.load_config(path)
        with self.assertRaisesRegex(ValueError, "AFTER_FORECAST_CUTOFF"):
            N.build(forecast, loaded, [-7.5], n=100)
        report, draws = N.build(forecast, loaded, [-7.5], n=100, retrospective=True)
        self.assertFalse(report["configuration_existed_at_parent_cutoff"])
        N.validate(report, draws)

    def test_new_fit_after_original_cutoff_rejected_even_before_start(self):
        check_new_fit_after_original_cutoff_rejected_even_before_start(self.configured)

    def test_bound_registration_rejections(self):
        for mutation in ["missing_oof", "wrong_settlement", "model_hash", "evaluation_parent", "evaluation_fit", "runtime_code", "evaluation_fail"]:
            with self.subTest(mutation=mutation):
                child = self.folder / mutation
                child.mkdir()
                fresh = configured(child, self.fitted, self.patches)
                check_bound_registration_rejections(fresh, mutation)

    def test_start_crossed_during_write_does_not_publish(self):
        report, draws = N.build(self.configured[2], self.configured[3], [-7.5], n=100)
        destination = self.folder / "crossed"
        later = dt.datetime(2030, 1, 4, tzinfo=dt.timezone.utc)
        with mock.patch.object(N, "now", side_effect=[NOW, NOW, later]):
            with self.assertRaisesRegex(ValueError, "START_CROSSED_DURING"):
                N.persist(destination, report, draws)
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.folder.glob(".margin-pending-*")), [])

    def test_invalid_or_unfinished_evaluation_refused_even_when_hold(self):
        path, config, forecast, loaded = self.configured
        evaluation_path = Path(config["evaluation"]["path"])
        original = json.loads(evaluation_path.read_text())
        for field, value in [("numerical_validity", "FAIL"), ("numerical_validity", None),
                             ("execution_status", "PARTIAL"), ("execution_status", None)]:
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(original)
                if value is None:
                    changed.pop(field)
                else:
                    changed[field] = value
                config["evaluation"] = write(evaluation_path, changed)
                write(path, config)
                with self.assertRaises(ValueError):
                    N.load_config(path)
        report, draws = N.build(forecast, loaded, [-7.5], n=100)
        report["evaluation_numerical_validity"] = "FAIL"
        report.pop("report_sha256")
        report["report_sha256"] = D.digest(report)
        with self.assertRaisesRegex(ValueError, "RESEARCH_ONLY"):
            N.validate(report, draws)

    def test_refit_requires_and_discloses_exact_evaluation_mapping(self):
        path, config, forecast, _ = self.configured
        evaluation_path = Path(config["evaluation"]["path"])
        evaluation = json.loads(evaluation_path.read_text())
        evaluation["evaluated_model_artifact_sha256"] = "d" * 64
        config["evaluation"] = write(evaluation_path, evaluation)
        write(path, config)
        with self.assertRaisesRegex(ValueError, "REFIT_EVALUATION_MAPPING"):
            N.load_config(path)
        evaluation["deployment_refit"] = {
            "policy": "SAME_PREREGISTERED_ALGORITHM_REFIT_ALL_QUALIFIED_HISTORY",
            "same_algorithm_and_feature_policy": True,
            "deployment_artifact_directly_evaluated": False,
            "evaluation_is_of_training_policy_and_prior_fitted_instance": True}
        config["evaluation"] = write(evaluation_path, evaluation)
        write(path, config)
        report, _ = N.build(forecast, N.load_config(path), [-7.5], n=100)
        self.assertFalse(report["deployment_artifact_directly_evaluated"])
        self.assertEqual(report["evaluated_model_artifact_sha256"], "d" * 64)
        self.assertIn("DEPLOYMENT_REFIT_IS_DISTINCT_FROM_HELDOUT_EVALUATED_ARTIFACT", report["warnings"])

    def test_resealed_label_or_draw_tamper_rejected(self):
        check_resealed_label_or_draw_tamper_rejected(self.configured)

    def test_immutable_persistence_and_cross_start_guard(self):
        check_immutable_persistence_and_cross_start_guard(self.configured, self.folder, self.patches)

    def test_runner_routes_configured_qb_spread_without_legacy_calibration(self):
        check_runner_routes_configured_qb_spread_without_legacy_calibration(self.configured, self.folder, self.patches)


if __name__ == "__main__":
    unittest.main()
