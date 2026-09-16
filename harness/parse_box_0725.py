#!/usr/bin/env python3
"""Parse the 2026-07-25 box-score paste LOCALLY.

Doctrine: 'Parse raw locally, NEVER trust the model-reported COUNT/SUM.'
Origin: the WSH 813-vs-858 extraction error.

Input : data/mlb/box/2026-07-25_paste.txt  (verbatim user paste, byte-for-byte)
Output: data/mlb/box/2026-07-25_raw.json

Nothing here is transcribed by hand. Every number is read off the raw text by
this script, and the per-pitcher SO column is checked against the Team Pitching
SO total, which is an INDEPENDENT field in the same paste. A game whose pitcher
SO do not sum to its team total is reported, not silently repaired.
"""

MODULE_ID = "parse_box_0725"
import json, re, sys, unicodedata

SRC = "data/mlb/box/2026-07-25_paste.txt"
OUT = "data/mlb/box/2026-07-25_raw.json"

def ascii_(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()

lines = open(SRC, encoding="utf-8").read().split("\n")

SCORE = re.compile(r"^\s*(\d+)\s*@\s*(\d+)\s*$")
PITCH_HDR = re.compile(r"\tIP\tH\tR\tER\tBB\tSO\tHR\tNP\tERA")
BAT_HDR = re.compile(r"\tPos\tAB\tR\tH\t2B\t3B\tHR\tRBI\tBB\tSO\t")
TP_HDR = "Team Pitching\tPitches"

# --- locate game blocks by the FINAL sentinel -------------------------------
starts = [i for i, L in enumerate(lines) if L.strip() == "FINAL"]
blocks = []
for n, s in enumerate(starts):
    e = starts[n + 1] if n + 1 < len(starts) else len(lines)
    blocks.append((s, e))

games = []
for s, e in blocks:
    blk = lines[s:e]
    # score line + team names
    si = next(i for i, L in enumerate(blk) if SCORE.match(L))
    m = SCORE.match(blk[si])
    away_r, home_r = int(m.group(1)), int(m.group(2))
    away_name = ascii_(blk[si - 2].strip() + " " + blk[si - 1].strip()).strip()
    home_name = ascii_(blk[si + 1].strip() + " " + blk[si + 2].strip()).strip()

    # linescores: the two rows right after the inning header
    li = next(i for i, L in enumerate(blk) if L.startswith("1\t2\t3\t"))
    def ls_row(row):
        return [c for c in row.split("\t") if c.strip() != ""]
    away_ls, home_ls = ls_row(blk[li + 1]), ls_row(blk[li + 2])

    # pitching sections (2 per game, away first then home)
    pitch_secs = []
    for i, L in enumerate(blk):
        if PITCH_HDR.search(L):
            rows = []
            j = i + 1
            while j < len(blk):
                f = blk[j].split("\t")
                if len(f) < 10 or BAT_HDR.search(blk[j]) or PITCH_HDR.search(blk[j]) \
                   or blk[j].startswith(TP_HDR):
                    break
                if not re.match(r"^\d+\.?\d*$", f[1].strip()):
                    break
                rows.append(dict(p=ascii_(f[0].strip()), ip=float(f[1]), h=int(f[2]),
                                 r=int(f[3]), er=int(f[4]), bb=int(f[5]), so=int(f[6]),
                                 hr=int(f[7]), np=int(f[8])))
                j += 1
            pitch_secs.append(rows)

    # batting sections (2 per game, away first then home) -> opponent K totals
    bat_so = []
    for i, L in enumerate(blk):
        if BAT_HDR.search(L):
            f = L.split("\t")
            so_ix = f.index("SO")
            tot, j = 0, i + 1
            while j < len(blk):
                g = blk[j].split("\t")
                if len(g) <= so_ix or not re.match(r"^\d+$", g[2].strip()):
                    break
                tot += int(g[so_ix]); j += 1
            bat_so.append(tot)

    # Team Pitching block: header then exactly two abbreviation rows
    ti = next(i for i, L in enumerate(blk) if L.startswith(TP_HDR))
    hdr = blk[ti].split("\t")
    so_col = hdr.index("SO")
    tp = []
    for j in (ti + 1, ti + 2):
        f = blk[j].split("\t")
        tp.append(dict(abbr=f[0].strip(), so=int(f[so_col])))

    games.append(dict(
        away_name=away_name, home_name=home_name,
        away=tp[0]["abbr"], home=tp[1]["abbr"],
        away_r=away_r, home_r=home_r,
        away_line=away_ls, home_line=home_ls,
        pitchers_away=pitch_secs[0] if pitch_secs else [],
        pitchers_home=pitch_secs[1] if len(pitch_secs) > 1 else [],
        team_so_away=tp[0]["so"], team_so_home=tp[1]["so"],
        bat_so_away=bat_so[0] if bat_so else None,
        bat_so_home=bat_so[1] if len(bat_so) > 1 else None,
    ))

# --- checksums --------------------------------------------------------------
problems = []
so_disputes = []
for g in games:
    tag = "%s@%s" % (g["away"], g["home"])
    # THREE independent SO fields per staff:
    #   (a) sum of that staff's per-pitcher SO
    #   (b) that staff's Team Pitching SO total
    #   (c) the OPPOSING lineup's batting SO total
    # Two agreeing against one is a source defect, and the majority is recorded.
    for side, opp in (("away", "home"), ("home", "away")):
        a = sum(p["so"] for p in g["pitchers_" + side])
        b = g["team_so_" + side]
        c = g["bat_so_" + opp]
        g["so_" + side] = dict(pitcher_lines=a, team_pitching=b, opp_batting=c)
        if not (a == b == c):
            votes = {}
            for src, v in (("pitcher_lines", a), ("team_pitching", b), ("opp_batting", c)):
                votes.setdefault(v, []).append(src)
            best = max(votes, key=lambda v: len(votes[v]))
            rec = dict(game=tag, staff=g[side], pitcher_lines=a, team_pitching=b,
                       opp_batting=c, resolved=best,
                       agree=votes[best], dissent=[s for v in votes if v != best for s in votes[v]],
                       decisive=len(votes[best]) >= 2)
            so_disputes.append(rec)
            if not rec["decisive"]:
                problems.append("%s %s staff: three-way SO disagreement %s/%s/%s - UNRESOLVED"
                                % (tag, g[side], a, b, c))
        else:
            g["so_" + side]["resolved"] = a
    for side in ("away", "home"):
        d = g["so_" + side]
        if "resolved" not in d:
            m = next((x for x in so_disputes if x["game"] == tag and x["staff"] == g[side]), None)
            d["resolved"] = m["resolved"] if m and m["decisive"] else None
    # IP integrity: total outs should be a whole number of innings
    for side in ("away", "home"):
        outs = 0
        for p in g["pitchers_" + side]:
            whole = int(p["ip"]); frac = round((p["ip"] - whole) * 10)
            if frac not in (0, 1, 2):
                problems.append("%s %s %s: illegal IP %.1f" % (tag, side, p["p"], p["ip"]))
            outs += whole * 3 + frac
        g["outs_" + side] = outs
    # runs allowed by away staff must equal home runs scored, and vice versa
    ra_away = sum(p["r"] for p in g["pitchers_away"])
    ra_home = sum(p["r"] for p in g["pitchers_home"])
    if ra_away != g["home_r"]:
        problems.append("%s: away staff allowed %d but home scored %d" % (tag, ra_away, g["home_r"]))
    if ra_home != g["away_r"]:
        problems.append("%s: home staff allowed %d but away scored %d" % (tag, ra_home, g["away_r"]))

out = dict(
    date="2026-07-25",
    source="user paste, verbatim, preserved at data/mlb/box/2026-07-25_paste.txt",
    parsed_by="harness/parse_box_0725.py (local parse; no model transcription)",
    n_games=len(games),
    games=games,
    checksum_failures=problems,
    so_disputes=so_disputes,
)
json.dump(out, open(OUT, "w"), indent=1)

print("games parsed      :", len(games))
print("starters (1st arm):", sum(1 for g in games for k in ("pitchers_away", "pitchers_home") if g[k]))
print("total pitcher rows:", sum(len(g["pitchers_away"]) + len(g["pitchers_home"]) for g in games))
print("SO 3-way disputes :", len(so_disputes))
for d in so_disputes:
    print("   ~ %s %s: pitcher_lines=%s team_pitching=%s opp_batting=%s -> %s (%s agree, %s dissents)"
          % (d["game"], d["staff"], d["pitcher_lines"], d["team_pitching"], d["opp_batting"],
             d["resolved"], "+".join(d["agree"]), "+".join(d["dissent"])))
print("unresolved        :", len(problems))
for p in problems:
    print("   !!", p)
print()
for g in games:
    print("%-4s %2d @ %2d %-4s   SO %2d/%2d  outs %2d/%2d  (%s @ %s)" % (
        g["away"], g["away_r"], g["home_r"], g["home"],
        g["team_so_away"], g["team_so_home"], g["outs_away"], g["outs_home"],
        g["away_name"], g["home_name"]))
