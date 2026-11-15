"""Bounded source replay for the three retained November 10 CFB forecasts.

The source package and active draw files are independently retained byte versions.
This helper verifies existing predictions and draws and never executes a sampler.
Original NumPy identity metadata remains 2.3.5 when read by another NumPy version.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

from models.current.cfb import feature_row
from models.current.common import current
from models.current.linear import predict
from models.nfl.contextual.recovered_inference import digest, utc
from pipelines.cards.selection import require_default
from pipelines.cards.semantic_identity import _components

REPO = Path(__file__).resolve().parents[2]
PACKAGE_SHA256 = "d615f27c490f0c6c39849f6f2dc7124efef6f52ec2461f894e9bc1cc4ff03e69"
CUTOFF = "2026-11-10T13:43:45.596253+00:00"
SEMANTICS = "market_blind_numeric.v2"
DRAW_COUNT = 150000
TOLERANCE = 1e-12
SELECTION_HASH = "dfef8b94709ad5a1d47d4f652c67ab18813f51c232fc6ea50f2e864dd139b8e9"
ADDITIONAL_CODE_PINS = {
    "models/nfl/contextual/recovered_inference.py":
        "ac70b26355c8a9fe0850caf6e69ec268f363363dffb3b1289cbee13d4d729abd",
    "pipelines/cards/semantic_identity.py":
        "a7f6541d1415523092e9e6364407100ceb9165de1493e833c93d21f88e65f756",
}
ACTIVE_DRAW_FILES = {
    "CFB:401866459": "ac54b1eda681c4539c173a814f86f0aa4101dba61677e9cdf861e01fdbb2f681",
    "CFB:401866458": "012aa94b382e82c15d38eb12195dc880d67f0f17ee4218763c4b70bf1d93222b",
    "CFB:401866460": "b3316328b3346743f5400b405fe08855f71f621a089529ae8317910c880d270d",
}
HEAD_FIELDS = ("kind", "impute", "mean", "scale", "coefficient", "intercept")


def _load(path):
    return json.loads(Path(path).read_bytes())


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _exact(actual, expected, name):
    if digest(actual) != digest(expected):
        raise ValueError("CFB_SOURCE_BINDING:" + name)


def _number(actual, expected, name):
    if (type(actual) not in (int, float) or not math.isfinite(actual)
            or not math.isclose(actual, expected, rel_tol=TOLERANCE, abs_tol=TOLERANCE)):
        raise ValueError("CFB_SOURCE_BINDING:" + name)


def verify_cfb(root, verification_inputs):
    """Verify a recovered bundle against the retained verification-input directory."""
    root, verification_inputs = Path(root), Path(verification_inputs)
    package_path = verification_inputs / "cfb-package.json"
    _exact(_sha(package_path), PACKAGE_SHA256, "source_package_version")
    package = _load(package_path)
    for name, expected in {**package["code_pins"], **ADDITIONAL_CODE_PINS}.items():
        _exact(_sha(REPO / name), expected, "native_code:" + name)
    _exact(digest({"model": package["fitted_model"], "state": package["team_state"],
                   "parameters": package["parameters"]}), package["model_sha256"], "model_state")

    card = _load(root / "cfb/diagnostic_card.json")
    for key, expected in {"league": "CFB", "card_date": "2026-11-10", "as_of_utc": CUTOFF,
                          "forecast_count": 3, "scheduled_game_count": 3,
                          "simulation_count": DRAW_COUNT, "authority": "SHADOW_ONLY"}.items():
        _exact(card[key], expected, "card_" + key)
    _exact(card["package_binding"], {"date": "2026-11-10", "league": "cfb",
                                    "sha256": PACKAGE_SHA256}, "card_package")
    current(package, CUTOFF)
    events = {event["event_id"]: event for event in package["events"]
              if event["slate_date"] == card["card_date"]}
    _exact(set(events) == set(ACTIVE_DRAW_FILES), True, "source_event_population")
    _exact(sorted(row["event_id"] for row in card["forecasts"]), sorted(events), "card_event_population")
    if not utc(CUTOFF) <= utc(card["generated_at_utc"]) < min(utc(e["start_time_utc"]) for e in events.values()):
        raise ValueError("CFB_SOURCE_BINDING:card_chronology")

    model = {target: {key: package["fitted_model"][target][key] for key in HEAD_FIELDS}
             for target in ("winner", "margin")}
    model["transform_code"] = {name: _sha(REPO / name) for name in (
        "models/current/linear.py", "models/nfl/contextual/recovered_inference.py", "models/current/cfb.py")}
    verified = []
    for row in card["forecasts"]:
        event = events[row["event_id"]]
        for key in ("event_id", "home_team", "away_team", "start_time_utc"):
            _exact(row[key], event[key], key)
        features = feature_row(package["team_state"], event, package["parameters"])
        _exact(list(features), package["feature_names"], "native_feature_order")
        _exact(row["model_input_snapshot"], features, "native_features")
        _exact(row["input_snapshot_hash"], digest(features), "feature_hash")
        _exact(row["model_state_config_hash"], package["model_sha256"], "row_model_state")
        _exact(row["model_id"], package["model_id"], "model_id")

        values = [features[key] for key in package["feature_names"]]
        home_probability = predict(package["fitted_model"]["winner"], values)
        home_margin = predict(package["fitted_model"]["margin"], values)
        home_selected = home_probability >= 0.5
        selected_probability = home_probability if home_selected else 1 - home_probability
        _exact(row["model_winner"], event["home_team" if home_selected else "away_team"], "winner_label")
        for key in ("model_p", "analytic_p"):
            _number(row[key], selected_probability, key)
        _number(row["projected_margin"], home_margin if home_selected else -home_margin, "point_margin")
        _number(row["diagnostics"]["home_win"], home_probability, "diagnostic_home_probability")
        _number(row["diagnostics"]["home_margin"], home_margin, "diagnostic_home_margin")
        _number(row["grading"]["analytic_p_home"], home_probability, "grading_home_probability")
        for key in ("projected_total", "projected_home_points", "projected_away_points",
                    "projected_home_runs", "projected_away_runs", "margin_std", "total_std"):
            _exact(row[key], None, key)
        _exact(row["diagnostics"]["total"], None, "diagnostic_total")
        _exact(row["diagnostics"]["package_sha256"], PACKAGE_SHA256, "diagnostic_package")
        _exact(row["diagnostics"]["model_lineage"], package["model_lineage"], "model_lineage")
        _exact(row["provenance"]["source_fetches"], package["source_fetches"], "source_fetches")

        selection = require_default("cfb", package["model_id"], week=event["week"], division=event["division_scope"])
        _exact(selection["policy_sha256"], SELECTION_HASH, "selection_version")
        _exact(row["selection_hash"], SELECTION_HASH, "selection_hash")
        _exact(row["diagnostics"]["default_selection"], selection, "selection_record")
        components = _components("cfb", package["model_id"], features, feature_configuration={
            "regress": package["parameters"]["regress"], "hfa": package["parameters"]["hfa"]})
        identity = {
            "schema": "sports.numeric_stochastic_identity.v2", "semantics": SEMANTICS,
            "league": "cfb", "event_id": event["event_id"], "start_time_utc": utc(event["start_time_utc"]).isoformat(),
            "cutoff_utc": CUTOFF, "model_id": package["model_id"], "feature_sha256": digest(features),
            "fitted_state_sha256": digest(model), "feature_procedure_id": components["feature"]["procedure_id"],
            "calibration_procedure_id": components["calibration"]["procedure_id"], "draw_count": DRAW_COUNT,
            "engine": "BERNOULLI_WINNER_DIAGNOSTIC", "numpy_version": "2.3.5",
            "semantic_runtime_sha256": ADDITIONAL_CODE_PINS["pipelines/cards/semantic_identity.py"],
        }
        identity["identity_sha256"] = digest(identity)
        _exact(row["numerical_identity"], identity, "numerical_identity")
        _exact(row["identity_semantics"], SEMANTICS, "identity_semantics")
        _exact(row["forecast_procedure_id"], package["model_id"] + ":" + SEMANTICS, "forecast_procedure")
        for key in ("feature_procedure_id", "calibration_procedure_id"):
            _exact(row[key], identity[key], key)

        # Archive-relative active files take precedence over display-only absolute paths.
        directory = root / "cfb/draws" / (event["event_id"].replace(":", "_") + ".semantic-v2")
        _exact(_load(directory / "numeric_inputs.json"), {
            "features": features, "fitted_state": model, "numerical_identity": identity}, "active_numeric_inputs")
        provenance = _load(directory / "identity_provenance.json")
        _exact(row["diagnostics"]["identity_provenance"], provenance, "identity_provenance")
        _exact(provenance["identity_components"], components, "procedure_components")
        _exact(provenance["legacy_package_sha256"], digest(package), "parent_package")
        _exact(provenance["legacy_input_snapshot_hash"], digest(features), "parent_features")
        _exact(provenance["legacy_model_state_config_hash"], package["model_sha256"], "parent_model_state")
        _exact(provenance["legacy_parent_forecast_sha256"], digest(_load(directory / "legacy_parent_forecast.json")), "parent_record")
        manifest = _load(directory / "manifest.json")
        expected_files = ("identity_provenance.json", "legacy_parent_forecast.json", "numeric_inputs.json", "winner_draws.npy")
        _exact(manifest, {name: _sha(directory / name) for name in expected_files}, "active_manifest")
        _exact(_sha(directory / "winner_draws.npy"), ACTIVE_DRAW_FILES[event["event_id"]], "active_draw_version")
        draws = np.load(directory / "winner_draws.npy", allow_pickle=False)
        if draws.dtype != np.uint8 or draws.shape != (DRAW_COUNT,) or not np.isin(draws, [0, 1]).all():
            raise ValueError("CFB_SOURCE_BINDING:active_draw_encoding")
        simulated_home = float(draws.mean())
        simulated_selected = simulated_home if home_selected else 1 - simulated_home
        raw_hash = hashlib.sha256(draws.tobytes()).hexdigest()
        binary = row["simulation"]["binary"]
        _exact(binary["count"], DRAW_COUNT, "simulation_count")
        _exact(binary["sha256"], raw_hash, "simulation_raw_hash")
        _exact(row["simulation"]["draw_sha256"], {"winner_draws": raw_hash}, "simulation_hashes")
        _exact(binary["seed"], int(digest({"id": identity["identity_sha256"],
                                          "kind": identity["engine"], "n": DRAW_COUNT})[:16], 16), "simulation_seed")
        _number(binary["home_win_probability"], simulated_home, "simulation_home_probability")
        _number(binary["mc_standard_error_pp"], 100 * math.sqrt(home_probability * (1 - home_probability) / DRAW_COUNT), "simulation_error")
        _exact(binary["scope"], "BINARY_NON_TIE_DIAGNOSTIC_NOT_INDEPENDENT_MODEL_VALIDATION", "simulation_scope")
        _exact(row["simulation"]["joint_scores"], None, "joint_scores")
        for key in ("sim_p", "stochastic_sim_p"):
            _number(row[key], simulated_selected, key)
        _number(row["grading"]["stochastic_sim_p_home"], simulated_home, "grading_simulation")
        gap = 100 * (selected_probability - simulated_selected)
        _number(row["analytic_sim_gap_pp"], gap, "analytic_simulation_gap")
        _number(row["analytic_sim_abs_gap_pp"], abs(gap), "absolute_analytic_simulation_gap")
        for key, expected in {"action_authority": False, "action_status": "SHADOW_ONLY",
                              "forecast_status": "FORECAST_GENERATED", "probability_estimator": "ANALYTIC_AND_SIMULATION",
                              "spread_or_runline": "UNSUPPORTED_BY_TIER", "total_market": "UNSUPPORTED_BY_TIER"}.items():
            _exact(row[key], expected, key)
        _number(row["dose"], 0, "exposure")
        verified.append({"event_id": event["event_id"], "home_probability": home_probability,
                         "home_point_margin": home_margin, "simulated_home_probability": simulated_home,
                         "active_draw_file_sha256": ACTIVE_DRAW_FILES[event["event_id"]]})

    return {"status": "PASS_SOURCE_BOUND_REPLAY", "source_package_sha256": PACKAGE_SHA256,
            "events": verified, "analytic_heads_verified": 6, "retained_active_draws_verified": 3 * DRAW_COUNT,
            "new_draws_generated": 0, "numeric_relative_and_absolute_tolerance": TOLERANCE,
            "source_authentication": "RETAINED_PACKAGE_BYTES", "action_authority": False}
