"""Adapter tests for pipelines/margins (per-sport margin adapters).

Fixtures mimic the real repo output shapes:
  * NFL: models/nfl/contextual/runtime.run result bundle
    (schema nfl.integrated_context_forecast.v1; arms[arm]['prediction']
    with a home_margin ridge head; selected_arm top-level + diagnostics).
  * CFB: ridge margin point prediction + a week-segmented sigma table.
  * MLB: paired simulated final scores from the Gamma-Poisson MC engine.
  * NHL: output dict of the existing separate (uncalibrated) margin model.
  * NBA/WNBA: margin_pred or frozen ridge head + features.
  * MLS: 1X2 forecast dict from models/current/baseline.py.
"""
from __future__ import annotations

import copy

import numpy as np
import pytest
from scipy.stats import norm

from models.common.margins import estimate_sigma, validate_record
from pipelines.margins import (
    ARM_NOT_SELECTED_CONSISTENT,
    MARGIN_POOL_MODEL_MISMATCH,
    MISSING_MARGIN_HEAD,
    SEGMENT_FALLBACK,
    SIGMA_PROVENANCE_NOT_OOF,
    SIGMA_SEGMENT_MISSING,
    SIGMA_SPORT_MISMATCH,
    UNSUPPORTED_1X2_ONLY,
    UNSUPPORTED_SETTLEMENT,
    MarginAdapterError,
    UnsupportedProductError,
    get_adapter,
    leagues,
)
from pipelines.margins import cfb, mlb, mls, nba, nfl, nhl, wnba

EVENT = {"event_id": "TEST:EVT:1", "home_team": "HOME", "away_team": "AWAY"}
SHA = "ab" * 32
SIGMA_PROV = {
    "sport": "nfl",
    "sigma": 13.5,
    "window_start": "2021-01-01",
    "window_end": "2025-12-31",
    "oof": True,
    "n": 1200,
}
# Compliant OOF provenance for the basketball adapters (estimate_sigma
# contract: sport + sigma + oof=True + window_start/window_end).
NBA_SIGMA_PROV = {
    "sport": "nba",
    "sigma": 12.0,
    "window_start": "2019-10-01",
    "window_end": "2025-06-30",
    "oof": True,
    "n": 2400,
}
WNBA_SIGMA_PROV = {
    "sport": "wnba",
    "sigma": 11.0,
    "window_start": "2019-05-01",
    "window_end": "2025-09-30",
    "oof": True,
    "n": 900,
}


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def nfl_result(selected="qb", margin=3.2, other_margin=-1.0):
    arms = {}
    for arm in ("base", "qb", "availability", "travel", "combined"):
        arms[arm] = {
            "prediction": {
                "home_win": 0.55,
                "home_margin": margin if arm == selected else other_margin,
                "total_points": 44.5,
            }
        }
    return {
        "schema": "nfl.integrated_context_forecast.v1",
        "model_id": f"nfl.integrated_context.{selected}.v1.research",
        "model_artifact_sha256": SHA,
        "selected_arm": selected,
        "diagnostics": {"selected_arm": selected},
        "event": dict(EVENT),
        "arms": arms,
        "prediction": dict(arms[selected]["prediction"]),
        "score_simulation": {
            "status": "UNAVAILABLE_FOR_SELECTED_ARM",
            "reason": "FROZEN_JOINT_RESIDUAL_POOL_IS_COMBINED_SPECIFIC",
        },
        "warnings": ["EMPIRICAL_SCORE_SETTLEMENT_UNVALIDATED"],
    }


def cfb_sigma_table(with_fallback=True):
    table = {
        "buckets": [
            {"label": "early", "week_min": 2, "week_max": 5, "sigma": 12.5, "n": 400,
             "window_start": "2021-01-01", "window_end": "2025-01-01", "oof": True},
            {"label": "late", "week_min": 6, "week_max": 16, "sigma": 11.0, "n": 900,
             "window_start": "2021-01-01", "window_end": "2025-01-01", "oof": True},
        ],
    }
    if with_fallback:
        table["fallback"] = {"label": "pooled", "sigma": 12.0, "n": 2000, "oof": True}
    return table


def mlb_scores(n=12000, seed=7):
    rng = np.random.default_rng(seed)
    home = rng.poisson(4.6, n)
    away = rng.poisson(3.9, n)
    return home, away


RIDGE_HEAD = {
    "impute": [0.0, 0.0],
    "mean": [1.0, 2.0],
    "scale": [2.0, 4.0],
    "coefficient": [0.5, -0.25],
    "intercept": 3.0,
}


# ---------------------------------------------------------------------------
# NFL
# ---------------------------------------------------------------------------
class TestNFL:
    def test_happy_path_record_valid(self):
        rec = nfl.nfl_cover(nfl_result(), -3.5, sigma_provenance=dict(SIGMA_PROV))
        assert validate_record(rec) is True
        assert rec["schema"] == "sports.margin_quote.v1"
        assert rec["research_only"] is True and rec["action_authority"] is False
        probs = rec["probabilities"]
        assert probs["p_cover"] + probs["p_push"] + probs["p_loss"] == pytest.approx(1.0)
        assert rec["source_model"]["model_id"] == "nfl.integrated_context.qb.v1.research"

    def test_uses_selected_arm_own_margin_head(self):
        res = nfl_result(selected="qb", margin=3.2, other_margin=-9.0)
        rec_qb = nfl.nfl_cover(res, 0.0, sigma_provenance=dict(SIGMA_PROV))
        assert rec_qb["probabilities"]["p_cover"] > 0.5  # +3.2 mean margin
        res_base = nfl_result(selected="base", margin=-9.0, other_margin=3.2)
        rec_base = nfl.nfl_cover(res_base, 0.0, sigma_provenance=dict(SIGMA_PROV))
        assert rec_base["probabilities"]["p_cover"] < 0.5
        assert rec_qb["distribution_id"] != rec_base["distribution_id"]

    def test_combined_pool_with_qb_model_id_refused(self):
        prov = dict(SIGMA_PROV, pool_arm="combined")
        with pytest.raises(MarginAdapterError, match=MARGIN_POOL_MODEL_MISMATCH):
            nfl.nfl_cover(nfl_result(selected="qb"), -3.5, sigma_provenance=prov)

    def test_combined_pool_detected_via_residual_source_string(self):
        prov = dict(SIGMA_PROV, residual_source="FROZEN_JOINT_RESIDUAL_POOL_IS_COMBINED_SPECIFIC")
        with pytest.raises(MarginAdapterError, match=MARGIN_POOL_MODEL_MISMATCH):
            nfl.nfl_cover(nfl_result(selected="qb"), -3.5, sigma_provenance=prov)

    def test_combined_pool_allowed_when_combined_selected(self):
        prov = dict(SIGMA_PROV, pool_arm="combined")
        rec = nfl.nfl_cover(nfl_result(selected="combined"), -3.5, sigma_provenance=prov)
        assert validate_record(rec) is True

    def test_missing_margin_head(self):
        res = nfl_result()
        del res["arms"]["qb"]["prediction"]["home_margin"]
        del res["prediction"]["home_margin"]
        with pytest.raises(MarginAdapterError, match=MISSING_MARGIN_HEAD):
            nfl.nfl_cover(res, -3.5, sigma_provenance=dict(SIGMA_PROV))

    def test_arm_selection_conflict(self):
        res = nfl_result()
        res["diagnostics"]["selected_arm"] = "qb"
        res["selected_arm"] = "base"
        with pytest.raises(MarginAdapterError, match=ARM_NOT_SELECTED_CONSISTENT):
            nfl.nfl_cover(res, -3.5, sigma_provenance=dict(SIGMA_PROV))

    def test_arm_selection_missing(self):
        res = nfl_result()
        del res["selected_arm"]
        del res["diagnostics"]["selected_arm"]
        with pytest.raises(MarginAdapterError, match=ARM_NOT_SELECTED_CONSISTENT):
            nfl.nfl_cover(res, -3.5, sigma_provenance=dict(SIGMA_PROV))

    def test_top_level_prediction_mismatch(self):
        res = nfl_result(selected="qb", margin=3.2)
        res["prediction"]["home_margin"] = -1.0  # not the qb arm's head output
        with pytest.raises(MarginAdapterError, match=ARM_NOT_SELECTED_CONSISTENT):
            nfl.nfl_cover(res, -3.5, sigma_provenance=dict(SIGMA_PROV))

    def test_integer_vs_half_point_push(self):
        rec_int = nfl.nfl_cover(nfl_result(), -3.0, sigma_provenance=dict(SIGMA_PROV))
        rec_half = nfl.nfl_cover(nfl_result(), -3.5, sigma_provenance=dict(SIGMA_PROV))
        assert rec_int["probabilities"]["p_push"] > 0.0
        assert "EXCLUDING_PUSHES" in rec_int["probabilities"]["labels"]
        assert rec_half["probabilities"]["p_push"] == 0.0

    def test_sigma_sport_mismatch_refused(self):
        prov = dict(SIGMA_PROV, sport="nba")
        with pytest.raises(MarginAdapterError, match=SIGMA_SPORT_MISMATCH):
            nfl.nfl_cover(nfl_result(), -3.5, sigma_provenance=prov)

    def test_input_not_mutated(self):
        res = nfl_result()
        frozen = copy.deepcopy(res)
        prov = dict(SIGMA_PROV)
        nfl.nfl_cover(res, -3.0, sigma_provenance=prov)
        assert res == frozen
        assert prov == SIGMA_PROV

    def test_sigma_provenance_must_be_oof(self):
        for bad in (
            {k: v for k, v in SIGMA_PROV.items() if k != "oof"},
            dict(SIGMA_PROV, oof=False),
            dict(SIGMA_PROV, label_in_sample=True),
            {k: v for k, v in SIGMA_PROV.items() if k != "window_start"},
            {k: v for k, v in SIGMA_PROV.items() if k != "window_end"},
        ):
            with pytest.raises(MarginAdapterError, match=SIGMA_PROVENANCE_NOT_OOF):
                nfl.nfl_cover(nfl_result(), -3.5, sigma_provenance=bad)

    def test_diagnostics_non_dict_fail_closed(self):
        res = nfl_result()
        res["diagnostics"] = "qb"  # truthy non-dict: must not AttributeError
        with pytest.raises(MarginAdapterError, match=ARM_NOT_SELECTED_CONSISTENT):
            nfl.nfl_cover(res, -3.5, sigma_provenance=dict(SIGMA_PROV))

    def test_pool_substring_false_positive_fixed(self):
        # 'database_residuals' contains the substring 'base' but names no arm;
        # it must not trigger a spurious pool/arm mismatch for a qb forecast.
        prov = dict(SIGMA_PROV, residual_source="database_residuals")
        rec = nfl.nfl_cover(nfl_result(selected="qb"), -3.5, sigma_provenance=prov)
        assert validate_record(rec) is True

    def test_unrecognized_pool_info_fails_closed(self):
        for prov in (
            dict(SIGMA_PROV, pool="unlabeled_holdout_pool"),
            dict(SIGMA_PROV, pool_arm="mystery_pool"),
            dict(SIGMA_PROV, residual_source="OOF_RESIDUAL_POOL_V2"),
        ):
            with pytest.raises(MarginAdapterError, match=MARGIN_POOL_MODEL_MISMATCH):
                nfl.nfl_cover(nfl_result(), -3.5, sigma_provenance=prov)


# ---------------------------------------------------------------------------
# CFB
# ---------------------------------------------------------------------------
class TestCFB:
    def test_happy_path_week_segmented_sigma(self):
        rec = cfb.cfb_cover(4.2, cfb_sigma_table(), -3.5, week=8,
                            artifact_sha256=SHA, event=dict(EVENT))
        assert validate_record(rec) is True
        assert rec["sigma_provenance"]["segment"] == "late"
        assert rec["sigma_provenance"]["segment_fallback"] is False
        assert rec["source_model"]["model_id"] == "cfb.fbs.elo_form_logit_ridge.v1_0.shadow"

    def test_segment_fallback_is_labeled(self):
        rec = cfb.cfb_cover(4.2, cfb_sigma_table(), -3.5, week=20,
                            artifact_sha256=SHA, event=dict(EVENT))
        assert validate_record(rec) is True
        assert SEGMENT_FALLBACK in rec["warnings"]
        assert rec["sigma_provenance"]["segment_fallback"] is True

    def test_segment_missing_without_fallback(self):
        with pytest.raises(MarginAdapterError, match=SIGMA_SEGMENT_MISSING):
            cfb.cfb_cover(4.2, cfb_sigma_table(with_fallback=False), -3.5, week=20,
                          artifact_sha256=SHA, event=dict(EVENT))

    def test_estimate_sigma_feeds_sigma_table(self):
        rng = np.random.default_rng(3)
        pred = rng.normal(0, 10, 500)
        actual = pred + rng.normal(0, 12.0, 500)
        est = estimate_sigma(pred, actual, min_n=200, provenance={
            "sport": "cfb", "oof": True,
            "window_start": "2021-01-01", "window_end": "2025-01-01"})
        table = {"buckets": [{"label": "all", "week_min": 2, "week_max": 20,
                              "sigma": est["sigma"], "n": est["n"], "oof": True}]}
        rec = cfb.cfb_cover(1.5, table, -3.0, week=4, artifact_sha256=SHA, event=dict(EVENT))
        assert validate_record(rec) is True
        assert rec["sigma_provenance"]["sigma"] == pytest.approx(est["sigma"])

    def test_sigma_requires_sport_label(self):
        with pytest.raises(ValueError, match="SIGMA_REQUIRES_SPORT"):
            estimate_sigma(np.zeros(300), np.zeros(300), min_n=200,
                           provenance={"oof": True, "window_start": "a", "window_end": "b"})

    def test_input_not_mutated(self):
        table = cfb_sigma_table()
        frozen = copy.deepcopy(table)
        cfb.cfb_cover(4.2, table, -3.5, week=8, artifact_sha256=SHA, event=dict(EVENT))
        assert table == frozen


# ---------------------------------------------------------------------------
# MLB
# ---------------------------------------------------------------------------
class TestMLB:
    def test_runline_direct_counting(self):
        home, away = mlb_scores()
        rec = mlb.mlb_runline_cover(home, away, -1.5, artifact_sha256=SHA, event=dict(EVENT))
        assert validate_record(rec) is True
        margins = home - away
        assert rec["probabilities"]["p_cover"] == pytest.approx(float(np.mean(margins >= 2)))
        assert rec["probabilities"]["p_push"] == 0.0
        assert rec["source_model"]["model_id"] == "mlb.winner.CHAMPION_V13"

    def test_integer_line_has_real_push_mass(self):
        home, away = mlb_scores()
        rec = mlb.mlb_runline_cover(home, away, -1.0, artifact_sha256=SHA, event=dict(EVENT))
        margins = home - away
        expected_push = float(np.mean(margins == 1))
        assert expected_push > 0.0
        assert rec["probabilities"]["p_push"] == pytest.approx(expected_push)
        assert "EXCLUDING_PUSHES" in rec["probabilities"]["labels"]

    def test_totals_unsupported_settlement(self):
        with pytest.raises(UnsupportedProductError, match=UNSUPPORTED_SETTLEMENT):
            mlb.mlb_totals_cover([5, 4], [3, 4], 8.5)

    def test_non_integer_draws_rejected(self):
        home, away = mlb_scores()
        home = home.astype(float)
        home[0] += 0.5
        with pytest.raises(MarginAdapterError, match="RUN_MARGIN_DRAWS_NOT_INTEGER"):
            mlb.mlb_runline_cover(home, away, -1.5, artifact_sha256=SHA, event=dict(EVENT))

    def test_input_arrays_not_mutated(self):
        home, away = mlb_scores()
        h0, a0 = home.copy(), away.copy()
        mlb.mlb_runline_cover(home, away, -1.5, artifact_sha256=SHA, event=dict(EVENT))
        assert np.array_equal(home, h0) and np.array_equal(away, a0)


# ---------------------------------------------------------------------------
# NHL
# ---------------------------------------------------------------------------
def nhl_margin_output(**over):
    out = {
        "model_id": "nhl.margin.research.v1",
        "artifact_sha256": SHA,
        "margin_mean": 0.8,
        "sigma": 2.4,
        "labels": ["UNCALIBRATED", "SEPARATE_FIT_FROM_WINNER_MODEL"],
        "event": dict(EVENT),
    }
    out.update(over)
    return out


class TestNHL:
    def test_happy_path_preserves_uncalibrated_labels(self):
        rec = nhl.nhl_puckline_cover(nhl_margin_output(), -1.5)
        assert validate_record(rec) is True
        assert nhl.UNCALIBRATED_LIMITATION in rec["limitations"]
        assert "UNCALIBRATED" in rec["warnings"]  # input label preserved verbatim
        assert "SEPARATE_FIT_FROM_WINNER_MODEL" in rec["warnings"]
        assert rec["probabilities"]["p_push"] == 0.0  # half-point puck line

    def test_integer_puck_line_push_mass(self):
        rec = nhl.nhl_puckline_cover(nhl_margin_output(), -2.0)
        assert rec["probabilities"]["p_push"] > 0.0

    def test_empirical_residuals_path(self):
        rng = np.random.default_rng(11)
        residuals = np.round(rng.normal(0.0, 2.3, 400))
        rec = nhl.nhl_puckline_cover(nhl_margin_output(residuals=residuals), -2.0)
        assert validate_record(rec) is True
        assert rec["probabilities"]["p_push"] > 0.0
        assert nhl.UNCALIBRATED_LIMITATION in rec["limitations"]

    def test_missing_sigma_and_residuals(self):
        out = nhl_margin_output()
        del out["sigma"]
        with pytest.raises(MarginAdapterError, match="SIGMA_REQUIRED"):
            nhl.nhl_puckline_cover(out, -1.5)

    def test_input_not_mutated(self):
        out = nhl_margin_output()
        frozen = copy.deepcopy(out)
        nhl.nhl_puckline_cover(out, -1.5)
        assert out == frozen


# ---------------------------------------------------------------------------
# NBA / WNBA
# ---------------------------------------------------------------------------
class TestNBA:
    def test_happy_path_half_point_line(self):
        rec = nba.nba_cover(-5.5, margin_pred=6.0,
                            sigma_provenance=dict(NBA_SIGMA_PROV),
                            artifact_sha256=SHA, event=dict(EVENT))
        assert validate_record(rec) is True
        assert rec["probabilities"]["p_push"] == 0.0
        assert rec["probabilities"]["p_cover"] > 0.5
        assert "INITIAL_RESEARCH_BASELINE_NOT_ACCURACY_DEFAULT" in rec["limitations"]

    def test_integer_line_push_mass(self):
        rec = nba.nba_cover(-5.0, margin_pred=6.0,
                            sigma_provenance=dict(NBA_SIGMA_PROV),
                            artifact_sha256=SHA, event=dict(EVENT))
        assert rec["probabilities"]["p_push"] > 0.0
        expected = norm.cdf((5.5 - 6.0) / 12.0) - norm.cdf((4.5 - 6.0) / 12.0)
        assert rec["probabilities"]["p_push"] == pytest.approx(expected)

    def test_frozen_ridge_head_application(self):
        # x=[3, None->impute 0]; z=[(3-1)/2, (0-2)/4]=[1, -0.5]
        # mu = 0.5*1 + (-0.25)*(-0.5) + 3.0 = 3.625
        rec = nba.nba_cover(-5.5, head=RIDGE_HEAD, features=[3.0, None],
                            sigma_provenance=dict(NBA_SIGMA_PROV),
                            artifact_sha256=SHA, event=dict(EVENT))
        expected = 1.0 - norm.cdf((5.5 - 3.625) / 12.0)
        assert rec["probabilities"]["p_cover"] == pytest.approx(expected)

    def test_missing_head_and_prediction(self):
        with pytest.raises(MarginAdapterError, match=MISSING_MARGIN_HEAD):
            nba.nba_cover(-5.5, sigma=12.0, artifact_sha256=SHA, event=dict(EVENT))

    def test_away_orientation_symmetry(self):
        rec_h = nba.nba_cover(-5.0, margin_pred=6.0,
                              sigma_provenance=dict(NBA_SIGMA_PROV),
                              artifact_sha256=SHA, event=dict(EVENT))
        rec_a = nba.nba_cover(-5.0, margin_pred=6.0,
                              sigma_provenance=dict(NBA_SIGMA_PROV),
                              artifact_sha256=SHA, event=dict(EVENT), orientation="away")
        ph, pa = rec_h["probabilities"], rec_a["probabilities"]
        assert ph["p_cover"] + pa["p_cover"] + ph["p_push"] == pytest.approx(1.0, abs=1e-9)
        assert pa["p_cover"] == pytest.approx(ph["p_loss"])

    def test_bare_scalar_sigma_rejected(self):
        # A bare scalar sigma carries no OOF provenance; the old shortcut is
        # removed — fail closed.
        with pytest.raises(MarginAdapterError, match="SIGMA_REQUIRED"):
            nba.nba_cover(-5.5, margin_pred=6.0, sigma=12.0,
                          artifact_sha256=SHA, event=dict(EVENT))

    def test_fabricated_non_oof_provenance_rejected(self):
        for bad in (
            {"sport": "nba", "sigma": 12.0},  # no oof/windows at all
            dict(NBA_SIGMA_PROV, oof=False),
            dict(NBA_SIGMA_PROV, label_in_sample=True),
        ):
            with pytest.raises(MarginAdapterError, match=SIGMA_PROVENANCE_NOT_OOF):
                nba.nba_cover(-5.5, margin_pred=6.0, sigma_provenance=bad,
                              artifact_sha256=SHA, event=dict(EVENT))

    def test_scalar_sigma_with_compliant_provenance_accepted(self):
        # The scalar kwarg may override the sigma VALUE, never the provenance.
        rec = nba.nba_cover(-5.5, margin_pred=6.0, sigma=12.5,
                            sigma_provenance=dict(NBA_SIGMA_PROV),
                            artifact_sha256=SHA, event=dict(EVENT))
        assert validate_record(rec) is True
        assert rec["sigma_provenance"]["sigma"] == 12.5


class TestWNBA:
    def test_happy_path_frozen_fitter_label(self):
        rec = wnba.wnba_cover(-4.5, margin_pred=2.0,
                              sigma_provenance=dict(WNBA_SIGMA_PROV),
                              artifact_sha256=SHA, event=dict(EVENT))
        assert validate_record(rec) is True
        assert "SELECTED_FROZEN_FITTER_SHADOW" in rec["limitations"]
        assert rec["source_model"]["model_id"] == "wnba.rs.ff7_logit_ridge.v1_0.shadow"
        assert rec["probabilities"]["p_push"] == 0.0

    def test_integer_line_push_mass(self):
        rec = wnba.wnba_cover(-4.0, margin_pred=2.0,
                              sigma_provenance=dict(WNBA_SIGMA_PROV),
                              artifact_sha256=SHA, event=dict(EVENT))
        assert rec["probabilities"]["p_push"] > 0.0

    def test_sigma_sport_mismatch_refused(self):
        with pytest.raises(MarginAdapterError, match=SIGMA_SPORT_MISMATCH):
            wnba.wnba_cover(-4.5, margin_pred=2.0,
                            sigma_provenance={"sport": "nba", "sigma": 11.0},
                            artifact_sha256=SHA, event=dict(EVENT))


# ---------------------------------------------------------------------------
# MLS
# ---------------------------------------------------------------------------
class TestMLS:
    def test_margin_product_unsupported_1x2_only(self):
        with pytest.raises(UnsupportedProductError, match=UNSUPPORTED_1X2_ONLY):
            mls.mls_cover(-1.0, margin_pred=0.7, sigma=1.8)

    def test_1x2_record_passthrough(self):
        forecast = {
            "model_id": "mls.initial_causal_score.research.v1",
            "model_winner": "HOME",
            "diagnostics": {"analytic_probabilities": [0.3, 0.27, 0.43]},
            "action_authority": False,
        }
        frozen = copy.deepcopy(forecast)
        rec = mls.mls_1x2_record(forecast)
        assert rec["schema"] == "sports.mls_1x2_passthrough.v1"
        assert rec["margin_products"]["status"] == UNSUPPORTED_1X2_ONLY
        assert rec["margin_products"]["p_cover"] is None
        assert rec["forecast"] == frozen  # full passthrough
        assert forecast == frozen  # input untouched
        assert rec["research_only"] is True and rec["action_authority"] is False
        assert "reason" in rec["margin_products"]


# ---------------------------------------------------------------------------
# registry / cross-cutting
# ---------------------------------------------------------------------------
class TestRegistry:
    def test_all_leagues_resolve(self):
        entrypoints = {
            "nfl": "nfl_cover", "cfb": "cfb_cover", "nhl": "nhl_puckline_cover",
            "mlb": "mlb_runline_cover", "nba": "nba_cover", "wnba": "wnba_cover",
            "mls": "mls_1x2_record",
        }
        assert set(leagues()) == set(entrypoints)
        for league, attr in entrypoints.items():
            assert callable(getattr(get_adapter(league), attr))

    def test_unknown_league(self):
        with pytest.raises(ValueError, match="UNKNOWN_LEAGUE_ADAPTER"):
            get_adapter("epl")


class TestRecordIntegrity:
    def test_validate_rejects_authority_tamper(self):
        rec = nba.nba_cover(-5.5, margin_pred=6.0,
                            sigma_provenance=dict(NBA_SIGMA_PROV),
                            artifact_sha256=SHA, event=dict(EVENT))
        tampered = dict(rec, action_authority=True)
        with pytest.raises(ValueError, match="MARGIN_RECORD_AUTHORITY_VIOLATION"):
            validate_record(tampered)

    def test_validate_rejects_hash_tamper(self):
        rec = nfl.nfl_cover(nfl_result(), -3.5, sigma_provenance=dict(SIGMA_PROV))
        tampered = dict(rec, home_spread=-9.5)
        with pytest.raises(ValueError, match="MARGIN_RECORD_HASH_MISMATCH"):
            validate_record(tampered)

    def test_label_extensions_keep_record_valid(self):
        # SEGMENT_FALLBACK and NHL labels are merged post-emit; hash must hold.
        rec = cfb.cfb_cover(4.2, cfb_sigma_table(), -3.5, week=99,
                            artifact_sha256=SHA, event=dict(EVENT))
        assert SEGMENT_FALLBACK in rec["warnings"]
        assert validate_record(rec) is True

    def test_finalize_record_revalidates(self):
        # finalize_record must never emit a structurally invalid re-sealed
        # record: validate_record runs before the record is returned.
        from pipelines.margins._shared import finalize_record

        rec = nfl.nfl_cover(nfl_result(), -3.5, sigma_provenance=dict(SIGMA_PROV))
        assert finalize_record(rec, extra_warnings=["EXTRA"])["record_sha256"] != rec["record_sha256"]
        broken = {k: v for k, v in rec.items() if k != "event_id"}
        with pytest.raises(ValueError, match="MARGIN_RECORD_SCHEMA_VIOLATION"):
            finalize_record(broken, extra_warnings=["EXTRA"])
