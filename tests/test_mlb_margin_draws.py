"""Tests for scripts/build_mlb_margin_draws.py (MLB qualifying-OOF margin draws).

All fixtures are synthetic except where marked; tests never read market data
(results.csv close_ml_* columns are forbidden by governance and never touched).
"""
from __future__ import annotations

import io
import json
import os
import sys

import numpy as np
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
MARGIN_LAYER = "/mnt/agents/output/margin-system"
SCRATCH = "/mnt/agents/output/scratch-mlb"
sys.path.insert(0, os.path.abspath(SCRIPT_DIR))
sys.path.insert(0, MARGIN_LAYER)

import build_mlb_margin_draws as B  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _row(game_pk="823244", date="2026-04-01", home_win=1, total=9, margin=3,
         away_sp=True, home_sp=True):
    return {
        "gamePk": str(game_pk), "date": date, "away": "AWY", "home": "HME",
        "home_win": home_win, "actual_total": total, "actual_margin": margin,
        "f": {
            "away_sp": {"era": 4.0, "gs": 10, "k": 22.0, "bb": 8.0} if away_sp else None,
            "home_sp": {"era": 3.2, "gs": 12, "k": 25.0, "bb": 7.0} if home_sp else None,
        },
    }


def _draws(n=10000, seed=0):
    rng = np.random.default_rng(seed)
    ra = rng.poisson(4.0, n)
    rh = rng.poisson(4.5, n)
    return ra, rh


# ---------------------------------------------------------------------------
# Deterministic npz writer
# ---------------------------------------------------------------------------

def test_npz_bytes_deterministic_repeat():
    ra, rh = _draws(1000)
    b1 = B.npz_bytes_deterministic({"away": ra.astype(np.int16),
                                    "home": rh.astype(np.int16)})
    b2 = B.npz_bytes_deterministic({"away": ra.astype(np.int16),
                                    "home": rh.astype(np.int16)})
    assert b1 == b2
    assert B.sha256_bytes(b1) == B.sha256_bytes(b2)


def test_npz_roundtrip_int16_arrays():
    ra, rh = _draws(500)
    b = B.npz_bytes_deterministic({"away": ra.astype(np.int16),
                                   "home": rh.astype(np.int16)})
    z = np.load(io.BytesIO(b))
    assert z["away"].dtype == np.int16
    assert z["home"].dtype == np.int16
    np.testing.assert_array_equal(z["away"], ra.astype(np.int16))
    np.testing.assert_array_equal(z["home"], rh.astype(np.int16))


# ---------------------------------------------------------------------------
# Append-only artifact writes
# ---------------------------------------------------------------------------

def test_append_only_write_then_noop(tmp_path):
    p = str(tmp_path / "sub" / "a.npz")
    assert B.append_only_write(p, b"abc") == "written"
    assert B.append_only_write(p, b"abc") == "noop_identical"


def test_append_only_immutable_violation(tmp_path):
    p = str(tmp_path / "a.npz")
    B.append_only_write(p, b"abc")
    with pytest.raises(B.OofBuildError) as ei:
        B.append_only_write(p, b"different")
    assert ei.value.code == "ARTIFACT_IMMUTABLE"


# ---------------------------------------------------------------------------
# Actuals derivation (features.csv total/margin; never close_ml_*)
# ---------------------------------------------------------------------------

def test_derive_actuals_ok_split():
    out = B.derive_actuals(_row(total=9, margin=3, home_win=1))
    assert out == {"home_runs": 6, "away_runs": 3, "home_win": 1,
                   "total": 9, "margin": 3}


def test_derive_actuals_missing_raises():
    with pytest.raises(B.OofBuildError) as ei:
        B.derive_actuals(_row(total=None))
    assert ei.value.code == "ACTUALS_MISSING"


def test_derive_actuals_parity_raises():
    with pytest.raises(B.OofBuildError) as ei:
        B.derive_actuals(_row(total=9, margin=2))  # total+margin odd
    assert ei.value.code == "ACTUALS_PARITY_MISMATCH"


def test_derive_actuals_sign_mismatch_raises():
    with pytest.raises(B.OofBuildError) as ei:
        B.derive_actuals(_row(total=9, margin=3, home_win=0))
    assert ei.value.code == "ACTUALS_SIGN_MISMATCH"


# ---------------------------------------------------------------------------
# Draw validation (floor + integer dtype + pairing)
# ---------------------------------------------------------------------------

def test_validate_draws_below_floor():
    ra, rh = _draws(100)
    with pytest.raises(B.OofBuildError) as ei:
        B.validate_draws(ra, rh, 722 + 1, 1, min_draws=10000)
    assert ei.value.code == "DRAWS_BELOW_FLOOR"


def test_validate_draws_non_integer():
    ra = np.linspace(0, 1, 10000)  # float draws
    rh = np.ones(10000, dtype=np.int64)
    with pytest.raises(B.OofBuildError) as ei:
        B.validate_draws(ra, rh, 722 + 1, 1)
    assert ei.value.code == "DRAWS_NOT_INTEGER"


def test_validate_draws_shape_mismatch():
    ra = np.ones(10001, dtype=np.int64)  # both above floor, unequal lengths
    rh = np.ones(10000, dtype=np.int64)
    with pytest.raises(B.OofBuildError) as ei:
        B.validate_draws(ra, rh, 722 + 1, 1)
    assert ei.value.code == "DRAWS_CAPTURE_MISSING"


def test_validate_draws_ok_at_floor():
    ra, rh = _draws(10000)
    assert B.validate_draws(ra, rh, 722 + 1, 1) is True


# ---------------------------------------------------------------------------
# Seed rule + game record assembly
# ---------------------------------------------------------------------------

def test_seed_rule_capture_key():
    rows = [_row(game_pk="700001"), _row(game_pk="700002")]
    cap = {}
    for r in rows:
        ra, rh = _draws(10000, seed=722 + int(r["gamePk"]))
        cap[722 + int(r["gamePk"])] = (ra, rh)
    games = B.build_game_records(rows, cap, 722, 10000)
    assert [g["seed"] for g in games] == [722 + 700001, 722 + 700002]
    assert all(g["n_sims"] == 10000 for g in games)
    assert games[0]["actual"]["margin"] == 3
    # missing-probable flagging: _row defaults have both SPs
    assert games[0]["sp_matched"] is True


def test_missing_probable_flagged():
    rows = [_row(game_pk="700003", away_sp=False)]
    ra, rh = _draws(10000, seed=722 + 700003)
    cap = {722 + 700003: (ra, rh)}
    games = B.build_game_records(rows, cap, 722, 10000)
    assert games[0]["sp_matched"] is False


def test_build_game_records_duplicate_raises():
    rows = [_row(game_pk="700004"), _row(game_pk="700004")]
    # provide valid captures so the first row passes; the second must trip
    cap = {722 + 700004: _draws(10000, seed=700004)}
    with pytest.raises(B.OofBuildError) as ei:
        B.build_game_records(rows, cap, 722, 10000)
    assert ei.value.code == "DUPLICATE_GAME"


def test_build_game_records_missing_capture_raises():
    rows = [_row(game_pk="700005")]
    with pytest.raises(B.OofBuildError) as ei:
        B.build_game_records(rows, {}, 722, 10000)
    assert ei.value.code == "DRAWS_CAPTURE_MISSING"


# ---------------------------------------------------------------------------
# Summary + weekly buckets
# ---------------------------------------------------------------------------

def test_summarize_weekly_buckets():
    rows = [_row(game_pk="700010", date="2026-04-01"),
            _row(game_pk="700011", date="2026-04-02"),
            _row(game_pk="700012", date="2026-04-09")]  # later ISO week
    cap = {}
    for r in rows:
        cap[722 + int(r["gamePk"])] = _draws(10000, seed=int(r["gamePk"]))
    games = B.build_game_records(rows, cap, 722, 10000)
    s = B.summarize(games)
    assert s["n_games"] == 3
    assert set(s["residual"]) == {"mae", "rmse", "bias", "std"}
    weeks = sorted(s["weekly"])
    assert len(weeks) == 2
    assert sum(b["n"] for b in s["weekly"].values()) == 3


# ---------------------------------------------------------------------------
# OOF sigma via models.common.margins.sigma.estimate_sigma
# ---------------------------------------------------------------------------

def test_oof_sigma_min_support_flag():
    rows = [_row(game_pk=str(700100 + i)) for i in range(3)]
    cap = {722 + int(r["gamePk"]): _draws(10000, seed=i)
           for i, r in enumerate(rows)}
    games = B.build_game_records(rows, cap, 722, 10000)
    info = B.estimate_oof_sigma(games, MARGIN_LAYER,
                                {"start": "2026-04-01", "end": "2026-04-01"})
    assert info["sigma"] is None
    assert info["status"] == "SIGMA_MIN_SUPPORT"


def test_oof_sigma_estimated_with_support():
    rng = np.random.default_rng(7)
    n = 250
    rows = []
    cap = {}
    for i in range(n):
        margin_true = int(rng.integers(-6, 7))
        total = 9 + (margin_true % 2)  # keep parity: (total+margin) even
        if (total + margin_true) % 2:
            total += 1
        rows.append(_row(game_pk=str(710000 + i),
                         date=f"2026-04-{1 + (i % 28):02d}",
                         home_win=int(margin_true > 0),
                         total=total, margin=margin_true))
        # predictive margin mean biased toward true margin + noise
        ra, rh = _draws(10000, seed=i)
        rh = (rh + margin_true).clip(min=0)
        cap[722 + 710000 + i] = (ra, rh)
    games = B.build_game_records(rows, cap, 722, 10000)
    info = B.estimate_oof_sigma(games, MARGIN_LAYER,
                                {"start": "2026-04-01", "end": "2026-04-28"})
    assert info["status"] == "ok"
    assert info["sigma"] is not None and info["sigma"] > 0
    assert info["n"] == n and info["sport"] == "mlb"


# ---------------------------------------------------------------------------
# Manifest provenance + hash integrity
# ---------------------------------------------------------------------------

def test_manifest_provenance_schema(tmp_path):
    rows = [_row(game_pk="700200", date="2026-04-01"),
            _row(game_pk="700201", date="2026-04-03")]
    cap = {722 + int(r["gamePk"]): _draws(10000, seed=int(r["gamePk"]))
           for r in rows}
    games = B.build_game_records(rows, cap, 722, 10000)
    files, _statuses = B.write_game_artifacts(games, str(tmp_path))
    summary = B.summarize(games)
    sigma_info = {"sigma": None, "status": "SIGMA_MIN_SUPPORT", "n": 2}
    m = B.build_manifest(games, files, 722, 10000, "f" * 64, "c" * 64,
                         "h" * 64, sigma_info, summary)
    prov = m["provenance"]
    assert prov["sport"] == "mlb" and prov["oof"] is True
    assert prov["window_start"] <= prov["window_end"]
    assert prov["seed_rule"] == "seed_base + int(gamePk)"
    assert prov["seed_base"] == 722
    assert prov["min_draws_floor"] == 10000
    assert prov["research_only"] is True
    assert prov["action_authority"] is False
    assert prov["market_data"] == "DISABLED_NO_MARKET_DATA"
    assert "close_ml_" in prov["actuals_source"]  # documents the prohibition
    assert m["engine"]["source_id"] == B.ENGINE_ID
    assert m["engine"]["version"] == B.ENGINE_VERSION
    # no wall-clock keys anywhere in the manifest
    assert "utc" not in json.dumps(m).lower()
    assert "generated_at" not in json.dumps(m)


def test_manifest_file_hashes_match_artifacts(tmp_path):
    rows = [_row(game_pk="700300")]
    cap = {722 + 700300: _draws(10000, seed=700300)}
    games = B.build_game_records(rows, cap, 722, 10000)
    files, _statuses = B.write_game_artifacts(games, str(tmp_path))
    for frec in files:
        disk = B.sha256_file(os.path.join(str(tmp_path), frec["file"]))
        assert disk == frec["sha256"]
        assert frec["n_sims"] == 10000
        assert frec["seed"] == 722 + 700300


def test_subset_label_applied_for_partial_replay(tmp_path):
    rows = [_row(game_pk="700400")]
    cap = {722 + 700400: _draws(10000, seed=700400)}
    games = B.build_game_records(rows, cap, 722, 10000)
    files, _statuses = B.write_game_artifacts(games, str(tmp_path))
    m = B.build_manifest(games, files, 722, 10000, "f" * 64, "c" * 64,
                         "h" * 64, {"sigma": None}, B.summarize(games),
                         subset_label="SUBSET_VERIFICATION_NOT_FULL_REPLAY")
    assert m["subset_label"] == "SUBSET_VERIFICATION_NOT_FULL_REPLAY"


# ---------------------------------------------------------------------------
# Adapter compatibility: margin layer consumes our int16 npz draws
# ---------------------------------------------------------------------------

def test_adapter_consumes_npz_draws(tmp_path):
    from pipelines.margins.mlb import mlb_runline_cover
    ra, rh = _draws(10000, seed=42)
    b = B.npz_bytes_deterministic({"away": ra.astype(np.int16),
                                   "home": rh.astype(np.int16)})
    p = tmp_path / "700500.npz"
    p.write_bytes(b)
    z = np.load(p)
    rec = mlb_runline_cover(
        z["home"], z["away"], -1.5,
        event={"event_id": "mlb-700500"},
        artifact_sha256=B.sha256_bytes(b),
    )
    assert rec["research_only"] is True
    assert rec["action_authority"] is False
    probs = rec["probabilities"]
    assert 0.0 <= probs["p_cover"] <= 1.0
    # home margin mean is +0.5 -> home -1.5 cover prob must be well under 1
    expected = float(np.mean((rh - ra) >= 2))
    assert abs(probs["p_cover"] - expected) < 1e-12
    assert probs["p_push"] == 0.0  # half line: zero push mass


def test_adapter_rejects_non_integer_draws():
    from pipelines.margins.mlb import mlb_runline_cover
    from pipelines.margins._shared import MarginAdapterError
    home = np.full(10000, 5.5)  # non-integer scores
    away = np.full(10000, 4.0)
    with pytest.raises(MarginAdapterError) as ei:
        mlb_runline_cover(home, away, -1.5,
                          event={"event_id": "mlb-x"},
                          artifact_sha256="0" * 64)
    assert "NOT_INTEGER" in str(ei.value)


# ---------------------------------------------------------------------------
# Real config hash pin (frozen candidate config on disk)
# ---------------------------------------------------------------------------

def test_config_hash_pin_on_disk():
    # Prefer the repo-committed frozen config; fall back to the sandbox
    # scratch copy (local rehearsal environments only).
    cfg = None
    for cand in ("data/mlb/ml_asof/p3_candidate_config.json",
                 os.path.join(SCRATCH,
                              "data/mlb/ml_asof/p3_candidate_config.json")):
        if os.path.exists(cand):
            cfg = cand
            break
    if cfg is None:
        pytest.skip("candidate config not on disk")
    assert B.sha256_file(cfg).startswith("eede422d")
    canonical = B.sha256_bytes(
        json.dumps(json.load(open(cfg)), sort_keys=True).encode())
    assert canonical.startswith("132523ac")
