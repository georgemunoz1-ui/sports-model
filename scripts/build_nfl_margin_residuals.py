"""Build per-arm NFL margin residual pools from OOF predictions (research-only).

Consumes data/nfl/contextual_v1/fit_03/oof_predictions.csv — the pinned,
append-only OOF frame produced by the contextual model's chronological folds
(5 arms x ~1871 games, seasons 2019-2025). The file is NOT committed to the
repo; regenerating it requires the owner's external recovered-root archive.
This builder therefore verifies the file against the pinned sha256 before
doing anything else.

Residual convention: residual = home_margin - pred_margin (actual - model),
per arm, in that arm's own OOF rows only. Pools are per-arm and must stay
per-arm: pipelines/margins/nfl.py fail-closes MARGIN_POOL_MODEL_MISMATCH if a
pool from one arm is used to back a quote whose selected arm is another.

Emitted per arm: data/nfl/margin_residuals/nfl_margin_residuals_<arm>_v1.json
with the sorted residual array, its sha256 (same byte convention as
models/common/margins/distribution._array_sha), n, sigma, and provenance
{sport: nfl, oof: true, window_start, window_end, pool_arm, n, sigma} in the
shape pipelines/margins/_shared.require_sigma expects. A manifest pins every
per-arm artifact by sha256.

Fail-closed governance:
  * OOF_MISSING                 - input file not found (recovered-root needed).
  * OOF_HASH_MISMATCH           - input sha256 != pinned digest.
  * OOF_SCHEMA_INVALID          - missing columns / unknown arm / NaN fields.
  * EMPIRICAL_MARGIN_MIN_SUPPORT - an arm with < 200 residuals (matches
    models/common/margins/distribution.EMPIRICAL_MIN_SUPPORT).

Artifacts are deterministic (no wall-clock fields) and append-only: a rebuild
on a new OOF frame is a NEW versioned file, never an in-place edit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCHEMA = "nfl_margin_residuals.v1"
MANIFEST_SCHEMA = "nfl_margin_residuals_manifest.v1"
KNOWN_ARMS = ("base", "qb", "availability", "travel", "combined")
EMPIRICAL_MARGIN_MIN_SUPPORT = 200  # mirrors models/common/margins/distribution.py
OOF_PINNED_SHA256 = "cb11bb530bb7d8149e0fbae8f6d6cc1775f6879ab157051e3c86dff525092510"
DEFAULT_OOF_PATH = Path("data/nfl/contextual_v1/fit_03/oof_predictions.csv")
DEFAULT_OUT_DIR = Path("data/nfl/margin_residuals")
REQUIRED_COLUMNS = (
    "game_id", "season", "week", "home_margin", "pred_margin", "arm",
)


class ResidualBuildError(ValueError):
    """Fail-closed builder error with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        self.code = str(code)
        super().__init__(f"{self.code}: {message}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _array_sha(arr: np.ndarray) -> str:
    """Same convention as models/common/margins/distribution._array_sha."""
    arr = np.ascontiguousarray(np.asarray(arr, dtype=np.float64))
    return hashlib.sha256(arr.tobytes()).hexdigest()


def _window_label(season: int, week: int) -> str:
    return f"{int(season)}W{int(week):02d}"


def load_oof(oof_csv: Path, *, expected_sha256: str | None = OOF_PINNED_SHA256) -> pd.DataFrame:
    if not oof_csv.is_file():
        raise ResidualBuildError(
            "OOF_MISSING",
            f"{oof_csv} not found; the OOF frame is not committed to the repo "
            "and must be restored from the owner's recovered-root archive",
        )
    if expected_sha256 is not None:
        digest = sha256_file(oof_csv)
        if digest != expected_sha256.lower():
            raise ResidualBuildError(
                "OOF_HASH_MISMATCH",
                f"{oof_csv}: sha256 {digest} != pinned {expected_sha256.lower()}; "
                "refusing to build residual pools from an unverified OOF frame",
            )
    df = pd.read_csv(oof_csv)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ResidualBuildError(
            "OOF_SCHEMA_INVALID", f"missing required columns: {missing}"
        )
    unknown = sorted(set(df["arm"].unique()) - set(KNOWN_ARMS))
    if unknown:
        raise ResidualBuildError(
            "OOF_SCHEMA_INVALID", f"unknown arm labels {unknown}; expected {KNOWN_ARMS}"
        )
    for col in ("home_margin", "pred_margin", "season", "week"):
        if not np.isfinite(pd.to_numeric(df[col], errors="coerce")).all():
            raise ResidualBuildError(
                "OOF_SCHEMA_INVALID", f"non-finite values in column '{col}'"
            )
    return df


def build_arm_pool(df_arm: pd.DataFrame, arm: str) -> dict:
    """Residual = home_margin - pred_margin (actual - model), one arm only."""
    residuals = (df_arm["home_margin"].astype(float) - df_arm["pred_margin"].astype(float)).to_numpy()
    n = int(residuals.size)
    if n < EMPIRICAL_MARGIN_MIN_SUPPORT:
        raise ResidualBuildError(
            "EMPIRICAL_MARGIN_MIN_SUPPORT",
            f"arm '{arm}' has n={n} < {EMPIRICAL_MARGIN_MIN_SUPPORT} OOF residuals",
        )
    order = df_arm[["season", "week"]].astype(int)
    start = order.min()
    end = order.max()
    xs = np.sort(residuals)
    sigma = float(np.std(residuals, ddof=1))
    return {
        "schema": SCHEMA,
        "research_only": True,
        "action_authority": False,
        "sport": "nfl",
        "arm": arm,
        "model_id": f"nfl.integrated_context.{arm}.v1.research",
        "n": n,
        "mean": float(np.mean(residuals)),
        "sigma": sigma,
        "residuals_sha256": _array_sha(xs),
        "residuals_sorted": xs.tolist(),
        "residual_convention": "actual_minus_predicted",
        "provenance": {
            "sport": "nfl",
            "oof": True,
            "window_start": _window_label(start["season"], start["week"]),
            "window_end": _window_label(end["season"], end["week"]),
            "pool_arm": arm,
            "n": n,
            "sigma": sigma,
        },
    }


def build_all(df: pd.DataFrame) -> dict:
    pools = {}
    for arm in KNOWN_ARMS:
        df_arm = df[df["arm"] == arm]
        if df_arm.empty:
            raise ResidualBuildError(
                "OOF_SCHEMA_INVALID", f"no rows for known arm '{arm}'"
            )
        pools[arm] = build_arm_pool(df_arm, arm)
    return pools


def write_pools(pools: dict, out_dir: Path, source: dict) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for arm, pool in pools.items():
        path = out_dir / f"nfl_margin_residuals_{arm}_v1.json"
        text = json.dumps(pool, indent=2, sort_keys=True) + "\n"
        path.write_text(text, encoding="utf-8")
        files[arm] = {
            "path": str(path),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "n": pool["n"],
            "sigma": pool["sigma"],
        }
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "research_only": True,
        "action_authority": False,
        "sport": "nfl",
        "source": source,
        "arms": files,
    }
    mpath = out_dir / "nfl_margin_residuals_manifest_v1.json"
    mtext = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    mpath.write_text(mtext, encoding="utf-8")
    manifest["path"] = str(mpath)
    manifest["sha256"] = hashlib.sha256(mtext.encode("utf-8")).hexdigest()
    return manifest


def _synthetic_oof(n_per_arm: int = 250, seed: int = 20260914) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_per_arm):
        season = 2019 + (i // 40)
        week = 1 + (i % 18)
        true_margin = rng.normal(2.2, 14.0)
        for arm in KNOWN_ARMS:
            pred = true_margin + rng.normal(0.0, 13.0)
            rows.append(
                {
                    "game_id": f"{season}_{week:02d}_SYN{i:04d}",
                    "season": season,
                    "week": week,
                    "home_win": int(true_margin > 0),
                    "home_margin": true_margin,
                    "total_points": rng.normal(45.0, 10.0),
                    "arm": arm,
                    "p_home": 0.5,
                    "pred_margin": pred,
                    "pred_total": 45.0,
                }
            )
    return pd.DataFrame(rows)


def _selftest() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        df = _synthetic_oof()
        csv = tmp / "oof_predictions.csv"
        df.to_csv(csv, index=False)
        # hash-pin pass path
        pools = build_all(load_oof(csv, expected_sha256=sha256_file(csv)))
        for arm, pool in pools.items():
            if pool["n"] != 250 or pool["provenance"]["pool_arm"] != arm:
                print(f"SELFTEST FAILED: bad pool for {arm}")
                return 1
            if pool["provenance"]["oof"] is not True:
                print("SELFTEST FAILED: provenance oof != True")
                return 1
            # residual sign convention: actual - predicted
            df_arm = df[df["arm"] == arm]
            expect = np.sort(
                (df_arm["home_margin"] - df_arm["pred_margin"]).to_numpy()
            )
            if not np.allclose(pool["residuals_sorted"], expect):
                print("SELFTEST FAILED: residual sign/ordering mismatch")
                return 1
        manifest = write_pools(pools, tmp / "out", source={"path": str(csv), "sha256": sha256_file(csv)})
        if set(manifest["arms"]) != set(KNOWN_ARMS):
            print("SELFTEST FAILED: manifest arms mismatch")
            return 1
        # hash mismatch must fail closed
        try:
            load_oof(csv, expected_sha256="0" * 64)
        except ResidualBuildError as exc:
            if exc.code != "OOF_HASH_MISMATCH":
                print(f"SELFTEST FAILED: wrong code {exc.code}")
                return 1
        else:
            print("SELFTEST FAILED: OOF_HASH_MISMATCH not raised")
            return 1
        # thin support must fail closed
        thin = _synthetic_oof(n_per_arm=50)
        try:
            build_all(thin)
        except ResidualBuildError as exc:
            if exc.code != "EMPIRICAL_MARGIN_MIN_SUPPORT":
                print(f"SELFTEST FAILED: wrong code {exc.code}")
                return 1
        else:
            print("SELFTEST FAILED: EMPIRICAL_MARGIN_MIN_SUPPORT not raised")
            return 1
        # missing file must fail closed
        try:
            load_oof(tmp / "nope.csv")
        except ResidualBuildError as exc:
            if exc.code != "OOF_MISSING":
                print(f"SELFTEST FAILED: wrong code {exc.code}")
                return 1
        else:
            print("SELFTEST FAILED: OOF_MISSING not raised")
            return 1
    print("SELFTEST OK: per-arm pools, sign convention, fail-closed paths verified")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--oof", type=Path, default=DEFAULT_OOF_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--expect-sha256",
        default=OOF_PINNED_SHA256,
        help="pinned OOF sha256 (default: committed pin); pass 'none' to disable",
    )
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()
    expected = None if str(args.expect_sha256).lower() == "none" else args.expect_sha256
    df = load_oof(args.oof, expected_sha256=expected)
    pools = build_all(df)
    manifest = write_pools(
        pools, args.out_dir, source={"path": str(args.oof), "sha256": sha256_file(args.oof)}
    )
    print(f"wrote manifest {manifest['path']} (sha256 {manifest['sha256']})")
    for arm, info in manifest["arms"].items():
        print(f"  {arm}: n={info['n']} sigma={info['sigma']:.4f} -> {info['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
