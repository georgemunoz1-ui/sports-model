"""League structures and playoff formats for the four major North American leagues.

Team codes are the abbreviations used by most public data sources.  Structures
reflect the alignments and playoff formats in place for the 2024-25 seasons.
"""

from __future__ import annotations

from dataclasses import dataclass

from .core.types import LeagueStructure

NFL = LeagueStructure(
    name="NFL",
    conferences={
        "AFC": {
            "AFC East": ["BUF", "MIA", "NE", "NYJ"],
            "AFC North": ["BAL", "CIN", "CLE", "PIT"],
            "AFC South": ["HOU", "IND", "JAX", "TEN"],
            "AFC West": ["DEN", "KC", "LAC", "LV"],
        },
        "NFC": {
            "NFC East": ["DAL", "NYG", "PHI", "WAS"],
            "NFC North": ["CHI", "DET", "GB", "MIN"],
            "NFC South": ["ATL", "CAR", "NO", "TB"],
            "NFC West": ["ARI", "LAR", "SEA", "SF"],
        },
    },
)

NBA = LeagueStructure(
    name="NBA",
    conferences={
        "East": {
            "Atlantic": ["BOS", "BKN", "NYK", "PHI", "TOR"],
            "Central": ["CHI", "CLE", "DET", "IND", "MIL"],
            "Southeast": ["ATL", "CHA", "MIA", "ORL", "WAS"],
        },
        "West": {
            "Northwest": ["DEN", "MIN", "OKC", "POR", "UTA"],
            "Pacific": ["GSW", "LAC", "LAL", "PHX", "SAC"],
            "Southwest": ["DAL", "HOU", "MEM", "NOP", "SAS"],
        },
    },
)

NHL = LeagueStructure(
    name="NHL",
    conferences={
        "Eastern": {
            "Atlantic": ["BOS", "BUF", "DET", "FLA", "MTL", "OTT", "TBL", "TOR"],
            "Metropolitan": ["CAR", "CBJ", "NJD", "NYI", "NYR", "PHI", "PIT", "WSH"],
        },
        "Western": {
            "Central": ["CHI", "COL", "DAL", "MIN", "NSH", "STL", "UTA", "WPG"],
            "Pacific": ["ANA", "CGY", "EDM", "LAK", "SEA", "SJS", "VAN", "VGK"],
        },
    },
)

MLB = LeagueStructure(
    name="MLB",
    conferences={
        "AL": {
            "AL East": ["BAL", "BOS", "NYY", "TBR", "TOR"],
            "AL Central": ["CHW", "CLE", "DET", "KCR", "MIN"],
            "AL West": ["ATH", "HOU", "LAA", "SEA", "TEX"],
        },
        "NL": {
            "NL East": ["ATL", "MIA", "NYM", "PHI", "WSN"],
            "NL Central": ["CHC", "CIN", "MIL", "PIT", "STL"],
            "NL West": ["ARI", "COL", "LAD", "SDP", "SFG"],
        },
    },
)

LEAGUES: dict[str, LeagueStructure] = {"nfl": NFL, "nba": NBA, "nhl": NHL, "mlb": MLB}


@dataclass(frozen=True)
class PlayoffFormat:
    """How a league gets from final standings to a champion.

    ``division_winners_seeded`` means division winners are guaranteed the top
    seeds regardless of record (NFL, MLB); the NBA seeds purely on record and
    the NHL uses a bracketed division format handled separately.
    """

    teams_per_conference: int
    #: games in each round, ordered from the first round to the final
    series_lengths: tuple[int, ...]
    division_winners_seeded: bool = True
    #: number of top seeds that skip the first round
    byes: int = 0
    #: NHL-style bracket: top 3 per division plus two wild cards
    divisional_bracket: bool = False
    #: NBA play-in tournament for seeds 7-10
    play_in: bool = False


PLAYOFF_FORMATS: dict[str, PlayoffFormat] = {
    # 7 per conference, the top seed gets a bye, single elimination.
    "nfl": PlayoffFormat(teams_per_conference=7, series_lengths=(1, 1, 1, 1), byes=1),
    # 8 per conference after the play-in, four best-of-seven rounds.
    "nba": PlayoffFormat(
        teams_per_conference=8, series_lengths=(7, 7, 7, 7), division_winners_seeded=False, play_in=True
    ),
    # 8 per conference in a divisional bracket, four best-of-seven rounds.
    "nhl": PlayoffFormat(teams_per_conference=8, series_lengths=(7, 7, 7, 7), divisional_bracket=True),
    # 6 per league: wild card best-of-three, then 5, 7, 7. Top 2 seeds get byes.
    "mlb": PlayoffFormat(teams_per_conference=6, series_lengths=(3, 5, 7, 7), byes=2),
}

#: Regular-season length per team, used by the synthetic schedule builder.
SEASON_LENGTH: dict[str, int] = {"nfl": 17, "nba": 82, "nhl": 82, "mlb": 162}

#: How a win is worth in the standings. The NHL awards a point for an overtime
#: loss, which is why its standings use points rather than wins.
USES_OT_POINTS: dict[str, bool] = {"nfl": False, "nba": False, "nhl": True, "mlb": False}

#: Ties are only possible in NFL regular-season games.
ALLOWS_TIES: dict[str, bool] = {"nfl": True, "nba": False, "nhl": False, "mlb": False}


def get_league(sport: str) -> LeagueStructure:
    key = sport.lower()
    if key not in LEAGUES:
        raise KeyError(f"unknown sport {sport!r}; choose from {sorted(LEAGUES)}")
    return LEAGUES[key]


def get_playoff_format(sport: str) -> PlayoffFormat:
    return PLAYOFF_FORMATS[sport.lower()]
