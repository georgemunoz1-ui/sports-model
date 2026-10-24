"""Authentic saved NFL calibrator, synthetic perturbations, no promotion test."""
import copy
import hashlib

import numpy as np
import pytest

from models.nfl.contextual.runtime import run
from models.nfl.contextual.spread_runtime import load_calibrator, build_overlay
from models.nfl.contextual.recovered_inference import digest
from pipelines.cards.semantic_identity import SEMANTIC, build_spread_overlay, reidentify_nfl_run
from tests.test_semantic_identity import nfl_inputs, QUOTES


def combined_parent(quote=None):
    args = nfl_inputs()
    if quote:
        args[4]["market_quotes"] = quote
    parent, w, s = run(*args, 100000, model_id=args[0]["arms"]["combined"]["model_id"])
    return reidentify_nfl_run(args[0], args[4], args[5], parent, w, s, semantics=SEMANTIC)


def spread_twins():
    model, evaluation = load_calibrator()
    variants = []
    for i, quote in enumerate(QUOTES):
        parent, _, scores = combined_parent(quote)
        m = copy.deepcopy(model); m.update(market_quotes=quote, display_label=str(i))
        child, draws = build_spread_overlay(parent, scores, [-3., -2.5, 0.], model=m,
                                           evaluation=evaluation, semantics=SEMANTIC)
        variants.append({"child": child, "draw_sha256": hashlib.sha256(draws.tobytes()).hexdigest(),
                         "calibrator_archive_sha256": digest(m)})
    return variants


def test_authentic_calibrator_metadata_changes_archive_not_numeric_identity():
    a, b = spread_twins()
    assert a["calibrator_archive_sha256"] != b["calibrator_archive_sha256"]
    assert a["child"]["identity_provenance"]["legacy_parent_draw_sha256"] != b["child"]["identity_provenance"]["legacy_parent_draw_sha256"]
    assert a["child"]["numerical_identity"] == b["child"]["numerical_identity"]
    assert a["draw_sha256"] == b["draw_sha256"]
    assert a["child"]["contracts"] == b["child"]["contracts"]
    assert a["child"]["calibration_procedure_id"] == b["child"]["calibration_procedure_id"]
    assert not a["child"]["calibration_reliability_established"]


def test_calibrator_coefficient_changes_numeric_child_and_exact_probabilities():
    parent, _, scores = combined_parent()
    model, evaluation = load_calibrator(); changed = copy.deepcopy(model); changed["intercept"] += .15
    outputs = [build_spread_overlay(parent, scores, [-3.], model=m, evaluation=evaluation, semantics=SEMANTIC) for m in (model, changed)]
    a, ad = outputs[0]; b, bd = outputs[1]
    assert a["numerical_identity"] != b["numerical_identity"] and not np.array_equal(ad, bd)
    assert a["contracts"][0]["calibrated"] != b["contracts"][0]["calibrated"]
    assert a["contracts"][0]["raw"] == b["contracts"][0]["raw"]


def test_legacy_overlay_replay_and_existing_admission_preserved():
    parent, _, scores = combined_parent(); model, evaluation = load_calibrator()
    a, ad = build_overlay(parent, scores, [-3.], model=model, evaluation=evaluation)
    b, bd = build_spread_overlay(parent, scores, [-3.], model=model, evaluation=evaluation)
    assert a["simulation"] == b["simulation"] and np.array_equal(ad, bd)
    assert "identity_semantics" not in b
    before = copy.deepcopy(parent); bad = scores.copy(); bad[0, 0] += 1
    with pytest.raises(ValueError, match="SAVED_SCORE_ARRAY_HASH_MISMATCH"):
        build_spread_overlay(parent, bad, [-3.], model=model, evaluation=evaluation, semantics=SEMANTIC)
    assert parent == before


def test_requested_lines_are_diagnostics_and_do_not_change_spread_draws():
    parent, _, scores = combined_parent(); model, evaluation = load_calibrator()
    a, ad = build_spread_overlay(parent, scores, [-3.], model=model, evaluation=evaluation, semantics=SEMANTIC)
    b, bd = build_spread_overlay(parent, scores, [-9., 2.5], model=model, evaluation=evaluation, semantics=SEMANTIC)
    assert a["numerical_identity"] == b["numerical_identity"] and np.array_equal(ad, bd)
