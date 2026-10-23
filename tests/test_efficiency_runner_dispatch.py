"""Regression coverage for disconnected CFB joint and control runner paths."""
from types import SimpleNamespace

import numpy as np
import pytest

from research.efficiency.runner import fit_stage, predict_stage


def test_cfb_joint_dispatch_keeps_training_and_residual_calibration_chronological():
    seen = {}
    def fit_joint(training, calibration):
        seen.update(training=training, calibration=calibration)
        return {"stage_id": "joint_distribution"}
    rows = [{"season": year, "event_id": str(year)} for year in (2021, 2022, 2023, 2024)]
    fit_stage(SimpleNamespace(fit_joint=fit_joint), "cfb", rows, "joint")
    assert [r["season"] for r in seen["training"]] == [2021, 2022, 2023]
    assert [r["season"] for r in seen["calibration"]] == [2024]
    with pytest.raises(ValueError, match="FUTURE_TRAINING_SEASON"):
        fit_stage(SimpleNamespace(fit_joint=fit_joint), "cfb", rows + [{"season": 2025}], "joint")


def test_cfb_joint_dispatch_retains_score_draws_and_their_actual_distribution():
    expected = np.array([[20.5, 19.2], [16.2, 31.8]])
    def simulate_joint(state, example, n, seed):
        assert n == 2
        assert type(seed) is int
        return expected, {"distribution_id": "continuous-test-not-settlement", "count": n,
            "seed": seed, "rng": "numpy.PCG64", "encoding": "float64 Nx2 home away",
            "draw_sha256": "a" * 64, "home_win_probability": .5, "settlement_eligible": False}
    module = SimpleNamespace(predict_joint=lambda *_: {"p_home": .55}, simulate_joint=simulate_joint)
    fitted = {"stage_id": "joint_distribution", "model_id": "cfb.test.joint", "state_sha256": "b" * 64}
    example = {"event_id": "CFB:test", "features": {"x": 2}}
    result = predict_stage(module, "cfb", fitted, example, simulations=2)
    assert np.array_equal(result["joint_draws"], expected)
    assert result["simulation"]["n"] == 2
    assert result["simulation"]["distribution_id"] == "continuous-test-not-settlement"
    assert result["simulation"]["p_home"] == .5
    assert result["simulation"]["settlement_eligible"] is False
    assert predict_stage(module, "cfb", fitted, example, simulations=0) == {"p_home": .55}
