"""Scoring rules and calibration checks.

A prediction model is only as good as its out-of-sample log loss and its
calibration curve; accuracy alone will happily reward a model that says 100%
on every home favourite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


def brier_score(probs: Sequence[float], outcomes: Sequence[int]) -> float:
    """Mean squared error of probabilistic forecasts. Lower is better."""
    p = np.asarray(probs, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    return float(np.mean((p - y) ** 2))


def log_loss(probs: Sequence[float], outcomes: Sequence[int], eps: float = 1e-15) -> float:
    """Mean negative log likelihood. The scoring rule to optimise."""
    p = np.clip(np.asarray(probs, dtype=float), eps, 1 - eps)
    y = np.asarray(outcomes, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def accuracy(probs: Sequence[float], outcomes: Sequence[int], threshold: float = 0.5) -> float:
    p = np.asarray(probs, dtype=float)
    y = np.asarray(outcomes, dtype=int)
    return float(np.mean((p >= threshold).astype(int) == y))


def skill_score(probs: Sequence[float], outcomes: Sequence[int], baseline: float | None = None) -> float:
    """Brier skill score against a fixed-probability baseline (base rate by default).

    0 means "no better than always predicting the base rate"; 1 is perfect.
    """
    y = np.asarray(outcomes, dtype=float)
    base = float(y.mean()) if baseline is None else float(baseline)
    ref = brier_score(np.full(y.shape, base), y)
    if ref == 0:
        return 0.0
    return float(1.0 - brier_score(probs, y) / ref)


def margin_errors(predicted: Sequence[float], actual: Sequence[float]) -> dict[str, float]:
    """MAE / RMSE / bias for point-margin predictions."""
    p = np.asarray(predicted, dtype=float)
    a = np.asarray(actual, dtype=float)
    err = p - a
    return {
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err**2))),
        "bias": float(np.mean(err)),
        "n": int(err.size),
    }


@dataclass
class CalibrationBin:
    lo: float
    hi: float
    n: int
    mean_pred: float
    observed: float

    @property
    def error(self) -> float:
        return self.mean_pred - self.observed


def calibration(probs: Sequence[float], outcomes: Sequence[int], n_bins: int = 10) -> list[CalibrationBin]:
    """Reliability table: predicted probability vs observed frequency."""
    p = np.asarray(probs, dtype=float)
    y = np.asarray(outcomes, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, n_bins - 1)
    bins: list[CalibrationBin] = []
    for b in range(n_bins):
        mask = idx == b
        if not mask.any():
            continue
        bins.append(
            CalibrationBin(
                lo=float(edges[b]),
                hi=float(edges[b + 1]),
                n=int(mask.sum()),
                mean_pred=float(p[mask].mean()),
                observed=float(y[mask].mean()),
            )
        )
    return bins


def expected_calibration_error(probs: Sequence[float], outcomes: Sequence[int], n_bins: int = 10) -> float:
    bins = calibration(probs, outcomes, n_bins)
    total = sum(b.n for b in bins)
    if total == 0:
        return 0.0
    return float(sum(b.n * abs(b.error) for b in bins) / total)


def calibration_report(probs: Sequence[float], outcomes: Sequence[int], n_bins: int = 10) -> str:
    lines = [
        f"{'bucket':>12}  {'n':>6}  {'pred':>7}  {'actual':>7}  {'diff':>7}",
        "-" * 46,
    ]
    for b in calibration(probs, outcomes, n_bins):
        lines.append(
            f"{b.lo:.2f}-{b.hi:.2f}".rjust(12)
            + f"  {b.n:>6}  {b.mean_pred:>6.1%}  {b.observed:>6.1%}  {b.error:>+6.1%}"
        )
    lines.append("-" * 46)
    lines.append(f"ECE {expected_calibration_error(probs, outcomes, n_bins):.4f}")
    return "\n".join(lines)


def evaluate(probs: Sequence[float], outcomes: Sequence[int]) -> dict[str, float]:
    """The standard bundle of headline numbers."""
    return {
        "n": int(len(list(outcomes))),
        "log_loss": log_loss(probs, outcomes),
        "brier": brier_score(probs, outcomes),
        "accuracy": accuracy(probs, outcomes),
        "skill_score": skill_score(probs, outcomes),
        "ece": expected_calibration_error(probs, outcomes),
    }


def ats_record(
    predicted_margins: Sequence[float],
    actual_margins: Sequence[float],
    market_spreads: Sequence[float],
    threshold: float = 0.0,
) -> dict[str, float]:
    """Against-the-spread record when betting every game the model disagrees on.

    ``market_spreads`` is the home line (-3.5 == home laying 3.5).  A bet is
    placed on the home side when the model's margin beats the line by more than
    ``threshold`` points, and on the away side when it falls short by that much.
    """
    pm = np.asarray(predicted_margins, dtype=float)
    am = np.asarray(actual_margins, dtype=float)
    sp = np.asarray(market_spreads, dtype=float)

    disagreement = pm + sp  # >0 -> model likes the home side
    bet = np.where(np.abs(disagreement) > threshold, np.sign(disagreement), 0)
    result = np.sign(am + sp)  # >0 -> home covered

    wins = int(np.sum((bet != 0) & (bet == result)))
    losses = int(np.sum((bet != 0) & (result != 0) & (bet != result)))
    pushes = int(np.sum((bet != 0) & (result == 0)))
    decided = wins + losses
    win_pct = wins / decided if decided else 0.0
    # -110 pricing: 52.38% is break-even.
    units = wins * (100 / 110) - losses
    return {
        "bets": int(np.sum(bet != 0)),
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_pct": float(win_pct),
        "units_at_-110": float(units),
        "roi": float(units / decided) if decided else 0.0,
    }
