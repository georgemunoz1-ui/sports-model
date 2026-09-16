"""Full-season Monte Carlo: standings, playoff odds, championship odds.

The engine has three layers, each chosen for speed:

1. **Matchup cache.**  Every distinct pairing is simulated once, in bulk, and
   the resulting score pairs are kept as an empirical distribution.  Replaying a
   season then costs one array index per game instead of a fresh simulation.
2. **Vectorised regular season.**  Games are stepped through in schedule order
   with all seasons in a batch advancing together.
3. **Analytic playoff series.**  Best-of-N probabilities come from an exact
   dynamic program over the home-court pattern rather than more simulation.

Team strength is not known exactly, so the run is split into scenarios: each
scenario jitters the ratings once and holds them for a whole season.  Without
that, playoff odds come out far too confident -- season-long uncertainty about
who is actually good is a bigger driver of the tails than game-to-game variance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from ..core.types import Game, LeagueStructure, TeamRating
from ..leagues import PlayoffFormat, get_league, get_playoff_format, USES_OT_POINTS
from ..sports import GameSimulator, get_simulator
from .playoffs import (
    SeriesOracle,
    run_nhl_bracket,
    run_play_in,
    run_standard_bracket,
    seed_conference,
    seed_nhl_bracket,
)
from .standings import rank_within

#: Season-long uncertainty in each team's true strength, as a fraction of its
#: rating.  A 162-game baseball season pins a team's true quality down far more
#: tightly than 17 NFL games do, so the NFL carries roughly twice the doubt.
RATING_NOISE: dict[str, float] = {"nfl": 0.030, "nba": 0.016, "nhl": 0.020, "mlb": 0.018}

#: Draws per distinct matchup when building the cache.  MLB is simulated plate
#: appearance by plate appearance, so it gets fewer -- it has both the most
#: distinct matchups and the slowest engine.
MATCHUP_SAMPLES: dict[str, int] = {"nfl": 1_500, "nba": 1_500, "nhl": 1_500, "mlb": 600}


@dataclass
class SeasonResult:
    """Per-simulation season outcomes, one row per simulated season."""

    teams: list[str]
    sport: str
    wins: np.ndarray  # (n_sims, n_teams)
    losses: np.ndarray
    ties: np.ndarray
    ot_losses: np.ndarray
    points: np.ndarray  # standings points (hockey-aware)
    points_for: np.ndarray
    points_against: np.ndarray
    made_playoffs: np.ndarray
    division_titles: np.ndarray
    conference_titles: np.ndarray
    championships: np.ndarray
    league: LeagueStructure | None = None

    @property
    def n_sims(self) -> int:
        return int(self.wins.shape[0])

    def team_index(self, team: str) -> int:
        return self.teams.index(team)

    def summary(self) -> list[dict[str, float | str]]:
        """One row per team, sorted by title odds."""
        diff = self.points_for - self.points_against
        rows = []
        for i, t in enumerate(self.teams):
            rows.append(
                {
                    "team": t,
                    "mean_wins": float(self.wins[:, i].mean()),
                    "p5_wins": float(np.percentile(self.wins[:, i], 5)),
                    "p95_wins": float(np.percentile(self.wins[:, i], 95)),
                    "mean_points": float(self.points[:, i].mean()),
                    "mean_diff": float(diff[:, i].mean()),
                    "playoffs": float(self.made_playoffs[:, i].mean()),
                    "division": float(self.division_titles[:, i].mean()),
                    "conference": float(self.conference_titles[:, i].mean()),
                    "title": float(self.championships[:, i].mean()),
                }
            )
        rows.sort(key=lambda r: (-r["title"], -r["mean_wins"]))
        return rows

    def report(self, top: int | None = None) -> str:
        rows = self.summary()
        if top:
            rows = rows[:top]
        out = [
            f"{self.sport.upper()} season projection ({self.n_sims:,} simulated seasons)",
            f"{'team':<6} {'W':>5} {'90% range':>12} {'diff':>7} {'playoff':>8} {'div':>7} {'conf':>7} {'title':>7}",
            "-" * 70,
        ]
        for r in rows:
            out.append(
                f"{r['team']:<6} {r['mean_wins']:>5.1f} "
                f"{r['p5_wins']:>5.0f}-{r['p95_wins']:<6.0f} {r['mean_diff']:>+7.0f} "
                f"{r['playoffs']:>7.1%} {r['division']:>6.1%} {r['conference']:>6.1%} {r['title']:>6.1%}"
            )
        return "\n".join(out)

    def team_report(self, team: str) -> str:
        i = self.team_index(team)
        w = self.wins[:, i]
        return (
            f"{team}: {w.mean():.1f} wins (80% range {np.percentile(w, 10):.0f}-{np.percentile(w, 90):.0f})"
            f" | playoffs {self.made_playoffs[:, i].mean():.1%}"
            f" | division {self.division_titles[:, i].mean():.1%}"
            f" | conference {self.conference_titles[:, i].mean():.1%}"
            f" | title {self.championships[:, i].mean():.1%}"
        )


@dataclass
class _MatchupCache:
    """Empirical score distribution for one ordered (home, away) pairing."""

    home: np.ndarray
    away: np.ndarray
    ot: np.ndarray
    home_win_prob: float


class SeasonSimulator:
    """Monte Carlo a full season, including the playoffs.

    ``ratings`` maps team -> :class:`TeamRating`; any team on the schedule that
    is missing gets a league-average rating.
    """

    def __init__(
        self,
        sport: str,
        ratings: dict[str, TeamRating],
        league: LeagueStructure | None = None,
        simulator: GameSimulator | None = None,
        playoff_format: PlayoffFormat | None = None,
    ):
        self.sport = sport.lower()
        self.ratings = dict(ratings)
        self.league = league if league is not None else get_league(self.sport)
        self.simulator = simulator or get_simulator(self.sport)
        self.playoff_simulator = get_simulator(self.sport, playoff=True)
        self.playoff_format = playoff_format or get_playoff_format(self.sport)
        self.ot_points = USES_OT_POINTS.get(self.sport, False)

    # -- caching -----------------------------------------------------------
    def _rating(self, team: str, jitter: dict[str, TeamRating] | None = None) -> TeamRating:
        source = jitter if jitter is not None else self.ratings
        return source.get(team, TeamRating(team=team))

    def _build_cache(
        self,
        matchups: Sequence[tuple[str, str]],
        ratings: dict[str, TeamRating],
        samples: int,
        rng: np.random.Generator,
    ) -> dict[tuple[str, str], _MatchupCache]:
        pairs = list(dict.fromkeys(matchups))
        if not pairs:
            return {}

        # Every matchup is simulated in a single call by handing the simulator
        # arrays of ratings -- one block of `samples` draws per pairing. Looping
        # in Python instead costs an order of magnitude, most of it in MLB.
        def stack(getter) -> np.ndarray:
            per_pair = np.array([float(np.asarray(getter(p))) for p in pairs])
            return np.repeat(per_pair, samples)

        home = TeamRating(
            team="home",
            attack=stack(lambda p: ratings.get(p[0], TeamRating(p[0])).attack),
            defense=stack(lambda p: ratings.get(p[0], TeamRating(p[0])).defense),
            pace=stack(lambda p: ratings.get(p[0], TeamRating(p[0])).pace),
        )
        away = TeamRating(
            team="away",
            attack=stack(lambda p: ratings.get(p[1], TeamRating(p[1])).attack),
            defense=stack(lambda p: ratings.get(p[1], TeamRating(p[1])).defense),
            pace=stack(lambda p: ratings.get(p[1], TeamRating(p[1])).pace),
        )
        s = self.simulator.simulate(home, away, n=len(pairs) * samples, rng=rng)

        hs = np.asarray(s.home).reshape(len(pairs), samples)
        as_ = np.asarray(s.away).reshape(len(pairs), samples)
        ot = np.asarray(s.ot).reshape(len(pairs), samples)
        margin = hs - as_
        win = (margin > 0).mean(axis=1) + 0.5 * (margin == 0).mean(axis=1)
        return {
            p: _MatchupCache(home=hs[i], away=as_[i], ot=ot[i], home_win_prob=float(win[i]))
            for i, p in enumerate(pairs)
        }

    # -- the regular season ------------------------------------------------
    def _play_regular_season(
        self,
        schedule: Sequence[Game],
        cache: dict[tuple[str, str], _MatchupCache],
        team_idx: dict[str, int],
        n: int,
        rng: np.random.Generator,
    ) -> dict[str, np.ndarray]:
        n_teams = len(team_idx)
        shape = (n, n_teams)
        wins = np.zeros(shape)
        losses = np.zeros(shape)
        ties = np.zeros(shape)
        otl = np.zeros(shape)
        pf = np.zeros(shape)
        pa = np.zeros(shape)

        for g in schedule:
            h, a = team_idx[g.home], team_idx[g.away]
            if g.played:
                # Completed games are facts, not simulations.
                hs = np.full(n, float(g.home_score))
                as_ = np.full(n, float(g.away_score))
                ot = np.full(n, bool(g.went_ot))
            else:
                mc = cache[(g.home, g.away)]
                pick = rng.integers(0, mc.home.size, size=n)
                hs = mc.home[pick].astype(float)
                as_ = mc.away[pick].astype(float)
                ot = mc.ot[pick]

            pf[:, h] += hs
            pa[:, h] += as_
            pf[:, a] += as_
            pa[:, a] += hs

            home_won = hs > as_
            away_won = as_ > hs
            tied = ~home_won & ~away_won

            wins[:, h] += home_won
            wins[:, a] += away_won
            losses[:, h] += away_won
            losses[:, a] += home_won
            ties[:, h] += tied
            ties[:, a] += tied
            if self.ot_points:
                otl[:, h] += away_won & ot
                otl[:, a] += home_won & ot

        points = 2 * wins + otl if self.ot_points else wins + 0.5 * ties
        return {
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "ot_losses": otl,
            "points": points,
            "points_for": pf,
            "points_against": pa,
        }

    # -- the playoffs ------------------------------------------------------
    def _pair_probs(
        self,
        pairs: Sequence[tuple[str, str]],
        reg_cache: dict[tuple[str, str], _MatchupCache],
        ratings: dict[str, TeamRating],
        samples: int,
        rng: np.random.Generator,
    ) -> dict[tuple[str, str], float]:
        """Single-game win probabilities for every pairing the bracket may need.

        Pairings that already appear on the regular-season schedule reuse the
        cache that was built for it.  The rules that differ in the postseason
        (no ties, sudden-death overtime, no ghost runner) move a single-game win
        probability by well under a percentage point, and reusing the cache is
        what keeps a full championship Monte Carlo interactive.
        """
        probs = {p: reg_cache[p].home_win_prob for p in pairs if p in reg_cache}
        missing = [p for p in pairs if p not in probs]
        if not missing:
            return probs

        def stack(getter) -> np.ndarray:
            return np.repeat(np.array([float(np.asarray(getter(p))) for p in missing]), samples)

        home = TeamRating(
            team="home",
            attack=stack(lambda p: ratings.get(p[0], TeamRating(p[0])).attack),
            defense=stack(lambda p: ratings.get(p[0], TeamRating(p[0])).defense),
            pace=stack(lambda p: ratings.get(p[0], TeamRating(p[0])).pace),
        )
        away = TeamRating(
            team="away",
            attack=stack(lambda p: ratings.get(p[1], TeamRating(p[1])).attack),
            defense=stack(lambda p: ratings.get(p[1], TeamRating(p[1])).defense),
            pace=stack(lambda p: ratings.get(p[1], TeamRating(p[1])).pace),
        )
        s = self.playoff_simulator.simulate(home, away, n=len(missing) * samples, rng=rng)
        margin = (np.asarray(s.home) - np.asarray(s.away)).reshape(len(missing), samples)
        win = (margin > 0).mean(axis=1) + 0.5 * (margin == 0).mean(axis=1)
        probs.update({p: float(win[i]) for i, p in enumerate(missing)})
        return probs

    def _run_playoffs(
        self,
        totals: dict[str, np.ndarray],
        team_idx: dict[str, int],
        ratings: dict[str, TeamRating],
        rng: np.random.Generator,
        playoff_samples: int,
        reg_cache: dict[tuple[str, str], _MatchupCache],
    ) -> dict[str, np.ndarray]:
        teams = list(team_idx)
        n = totals["wins"].shape[0]
        n_teams = len(teams)
        fmt = self.playoff_format

        made = np.zeros((n, n_teams), dtype=bool)
        div_titles = np.zeros((n, n_teams), dtype=bool)
        conf_titles = np.zeros((n, n_teams), dtype=bool)
        titles = np.zeros((n, n_teams), dtype=bool)

        points = totals["points"]
        diff = totals["points_for"] - totals["points_against"]
        tiebreak = rng.random((n, n_teams))

        # Rank every conference and division once, for all seasons at once.
        conf_order: dict[str, np.ndarray] = {}
        div_order: dict[str, list[np.ndarray]] = {}
        for conf, divisions in self.league.conferences.items():
            conf_members = [team_idx[t] for members in divisions.values() for t in members if t in team_idx]
            conf_order[conf] = rank_within(points, diff, conf_members, tiebreak)
            div_order[conf] = [
                rank_within(points, diff, [team_idx[t] for t in members if t in team_idx], tiebreak)
                for members in divisions.values()
            ]

        # Work out every pairing the bracket could produce before simulating any
        # of them, so the whole postseason costs one batched simulate() call.
        # A team is a candidate if it finishes high enough in any season; the
        # cushion covers the play-in and the NHL's divisional seeding, where a
        # team can qualify without being top-8 in its conference.
        cushion = fmt.teams_per_conference + (4 if (fmt.play_in or fmt.divisional_bracket) else 2)
        candidates = {
            conf: sorted({teams[i] for i in np.unique(order[:, : min(cushion, order.shape[1])])})
            for conf, order in conf_order.items()
        }
        needed: set[tuple[str, str]] = set()
        for members in candidates.values():
            needed.update((a, b) for a in members for b in members if a != b)
        conf_names = list(self.league.conferences)
        for i, ca in enumerate(conf_names):
            for cb in conf_names[i + 1 :]:
                for a in candidates[ca]:
                    for b in candidates[cb]:
                        needed.add((a, b))
                        needed.add((b, a))

        probs = self._pair_probs(sorted(needed), reg_cache, ratings, playoff_samples, rng)

        def game_win_prob(home: str, away: str) -> float:
            key = (home, away)
            if key not in probs:
                # Safety net for a pairing outside the candidate cushion.
                s = self.playoff_simulator.simulate(
                    ratings.get(home, TeamRating(home)),
                    ratings.get(away, TeamRating(away)),
                    n=playoff_samples,
                    rng=rng,
                )
                m = s.margin
                probs[key] = float((m > 0).mean() + 0.5 * (m == 0).mean())
            return probs[key]

        oracle = SeriesOracle(game_win_prob)
        conferences = conf_names

        for s in range(n):
            finalists: list[str] = []
            for conf in conferences:
                ranked = [teams[i] for i in conf_order[conf][s]]
                ranked_divs = [[teams[i] for i in d[s]] for d in div_order[conf]]

                for d in ranked_divs:
                    div_titles[s, team_idx[d[0]]] = True

                if fmt.divisional_bracket:
                    pairs = seed_nhl_bracket(ranked_divs, ranked)
                    field = [t for pair in pairs for t in pair]
                    rank_of = {t: r for r, t in enumerate(ranked)}
                    seed_rank = {t: rank_of[t] for t in field}
                    winner = run_nhl_bracket(pairs, oracle, seed_rank, rng, fmt.series_lengths[0])
                elif fmt.play_in:
                    field = run_play_in(ranked, oracle, rng)
                    winner = run_standard_bracket(field, oracle, fmt.series_lengths, 0, rng, reseed=False)
                else:
                    field = seed_conference(
                        ranked, ranked_divs, fmt.teams_per_conference, fmt.division_winners_seeded
                    )
                    winner = run_standard_bracket(
                        field, oracle, fmt.series_lengths, fmt.byes, rng, reseed=(self.sport == "nfl")
                    )

                for t in field:
                    made[s, team_idx[t]] = True
                conf_titles[s, team_idx[winner]] = True
                finalists.append(winner)

            if len(finalists) == 2:
                high, low = finalists
                # The finals host is the team with the better regular season.
                if points[s, team_idx[low]] > points[s, team_idx[high]]:
                    high, low = low, high
                champ = oracle.play(high, low, fmt.series_lengths[-1], float(rng.random()))
            else:
                champ = finalists[0]
            titles[s, team_idx[champ]] = True

        return {
            "made_playoffs": made,
            "division_titles": div_titles,
            "conference_titles": conf_titles,
            "championships": titles,
        }

    # -- public entry point ------------------------------------------------
    def run(
        self,
        schedule: Sequence[Game],
        n_sims: int = 5_000,
        rng: np.random.Generator | int | None = None,
        rating_noise: float | None = None,
        n_scenarios: int = 12,
        samples_per_matchup: int | None = None,
        playoff_samples: int = 1_500,
        include_playoffs: bool = True,
    ) -> SeasonResult:
        """Simulate ``n_sims`` seasons from a schedule.

        ``rating_noise`` is the season-long uncertainty in each team's true
        strength, as a fraction; it defaults to a per-league value from
        :data:`RATING_NOISE`.  Set it to 0 to treat the input ratings as exactly
        right, which will make the playoff odds noticeably overconfident.
        ``n_scenarios`` controls how many distinct rating draws are used -- more
        scenarios sample that uncertainty better, at the cost of rebuilding the
        matchup cache each time.
        """
        rng = rng if isinstance(rng, np.random.Generator) else np.random.default_rng(rng)
        if rating_noise is None:
            rating_noise = RATING_NOISE.get(self.sport, 0.025)
        if samples_per_matchup is None:
            samples_per_matchup = MATCHUP_SAMPLES.get(self.sport, 1_500)
        schedule = list(schedule)
        if not schedule:
            raise ValueError("schedule is empty")

        teams = sorted({t for g in schedule for t in (g.home, g.away)})
        team_idx = {t: i for i, t in enumerate(teams)}
        matchups = sorted({(g.home, g.away) for g in schedule if not g.played})

        if rating_noise <= 0:
            n_scenarios = 1
        n_scenarios = max(1, min(n_scenarios, n_sims))
        per_scenario = [n_sims // n_scenarios] * n_scenarios
        for i in range(n_sims % n_scenarios):
            per_scenario[i] += 1

        chunks: list[dict[str, np.ndarray]] = []
        for batch in per_scenario:
            if batch == 0:
                continue
            if rating_noise > 0:
                # One strength draw held for the whole season -- teams are good
                # or bad all year, not re-rolled every game.
                scenario = {
                    t: TeamRating(
                        team=t,
                        elo=r.elo,
                        attack=float(np.asarray(r.attack)) * float(np.exp(rng.normal(0, rating_noise))),
                        defense=float(np.asarray(r.defense)) * float(np.exp(rng.normal(0, rating_noise))),
                        pace=r.pace,
                    )
                    for t, r in self.ratings.items()
                }
            else:
                scenario = self.ratings

            cache = self._build_cache(matchups, scenario, samples_per_matchup, rng)
            totals = self._play_regular_season(schedule, cache, team_idx, batch, rng)
            if include_playoffs:
                totals.update(
                    self._run_playoffs(totals, team_idx, scenario, rng, playoff_samples, cache)
                )
            else:
                shape = (batch, len(teams))
                totals.update(
                    {
                        "made_playoffs": np.zeros(shape, dtype=bool),
                        "division_titles": np.zeros(shape, dtype=bool),
                        "conference_titles": np.zeros(shape, dtype=bool),
                        "championships": np.zeros(shape, dtype=bool),
                    }
                )
            chunks.append(totals)

        merged = {k: np.concatenate([c[k] for c in chunks], axis=0) for k in chunks[0]}
        return SeasonResult(teams=teams, sport=self.sport, league=self.league, **merged)
