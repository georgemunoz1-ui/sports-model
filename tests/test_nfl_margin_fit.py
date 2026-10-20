"""Tests for the NFL margin fitting-data pieces (F3a/F3b/F3c).

All fixtures are synthetic; no market data, research-only governance labels
are asserted on every emitted artifact. The margin-system repo copy (core
distribution constructors + NFL adapter) is exercised for integration where
available.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

FITTING_ROOT = Path(__file__).resolve().parents[1]
MARGIN_SYSTEM_ROOT = Path("/mnt/agents/output/margin-system")
if MARGIN_SYSTEM_ROOT.is_dir() and str(MARGIN_SYSTEM_ROOT) not in sys.path:
    sys.path.insert(0, str(MARGIN_SYSTEM_ROOT))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fit_kn = _load_module("fit_nfl_key_number_mass", FITTING_ROOT / "scripts/fit_nfl_key_number_mass.py")
build_resid = _load_module(
    "build_nfl_margin_residuals", FITTING_ROOT / "scripts/build_nfl_margin_residuals.py"
)
extract_comb = _load_module(
    "extract_nfl_combined_margin_residuals",
    FITTING_ROOT / "scripts/extract_nfl_combined_margin_residuals.py",
)
kn_loader = _load_module(
    "nfl_key_numbers_under_test", FITTING_ROOT / "pipelines/margins/nfl_key_numbers.py"
)


# ---------------------------------------------------------------------------
# Synthetic fixtures
# ---------------------------------------------------------------------------
def _margins_with_spikes(n=6000, spike_ks=(3, 7), spike_frac=0.25, seed=7):
    rng = np.random.default_rng(seed)
    margins = np.round(rng.normal(2.5, 13.8, n)).astype(int)
    mask = np.isin(np.abs(margins), list(spike_ks))
    extra = margins[mask]
    extra = extra[rng.random(extra.size) < spike_frac]
    return np.concatenate([margins, extra])


def _games_csv(tmp_path: Path, margins: np.ndarray) -> Path:
    rows = []
    for i, m in enumerate(margins):
        home, away = (24 + int(m), 24) if m >= 0 else (24, 24 - int(m))
        rows.append(
            {
                "game_id": f"2020_01_SYN{i:05d}",
                "season": 2015 + (i % 10),
                "week": 1 + (i % 18),
                "home_score": home,
                "away_score": away,
            }
        )
    path = tmp_path / "games.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _packed_fixture(tmp_path: Path, n=400, seed=11):
    rng = np.random.default_rng(seed)
    pairs = rng.normal(0.0, 10.0, size=(n, 2)).tolist()
    seasons = [2019 + (i // 100) for i in range(n)]
    inner = json.dumps(
        {"final_score_residuals": pairs, "residual_seasons": seasons}
    ).encode()
    import base64
    import gzip

    wrapper = {
        "encoding": "GZIP_BASE64",
        "sha256": hashlib.sha256(inner).hexdigest(),
        "payload": base64.b64encode(gzip.compress(inner)).decode(),
    }
    path = tmp_path / "model_packed.json"
    path.write_text(json.dumps(wrapper))
    return path, pairs, seasons


# ---------------------------------------------------------------------------
# F3a: key-number mass fitter
# ---------------------------------------------------------------------------
class TestKeyNumberMassFit:
    def test_planted_key_number_excess_recovered(self):
        margins = _margins_with_spikes()
        fit = fit_kn.fit_key_number_mass(margins)
        for k in (3, 7):
            assert fit["key_number_mass"][k] > 0.10
            assert fit["key_number_mass"][-k] == fit["key_number_mass"][k]  # symmetric
        assert abs(fit["key_number_mass"][10]) < 0.15  # unplanted stays near 0

    def test_insufficient_history_fails_closed(self):
        with pytest.raises(fit_kn.KeyNumberFitError) as exc:
            fit_kn.fit_key_number_mass(np.zeros(500))
        assert exc.value.code == "INSUFFICIENT_HISTORY"

    def test_source_hash_mismatch_fails_closed(self, tmp_path):
        csv = _games_csv(tmp_path, _margins_with_spikes(n=2500))
        with pytest.raises(fit_kn.KeyNumberFitError) as exc:
            fit_kn.main(
                [
                    "--games", str(csv),
                    "--expect-sha256", "0" * 64,
                    "--out", str(tmp_path / "out.json"),
                ]
            )
        assert exc.value.code == "SOURCE_HASH_MISMATCH"

    def test_artifact_hash_stability_and_labels(self, tmp_path):
        margins = _margins_with_spikes(n=2500)
        csv = _games_csv(tmp_path, margins)
        df = fit_kn.load_margins(csv)
        fit = fit_kn.fit_key_number_mass(df["margin"].to_numpy())
        src = {"path": str(csv), "sha256": fit_kn.sha256_file(csv)}
        a1 = fit_kn.build_artifact(fit, df, src)
        a2 = fit_kn.build_artifact(fit, df, src)
        t1 = json.dumps(a1, indent=2, sort_keys=True) + "\n"
        t2 = json.dumps(a2, indent=2, sort_keys=True) + "\n"
        assert t1 == t2
        assert hashlib.sha256(t1.encode()).hexdigest() == hashlib.sha256(t2.encode()).hexdigest()
        assert a1["research_only"] is True and a1["action_authority"] is False
        assert a1["provenance"]["sport"] == "nfl"
        assert len(a1["observed_vs_expected"]) == 22  # audit bins 0..21

    def test_all_boosts_above_negative_one(self):
        fit = fit_kn.fit_key_number_mass(_margins_with_spikes())
        assert all(v > -1.0 for v in fit["key_number_mass"].values())


# ---------------------------------------------------------------------------
# F3a: loader
# ---------------------------------------------------------------------------
class TestKeyNumberLoader:
    def _write_artifact(self, tmp_path: Path, **overrides) -> Path:
        artifact = {
            "schema": "nfl_key_number_mass.v1",
            "research_only": True,
            "action_authority": False,
            "key_number_mass": {"3": 0.5, "-3": 0.5, "7": 0.4, "-7": 0.4},
        }
        artifact.update(overrides)
        path = tmp_path / "kn.json"
        path.write_text(json.dumps(artifact, sort_keys=True))
        return path

    def test_roundtrip_with_pinned_hash(self, tmp_path):
        path = self._write_artifact(tmp_path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        mass = kn_loader.load_nfl_key_number_mass(path, expected_sha256=digest)
        assert mass == {3: 0.5, -3: 0.5, 7: 0.4, -7: 0.4}
        assert all(isinstance(k, int) for k in mass)

    def test_hash_mismatch_fails_closed(self, tmp_path):
        path = self._write_artifact(tmp_path)
        with pytest.raises(kn_loader.KeyNumberMassError) as exc:
            kn_loader.load_nfl_key_number_mass(path, expected_sha256="0" * 64)
        assert exc.value.code == "NFL_KEY_NUMBER_MASS_HASH_MISMATCH"

    def test_missing_file_fails_closed(self, tmp_path):
        with pytest.raises(kn_loader.KeyNumberMassError) as exc:
            kn_loader.load_nfl_key_number_mass(tmp_path / "nope.json")
        assert exc.value.code == "NFL_KEY_NUMBER_MASS_MISSING"

    def test_schema_and_governance_validation(self, tmp_path):
        bad = self._write_artifact(tmp_path, research_only=False)
        with pytest.raises(kn_loader.KeyNumberMassError) as exc:
            kn_loader.load_nfl_key_number_mass(bad, expected_sha256=None)
        assert exc.value.code == "NFL_KEY_NUMBER_MASS_SCHEMA_INVALID"
        neg = self._write_artifact(tmp_path, key_number_mass={"3": -1.0, "-3": -1.0})
        with pytest.raises(kn_loader.KeyNumberMassError) as exc:
            kn_loader.load_nfl_key_number_mass(neg, expected_sha256=None)
        assert exc.value.code == "NFL_KEY_NUMBER_MASS_SCHEMA_INVALID"


# ---------------------------------------------------------------------------
# F3b: per-arm OOF residual pools
# ---------------------------------------------------------------------------
class TestBuildMarginResiduals:
    def test_provenance_schema_per_arm(self):
        df = build_resid._synthetic_oof(n_per_arm=250)
        pools = build_resid.build_all(df)
        assert set(pools) == set(build_resid.KNOWN_ARMS)
        for arm, pool in pools.items():
            prov = pool["provenance"]
            assert prov["sport"] == "nfl" and prov["oof"] is True
            assert prov["pool_arm"] == arm
            assert prov["n"] == 250 and prov["sigma"] > 0
            assert "window_start" in prov and "window_end" in prov
            assert pool["research_only"] is True and pool["action_authority"] is False
            assert pool["model_id"] == f"nfl.integrated_context.{arm}.v1.research"

    def test_residual_sign_convention_actual_minus_predicted(self):
        df = build_resid._synthetic_oof(n_per_arm=250)
        pools = build_resid.build_all(df)
        df_qb = df[df["arm"] == "qb"]
        expect = np.sort((df_qb["home_margin"] - df_qb["pred_margin"]).to_numpy())
        assert np.allclose(pools["qb"]["residuals_sorted"], expect)
        assert not np.allclose(
            pools["qb"]["residuals_sorted"],
            np.sort((df_qb["pred_margin"] - df_qb["home_margin"]).to_numpy()),
        )

    def test_oof_hash_mismatch_fails_closed(self, tmp_path):
        csv = tmp_path / "oof.csv"
        build_resid._synthetic_oof().to_csv(csv, index=False)
        with pytest.raises(build_resid.ResidualBuildError) as exc:
            build_resid.load_oof(csv, expected_sha256="0" * 64)
        assert exc.value.code == "OOF_HASH_MISMATCH"

    def test_thin_arm_support_fails_closed(self):
        df = build_resid._synthetic_oof(n_per_arm=50)
        with pytest.raises(build_resid.ResidualBuildError) as exc:
            build_resid.build_all(df)
        assert exc.value.code == "EMPIRICAL_MARGIN_MIN_SUPPORT"

    def test_manifest_pins_every_arm(self, tmp_path):
        df = build_resid._synthetic_oof()
        pools = build_resid.build_all(df)
        manifest = build_resid.write_pools(pools, tmp_path / "out", source={"path": "x", "sha256": "y"})
        for arm, info in manifest["arms"].items():
            blob = Path(info["path"]).read_bytes()
            assert hashlib.sha256(blob).hexdigest() == info["sha256"]
            assert info["n"] == 250

    def test_arm_token_exactness_against_adapter(self):
        pytest.importorskip("pipelines.margins.nfl")
        from pipelines.margins.nfl import _arm_token

        df = build_resid._synthetic_oof()
        pools = build_resid.build_all(df)
        for arm, pool in pools.items():
            assert _arm_token(pool["provenance"]["pool_arm"]) == arm
        # never substring-match: 'database_residuals' must not match 'base'
        assert _arm_token("database_residuals") is None
        assert _arm_token("combined") == "combined"


# ---------------------------------------------------------------------------
# F3c: combined-arm score-pair extraction
# ---------------------------------------------------------------------------
class TestExtractCombinedResiduals:
    def test_derivation_home_minus_away(self, tmp_path):
        path, pairs, _ = _packed_fixture(tmp_path)
        payload, _ = extract_comb.load_packed_payload(path)
        ext = extract_comb.extract_margin_residuals(payload)
        expect = np.sort(np.asarray(pairs)[:, 0] - np.asarray(pairs)[:, 1])
        assert np.allclose(ext["residuals_sorted"], expect)

    def test_payload_hash_mismatch_fails_closed(self, tmp_path):
        path, _, _ = _packed_fixture(tmp_path)
        wrapper = json.loads(path.read_text())
        wrapper["sha256"] = "0" * 64
        path.write_text(json.dumps(wrapper))
        with pytest.raises(extract_comb.PackedExtractError) as exc:
            extract_comb.load_packed_payload(path)
        assert exc.value.code == "PAYLOAD_HASH_MISMATCH"

    def test_limitation_label_and_window(self, tmp_path):
        path, _, seasons = _packed_fixture(tmp_path)
        payload, payload_sha = extract_comb.load_packed_payload(path)
        ext = extract_comb.extract_margin_residuals(payload)
        art = extract_comb.build_artifact(
            ext, source={"sha256": "s", "payload_sha256": payload_sha}
        )
        assert "SCORE_PAIR_DERIVED_NOT_MARGIN_HEAD" in art["limitations"]
        prov = art["provenance"]
        assert prov["pool_arm"] == "combined" and prov["oof"] is True
        assert prov["window_start"] == str(min(seasons))
        assert prov["window_end"] == str(max(seasons))
        assert art["research_only"] is True and art["action_authority"] is False

    def test_length_mismatch_fails_closed(self, tmp_path):
        path, pairs, seasons = _packed_fixture(tmp_path)
        payload, _ = extract_comb.load_packed_payload(path)
        payload["residual_seasons"] = payload["residual_seasons"][:-1]
        with pytest.raises(extract_comb.PackedExtractError) as exc:
            extract_comb.extract_margin_residuals(payload)
        assert exc.value.code == "RESIDUAL_LENGTH_MISMATCH"


# ---------------------------------------------------------------------------
# Integration against the margin-system core + NFL adapter
# ---------------------------------------------------------------------------
class TestAdapterIntegration:
    def test_fitted_mass_accepted_by_discrete_football_margin(self):
        pytest.importorskip("models.common.margins")
        from models.common.margins import discrete_football_margin

        fit = fit_kn.fit_key_number_mass(_margins_with_spikes())
        dist = discrete_football_margin(
            mu=-3.0, sigma=13.5, key_number_mass=fit["key_number_mass"],
            provenance={"sport": "nfl", "research_only": True},
        )
        assert abs(float(np.sum(dist.probs)) - 1.0) < 1e-9
        assert dist.push_mass(3) > 0

    def test_combined_provenance_passes_require_sigma(self, tmp_path):
        pytest.importorskip("pipelines.margins._shared")
        from pipelines.margins._shared import require_sigma

        path, _, _ = _packed_fixture(tmp_path)
        payload, payload_sha = extract_comb.load_packed_payload(path)
        art = extract_comb.build_artifact(
            extract_comb.extract_margin_residuals(payload),
            source={"sha256": "s", "payload_sha256": payload_sha},
        )
        sigma = require_sigma(dict(art["provenance"]), "nfl")
        assert sigma > 0

    def test_adapter_fail_closes_pool_mismatch_qb_vs_combined(self, tmp_path):
        pytest.importorskip("pipelines.margins.nfl")
        from pipelines.margins._shared import MARGIN_POOL_MODEL_MISMATCH, MarginAdapterError
        from pipelines.margins.nfl import nfl_cover

        path, _, _ = _packed_fixture(tmp_path)
        payload, payload_sha = extract_comb.load_packed_payload(path)
        art = extract_comb.build_artifact(
            extract_comb.extract_margin_residuals(payload),
            source={"sha256": "s", "payload_sha256": payload_sha},
        )
        result = {
            "model_id": "nfl.integrated_context.qb.v1.research",
            "model_artifact_sha256": "f" * 64,
            "selected_arm": "qb",
            "arms": {"qb": {"prediction": {"home_margin": -3.0}}},
            "event": {"event_id": "SYN-EVT-1"},
        }
        with pytest.raises(MarginAdapterError) as exc:
            nfl_cover(result, -3.5, sigma_provenance=dict(art["provenance"]))
        assert exc.value.code == MARGIN_POOL_MODEL_MISMATCH
