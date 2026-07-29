#!/usr/bin/env python3
"""Parse the frozen Savant Statcast Game Preview paste into structured player profiles.

Input : data/mlb/statcast_previews/2026-07-29_savant_previews_paste.txt (sha256 in output)
Output: data/mlb/statcast_previews/2026-07-29_profiles.json

What this is: the first batter-level rate data in the repo — per-player season-to-date Statcast
profiles (contact quality, batted-ball mix, plate discipline) plus per-team pitcher profiles and
catcher pop times, for every team on the 2026-07-29 slate.

What this is NOT: it is not the ML-E1 player-season event-count dataset (no PA totals, no
mutually-exclusive event counts, no ages, no multi-year history), so the ML-E1 evidence gate is
unchanged by this file. And it is a SNAPSHOT: season-to-date at capture time. As-of usable ONLY
for slates on/after 2026-07-29; applying it to any earlier date is LOOK-AHEAD (same caveat class
as data/mlb/team_batting_asof).

Deliberately skipped (mangled by copy-paste, would require guessing): Pitcher Arsenals pitch-mix
rows, Outs Above Average grids, and the per-featured-pitcher batted-ball/discipline duplicates.
Skips are counted, not silent.
"""

from __future__ import annotations

import hashlib
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

SRC = "data/mlb/statcast_previews/2026-07-29_savant_previews_paste.txt"
OUT = "data/mlb/statcast_previews/2026-07-29_profiles.json"

HIT_COLS = ("pos", "bbe", "la_deg", "ev_mph", "hard_hit_pct", "xwoba", "xba", "xslg",
            "k_pct", "bb_pct", "sprint")
PIT_COLS = ("pos", "bbe", "la_deg", "ev_mph", "hard_hit_pct", "xwoba", "xba", "xslg",
            "k_pct", "bb_pct")
SBB_COLS = ("weak_pct", "topped_pct", "under_pct", "flare_burner_pct", "solid_pct", "barrel_pct")
BBP_COLS = ("gb_pct", "fb_pct", "ld_pct", "pu_pct", "pull_pct", "straight_pct", "oppo_pct")
PD_COLS = ("zone_pct", "zone_sw_pct", "chase_pct", "edge_pct", "first_pitch_sw_pct",
           "swing_pct", "whiff_pct")


def _num(t):
    t = t.strip()
    if t in ("--", "", "—"):
        return None
    try:
        return float(t)
    except ValueError:
        return t  # positions etc. stay strings


def _name(t):
    t = t.strip()
    if t.endswith("*"):
        return t.rstrip("* ").strip(), False
    return t, True


def _rows(lines, i, ncols, cols, stop_prefixes, with_vs):
    """Consume tab-separated rows of exactly name+ncols (+'Vs.') until a stop line."""
    out = []
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s or any(s.startswith(p) for p in stop_prefixes):
            break
        toks = [t for t in ln.split("\t") if t.strip() != ""]
        if with_vs and toks and toks[-1] == "Vs.":
            toks = toks[:-1]
        if len(toks) != ncols + 1:
            break
        nm, qual = _name(toks[0])
        row = {"name": nm, "qualified": qual}
        row.update({c: _num(v) for c, v in zip(cols, toks[1:])})
        out.append(row)
        i += 1
    return out, i


def parse():
    raw = open(SRC, "rb").read()
    pages = open(SRC).read().split("page break")
    teams, skipped = [], {"arsenal_tables": 0, "oaa_tables": 0, "featured_pitcher_dupes": 0}
    for pg in pages:
        lines = pg.splitlines()
        starts = [i for i, ln in enumerate(lines) if ln.strip() == "Awaiting Starting Lineup"]
        for si, st in enumerate(starts):
            tname = lines[st - 1].strip()
            end = starts[si + 1] - 1 if si + 1 < len(starts) else len(lines)
            sec = lines[st:end]
            t = {"team": tname, "hitters": [], "hitters_statcast_bb": [], "hitters_bb": [],
                 "hitters_discipline": [], "pitchers": [], "catcher_pop_times": []}
            in_pitcher_zone = False
            i = 0
            while i < len(sec):
                s = sec[i].strip()
                if s == "Hitters" and i + 1 < len(sec) and sec[i + 1].startswith("Name\t"):
                    t["hitters"], i = _rows(sec, i + 2, 11, HIT_COLS, ("Starting Lineup",), True)
                    continue
                if s == "Pitchers" and i + 1 < len(sec) and sec[i + 1].startswith("Name\t"):
                    in_pitcher_zone = True
                    t["pitchers"], i = _rows(sec, i + 2, 10, PIT_COLS, ("Hide Non-Starters",), True)
                    continue
                if s == "Statcast Batted Ball Profile":
                    if in_pitcher_zone:
                        skipped["featured_pitcher_dupes"] += 1
                    else:
                        t["hitters_statcast_bb"], i = _rows(sec, i + 2, 6, SBB_COLS, (), False)
                        continue
                if s == "Batted Ball Profile":
                    if in_pitcher_zone:
                        skipped["featured_pitcher_dupes"] += 1
                    else:
                        t["hitters_bb"], i = _rows(sec, i + 2, 7, BBP_COLS, (), False)
                        continue
                if s == "Plate Discipline":
                    if in_pitcher_zone:
                        skipped["featured_pitcher_dupes"] += 1
                    else:
                        t["hitters_discipline"], i = _rows(sec, i + 2, 7, PD_COLS, (), False)
                        continue
                if s == "Pitcher Arsenals":
                    skipped["arsenal_tables"] += 1
                if s == "Outs Above Average":
                    skipped["oaa_tables"] += 1
                if s == "Catcher Pop Times":
                    rows, i = _rows(sec, i + 2, 3, ("arm", "exchange", "avg_pop_2b"), (), False)
                    t["catcher_pop_times"] = rows
                    continue
                i += 1
            teams.append(t)

    problems = []
    for t in teams:
        if not t["hitters"]:
            problems.append(f"{t['team']}: no hitters parsed")
        nh = len(t["hitters"])
        for key in ("hitters_statcast_bb", "hitters_bb", "hitters_discipline"):
            if t[key] and abs(len(t[key]) - nh) > 2:
                problems.append(f"{t['team']}: {key} rows {len(t[key])} vs {nh} hitters")

    out = {"record_id": "SAVANT-PREVIEW-PROFILES-2026-07-29",
           "source_file": SRC, "source_sha256": hashlib.sha256(raw).hexdigest(),
           "provenance": "owner upload 2026-07-29; Baseball Savant Statcast Game Preview pages, "
                         "corroborated by 5 owner screenshots (PHI@MIA, AZ@PIT, TOR@WSH, BAL@DET, ATL@NYM)",
           "snapshot_caveat": "SEASON-TO-DATE SNAPSHOT at capture. As-of usable ONLY for slates "
                              ">= 2026-07-29; any earlier application is LOOK-AHEAD. Not event "
                              "counts: ML-E1 evidence gate unchanged.",
           "slate_date": "2026-07-29",
           "teams": teams, "skipped_tables": skipped, "problems": problems}
    json.dump(out, open(OUT, "w"), indent=1)
    nH = sum(len(t["hitters"]) for t in teams)
    nP = sum(len(t["pitchers"]) for t in teams)
    print(f"{OUT}: {len(teams)} teams, {nH} hitter profiles, {nP} pitcher profiles, "
          f"{len(problems)} problems, skipped {skipped}")
    for p in problems:
        print("  PROBLEM: " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(parse())
