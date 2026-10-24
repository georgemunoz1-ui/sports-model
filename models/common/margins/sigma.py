"""Residual sigma estimation with chronological/OOF enforcement.

Residual convention: residual = actual - pred (home-orientation margins).

Fail-closed rules:
  - label_in_sample=False requires provenance with window_start, window_end,
    and oof is True, else SIGMA_REQUIRES_CHRONOLOGICAL_OOF.
  - window_start must be <= window_end (ISO strings compare lexicographically,
    numerics numerically; incomparable types fail closed), else
    SIGMA_WINDOW_INVERTED.
  - provenance['sport'] is always required (no silent cross-sport sigma reuse),
    else SIGMA_REQUIRES_SPORT.
  - min_n < 2 is rejected (SIGMA_MIN_N_INVALID): std(ddof=1) is undefined at
    n=1, so min_n=1 could silently yield NaN sigmas.
  - Overall support below min_n -> SIGMA_MIN_SUPPORT.
  - Zero-variance residuals (sigma == 0.0) -> SIGMA_ZERO_VARIANCE: a zero
    sigma is a degenerate distribution input, not an estimate.
  - Per-group support below min_n -> sigma=None with flag INSUFFICIENT_SUPPORT
    (not an error; caller sees the gap explicitly).
"""
from __future__ import annotations

from collections import OrderedDict

import numpy as np


def _window_ordered(window_start, window_end) -> bool:
    """window_start <= window_end; incomparable/mixed types fail closed."""
    if isinstance(window_start, str) and isinstance(window_end, str):
        # ISO-8601 date/timestamp strings order lexicographically.
        return window_start <= window_end
    try:
        return float(window_start) <= float(window_end)
    except (TypeError, ValueError):
        return False


def _require_provenance(label_in_sample: bool, provenance: dict | None) -> dict:
    if not label_in_sample:
        if (
            provenance is None
            or provenance.get("oof") is not True
            or "window_start" not in provenance
            or "window_end" not in provenance
        ):
            raise ValueError("SIGMA_REQUIRES_CHRONOLOGICAL_OOF")
        if not _window_ordered(provenance["window_start"], provenance["window_end"]):
            raise ValueError("SIGMA_WINDOW_INVERTED")
    if provenance is None or "sport" not in provenance:
        raise ValueError("SIGMA_REQUIRES_SPORT")
    return dict(provenance)


def estimate_sigma(
    pred,
    actual,
    *,
    group_by=None,
    min_n: int = 200,
    label_in_sample: bool = False,
    provenance: dict | None = None,
) -> dict:
    """Estimate residual sigma with diagnostics.

    group_by: optional tuple of equal-length array-likes, e.g. (seasons,) or
    (sports, season_weeks); each tuple position is one grouping key column.
    Returns {'sigma', 'mean_bias', 'n', 'min_n', 'label_in_sample', 'sport',
             'groups': None | [per-group dicts]}.
    """
    prov = _require_provenance(label_in_sample, provenance)
    min_n = int(min_n)
    if min_n < 2:
        # std(ddof=1) is undefined at n=1; min_n=1 could yield NaN sigmas.
        raise ValueError("SIGMA_MIN_N_INVALID")
    pred = np.asarray(pred, dtype=np.float64).ravel()
    actual = np.asarray(actual, dtype=np.float64).ravel()
    if pred.shape != actual.shape:
        raise ValueError("SIGMA_SHAPE_MISMATCH")
    n = pred.size
    if n < min_n:
        raise ValueError("SIGMA_MIN_SUPPORT")
    resid = actual - pred
    if not np.all(np.isfinite(resid)):
        raise ValueError("SIGMA_NAN_RESIDUAL")
    sigma = float(resid.std(ddof=1))
    if sigma <= 0.0:
        # Zero-variance residuals are a degenerate distribution input, not
        # a usable sigma; never silently return 0.0.
        raise ValueError("SIGMA_ZERO_VARIANCE")

    result = {
        "sigma": sigma,
        "mean_bias": float(resid.mean()),
        "n": int(n),
        "min_n": int(min_n),
        "label_in_sample": bool(label_in_sample),
        "sport": prov["sport"],
        "groups": None,
    }

    if group_by is not None:
        cols = [np.asarray(c).ravel() for c in group_by]
        if any(c.shape[0] != n for c in cols):
            raise ValueError("SIGMA_GROUPBY_SHAPE_MISMATCH")
        buckets: "OrderedDict[tuple, list[int]]" = OrderedDict()
        for i, key in enumerate(zip(*cols)):
            buckets.setdefault(tuple(key), []).append(i)
        groups = []
        for key, idx in buckets.items():
            idx = np.asarray(idx, dtype=np.int64)
            r = resid[idx]
            g = {
                "key": tuple(str(k) for k in key),
                "n": int(idx.size),
                "mean_bias": float(r.mean()),
            }
            if idx.size < int(min_n):
                g["sigma"] = None
                g["flag"] = "INSUFFICIENT_SUPPORT"
            else:
                g["sigma"] = float(r.std(ddof=1)) if idx.size > 1 else 0.0
                g["flag"] = "OK"
            groups.append(g)
        result["groups"] = groups

    return result
