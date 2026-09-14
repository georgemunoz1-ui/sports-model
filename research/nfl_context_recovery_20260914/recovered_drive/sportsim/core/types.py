"""Core data types shared by every sport module."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Sequence

import numpy as np

Number = Any  # float or np.ndarray -- every rating field is broadcast-friendly


@dataclass
class TeamRating:
    """Strength description for one team.

    The numeric fields are multiplicative and centred on 1.0, so an ``attack``
    of 1.08 means "scores 8% more than a league-average team against a
    league-average opponent" and a ``defense`` of 0.95 means "allows 5% fewer
    points than average" (lower is better).

    Every numeric field may also be a numpy array.  Simulators are written with
    pure elementwise math, so passing arrays of length ``n`` simulates ``n``
    games with per-simulation ratings -- that is what the season Monte Carlo
    uses to inject rating uncertainty.
    """

    team: str = "TEAM"
    elo: Number = 1500.0
    attack: Number = 1.0
    defense: Number = 1.0
    pace: Number = 1.0

    def with_noise(self, rng: np.random.Generator, sd: float, n: int) -> "TeamRating":
        """Return a copy whose attack/defense are jittered ``n`` independent ways.

        ``sd`` is expressed as a fraction of team strength (0.03 == 3%).
        """
        if sd <= 0:
            return self
        a = np.asarray(self.attack) * np.exp(rng.normal(0.0, sd, n))
        d = np.asarray(self.defense) * np.exp(rng.normal(0.0, sd, n))
        return replace(self, attack=a, defense=d)


@dataclass
class Game:
    """A single scheduled or completed game."""

    home: str
    away: str
    home_score: int | None = None
    away_score: int | None = None
    date: str | None = None
    neutral: bool = False
    went_ot: bool = False
    season: int | None = None

    @property
    def played(self) -> bool:
        return self.home_score is not None and self.away_score is not None

    @property
    def margin(self) -> int:
        """Home score minus away score."""
        if not self.played:
            raise ValueError("game has no result")
        return int(self.home_score) - int(self.away_score)

    @property
    def total(self) -> int:
        if not self.played:
            raise ValueError("game has no result")
        return int(self.home_score) + int(self.away_score)

    @property
    def home_won(self) -> bool:
        return self.margin > 0


@dataclass
class ScoreSamples:
    """Monte Carlo output: aligned arrays of simulated final scores."""

    home: np.ndarray
    away: np.ndarray
    ot: np.ndarray | None = None
    home_team: str = "HOME"
    away_team: str = "AWAY"

    def __post_init__(self) -> None:
        self.home = np.asarray(self.home)
        self.away = np.asarray(self.away)
        if self.home.shape != self.away.shape:
            raise ValueError("home/away sample arrays must be the same shape")
        if self.ot is None:
            self.ot = np.zeros(self.home.shape, dtype=bool)

    def __len__(self) -> int:
        return int(self.home.size)

    @property
    def margin(self) -> np.ndarray:
        return self.home - self.away

    @property
    def total(self) -> np.ndarray:
        return self.home + self.away

    def forecast(self) -> "GameForecast":
        return GameForecast(self)


@dataclass
class GameForecast:
    """Turns raw simulated scores into the numbers a bettor/analyst wants."""

    samples: ScoreSamples

    # ---- win probability -------------------------------------------------
    @property
    def home_win_prob(self) -> float:
        m = self.samples.margin
        # Simulators resolve ties, but guard anyway: split any remaining pushes.
        return float((m > 0).mean() + 0.5 * (m == 0).mean())

    @property
    def away_win_prob(self) -> float:
        return 1.0 - self.home_win_prob

    # ---- margin / total --------------------------------------------------
    @property
    def mean_margin(self) -> float:
        return float(self.samples.margin.mean())

    @property
    def median_margin(self) -> float:
        return float(np.median(self.samples.margin))

    @property
    def mean_total(self) -> float:
        return float(self.samples.total.mean())

    @property
    def mean_home_score(self) -> float:
        return float(self.samples.home.mean())

    @property
    def mean_away_score(self) -> float:
        return float(self.samples.away.mean())

    @property
    def ot_prob(self) -> float:
        return float(np.asarray(self.samples.ot).mean())

    def score_interval(self, level: float = 0.9) -> tuple[tuple[float, float], tuple[float, float]]:
        """Central credible intervals for each team's score."""
        lo, hi = (1 - level) / 2 * 100, (1 + level) / 2 * 100
        return (
            (float(np.percentile(self.samples.home, lo)), float(np.percentile(self.samples.home, hi))),
            (float(np.percentile(self.samples.away, lo)), float(np.percentile(self.samples.away, hi))),
        )

    # ---- market-shaped questions ----------------------------------------
    def cover_prob(self, spread: float) -> float:
        """P(home team covers ``spread``), where -3.5 means home laying 3.5.

        Pushes are split, matching how a graded bet's break-even is computed.
        """
        adj = self.samples.margin + spread
        return float((adj > 0).mean() + 0.5 * (adj == 0).mean())

    def over_prob(self, total: float) -> float:
        t = self.samples.total
        return float((t > total).mean() + 0.5 * (t == total).mean())

    def fair_spread(self) -> float:
        """The spread that makes the game a coin flip (home perspective)."""
        return -self.median_margin

    def team_total_over_prob(self, team: str, line: float) -> float:
        arr = self.samples.home if team == self.samples.home_team else self.samples.away
        return float((arr > line).mean() + 0.5 * (arr == line).mean())

    def margin_distribution(self) -> dict[int, float]:
        vals, counts = np.unique(self.samples.margin, return_counts=True)
        n = counts.sum()
        return {int(v): float(c / n) for v, c in zip(vals, counts)}

    # ---- reporting -------------------------------------------------------
    def to_dict(self) -> dict[str, float | str]:
        return {
            "home": self.samples.home_team,
            "away": self.samples.away_team,
            "home_win_prob": round(self.home_win_prob, 4),
            "away_win_prob": round(self.away_win_prob, 4),
            "mean_home_score": round(self.mean_home_score, 2),
            "mean_away_score": round(self.mean_away_score, 2),
            "fair_spread": round(self.fair_spread(), 1),
            "mean_total": round(self.mean_total, 2),
            "ot_prob": round(self.ot_prob, 4),
            "n_sims": len(self.samples),
        }

    def report(self) -> str:
        from .market import prob_to_american

        h, a = self.samples.home_team, self.samples.away_team
        (hlo, hhi), (alo, ahi) = self.score_interval(0.8)
        spread = self.fair_spread()
        sign = "+" if spread > 0 else ""
        lines = [
            f"{a} @ {h}   ({len(self.samples):,} simulations)",
            "-" * 52,
            f"  {h:<20} {self.mean_home_score:6.1f}   win {self.home_win_prob:6.1%}"
            f"   ML {prob_to_american(self.home_win_prob):+d}",
            f"  {a:<20} {self.mean_away_score:6.1f}   win {self.away_win_prob:6.1%}"
            f"   ML {prob_to_american(self.away_win_prob):+d}",
            "-" * 52,
            f"  fair spread  {h} {sign}{spread:.1f}",
            f"  fair total   {self.mean_total:.1f}",
            f"  80% score range   {h} {hlo:.0f}-{hhi:.0f}   {a} {alo:.0f}-{ahi:.0f}",
        ]
        if self.ot_prob > 0.001:
            lines.append(f"  overtime     {self.ot_prob:.1%}")
        return "\n".join(lines)

    def __str__(self) -> str:  # pragma: no cover - thin wrapper
        return self.report()


@dataclass
class LeagueStructure:
    """Conference / division membership used for standings and playoff seeding."""

    name: str
    # {conference: {division: [teams]}}
    conferences: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    @property
    def teams(self) -> list[str]:
        out: list[str] = []
        for divisions in self.conferences.values():
            for members in divisions.values():
                out.extend(members)
        return out

    def conference_of(self, team: str) -> str:
        for conf, divisions in self.conferences.items():
            for members in divisions.values():
                if team in members:
                    return conf
        raise KeyError(f"unknown team: {team}")

    def division_of(self, team: str) -> str:
        for divisions in self.conferences.values():
            for div, members in divisions.items():
                if team in members:
                    return div
        raise KeyError(f"unknown team: {team}")

    def teams_in_conference(self, conference: str) -> list[str]:
        return [t for members in self.conferences[conference].values() for t in members]

    @classmethod
    def flat(cls, name: str, teams: Iterable[str], n_conferences: int = 2, n_divisions: int = 2) -> "LeagueStructure":
        """Build a synthetic balanced structure -- handy for tests and demos."""
        teams = list(teams)
        conferences: dict[str, dict[str, list[str]]] = {}
        per_conf = len(teams) // n_conferences
        for c in range(n_conferences):
            chunk = teams[c * per_conf : (c + 1) * per_conf] if c < n_conferences - 1 else teams[c * per_conf :]
            per_div = max(1, len(chunk) // n_divisions)
            divisions: dict[str, list[str]] = {}
            for d in range(n_divisions):
                sl = chunk[d * per_div : (d + 1) * per_div] if d < n_divisions - 1 else chunk[d * per_div :]
                divisions[f"C{c + 1}D{d + 1}"] = list(sl)
            conferences[f"Conference {c + 1}"] = divisions
        return cls(name=name, conferences=conferences)


def teams_from_games(games: Sequence[Game]) -> list[str]:
    seen: dict[str, None] = {}
    for g in games:
        seen.setdefault(g.home, None)
        seen.setdefault(g.away, None)
    return sorted(seen)

