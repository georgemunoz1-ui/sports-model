"""Regression tests for P0-MC-CONVERGENCE-2026-08-30: the ported MC convergence gate
bound into the forecastable/actionable gate.

Two contract directions, both asserted:
  * a synthetic MC gap ABOVE tolerance -> the game is demoted to forecast-only
    (REGISTERED_FALLBACK_ONLY), the rest of the board still builds, and the audit
    disposition is recorded;
  * a gap BELOW tolerance -> the normal actionable path is untouched.

Runnable two ways: ``pytest harness/test_mc_convergence_gate.py`` and
``python harness/test_mc_convergence_gate.py --selftest`` (healthcheck wiring).
"""
from __future__ import annotations

MODULE_ID = "test_mc_convergence_gate"

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mc_convergence as MC  # noqa: E402


def _actionable():
    return {"subject": "test", "disposition": "FRESH", "grade": "CONFIRMED",
            "dose_multiplier": 1.0, "forecastable": True, "actionable": True,
            "bettable": True, "input_value_policy": MC.CURRENT_OBSERVED_VALUE,
            "reason": "test fixture"}


def _honest_blocks(p):
    return [p + (0.001 if i % 2 else -0.001) for i in range(MC.MC_BLOCKS)]


def _failing_blocks(p):
    return [p] * (MC.MC_BLOCKS - 1) + [p + 0.05]   # ~4.5pp departure


# ---------------------------------------------------------------- above tolerance

def test_gap_above_tolerance_demotes_to_forecast_only():
    verdict = MC.block_convergence_verdict(_failing_blocks(0.55))
    assert verdict["status"] == MC.CONVERGENCE_FAIL
    disp = MC.apply_convergence_gate(_actionable(), verdict, game_id="SYNTH@HOME")
    # forecast-only: the labelled row survives, action fails closed
    assert disp["forecastable"] is True
    assert disp["actionable"] is False
    assert disp["bettable"] is False
    assert disp["input_value_policy"] == MC.REGISTERED_FALLBACK_ONLY
    # audit disposition recorded, with the pre-demotion state retained
    conv = disp["convergence"]
    assert conv["status"] == MC.CONVERGENCE_FAIL
    assert conv["gate"] == "mc_convergence"
    assert conv["pre_demotion_actionable"] is True
    assert conv["pre_demotion_value_policy"] == MC.CURRENT_OBSERVED_VALUE
    assert conv["verdict"]["gap_pp"] > verdict["threshold_pp"]


def test_slate_builds_around_a_convergence_failure():
    games = [
        {"game_id": "GOOD1@HOME", "disposition": _actionable(),
         "block_p_home": _honest_blocks(0.60)},
        {"game_id": "SYNTH@HOME", "disposition": _actionable(),
         "block_p_home": _failing_blocks(0.55)},
        {"game_id": "GOOD2@HOME", "disposition": _actionable(),
         "estimators": (0.505, 0.500)},
    ]
    slate = MC.run_slate(games)   # must NOT raise and must NOT exit 1
    assert slate["n_games"] == 3 and len(slate["rows"]) == 3
    assert len(slate["convergence_failures"]) == 1
    assert "SYNTH@HOME" in slate["convergence_failures"][0]
    by_id = {r["game"]: r["disposition"] for r in slate["rows"]}
    assert by_id["SYNTH@HOME"]["actionable"] is False
    assert by_id["SYNTH@HOME"]["input_value_policy"] == MC.REGISTERED_FALLBACK_ONLY
    assert by_id["SYNTH@HOME"]["forecastable"] is True
    # the rest of the board builds normally
    assert by_id["GOOD1@HOME"]["actionable"] is True
    assert by_id["GOOD2@HOME"]["actionable"] is True


def test_two_estimator_gap_above_registered_tolerance_fails():
    # source lineage's observed 2.968pp failure scale, via the two-estimator path
    verdict = MC.estimator_verdict(0.52968, 0.5)
    assert verdict["status"] == MC.CONVERGENCE_FAIL
    assert abs(verdict["gap_pp"] - 2.968) < 0.001
    assert verdict["registered_tol_pp"] == MC.MC_CONVERGENCE_TOL_PP == 2.7386


# ---------------------------------------------------------------- below tolerance

def test_gap_below_tolerance_keeps_normal_actionable_path():
    verdict = MC.block_convergence_verdict(_honest_blocks(0.55))
    assert verdict["status"] == MC.CONVERGENCE_OK
    disp = MC.apply_convergence_gate(_actionable(), verdict, game_id="OK@HOME")
    assert disp["actionable"] is True
    assert disp["bettable"] is True
    assert disp["input_value_policy"] == MC.CURRENT_OBSERVED_VALUE
    assert disp["convergence"]["status"] == MC.CONVERGENCE_OK  # clean verdict still audited


def test_two_estimator_gap_below_tolerance_passes():
    assert MC.estimator_verdict(0.51, 0.50)["status"] == MC.CONVERGENCE_OK


# ---------------------------------------------------------------- gate hygiene

def test_convergence_never_promotes_a_degraded_input():
    stale = dict(_actionable(), disposition="DEGRADED", grade="ABSENT",
                 actionable=False, bettable=False,
                 input_value_policy=MC.REGISTERED_FALLBACK_ONLY)
    disp = MC.apply_convergence_gate(stale, MC.block_convergence_verdict(_honest_blocks(0.5)))
    assert disp["actionable"] is False


def test_missing_convergence_evidence_is_refused_not_passed():
    import pytest
    with pytest.raises(MC.ConvergenceInputError):
        MC.run_slate([{"game_id": "NOEV@HOME", "disposition": _actionable()}])


# ====================================================================== selftest runner

def selftest():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    fails = []
    for fn in fns:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - report all failures, then fail
            fails.append(f"{fn.__name__}: {e}")
    print(f"test_mc_convergence_gate selftest: {'OK' if not fails else 'FAIL'} "
          f"({len(fns) - len(fails)}/{len(fns)} passed)")
    for x in fails:
        print("  !", x)
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(selftest())
