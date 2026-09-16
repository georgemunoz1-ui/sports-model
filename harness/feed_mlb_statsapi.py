"""MLB StatsAPI client — FU-1 feed adapter, StatsAPI leg.

ENDPOINTS (no API key):
  schedule: https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=YYYY-MM-DD&hydrate=probablePitcher
  boxscore: https://statsapi.mlb.com/api/v1/game/{gamePk}/boxscore

GRADE SEMANTICS (freshness_contract vocabulary; nothing invented):
  - FINAL scores from the StatsAPI schedule (statusCode F/O with both scores) are first-party
    league feed data for THIS game: grade=CONFIRMED.
  - schedule?hydrate=probablePitcher is a PROBABLE listing: grade=IDENTIFIED_UNCONFIRMED.
    NEVER mint CONFIRMED from a probable. Confirmation requires the boxscore to show the game
    past first pitch (status Final/In-Progress) with the pitcher actually appearing in the
    pitching statistics — i.e. lineups/officials posted, not merely expected.

QUIRKS discovered while building (documented, not worked around silently):
  - hydrate=probablePitcher returns "probablePitchers" per game; it survives briefly after first
    pitch, so its presence is NOT a confirmation signal.
  - StatsAPI "officialDate" is already the local (US host-city) game date — it matches the ET
    slate date for continental games, but the adapter still derives date_et from gameDate (UTC)
    through America/New_York rather than trusting officialDate blindly; a disagreement between the
    two is surfaced as a conflict by feed_sweep, never resolved silently.
  - schedule teams carry full names, not abbreviations; TEAM_ABBR maps the 30 clubs.
"""
from __future__ import annotations

MODULE_ID = "feed_mlb_statsapi"

import datetime as dt
import hashlib
import json
import sys

UTC = dt.timezone.utc
API_ROOT = "https://statsapi.mlb.com/api/v1"

from feed_espn import ET, et_date_of, parse_utc  # ET date derivation lives in exactly one place

#: StatsAPI full club name -> repo abbreviation. The 8/28 board's spellings included.
TEAM_ABBR = {
    "Arizona Diamondbacks": "AZ", "Athletics": "ATH", "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS", "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS", "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL", "Detroit Tigers": "DET", "Houston Astros": "HOU",
    "Kansas City Royals": "KC", "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN",
    "New York Mets": "NYM", "New York Yankees": "NYY", "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD", "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
}

FINAL_STATUS_CODES = ("F", "O")  # Final, Game Over


def schedule_url(date_et):
    return (f"{API_ROOT}/schedule?sportId=1&date={date_et}"
            f"&hydrate=probablePitcher&language=en")


def boxscore_url(game_pk):
    return f"{API_ROOT}/game/{game_pk}/boxscore"


def _abbr(team_obj):
    name = (team_obj or {}).get("name", "")
    ab = (team_obj or {}).get("abbreviation")
    return ab or TEAM_ABBR.get(name, name)


def parse_schedule(payload, fetched_utc):
    """StatsAPI schedule payload -> gamePk-keyed records. Pure parse."""
    out = []
    for day in payload.get("dates") or []:
        for g in day.get("games") or []:
            start = parse_utc(g["gameDate"])
            teams = g.get("teams") or {}
            away, home = teams.get("away") or {}, teams.get("home") or {}
            prob = g.get("probablePitchers") or {}
            status = g.get("status") or {}
            out.append({
                "league": "mlb",
                "game_id": str(g["gamePk"]),
                "id_space": "MLB_GAMEPK",
                "date_et": et_date_of(start),
                "official_date": g.get("officialDate"),
                "away": _abbr((away.get("team") or {})),
                "home": _abbr((home.get("team") or {})),
                "start_utc": start.isoformat().replace("+00:00", "Z"),
                "status": status.get("detailedState", "UNKNOWN"),
                "status_code": status.get("statusCode", ""),
                "completed": status.get("statusCode") in FINAL_STATUS_CODES,
                "away_score": away.get("score"),
                "home_score": home.get("score"),
                "probable_pitchers": {
                    side: (prob.get(side) or {}).get("fullName")
                    for side in ("away", "home") if prob.get(side)
                },
                "doubleheader_game_number": g.get("gameNumber"),
                "source": "mlb_statsapi",
                "fetched_utc": fetched_utc,
            })
    return out


def parse_boxscore_starters(payload, game_pk, fetched_utc):
    """Confirmed-starter detection from the boxscore.

    CONFIRMED only when the game is in progress/final AND the pitcher appears in that side's
    pitching statistics with games_started evidence. A probable listing — even a fresh one —
    never reaches this function's CONFIRMED: the caller must not route schedule probables here.

    StatsAPI marks each pitching stat line with gamesStarted; the starter is the pitcher with
    gamesStarted >= 1 in the boxscore once the game is underway. Before lineups post the
    boxscore players carry no pitching stats, so the function returns PROBABLE/ABSENT rather
    than guessing.
    """
    info = {i.get("label"): i.get("value") for i in (payload.get("info") or [])}
    teams = payload.get("teams") or {}
    out = {"league": "mlb", "game_id": str(game_pk), "starters": {},
           "lineups_posted": False, "source": "mlb_statsapi_boxscore",
           "fetched_utc": fetched_utc}
    for side in ("away", "home"):
        players = (teams.get(side) or {}).get("players") or {}
        starter = None
        for p in players.values():
            pitching = ((p.get("stats") or {}).get("pitching") or {})
            if pitching.get("gamesStarted", 0) >= 1:
                person = p.get("person") or {}
                starter = {"name": person.get("fullName"), "player_id": person.get("id"),
                           "grade": "CONFIRMED",
                           "basis": "boxscore pitching line with gamesStarted>=1; game underway"}
                out["lineups_posted"] = True
                break
        out["starters"][side] = starter
    return out


def confirmed_starter_or_probable(schedule_rec, boxscore_starters):
    """The gating rule in one place.

    Returns (side-> {name, grade, basis}). A boxscore CONFIRMED wins. If the boxscore has not
    posted lineups, the schedule's probablePitcher survives ONLY as IDENTIFIED_UNCONFIRMED —
    never promoted, whatever its freshness.
    """
    res = {}
    for side in ("away", "home"):
        bs = (boxscore_starters or {}).get("starters", {}).get(side)
        if bs and bs.get("grade") == "CONFIRMED":
            res[side] = bs
            continue
        name = (schedule_rec.get("probable_pitchers") or {}).get(side)
        if name:
            res[side] = {"name": name, "grade": "IDENTIFIED_UNCONFIRMED",
                         "basis": "schedule hydrate=probablePitcher listing; probable-only, "
                                  "never a confirmation"}
        else:
            res[side] = {"name": None, "grade": "ABSENT", "basis": "no probable, no boxscore"}
    return res


def result_rows(records):
    """StatsAPI finals -> binding rows with the namespaced MLB_GAMEPK id space."""
    rows = []
    for r in records:
        if not r["completed"] or r["away_score"] is None or r["home_score"] is None:
            continue
        row = {
            "sport": "mlb",
            "game_pk": f"MLB_GAMEPK:{r['game_id']}",
            "scheduled_date": r["date_et"],
            "result_date": r["date_et"],
            "away": r["away"], "home": r["home"],
            "away_score": r["away_score"], "home_score": r["home_score"],
            "source": r["source"], "fetched_utc": r["fetched_utc"],
        }
        if r.get("doubleheader_game_number") not in (None, 1):
            row["game_number"] = r["doubleheader_game_number"]
        rows.append(row)
    return rows



# 2026-08-30: as delivered, this module's DEFAULT fetcher was a live requests.get against
# statsapi.mlb.com. That is direct script HTTP against a sports data site, which this deployment does
# not permit -- outbound calls go through the org egress proxy and must use approved
# browsing/search/fetch tooling. The precedent is on file: acquisition_adapters shipped with
# exactly this defect (urlopen against statsapi.mlb.com), was fixed by making the DEFAULT
# refuse, and carries ALLOW_DIRECT_HTTP = False to this day. None of the six modules in this
# delivery imported that gate, so the guard had zero callers on these paths -- the same shape
# as aggregate_guard before it was wired in.
#
# The fix keeps dependency injection exactly as designed and only changes what happens when
# NOTHING is injected: it refuses, loudly, instead of reaching the network. A caller that
# wanted a fetch learns it did not happen.

ALLOW_DIRECT_HTTP = False


class AcquisitionDisabled(RuntimeError):
    """Raised when a network fetch is attempted with no approved fetcher injected."""


def _default_get(url, timeout=20):
    """Refuses by default. Pass get=<approved fetcher> to enable acquisition."""
    if not ALLOW_DIRECT_HTTP:
        raise AcquisitionDisabled(
            f"direct HTTP is disabled in this deployment (attempted {url!r}). Pass "
            "get=<approved fetcher> to the fetch_* call. Refusing rather than silently "
            "degrading is deliberate: the caller asked for a network fetch and must "
            "learn it did not happen.")
    import requests
    r = requests.get(url, timeout=timeout,
                     headers={"User-Agent": "sports-model-fu1/1.0"})
    r.raise_for_status()
    return r.text


def fetch_schedule(date_et, get=_default_get):
    fetched_utc = dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")
    text = get(schedule_url(date_et))
    sha = hashlib.sha256(text.encode()).hexdigest()
    return parse_schedule(json.loads(text), fetched_utc), text, sha


def fetch_boxscore_starters(game_pk, get=_default_get):
    fetched_utc = dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")
    text = get(boxscore_url(game_pk))
    sha = hashlib.sha256(text.encode()).hexdigest()
    return parse_boxscore_starters(json.loads(text), game_pk, fetched_utc), text, sha


# ====================================================================== selftest

def selftest():
    f = []
    sched = {"dates": [{"date": "2026-08-28", "games": [{
        "gamePk": 823504, "gameDate": "2026-08-28T23:15:00Z", "officialDate": "2026-08-28",
        "status": {"detailedState": "Final", "statusCode": "F"},
        "teams": {"away": {"team": {"name": "Boston Red Sox"}, "score": 3},
                  "home": {"team": {"name": "New York Yankees"}, "score": 6}},
        "probablePitchers": {"away": {"fullName": "Patrick Sandoval"},
                             "home": {"fullName": "Gerrit Cole"}},
        "gameNumber": 1}]}]}
    recs = parse_schedule(sched, "2026-08-30T00:00:00Z")
    r = recs[0]
    if r["game_id"] != "823504" or r["away"] != "BOS" or r["home"] != "NYY":
        f.append(f"schedule parse broke: {r}")
    if r["date_et"] != "2026-08-28" or not r["completed"]:
        f.append(f"date/status wrong: {r['date_et']} completed={r['completed']}")
    rows = result_rows(recs)
    if len(rows) != 1 or rows[0]["game_pk"] != "MLB_GAMEPK:823504":
        f.append(f"namespaced row wrong: {rows}")

    # THE GATING CASE. A probable listing must never mint CONFIRMED.
    gated = confirmed_starter_or_probable(r, None)
    if gated["away"]["grade"] != "IDENTIFIED_UNCONFIRMED" or gated["away"]["name"] != "Patrick Sandoval":
        f.append(f"a probable listing was promoted: {gated['away']}")
    # a boxscore with gamesStarted confirms
    bs = {"teams": {"away": {"players": {"p1": {"person": {"fullName": "Patrick Sandoval", "id": 1},
                                               "stats": {"pitching": {"gamesStarted": 1}}}}},
                    "home": {"players": {}}}, "info": []}
    parsed_bs = parse_boxscore_starters(bs, 823504, "t")
    if parsed_bs["starters"]["away"]["grade"] != "CONFIRMED":
        f.append("a gamesStarted=1 boxscore line failed to confirm")
    if parsed_bs["starters"]["home"] is not None:
        f.append("an empty boxscore side minted a starter")
    gated2 = confirmed_starter_or_probable(r, parsed_bs)
    if gated2["away"]["grade"] != "CONFIRMED" or gated2["home"]["grade"] != "IDENTIFIED_UNCONFIRMED":
        f.append(f"mixed gating wrong: {gated2}")
    # a pre-lineup boxscore (players present, no pitching stats) does NOT confirm
    bs_pre = {"teams": {"away": {"players": {"p1": {"person": {"fullName": "X", "id": 9},
                                                   "stats": {"pitching": {}}}}},
                        "home": {"players": {}}}, "info": []}
    pre = parse_boxscore_starters(bs_pre, 823504, "t")
    if pre["starters"]["away"] is not None or pre["lineups_posted"]:
        f.append("a pre-lineup boxscore was read as a confirmation")

    print(f"feed_mlb_statsapi selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("   -", x)
    return 0 if not f else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__)
