#!/usr/bin/env python3
"""Deterministic parser for owner-relayed capture files.

WHY THIS EXISTS. On 2026-08-30 the owner uploaded a 4,461-line DK/ESPN capture containing all
14 MLB matchups with game times, named probable starters, starter-vs-current-roster Statcast
tables, team records, and the full DraftKings ML / total / run-line board. The board that came
out of it carried ZERO model forecasts and fifteen CLV_ONLY rows.

The file was read by an LLM skimming it. That is the failure mode: a 4,000-line artifact is
exactly where "I looked at it" and "I extracted it" diverge, and nothing downstream could tell
the difference because nothing downstream had a parsed record to check against. An agent should
not have to remember that SEA@TOR appeared somewhere around line 400. The parser knows.

WHAT IT REFUSES TO DO. It does not infer. The DK block's Open column is genuinely ambiguous --
the favourite's row carries an opening MONEYLINE and the underdog's row carries an opening TOTAL,
distinguished only by which side carries the literal "ML" token. That is parsed by detecting the
token, never by assuming away-or-home. Where a field cannot be read unambiguously it comes back
None with a stated reason (R1), and the game still parses; a missing opening total does not cost
you the starters.
"""
from __future__ import annotations

MODULE_ID = "relay_parser"

import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SEC_MLB_MATCHUPS = "MLB_MATCHUPS"
SEC_MLB_ODDS = "MLB_ODDS"
SEC_NCAAF = "NCAAF"
SEC_UNKNOWN = "UNKNOWN"

#: full club name -> repo abbreviation. Reused from the StatsAPI adapter so the vocabulary
#: cannot fork; the two extra spellings DK uses are added here and nowhere else.
def _team_map():
    from feed_mlb_statsapi import TEAM_ABBR
    m = dict(TEAM_ABBR)
    m.setdefault("Athletics", "ATH")
    m.setdefault("Arizona Diamondbacks", "AZ")
    return m


TEAM = _team_map()
_TEAM_RE = "|".join(sorted((re.escape(k) for k in TEAM), key=len, reverse=True))

RE_MATCHUP_HDR = re.compile(rf"^({_TEAM_RE}) @ ({_TEAM_RE})$")
RE_DATE = re.compile(r"^\w+day, (\w+) (\d+)\w{2} (\d{4})$")
RE_TIME_VENUE = re.compile(r"^(\d{1,2}:\d{2} [AP]M) ET \| (.+)$")
RE_ODDS_TEAM = re.compile(rf"^({_TEAM_RE}) \((\d+)-(\d+), (\d+)-(\d+) (Away|Home)\)$")
RE_ODDS_SP = re.compile(r"^(.+?) \((\d+)-(\d+), (\d+\.\d+)\)$")
RE_PRICE = re.compile(r"^[+-]\d+$")
RE_TOTAL = re.compile(r"^([ou])(\d+(?:\.\d+)?)$")
RE_RL = re.compile(r"^[+-]1\.5$")
RE_THROWS = re.compile(r"^#\d+ Throws: (Right|Left)$")

MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def sections(lines):
    """Label every line. Section boundaries are STRUCTURAL, not guessed from prose."""
    out, cur = [], SEC_UNKNOWN
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("Daily matchups"):
            cur = SEC_MLB_MATCHUPS
        elif s == "MLB Odds":
            cur = SEC_MLB_ODDS
        elif s in ("NCAAF", "NCAAF Odds - Week 1") and cur != SEC_MLB_MATCHUPS:
            cur = SEC_NCAAF
        elif s.startswith("---page break---"):
            cur = SEC_UNKNOWN
        out.append((i + 1, cur, ln.rstrip("\n")))
    return out


# ----------------------------------------------------------------- matchup section

def parse_matchups(labelled):
    """Game header + both starters with handedness and the vs-roster Statcast block."""
    lines = [(n, t) for n, sec, t in labelled if sec == SEC_MLB_MATCHUPS]
    games, i = [], 0
    while i < len(lines):
        n, t = lines[i]
        m = RE_MATCHUP_HDR.match(t.strip())
        if not m:
            i += 1
            continue
        away, home = TEAM[m.group(1)], TEAM[m.group(2)]
        g = {"event": f"{away}@{home}", "away": away, "home": home, "line_no": n,
             "date": None, "start_time_et": None, "venue": None,
             "away_starter": None, "home_starter": None,
             "away_throws": None, "home_throws": None,
             "matchup_evidence": {}}
        j = i + 1
        side = "away"
        while j < len(lines):
            nn, tt = lines[j]
            s = tt.strip()
            if RE_MATCHUP_HDR.match(s):
                break
            d = RE_DATE.match(s)
            if d:
                g["date"] = f"{d.group(3)}-{MONTHS[d.group(1)]:02d}-{int(d.group(2)):02d}"
            tv = RE_TIME_VENUE.match(s)
            if tv:
                g["start_time_et"], g["venue"] = tv.group(1), tv.group(2)
            th = RE_THROWS.match(s)
            if th and j > 0:
                name = lines[j - 1][1].strip()
                if name and not name.startswith(("PA", "Exit", "*", "Career", "Never")):
                    g[f"{side}_starter"] = name
                    g[f"{side}_throws"] = th.group(1)
                    side = "home" if side == "away" else side
            j += 1
        games.append(g)
        i = j
    return games


# ----------------------------------------------------------------- odds section

def _num(tok):
    return int(tok) if RE_PRICE.match(tok) else None


def parse_odds(labelled):
    """The DK board. Ambiguity is detected, never resolved by assumption.

    Layout per game: a team line, a starter line, then 7 value tokens per side. The side that
    carries the literal "ML" token is the FAVOURITE, and the token immediately before it is that
    side's OPENING moneyline; the other side's first two tokens are the opening TOTAL. Which side
    that is varies game to game, so it is detected rather than positional.
    """
    lines = [(n, t.strip()) for n, sec, t in labelled if sec == SEC_MLB_ODDS]
    blocks, cur = [], []
    for n, t in lines:
        if RE_ODDS_TEAM.match(t):
            if len(cur) >= 2 and RE_ODDS_TEAM.match(cur[0][1]):
                blocks.append(cur)
            cur = [(n, t)]
        elif cur:
            cur.append((n, t))
    if cur:
        blocks.append(cur)

    sides = []
    for b in blocks:
        n0, t0 = b[0]
        m = RE_ODDS_TEAM.match(t0)
        sp = None
        vals = []
        for n, t in b[1:]:
            s = RE_ODDS_SP.match(t)
            if s and sp is None:
                sp = {"name": s.group(1), "w": int(s.group(2)), "l": int(s.group(3)),
                      "era": float(s.group(4))}
                continue
            if t in ("ML", "Total", "RL", "Open") or RE_PRICE.match(t) or RE_TOTAL.match(t) \
                    or RE_RL.match(t) or re.match(r"^[+-]?\d+(\.\d+)?$", t):
                vals.append(t)
        sides.append({"line_no": n0, "team": TEAM[m.group(1)],
                      "record": f"{m.group(2)}-{m.group(3)}",
                      "split": f"{m.group(4)}-{m.group(5)}", "side": m.group(6).lower(),
                      "starter": sp, "tokens": vals})

    games, k = [], 0
    while k + 1 < len(sides):
        a, h = sides[k], sides[k + 1]
        if a["side"] != "away" or h["side"] != "home":
            k += 1
            continue
        g = {"event": f"{a['team']}@{h['team']}", "away": a["team"], "home": h["team"],
             "line_no": a["line_no"],
             "away_record": a["record"], "home_record": h["record"],
             "away_starter": (a["starter"] or {}).get("name"),
             "home_starter": (h["starter"] or {}).get("name"),
             "away_starter_line": a["starter"], "home_starter_line": h["starter"],
             "market": {}, "parse_problems": []}
        fav = "away" if "ML" in a["tokens"] else ("home" if "ML" in h["tokens"] else None)
        if fav is None:
            g["parse_problems"].append(
                "NO_ML_TOKEN_ON_EITHER_SIDE — the favourite cannot be identified, so the opening "
                "moneyline and opening total cannot be told apart. Current prices are still read.")
        g["market"] = _market(a["tokens"], h["tokens"], fav, g["parse_problems"])
        g["favourite_side"] = fav
        games.append(g)
        k += 2
    return games


def _market(at, ht, fav, problems):
    def cur_ml(toks, is_fav):
        if is_fav:
            i = toks.index("ML")
            return _num(toks[i + 1]) if i + 1 < len(toks) else None
        # underdog: opening total occupies the first two tokens, current ML is the third
        return _num(toks[2]) if len(toks) > 2 and RE_PRICE.match(toks[2]) else None

    def totals(toks):
        for i, t in enumerate(toks):
            m = RE_TOTAL.match(t)
            if m and i + 1 < len(toks) and RE_PRICE.match(toks[i + 1]):
                yield float(m.group(2)), int(toks[i + 1]), m.group(1)

    def rl(toks):
        for i, t in enumerate(toks):
            if RE_RL.match(t) and i + 1 < len(toks) and RE_PRICE.match(toks[i + 1]):
                return float(t), int(toks[i + 1])
        return None, None

    a_ml = cur_ml(at, fav == "away")
    h_ml = cur_ml(ht, fav == "home")
    a_tot = list(totals(at))
    h_tot = list(totals(ht))
    cur_total = a_tot[-1][0] if a_tot else (h_tot[-1][0] if h_tot else None)
    open_total = None
    if fav == "away" and h_tot:
        open_total = h_tot[0][0]
    elif fav == "home" and a_tot:
        open_total = a_tot[0][0]
    a_rl, a_rl_p = rl(at)
    h_rl, h_rl_p = rl(ht)
    if cur_total is None:
        problems.append("TOTAL_NOT_READABLE")
    return {"away_ml": a_ml, "home_ml": h_ml,
            "total": cur_total, "open_total": open_total,
            "total_moved": (None if (open_total is None or cur_total is None)
                            else round(cur_total - open_total, 1)),
            "away_rl": a_rl, "away_rl_price": a_rl_p,
            "home_rl": h_rl, "home_rl_price": h_rl_p}


# ----------------------------------------------------------------- join

def parse(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
    lab = sections(lines)
    mu = {g["event"]: g for g in parse_matchups(lab)}
    od = {g["event"]: g for g in parse_odds(lab)}
    events = sorted(set(mu) | set(od))
    out = []
    for e in events:
        m, o = mu.get(e, {}), od.get(e, {})
        rec = {"event": e, "date": m.get("date"), "start_time_et": m.get("start_time_et"),
               "venue": m.get("venue"),
               "away": (m or o).get("away"), "home": (m or o).get("home"),
               "away_starter": m.get("away_starter") or o.get("away_starter"),
               "home_starter": m.get("home_starter") or o.get("home_starter"),
               "away_throws": m.get("away_throws"), "home_throws": m.get("home_throws"),
               "away_record": o.get("away_record"), "home_record": o.get("home_record"),
               "away_starter_line": o.get("away_starter_line"),
               "home_starter_line": o.get("home_starter_line"),
               "market": o.get("market"),
               "in_matchup_section": e in mu, "in_odds_section": e in od,
               "parse_problems": o.get("parse_problems", []),
               "source": "OWNER_RELAY"}
        # a starter named in one section and not the other is a CONFLICT to surface, not to fix
        if e in mu and e in od:
            for s in ("away", "home"):
                a, b = m.get(f"{s}_starter"), o.get(f"{s}_starter")
                if a and b and a != b:
                    rec["parse_problems"].append(
                        f"STARTER_DISAGREES_BETWEEN_SECTIONS:{s} matchup={a!r} odds={b!r}")
        out.append(rec)
    return {"schema": "ops.relay_parse.v1", "source_path": path,
            "source_sha256": sha256_file(path), "n_lines": len(lines),
            "sections": sorted({sec for _, sec, _ in lab}),
            "n_events": len(out), "events": out}


def selftest():
    """Hermetic parser test. Never depend on a session upload path to prove parser health."""
    import tempfile
    f = []
    text = "\n".join([
        "Daily matchups",
        "Seattle Mariners @ Toronto Blue Jays",
        "Sunday, August 30th 2026",
        "1:05 PM ET | Rogers Centre",
        "Logan Gilbert",
        "#36 Throws: Right",
        "Max Scherzer",
        "#31 Throws: Right",
        "Boston Red Sox @ New York Yankees",
        "Sunday, August 30th 2026",
        "7:05 PM ET | Yankee Stadium",
        "Brayan Bello",
        "#66 Throws: Right",
        "Gerrit Cole",
        "#45 Throws: Right",
        "MLB Odds",
        "Seattle Mariners (80-50, 40-30 Away)",
        "Logan Gilbert (10-4, 3.20)",
        "ML", "-135", "Total", "o8", "-110", "RL", "-1.5", "+125",
        "Toronto Blue Jays (70-60, 35-30 Home)",
        "Max Scherzer (8-5, 3.50)",
        "o8.5", "-105", "+120", "Total", "u8", "-110", "RL", "+1.5", "-145",
        "Boston Red Sox (70-60, 35-30 Away)",
        "Brayan Bello (8-7, 4.20)",
        "o8.5", "-110", "+120", "Total", "o8", "-110", "RL", "+1.5", "-150",
        "New York Yankees (85-45, 45-20 Home)",
        "Gerrit Cole (12-4, 2.90)",
        "ML", "-140", "Total", "u8", "-110", "RL", "-1.5", "+130",
        "",
    ])
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        fh.write(text)
        up = fh.name
    try:
        r = parse(up)
    finally:
        os.unlink(up)
    ev = {e["event"]: e for e in r["events"]}
    if r["n_events"] != 2:
        f.append(f"expected 2 synthetic MLB events, parsed {r['n_events']}")
    for want in ("SEA@TOR", "BOS@NYY"):
        if want not in ev:
            f.append(f"{want} not parsed")
    sea = ev.get("SEA@TOR", {})
    if sea.get("date") != "2026-08-30" or sea.get("venue") != "Rogers Centre":
        f.append(f"SEA@TOR date/venue wrong: {sea.get('date')} / {sea.get('venue')}")
    if sea.get("away_starter") != "Logan Gilbert" or sea.get("home_starter") != "Max Scherzer":
        f.append(f"SEA@TOR starters wrong: {sea.get('away_starter')} / {sea.get('home_starter')}")
    sm = sea.get("market") or {}
    if sm.get("away_ml") != -135 or sm.get("home_ml") != 120:
        f.append(f"SEA@TOR ML wrong: {sm.get('away_ml')} / {sm.get('home_ml')}")
    if sm.get("total") != 8.0 or sm.get("open_total") != 8.5 or sm.get("total_moved") != -0.5:
        f.append(f"SEA@TOR total wrong: {sm}")
    bos = ev.get("BOS@NYY", {})
    bm = bos.get("market") or {}
    if bm.get("total") != 8.0 or bm.get("open_total") != 8.5 or bm.get("total_moved") != -0.5:
        f.append(f"BOS@NYY total move wrong: {bm}")
    if any(e.get("parse_problems") for e in r["events"]):
        f.append(f"synthetic clean fixture produced parse problems: {[e.get('parse_problems') for e in r['events']]}")
    for x in f:
        print("  FAIL:", x)
    print(f"relay_parser selftest: {'OK' if not f else 'FAIL'}")
    return not f


if __name__ == "__main__":
    if "--parse" in sys.argv:
        print(json.dumps(parse(sys.argv[sys.argv.index("--parse") + 1]), indent=1))
        sys.exit(0)
    sys.exit(0 if selftest() else 1)
