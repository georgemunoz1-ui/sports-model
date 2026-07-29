#!/usr/bin/env python3
"""Backfill results.csv finals for 2026-07-26/27/28 from frozen single-source extracts.

Sources (both already hash-frozen, both SINGLE-SOURCE owner pastes):
  data/mlb/box/2026-07-27_extract.json            (11 finals; CLE@CIN was PPD that day)
  data/mlb/box/2026-07-26_and_07-28_extract.json  (15 + 15 finals; CLE@CIN doubleheader 7/28;
                                                   ATL@NYM 7/28 box ABSENT from capture)

Rules:
- Idempotent: a (date, away, home) occurrence already present is never re-appended.
- Synthetic game_id 'mlb:2026:box{MMDD}:{AWAY}{HOME}' (+'b' for a doubleheader second game):
  no gamePk is available from these pastes and none is invented. Consumers key on game_id
  strings, not numeric gamePks (build_ml_asof splits on ':' and treats the tail as an opaque key).
- Venue comes only from existing results.csv rows for the same home team (abbr or full name);
  if none exists it stays blank. close_* stays blank — these pastes carry no prices.
- source column: 'savant_box_paste(single-source)' — honest about the one-source provenance.
- KNOWN LIMITS recorded here, not hidden: 7/28 header claims 16 games but the capture holds 15
  boxes (ATL@NYM missing — the 7/29 preview lists ATL@NYM twice, consistent with a PPD->DH, but
  that is corroboration, not proof); CLE@CIN 7/28 game order within the doubleheader is unknown.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

RESULTS = "data/backfill/mlb/2026/results.csv"

FULLNAME = {"AZ": "Arizona Diamondbacks", "ATL": "Atlanta Braves", "BAL": "Baltimore Orioles",
            "BOS": "Boston Red Sox", "CHC": "Chicago Cubs", "CWS": "Chicago White Sox",
            "CIN": "Cincinnati Reds", "CLE": "Cleveland Guardians", "COL": "Colorado Rockies",
            "DET": "Detroit Tigers", "HOU": "Houston Astros", "KC": "Kansas City Royals",
            "LAA": "Los Angeles Angels", "LAD": "Los Angeles Dodgers", "MIA": "Miami Marlins",
            "MIL": "Milwaukee Brewers", "MIN": "Minnesota Twins", "NYM": "New York Mets",
            "NYY": "New York Yankees", "ATH": "Athletics", "PHI": "Philadelphia Phillies",
            "PIT": "Pittsburgh Pirates", "SD": "San Diego Padres", "SEA": "Seattle Mariners",
            "SF": "San Francisco Giants", "STL": "St. Louis Cardinals", "TB": "Tampa Bay Rays",
            "TEX": "Texas Rangers", "TOR": "Toronto Blue Jays", "WSH": "Washington Nationals"}


def new_rows():
    rows = []
    # NOTE: that extract's results_csv field says "NOT backfilled: rows require game_id (gamePk)
    # and venue". This script SUPERSEDES that blocker deliberately (append-only, R6): the game_id
    # written here is an explicitly-synthetic opaque label (box{MMDD}:...) — a key, not a claimed
    # gamePk — and venue is derived from existing rows or left blank. Nothing is invented.
    x27 = json.load(open("data/mlb/box/2026-07-27_extract.json"))
    for g in x27["finals"]:
        a, h = g["game"].split("@")
        rows.append(("2026-07-27", a, h, int(g["away"]), int(g["home"])))
    x = json.load(open("data/mlb/box/2026-07-26_and_07-28_extract.json"))
    for g in x["games"]:
        rows.append((g["date"], g["away"], g["home"], g["away_score"], g["home_score"]))
    return rows


def main():
    existing = list(csv.DictReader(open(RESULTS)))
    fields = existing[0].keys()
    have = {}
    for r in existing:
        have[(r["date"], r["away"], r["home"])] = have.get((r["date"], r["away"], r["home"]), 0) + 1
    ids = {r["game_id"] for r in existing}
    venue_by_home = {}
    for r in existing:  # later rows win: most recent venue per home label
        if r.get("venue"):
            venue_by_home[r["home"]] = r["venue"]

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seen_here, out = {}, []
    for date, a, h, asc, hsc in new_rows():
        key = (date, a, h)
        seen_here[key] = seen_here.get(key, 0) + 1
        if have.get(key, 0) >= seen_here[key]:
            continue  # this occurrence already in results.csv
        # the last ':'-segment is what build_ml_asof uses as its unique per-game key, so the
        # date must live INSIDE that segment (box0727:HOULAA vs box0728:HOULAA collided on it)
        gid = f"mlb:2026:box{date[5:7]}{date[8:10]}-{a}{h}" + ("b" if seen_here[key] > 1 else "")
        if gid in ids:
            raise SystemExit(f"game_id collision: {gid}")
        venue = venue_by_home.get(h) or venue_by_home.get(FULLNAME.get(h, ""), "")
        out.append({
            "sport": "mlb", "season": "2026", "game_id": gid, "date": date, "status": "final",
            "away": a, "home": h, "away_score": asc, "home_score": hsc,
            "home_win": 1 if hsc > asc else 0, "margin": hsc - asc, "total": hsc + asc,
            "neutral_site": "0", "venue": venue,
            "close_ml_away": "", "close_ml_home": "", "close_spread_home": "", "close_total": "",
            "features_json": "", "source": "savant_box_paste(single-source)", "ingested_utc": now,
        })
    if "--dry" in sys.argv:
        for r in out:
            print(r["date"], r["game_id"], f"{r['away']} {r['away_score']} @ {r['home_score']} {r['home']}",
                  f"venue={r['venue'] or 'BLANK'}")
        print(f"{len(out)} rows would be appended")
        return 0
    with open(RESULTS, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fields))
        for r in out:
            w.writerow(r)
    print(f"appended {len(out)} finals to {RESULTS} "
          f"({sum(1 for r in out if r['date']=='2026-07-26')}x 7/26, "
          f"{sum(1 for r in out if r['date']=='2026-07-27')}x 7/27, "
          f"{sum(1 for r in out if r['date']=='2026-07-28')}x 7/28)")
    blank = [r["game_id"] for r in out if not r["venue"]]
    if blank:
        print(f"  venue blank (no prior row for that home team): {blank}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
