"""Team rating models.

Three complementary estimators:

* :class:`EloModel` -- online, chronological, reacts to recent form.
* :func:`fit_poisson_strength` -- multiplicative attack/defence multipliers,
  the input the game simulators actually consume.
* :func:`fit_ridge_margin` -- ridge-regularised point ratings plus a fitted
  home-field advantage, useful as a sanity check and for margin predictions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np

from .types import Game, TeamRating, teams_from_games


# --------------------------------------------------------------------------
# Elo
# --------------------------------------------------------------------------
@dataclass
class EloConfig:
    """Tuning knobs for the Elo updater.

    ``k`` sets how fast ratings move, ``home_advantage`` is in rating points,
    ``mov_factor`` enables the margin-of-victory multiplier with autocorrelation
    damping, and ``season_regression`` pulls ratings toward the mean between
    seasons (0.25 == give back a quarter of the deviation from 1500).
    """

    k: float = 20.0
    home_advantage: float = 55.0
    scale: float = 400.0
    mov_factor: bool = True
    mov_scale: float = 2.2
    season_regression: float = 0.25
    initial: float = 1500.0


ELO_PRESETS: dict[str, EloConfig] = {
    # Roughly the values that minimise log loss on each league's history; the
    # pattern is intuitive -- a 16-game NFL season needs a big K, a 162-game
    # MLB season needs a tiny one.
    "nfl": EloConfig(k=20.0, home_advantage=48.0, mov_factor=True, season_regression=0.33),
    "nba": EloConfig(k=20.0, home_advantage=85.0, mov_factor=True, season_regression=0.25),
    "nhl": EloConfig(k=6.0, home_advantage=50.0, mov_factor=True, season_regression=0.30),
    "mlb": EloConfig(k=4.0, home_advantage=24.0, mov_factor=False, season_regression=0.35),
}


class EloModel:
    """Chronological Elo with margin-of-victory scaling.

    Feed it games in date order; it exposes a probability before each update so
    the same pass produces both ratings and an honest out-of-sample backtest.
    """

    def __init__(self, config: EloConfig | str = "nfl", ratings: dict[str, float] | None = None):
        if isinstance(config, str):
            config = ELO_PRESETS[config.lower()]
        self.config = config
        self.ratings: dict[str, float] = dict(ratings or {})
        self.history: list[tuple[str, str, float, float]] = []

    # -- access ------------------------------------------------------------
    def get(self, team: str) -> float:
        return self.ratings.setdefault(team, self.config.initial)

    def __getitem__(self, team: str) -> float:
        return self.get(team)

    def rating_diff(self, home: str, away: str, neutral: bool = False) -> float:
        hfa = 0.0 if neutral else self.config.home_advantage
        return self.get(home) - self.get(away) + hfa

    def win_prob(self, home: str, away: str, neutral: bool = False) -> float:
        """P(home wins) from the logistic Elo curve."""
        return 1.0 / (1.0 + 10 ** (-self.rating_diff(home, away, neutral) / self.config.scale))

    # -- updating ----------------------------------------------------------
    def update(self, game: Game) -> float:
        """Apply one result and return the pre-game home win probability."""
        if not game.played:
            raise ValueError("cannot update Elo from an unplayed game")
        p_home = self.win_prob(game.home, game.away, game.neutral)
        margin = game.margin
        actual = 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5

        k = self.config.k
        if self.config.mov_factor and margin != 0:
            diff = self.rating_diff(game.home, game.away, game.neutral)
            # Damp the multiplier by the winner's rating edge, otherwise good
            # teams run away with the ratings after routine blowouts.
            winner_diff = diff if margin > 0 else -diff
            mult = math.log(abs(margin) + 1.0) * (self.config.mov_scale / (winner_diff * 0.001 + self.config.mov_scale))
            k *= mult

        delta = k * (actual - p_home)
        self.ratings[game.home] = self.get(game.home) + delta
        self.ratings[game.away] = self.get(game.away) - delta
        self.history.append((game.date or "", f"{game.away}@{game.home}", p_home, actual))
        return p_home

    def regress_to_mean(self, factor: float | None = None) -> None:
        """Between-season regression toward the league mean."""
        f = self.config.season_regression if factor is None else factor
        mean = self.config.initial
        for team, r in self.ratings.items():
            self.ratings[team] = mean + (r - mean) * (1.0 - f)

    def fit(self, games: Sequence[Game]) -> "EloModel":
        """Walk forward through games in order, regressing between seasons."""
        current_season = None
        for g in games:
            if not g.played:
                continue
            if g.season is not None and current_season is not None and g.season != current_season:
                self.regress_to_mean()
            current_season = g.season if g.season is not None else current_season
            self.update(g)
        return self

    def backtest(self, games: Sequence[Game]) -> tuple[list[float], list[int]]:
        """Fit and collect (pre-game probability, outcome) pairs for scoring."""
        probs: list[float] = []
        outcomes: list[int] = []
        current_season = None
        for g in games:
            if not g.played:
                continue
            if g.season is not None and current_season is not None and g.season != current_season:
                self.regress_to_mean()
            current_season = g.season if g.season is not None else current_season
            probs.append(self.update(g))
            outcomes.append(1 if g.margin > 0 else 0)
        return probs, outcomes

    def table(self) -> list[tuple[str, float]]:
        return sorted(self.ratings.items(), key=lambda kv: -kv[1])


def elo_to_win_prob(rating_diff: float, scale: float = 400.0) -> float:
    return 1.0 / (1.0 + 10 ** (-rating_diff / scale))


# --------------------------------------------------------------------------
# Multiplicative attack / defence (the simulator's input)
# --------------------------------------------------------------------------
@dataclass
class StrengthFit:
    """Result of :func:`fit_poisson_strength`."""

    attack: dict[str, float]
    defense: dict[str, float]
    league_mean: float
    home_factor: float
    pace: dict[str, float] = field(default_factory=dict)
    n_games: int = 0

    def rating(self, team: str) -> TeamRating:
        return TeamRating(
            team=team,
            attack=self.attack.get(team, 1.0),
            defense=self.defense.get(team, 1.0),
            pace=self.pace.get(team, 1.0),
        )

    def ratings(self) -> dict[str, TeamRating]:
        return {t: self.rating(t) for t in sorted(self.attack)}

    def expected_score(self, home: str, away: str, neutral: bool = False) -> tuple[float, float]:
        hf = 1.0 if neutral else self.home_factor
        h = self.league_mean * self.attack.get(home, 1.0) * self.defense.get(away, 1.0) * math.sqrt(hf)
        a = self.league_mean * self.attack.get(away, 1.0) * self.defense.get(home, 1.0) / math.sqrt(hf)
        return h, a

    def table(self) -> list[tuple[str, float, float, float]]:
        """(team, attack, defense, net) sorted by net rating."""
        rows = [
            (t, self.attack[t], self.defense[t], self.attack[t] - self.defense[t])
            for t in self.attack
        ]
        return sorted(rows, key=lambda r: -r[3])


#: How hard to regress each league's ratings toward average, and how quickly to
#: forget old games.  A 17-game NFL season carries far less signal per team than
#: a 162-game MLB season, so it needs much heavier shrinkage; MLB and the NBA
#: can afford to weight recent form instead.
FIT_PRESETS: dict[str, dict[str, float | None]] = {
    "nfl": {"shrinkage": 0.85, "decay_half_life": 40.0},
    "nba": {"shrinkage": 0.30, "decay_half_life": 400.0},
    "nhl": {"shrinkage": 0.45, "decay_half_life": 450.0},
    "mlb": {"shrinkage": 0.40, "decay_half_life": 900.0},
}


def fit_for_sport(games: Sequence[Game], sport: str, **overrides) -> "StrengthFit":
    """Fit strength ratings using sensible per-league defaults.

    ``decay_half_life`` is measured in games across the whole league, so the NFL
    value of 40 is roughly "the last two and a half weeks count double".
    """
    params = dict(FIT_PRESETS.get(sport.lower(), {"shrinkage": 0.3, "decay_half_life": None}))
    params.update(overrides)
    return fit_poisson_strength(games, **params)


def fit_poisson_strength(
    games: Sequence[Game],
    shrinkage: float = 0.25,
    iterations: int = 60,
    fit_pace: bool = False,
    decay_half_life: float | None = None,
) -> StrengthFit:
    """Fit multiplicative attack/defence multipliers from final scores.

    This is the classic Dixon-Coles style factorisation solved by iterative
    proportional fitting: a team's attack rating is its goals scored divided by
    what an average team would have scored against the same opponents.

    ``shrinkage`` regularises toward 1.0 as a fraction of a team's expected
    output -- 0.25 is roughly "add a quarter-season of league-average games",
    which keeps a 3-0 start from producing an absurd rating.
    ``decay_half_life`` (in games, most recent = index -1) down-weights old
    results so the fit tracks in-season form.
    """
    played = [g for g in games if g.played]
    if not played:
        raise ValueError("no completed games to fit")
    teams = teams_from_games(played)
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    h_idx = np.array([idx[g.home] for g in played])
    a_idx = np.array([idx[g.away] for g in played])
    hs = np.array([g.home_score for g in played], dtype=float)
    as_ = np.array([g.away_score for g in played], dtype=float)
    neutral = np.array([g.neutral for g in played], dtype=bool)

    if decay_half_life:
        age = np.arange(len(played) - 1, -1, -1, dtype=float)
        w = 0.5 ** (age / float(decay_half_life))
    else:
        w = np.ones(len(played))

    league_mean = float(np.average(np.concatenate([hs, as_]), weights=np.concatenate([w, w])))
    home_total = float(np.average(hs, weights=w))
    away_total = float(np.average(as_, weights=w))
    home_factor = home_total / away_total if away_total > 0 else 1.0

    # Split the home effect symmetrically so the league mean is preserved.
    hf_home = np.where(neutral, 1.0, math.sqrt(home_factor))
    hf_away = np.where(neutral, 1.0, 1.0 / math.sqrt(home_factor))

    attack = np.ones(n)
    defense = np.ones(n)

    gf = np.bincount(h_idx, weights=w * hs, minlength=n) + np.bincount(a_idx, weights=w * as_, minlength=n)
    ga = np.bincount(h_idx, weights=w * as_, minlength=n) + np.bincount(a_idx, weights=w * hs, minlength=n)
    # What a league-average team would have scored on the same schedule.
    flat = league_mean * (
        np.bincount(h_idx, weights=w * hf_home, minlength=n) + np.bincount(a_idx, weights=w * hf_away, minlength=n)
    )
    prior = shrinkage * flat

    for _ in range(iterations):
        exp_for = league_mean * (
            np.bincount(h_idx, weights=w * hf_home * defense[a_idx], minlength=n)
            + np.bincount(a_idx, weights=w * hf_away * defense[h_idx], minlength=n)
        )
        attack = (gf + prior) / np.maximum(exp_for + prior, 1e-9)

        exp_against = league_mean * (
            np.bincount(h_idx, weights=w * hf_away * attack[a_idx], minlength=n)
            + np.bincount(a_idx, weights=w * hf_home * attack[h_idx], minlength=n)
        )
        defense = (ga + prior) / np.maximum(exp_against + prior, 1e-9)

        # Identifiability: attack and defense are only defined up to a scalar.
        attack /= np.exp(np.mean(np.log(np.maximum(attack, 1e-9))))
        defense /= np.exp(np.mean(np.log(np.maximum(defense, 1e-9))))

    pace: dict[str, float] = {}
    if fit_pace:
        totals = hs + as_
        league_total = float(np.average(totals, weights=w))
        num = np.bincount(h_idx, weights=w * totals, minlength=n) + np.bincount(a_idx, weights=w * totals, minlength=n)
        den = np.bincount(h_idx, weights=w, minlength=n) + np.bincount(a_idx, weights=w, minlength=n)
        raw = (num / np.maximum(den, 1e-9)) / league_total
        # A game's pace is set by both teams, so a team's own effect is roughly
        # twice its deviation from average.
        pace = {t: float(1.0 + 2.0 * (raw[i] - 1.0) * (1.0 - shrinkage)) for t, i in idx.items()}

    return StrengthFit(
        attack={t: float(attack[i]) for t, i in idx.items()},
        defense={t: float(defense[i]) for t, i in idx.items()},
        league_mean=league_mean,
        home_factor=home_factor,
        pace=pace,
        n_games=len(played),
    )


# --------------------------------------------------------------------------
# Ridge point ratings
# --------------------------------------------------------------------------
@dataclass
class MarginFit:
    """Additive point ratings: margin ~= rating[home] - rating[away] + hfa."""

    ratings: dict[str, float]
    home_advantage: float
    residual_sd: float
    n_games: int

    def predicted_margin(self, home: str, away: str, neutral: bool = False) -> float:
        hfa = 0.0 if neutral else self.home_advantage
        return self.ratings.get(home, 0.0) - self.ratings.get(away, 0.0) + hfa

    def win_prob(self, home: str, away: str, neutral: bool = False) -> float:
        """Normal-CDF win probability implied by the margin model."""
        mu = self.predicted_margin(home, away, neutral)
        z = mu / max(self.residual_sd, 1e-9)
        return float(0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))

    def table(self) -> list[tuple[str, float]]:
        return sorted(self.ratings.items(), key=lambda kv: -kv[1])


def fit_ridge_margin(games: Sequence[Game], ridge: float = 3.0, cap_margin: float | None = None) -> MarginFit:
    """Least-squares team point ratings with an L2 penalty and fitted HFA.

    ``ridge`` shrinks toward an even league (higher = flatter ratings);
    ``cap_margin`` truncates blowouts, which is standard practice because a
    45-point win says little more about team quality than a 25-point one.
    """
    played = [g for g in games if g.played]
    if not played:
        raise ValueError("no completed games to fit")
    teams = teams_from_games(played)
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)

    X = np.zeros((len(played), n + 1))
    y = np.zeros(len(played))
    for r, g in enumerate(played):
        X[r, idx[g.home]] = 1.0
        X[r, idx[g.away]] = -1.0
        if not g.neutral:
            X[r, n] = 1.0
        m = float(g.margin)
        if cap_margin is not None:
            m = float(np.clip(m, -cap_margin, cap_margin))
        y[r] = m

    penalty = np.eye(n + 1) * ridge
    penalty[n, n] = 0.0  # never shrink the home-field term
    # Pin the mean rating to zero so the system is identifiable.
    sum_row = np.zeros((1, n + 1))
    sum_row[0, :n] = 1.0
    X_aug = np.vstack([X, sum_row * 1000.0])
    y_aug = np.concatenate([y, [0.0]])

    beta = np.linalg.solve(X_aug.T @ X_aug + penalty, X_aug.T @ y_aug)
    resid = y - X @ beta
    dof = max(len(played) - n, 1)
    return MarginFit(
        ratings={t: float(beta[i]) for t, i in idx.items()},
        home_advantage=float(beta[n]),
        residual_sd=float(np.sqrt(np.sum(resid**2) / dof)),
        n_games=len(played),
    )


def blend_ratings(
    strength: StrengthFit,
    elo: EloModel | None = None,
    elo_weight: float = 0.0,
    sensitivity: float = 0.0008,
) -> dict[str, TeamRating]:
    """Attach Elo to the strength ratings and optionally nudge attack/defence.

    Score-based strength ratings are stable; Elo reacts faster to recent form.
    ``elo_weight`` (0-1) controls how much of the Elo deviation from 1500 is
    folded into the scoring multipliers, split evenly between attack and
    defence.  ``sensitivity`` converts rating points into log-scoring units.
    """
    out = strength.ratings()
    if elo is None:
        return out
    for team, rating in out.items():
        rating.elo = elo.get(team)
        if elo_weight > 0:
            adj = elo_weight * (rating.elo - elo.config.initial) * sensitivity
            rating.attack = float(rating.attack * math.exp(adj / 2))
            rating.defense = float(rating.defense * math.exp(-adj / 2))
    return out

