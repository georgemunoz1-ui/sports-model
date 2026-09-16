"""Playoff brackets for the four leagues.

Series are resolved from single-game win probabilities rather than by simulating
every game again: given P(higher seed wins at home) and P(higher seed wins on
the road), the probability of taking the series is an exact dynamic program over
the home-court pattern.  That keeps a full-league championship Monte Carlo fast
enough to run interactively.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Callable, Sequence

import numpy as np

# Home-court patterns from the higher seed's perspective.
SERIES_PATTERNS: dict[int, tuple[bool, ...]] = {
    1: (True,),
    3: (True, True, True),  # MLB wild card round: all at the higher seed
    5: (True, True, False, False, True),
    7: (True, True, False, False, True, False, True),
}


def series_win_prob(p_high_home: float, p_high_away: float, length: int) -> float:
    """P(higher seed wins the series) for a best-of-``length`` series."""
    pattern = SERIES_PATTERNS[length]
    needed = length // 2 + 1
    # state[(high_wins, low_wins)] -> probability of reaching that state
    state = {(0, 0): 1.0}
    total = 0.0
    for game, at_home in enumerate(pattern):
        p = p_high_home if at_home else p_high_away
        nxt: dict[tuple[int, int], float] = {}
        for (hw, lw), prob in state.items():
            for win, q in ((True, p), (False, 1.0 - p)):
                nh, nl = (hw + 1, lw) if win else (hw, lw + 1)
                if nh == needed:
                    total += prob * q
                elif nl == needed:
                    continue
                else:
                    nxt[(nh, nl)] = nxt.get((nh, nl), 0.0) + prob * q
        state = nxt
        if not state:
            break
    return total


class SeriesOracle:
    """Caches series probabilities for every matchup encountered."""

    def __init__(self, game_win_prob: Callable[[str, str], float]):
        #: ``game_win_prob(home, away)`` -> P(home wins that single game)
        self._p = game_win_prob
        self._cache: dict[tuple[str, str, int], float] = {}

    def prob(self, high: str, low: str, length: int) -> float:
        key = (high, low, length)
        if key not in self._cache:
            p_home = self._p(high, low)
            p_away = 1.0 - self._p(low, high)
            self._cache[key] = series_win_prob(p_home, p_away, length)
        return self._cache[key]

    def play(self, high: str, low: str, length: int, u: float) -> str:
        """Resolve one series against a uniform draw."""
        return high if u < self.prob(high, low, length) else low


# --------------------------------------------------------------------------
# seeding
# --------------------------------------------------------------------------
def seed_conference(
    ranked_conf: Sequence[str],
    ranked_divisions: Sequence[Sequence[str]],
    n_teams: int,
    division_winners_seeded: bool,
) -> list[str]:
    """Return the playoff field for one conference, best seed first.

    ``ranked_conf`` is every team in the conference ordered best to worst;
    ``ranked_divisions`` is the same ordering split by division.
    """
    if not division_winners_seeded:
        return list(ranked_conf[:n_teams])

    winners = [d[0] for d in ranked_divisions]
    # Division winners keep the top seeds, ordered among themselves by record.
    winners = [t for t in ranked_conf if t in set(winners)]
    wildcards = [t for t in ranked_conf if t not in set(winners)]
    return (winners + wildcards)[:n_teams]


def seed_nhl_bracket(ranked_divisions: Sequence[Sequence[str]], ranked_conf: Sequence[str]) -> list[tuple[str, str]]:
    """NHL divisional bracket: top three per division plus two wild cards.

    The conference's better wild card faces the weaker division winner, so the
    first round is D1-vs-WC2, D2-vs-D3 inside each division.
    """
    if len(ranked_divisions) != 2:
        raise ValueError("the NHL bracket expects exactly two divisions per conference")
    top3 = [list(d[:3]) for d in ranked_divisions]
    qualified = {t for d in top3 for t in d}
    wildcards = [t for t in ranked_conf if t not in qualified][:2]

    # The division winner with the better record draws the weaker wild card.
    order = sorted(range(2), key=lambda i: ranked_conf.index(top3[i][0]))
    pairs: list[tuple[str, str]] = []
    for rank, div_i in enumerate(order):
        div = top3[div_i]
        pairs.append((div[0], wildcards[1 - rank]))
        pairs.append((div[1], div[2]))
    return pairs


# --------------------------------------------------------------------------
# brackets
# --------------------------------------------------------------------------
def run_standard_bracket(
    field: Sequence[str],
    oracle: SeriesOracle,
    series_lengths: Sequence[int],
    byes: int,
    rng: np.random.Generator,
    reseed: bool,
) -> str:
    """Play one conference bracket and return the winner.

    ``field`` is seeded best-first.  With ``reseed`` the highest remaining seed
    always faces the lowest remaining seed (NFL); otherwise the bracket is fixed
    once set (NBA, MLB).
    """
    seeds = {t: i for i, t in enumerate(field)}
    alive = list(field)
    round_index = 0

    if byes:
        # The bye teams sit out while the rest play the opening round.
        playing = alive[byes:]
        length = series_lengths[0]
        # Keeping the bye teams first and the opening-round winners in bracket
        # order is what makes the fixed MLB bracket come out right: seed 1 meets
        # the 4/5 winner and seed 2 meets the 3/6 winner.
        alive = alive[:byes] + _play_round(playing, oracle, length, rng, seeds)
        if reseed:
            alive = sorted(alive, key=lambda t: seeds[t])
        round_index = 1

    while len(alive) > 1:
        length = series_lengths[min(round_index, len(series_lengths) - 1)]
        alive = _play_round(alive, oracle, length, rng, seeds)
        if reseed:
            alive = sorted(alive, key=lambda t: seeds[t])
        round_index += 1
    return alive[0]


def _play_round(
    teams: Sequence[str],
    oracle: SeriesOracle,
    length: int,
    rng: np.random.Generator,
    seeds: dict[str, int],
) -> list[str]:
    """Pair first-vs-last, second-vs-second-last, and resolve each series."""
    teams = list(teams)
    if len(teams) % 2:
        raise ValueError(f"cannot pair an odd number of teams: {teams}")
    winners: list[str] = []
    for i in range(len(teams) // 2):
        high, low = teams[i], teams[-1 - i]
        if seeds[high] > seeds[low]:
            high, low = low, high
        winners.append(oracle.play(high, low, length, float(rng.random())))
    return winners


def run_nhl_bracket(
    pairs: Sequence[tuple[str, str]],
    oracle: SeriesOracle,
    seed_rank: dict[str, int],
    rng: np.random.Generator,
    length: int = 7,
) -> str:
    """NHL conference bracket: fixed first round, then division finals."""
    winners = [oracle.play(h, l, length, float(rng.random())) for h, l in pairs]
    # winners[0]/winners[1] are the same division, as are [2]/[3].
    div_finals = []
    for i in (0, 2):
        a, b = winners[i], winners[i + 1]
        high, low = (a, b) if seed_rank[a] < seed_rank[b] else (b, a)
        div_finals.append(oracle.play(high, low, length, float(rng.random())))
    a, b = div_finals
    high, low = (a, b) if seed_rank[a] < seed_rank[b] else (b, a)
    return oracle.play(high, low, length, float(rng.random()))


def run_play_in(ranked_conf: Sequence[str], oracle: SeriesOracle, rng: np.random.Generator) -> list[str]:
    """NBA play-in: seeds 7-10 fight for the last two spots.

    7 beats 8 to claim the seven seed; the 8/9 loser-vs-winner game decides the
    eighth.
    """
    field = list(ranked_conf[:6])
    s7, s8, s9, s10 = ranked_conf[6:10]
    winner_78 = oracle.play(s7, s8, 1, float(rng.random()))
    loser_78 = s8 if winner_78 == s7 else s7
    winner_910 = oracle.play(s9, s10, 1, float(rng.random()))
    # The 7/8 loser hosts the 9/10 winner for the final spot.
    eighth = oracle.play(loser_78, winner_910, 1, float(rng.random()))
    return field + [winner_78, eighth]
