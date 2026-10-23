#!/usr/bin/env python3
"""Reproduce MI-002 before/after on real adapters with retained fixture identities.

Six model packages are synthetic fixtures adapted from PR74; NFL uses the saved
historical fitted QB artifact. No present-day forecast or predictive test is run.
Output contains source/package/draw hashes; temporary execution draws are cleaned
unless --retain-runs is supplied. No predictor is mocked.
"""
from __future__ import annotations
import argparse
import copy
import datetime as dt
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from pytest import MonkeyPatch
from models.nfl.contextual.recovered_inference import digest
from models.nfl.contextual.runtime import run
from pipelines.cards.selection import select
from pipelines.cards.semantic_identity import LEGACY, SEMANTIC, reidentify_nfl_run
from tests.semantic_identity_fixtures import package
from tests.test_semantic_identity import execute, numeric, nfl_inputs, QUOTES, LEAGUES
from tests.test_semantic_distribution_identity import full_chain
from tests.test_semantic_spread_identity import spread_twins
from models.common import discrete_research as D


def source_receipts():
    names = ["pipelines/cards/semantic_identity.py", "tests/semantic_identity_fixtures.py", "tests/test_semantic_identity.py",
             "pipelines/cards/distribution_research.py", "tests/test_semantic_distribution_identity.py",
             "tests/test_semantic_spread_identity.py", "models/nfl/contextual/spread_runtime.py",
             "models/nfl/contextual/spread_calibration.py", "data/nfl/spread_calibration_v1/runtime.json",
             "data/nfl/spread_calibration_v1/fit_01/model.json", "data/nfl/spread_calibration_v1/fit_01/evaluation.json",
             "models/common/discrete_research.py",
             "scripts/verify_semantic_identity.py", "data/model_selection/defaults_v1.json",
             "data/nfl/contextual_v1/model_packed.json", "data/nfl/contextual_v1/recovered_parameters.json",
             "data/nfl/contextual_v1/mnf_base_row.json", "data/nfl/contextual_v1/mnf_context_integrated.json",
             "data/nfl/contextual_v1/mnf_event.json"]
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}


def reproduce(folder):
    results = []
    with MonkeyPatch.context() as env:
        for league in LEAGUES:
            variants = {}
            for version in (LEGACY, SEMANTIC):
                rows = []
                for i, quote in enumerate(QUOTES):
                    p = package(league)
                    p["events"][0].update(market_quotes=copy.deepcopy(quote), display_metadata={"label": str(i)})
                    p["market_quotes"] = copy.deepcopy(quote)
                    raw, arrays = execute(p, folder / league / version / str(i), env, semantics=version)
                    rows.append({"source_package_sha256": digest(p), "model_state_config_hash": raw["model_state_config_hash"],
                        "numeric": numeric(raw), "retained_array_file_sha256": arrays,
                        "archival_parent_sha256": raw.get("diagnostics", {}).get("identity_provenance", {}).get("legacy_parent_forecast_sha256")})
                variants[version] = rows
            a, b = variants[LEGACY]; x, y = variants[SEMANTIC]
            assert a["retained_array_file_sha256"] != b["retained_array_file_sha256"]
            assert x["numeric"] == y["numeric"] and x["retained_array_file_sha256"] == y["retained_array_file_sha256"]
            results.append({"league": league, "fixture_scope": "SYNTHETIC_SOURCE_BOUND_CURRENT_PACKAGE_REAL_CODE_PINS_AND_ADAPTER",
                "draws_per_execution": 100000, "legacy_metadata_leak_reproduced": True,
                "v2_numeric_identity_draws_probabilities_invariant": True, "variants": variants})
    args = nfl_inputs(); variants = []
    for i, quote in enumerate(QUOTES):
        inputs = copy.deepcopy(args); inputs[4].update(market_quotes=quote, display_metadata=str(i))
        legacy, draws, scores = run(*inputs, 100000, model_id=select("nfl")["default_model_id"])
        child, child_draws, _ = reidentify_nfl_run(inputs[0], inputs[4], inputs[5], legacy, draws, scores, semantics=SEMANTIC)
        variants.append({"source_input_sha256": digest(inputs), "model_artifact_sha256": legacy["model_artifact_sha256"],
            "legacy_identity": legacy["identity"], "legacy_prediction": legacy["prediction"],
            "legacy_draw_sha256": hashlib.sha256(draws.tobytes()).hexdigest(),
            "v2_numerical_identity": child["numerical_identity"], "v2_prediction": child["prediction"],
            "v2_draw_sha256": hashlib.sha256(child_draws.tobytes()).hexdigest(),
            "v2_probability": child["winner_simulation"]["home_win_probability"]})
    a, b = variants
    assert a["legacy_draw_sha256"] != b["legacy_draw_sha256"] and a["legacy_prediction"] == b["legacy_prediction"]
    assert a["v2_numerical_identity"] == b["v2_numerical_identity"] and a["v2_draw_sha256"] == b["v2_draw_sha256"]
    results.append({"league": "nfl", "fixture_scope": "RETAINED_HISTORICAL_FITTED_QB_ARTIFACT_SYNTHETIC_METADATA_PERTURBATION",
                    "draws_per_execution": 100000, "legacy_metadata_leak_reproduced": True,
                    "v2_numeric_identity_draws_probabilities_invariant": True, "variants": variants})
    downstream = []
    with MonkeyPatch.context() as env:
        for league in LEAGUES + ("nfl",):
            cards, reports = full_chain(league, folder / "downstream" / league, env)
            variants = []
            for card, report in zip(cards, reports):
                result = report["results"][0]
                _, old = D.simulate(result["distribution"])
                variants.append({"parent_card_sha256": D.digest(card),
                    "distribution_sha256": result["distribution"]["distribution_sha256"],
                    "canonical_pmf_sha256": D.digest({k: result["distribution"][k] for k in ("support", "masses", "league", "product", "settlement")}),
                    "legacy_sampler": old, "v2_sampler": result["simulation"], "contract_probabilities": result["contracts"]})
            a, b = variants
            assert a["distribution_sha256"] != b["distribution_sha256"]
            assert a["canonical_pmf_sha256"] == b["canonical_pmf_sha256"]
            assert a["legacy_sampler"]["draw_sha256"] != b["legacy_sampler"]["draw_sha256"]
            assert a["v2_sampler"]["numerical_identity"] == b["v2_sampler"]["numerical_identity"]
            assert a["v2_sampler"]["draw_sha256"] == b["v2_sampler"]["draw_sha256"]
            assert a["contract_probabilities"] == b["contract_probabilities"]
            downstream.append({"league": league, "product": "margin", "residual_fixture_scope": "SYNTHETIC_FIT_NOT_VALIDATION",
                "legacy_pmf_provenance_seed_leak_reproduced": True, "v2_parent_to_pmf_to_draw_invariant": True, "variants": variants})
    spread = []
    for variant in spread_twins():
        child = variant["child"]
        spread.append({"calibrator_archive_sha256": variant["calibrator_archive_sha256"],
            "legacy_draw_sha256": child["identity_provenance"]["legacy_parent_draw_sha256"],
            "v2_numerical_identity": child["numerical_identity"], "v2_draw_sha256": variant["draw_sha256"],
            "contracts": child["contracts"]})
    assert spread[0]["legacy_draw_sha256"] != spread[1]["legacy_draw_sha256"]
    assert spread[0]["v2_numerical_identity"] == spread[1]["v2_numerical_identity"]
    assert spread[0]["v2_draw_sha256"] == spread[1]["v2_draw_sha256"]
    assert spread[0]["contracts"] == spread[1]["contracts"]
    report = {"schema": "sports.mi002_reproduction.v1", "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fixture_origin": {"repository": "georgemunoz1-ui/sports-model", "pr": 74,
            "commit": "d5ab18213253fb2c903a943f06d499fe547afc7d", "path": "tests/test_selected_market_independence.py",
            "git_blob": "7accd370573e441d60685ea55fb5da5d60209715", "adaptation": "Existing synthetic fixtures plus actual current-code pins"},
        "source_receipts": source_receipts(), "results": results, "downstream_results": downstream,
        "nfl_spread_overlay": {"fixture_scope": "AUTHENTIC_SAVED_CALIBRATOR_SYNTHETIC_METADATA_PERTURBATION",
            "legacy_calibrator_metadata_seed_leak_reproduced": True, "v2_numeric_identity_draws_probabilities_invariant": True,
            "variants": spread},
        "scope": "FIXED_FITTED_STATE_INPUT_PERTURBATION_NOT_FULL_REACQUISITION_REFIT_OR_PREDICTIVE_VALIDATION",
        "legacy_path_status": "MI002_REMAINS_OPEN_EXPLICIT_REPLAY_ONLY", "v2_path_status": "FIXED_STATE_METAMORPHIC_CHECKS_PASS",
        "unsupported_paths": ["NFL_MARKET_INFORMED_ENHANCED_LIVE", "MLB_LEGACY_STALE_PINNED_PACKAGE"],
        "predictive_validation": "NOT_ASSESSED", "action_authority": False}
    report["report_sha256"] = digest(report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retain-runs", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("REPRODUCTION_OUTPUT_ALREADY_EXISTS")
    if args.retain_runs:
        args.retain_runs.mkdir(parents=True, exist_ok=False)
        report = reproduce(args.retain_runs)
    else:
        with tempfile.TemporaryDirectory(prefix="mi002-reproduction-") as temp:
            report = reproduce(Path(temp))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as out:
        json.dump(report, out, sort_keys=True, indent=2, allow_nan=False); out.write("\n")
    print(json.dumps({"output": str(args.output), "leagues": len(report["results"]),
        "v2_fixed_state_checks": "PASS", "legacy_scope": report["legacy_path_status"], "report_sha256": report["report_sha256"]}))


if __name__ == "__main__":
    main()
