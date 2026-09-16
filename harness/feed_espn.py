"""ESPN scoreboard API client — FU-1 feed adapter, ESPN leg.

WHY THIS EXISTS. POSTGAME-AUDIT-2026-08-30 named FU-1 the highest-leverage follow-up: the
8/28 MLB slate carried real CAPTURED game ids (10 ESPN_GAMEID + 5 MLB_GAMEPK) and
result_binding_gate already maps them, but no programmatic finals source existed to produce
result rows carrying those ids, so grading fell back to manual odds-page uploads. This module is
the ESPN half of that source. It performs network I/O only when its fetch functions are CALLED;
parsing is pure and testable offline.

ENDPOINTS (no API key):
  scoreboard: https://site.api.espn.com/apis/site/v2/sports/{sport_path}/scoreboard?dates=YYYYMMDD
  summary:    https://site.api.espn.com/apis/site/v2/sports/{sport_path}/summary?event={game_id}

GRADE SEMANTICS (harness/freshness_contract.py vocabulary — no new grades invented):
  - A FINAL score read from the ESPN scoreboard is first-party feed data for THIS game and is
    stamped grade=CONFIRMED (the feed is the league/score vendor of record, not a search snippet).
  - Probable pitchers / lineups / injuries from the summary endpoint are PROBABLE-ONLY listings.
    They are stamped IDENTIFIED_UNCONFIRMED and never CONFIRMED: a probable listing identifies a
    name; it does not confirm a starter. Confirmation belongs to official lineup/boxscore data
    (see feed_mlb_statsapi.confirmed_starters).

ET DATE DERIVATION (the known UTC_SLICE_BUG). Every record's date_et is derived by converting the
event's UTC instant into America/New_York. Slicing the first ten characters of the UTC timestamp
puts an 8pm ET game on the WRONG DATE, which is exactly how prior-date series contamination
entered grading. Never slice.
"""
from __future__ import annotations

MODULE_ID = "feed_espn"

import datetime as dt
import hashlib
import json
import sys

UTC = dt.timezone.utc

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # zoneinfo database absent — fall back to the US-Eastern DST rule
    class _Eastern(dt.tzinfo):
        def _dst_bounds(self, year):
            # second Sunday of March 02:00, first Sunday of November 02:00
            mar = dt.datetime(year, 3, 8, 2)
            start = mar + dt.timedelta(days=(6 - mar.weekday()) % 7)
            nov = dt.datetime(year, 11, 1, 2)
            end = nov + dt.timedelta(days=(6 - nov.weekday()) % 7)
            return start, end

        def utcoffset(self, d):
            if d is None:
                return dt.timedelta(hours=-5)
            naive = d.replace(tzinfo=None)
            start, end = self._dst_bounds(naive.year)
            return dt.timedelta(hours=-4 if start <= naive < end else -5)

        def dst(self, d):
            return self.utcoffset(d) - dt.timedelta(hours=-5)

        def tzname(self, d):
            return "EDT" if self.utcoffset(d) == dt.timedelta(hours=-4) else "EST"

    ET = _Eastern()

API_ROOT = "https://site.api.espn.com/apis/site/v2/sports"

#: league key -> ESPN sport path. college-football is the canonical repo name for CFB.
LEAGUES = {
    "mlb": "baseball/mlb",
    "wnba": "basketball/wnba",
    "nfl": "football/nfl",
    "college-football": "football/college-football",
}

STATUS_FINAL = "STATUS_FINAL"
STATUS_POSTPONED = "STATUS_POSTPONED"
STATUS_SCHEDULED = "STATUS_SCHEDULED"


def et_date_of(start_utc):
    """The ET calendar date of a UTC instant. THE function the UTC_SLICE_BUG got wrong."""
    if isinstance(start_utc, str):
        start_utc = parse_utc(start_utc)
    return start_utc.astimezone(ET).date().isoformat()


def parse_utc(value):
    p = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return p if p.tzinfo else p.replace(tzinfo=UTC)


def scoreboard_url(league, date_et):
    return f"{API_ROOT}/{LEAGUES[league]}/scoreboard?dates={date_et.replace('-', '')}"


def summary_url(league, game_id):
    return f"{API_ROOT}/{LEAGUES[league]}/summary?event={game_id}"


def _competitors(event):
    comps = (event.get("competitions") or [{}])[0].get("competitors") or []
    away = next((c for c in comps if c.get("homeAway") == "away"), None)
    home = next((c for c in comps if c.get("homeAway") == "home"), None)
    return away, home


def normalize_event(event, league, fetched_utc):
    """One ESPN scoreboard event -> the common game record. Returns None for unscheduled ghosts."""
    away, home = _competitors(event)
    if away is None or home is None:
        return None
    start = parse_utc(event["date"])
    status = (event.get("status") or {}).get("type") or {}
    rec = {
        "league": league,
        "game_id": str(event["id"]),
        "id_space": "ESPN_GAMEID",
        "date_et": et_date_of(start),
        "away": (away.get("team") or {}).get("abbreviation"),
        "home": (home.get("team") or {}).get("abbreviation"),
        "start_utc": start.isoformat().replace("+00:00", "Z"),
        "status": status.get("name", "UNKNOWN"),
        "completed": bool(status.get("completed")),
        "away_score": (int(away["score"]) if str(away.get("score", "")).isdigit() else None),
        "home_score": (int(home["score"]) if str(home.get("score", "")).isdigit() else None),
        "source": "espn_scoreboard_api",
        "fetched_utc": fetched_utc,
    }
    return rec


def parse_scoreboard(payload, league, fetched_utc):
    """Pure parse of a scoreboard payload. No I/O."""
    out = []
    for ev in payload.get("events") or []:
        rec = normalize_event(ev, league, fetched_utc)
        if rec is not None:
            out.append(rec)
    return out


def parse_summary_probables(payload, game_id, league, fetched_utc):
    """Probable pitchers (MLB) / starters / injuries from the summary endpoint.

    GRADE: IDENTIFIED_UNCONFIRMED, always. A probable listing is the feed saying 'expected',
    which is probable-only; minting CONFIRMED here would fabricate an official attestation.
    """
    prob = []
    for block in (payload.get("probables") or []):
        for side in ("away", "home"):
            p = ((block.get(side) or {}).get("athlete")
                 or (block.get(side) or {}).get("player") or {})
            name = p.get("displayName") or p.get("fullName")
            if name:
                prob.append({"side": side, "name": name, "kind": "probable_pitcher"})
    box = payload.get("boxscore") or {}
    lineups_posted = bool((box.get("players") or []))
    injuries = []
    for inj in (payload.get("injuries") or []):
        team = (inj.get("team") or {}).get("abbreviation")
        for it in (inj.get("injuries") or []):
            a = it.get("athlete") or {}
            injuries.append({"team": team, "name": a.get("displayName"),
                             "status": it.get("status")})
    return {
        "league": league,
        "game_id": str(game_id),
        "probables": prob,
        "lineups_posted": lineups_posted,
        "injuries": injuries,
        # even if lineups are posted on ESPN, the adapter marks the STAMP unconfirmed for starter
        # confirmation; official confirmation is the StatsAPI boxscore's job (single authority).
        "grade": "IDENTIFIED_UNCONFIRMED",
        "source": "espn_summary_api",
        "fetched_utc": fetched_utc,
    }


# ----------------------------------------------------------------- network (called, never imported-time)


# 2026-08-30: as delivered, this module's DEFAULT fetcher was a live requests.get against
# site.api.espn.com. That is direct script HTTP against a sports data site, which this deployment does
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


def fetch_scoreboard(league, date_et, get=_default_get):
    """Fetch + parse one league's scoreboard for an ET date. Returns (records, raw, sha256)."""
    if league not in LEAGUES:
        raise ValueError(f"unknown league {league!r}; known: {sorted(LEAGUES)}")
    fetched_utc = dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")
    # was: `raw = _default_get if get is None else get` -- assigned, never used, and the
    # next line then called get() directly, so a get=None caller hit a TypeError instead of
    # the fallback the line was written to provide. The guard now actually guards.
    get = _default_get if get is None else get
    text = get(scoreboard_url(league, date_et))
    sha = hashlib.sha256(text.encode()).hexdigest()
    return parse_scoreboard(json.loads(text), league, fetched_utc), text, sha


def fetch_summary(league, game_id, get=_default_get):
    fetched_utc = dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")
    text = get(summary_url(league, game_id))
    sha = hashlib.sha256(text.encode()).hexdigest()
    return parse_summary_probables(json.loads(text), game_id, league, fetched_utc), text, sha


def result_rows(records):
    """Finals -> result rows compatible with result_binding_gate.binding_proof.

    game_pk carries the namespaced canonical id — the namespace is load-bearing (MLB_GAMEPK and
    ESPN_GAMEID both look like bare integers; stripping the prefix is the 8/27 defect reborn).
    Only completed games with both scores present emit rows; a scheduled/postponed game emits
    NOTHING rather than a row with invented scores (R1: never invent a number).
    """
    rows = []
    for r in records:
        if r["status"] != STATUS_FINAL or r["away_score"] is None or r["home_score"] is None:
            continue
        rows.append({
            "sport": r["league"],
            "game_pk": f"ESPN_GAMEID:{r['game_id']}",
            "scheduled_date": r["date_et"],
            "result_date": r["date_et"],
            "away": r["away"], "home": r["home"],
            "away_score": r["away_score"], "home_score": r["home_score"],
            "source": r["source"], "fetched_utc": r["fetched_utc"],
        })
    return rows


# ====================================================================== selftest

def selftest():
    f = []
    # the UTC_SLICE_BUG case: 2026-08-29T00:10:00Z is 8:10pm ET on 2026-08-28, NOT 8/29
    got = et_date_of("2026-08-29T00:10:00Z")
    if got != "2026-08-28":
        f.append(f"ET derivation produced {got}, expected 2026-08-28 (UTC slice would say 08-29)")
    # a midday UTC time stays on the same date in ET
    if et_date_of("2026-08-28T18:20:00Z") != "2026-08-28":
        f.append("an afternoon game moved off its date")
    # winter date exercises EST (non-DST) branch
    if et_date_of("2026-01-15T02:30:00Z") != "2026-01-14":
        f.append("EST (winter) late-night crossing derived the wrong ET date")
    # 4am UTC = midnight ET boundary: 2026-07-01T04:00Z is 2026-07-01 00:00 EDT
    if et_date_of("2026-07-01T03:59:00Z") != "2026-06-30":
        f.append("the midnight-ET boundary in DST is wrong")

    ev = {"id": "401816704", "date": "2026-08-28T23:10Z",
          "status": {"type": {"name": STATUS_FINAL, "completed": True}},
          "competitions": [{"competitors": [
              {"homeAway": "away", "team": {"abbreviation": "HOU"}, "score": "4"},
              {"homeAway": "home", "team": {"abbreviation": "NYM"}, "score": "2"}]}]}
    rec = normalize_event(ev, "mlb", "2026-08-30T00:00:00Z")
    if not rec or rec["date_et"] != "2026-08-28" or rec["away_score"] != 4:
        f.append(f"normalize_event broke on a final: {rec}")
    rows = result_rows([rec])
    if len(rows) != 1 or rows[0]["game_pk"] != "ESPN_GAMEID:401816704":
        f.append(f"result row lost its namespace: {rows}")
    if rows[0]["result_date"] != "2026-08-28":
        f.append("result row carries the wrong date")
    # a non-final emits NO row (never an invented score)
    sched = dict(rec, status="STATUS_SCHEDULED", away_score=None, home_score=None)
    if result_rows([sched]):
        f.append("a scheduled game emitted a result row")
    # probables are never graded CONFIRMED
    s = parse_summary_probables({"probables": [{"away": {"athlete": {"displayName": "A"}},
                                                "home": {"athlete": {"displayName": "B"}}}]},
                                "1", "mlb", "t")
    if s["grade"] != "IDENTIFIED_UNCONFIRMED" or len(s["probables"]) != 2:
        f.append(f"probables grading wrong: {s['grade']}")

    print(f"feed_espn selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("   -", x)
    return 0 if not f else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(__doc__)
