"""Odds conversion, vig removal, and staking.

Everything here is plain probability arithmetic -- the point is to make model
output comparable with a posted price, and to size a bet once you believe you
have an edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np


# --------------------------------------------------------------------------
# odds formats
# --------------------------------------------------------------------------
def american_to_prob(odds: float) -> float:
    """Implied probability of an American price (includes the vig)."""
    odds = float(odds)
    if odds == 0:
        raise ValueError("American odds cannot be 0")
    return 100.0 / (odds + 100.0) if odds > 0 else -odds / (-odds + 100.0)


def prob_to_american(prob: float) -> int:
    """Fair American price for a probability. 0.5 -> +100."""
    p = float(prob)
    if not 0.0 < p < 1.0:
        raise ValueError("probability must be strictly between 0 and 1")
    # A true coin flip is quoted +100, so only a real favourite goes negative.
    if p > 0.5:
        return -int(round(100.0 * p / (1.0 - p)))
    return int(round(100.0 * (1.0 - p) / p))


def american_to_decimal(odds: float) -> float:
    odds = float(odds)
    return 1.0 + (odds / 100.0 if odds > 0 else 100.0 / -odds)


def decimal_to_american(decimal: float) -> int:
    d = float(decimal)
    if d < 1.0:
        raise ValueError("decimal odds must be >= 1")
    return int(round((d - 1.0) * 100.0)) if d >= 2.0 else -int(round(100.0 / (d - 1.0)))


def decimal_to_prob(decimal: float) -> float:
    return 1.0 / float(decimal)


# --------------------------------------------------------------------------
# vig removal
# --------------------------------------------------------------------------
def overround(implied: Sequence[float]) -> float:
    """Sum of implied probabilities. 1.045 == 4.5% hold on a two-way market."""
    return float(np.sum(implied))


def remove_vig(implied: Sequence[float], method: str = "multiplicative") -> np.ndarray:
    """Strip the bookmaker margin from a set of implied probabilities.

    ``multiplicative`` simply normalises, which over-prices longshots.
    ``power`` solves for the exponent k with sum(p**k) == 1 and is the better
    default for lopsided markets (heavy favourites, futures).
    ``shin`` estimates the insider-trading proportion z and is closest to
    "true" prices on two-way markets.
    """
    p = np.asarray(implied, dtype=float)
    if p.ndim != 1 or p.size < 2:
        raise ValueError("need at least two implied probabilities")
    if np.any(p <= 0):
        raise ValueError("implied probabilities must be positive")

    if method == "multiplicative":
        return p / p.sum()

    if method == "power":
        lo, hi = 0.01, 10.0
        for _ in range(200):
            k = 0.5 * (lo + hi)
            if np.sum(p**k) > 1.0:
                lo = k
            else:
                hi = k
        k = 0.5 * (lo + hi)
        out = p**k
        return out / out.sum()

    if method == "shin":
        s = p.sum()
        z = 0.0
        for _ in range(200):
            root = np.sqrt(z * z + 4.0 * (1.0 - z) * p * p / s)
            fair = (root - z) / (2.0 * (1.0 - z)) if z < 1 else p / s
            diff = fair.sum() - 1.0
            if abs(diff) < 1e-12:
                break
            z += diff * 0.5
            z = min(max(z, 0.0), 0.5)
        root = np.sqrt(z * z + 4.0 * (1.0 - z) * p * p / s)
        fair = (root - z) / (2.0 * (1.0 - z))
        return fair / fair.sum()

    raise ValueError(f"unknown de-vig method: {method}")


def no_vig_probs(odds: Sequence[float], method: str = "power") -> np.ndarray:
    """De-vigged probabilities straight from American prices."""
    return remove_vig([american_to_prob(o) for o in odds], method=method)


# --------------------------------------------------------------------------
# staking / edge
# --------------------------------------------------------------------------
def expected_value(prob: float, american_odds: float, stake: float = 1.0) -> float:
    """Expected profit per ``stake`` units risked."""
    dec = american_to_decimal(american_odds)
    return stake * (prob * (dec - 1.0) - (1.0 - prob))


def kelly_fraction(prob: float, american_odds: float, fraction: float = 1.0, cap: float = 0.05) -> float:
    """Kelly stake as a fraction of bankroll.

    ``fraction`` scales the full Kelly bet (0.25 == quarter Kelly, which is the
    usual choice once you admit the model's probability is itself uncertain).
    ``cap`` bounds the result; returns 0.0 when there is no edge.
    """
    b = american_to_decimal(american_odds) - 1.0
    q = 1.0 - prob
    f = (b * prob - q) / b
    if f <= 0:
        return 0.0
    return float(min(f * fraction, cap))


@dataclass
class BetEdge:
    """One model-vs-market comparison."""

    label: str
    model_prob: float
    market_odds: float
    market_prob: float
    fair_odds: int
    edge: float
    ev_per_unit: float
    kelly: float

    def __str__(self) -> str:
        return (
            f"{self.label:<28} model {self.model_prob:6.1%}  market {self.market_prob:6.1%}"
            f"  edge {self.edge:+6.2%}  EV {self.ev_per_unit:+6.3f}u  kelly {self.kelly:5.2%}"
        )


def find_edge(
    label: str,
    model_prob: float,
    market_odds: float,
    opposing_odds: float | None = None,
    kelly_multiplier: float = 0.25,
) -> BetEdge:
    """Compare a model probability with a posted price.

    Pass ``opposing_odds`` (the other side of the same market) to de-vig before
    computing the edge -- otherwise the "market probability" carries the hold
    and every bet looks worse than it is.
    """
    if opposing_odds is not None:
        market_prob = float(no_vig_probs([market_odds, opposing_odds])[0])
    else:
        market_prob = american_to_prob(market_odds)
    return BetEdge(
        label=label,
        model_prob=float(model_prob),
        market_odds=float(market_odds),
        market_prob=market_prob,
        fair_odds=prob_to_american(model_prob),
        edge=float(model_prob) - market_prob,
        ev_per_unit=expected_value(model_prob, market_odds),
        kelly=kelly_fraction(model_prob, market_odds, fraction=kelly_multiplier),
    )


def scan_edges(forecast, lines: dict, kelly_multiplier: float = 0.25, min_edge: float = 0.0) -> list[BetEdge]:
    """Compare a :class:`GameForecast` against a book's posted numbers.

    ``lines`` accepts any of::

        {"moneyline": {"home": -140, "away": +120},
         "spread":    {"line": -3.5, "home": -110, "away": -110},
         "total":     {"line": 44.5, "over": -110, "under": -110}}
    """
    edges: list[BetEdge] = []
    home, away = forecast.samples.home_team, forecast.samples.away_team

    ml = lines.get("moneyline")
    if ml:
        edges.append(find_edge(f"ML {home}", forecast.home_win_prob, ml["home"], ml.get("away"), kelly_multiplier))
        edges.append(find_edge(f"ML {away}", forecast.away_win_prob, ml["away"], ml.get("home"), kelly_multiplier))

    sp = lines.get("spread")
    if sp:
        line = float(sp["line"])
        p_home = forecast.cover_prob(line)
        edges.append(find_edge(f"{home} {line:+g}", p_home, sp["home"], sp.get("away"), kelly_multiplier))
        edges.append(find_edge(f"{away} {-line:+g}", 1 - p_home, sp["away"], sp.get("home"), kelly_multiplier))

    tot = lines.get("total")
    if tot:
        line = float(tot["line"])
        p_over = forecast.over_prob(line)
        edges.append(find_edge(f"Over {line:g}", p_over, tot["over"], tot.get("under"), kelly_multiplier))
        edges.append(find_edge(f"Under {line:g}", 1 - p_over, tot["under"], tot.get("over"), kelly_multiplier))

    return sorted((e for e in edges if e.edge >= min_edge), key=lambda e: -e.edge)


def closing_line_value(bet_odds: float, closing_odds: float) -> float:
    """CLV in probability terms -- the most reliable short-run skill signal.

    Positive means you got a better number than the close.
    """
    return american_to_prob(closing_odds) - american_to_prob(bet_odds)

