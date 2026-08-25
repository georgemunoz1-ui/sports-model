#!/usr/bin/env python3
"""Deterministically parse an owner-supplied Statcast/box-score dump into finals.

WHY THIS EXISTS (2026-08-10): result ingestion had been done by an LLM reading WebSearch snippets.
On 2026-08-08 that produced 4 wrong rows out of 15 (3 with the WRONG WINNER) — ATH@BOS, LAA@MIA and
DET@SF were all recorded with the winner reversed, and those wrong results were then used to GRADE the
model. The same failure mode had already occurred on 7/29 (two extra-innings games captured at wrong
regulation-era scores) and 7/23 (a game missed entirely).

A search snippet is a summary written by a language model about a page; a box-score dump is the record
itself. This module reads the record with a parser (no model in the loop), so the same bytes always
produce the same finals, and it CROSS-VALIDATES each score against the game's own linescore where the
dump provides one (innings must sum to the final). That structural check is what a snippet can never
offer.

Source tier (see RESULT_SOURCE_TIER in the results schema):
  1 = official box / owner-supplied box dump (this parser)   -> may FINALIZE a graded result
  2 = reputable outlet recap                                  -> PROVISIONAL
  3 = search snippet / aggregator                             -> PROVISIONAL, never finalizes

Usage:
  python3 harness/parse_box_dump.py <dump.txt>              # print parsed finals + validation
  python3 harness/parse_box_dump.py <dump.txt> --json out.json
  python3 harness/parse_box_dump.py --selftest
"""

from __future__ import annotations

MODULE_ID = "parse_box_dump"

import argparse
import hashlib
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: City/team display names as they appear in the dump -> canonical abbreviation.
TEAM = {
    "Arizona Dbacks": "AZ", "Arizona Diamondbacks": "AZ", "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS", "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS", "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL", "Detroit Tigers": "DET", "Houston Astros": "HOU",
    "Kansas City Royals": "KC", "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN",
    "New York Mets": "NYM", "New York Yankees": "NYY", "Athletics Athletics": "ATH",
    "Athletics": "ATH", "Philadelphia Phillies": "PHI", "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD", "San Francisco Giants": "SF", "Seattle Mariners": "SEA",
    "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TB", "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
}

SCORE_RE = re.compile(r"^\s*(\d+)\s*@\s*(\d+)\s*$")
DATE_RE = re.compile(r"MLB Games\s*-\s*(\d{1,2})/(\d{1,2})/(\d{4})")


def _linescore_cells(line):
    """Tab/space-separated linescore row -> leading run cells, or None.

    The dump emits rows like "\t0\t0\t0\t0\t2\t0\t0\t1\t1\t4\t9\t.325\t42.1\t✖":
    a leading empty cell, then the per-inning runs, then R, H, and trailing non-integer
    columns (xBA/HH%/ABS). We keep only the leading run of integer-or-X cells, which is
    exactly [innings..., R, H].
    """
    parts = [p.strip() for p in re.split(r"\t|\s{2,}", line)]
    cells = []
    for p in parts:
        if p == "":
            if cells:
                break
            continue
        if p.upper() == "X":
            cells.append(0)
        elif p.isdigit():
            cells.append(int(p))
        else:
            break
    # A real linescore row is [inning_1..inning_N, R, H] -> at least 11 cells.
    if len(cells) < 11:
        return None
    # Reject the COLUMN HEADER "1 2 3 4 5 6 7 8 9 R H ..." — it parses as 1..9 then stops at "R".
    # (This header caused a false-positive "CONTRADICTED" on every game before the guard existed.)
    if cells == list(range(1, len(cells) + 1)):
        return None
    return cells


def _norm_team(chunk: str):
    """Map the 1-3 display lines preceding/following a score line to an abbreviation."""
    c = " ".join(chunk.split())
    if c in TEAM:
        return TEAM[c]
    for name, ab in TEAM.items():  # suffix/substring match ("Los Angeles Angels" inside a longer join)
        if c.endswith(name) or name in c:
            return ab
    return None


def parse(path):
    """Parse a dump into {date: [ {away,home,away_score,home_score,home_win,linescore_ok}, ... ]}."""
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    cur_date = None
    by_date = {}
    for i, ln in enumerate(lines):
        d = DATE_RE.search(ln)
        if d:
            mm, dd, yy = int(d.group(1)), int(d.group(2)), int(d.group(3))
            cur_date = f"{yy:04d}-{mm:02d}-{dd:02d}"
            by_date.setdefault(cur_date, [])
            continue
        m = SCORE_RE.match(ln)
        if not m or cur_date is None:
            continue
        away_score, home_score = int(m.group(1)), int(m.group(2))
        before = [x.strip() for x in lines[max(0, i - 4):i] if x.strip()]
        after = [x.strip() for x in lines[i + 1:i + 5] if x.strip()]
        away = _norm_team(" ".join(before[-2:])) or _norm_team(" ".join(before[-3:]))
        home = _norm_team(" ".join(after[:2])) or _norm_team(" ".join(after[:3]))
        if not away or not home:
            continue
        rec = {
            "away": away, "home": home,
            "away_score": away_score, "home_score": home_score,
            "home_win": int(home_score > away_score),
            "total": away_score + home_score, "margin": home_score - away_score,
            "source_line": i + 1,
        }
        rec["linescore_ok"] = _linescore_check(lines, i, away_score, home_score)
        by_date[cur_date].append(rec)
    return by_date


def _linescore_check(lines, idx, away_score, home_score):
    """If a linescore block follows, verify the innings sum to the reported final.

    Returns True (verified), False (contradicted) or None (no linescore present).
    """
    rows = []
    for j in range(idx, min(idx + 16, len(lines))):
        cells = _linescore_cells(lines[j])
        if cells:
            rows.append(cells)
            if len(rows) == 2:
                break
    if len(rows) < 2:
        return None
    # Layout is [inning_1..inning_N, R, H]. N is unknown (9, or more for extras), so try each:
    # the innings must sum to R for BOTH teams AND those R values must equal the stated final.
    for n_inn in range(9, min(len(rows[0]), len(rows[1]))):
        a_r, h_r = rows[0][n_inn], rows[1][n_inn]
        if (sum(rows[0][:n_inn]) == a_r == away_score
                and sum(rows[1][:n_inn]) == h_r == home_score):
            return True
    return False


def validate(by_date, expect_per_date=None):
    """Structural validation. Returns (ok, problems)."""
    problems = []
    # A total parse failure must FAIL, not pass vacuously. The first build returned
    # "VALIDATION: PASS", exit 0 on zero games parsed — a gate that green-lights an empty
    # result set is worse than none, because it reads as confirmation.
    if not by_date or not any(games for games in by_date.values()):
        problems.append("no games parsed — refusing to report PASS on an empty parse")
        return False, problems
    for date, games in sorted(by_date.items()):
        seen = set()
        for g in games:
            key = (g["away"], g["home"])
            if key in seen:
                problems.append(f"{date}: duplicate matchup {g['away']}@{g['home']}")
            seen.add(key)
            if g["away_score"] == g["home_score"]:
                problems.append(f"{date}: {g['away']}@{g['home']} is a TIE ({g['away_score']}-"
                                f"{g['home_score']}) — MLB games cannot end tied")
            if g["linescore_ok"] is False:
                problems.append(f"{date}: {g['away']}@{g['home']} linescore does not sum to the "
                                f"stated final {g['away_score']}-{g['home_score']}")
            if g["away"] == g["home"]:
                problems.append(f"{date}: {g['away']} listed against itself")
        if expect_per_date and date in expect_per_date and len(games) != expect_per_date[date]:
            problems.append(f"{date}: parsed {len(games)} games, expected {expect_per_date[date]}")
    return (not problems), problems


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def selftest():
    fails = []
    # team normalisation, including the doubled "Athletics Athletics" the dump emits
    for disp, ab in (("Athletics Athletics", "ATH"), ("Los Angeles Angels", "LAA"),
                     ("Arizona Dbacks", "AZ"), ("St. Louis Cardinals", "STL")):
        if _norm_team(disp) != ab:
            fails.append(f"team norm {disp!r} -> {_norm_team(disp)!r} != {ab}")
    # orientation: "4 @ 5" means AWAY 4, HOME 5 -> home_win=1
    m = SCORE_RE.match(" 4 @ 5 ")
    if not m or int(m.group(1)) != 4 or int(m.group(2)) != 5:
        fails.append("score orientation parse")
    # a tie must be reported as a problem (structural impossibility in MLB)
    ok, probs = validate({"2026-01-01": [{"away": "ATL", "home": "NYY", "away_score": 3,
                                          "home_score": 3, "linescore_ok": None}]})
    if ok or not any("TIE" in p for p in probs):
        fails.append("tie not flagged")
    # a contradicted linescore must be reported
    ok, probs = validate({"2026-01-01": [{"away": "ATL", "home": "NYY", "away_score": 3,
                                          "home_score": 4, "linescore_ok": False}]})
    if ok or not any("linescore" in p for p in probs):
        fails.append("bad linescore not flagged")
    # count mismatch must be reported
    ok, probs = validate({"2026-01-01": [{"away": "ATL", "home": "NYY", "away_score": 3,
                                          "home_score": 4, "linescore_ok": True}]},
                         expect_per_date={"2026-01-01": 15})
    if ok or not any("expected 15" in p for p in probs):
        fails.append("game-count mismatch not flagged")
    # REGRESSION FIXTURE (real dump format): the column header must NOT be read as a linescore,
    # and a correct linescore must verify. An earlier build parsed the header "1 2 3 ... 9 R H"
    # as a data row and reported every game CONTRADICTED — a checker that cries wolf on valid
    # data is worse than no checker, so this fixture is mandatory.
    block = [
        " 4 @ 5 ",
        "Scoreboard Illustrator Box Score",
        "1\t2\t3\t4\t5\t6\t7\t8\t9\tR\tH\txBA\tHH%\tABS",
        "\t0\t0\t0\t0\t2\t0\t0\t1\t1\t4\t9\t.325\t42.1\t✖",
        "\t0\t1\t0\t0\t2\t0\t1\t1\tX\t5\t8\t.251\t46.2\t↺",
    ]
    if _linescore_cells(block[2]) is not None:
        fails.append("column header parsed as a linescore row (false-positive source)")
    if _linescore_check(block, 0, 4, 5) is not True:
        fails.append("valid linescore did not verify (false positive)")
    if _linescore_check(block, 0, 9, 1) is not False:
        fails.append("wrong score not contradicted by linescore (false negative)")
    # empty parse must FAIL, never pass vacuously
    ok, probs = validate({})
    if ok or not any("no games parsed" in p for p in probs):
        fails.append("empty parse reported PASS (vacuous green light)")
    ok, _ = validate({"2026-01-01": []})
    if ok:
        fails.append("date with zero games reported PASS")
    if fails:
        print("parse_box_dump selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("parse_box_dump selftest: PASS (team normalisation, away@home orientation, tie guard, "
          "linescore-sum guard, game-count guard)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", nargs="?")
    ap.add_argument("--json")
    ap.add_argument("--expect", type=int, help="expected games per date")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.dump:
        ap.error("dump path required")
    by_date = parse(a.dump)
    exp = {d: a.expect for d in by_date} if a.expect else None
    ok, problems = validate(by_date, exp)
    h = sha256(a.dump)
    for date, games in sorted(by_date.items()):
        ver = sum(1 for g in games if g["linescore_ok"] is True)
        print(f"\n{date}: {len(games)} games  (linescore-verified: {ver})")
        for g in games:
            mark = {True: "verified", False: "CONTRADICTED", None: "no-linescore"}[g["linescore_ok"]]
            print(f"  {g['away']:>3} {g['away_score']:>2} @ {g['home_score']:<2} {g['home']:<3}  {mark}")
    print(f"\nsource sha256: {h}")
    print("VALIDATION:", "PASS" if ok else "PROBLEMS")
    for p in problems:
        print("  ! " + p)
    if a.json:
        json.dump({"source_file": os.path.abspath(a.dump), "source_sha256": h,
                   "source_tier": 1, "parser": "harness/parse_box_dump.py",
                   "validation_ok": ok, "problems": problems, "by_date": by_date},
                  open(a.json, "w"), indent=1)
        print(f"wrote {a.json}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
