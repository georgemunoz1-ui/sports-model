"""Tests for pipelines/margins/validate.py (margin-layer validation harness).

Standalone-runnable: loads validate.py by file path so the suite runs without
package installation and cannot be broken by unrelated package __init__ state.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE_PATH = REPO_ROOT / "pipelines" / "margins" / "validate.py"

spec = importlib.util.spec_from_file_location("margins_validate", VALIDATE_PATH)
validate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_record(
    p_cover,
    line,
    actual_margin,
    *,
    orientation="home",
    sport="nfl",
    season=2024,
    week=1,
):
    return {
        "p_cover": p_cover,
        "p_push": 0.0,
        "probability_basis": "UNCONDITIONAL",
        "line": line,
        "actual_margin": actual_margin,
        "orientation": orientation,
        "sport": sport,
        "season": season,
        "week": week,
    }


def synthetic_records(n, p_fn, y_fn, *, seed=0, sport="nfl", weeks_per_season=18):
    """Build chronological records; p_fn(i)->p_cover, y_fn(i,p)->cover bool."""
    rng = np.random.default_rng(seed)
    recs = []
    for i in range(n):
        season = 2020 + (i // (weeks_per_season * 32))
        week = 1 + (i // 32) % weeks_per_season
        p = float(p_fn(i, rng))
        # lines always on half-points so nothing pushes unless requested
        line = -3.5
        home_covers = bool(y_fn(i, p, rng))
        margin = 7.0 if home_covers else -7.0
        recs.append(
            make_record(p, line, margin, season=season, week=week, sport=sport)
        )
    return recs


# ---------------------------------------------------------------------------
# chronological enforcement
# ---------------------------------------------------------------------------

class TestChronologicalEnforcement:
    def test_sorted_input_accepted(self):
        recs = [make_record(0.6, -3.5, 7.0, week=w) for w in (1, 2, 3)]
        out = validate.cover_calibration(recs)
        assert out["n_scored"] == 3

    def test_unsorted_input_raises_exact_message(self):
        recs = [make_record(0.6, -3.5, 7.0, week=w) for w in (1, 3, 2)]
        with pytest.raises(ValueError, match="VALIDATION_REQUIRES_CHRONOLOGICAL_ORDER"):
            validate.cover_calibration(recs)

    def test_equal_timestamps_are_nondecreasing(self):
        recs = [make_record(0.6, -3.5, 7.0, week=2) for _ in range(3)]
        assert validate.cover_calibration(recs)["n_scored"] == 3

    def test_bootstrap_also_enforces_chronology(self):
        recs = [make_record(0.6, -3.5, 7.0, week=w) for w in (2, 1)]
        with pytest.raises(ValueError, match="VALIDATION_REQUIRES_CHRONOLOGICAL_ORDER"):
            validate.paired_brier_vs_baseline(recs)

    def test_date_keyed_records(self):
        recs = [
            make_record(0.55, -2.5, 3.0, season=2024, week=None),
            make_record(0.55, -2.5, 3.0, season=2024, week=None),
        ]
        recs[0]["date"] = "2024-09-05"
        recs[1]["date"] = "2024-09-12"
        assert validate.cover_calibration(recs)["n_scored"] == 2
        recs.reverse()
        with pytest.raises(ValueError, match="VALIDATION_REQUIRES_CHRONOLOGICAL_ORDER"):
            validate.cover_calibration(recs)


class TestSeasonOrdering:
    def test_numeric_seasons_compare_numerically(self):
        # 9 -> 10 is chronologically forward even though "10" < "9" as strings.
        recs = [
            make_record(0.6, -3.5, 7.0, season=9, week=1),
            make_record(0.6, -3.5, 7.0, season=10, week=1),
        ]
        assert validate.cover_calibration(recs)["n_total"] == 2

    def test_two_digit_season_inversion_rejected(self):
        # Lexicographic str(season) keys would order "10" < "9" and wrongly
        # accept this out-of-order sequence.
        recs = [
            make_record(0.6, -3.5, 7.0, season=10, week=1),
            make_record(0.6, -3.5, 7.0, season=9, week=1),
        ]
        with pytest.raises(ValueError, match="VALIDATION_REQUIRES_CHRONOLOGICAL_ORDER"):
            validate.cover_calibration(recs)

    def test_numpy_integer_season_treated_as_numeric(self):
        recs = [
            make_record(0.6, -3.5, 7.0, season=np.int64(9), week=1),
            make_record(0.6, -3.5, 7.0, season=np.int64(10), week=1),
        ]
        assert validate.cover_calibration(recs)["n_total"] == 2

    def test_mixed_season_types_deterministic(self):
        # numeric sorts before string; no TypeError from cross-type compare
        recs = [
            make_record(0.6, -3.5, 7.0, season=2024, week=1),
            make_record(0.6, -3.5, 7.0, season="2025", week=1),
        ]
        assert validate.cover_calibration(recs)["n_total"] == 2
        recs.reverse()
        with pytest.raises(ValueError, match="VALIDATION_REQUIRES_CHRONOLOGICAL_ORDER"):
            validate.cover_calibration(recs)


# ---------------------------------------------------------------------------
# push exclusion + denominators
# ---------------------------------------------------------------------------

class TestPushExclusion:
    def test_pushes_excluded_with_explicit_denominators(self):
        # line -3.0, margin 3.0 -> adjusted 0 -> push (integer line)
        push = make_record(0.7, -3.0, 3.0, week=1)
        cover = make_record(0.9, -3.5, 7.0, week=2)  # y=1
        loss = make_record(0.1, -3.5, -7.0, week=3)  # y=0
        out = validate.cover_calibration([push, cover, loss])
        assert out["n_total"] == 3
        assert out["n_push"] == 1
        assert out["n_scored"] == 2
        assert out["brier_denominator"] == 2
        # Brier over the two scored games only
        expected = ((0.9 - 1.0) ** 2 + (0.1 - 0.0) ** 2) / 2.0
        assert out["brier"] == pytest.approx(expected)
        assert out["push_rate"] == pytest.approx(1 / 3)

    def test_half_point_lines_never_push(self):
        recs = [make_record(0.6, -3.5, 3.0, week=1)]  # adjusted -0.5 -> loss
        out = validate.cover_calibration(recs)
        assert out["n_push"] == 0
        assert out["n_scored"] == 1

    def test_away_orientation_outcome(self):
        # home spread -3.5, home margin +7 => home covers => away bet LOSES
        rec = make_record(0.8, -3.5, 7.0, orientation="away", week=1)
        out = validate.cover_calibration([rec])
        assert out["brier"] == pytest.approx((0.8 - 0.0) ** 2)
        # away bet wins when home fails to cover
        rec2 = make_record(0.8, -3.5, 1.0, orientation="away", week=1)
        out2 = validate.cover_calibration([rec2])
        assert out2["brier"] == pytest.approx((0.8 - 1.0) ** 2)

    def test_away_push_still_excluded(self):
        rec = make_record(0.6, 3.0, -3.0, orientation="away", week=1)  # push
        out = validate.cover_calibration([rec])
        assert out["n_push"] == 1 and out["n_scored"] == 0
        assert "NO_SCORED_GAMES_ALL_PUSHES" in out["warnings"]

    def test_log_loss_clipped_for_extreme_probabilities(self):
        # p=0 with y=1 must not produce inf/nan
        rec = make_record(0.0, -3.5, 7.0, week=1)
        out = validate.cover_calibration([rec])
        assert math.isfinite(out["log_loss"])
        assert out["log_loss"] == pytest.approx(-math.log(validate.LOG_LOSS_EPS))


# ---------------------------------------------------------------------------
# reliability table, bias, calibration slope
# ---------------------------------------------------------------------------

class TestReliabilityAndBias:
    def test_reliability_bucket_counts_and_means(self):
        recs = [
            make_record(0.62, -3.5, 7.0, week=1),   # bucket 6, y=1
            make_record(0.68, -3.5, -7.0, week=2),  # bucket 6, y=0
            make_record(0.91, -3.5, 7.0, week=3),   # bucket 9, y=1
        ]
        out = validate.cover_calibration(recs)
        table = out["reliability"]
        assert len(table) == 10
        b6 = table[6]
        assert b6["n"] == 2
        assert b6["predicted_mean"] == pytest.approx(0.65)
        assert b6["observed_rate"] == pytest.approx(0.5)
        assert table[9]["n"] == 1
        empty = [row for row in table if row["n"] == 0]
        assert all(math.isnan(row["predicted_mean"]) for row in empty)
        assert len(empty) == 8

    def test_bias_zero_for_perfect_two_game(self):
        recs = [
            make_record(0.9, -3.5, 7.0, week=1),   # y=1
            make_record(0.1, -3.5, -7.0, week=2),  # y=0... p=0.1
        ]
        out = validate.cover_calibration(recs)
        assert out["bias"] == pytest.approx(0.0)

    def test_bias_positive_when_overconfident(self):
        recs = [make_record(0.9, -3.5, -7.0, week=w) for w in range(1, 5)]
        out = validate.cover_calibration(recs)
        assert out["bias"] == pytest.approx(0.9)
        assert "COVER_BIAS_EXCEEDS_5PP" in out["warnings"]

    def test_calibrated_synthetic_near_unit_slope_and_low_brier(self):
        rng = np.random.default_rng(7)
        n = 6000
        ps = rng.uniform(0.15, 0.85, size=n)
        covers = rng.uniform(size=n) < ps
        recs = []
        for i in range(n):
            recs.append(
                make_record(
                    ps[i],
                    -3.5,
                    7.0 if covers[i] else -7.0,
                    season=2020 + i // 2000,
                    week=1 + (i // 250) % 8,
                )
            )
        out = validate.cover_calibration(recs)
        assert out["calibration_slope"] == pytest.approx(1.0, abs=0.1)
        assert abs(out["bias"]) < 0.02
        # irreducible Brier for calibrated p~U(0.15,0.85) is E[p(1-p)] ~= 0.209
        assert out["brier"] < 0.215  # near-irreducible, well under 0.25 baseline

    def test_miscalibrated_synthetic_detected(self):
        # predict extremes, truth is a coin flip -> slope far from 1, bad Brier
        rng = np.random.default_rng(11)
        n = 3000
        recs = []
        for i in range(n):
            p = 0.95 if i % 2 == 0 else 0.05
            cover = bool(rng.uniform() < 0.5)
            recs.append(
                make_record(
                    p, -3.5, 7.0 if cover else -7.0,
                    season=2021, week=1 + (i // 200) % 15,
                )
            )
        out = validate.cover_calibration(recs)
        assert out["brier"] > 0.30
        assert not (0.9 <= out["calibration_slope"] <= 1.1)


# ---------------------------------------------------------------------------
# schema validation
# ---------------------------------------------------------------------------

class TestSchema:
    def test_missing_field_rejected(self):
        rec = make_record(0.6, -3.5, 7.0)
        del rec["line"]
        with pytest.raises(ValueError, match="RECORD_SCHEMA_MISSING_FIELDS"):
            validate.cover_calibration([rec])

    def test_bad_orientation_rejected(self):
        rec = make_record(0.6, -3.5, 7.0)
        rec["orientation"] = "HOME"
        with pytest.raises(ValueError, match="RECORD_BAD_ORIENTATION"):
            validate.cover_calibration([rec])

    def test_p_cover_out_of_range_rejected(self):
        with pytest.raises(ValueError, match="RECORD_BAD_P_COVER"):
            validate.cover_calibration([make_record(1.5, -3.5, 7.0)])

    def test_empty_records_rejected(self):
        with pytest.raises(ValueError, match="NONEMPTY"):
            validate.cover_calibration([])


# ---------------------------------------------------------------------------
# sigma_audit
# ---------------------------------------------------------------------------

class TestSigmaAudit:
    def test_overall_sigma_recovers_known_value(self):
        rng = np.random.default_rng(3)
        pred = np.zeros(500)
        actual = rng.normal(0.0, 13.5, size=500)
        out = validate.sigma_audit(pred, actual, "nfl")
        assert out["sigma_overall"] == pytest.approx(13.5, rel=0.05)
        assert out["flags"] == []

    def test_dispersion_grows_with_abs_pred_bucket(self):
        rng = np.random.default_rng(4)
        pred = np.concatenate([np.full(300, 2.0), np.full(300, 17.0)])
        noise = np.concatenate(
            [rng.normal(0, 5.0, 300), rng.normal(0, 15.0, 300)]
        )
        actual = pred + noise
        out = validate.sigma_audit(pred, actual, "nfl")
        buckets = {row["lo"]: row for row in out["by_abs_pred_bucket"]}
        small = buckets[0.0]["sigma"]   # |pred| in [0,3)
        large = buckets[14.0]["sigma"]  # |pred| in [14,21)
        assert large > small * 2

    def test_by_season_table(self):
        rng = np.random.default_rng(5)
        pred = np.zeros(200)
        actual = np.concatenate(
            [rng.normal(0, 10.0, 100), rng.normal(0, 20.0, 100)]
        )
        seasons = ["2023"] * 100 + ["2024"] * 100
        out = validate.sigma_audit(pred, actual, "cfb", seasons=seasons)
        assert set(out["by_season"]) == {"2023", "2024"}
        assert out["by_season"]["2023"]["sigma"] == pytest.approx(10.0, rel=0.15)
        assert out["by_season"]["2024"]["sigma"] == pytest.approx(20.0, rel=0.15)

    def test_sigma_drift_flag_when_recent_inflated(self):
        rng = np.random.default_rng(6)
        pred = np.zeros(400)
        # fit window sigma 10, recent window (last 25%) sigma 20 -> +100%
        actual = np.concatenate(
            [rng.normal(0, 10.0, 300), rng.normal(0, 20.0, 100)]
        )
        out = validate.sigma_audit(pred, actual, "nfl")
        assert "SIGMA_DRIFT" in out["flags"]
        assert out["drift"]["relative_change"] > 0.15

    def test_no_drift_flag_when_stable(self):
        rng = np.random.default_rng(8)
        pred = np.zeros(400)
        actual = rng.normal(0, 12.0, 400)
        out = validate.sigma_audit(pred, actual, "nfl")
        assert "SIGMA_DRIFT" not in out["flags"]
        assert abs(out["drift"]["relative_change"]) <= 0.15

    def test_missing_seasons_warns_not_fails(self):
        rng = np.random.default_rng(9)
        out = validate.sigma_audit(np.zeros(50), rng.normal(0, 10, 50), "mlb")
        assert out["by_season"] == {}
        assert "SIGMA_AUDIT_NO_SEASON_LABELS" in out["warnings"]

    def test_shape_mismatch_rejected(self):
        with pytest.raises(ValueError, match="SHAPE_MISMATCH"):
            validate.sigma_audit([1.0, 2.0], [1.0], "nfl")


# ---------------------------------------------------------------------------
# key_number_audit
# ---------------------------------------------------------------------------

class TestKeyNumberAudit:
    def test_clustered_margins_flagged(self):
        rng = np.random.default_rng(10)
        n = 4000
        # integer margins, as in real football scores
        base = np.round(rng.normal(0, 13.0, n))
        # inject excess mass exactly at |margin| in {3, 7}
        signs = rng.choice([-1.0, 1.0], size=n)
        clustered = base.copy()
        idx = rng.choice(n, size=int(0.20 * n), replace=False)
        clustered[idx] = signs[idx] * rng.choice([3.0, 7.0], size=idx.size)
        out = validate.key_number_audit(clustered)
        assert "KEY_NUMBER_MASS_SIGNIFICANT" in out["flags"]
        assert out["total_excess_mass"] > 0.02
        table = {row["key"]: row for row in out["table"]}
        assert table[3]["excess"] > 0
        assert table[7]["excess"] > 0

    def test_smooth_normal_not_flagged(self):
        rng = np.random.default_rng(12)
        margins = np.round(rng.normal(0, 13.0, 20000))  # integer margins
        out = validate.key_number_audit(margins)
        assert "KEY_NUMBER_MASS_SIGNIFICANT" not in out["flags"]
        assert abs(out["total_excess_mass"]) < 0.02

    def test_expected_mass_uses_abs_and_rounding_bin(self):
        # margins centered far from 0 (|m| genuinely ~normal, no folding);
        # expected mass at key k must equal the fitted-normal rounding-bin
        # probability and match the empirical integer mass
        from scipy import stats as _st

        rng = np.random.default_rng(13)
        margins = np.round(rng.normal(20.0, 8.0, 50000))  # integer margins
        out = validate.key_number_audit(margins)
        table = {row["key"]: row for row in out["table"]}
        mu, sd = out["mu_abs_margin"], out["sigma_abs_margin"]
        analytic = _st.norm.cdf((7.5 - mu) / sd) - _st.norm.cdf((6.5 - mu) / sd)
        assert table[7]["expected_mass"] == pytest.approx(analytic)
        assert table[7]["expected_mass"] > 0
        assert abs(table[7]["empirical_mass"] - table[7]["expected_mass"]) < 0.005
        assert abs(table[14]["empirical_mass"] - table[14]["expected_mass"]) < 0.005

    def test_zero_variance_rejected(self):
        with pytest.raises(ValueError, match="DEGENERATE"):
            validate.key_number_audit(np.full(10, 3.0))


# ---------------------------------------------------------------------------
# paired_brier_vs_baseline (block bootstrap)
# ---------------------------------------------------------------------------

class TestPairedBrierBootstrap:
    def _skilled_records(self, n=1200, seed=21):
        rng = np.random.default_rng(seed)
        recs = []
        for i in range(n):
            true_p = float(rng.uniform(0.3, 0.7))
            cover = bool(rng.uniform() < true_p)
            recs.append(
                make_record(
                    true_p, -3.5, 7.0 if cover else -7.0,
                    season=2020 + i // 400, week=1 + (i // 100) % 4,
                )
            )
        return recs

    def test_determinism_fixed_seed(self):
        recs = self._skilled_records(n=400)
        a = validate.paired_brier_vs_baseline(recs)
        b = validate.paired_brier_vs_baseline(recs)
        assert a["ci_lower"] == b["ci_lower"]
        assert a["ci_upper"] == b["ci_upper"]
        assert a["reps"] == 20000 and a["seed"] == validate.BOOTSTRAP_SEED

    def test_different_seed_changes_ci_slightly(self):
        # one block per game -> near-continuous bootstrap distribution, so a
        # different seed must (overwhelmingly) produce a different CI
        rng = np.random.default_rng(42)
        recs = []
        for i in range(400):
            true_p = float(rng.uniform(0.3, 0.7))
            cover = bool(rng.uniform() < true_p)
            recs.append(
                make_record(
                    true_p, -3.5, 7.0 if cover else -7.0, season=2024, week=i + 1,
                )
            )
        a = validate.paired_brier_vs_baseline(recs)
        b = validate.paired_brier_vs_baseline(recs, seed=99)
        assert (a["ci_lower"], a["ci_upper"]) != (b["ci_lower"], b["ci_upper"])

    def test_skilled_model_beats_fifty_fifty(self):
        recs = self._skilled_records()
        out = validate.paired_brier_vs_baseline(recs)
        assert out["diff_mean"] < 0  # negative = model better
        assert out["model_better"] is True
        assert out["ci_excludes_zero"] is True
        assert out["ci_upper"] < 0.0
        assert out["baseline_brier"] == pytest.approx(0.25)

    def test_coin_flip_model_does_not_beat_baseline(self):
        rng = np.random.default_rng(22)
        recs = []
        for i in range(1500):
            cover = bool(rng.uniform() < 0.5)
            recs.append(
                make_record(
                    0.5, -3.5, 7.0 if cover else -7.0,
                    season=2020 + i // 500, week=1 + (i // 100) % 5,
                )
            )
        out = validate.paired_brier_vs_baseline(recs)
        assert out["diff_mean"] == pytest.approx(0.0, abs=1e-12)
        assert out["ci_excludes_zero"] is False
        assert out["model_better"] is False

    def test_pushes_excluded_from_bootstrap_denominator(self):
        recs = self._skilled_records(n=300)
        # insert pushes (integer line, matching margin) interleaved in time
        pushed = []
        for i, rec in enumerate(recs):
            pushed.append(rec)
            if i % 10 == 9:
                pushed.append(
                    make_record(
                        0.6, -3.0, 3.0,
                        season=rec["season"], week=rec["week"],
                    )
                )
        out = validate.paired_brier_vs_baseline(pushed)
        assert out["n_push"] == 30
        assert out["n_scored"] == 300
        assert out["brier_denominator"] == 300

    def test_block_structure_by_season_week(self):
        recs = self._skilled_records(n=300)
        out = validate.paired_brier_vs_baseline(recs)
        # 300 games, 100/week-slot -> 3 distinct (season, week) blocks
        assert out["n_blocks"] == 3
        assert "BLOCK_BOOTSTRAP_UNDER_60_BLOCKS_PIPELINE_ONLY" in out["warnings"]

    def test_unknown_baseline_rejected(self):
        recs = self._skilled_records(n=50)
        with pytest.raises(ValueError, match="UNKNOWN_BASELINE"):
            validate.paired_brier_vs_baseline(recs, baseline="market")
