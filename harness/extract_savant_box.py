#!/usr/bin/env python3
"""Extract final scores from a frozen Baseball Savant scoreboard paste (multi-date).

Input: data/mlb/box/2026-07-26_and_07-28_savant_paste.txt (sha256 recorded in the extract).
Output: data/mlb/box/2026-07-26_and_07-28_extract.json

Parsing contract (refuse rather than guess):
- Sections are delimited by lines matching 'N MLB Games - M/D/YYYY'; every FINAL block after a
  section header belongs to that header's date. A block that cannot be parsed cleanly is recorded
  under 'unparsed' with its line number — never silently dropped, never patched by hand.
- Each FINAL block: away name line(s), a ' A @ H ' score line, home name line(s); the line-score
  row R totals are cross-checked against the score line and any mismatch flags the game.
- SINGLE-SOURCE: one upload, no independent cross-check. Rows derived from this extract carry
  source 'savant_box_paste(single-source)'.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE)

SRC = "data/mlb/box/2026-07-26_and_07-28_savant_paste.txt"
OUT = "data/mlb/box/2026-07-26_and_07-28_extract.json"

NICK2ABBR = {
    "Guardians": "CLE", "Rays": "TB", "Dbacks": "AZ", "D-backs": "AZ", "Nationals": "WSH",
    "Cubs": "CHC", "Pirates": "PIT", "Yankees": "NYY", "Phillies": "PHI", "Red Sox": "BOS",
    "Athletics": "ATH", "Blue Jays": "TOR", "Orioles": "BAL", "Tigers": "DET", "Braves": "ATL",
    "Mets": "NYM", "Brewers": "MIL", "Giants": "SF", "Rockies": "COL", "Padres": "SD",
    "Rangers": "TEX", "Reds": "CIN", "Royals": "KC", "Twins": "MIN", "White Sox": "CWS",
    "Cardinals": "STL", "Astros": "HOU", "Angels": "LAA", "Mariners": "SEA", "Dodgers": "LAD",
    "Marlins": "MIA",
}

SCORE_RE = re.compile(r"^\s*(\d+)\s*@\s*(\d+)\s*$")
SECTION_RE = re.compile(r"^(\d+) MLB Games - (\d{1,2})/(\d{1,2})/(\d{4})")


def _abbr(name_lines):
    """Map trailing nickname token(s) of a displayed team name to the repo abbreviation."""
    joined = " ".join(x.strip() for x in name_lines if x.strip())
    for nick, ab in NICK2ABBR.items():
        if joined.endswith(nick):
            return ab, joined
    return None, joined


def extract():
    lines = open(SRC).read().splitlines()
    src_sha = hashlib.sha256(open(SRC, "rb").read()).hexdigest()

    sections = []          # (line_idx, date_iso, claimed_count)
    for i, ln in enumerate(lines):
        m = SECTION_RE.match(ln.strip())
        if m:
            n, mo, dy, yr = m.groups()
            # line 1 of the paste is a combined title naming BOTH dates -> not a section start
            if "&" in ln:
                continue
            sections.append((i, f"{yr}-{int(mo):02d}-{int(dy):02d}", int(n)))
    games, unparsed = [], []
    for i, ln in enumerate(lines):
        if ln.strip() != "FINAL":
            continue
        sec = [s for s in sections if s[0] < i]
        if not sec:
            unparsed.append({"line": i + 1, "reason": "FINAL before any section header"})
            continue
        _, date, _ = sec[-1]
        # find the score line within the next 8 lines
        j = next((k for k in range(i + 1, min(i + 9, len(lines)))
                  if SCORE_RE.match(lines[k])), None)
        if j is None:
            unparsed.append({"line": i + 1, "reason": "no 'A @ H' score line after FINAL"})
            continue
        m = SCORE_RE.match(lines[j])
        away_lines = [x for x in lines[i + 1:j] if x.strip()]
        k = j + 1
        home_lines = []
        while k < len(lines) and not lines[k].strip().startswith(("Direct Link", "Scoreboard")):
            if lines[k].strip():
                home_lines.append(lines[k])
            k += 1
        a_ab, a_disp = _abbr(away_lines)
        h_ab, h_disp = _abbr(home_lines)
        rec = {"date": date, "away": a_ab, "home": h_ab,
               "away_display": a_disp, "home_display": h_disp,
               "away_score": int(m.group(1)), "home_score": int(m.group(2)),
               "src_line": i + 1, "flags": []}
        if a_ab is None or h_ab is None:
            unparsed.append({"line": i + 1, "reason": f"unmapped team name: {a_disp!r} / {h_disp!r}"})
            continue
        # cross-check: the two line-score rows' R totals (tokens just before the first '.xxx' token)
        rvals = []
        for k2 in range(j + 1, min(j + 40, len(lines))):
            toks = [t for t in lines[k2].split("\t") if t.strip()]
            dot = next((x for x, t in enumerate(toks) if re.fullmatch(r"\.\d{3}", t)), None)
            if dot is not None and dot >= 2 and toks[dot - 2].isdigit():
                rvals.append(int(toks[dot - 2]))
            if len(rvals) == 2:
                break
        if len(rvals) == 2 and (rvals[0] != rec["away_score"] or rvals[1] != rec["home_score"]):
            rec["flags"].append(f"LINESCORE_MISMATCH:{rvals} vs @-line")
        elif len(rvals) < 2:
            rec["flags"].append("LINESCORE_ROWS_NOT_FOUND")
        games.append(rec)

    by_date = {}
    for g in games:
        by_date.setdefault(g["date"], []).append(g)
    discrepancies = []
    for idx, date, claimed in sections:
        got = len(by_date.get(date, []))
        if got != claimed:
            discrepancies.append(f"{date}: header claims {claimed} games, {got} FINAL boxes parsed "
                                 "— completeness NOT established for this date")
    # duplicate matchup on one date = doubleheader candidate, surfaced not assumed
    for date, gs in by_date.items():
        seen = {}
        for g in gs:
            key = (g["away"], g["home"])
            if key in seen:
                g["flags"].append("DUPLICATE_MATCHUP_SAME_DATE (doubleheader?)")
            seen[key] = True

    out = {"record_id": "SAVANT-BOX-EXTRACT-0726-0728",
           "source_file": SRC, "source_sha256": src_sha,
           "provenance": "owner upload 2026-07-29; SINGLE-SOURCE, no independent cross-check",
           "sections": [{"date": d, "claimed_games": c} for _, d, c in sections],
           "games": games, "unparsed": unparsed, "count_discrepancies": discrepancies}
    json.dump(out, open(OUT, "w"), indent=1)
    print(f"{OUT}: {len(games)} games "
          f"({', '.join(f'{d}:{len(by_date[d])}' for d in sorted(by_date))}), "
          f"{len(unparsed)} unparsed, {len(discrepancies)} count discrepancies")
    for d in discrepancies:
        print("  DISCREPANCY: " + d)
    for u in unparsed:
        print(f"  UNPARSED line {u['line']}: {u['reason']}")
    flagged = [g for g in games if g["flags"]]
    for g in flagged:
        print(f"  FLAG {g['date']} {g['away']}@{g['home']}: {g['flags']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(extract())
