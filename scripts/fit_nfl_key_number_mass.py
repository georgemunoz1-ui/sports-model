"""Fit NFL key-number mass boosts from historical final scores (research-only).

Replaces the RESEARCH_PLACEHOLDER_EMPIRICAL_REFIT_REQUIRED table in
pipelines/margins/nfl.py with an empirically fitted, hash-pinned artifact.

Method
------
Margins are M = home_score - away_score over completed regular-season games.
A smooth baseline is a normal fit to the empirical margin distribution
(mu = mean(M), sigma = std(M), ddof=1). The expected frequency of |M| == k is
the baseline mass in the rounding bins [k-0.5, k+0.5) at +k and -k:

    E_k = Phi(k + 0.5; mu, sigma) - Phi(k - 0.5; mu, sigma)
        + Phi(-k + 0.5; mu, sigma) - Phi(-k - 0.5; mu, sigma)   (k > 0)

The fitted boost is boost_k = observed_freq_k / expected_freq_k - 1, computed
for the canonical NFL key numbers {3, 6, 7, 10, 14, 17, 21} and applied
symmetrically at +k and -k (matching the discrete_football_margin contract:
multiplicative inflation w_k = phi(k) * (1 + m_k), so boost > -1 always).

Fail-closed governance
----------------------
  * INSUFFICIENT_HISTORY        - fewer than MIN_HISTORY completed games.
  * INSUFFICIENT_KEY_NUMBER_SUPPORT - a key number with zero observed games
    would imply boost == -1, which discrete_football_margin rejects
    (DISCRETE_FOOTBALL_NEGATIVE_MASS); refuse to emit instead.
  * SOURCE_HASH_MISMATCH        - --expect-sha256 given and the input file
    does not match.
  * GAMES_SCHEMA_INVALID        - required columns missing / non-finite scores.

The emitted artifact is deterministic (no wall-clock fields) so its sha256 is
stable across re-runs on identical input. Artifacts are append-only: a refit
on new data is a NEW versioned file, never an in-place edit.

research_only=True, action_authority=False. No market data, no wagering
language: this is a league-level scoring-frequency property fitted from final
scores only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

SCHEMA = "nfl_key_number_mass.v1"
KEY_NUMBERS = (3, 6, 7, 10, 14, 17, 21)
AUDIT_RANGE = range(0, 22)  # |margin| bins 0..21 audited
MIN_HISTORY = 2000
REQUIRED_COLUMNS = ("game_id", "season", "week", "home_score", "away_score")


class KeyNumberFitError(ValueError):
    """Fail-closed fitting error with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        self.code = str(code)
        super().__init__(f"{self.code}: {message}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_margins(games_csv: Path) -> pd.DataFrame:
    """Load completed games and return frame with integer margin column."""
    df = pd.read_csv(games_csv)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise KeyNumberFitError(
            "GAMES_SCHEMA_INVALID", f"missing required columns: {missing}"
        )
    df = df.dropna(subset=["home_score", "away_score"]).copy()
    df["home_score"] = df["home_score"].astype(float)
    df["away_score"] = df["away_score"].astype(float)
    if not (np.isfinite(df["home_score"]).all() and np.isfinite(df["away_score"]).all()):
        raise KeyNumberFitError("GAMES_SCHEMA_INVALID", "non-finite scores present")
    df["margin"] = (df["home_score"] - df["away_score"]).astype(int)
    return df


def _bin_mass(mu: float, sigma: float, k: int) -> float:
    """Normal mass in the rounding bin [k-0.5, k+0.5)."""
    return float(norm.cdf(k + 0.5, mu, sigma) - norm.cdf(k - 0.5, mu, sigma))


def fit_key_number_mass(margins: np.ndarray, min_history: int = MIN_HISTORY) -> dict:
    """Fit symmetric key-number boosts. Returns the full fit payload."""
    margins = np.asarray(margins, dtype=np.float64).ravel()
    if not np.all(np.isfinite(margins)):
        raise KeyNumberFitError("GAMES_SCHEMA_INVALID", "non-finite margins")
    n = int(margins.size)
    if n < int(min_history):
        raise KeyNumberFitError(
            "INSUFFICIENT_HISTORY",
            f"n={n} completed games < min_history={int(min_history)}; refusing "
            "to fit key-number mass on thin history",
        )
    mu = float(np.mean(margins))
    sigma = float(np.std(margins, ddof=1))
    if not np.isfinite(sigma) or sigma <= 0:
        raise KeyNumberFitError("GAMES_SCHEMA_INVALID", "degenerate margin variance")

    abs_m = np.abs(margins).astype(int)
    audit = []
    for k in AUDIT_RANGE:
        observed = int((abs_m == k).sum())
        observed_freq = observed / n
        if k == 0:
            expected_freq = _bin_mass(mu, sigma, 0)
        else:
            expected_freq = _bin_mass(mu, sigma, k) + _bin_mass(mu, sigma, -k)
        ratio = (observed_freq / expected_freq) if expected_freq > 0 else float("nan")
        audit.append(
            {
                "k": k,
                "observed": observed,
                "observed_freq": observed_freq,
                "expected_freq": expected_freq,
                "ratio": ratio,
                "boost": ratio - 1.0,
            }
        )
    by_k = {row["k"]: row for row in audit}
    key_number_mass = {}
    for k in KEY_NUMBERS:
        row = by_k[k]
        if row["observed"] == 0:
            raise KeyNumberFitError(
                "INSUFFICIENT_KEY_NUMBER_SUPPORT",
                f"key number {k} has zero observed games; boost would be -1.0 "
                "which discrete_football_margin rejects "
                "(DISCRETE_FOOTBALL_NEGATIVE_MASS) — refusing to emit",
            )
        boost = row["boost"]
        key_number_mass[k] = boost
        key_number_mass[-k] = boost  # symmetric at +k and -k
    return {
        "n_games": n,
        "baseline": {"family": "normal_rounding_bins", "mu": mu, "sigma": sigma},
        "key_number_mass": key_number_mass,
        "audit": audit,
    }


def build_artifact(fit: dict, df: pd.DataFrame, source: dict) -> dict:
    seasons = sorted(int(s) for s in df["season"].unique())
    return {
        "schema": SCHEMA,
        "research_only": True,
        "action_authority": False,
        "sport": "nfl",
        "n_games": fit["n_games"],
        "season_window": {"min_season": seasons[0], "max_season": seasons[-1]},
        "baseline": fit["baseline"],
        "key_numbers": list(KEY_NUMBERS),
        "key_number_mass": {str(k): v for k, v in sorted(fit["key_number_mass"].items())},
        "observed_vs_expected": fit["audit"],
        "provenance": {
            "sport": "nfl",
            "oof": False,
            "window_start": str(seasons[0]),
            "window_end": str(seasons[-1]),
            "basis": "league-wide final-score margin frequencies (not model residuals)",
            "source": source,
        },
        "limitations": [
            "LEAGUE_WIDE_AVERAGE_NOT_TEAM_SPECIFIC",
            "SYMMETRIC_BOOST_AT_PLUS_AND_MINUS_K",
            "NORMAL_BASELINE_SMOOTHING",
        ],
    }


def write_artifact(artifact: dict, out_path: Path) -> str:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
    out_path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _selftest() -> int:
    """Synthetic recovery check: planted spikes at 3 and 7 must be recovered."""
    rng = np.random.default_rng(20260903)
    n = 50000
    base = rng.normal(2.5, 13.8, n)
    margins = np.round(base).astype(int)
    # Plant multiplicative excess at |m| in {3, 7}: duplicate ~25% of those rows.
    mask = np.isin(np.abs(margins), [3, 7])
    extra = margins[mask]
    extra = extra[rng.random(extra.size) < 0.25]
    margins = np.concatenate([margins, extra])
    fit = fit_key_number_mass(margins, min_history=2000)
    for k in (3, 7):
        boost = fit["key_number_mass"][k]
        if not (0.10 < boost < 0.45):
            print(f"SELFTEST FAILED: planted boost at {k} recovered as {boost:.4f}")
            return 1
    for k in (10, 14, 17, 21):
        if abs(fit["key_number_mass"][k]) > 0.15:
            print(f"SELFTEST FAILED: unplanted boost at {k} = {fit['key_number_mass'][k]:.4f}")
            return 1
    try:
        fit_key_number_mass(margins[:100], min_history=2000)
    except KeyNumberFitError as exc:
        if exc.code != "INSUFFICIENT_HISTORY":
            print(f"SELFTEST FAILED: wrong code {exc.code}")
            return 1
    else:
        print("SELFTEST FAILED: INSUFFICIENT_HISTORY not raised")
        return 1
    print("SELFTEST OK: planted key-number excess recovered; fail-closed checks pass")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--games", type=Path, default=None, help="nflverse games CSV")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/nfl/margin_fit/nfl_key_number_mass_v1.json"),
    )
    parser.add_argument("--expect-sha256", default=None, help="pin input file sha256")
    parser.add_argument("--min-history", type=int, default=MIN_HISTORY)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.games is None:
        parser.error("--games is required unless --selftest")
    if not args.games.is_file():
        raise KeyNumberFitError("GAMES_SCHEMA_INVALID", f"no such file: {args.games}")
    source_sha = sha256_file(args.games)
    if args.expect_sha256 is not None and source_sha != args.expect_sha256.lower():
        raise KeyNumberFitError(
            "SOURCE_HASH_MISMATCH",
            f"{args.games}: sha256 {source_sha} != pinned {args.expect_sha256.lower()}",
        )
    df = load_margins(args.games)
    fit = fit_key_number_mass(df["margin"].to_numpy(), min_history=args.min_history)
    artifact = build_artifact(
        fit,
        df,
        source={"path": str(args.games), "sha256": source_sha},
    )
    digest = write_artifact(artifact, args.out)
    print(f"wrote {args.out} (sha256 {digest})")
    print(f"n={fit['n_games']} games, baseline mu={fit['baseline']['mu']:.4f} "
          f"sigma={fit['baseline']['sigma']:.4f}")
    for k in KEY_NUMBERS:
        print(f"  |M|={k:>2}: boost={fit['key_number_mass'][k]:+.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
