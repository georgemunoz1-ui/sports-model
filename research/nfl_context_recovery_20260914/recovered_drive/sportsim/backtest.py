"""Walk-forward backtesting.

The only honest way to score a sports model is to predict each game using
nothing but the games that came before it.  Fitting on a full season and then
"predicting" games inside that season will produce a log loss you cannot
reproduce live, because the ratings already contain the answers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from .core.metrics import ats_record, calibration_report, evaluate, margin_errors
from .core.ratings import EloConfig, EloModel, fit_poisson_strength, fit_ridge_margin
from .core.types import Game
from .sports import get_simulator


@dataclass
class BacktestResult:
    """Out-of-sample predictions and their scores."""

    label: str
    probs: list[float] = field(default_factory=list)
    outcomes: list[int] = field(default_factory=list)
    predicted_margins: list[float] = field(default_factory=list)
    actual_margins: list[float] = field(default_factory=list)
    games: list[Game] = field(default_factory=list)

    def metrics(self) -> dict[str, float]:
        out = evaluate(self.probs, self.outcomes)
        if self.predicted_margins:
            out.update({f"margin_{k}": v for k, v in margin_errors(self.predicted_margins, self.actual_margins).items()})
        return out

    def ats(self, market_spreads: Sequence[float], threshold: float = 0.0) -> dict[str, float]:
        """ATS record against a set of market spreads (home line per game)."""
        return ats_record(self.predicted_margins, self.actual_margins, market_spreads, threshold)

    def report(self, calibration_bins: int = 10) -> str:
        m = self.metrics()
        lines = [
            f"{self.label}  ({m['n']:,} games)",
            "-" * 46,
            f"  log loss   {m['log_loss']:.4f}",
            f"  brier      {m['brier']:.4f}",
            f"  accuracy   {m['accuracy']:.1%}",
            f"  skill      {m['skill_score']:+.4f}   (vs always predicting the base rate)",
            f"  ECE        {m['ece']:.4f}",
        ]
        if "margin_mae" in m:
            lines.append(f"  margin MAE {m['margin_mae']:.2f}   RMSE {m['margin_rmse']:.2f}   bias {m['margin_bias']:+.2f}")
        lines += ["", calibration_report(self.probs, self.outcomes, calibration_bins)]
        return "\n".join(lines)


def backtest_elo(games: Sequence[Game], sport: str = "nfl", config: EloConfig | None = None) -> BacktestResult:
    """Score Elo's pre-game probabilities as it walks through the season."""
    model = EloModel(config or sport)
    played = [g for g in games if g.played]
    probs, outcomes = model.backtest(played)
    return BacktestResult(
        label=f"Elo ({sport.upper()})",
        probs=probs,
        outcomes=outcomes,
        games=played,
    )


def walk_forward(
    games: Sequence[Game],
    sport: str,
    method: str = "simulator",
    min_games: int = 150,
    refit_every: int = 50,
    sims: int = 4_000,
    decay_half_life: float | None = None,
    shrinkage: float = 0.3,
    rng: np.random.Generator | int | None = 0,
) -> BacktestResult:
    """Refit ratings periodically and predict the games that follow.

    ``method`` is one of:

    * ``simulator`` -- fit attack/defence, then Monte Carlo each matchup. Gives
      win probabilities *and* score distributions.
    * ``ridge`` -- ridge point ratings with a normal-CDF win probability. Fast,
      and a good baseline for the simulator to beat.

    ``min_games`` is how much history to require before the first prediction;
    ``refit_every`` trades accuracy for speed by reusing ratings for a block of
    games.
    """
    rng = rng if isinstance(rng, np.random.Generator) else np.random.default_rng(rng)
    played = [g for g in games if g.played]
    if len(played) <= min_games:
        raise ValueError(f"need more than {min_games} completed games to backtest; got {len(played)}")

    simulator = get_simulator(sport) if method == "simulator" else None
    result = BacktestResult(label=f"{method} ({sport.upper()})")

    fit = None
    fitted_at = -1
    # Matchup forecasts are reused inside a refit block; leagues that play the
    # same pairing repeatedly (MLB, NHL) get most of their speed from this.
    block_cache: dict[tuple[str, str], tuple[float, float]] = {}

    for i in range(min_games, len(played)):
        if fit is None or i - fitted_at >= refit_every:
            history = played[:i]
            fit = (
                fit_poisson_strength(history, shrinkage=shrinkage, decay_half_life=decay_half_life)
                if method == "simulator"
                else fit_ridge_margin(history)
            )
            fitted_at = i
            block_cache.clear()

        g = played[i]
        key = (g.home, g.away)
        if key in block_cache:
            p_home, pred_margin = block_cache[key]
        elif method == "simulator":
            f = simulator.forecast(fit.rating(g.home), fit.rating(g.away), n=sims, rng=rng, neutral=g.neutral)
            p_home, pred_margin = f.home_win_prob, f.mean_margin
            block_cache[key] = (p_home, pred_margin)
        else:
            p_home = fit.win_prob(g.home, g.away, g.neutral)
            pred_margin = fit.predicted_margin(g.home, g.away, g.neutral)
            block_cache[key] = (p_home, pred_margin)

        result.probs.append(float(np.clip(p_home, 1e-6, 1 - 1e-6)))
        result.outcomes.append(1 if g.margin > 0 else 0)
        result.predicted_margins.append(pred_margin)
        result.actual_margins.append(float(g.margin))
        result.games.append(g)

    return result


def backtest_simulator(games: Sequence[Game], sport: str, **kwargs) -> BacktestResult:
    """Convenience wrapper for :func:`walk_forward` with the simulator method."""
    return walk_forward(games, sport, method="simulator", **kwargs)


def _trim(result: BacktestResult, skip: int) -> BacktestResult:
    """Drop the first ``skip`` predictions so two models cover the same games."""
    return BacktestResult(
        label=result.label,
        probs=result.probs[skip:],
        outcomes=result.outcomes[skip:],
        predicted_margins=result.predicted_margins[skip:],
        actual_margins=result.actual_margins[skip:],
        games=result.games[skip:],
    )


def compare_models(games: Sequence[Game], sport: str, min_games: int = 150, **kwargs) -> str:
    """Run Elo, ridge and the simulator over the same games and print a table.

    Elo is warmed up on the same leading games the other two use to fit, so all
    three are scored on an identical set of predictions.
    """
    results = [
        _trim(backtest_elo(games, sport), min_games),
        walk_forward(games, sport, method="ridge", min_games=min_games, **kwargs),
        walk_forward(games, sport, method="simulator", min_games=min_games, **kwargs),
    ]
    lines = [f"{'model':<22} {'n':>6} {'log loss':>9} {'brier':>8} {'acc':>7} {'skill':>8}", "-" * 60]
    for r in results:
        m = r.metrics()
        lines.append(
            f"{r.label:<22} {m['n']:>6} {m['log_loss']:>9.4f} {m['brier']:>8.4f} {m['accuracy']:>6.1%} {m['skill_score']:>+8.4f}"
        )
    return "\n".join(lines)

