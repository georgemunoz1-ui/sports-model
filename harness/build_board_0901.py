#!/usr/bin/env python3
"""THE 2026-09-01 MLB PREGAME BOARD — forecast first, market later, per the restated objective:
"safely find the information -> build the forecast -> then decide whether the wager is".

ACQUISITION, honestly. Every feed rung is EGRESS_BLOCKED (2026-08-31 reachability record, 13
hosts). This slate came over the OPEN_WEB_SEARCH rung: 15 games identified, 27 of 30 probable
starters identified, TWO canonical gamePks harvested from gameday URLs. Search snippets IDENTIFY
and never BIND; ids and starters below carry that grade. OWNER_RELAY is the next rung for the
market board and for starter confirmation — ACQUISITION_INCOMPLETE, not terminated.

THE THREE UNIDENTIFIED STARTERS are null with stated reasons (R1):
  CWS  away @ HOU   "TBD" at every source consulted
  AZ   home vs PHI  Pfaadt started Monday; the series preview names E-Rod without a day
  NYM  away starter Robert Stock appears at ONE source with a 7.40 ERA; retained as named
                     (n=1) but he is not in the pitcher registry regardless
Also DATE-AMBIGUOUS sources were refused: deGrom/Jump (8/31 opener, not 9/1), Nola/Pfaadt
(Monday's game reported under a 9/1 dateline), Harrison (8/31).

MARKET: NOT READ. No admissible price rail is reachable; one aggregator snippet price (SF +150 /
PIT -182) was seen during acquisition and is deliberately NOT captured here — a price glimpsed
through the search rung is neither a book nor a timestamp. Every row is NO_LINE until the owner
relays a board. The forecast freezes first either way; that is the point of this file.

PRIOR_DATE_SERIES_JOIN: 9/1 is game 2 of series that began 8/31 with the SAME matchup keys.
(away, home) does not identify a game; the two harvested pks are 9/1-specific, the rest are null.
"""

MODULE_ID = "build_board_0901"

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SLATE_DATE = "2026-09-01"
OUT = "cards/2026-09-01_mlb_board_FREEZE.json"

SEARCH_GRADE = "SEARCH_IDENTIFIED_UNCONFIRMED"

# game events. id: MLB_GAMEPK harvested from a 9/1-dated gameday URL, else None with the reason
# NO_DATE_BOUND_ID_IN_SEARCH_RESULTS. Starters as identified; None where unresolved.
EVENTS = [
    dict(event="SD@CIN",  away="SD",  home="CIN", away_starter="Randy Vásquez",      home_starter="Nick Lodolo",       game_pk=None),
    dict(event="SF@PIT",  away="SF",  home="PIT", away_starter="Logan Webb",          home_starter="Paul Skenes",       game_pk=None),
    dict(event="NYM@TB",  away="NYM", home="TB",  away_starter="Robert Stock",        home_starter="Ian Seymour",       game_pk=None),
    dict(event="TOR@CLE", away="TOR", home="CLE", away_starter="Spencer Arrighetti",  home_starter="Gavin Williams",    game_pk=824391),
    dict(event="SEA@BOS", away="SEA", home="BOS", away_starter="Bryan Woo",           home_starter="Jedixson Paez",     game_pk=None),
    dict(event="ATL@WSH", away="ATL", home="WSH", away_starter="AJ Smith-Shawver",    home_starter="Jake Irvin",        game_pk=None),
    dict(event="DET@MIN", away="DET", home="MIN", away_starter="Troy Melton",         home_starter="Andrew Morris",     game_pk=None),
    dict(event="MIA@KC",  away="MIA", home="KC",  away_starter="Tyler Phillips",      home_starter="Randy Dobnak",      game_pk=None),
    dict(event="MIL@CHC", away="MIL", home="CHC", away_starter="Robert Gasser",       home_starter="Matthew Boyd",      game_pk=None),
    dict(event="ATH@TEX", away="ATH", home="TEX", away_starter="J.T. Ginn",           home_starter="MacKenzie Gore",    game_pk=None),
    dict(event="CWS@HOU", away="CWS", home="HOU", away_starter=None,                  home_starter="Sean Burke",        game_pk=None,
         away_starter_null_reason="TBD_AT_EVERY_SOURCE_CONSULTED"),
    dict(event="BAL@COL", away="BAL", home="COL", away_starter="Trevor Rogers",       home_starter="Gabriel Hughes",    game_pk=None),
    dict(event="NYY@LAA", away="NYY", home="LAA", away_starter="Gerrit Cole",         home_starter="Grayson Rodriguez", game_pk=None),
    dict(event="PHI@AZ",  away="PHI", home="AZ",  away_starter="Jesús Luzardo",       home_starter=None,                game_pk=None,
         home_starter_null_reason="SERIES_PREVIEW_NAMES_ERON_WITHOUT_A_DAY_PFAADT_USED_MONDAY"),
    dict(event="STL@LAD", away="STL", home="LAD", away_starter="Michael McGreevy",    home_starter="Eric Lauer",        game_pk=823908),
]


def build(trials=30000):
    import mlb_daily_coordinator as C
    res = C.run(SLATE_DATE, [], extra=EVENTS, trials=trials)
    res["acquisition"] = {
        "rung": "OPEN_WEB_SEARCH", "grade": SEARCH_GRADE,
        "disposition": "ACQUISITION_INCOMPLETE",
        "next_rung": "OWNER_RELAY (market board; starter confirmation)",
        "ids": {e["event"]: (("MLB_GAMEPK:%d" % e["game_pk"]) if e.get("game_pk")
                             else None) for e in EVENTS},
        "id_null_reason": "NO_DATE_BOUND_ID_IN_SEARCH_RESULTS",
        "market_read": False,
        "prices_seen_and_refused": ["SF@PIT snippet +150/-182 - no book, no timestamp"],
    }
    return res


def selftest():
    f = []
    evs = {e["event"] for e in EVENTS}
    if len(EVENTS) != 15 or len(evs) != 15:
        f.append("slate is not 15 unique games")
    for e in EVENTS:
        a, h = e["event"].split("@")
        if a != e["away"] or h != e["home"]:
            f.append("event key disagrees with team fields: %s" % e["event"])
        for side in ("away", "home"):
            if e.get("%s_starter" % side) is None and not e.get("%s_starter_null_reason" % side):
                f.append("%s %s starter null without a reason" % (e["event"], side))
    r = build(trials=2000)
    if r["n_scheduled"] != 15 or r["summary"]["forecasted"] != 15:
        f.append("coordinator did not forecast the full slate: %r" % r["summary"])
    if r["summary"]["true_no_forecast"] != 0:
        f.append("a TRUE_NO_FORECAST leaked in: %r" % r["summary"])
    import mlb_daily_coordinator as C
    if any(g["overlay"].get("execution_state") != C.EXEC_NO_LINE for g in r["games"]):
        f.append("an execution state other than NO_LINE with no market read")
    pfs = {g["snapshot"]["park_factor"] for g in r["games"]}
    if pfs == {1.0}:
        f.append("every park factor is 1.0 - the silent-default defect is back")
    print("%s selftest: %s" % (MODULE_ID, "PASS" if not f else "FAIL"))
    for x in f:
        print("  -", x)
    return not f


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    board = build()
    os.makedirs("cards", exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(board, fh, indent=1, sort_keys=True)
    print("frozen ->", OUT)
    print(json.dumps(board["summary"], indent=1))
