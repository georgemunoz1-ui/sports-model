"""Optional same-parent NFL margin product; frozen winner forecasts stay intact.

The fitted model supplies a full regular-season final-margin PMF, including ties.
The selected QB winner head remains conditional on no tie and is reported separately.
Post-start transforms require the explicit retrospective CLI; no timestamp is reset.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path
import shutil
import tempfile

import numpy as np

from models.common import discrete_research as D
from models.common import margin_challenger as F
from models.common import margin_system as M
from .model import load_artifact

CONFIG_SCHEMA = "nfl.margin_distribution_config.research.v1"
REPORT_SCHEMA = "nfl.margin_distribution_overlay.research.v1"
PARENT_ID = "nfl.integrated_context.qb.v1.research"
SETTLEMENT = "FULL_GAME_OT_REGULAR"
RUNTIME_FILES = ("runtime.py", "personnel.py", "model.py", "features.py",
                 "recovered_inference.py", "operating.py", "capabilities.py",
                 "settlement.py", "forecast_stream.py", "week2.py",
                 "joint_distribution.py", "qb_assimilation.py", "weekly_state.py",
                 "assimilation.py")


def now():
    return dt.datetime.now(dt.timezone.utc)


def _require(value, code):
    if not value:
        raise ValueError(code)


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json(path):
    def reject(value):
        raise ValueError("NONFINITE_JSON:" + value)
    value = json.loads(Path(path).read_text(), parse_constant=reject)
    _require(isinstance(value, dict), "JSON_OBJECT_REQUIRED")
    return value


def runtime_hashes():
    return {name: _hash(Path(__file__).parent / name) for name in RUNTIME_FILES}


def _bound_file(entry, root):
    _require(isinstance(entry, dict), "BOUND_FILE_OBJECT_REQUIRED")
    path = (root / D.identity(entry["path"], "BOUND_FILE_PATH")).resolve()
    _require(_hash(path) == D.source_hash(entry["sha256"]), "BOUND_FILE_HASH_MISMATCH")
    return path


def load_config(path):
    """Load model/evaluation/parent bytes from one explicit pinned registration."""
    path = Path(path).resolve()
    config = _json(path)
    try:
        _require(config["schema"] == CONFIG_SCHEMA and config["action_authority"] is False
                 and config["prospective_grade_eligible"] is False, "MARGIN_CONFIG_SCOPE")
        _require(config["parent_model_id"] == PARENT_ID and config["settlement"] == SETTLEMENT,
                 "MARGIN_CONFIG_PARENT_OR_SETTLEMENT")
        D.identity(config["information_set"], "INFORMATION_SET")
        D.stamp(config["created_at_utc"])
        _require(config["parent_runtime_code_sha256"] == runtime_hashes(), "PARENT_RUNTIME_CODE_MISMATCH")
        parent_path = _bound_file(config["parent_model_file"], path.parent)
        parent = load_artifact(parent_path)
        _require(D.digest(parent) == config["parent_model_artifact_sha256"]
                 and parent["arms"]["qb"]["model_id"] == PARENT_ID, "PARENT_PACKED_MODEL_MISMATCH")
        model_path = _bound_file(config["model"], path.parent)
        evaluation_path = _bound_file(config["evaluation"], path.parent)
        model, evaluation = _json(model_path), _json(evaluation_path)
        F.validate_model(model)
        _require(model["league"] == "nfl" and model["parent_model_id"] == PARENT_ID
                 and model["settlement"] == SETTLEMENT
                 and model["information_set"] == config["information_set"], "FITTED_MARGIN_SCOPE_MISMATCH")
        _require(evaluation["schema"] == "nfl.qb_margin_evaluation.v1"
                 and evaluation["model_artifact_sha256"] == model["artifact_sha256"]
                 and evaluation["parent_model_id"] == PARENT_ID
                 and evaluation["information_set"] == model["information_set"]
                 and evaluation["settlement"] == SETTLEMENT, "MARGIN_EVALUATION_BINDING_MISMATCH")
        _require(evaluation["status"] in {"HOLD", "PASS"}, "MARGIN_EVALUATION_STATUS")
        _require(evaluation["numerical_validity"] == "PASS"
                 and evaluation["execution_status"] == "COMPLETED", "MARGIN_EVALUATION_EXECUTION_OR_NUMERICS_FAILED")
        evaluated_model = D.source_hash(evaluation.get("evaluated_model_artifact_sha256", model["artifact_sha256"]))
        if evaluated_model != model["artifact_sha256"]:
            refit = evaluation.get("deployment_refit", {})
            _require(refit.get("policy") == "SAME_PREREGISTERED_ALGORITHM_REFIT_ALL_QUALIFIED_HISTORY"
                     and refit.get("same_algorithm_and_feature_policy") is True
                     and refit.get("deployment_artifact_directly_evaluated") is False
                     and refit.get("evaluation_is_of_training_policy_and_prior_fitted_instance") is True,
                     "DEPLOYMENT_REFIT_EVALUATION_MAPPING_REQUIRED")
        D.stamp(evaluation["created_at_utc"])
        lines = config.get("home_spreads", [-14., -10., -7.5, -7., -3.5, -3., 0., 3., 3.5, 7., 7.5, 10., 14.])
        _require(isinstance(lines, list) and bool(lines), "HOME_SPREAD_LIST_REQUIRED")
        lines = [D.finite(line) for line in lines]
        _require(len(set(lines)) == len(lines), "DUPLICATE_HOME_SPREAD")
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError("MARGIN_CONFIG_STRUCTURE_INVALID") from exc
    return {"config": config, "model": model, "evaluation": evaluation,
            "default_home_spreads": lines, "config_path": str(path),
            "config_file_sha256": _hash(path), "config_content_sha256": D.digest(config),
            "evaluation_content_sha256": D.digest(evaluation),
            "parent_model_path": str(parent_path), "parent_model": parent, "model_path": str(model_path),
            "evaluation_path": str(evaluation_path)}


def _validate_loaded(loaded):
    config, model, evaluation = loaded["config"], loaded["model"], loaded["evaluation"]
    _require(D.digest(config) == loaded["config_content_sha256"]
             and D.digest(evaluation) == loaded["evaluation_content_sha256"], "LOADED_CONFIG_MUTATED")
    F.validate_model(model)
    _require(D.digest(loaded["parent_model"]) == config["parent_model_artifact_sha256"], "PARENT_PACKED_MODEL_MISMATCH")
    _require(evaluation["status"] in {"HOLD", "PASS"}, "MARGIN_EVALUATION_STATUS")
    _require(evaluation.get("numerical_validity") == "PASS"
             and evaluation.get("execution_status") == "COMPLETED", "MARGIN_EVALUATION_EXECUTION_OR_NUMERICS_FAILED")
    _require(model["artifact_sha256"] == evaluation["model_artifact_sha256"], "MARGIN_EVALUATION_BINDING_MISMATCH")
    _require(config["parent_runtime_code_sha256"] == runtime_hashes(), "PARENT_RUNTIME_CODE_MISMATCH")
    return config, model, evaluation


def _regular_season(event):
    match = re.fullmatch(r"(\d{4})_(\d{2})_([A-Z0-9]+)_([A-Z0-9]+)", event["event_id"])
    _require(match is not None, "NFL_REGULAR_SEASON_EVENT_ID_REQUIRED")
    season, week = int(match[1]), int(match[2])
    _require(1920 <= season <= 2100 and 1 <= week <= (18 if season >= 2021 else 17), "NFL_REGULAR_SEASON_ONLY")
    _require(match[3] == event["away_team"] and match[4] == event["home_team"], "NFL_EVENT_TEAM_ID_MISMATCH")
    _require(event.get("game_type", "REG") == "REG", "NFL_REGULAR_SEASON_ONLY")
    for key, expected in (("season", season), ("week", week)):
        if key in event:
            _require(D.finite(event[key]) == expected, "NFL_EVENT_SEASON_WEEK_MISMATCH")
    return {"season": season, "week": week, "phase": "REGULAR_SEASON",
            "basis": "STRUCTURED_EVENT_ID_AND_OPTIONAL_GAME_TYPE"}


def _forecast_scope(forecast, config, parent_model):
    _require(isinstance(forecast, dict), "NFL_FORECAST_OBJECT_REQUIRED")
    try:
        _require(forecast["schema"] == "nfl.integrated_context_forecast.v1"
                 and forecast["model_id"] == PARENT_ID and forecast["selected_arm"] == "qb"
                 and forecast.get("mode", "research_pregame") == "research_pregame", "NFL_MARGIN_PARENT_MISMATCH")
        _require(forecast["market_input"] is False and forecast["action_authority"] is False,
                 "NFL_MARGIN_MARKET_OR_AUTHORITY")
        _require(forecast["model_artifact_sha256"] == config["parent_model_artifact_sha256"],
                 "FORECAST_PARENT_ARTIFACT_MISMATCH")
        _require(forecast["code_hashes"] == config["parent_runtime_code_sha256"], "FORECAST_PARENT_CODE_MISMATCH")
        D.source_hash(forecast["identity"])
        event = forecast["event"]
        for key in ("event_id", "home_team", "away_team"):
            D.identity(event[key], key.upper())
        _require(event["home_team"] != event["away_team"], "EVENT_TEAM_BINDING_INVALID")
        cutoff, start = D.stamp(forecast["cutoff_utc"]), D.stamp(event["start_time_utc"])
        _require(cutoff < start, "PARENT_CUTOFF_NOT_PREGAME")
        mean = D.finite(forecast["prediction"]["home_margin"])
        probability = D.finite(forecast["prediction"]["home_win"])
        _require(0 <= probability <= 1, "PARENT_WINNER_PROBABILITY_INVALID")
        features = forecast["features"]
        _require(isinstance(features, dict), "PARENT_FEATURE_OBJECT_REQUIRED")
        _regular_season(event)
        from .recovered_inference import predict
        parameters = parent_model["arms"]["qb"]
        used = {name: features[name] for name in parameters["feature_names"]}
        reconstructed = predict(parameters, used)
        for target, value in reconstructed["prediction"].items():
            _require(math.isclose(D.finite(forecast["prediction"][target]), value, rel_tol=1e-12, abs_tol=1e-10)
                     and math.isclose(D.finite(forecast["arms"]["qb"]["prediction"][target]), value,
                                      rel_tol=1e-12, abs_tol=1e-10), "PARENT_PREDICTION_REPLAY_MISMATCH")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("NFL_MARGIN_PARENT_STRUCTURE_INVALID") from exc
    return event, cutoff, start, mean, features


def build(forecast, loaded, home_spreads=None, *, n=100000, retrospective=False):
    """Generate a separate child from the explicit point head and fitted PMF."""
    _require(isinstance(retrospective, bool), "EXPLICIT_RETROSPECTIVE_BOOLEAN_REQUIRED")
    config, model, evaluation = _validate_loaded(loaded)
    event, cutoff, start, mean, features = _forecast_scope(forecast, config, loaded["parent_model"])
    clock = now()
    created, evaluated = D.stamp(model["created_at_utc"]), D.stamp(evaluation["created_at_utc"])
    configured = D.stamp(config["created_at_utc"])
    _require(max(cutoff, created, evaluated, configured) <= clock, "MARGIN_INPUT_FROM_FUTURE")
    if not retrospective:
        _require(clock < start, "NFL_MARGIN_POST_START_REQUIRES_RETROSPECTIVE")
        _require(max(created, evaluated, configured) <= cutoff, "MARGIN_ARTIFACT_AFTER_FORECAST_CUTOFF")
    lines = loaded["default_home_spreads"] if home_spreads is None else list(home_spreads)
    _require(bool(lines), "HOME_SPREAD_LIST_REQUIRED")
    required = (model["state"].get("scaling") or {}).get("features", [])
    scale = {}
    for name in required:
        if name == "absolute_parent_margin":
            scale[name] = abs(mean)
        elif name in features:
            scale[name] = D.finite(features[name])
        else:
            raise ValueError("SCALE_FEATURE_UNAVAILABLE:" + name)
    distribution = F.predict(model, mean=mean, event_id=event["event_id"], cutoff=forecast["cutoff_utc"],
                             start_time_utc=event["start_time_utc"], parent_model_id=PARENT_ID,
                             information_set=config["information_set"], parent_forecast_sha256=D.digest(forecast),
                             scale_features=scale)
    report = M.build_margin_report(distribution, home_spreads=lines, draws=n)
    draws, replay = M.simulate_margin(distribution, draws=n, home_spreads=lines)
    _require(D.digest(replay) == D.digest(report["simulation"]), "MARGIN_REPLAY_MISMATCH")
    contracts = []
    for analytic, simulation in zip(report["cover_ladder"], replay["cover_ladder"]):
        for side in ("home", "away"):
            states = analytic[side]
            ex_push = states["win"] / (1 - states["push"]) if states["push"] < 1 else None
            contracts.append({"team": event[side + "_team"], "side": side.upper(),
                              "handicap": analytic[side + "_spread"], "analytic": states,
                              "simulation": simulation[side], "cover_probability_basis": M.PROBABILITY_BASIS,
                              "conditional_nonpush_probability": ex_push,
                              "conditional_nonpush_label": "EXCLUDING_PUSHES" if ex_push is not None else None,
                              "line_role": "REQUESTED_HANDICAP_NOT_AUTHENTICATED_MARKET_QUOTE"})
    out = {"schema": REPORT_SCHEMA, "created_at_utc": clock.isoformat(), "event": copy.deepcopy(event),
           "mode": "RETROSPECTIVE_RECONSTRUCTION" if retrospective else "PREGAME_RESEARCH",
           "model_id": model["model_id"], "parent_model_id": PARENT_ID,
           "parent_forecast_sha256": D.digest(forecast), "parent_forecast_identity": forecast["identity"],
           "parent_cutoff_utc": forecast["cutoff_utc"], "parent_model_artifact_sha256": forecast["model_artifact_sha256"],
           "parent_runtime_code_sha256": copy.deepcopy(forecast["code_hashes"]),
           "parent_input_sha256": D.digest(features), "parent_assimilation_sha256": D.digest(forecast.get("assimilation")),
           "event_scope": _regular_season(event), "parent_prediction_replayed": True,
           "full_parent_runtime_identity_recomputed": False,
           "parent_identity_limitation": "FULL_IDENTITY_RECONSTRUCTION_REQUIRES_ORIGINAL_RUNTIME_CONTEXT; CALLER_OR_FROZEN_MANIFEST_BINDS_EVENT",
           "source_point_margin": mean, "parent_winner_probability_conditional_non_tie": forecast["prediction"]["home_win"],
           "parent_winner_is_separate_model_head": True,
           "config_file_sha256": loaded["config_file_sha256"], "config_created_at_utc": config["created_at_utc"],
           "configuration_existed_at_parent_cutoff": configured <= cutoff, "fitted_artifact_sha256": model["artifact_sha256"],
           "evaluation_file_sha256": config["evaluation"]["sha256"], "evaluation_status": evaluation["status"],
           "evaluation_created_at_utc": evaluation["created_at_utc"],
           "evaluation_numerical_validity": evaluation["numerical_validity"],
           "evaluation_execution_status": evaluation["execution_status"],
           "evaluated_model_artifact_sha256": evaluation.get("evaluated_model_artifact_sha256", model["artifact_sha256"]),
           "deployment_refit": copy.deepcopy(evaluation.get("deployment_refit")),
           "deployment_artifact_directly_evaluated": evaluation.get("evaluated_model_artifact_sha256", model["artifact_sha256"]) == model["artifact_sha256"],
           "fitted_artifact_created_at_utc": model["created_at_utc"],
           "fitted_artifact_existed_at_parent_cutoff": created <= cutoff,
           "evaluation_existed_at_parent_cutoff": evaluated <= cutoff,
           "computed_before_kickoff": clock < start, "distribution": distribution, "margin_report": report,
           "contracts": contracts, "total_probabilities": None, "joint_score_distribution": False,
           "original_forecast_mutated": False, "calibration_established": False,
           "prospective_grade_eligible": False, "action_authority": False,
           "status": "DIAGNOSTIC", "code_sha256": _hash(__file__),
           "warnings": ["RESEARCH_ONLY_NOT_PROVEN_CALIBRATION", "MARGIN_WINNER_DISTINCT_FROM_CONDITIONAL_BINARY_HEAD",
                        "NO_TOTAL_OR_JOINT_SCORE_DISTRIBUTION", "HISTORICAL_SOURCE_AVAILABILITY_UNPROVEN"]}
    if not out["deployment_artifact_directly_evaluated"]:
        out["warnings"].append("DEPLOYMENT_REFIT_IS_DISTINCT_FROM_HELDOUT_EVALUATED_ARTIFACT")
    if retrospective:
        out["warnings"].append("RETROSPECTIVE_NOT_AN_ORIGINAL_PREGAME_FORECAST")
    out["report_sha256"] = D.digest(out)
    validate(out, draws)
    return out, draws


def validate(report, draws):
    """Verify arithmetic and late/pregame labels before any artifact is published."""
    try:
        body = dict(report)
        expected = body.pop("report_sha256")
        _require(D.digest(body) == expected and report["schema"] == REPORT_SCHEMA, "NFL_MARGIN_REPORT_HASH")
        _require(report["action_authority"] is False and report["prospective_grade_eligible"] is False
                 and report["calibration_established"] is False and report["original_forecast_mutated"] is False
                 and report["status"] == "DIAGNOSTIC"
                 and report["evaluation_status"] in {"HOLD", "PASS"}
                 and report["evaluation_numerical_validity"] == "PASS"
                 and report["evaluation_execution_status"] == "COMPLETED", "NFL_MARGIN_RESEARCH_ONLY")
        _require(report["code_sha256"] == _hash(__file__), "NFL_MARGIN_ADAPTER_CODE_DRIFT")
        _require(report["deployment_artifact_directly_evaluated"] is
                 (report["fitted_artifact_sha256"] == report["evaluated_model_artifact_sha256"]), "NFL_MARGIN_EVALUATION_LABEL")
        _require(report["total_probabilities"] is None and report["joint_score_distribution"] is False,
                 "NFL_MARGIN_TOTAL_SCOPE")
        _require(report["event_scope"] == _regular_season(report["event"]) and report["parent_prediction_replayed"] is True, "NFL_MARGIN_EVENT_SCOPE")
        distribution, inner = report["distribution"], report["margin_report"]
        M.validate_report(inner, distribution)
        _require(distribution["league"] == "nfl" and distribution["settlement"] == SETTLEMENT
                 and distribution["model_id"] == report["model_id"]
                 and report["parent_model_id"] == PARENT_ID
                 and distribution["provenance"]["parent_model_id"] == PARENT_ID, "NFL_MARGIN_DISTRIBUTION_SCOPE")
        cutoff = D.stamp(report["parent_cutoff_utc"])
        start = D.stamp(report["event"]["start_time_utc"])
        created = D.stamp(report["created_at_utc"])
        existed = D.stamp(report["fitted_artifact_created_at_utc"]) <= cutoff
        evaluated = D.stamp(report["evaluation_created_at_utc"]) <= cutoff
        configured = D.stamp(report["config_created_at_utc"]) <= cutoff
        _require(max(D.stamp(report["fitted_artifact_created_at_utc"]), D.stamp(report["evaluation_created_at_utc"]), D.stamp(report["config_created_at_utc"])) <= created, "NFL_MARGIN_INPUT_FROM_FUTURE")
        _require(cutoff < start and cutoff <= created and report["computed_before_kickoff"] is (created < start)
                 and report["fitted_artifact_existed_at_parent_cutoff"] is existed
                 and report["evaluation_existed_at_parent_cutoff"] is evaluated
                 and report["configuration_existed_at_parent_cutoff"] is configured, "NFL_MARGIN_TIMING_LABEL")
        _require(report["mode"] in {"PREGAME_RESEARCH", "RETROSPECTIVE_RECONSTRUCTION"}, "NFL_MARGIN_MODE")
        if report["mode"] == "PREGAME_RESEARCH":
            _require(created < start and existed and evaluated and configured, "NFL_MARGIN_FALSE_PREGAME_LABEL")
        _require(distribution["provenance"]["parent_forecast_sha256"] == report["parent_forecast_sha256"]
                 and distribution["provenance"]["cutoff"] == report["parent_cutoff_utc"]
                 and distribution["provenance"]["event_id"] == report["event"]["event_id"]
                 and distribution["provenance"]["start_time_utc"] == report["event"]["start_time_utc"]
                 and distribution["provenance"]["fitted_artifact_sha256"] == report["fitted_artifact_sha256"]
                 and distribution["provenance"]["mean_input"] == report["source_point_margin"], "NFL_MARGIN_PARENT_BINDING")
        count = inner["simulation"]["receipt"]["count"]
        lines = [r["home_spread"] for r in inner["cover_ladder"]]
        replay, _ = M.simulate_margin(distribution, draws=count, home_spreads=lines)
        _require(np.asarray(draws).dtype == replay.dtype and np.array_equal(draws, replay), "NFL_MARGIN_DRAW_MISMATCH")
        _require(len(report["contracts"]) == len(lines) * 2, "NFL_MARGIN_CONTRACT_COUNT")
        for i, row in enumerate(report["contracts"]):
            side = "home" if i % 2 == 0 else "away"
            analytic, sim = inner["cover_ladder"][i // 2], inner["simulation"]["cover_ladder"][i // 2]
            states = analytic[side]
            ex_push = states["win"] / (1 - states["push"]) if states["push"] < 1 else None
            _require(row["side"] == side.upper() and row["team"] == report["event"][side + "_team"]
                     and row["handicap"] == analytic[side + "_spread"]
                     and D.digest(row["analytic"]) == D.digest(states)
                     and D.digest(row["simulation"]) == D.digest(sim[side])
                     and row["conditional_nonpush_probability"] == ex_push
                     and row["conditional_nonpush_label"] == ("EXCLUDING_PUSHES" if ex_push is not None else None)
                     and row["cover_probability_basis"] == M.PROBABILITY_BASIS, "NFL_MARGIN_CONTRACT_MISMATCH")
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError("NFL_MARGIN_REPORT_STRUCTURE_INVALID") from exc
    return expected


def persist(folder, report, draws):
    """Immutable child output with an actual completion-time pregame check."""
    validate(report, draws)
    folder = Path(folder)
    _require(not folder.exists(), "MARGIN_OUTPUT_ALREADY_EXISTS")
    if report["mode"] == "PREGAME_RESEARCH":
        _require(now() < D.stamp(report["event"]["start_time_utc"]), "START_CROSSED_BEFORE_MARGIN_PERSISTENCE")
    folder.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".margin-pending-", dir=folder.parent))
    try:
        (temporary / "margin_report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        np.save(temporary / "margin_draws.npy", draws, allow_pickle=False)
        receipt = {"created_at_utc": now().isoformat(), "type": "LOCAL_RESEARCH_MARGIN_ARTIFACT",
                   "mode": report["mode"], "information_cutoff_utc": report["parent_cutoff_utc"],
                   "parent_forecast_sha256": report["parent_forecast_sha256"], "report_sha256": report["report_sha256"],
                   "prospective_grade_eligible": False, "action_authority": False}
        receipt["record_hash"] = D.digest(receipt)
        (temporary / "registration.json").write_text(json.dumps(receipt, indent=2) + "\n")
        manifest = {p.name: _hash(p) for p in temporary.iterdir() if p.is_file()}
        (temporary / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        if report["mode"] == "PREGAME_RESEARCH":
            _require(now() < D.stamp(report["event"]["start_time_utc"]), "START_CROSSED_DURING_MARGIN_PERSISTENCE")
        _require(not folder.exists(), "MARGIN_OUTPUT_ALREADY_EXISTS")
        temporary.rename(folder)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return manifest


def read_frozen_forecast(folder):
    folder = Path(folder)
    manifest = _json(folder / "manifest.json")
    for name in ("forecast.json", "registration.jsonl"):
        _require(manifest.get(name) == _hash(folder / name), "FROZEN_FORECAST_MANIFEST_MISMATCH")
    forecast = _json(folder / "forecast.json")
    receipt = _json(folder / "registration.jsonl")
    body = dict(receipt)
    stored = body.pop("record_hash")
    _require(D.digest(body) == stored and receipt["forecast_identity"] == forecast["identity"], "FROZEN_FORECAST_RECEIPT_MISMATCH")
    _require(D.stamp(forecast["cutoff_utc"]) <= D.stamp(receipt["created_at_utc"]) < D.stamp(forecast["event"]["start_time_utc"]),
             "FROZEN_PARENT_NOT_CREATED_PREGAME")
    return forecast


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast-dir", type=Path, required=True)
    parser.add_argument("--margin-model", type=Path, required=True, help="Pinned margin configuration JSON")
    parser.add_argument("--home-spread", type=float, action="append")
    parser.add_argument("--simulations", type=int, default=100000)
    parser.add_argument("--retrospective", action="store_true", help="Explicit reconstruction; never original pregame registration")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    forecast = read_frozen_forecast(args.forecast_dir)
    report, draws = build(forecast, load_config(args.margin_model), args.home_spread,
                          n=args.simulations, retrospective=args.retrospective)
    persist(args.output, report, draws)
    print(json.dumps({"model_id": report["model_id"], "mode": report["mode"], "contracts": report["contracts"]}, indent=2))


if __name__ == "__main__":
    main()
