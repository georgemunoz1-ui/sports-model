"""Tests for scripts/build_wnba_margin_oof.py — SYNTHETIC fixtures only (no parquet).

The real regeneration reads staged parquet via the harness (pyarrow); that data-loading seam
(load_games/import_harness) is intentionally NOT exercised here. Everything downstream —
retained-bank handling, sign convention, reproduction gate, provenance, sigma integration,
ridge-head repack, hashing, append-only writes — is pure and tested here.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

import build_wnba_margin_oof as B
from models.common.margins.sigma import estimate_sigma
from pipelines.margins._shared import require_sigma, margin_from_ridge_head, MarginAdapterError


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------
def _bank_rows(n=320, seed=7):
    """Chronological synthetic retained bank via the module's own mini-league generator."""
    return B.retained_bank(B.synthetic_walk_forward_out(n=n, seed=seed))


def _self_consistent_reference(rows):
    s = B.bank_stats(rows)
    ref = dict(B.LEGACY_REFERENCE)
    ref.update({"n": s["n"], "mae": s["mae"], "sd": s["sd"], "record_id": "TEST-SYNTHETIC",
                "source_file": "(synthetic)", "record_sha256": "(synthetic)"})
    return ref


def _fit_dict(seed=11):
    return B.synthetic_fit_full(seed=seed)


def _x_rows(n=25, seed=21):
    rng = np.random.default_rng(seed)
    return [rng.normal(0, 1, len(B.FROZEN_FEATURES)) for _ in range(n)]


def _provenance(rows):
    return B.build_provenance(rows)


# ---------------------------------------------------------------------------
# 1-3. Sign convention
# ---------------------------------------------------------------------------
def test_residual_sign_convention_is_actual_minus_pred():
    rows = B.retained_bank({"d": ["2026-06-01", "2026-06-02"],
                            "m_pred": [3.0, -1.0], "m_act": [1.0, 4.0]})
    assert [r["residual"] for r in rows] == [-2.0, 5.0]  # actual - pred


def test_legacy_sign_conversion_flips_and_preserves_shape_stats():
    rng = np.random.default_rng(5)
    legacy = rng.normal(0.25, 12.0, 500)  # legacy .npy convention: pred - actual
    converted = B.convert_legacy_residuals(legacy)
    assert np.allclose(converted, -legacy)
    # MAE and sd are sign-invariant; mean bias flips sign
    assert np.isclose(np.mean(np.abs(converted)), np.mean(np.abs(legacy)))
    assert np.isclose(converted.std(ddof=0), legacy.std(ddof=0))
    assert np.isclose(converted.mean(), -legacy.mean())


def test_manifest_records_sign_conversion_explicitly():
    rows = _bank_rows()
    ref = _self_consistent_reference(rows)
    report = B.reproduction_check(rows, reference=ref)
    prov = _provenance(rows)
    sig = B.run_estimate_sigma(estimate_sigma, rows, prov)
    manifest = B.build_oof_manifest(rows, prov, report, sig)
    sc = manifest["sign_convention"]
    assert sc["emitted"] == "actual_minus_pred"
    assert sc["legacy_bank"] == "pred_minus_actual"
    assert "-1" in sc["conversion"]
    assert "sigma.py" in sc["canonical_definition"]


# ---------------------------------------------------------------------------
# 4-7. Chronology + provenance
# ---------------------------------------------------------------------------
def test_chronology_violation_fails_closed():
    bad = {"d": ["2026-06-02", "2026-06-01"], "m_pred": [1.0, 2.0], "m_act": [2.0, 1.0]}
    with pytest.raises(B.OofBuildError) as ei:
        B.retained_bank(bad)
    assert ei.value.code == B.OOF_CHRONOLOGY_VIOLATION


def test_empty_bank_fails_closed():
    with pytest.raises(B.OofBuildError) as ei:
        B.retained_bank({"d": [], "m_pred": [], "m_act": []})
    assert ei.value.code == B.OOF_BANK_EMPTY


def test_provenance_block_schema_and_window():
    rows = _bank_rows()
    prov = B.build_provenance(rows)
    assert prov["sport"] == "wnba"
    assert prov["oof"] is True
    assert prov["window_start"] == rows[0]["date"]
    assert prov["window_end"] == rows[-1]["date"]
    assert prov["window_start"] <= prov["window_end"]
    for key in ("sport", "oof", "window_start", "window_end"):
        assert key in prov


# ---------------------------------------------------------------------------
# 8-10. Reproduction gate
# ---------------------------------------------------------------------------
def test_legacy_reference_constants_match_verified_measurement():
    # Static pin against data/wnba/model/wnba_margin_sd_measurement.json
    assert B.LEGACY_REFERENCE["n"] == 1721
    assert B.LEGACY_REFERENCE["mae"] == 9.881
    assert B.LEGACY_REFERENCE["sd"] == 12.5523
    assert B.LEGACY_REFERENCE["tolerance"] == 0.01


def test_reproduction_check_passes_on_self_consistent_reference():
    rows = _bank_rows()
    report = B.reproduction_check(rows, reference=_self_consistent_reference(rows))
    assert report["passed"] is True
    assert report["observed"]["n"] == len(rows)


def test_reproduction_check_fails_on_tampered_mae():
    rows = _bank_rows()
    ref = _self_consistent_reference(rows)
    ref["mae"] = ref["mae"] + 0.5  # far beyond the 0.01 tolerance
    with pytest.raises(B.OofBuildError) as ei:
        B.reproduction_check(rows, reference=ref)
    assert ei.value.code == B.OOF_REPRODUCTION_MISMATCH


def test_reproduction_check_fails_on_wrong_n():
    rows = _bank_rows()
    ref = _self_consistent_reference(rows)
    ref["n"] = ref["n"] + 1
    with pytest.raises(B.OofBuildError) as ei:
        B.reproduction_check(rows, reference=ref)
    assert ei.value.code == B.OOF_REPRODUCTION_MISMATCH


def test_reproduction_check_elementwise_legacy_npy():
    rows = _bank_rows()
    resid_actual_minus_pred = np.array([r["residual"] for r in rows])
    legacy_npy = -resid_actual_minus_pred  # stored legacy convention: pred - actual
    report = B.reproduction_check(rows, reference=_self_consistent_reference(rows),
                                  legacy_residuals_pred_minus_actual=legacy_npy)
    assert report["elementwise_vs_legacy_npy"] is True
    tampered = legacy_npy.copy()
    tampered[0] += 1.0
    with pytest.raises(B.OofBuildError) as ei:
        B.reproduction_check(rows, reference=_self_consistent_reference(rows),
                             legacy_residuals_pred_minus_actual=tampered)
    assert ei.value.code == B.OOF_REPRODUCTION_MISMATCH


# ---------------------------------------------------------------------------
# 11-13. Sigma estimation + require_sigma compatibility
# ---------------------------------------------------------------------------
def test_estimate_sigma_integration_verbatim_output():
    rows = _bank_rows()
    prov = _provenance(rows)
    sig = B.run_estimate_sigma(estimate_sigma, rows, prov)
    resid = np.array([r["residual"] for r in rows])
    assert sig["n"] == len(rows)
    assert np.isclose(sig["sigma"], resid.std(ddof=1))
    assert np.isclose(sig["mean_bias"], resid.mean())
    assert sig["label_in_sample"] is False
    assert sig["sport"] == "wnba"
    assert sig["sigma"] > 0


def test_estimate_sigma_rejects_non_oof_provenance():
    pred = np.zeros(300)
    actual = np.random.default_rng(1).normal(0, 1, 300)
    with pytest.raises(ValueError) as ei:
        estimate_sigma(pred, actual, provenance={"sport": "wnba"})  # no oof/window
    assert "SIGMA_REQUIRES_CHRONOLOGICAL_OOF" in str(ei.value)


def test_sigma_provenance_block_is_require_sigma_compatible():
    rows = _bank_rows()
    prov = _provenance(rows)
    sig = B.run_estimate_sigma(estimate_sigma, rows, prov)
    block = B.sigma_provenance_block(sig, prov)
    sigma = require_sigma(block, "wnba")
    assert sigma == pytest.approx(sig["sigma"])
    assert sigma > 0


def test_require_sigma_rejects_in_sample_or_windowless():
    rows = _bank_rows()
    prov = _provenance(rows)
    sig = B.run_estimate_sigma(estimate_sigma, rows, prov)
    bad_insample = dict(B.sigma_provenance_block(sig, prov)); bad_insample["label_in_sample"] = True
    with pytest.raises(MarginAdapterError) as ei:
        require_sigma(bad_insample, "wnba")
    assert ei.value.code == "SIGMA_PROVENANCE_NOT_OOF"
    bad_window = B.sigma_provenance_block(sig, prov); del bad_window["window_end"]
    with pytest.raises(MarginAdapterError) as ei2:
        require_sigma(bad_window, "wnba")
    assert ei2.value.code == "SIGMA_PROVENANCE_NOT_OOF"
    bad_sport = B.sigma_provenance_block(sig, prov)
    with pytest.raises(MarginAdapterError) as ei3:
        require_sigma(bad_sport, "nba")
    assert ei3.value.code == "SIGMA_SPORT_MISMATCH"


# ---------------------------------------------------------------------------
# 14-16. Ridge-head repack
# ---------------------------------------------------------------------------
def test_head_repack_b2b_passthrough_and_schema():
    head = B.repack_ridge_head(_fit_dict())
    assert set(head) == {"impute", "mean", "scale", "coefficient", "intercept"}
    assert len(head["coefficient"]) == len(B.FROZEN_FEATURES) == 7
    assert len(head["mean"]) == len(head["scale"]) == len(head["impute"]) == 7
    assert head["mean"][6] == 0.0 and head["scale"][6] == 1.0  # b2b_edge never standardized


def test_head_coefficient_order_matches_frozen_features():
    fit = {"mu": np.zeros(6), "sd": np.ones(6),
           "bmar": np.array([100.0, 1, 2, 3, 4, 5, 6, 7], float)}
    head = B.repack_ridge_head(fit)
    assert head["coefficient"] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    assert head["intercept"] == 100.0
    # feature at position i in FROZEN_FEATURES multiplies coefficient[i]
    x = np.zeros(7); x[3] = 2.0  # orb_edge
    assert head["coefficient"][3] == 4.0
    assert B.head_predict(head, x) == pytest.approx(100.0 + 8.0)


def test_head_numeric_equivalence_with_harness_bmar():
    fit = _fit_dict()
    head = B.repack_ridge_head(fit)
    x_rows = _x_rows()
    worst = B.verify_head_numeric(head, fit, x_rows)
    assert worst <= 1e-9
    # and the adapter's own consumer agrees on raw features
    raw = B.xs_to_raw(np.asarray(x_rows[0]), fit["mu"], fit["sd"])
    assert margin_from_ridge_head(head, list(raw)) == pytest.approx(B.head_predict(head, raw))


def test_head_schema_mismatch_fails_closed():
    fit = {"mu": np.zeros(6), "sd": np.ones(6), "bmar": np.zeros(6)}  # too short
    with pytest.raises(B.OofBuildError) as ei:
        B.repack_ridge_head(fit)
    assert ei.value.code == B.OOF_HEAD_SCHEMA_MISMATCH


# ---------------------------------------------------------------------------
# 17-19. Hashing, governance labels, append-only
# ---------------------------------------------------------------------------
def test_hash_stability_deterministic_payload():
    rows1 = _bank_rows()
    rows2 = _bank_rows()
    prov1, prov2 = _provenance(rows1), _provenance(rows2)
    sig1 = B.run_estimate_sigma(estimate_sigma, rows1, prov1)
    sig2 = B.run_estimate_sigma(estimate_sigma, rows2, prov2)
    rep1 = B.reproduction_check(rows1, reference=_self_consistent_reference(rows1))
    rep2 = B.reproduction_check(rows2, reference=_self_consistent_reference(rows2))
    m1 = B.build_oof_manifest(rows1, prov1, rep1, sig1)
    m2 = B.build_oof_manifest(rows2, prov2, rep2, sig2)
    assert m1["payload_sha256"] == m2["payload_sha256"]
    assert B.canonical_json(m1) == B.canonical_json(m2)  # fully deterministic bytes


def test_research_only_labels_on_both_artifacts(tmp_path):
    rows = _bank_rows()
    res = B.build_and_emit(rows, _fit_dict(), estimate_sigma=estimate_sigma,
                           out_dir=str(tmp_path),
                           reference=_self_consistent_reference(rows),
                           head_check_rows=_x_rows())
    for art in (res["manifest"], res["head_artifact"]):
        assert art["research_only"] is True
        assert art["action_authority"] is False
        assert "RESEARCH_ONLY_NO_ACTION_AUTHORITY" in art["limitations"]
    # and the on-disk bytes parse back to the same labeled artifacts
    on_disk = json.load(open(res["oof_path"]))
    assert on_disk["research_only"] is True and on_disk["action_authority"] is False
    assert on_disk["payload_sha256"] == res["manifest"]["payload_sha256"]


def test_append_only_refuses_overwrite_but_allows_identical(tmp_path):
    p = os.path.join(str(tmp_path), "artifact.json")
    assert B.write_append_only(p, '{"a": 1}\n') == "written"
    assert B.write_append_only(p, '{"a": 1}\n') == "unchanged"
    with pytest.raises(B.OofBuildError) as ei:
        B.write_append_only(p, '{"a": 2}\n')
    assert ei.value.code == B.OOF_ARTIFACT_IMMUTABLE


# ---------------------------------------------------------------------------
# 20. Selftest end-to-end
# ---------------------------------------------------------------------------
def test_selftest_passes(tmp_path):
    assert B.selftest(out_dir=str(tmp_path)) is True
