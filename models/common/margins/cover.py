"""Cover probability quotes for a home spread against a margin distribution.

Conventions (HOME orientation):
  - home_spread s: home team covers iff M + s > 0, pushes iff M + s == 0.
  - cover_quote(dist, s, orientation='home'):  p_cover = P(M > -s) = 1 - cdf(-s)
  - cover_quote(dist, s, orientation='away'):  p_cover = P(M < -s) = cdf(-s) - push_mass(-s)
  - Half-point lines (abs(2s) odd) have p_push == 0.0 exactly, always.
  - Non-finite lines fail closed (COVER_LINE_NOT_FINITE).
  - The EXCLUDING_PUSHES label is attached only when p_cover_ex_push is
    actually defined (0 < p_push < 1). In the degenerate all-mass-on-the-line
    case (p_push == 1.0) p_cover_ex_push is None and the label is suppressed,
    keeping emit/validate consistent.
  - Symmetry invariant: p_cover_home + p_cover_away + p_push == 1 (1e-9 tol).
    This fails closed (COVER_SYMMETRY_VIOLATION) when a distribution's
    cdf/push_mass are mutually inconsistent (e.g. cdf excludes a point mass
    that push_mass reports).

Limitations: probabilities are only as good as the supplied distribution;
push probabilities are exactly zero for continuous distributions and depend
on integer support otherwise. Research only; no betting action authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .distribution import MarginDistribution

_SYMMETRY_TOL = 1e-9


@dataclass(frozen=True)
class CoverQuote:
    p_cover: float
    p_push: float
    p_loss: float
    p_cover_ex_push: float | None
    home_spread: float
    distribution_id: str
    labels: tuple = field(default_factory=tuple)


def _is_half_line(x: float) -> bool:
    v = abs(float(x) * 2.0)
    if not np.isfinite(v):
        raise ValueError("COVER_LINE_NOT_FINITE")
    r = round(v)
    return abs(v - r) < 1e-9 and int(r) % 2 == 1


def cover_quote(
    dist: MarginDistribution, home_spread: float, *, orientation: str = "home"
) -> CoverQuote:
    if orientation not in ("home", "away"):
        raise ValueError("COVER_ORIENTATION_INVALID")
    s = float(home_spread)
    if not np.isfinite(s):
        raise ValueError("COVER_LINE_NOT_FINITE")
    t = -s  # cover threshold on the margin

    cdf_t = float(dist.cdf(t))
    if not (-1e-12 <= cdf_t <= 1.0 + 1e-12):
        raise ValueError("COVER_SYMMETRY_VIOLATION")
    cdf_t = min(1.0, max(0.0, cdf_t))

    push_t = 0.0 if _is_half_line(s) else float(dist.push_mass(t))
    if push_t < 0.0 or push_t > cdf_t + 1e-9:
        # Point mass must be contained in the inclusive CDF mass.
        raise ValueError("COVER_SYMMETRY_VIOLATION")

    # Left-limit probe: any point mass reported by push_mass must appear
    # between cdf(t-) and cdf(t). Catches strict-style CDFs that omit the
    # point mass their push_mass reports (sum would otherwise exceed 1).
    t_left = float(np.nextafter(t, -np.inf))
    cdf_left = float(dist.cdf(t_left))
    if not (-1e-12 <= cdf_left <= 1.0 + 1e-12):
        raise ValueError("COVER_SYMMETRY_VIOLATION")
    cdf_left = min(1.0, max(0.0, cdf_left))

    p_cover_home = 1.0 - cdf_t
    p_cover_away = cdf_t - push_t
    total = p_cover_home + cdf_left + push_t
    if abs(total - 1.0) > _SYMMETRY_TOL:
        raise ValueError("COVER_SYMMETRY_VIOLATION")

    if orientation == "home":
        p_cover, p_loss = p_cover_home, p_cover_away
    else:
        p_cover, p_loss = p_cover_away, p_cover_home

    p_push = push_t
    if p_push < 1.0:
        p_cover_ex_push = p_cover / (1.0 - p_push)
    else:
        p_cover_ex_push = None
    # Suppress the label when the ex-push probability is undefined
    # (p_push == 1.0): emitting EXCLUDING_PUSHES there would make
    # validate_record reject its own record.
    labels = ("EXCLUDING_PUSHES",) if p_push > 0.0 and p_cover_ex_push is not None else ()

    return CoverQuote(
        p_cover=float(p_cover),
        p_push=float(p_push),
        p_loss=float(p_loss),
        p_cover_ex_push=p_cover_ex_push,
        home_spread=s,
        distribution_id=dist.distribution_id,
        labels=labels,
    )
