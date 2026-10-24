"""Opt-in numeric RNG identity; legacy core files and package pins stay intact.

V2 is a separately identified stochastic execution, not a fitted-model promotion.
It retains the parent run and uses explicit consumed-input/model allowlists. Full
package/forecast hashes remain archival, never seed inputs. Market-aware NFL modes
and legacy MLB packages are deliberately outside this independent-model boundary.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np

from models.nfl.contextual.recovered_inference import digest, utc, bernoulli_simulation, predict

LEGACY = "legacy.v1"
SEMANTIC = "market_blind_numeric.v2"
SEMANTICS = (LEGACY, SEMANTIC)
ROOT = Path(__file__).resolve().parents[2]
_HEAD = ("kind", "impute", "mean", "scale", "coefficient", "intercept")
_NFL_HEAD = ("impute", "center", "scale", "coefficient", "intercept")
_ALLOWED = {
    "cfb": {"cfb.fbs.elo_form_logit_ridge.v1_0.shadow", "cfb.fbs.elo_context_logit.v1_0.week1_shadow"},
    "wnba": {"wnba.rs.ff7_logit_ridge.v1_0.shadow"},
    "mlb": {"mlb.v13.current_input.research.v1"},
    **{l: {f"{l}.initial_causal_score.research.v1"} for l in ("nba", "nhl", "mls")},
}


def _check(semantics):
    if semantics not in SEMANTICS:
        raise ValueError("UNKNOWN_STOCHASTIC_IDENTITY_SEMANTICS")


def _pick(mapping, fields):
    return {key: copy.deepcopy(mapping[key]) for key in fields}


def _code(paths):
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in paths}


def _components(league, model_id, features, *, feature_configuration=None):
    """Source-bound executed procedures, including explicit no-posthoc stage.

    These are observed research identities, not validation registry entries.
    Do not replace absence with an invented calibrated-probability claim.
    """
    if league == "nfl":
        feature_paths = ["models/nfl/contextual/" + name + ".py" for name in
            ("runtime", "features", "recovered_inference", "personnel", "weekly_state", "qb_assimilation")]
        prediction_paths = ["models/nfl/contextual/runtime.py", "models/nfl/contextual/recovered_inference.py"]
    elif league == "wnba":
        feature_paths = ["models/current/wnba.py", "harness/wnba_model_v1.py"]
        prediction_paths = feature_paths + ["harness/ml_regression.py", "models/current/common.py"]
    elif league == "mlb":
        feature_paths = ["models/current/mlb.py", "harness/run_v13_historical.py", "engine/hfa.py"]
        prediction_paths = feature_paths + ["pipelines/cards/adapters/mlb.py"]
    else:
        feature_paths = ["models/current/cfb.py" if league == "cfb" else "models/current/baseline.py"]
        prediction_paths = feature_paths + ["models/current/linear.py", "models/current/common.py"]
    def contract(value):
        return {k: contract(v) for k, v in value.items()} if isinstance(value, dict) else "CONSUMED_SCALAR"
    feature = {"schema": "sports.observed_feature_procedure.v1", "league": league, "model_id": model_id,
        "ordered_feature_names": list(features), "feature_contract": contract(features),
        "constructor_code_sha256": _code(feature_paths),
        "feature_configuration": feature_configuration or {}, "validation_status": "NOT_ASSESSED"}
    calibration = {"schema": "sports.observed_calibration_procedure.v1", "league": league, "model_id": model_id,
        "stage": "NONE_NO_SEPARATE_FITTED_POSTHOC_CALIBRATOR_IN_SELECTED_PATH",
        "observed_prediction_code_sha256": _code(prediction_paths),
        "retained_numeric_operations": "WNBA_ROUND_P_4DP_MARGIN_2DP_TOTAL_1DP" if league == "wnba" else "SELECTED_HEAD_OR_SIMULATION_TRANSFORM_UNCHANGED",
        "validation_status": "NOT_ASSESSED"}
    return {"feature": {**feature, "procedure_id": digest(feature)},
            "calibration": {**calibration, "procedure_id": digest(calibration)}}


def _identity(league, event, cutoff, model_id, features, model, n, engine, components):
    if type(n) is not int or not 1 <= n <= 1000000:
        raise ValueError("DRAW_COUNT_RANGE")
    if not isinstance(event.get("event_id"), str) or not event["event_id"]:
        raise ValueError("EVENT_ID_REQUIRED")
    material = {"schema": "sports.numeric_stochastic_identity.v2", "semantics": SEMANTIC,
                "league": league, "event_id": event["event_id"],
                "start_time_utc": utc(event["start_time_utc"]).isoformat(),
                "cutoff_utc": utc(cutoff).isoformat(), "model_id": model_id,
                "feature_sha256": digest(features), "fitted_state_sha256": digest(model),
                "feature_procedure_id": components["feature"]["procedure_id"],
                "calibration_procedure_id": components["calibration"]["procedure_id"],
                "draw_count": n, "engine": engine,
                "numpy_version": np.__version__,
                "semantic_runtime_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    # Event IDs are the stable target key. Presentation labels/quotes are excluded.
    material["identity_sha256"] = digest(material)
    return material


def _provenance(parent, package=None):
    return {"legacy_parent_forecast_sha256": digest(parent),
            "legacy_parent_identity": parent.get("identity"),
            "legacy_input_snapshot_hash": parent.get("input_snapshot_hash"),
            "legacy_model_state_config_hash": parent.get("model_state_config_hash"),
            "legacy_package_sha256": digest(package) if package is not None else None,
            "legacy_draw_directory": (parent.get("simulation") or {}).get("draw_directory"),
            "interpretation": "Full provenance retained separately; none of these archive hashes seeds v2.",
            "predictive_validation": "NOT_ASSESSED", "action_authority": False}


def _decorate(result, identity, provenance, components):
    result["identity_semantics"] = SEMANTIC
    result["numerical_identity"] = identity
    result["forecast_procedure_id"] = result["model_id"] + ":" + SEMANTIC
    result["feature_procedure_id"] = identity["feature_procedure_id"]
    result["calibration_procedure_id"] = identity["calibration_procedure_id"]
    provenance["identity_components"] = copy.deepcopy(components)
    result["action_authority"] = False
    result.setdefault("warnings", []).append("VERSIONED_RNG_IDENTITY_REPAIR_NOT_PREDICTIVE_PROMOTION")
    result.setdefault("diagnostics", {})["identity_provenance"] = provenance


def validate_numeric_parent(row, *, league, cutoff):
    """Verify explicit v2 identity/target bindings; never upgrade a legacy row.

    This validates retained identity integrity, not fitted-model certification or
    whether upstream acquisition/training was market-free.
    """
    if row.get("identity_semantics") != SEMANTIC:
        raise ValueError("SEMANTIC_NUMERIC_PARENT_REQUIRED")
    identity = row.get("numerical_identity") or {}
    if (not isinstance(identity, dict)
            or identity.get("schema") != "sports.numeric_stochastic_identity.v2"
            or identity.get("semantics") != SEMANTIC
            or identity.get("identity_sha256") != digest({k: v for k, v in identity.items() if k != "identity_sha256"})):
        raise ValueError("SEMANTIC_NUMERIC_PARENT_HASH_MISMATCH")
    if any(not isinstance(v, str) for v in
           (identity.get("cutoff_utc"), cutoff, identity.get("start_time_utc"), row.get("start_time_utc"))):
        raise ValueError("SEMANTIC_NUMERIC_PARENT_TARGET_MISMATCH")
    if (identity.get("league") != league
            or identity.get("event_id") != row["event_id"]
            or identity.get("model_id") != row["model_id"]
            or utc(identity["cutoff_utc"]) != utc(cutoff)
            or utc(identity["start_time_utc"]) != utc(row["start_time_utc"])
            or row.get("forecast_procedure_id") != row["model_id"] + ":" + SEMANTIC
            or any(row.get(key) != identity.get(key) for key in ("feature_procedure_id", "calibration_procedure_id"))):
        raise ValueError("SEMANTIC_NUMERIC_PARENT_TARGET_MISMATCH")
    return identity


def simulate_distribution(distribution, row, cutoff, *, draws=100000):
    """Sample an explicitly v2 parent's validated PMF without provenance seeds.

    The full distribution and parent hashes remain archive receipts. The numeric
    PMF, target, parent numeric identity and sampler code define the new child.
    Existing fitted artifacts retain their original code-pin admission checks.
    """
    from models.common import discrete_research as D
    if type(draws) is not int or not 1 <= draws <= 1000000:
        raise ValueError("DRAW_COUNT_RANGE")
    x, p = D.validate(distribution)
    parent = validate_numeric_parent(row, league=distribution["league"], cutoff=cutoff)
    provenance = distribution["provenance"]
    if not isinstance(provenance, dict) or not isinstance(provenance.get("cutoff"), str):
        raise ValueError("SEMANTIC_DISTRIBUTION_TARGET_MISMATCH")
    if (provenance.get("event_id") != row["event_id"]
            or utc(provenance["cutoff"]) != utc(cutoff)):
        raise ValueError("SEMANTIC_DISTRIBUTION_TARGET_MISMATCH")
    if provenance.get("parent_forecast_sha256") is not None and provenance["parent_forecast_sha256"] != D.digest(row):
        raise ValueError("SEMANTIC_DISTRIBUTION_PARENT_MISMATCH")
    numeric = {"schema": "sports.numeric_pmf_identity.v2", "semantics": SEMANTIC,
        "parent_numeric_identity_sha256": parent["identity_sha256"],
        "league": distribution["league"], "product": distribution["product"],
        "settlement": distribution["settlement"], "support": x.tolist(), "masses": p.tolist(),
        "draw_count": draws, "rng": "numpy.PCG64", "numpy_version": np.__version__,
        "sampler_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "distribution_core_sha256": D.code_hash()}
    numeric["identity_sha256"] = D.digest(numeric)
    seed = int(numeric["identity_sha256"][:16], 16)
    values = np.random.Generator(np.random.PCG64(seed)).choice(x, size=draws, p=p).astype("<i8")
    return values, {"count": draws, "seed": seed, "rng": "numpy.PCG64", "numpy_version": np.__version__,
        "identity_semantics": SEMANTIC, "numerical_identity": numeric,
        "simulation_code_sha256": numeric["sampler_code_sha256"], "encoding": "little_endian_int64",
        "draw_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
        "worst_case_mc_se_pp": 100 * math.sqrt(.25 / draws),
        "archive_distribution_sha256": distribution["distribution_sha256"],
        "archive_parent_forecast_sha256": D.digest(row),
        "predictive_validation": "NOT_ASSESSED", "action_authority": False}


def build_spread_overlay(forecast, scores, home_handicaps, *, n=100000,
                         semantics=LEGACY, model=None, evaluation=None):
    """Versioned child of the existing admitted NFL spread overlay.

    The old constructor still checks parent artifact, target and score-array
    receipts. Its full output is retained. Only v2 stochastic identity changes;
    fitted coefficients, raw/calibrated exact probabilities and gates do not.
    """
    from models.nfl.contextual import spread_runtime as R
    from models.nfl.contextual import spread_calibration as C
    _check(semantics)
    if semantics == LEGACY:
        return R.build_overlay(forecast, scores, home_handicaps, n=n, model=model, evaluation=evaluation)
    if type(n) is not int or not 1 <= n <= 1000000:
        raise ValueError("DRAW_COUNT_RANGE")
    if model is None:
        model, evaluation = R.load_calibrator()
    parent_overlay, parent_draws = R.build_overlay(forecast, scores, home_handicaps, n=n,
                                                  model=model, evaluation=evaluation)
    row = {**forecast["event"], **{key: forecast[key] for key in
        ("model_id", "identity_semantics", "numerical_identity", "forecast_procedure_id",
         "feature_procedure_id", "calibration_procedure_id")}}
    parent = validate_numeric_parent(row, league="nfl", cutoff=forecast["cutoff_utc"])
    values = np.asarray(scores)
    margins = values[:, 0].astype(np.int64) - values[:, 1].astype(np.int64)
    support, mass = C.margin_distribution(margins)
    cm, cw = C.calibrated_distribution(support, mass, model["intercept"], model["slope"])
    calibrator = {"schema": "sports.observed_calibration_procedure.v1", "league": "nfl",
        "model_id": model["model_id"], "reference_model_id": model["reference_model_id"],
        "stage": "FITTED_LOGISTIC_CDF_RECALIBRATION", "intercept": float(model["intercept"]),
        "slope": float(model["slope"]), "target": "FINAL_HOME_MARGIN_INCLUDING_OVERTIME",
        "observed_prediction_code_sha256": _code(["models/nfl/contextual/spread_calibration.py",
                                                   "models/nfl/contextual/spread_runtime.py"]),
        "validation_status": "EXISTING_RESEARCH_STATUS_UNCHANGED_NO_NEW_CERTIFICATION"}
    calibrator["procedure_id"] = digest(calibrator)
    numeric = {"schema": "nfl.numeric_calibrated_spread_identity.v2", "semantics": SEMANTIC,
        "parent_numeric_identity_sha256": parent["identity_sha256"],
        "source_score_draw_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
        "calibration_procedure_id": calibrator["procedure_id"], "support": cm.tolist(), "masses": cw.tolist(),
        "target": "FINAL_HOME_MARGIN_INCLUDING_OVERTIME", "draw_count": n,
        "rng": "numpy.PCG64", "numpy_version": np.__version__,
        "semantic_runtime_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    numeric["identity_sha256"] = digest(numeric)
    draws, summary = C.simulate_margins(cm, cw, int(numeric["identity_sha256"][:16], 16), n)
    dm, dw = C.margin_distribution(draws)
    child = copy.deepcopy(parent_overlay)
    for contract in child["contracts"]:
        home_line = contract["handicap"] if contract["side"] == "HOME" else -contract["handicap"]
        contract["calibrated_simulation"] = C.price_spread(dm, dw, home_line, side=contract["side"])
    child["simulation"] = summary
    child["identity_semantics"] = SEMANTIC
    child["numerical_identity"] = numeric
    child["identity"] = numeric["identity_sha256"]
    child["calibration_procedure_id"] = calibrator["procedure_id"]
    child["identity_provenance"] = {"legacy_parent_overlay_sha256": digest(parent_overlay),
        "legacy_parent_draw_sha256": hashlib.sha256(parent_draws.tobytes()).hexdigest(),
        "calibrator_archive_sha256": digest(model), "legacy_parent_overlay": parent_overlay,
        "identity_components": {"calibration": calibrator},
        "predictive_validation": "NOT_ASSESSED", "action_authority": False}
    child["warnings"].append("VERSIONED_RNG_IDENTITY_REPAIR_NOT_PREDICTIVE_PROMOTION")
    return child, draws


def _current_material(league, event, context, raw):
    p = context["package"]
    if p.get("schema") != "sports.current_research_package.v1" or raw.get("model_id") not in _ALLOWED.get(league, set()):
        raise ValueError("SEMANTIC_IDENTITY_UNSUPPORTED_PACKAGE_OR_MODEL")
    snapshot = raw["model_input_snapshot"]
    if league == "mlb":
        features = {"away_starter": _pick(snapshot["sp_away"], ("era", "gs", "k", "bb")),
                    "home_starter": _pick(snapshot["sp_home"], ("era", "gs", "k", "bb")),
                    "away_form": _pick(snapshot["away_form"], ("rf", "ra")),
                    "home_form": _pick(snapshot["home_form"], ("rf", "ra")),
                    "park_factor": snapshot["park_factor"]}
        # V13 is a frozen formula, not a fitted parameter dictionary. Its actual
        # engine/HFA bytes define the numeric state; metadata-bearing pins do not.
        model = {"engine_code": _code(["harness/run_v13_historical.py", "engine/hfa.py"])}
        return features, model, "FROZEN_V13_GAMMA_POISSON_AND_TIE_PROXY"
    if league == "wnba":
        fields = ("net", "efg", "tov", "orb", "ftr", "rest", "b2b", "pace")
        league_state = snapshot["league_state"]
        if (not isinstance(league_state, (list, tuple)) or len(league_state) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in league_state)):
            raise ValueError("WNBA_NUMERIC_LEAGUE_STATE_REQUIRED")
        features = {"home": _pick(snapshot["home"], fields), "away": _pick(snapshot["away"], fields),
                    "league_state": dict(zip(("total_points_sum", "game_count", "pace_sum"), league_state))}
        model = _pick(p["fitted_model"], ("mu", "sd", "blog", "bmar", "tmu", "tsd", "btot"))
        model["transform_code"] = _code(["harness/wnba_model_v1.py", "harness/ml_regression.py", "models/nfl/contextual/recovered_inference.py"])
    else:
        from models.current.baseline import FEATURES
        names = p["feature_names"] if league == "cfb" else FEATURES
        features = _pick(snapshot, names)
        required = ("home_goals", "away_goals") if league == "mls" else (("winner", "margin") if league == "cfb" else ("winner", "margin", "total"))
        model = {target: _pick(p["fitted_model"][target], _HEAD) for target in required}
        model["transform_code"] = _code(["models/current/linear.py", "models/nfl/contextual/recovered_inference.py",
                                          "models/current/cfb.py" if league == "cfb" else "models/current/baseline.py"])
    return features, model, "INDEPENDENT_POISSON_REGULATION" if league == "mls" else "BERNOULLI_WINNER_DIAGNOSTIC"


def reidentify_nfl_run(artifact, event, cutoff, result, winner, scores, *, semantics=LEGACY):
    """Return a child NFL bundle/arrays; legacy returns exact original objects.

    The caller can persist through the normal runtime. All existing feature/PIT
    admission and capability checks have already run; no admission is bypassed.
    """
    _check(semantics)
    if semantics == LEGACY:
        return result, winner, scores
    if result.get("mode", "research_pregame") != "research_pregame" or result.get("market_input") is not False:
        raise ValueError("SEMANTIC_IDENTITY_INDEPENDENT_NFL_PREGAME_ONLY")
    selected = result["selected_arm"]
    params = artifact["arms"][selected]
    if params["model_id"] != result["model_id"]:
        raise ValueError("SEMANTIC_NFL_SELECTED_MODEL_MISMATCH")
    if (result.get("model_artifact_sha256") != digest(artifact)
            or result.get("event", {}).get("event_id") != event.get("event_id")
            or utc(result["cutoff_utc"]) != utc(cutoff)
            or utc(result["event"]["start_time_utc"]) != utc(event["start_time_utc"])):
        raise ValueError("SEMANTIC_NFL_PARENT_BINDING_MISMATCH")
    n = len(winner)
    features = _pick(result["features"], params["feature_names"])
    if predict(params, features)["prediction"] != result["prediction"]:
        raise ValueError("SEMANTIC_NFL_PARENT_PREDICTION_MISMATCH")
    if (n != result["winner_simulation"]["count"]
            or hashlib.sha256(np.asarray(winner).tobytes()).hexdigest() != result["winner_simulation"]["sha256"]):
        raise ValueError("SEMANTIC_NFL_PARENT_DRAW_MISMATCH")
    if selected == "combined" and (scores is None or len(scores) != result["score_simulation"]["n"]
            or hashlib.sha256(np.asarray(scores).tobytes()).hexdigest() != result["score_simulation"]["sha256"]):
        raise ValueError("SEMANTIC_NFL_PARENT_SCORE_DRAW_MISMATCH")
    model = {"feature_names": copy.deepcopy(params["feature_names"]),
             "heads": {target: _pick(head, _NFL_HEAD) for target, head in params["heads"].items()},
             "engine_code": _code(["models/nfl/contextual/recovered_inference.py", "models/nfl/contextual/model.py"])}
    if selected == "combined":
        model.update(residual_pairs=copy.deepcopy(artifact["final_score_residuals"]), tie_rate=artifact["simulation_v2"]["tie_rate"])
    components = _components("nfl", result["model_id"], features, feature_configuration={"selected_arm": selected})
    identity = _identity("nfl", event, cutoff, result["model_id"], features, model, n,
                         "NFL_BINARY_AND_COMBINED_JOINT_KERNEL" if selected == "combined" else "BERNOULLI_WINNER_DIAGNOSTIC", components)
    child = copy.deepcopy(result); p = child["prediction"]
    draws, summary = bernoulli_simulation(p["home_win"], identity["identity_sha256"], n)
    child["winner_simulation"] = summary
    score_draws = None
    if selected == "combined":
        from models.nfl.contextual.model import simulate_joint
        score_draws, child["score_simulation"] = simulate_joint(p["home_margin"], p["total_points"], p["home_win"],
            artifact["final_score_residuals"], artifact["simulation_v2"]["tie_rate"], identity["identity_sha256"], n)
    elif scores is not None:
        raise ValueError("UNEXPECTED_SELECTED_SCORE_SAMPLER")
    archive = _provenance(result)
    archive["legacy_winner_draw_sha256"] = hashlib.sha256(np.asarray(winner).tobytes()).hexdigest()
    archive["legacy_score_draw_sha256"] = hashlib.sha256(np.asarray(scores).tobytes()).hexdigest() if scores is not None else None
    child["identity"] = identity["identity_sha256"]
    _decorate(child, identity, archive, components)
    child["identity_provenance"] = copy.deepcopy(archive)
    return child, draws, score_draws


def _persist_child(event, raw, child, arrays, features, model):
    output = os.environ.get("SPORTS_RESEARCH_DRAW_OUTPUT")
    if not output:
        raise ValueError("SPORTS_RESEARCH_DRAW_OUTPUT_REQUIRED_FOR_SEMANTIC_CHILD")
    folder = Path(output) / (event["event_id"].replace(":", "_") + ".semantic-v2")
    folder.mkdir(parents=True, exist_ok=False)
    for name, values in arrays.items():
        np.save(folder / (name + ".npy"), values, allow_pickle=False)
    payloads = {"legacy_parent_forecast.json": raw,
                "numeric_inputs.json": {"features": features, "fitted_state": model, "numerical_identity": child["numerical_identity"]},
                "identity_provenance.json": child["diagnostics"]["identity_provenance"]}
    for name, value in payloads.items():
        (folder / name).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")
    manifest = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in folder.iterdir()}
    (folder / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    child["simulation"]["draw_directory"] = str(folder)
    child["simulation"]["draw_sha256"] = {name: hashlib.sha256(np.asarray(a).tobytes()).hexdigest() for name, a in arrays.items()}


def forecast_with_identity(adapter, event, context, simulations=100000, *, semantics=LEGACY, **forecast_kwargs):
    """Execute the real adapter, then optionally retain a numeric-identity child."""
    _check(semantics)
    if semantics == SEMANTIC and forecast_kwargs.get("mode", "research_pregame") != "research_pregame":
        raise ValueError("SEMANTIC_IDENTITY_INDEPENDENT_NFL_PREGAME_ONLY")
    if semantics == SEMANTIC and not os.environ.get("SPORTS_RESEARCH_DRAW_OUTPUT"):
        raise ValueError("SPORTS_RESEARCH_DRAW_OUTPUT_REQUIRED_FOR_SEMANTIC_CHILD")
    raw = adapter.forecast_event(event, context, simulations, **forecast_kwargs)
    if semantics == LEGACY:
        return raw
    league = context["package"].get("league") or ("nfl" if adapter.__name__.endswith(".nfl") else None)
    if league == "nfl":
        parent = raw["diagnostics"]
        # Reconstruct the already executed parent arrays from its exact identity;
        # no probability is refitted or inferred from displayed percentages.
        pw, _ = bernoulli_simulation(parent["prediction"]["home_win"], parent["identity"], simulations)
        ps = None
        if parent["selected_arm"] == "combined":
            from models.nfl.contextual.model import simulate_joint
            p = parent["prediction"]; artifact = context["model"]
            ps, _ = simulate_joint(p["home_margin"], p["total_points"], p["home_win"], artifact["final_score_residuals"],
                artifact["simulation_v2"]["tie_rate"], parent["identity"], simulations)
        bundle, draws, scores = reidentify_nfl_run(context["model"], event, context["cutoff"], parent, pw, ps, semantics=semantics)
        child = copy.deepcopy(raw); child["diagnostics"] = bundle
        home = bundle["prediction"]["home_win"] >= .5
        child["sim_p"] = child["stochastic_sim_p"] = bundle["winner_simulation"]["home_win_probability"] if home else 1 - bundle["winner_simulation"]["home_win_probability"]
        child["simulation"] = {"binary": bundle["winner_simulation"], "joint_scores": bundle["score_simulation"]}
        identity = bundle["numerical_identity"]
        components = bundle["identity_provenance"]["identity_components"]
        arrays = {"winner_draws": draws}
        if scores is not None:
            arrays["score_draws"] = scores
        features = _pick(bundle["features"], context["model"]["arms"][bundle["selected_arm"]]["feature_names"])
        model = {"fitted_state_sha256": identity["fitted_state_sha256"]}
    else:
        features, model, engine = _current_material(league, event, context, raw)
        p = context["package"]
        feature_configuration = (_pick(p["parameters"], ("regress", "hfa")) if league == "cfb" else
                                 {"prior": p["prior"]} if league in {"nba", "nhl", "mls"} else {})
        components = _components(league, raw["model_id"], features, feature_configuration=feature_configuration)
        identity = _identity(league, event, context["cutoff"], raw["model_id"], features, model, simulations, engine, components)
        child = copy.deepcopy(raw); seed = int(identity["identity_sha256"][:16], 16)
        if league == "mlb":
            import sys
            sys.path.insert(0, str(ROOT / "harness"))
            import run_v13_historical as V
            from pipelines.cards.adapters.mlb import capture_sim
            f = features
            sim, arrays = capture_sim(V, f["away_starter"], f["home_starter"], f["away_form"]["rf"], f["away_form"]["ra"],
                f["home_form"]["rf"], f["home_form"]["ra"], f["park_factor"], seed, simulations)
            home = sim["p_home"] >= .5; prob = sim["p_home"] if home else 1 - sim["p_home"]
            child.update(model_winner=event["home_team"] if home else event["away_team"], model_p=prob,
                         sim_p=prob, stochastic_sim_p=prob, projected_home_runs=sim["proj_home"], projected_away_runs=sim["proj_away"])
            child["diagnostics"]["sim_home_win"] = sim["p_home"]
            child["simulation"] = {"count": simulations, "seed": seed, "home_win_probability": sim["p_home"], "mc_standard_error": sim["mc_se"]}
        elif league == "mls":
            h, a = raw["projected_home_points"], raw["projected_away_points"]
            rng = np.random.default_rng(seed); hd, ad = rng.poisson(h, simulations), rng.poisson(a, simulations)
            counts = np.array([(ad > hd).sum(), (ad == hd).sum(), (hd > ad).sum()]) / simulations
            index = int(np.argmax(raw["diagnostics"]["analytic_probabilities"]))
            child["sim_p"] = child["stochastic_sim_p"] = float(counts[index])
            child["diagnostics"]["simulation_probabilities"] = counts.tolist()
            child["simulation"] = {"count": simulations, "seed": seed, "joint_scores": "INDEPENDENT_POISSON_REGULATION"}
            arrays = {"home_goals": hd, "away_goals": ad}
        else:
            p = raw["diagnostics"]["home_win"]
            draws, summary = bernoulli_simulation(p, identity["identity_sha256"], simulations)
            child["sim_p"] = child["stochastic_sim_p"] = summary["home_win_probability"] if p >= .5 else 1 - summary["home_win_probability"]
            child["simulation"] = {"binary": summary, "joint_scores": None}
            arrays = {"winner_draws": draws}
    _decorate(child, identity, _provenance(raw, context["package"]), components)
    _persist_child(event, raw, child, arrays, features, model)
    return child
