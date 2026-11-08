"""CSV I/O for games and ratings.

The formats are deliberately boring so results scraped from anywhere can be
dropped straight in.

Games CSV -- ``date,home,away,home_score,away_score`` with optional
``neutral``, ``ot``, ``season`` columns.  Rows with blank scores are treated as
unplayed and become part of the schedule to simulate::

    date,home,away,home_score,away_score
    2024-09-08,KC,BAL,27,20
    2024-09-15,KC,CIN,,

Ratings CSV -- ``team,attack,defense,pace,elo``; only ``team`` is required.
"""

from __future__ import annotations

import csv
import io
import hashlib
import math
from pathlib import Path
from typing import Iterable, Sequence

from ..core.types import Game, TeamRating

_TRUE = {"1", "true", "yes", "y", "t"}

# Column aliases seen in public data sources.
_HOME_KEYS = ("home", "home_team", "hometeam", "team_home", "h")
_AWAY_KEYS = ("away", "away_team", "awayteam", "team_away", "visitor", "a")
_HS_KEYS = ("home_score", "homescore", "home_points", "score_home", "hs", "home_runs", "home_goals")
_AS_KEYS = ("away_score", "awayscore", "away_points", "score_away", "as", "away_runs", "away_goals")


def _pick(row: dict[str, str], keys: Sequence[str]) -> str | None:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def _to_int(value: str | None) -> int | None:
    if value in (None, "", "NA", "null", "None"):
        return None
    return int(float(value))


def _open_csv(path, evidence):
    if evidence is None:
        return open(path,newline="",encoding="utf-8")
    try:
        raw=Path(path).read_bytes()
    except OSError:
        evidence["state"]="ACQUISITION_FAILURE"
        raise
    evidence.update(state="LOCAL_CSV_READ",sha256=hashlib.sha256(raw).hexdigest(),rows=0)
    return io.StringIO(raw.decode("utf-8-sig"),newline="")


def read_games_csv(path: str | Path, *, evidence=None) -> list[Game]:
    """Load games; rows without both scores are returned as unplayed."""
    games: list[Game] = []
    with _open_csv(path,evidence) as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            return games
        keys=set()
        for raw in reader:
            row = {(k or "").strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}
            home, away = _pick(row, _HOME_KEYS), _pick(row, _AWAY_KEYS)
            if evidence is not None:
                evidence["rows"]+=1
                if not home or not away or home==away:
                    raise ValueError("UNRESOLVED_GAME_TEAMS")
                eid=row.get("event_id") or row.get("game_id")
                # With no provider ID, repeated team/date pairs need disambiguation (including doubleheaders).
                identity=("event",eid) if eid else (row.get("date"),home,away)
                if identity in keys:
                    raise ValueError("DUPLICATE_OR_AMBIGUOUS_GAME_IDENTITY")
                keys.add(identity)
                for field in ("neutral","ot"):
                    v=(row.get("overtime") if field=="ot" and "ot" not in row else row.get(field))
                    if v in (None,""):
                        evidence[field+"_default_count"]=evidence.get(field+"_default_count",0)+1
                    elif str(v).lower() not in _TRUE|{"0","false","no","n","f"}:
                        raise ValueError("INVALID_GAME_FLAG:"+field)
            if not home or not away:
                continue
            hs, as_ = _to_int(_pick(row, _HS_KEYS)), _to_int(_pick(row, _AS_KEYS))
            if evidence is not None and ((hs is None)!=(as_ is None)):
                raise ValueError("PARTIAL_SCORE_CANNOT_BECOME_UNPLAYED")
            games.append(
                Game(
                    home=home,
                    away=away,
                    home_score=hs if as_ is not None else None,
                    away_score=as_ if hs is not None else None,
                    date=row.get("date") or None,
                    neutral=str(row.get("neutral", "")).lower() in _TRUE,
                    went_ot=str(row.get("ot", row.get("overtime", ""))).lower() in _TRUE,
                    season=_to_int(row.get("season")),
                )
            )
    return games


def write_games_csv(path: str | Path, games: Iterable[Game]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "home", "away", "home_score", "away_score", "neutral", "ot", "season"])
        for g in games:
            writer.writerow(
                [
                    g.date or "",
                    g.home,
                    g.away,
                    "" if g.home_score is None else g.home_score,
                    "" if g.away_score is None else g.away_score,
                    int(g.neutral),
                    int(g.went_ot),
                    "" if g.season is None else g.season,
                ]
            )


def read_ratings_csv(path: str | Path, *, evidence=None) -> dict[str, TeamRating]:
    ratings: dict[str, TeamRating] = {}
    with _open_csv(path,evidence) as fh:
        for raw in csv.DictReader(fh):
            row = {(k or "").strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}
            team = row.get("team") or row.get("name")
            if evidence is not None:
                evidence["rows"]+=1
                if not team or team in ratings:
                    raise ValueError("DUPLICATE_OR_UNRESOLVED_RATING_TEAM")
                defaults=evidence.setdefault("default_fields_by_team",{})
                defaults[team]=[k for k in ("elo","attack","defense","pace") if not row.get(k)]
                for k in ("elo","attack","defense","pace"):
                    if row.get(k) and not math.isfinite(float(row[k])):
                        raise ValueError("NONFINITE_RATING")
            if not team:
                continue
            ratings[team] = TeamRating(
                team=team,
                elo=float(row.get("elo") or 1500.0),
                attack=float(row.get("attack") or 1.0),
                defense=float(row.get("defense") or 1.0),
                pace=float(row.get("pace") or 1.0),
            )
    return ratings


def write_ratings_csv(path: str | Path, ratings: dict[str, TeamRating]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["team", "attack", "defense", "pace", "elo"])
        for team in sorted(ratings):
            r = ratings[team]
            writer.writerow(
                [team, f"{float(r.attack):.4f}", f"{float(r.defense):.4f}", f"{float(r.pace):.4f}", f"{float(r.elo):.1f}"]
            )
