"""Margin distribution primitives (HOME-orientation margins).

Margin convention: M = home_score - away_score. All CDFs are P(M <= margin).

Distribution identity: `distribution_id` is sha256 over the canonical JSON of
{"type": ..., "params": ..., "provenance": ...} (sorted keys, compact
separators). Same construction inputs -> same id; provenance is part of the
identity so a re-fit distribution never silently collides with a stale one.
"""
from __future__ import annotations

import hashlib
import json
from typing import Protocol, runtime_checkable

import numpy as np
from scipy.stats import norm

EMPIRICAL_MIN_SUPPORT = 200
SIMULATED_MIN_DRAWS = 10000


def _canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _array_sha(arr: np.ndarray) -> str:
    arr = np.ascontiguousarray(np.asarray(arr, dtype=np.float64))
    return hashlib.sha256(arr.tobytes()).hexdigest()


def distribution_id_for(type_: str, params: dict, provenance: dict) -> str:
    canon = {"type": type_, "params": params, "provenance": provenance or {}}
    return _sha256_text(_canonical_json(canon))


@runtime_checkable
class MarginDistribution(Protocol):
    """Protocol for margin distributions (HOME-orientation)."""

    distribution_id: str

    def cdf(self, margin: float) -> float:
        """P(M <= margin)."""
        ...

    def push_mass(self, margin: float) -> float:
        """P(M == margin). 0.0 for continuous distributions."""
        ...

    def sample(self, n: int, seed: int) -> np.ndarray:
        """Deterministic draws via np.random.default_rng(seed)."""
        ...


def _check_n(n: int) -> int:
    n = int(n)
    if n <= 0:
        raise ValueError("MARGIN_SAMPLE_N_INVALID")
    return n


class NormalMargin:
    """Continuous normal margin distribution. No push mass anywhere."""

    def __init__(self, mu: float, sigma: float, provenance: dict):
        self.mu = float(mu)
        self.sigma = float(sigma)
        self.provenance = dict(provenance or {})
        self.distribution_id = distribution_id_for(
            "normal", {"mu": self.mu, "sigma": self.sigma}, self.provenance
        )

    def cdf(self, margin: float) -> float:
        return float(norm.cdf(float(margin), loc=self.mu, scale=self.sigma))

    def push_mass(self, margin: float) -> float:
        return 0.0

    def sample(self, n: int, seed: int) -> np.ndarray:
        n = _check_n(n)
        rng = np.random.default_rng(seed)
        return rng.normal(self.mu, self.sigma, n)


class EmpiricalMargin:
    """CDF from sorted residuals shifted by mu (empirical CDF, inclusive).

    integer_snap=True rounds support to integers (football/soccer), which
    creates real push mass at integer margins.
    """

    def __init__(self, mu, xs_sorted, integer_snap, provenance, resid_sha, n_resid):
        self.mu = float(mu)
        self.xs = xs_sorted
        self.integer_snap = bool(integer_snap)
        self.provenance = dict(provenance or {})
        self.distribution_id = distribution_id_for(
            "empirical",
            {
                "mu": self.mu,
                "integer_snap": self.integer_snap,
                "n_residuals": int(n_resid),
                "residuals_sha256": resid_sha,
            },
            self.provenance,
        )

    def cdf(self, margin: float) -> float:
        return float(np.searchsorted(self.xs, float(margin), side="right") / self.xs.size)

    def push_mass(self, margin: float) -> float:
        m = float(margin)
        if not self.integer_snap or not m.is_integer():
            return 0.0
        lo = np.searchsorted(self.xs, m, side="left")
        hi = np.searchsorted(self.xs, m, side="right")
        return float((hi - lo) / self.xs.size)

    def sample(self, n: int, seed: int) -> np.ndarray:
        n = _check_n(n)
        rng = np.random.default_rng(seed)
        idx = rng.integers(0, self.xs.size, n)
        return self.xs[idx].astype(np.float64)


class SimulatedMargin:
    """Direct-counting distribution over existing simulation draws.

    Integer support is auto-detected; when detected, push mass at integer
    margins is the exact draw frequency.
    """

    def __init__(self, draws_sorted, integer_support, provenance, draws_sha):
        self.xs = draws_sorted
        self.integer_support = bool(integer_support)
        self.provenance = dict(provenance or {})
        self.distribution_id = distribution_id_for(
            "simulated",
            {
                "n_draws": int(self.xs.size),
                "integer_support": self.integer_support,
                "draws_sha256": draws_sha,
            },
            self.provenance,
        )

    def cdf(self, margin: float) -> float:
        return float(np.searchsorted(self.xs, float(margin), side="right") / self.xs.size)

    def push_mass(self, margin: float) -> float:
        m = float(margin)
        if not self.integer_support or not m.is_integer():
            return 0.0
        lo = np.searchsorted(self.xs, m, side="left")
        hi = np.searchsorted(self.xs, m, side="right")
        return float((hi - lo) / self.xs.size)

    def sample(self, n: int, seed: int) -> np.ndarray:
        n = _check_n(n)
        rng = np.random.default_rng(seed)
        idx = rng.integers(0, self.xs.size, n)
        return self.xs[idx].astype(np.float64)


class DiscreteFootballMargin:
    """Integer-valued margin distribution: normal base + key-number spikes.

    Construction method: take an integer grid k over mu +/- 10*sigma, weight
    each integer by the normal density phi(k; mu, sigma), then multiplicatively
    inflate key numbers: w_k = phi(k; mu, sigma) * (1 + m_k) where m_k comes
    from key_number_mass (e.g. {3: 0.05, 7: 0.04}); renormalize so sum(p)=1.
    CDF is the cumulative sum over the grid; push_mass(k) = p_k at integers.
    """

    def __init__(self, mu, sigma, key_number_mass, grid, probs, provenance):
        self.mu = float(mu)
        self.sigma = float(sigma)
        self.key_number_mass = {int(k): float(v) for k, v in key_number_mass.items()}
        self.grid = grid
        self.probs = probs
        self.provenance = dict(provenance or {})
        self.distribution_id = distribution_id_for(
            "discrete_football",
            {
                "mu": self.mu,
                "sigma": self.sigma,
                "key_number_mass": self.key_number_mass,
            },
            self.provenance,
        )

    def cdf(self, margin: float) -> float:
        return float(self.probs[self.grid <= float(margin)].sum())

    def push_mass(self, margin: float) -> float:
        m = float(margin)
        if not m.is_integer():
            return 0.0
        k = int(m)
        if k < self.grid[0] or k > self.grid[-1]:
            return 0.0
        return float(self.probs[k - self.grid[0]])

    def sample(self, n: int, seed: int) -> np.ndarray:
        n = _check_n(n)
        rng = np.random.default_rng(seed)
        return rng.choice(self.grid, size=n, p=self.probs).astype(np.float64)


def normal_margin(mu: float, sigma: float, provenance: dict) -> NormalMargin:
    sigma = float(sigma)
    if not np.isfinite(sigma) or sigma <= 0:
        raise ValueError("MARGIN_SIGMA_INVALID")
    if not np.isfinite(float(mu)):
        raise ValueError("MARGIN_MU_INVALID")
    return NormalMargin(mu, sigma, provenance)


def empirical_margin(
    mu: float, residuals: np.ndarray, provenance: dict, *, integer_snap: bool = False
) -> EmpiricalMargin:
    residuals = np.asarray(residuals, dtype=np.float64).ravel()
    if residuals.size < EMPIRICAL_MIN_SUPPORT:
        raise ValueError("EMPIRICAL_MARGIN_MIN_SUPPORT")
    if not np.all(np.isfinite(residuals)):
        raise ValueError("EMPIRICAL_MARGIN_NAN")
    if not np.isfinite(float(mu)):
        raise ValueError("MARGIN_MU_INVALID")
    resid_sha = _array_sha(np.sort(residuals))
    xs = np.sort(residuals) + float(mu)
    if integer_snap:
        xs = np.round(xs)
    return EmpiricalMargin(mu, xs, integer_snap, provenance, resid_sha, residuals.size)


def simulated_margin(draws: np.ndarray, provenance: dict) -> SimulatedMargin:
    draws = np.asarray(draws, dtype=np.float64).ravel()
    if draws.size < SIMULATED_MIN_DRAWS:
        raise ValueError("SIMULATED_MARGIN_MIN_DRAWS")
    if not np.all(np.isfinite(draws)):
        raise ValueError("SIMULATED_MARGIN_NAN")
    xs = np.sort(draws)
    integer_support = bool(np.all(np.isclose(xs, np.round(xs), atol=1e-9)))
    return SimulatedMargin(xs, integer_support, provenance, _array_sha(xs))


def discrete_football_margin(
    mu: float,
    sigma: float,
    key_number_mass: dict | None,
    provenance: dict,
) -> MarginDistribution:
    sigma = float(sigma)
    if not np.isfinite(sigma) or sigma <= 0:
        raise ValueError("MARGIN_SIGMA_INVALID")
    if key_number_mass is None:
        if (provenance or {}).get("allow_plain_normal") is True:
            return normal_margin(mu, sigma, provenance)
        raise ValueError("DISCRETE_FOOTBALL_REQUIRES_KEY_NUMBER_MASS")
    if not key_number_mass:
        raise ValueError("DISCRETE_FOOTBALL_REQUIRES_KEY_NUMBER_MASS")
    boost = {int(k): float(v) for k, v in key_number_mass.items()}
    if any(v <= -1.0 for v in boost.values()):
        raise ValueError("DISCRETE_FOOTBALL_NEGATIVE_MASS")
    lo = int(np.floor(float(mu) - 10.0 * sigma))
    hi = int(np.ceil(float(mu) + 10.0 * sigma))
    grid = np.arange(lo, hi + 1, dtype=np.int64)
    w = norm.pdf(grid, float(mu), sigma)
    mult = np.array([1.0 + boost.get(int(k), 0.0) for k in grid])
    w = w * mult
    probs = w / w.sum()
    return DiscreteFootballMargin(mu, sigma, boost, grid, probs, provenance)
