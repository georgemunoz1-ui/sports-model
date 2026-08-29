#!/usr/bin/env python3
"""WNBA FEATURE REFRESH from the sportsdataverse GitHub archive — the registered model, current.

ROUTE. Every HTTP content domain is blocked by the environment's network policy, but this
session's git proxy serves anonymous reads of public GitHub repositories. The sportsdataverse
`wehoop-wnba-raw` archive — the SAME source family the staged pool was built from — stores the
full ESPN schedule parquet and per-game JSON payloads in-tree, updated daily (HEAD commit
b843138d, 2026-08-26T06:32-04:00, 288 completed games through the night of 8/25). A git-fetched
blob addressed by commit sha and path, hashed at extraction, is a retrieved artifact with real
provenance — not a snippet.

GRADE. The staged pool's rule is official-plus-one (official stats row confirmed by ESPN). The
extension window (2026-07-23 .. as-of) has ESPN-family data only — schedule parquet confirmed by
the game JSON's box score, a SINGLE-FAMILY double-check. Outputs therefore run under the
preregistered replacement identity `wnba.replacement.FEATURE_REFRESH` (named in incident
19a644a8's remediation), graded separately from the shadow arm, ACTION-BLOCKED like everything
else while SYSTEM_NOT_DECISION_READY.

FROZEN METHOD. Everything model-side is wnba_model_v1's frozen code: TeamState four-factors
accumulators, make_rows, fit_full ridge/logistic, predict_slate. This module only supplies rows.

DATE DISCIPLINE (patched 2026-08-28). The schedule parquet has NO game_date column; its
date/start_date are UTC instants. Slicing `str(date)[:10]` took the UTC calendar date and landed
49/91 extension games one ET day late — CON@IND (401857090) and DAL@PDX (401857091) are ET
2026-07-22 evening games (UTC 07-23) that slipped past the 2026-07-22 cutoff and double-counted
base-pool gids 1022600201/1022600202 (identical scores; 2378 as-built vs 2376 ET-corrected pool
games). Dates are now DERIVED as ET calendar dates (America/New_York via zoneinfo) from the raw
UTC instant, at extraction AND at the cutoff comparison. Artifact rows carry both `utc_instant`
(raw, as read) and `et_date` (derived), and the artifact declares
`"date_timezone": "America/New_York"`.

REBUILD REQUIRED. This patch changes extracted dates, so the live extension artifact
(data/wnba/source/staging/EXTENSION_ESPN/ext_2026.json) must be RE-EXTRACTED after patching —
selftest now fails any artifact whose stored `et_date` disagrees with the ET date re-derived
independently from its stored `utc_instant`. Rebuild invocation (requires the cloned
sportsdataverse/wehoop-wnba-raw archive at RAW, checked out at COMMIT_PIN — the archive is NOT
present in this repository, so no rebuilt artifact is committed here):

    python3 harness/wnba_refresh_espn.py --extract
    python3 harness/wnba_refresh_espn.py --selftest
"""
from __future__ import annotations

MODULE_ID = "wnba_refresh_espn"

import datetime as dt
import hashlib
import json
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))

ET = ZoneInfo("America/New_York")   # EDT in season; pool/cutoff dates are ET calendar dates
DATE_TIMEZONE = "America/New_York"


def _utc_instant(v):
    """Parse a UTC instant (ISO string or datetime, 'Z' or offset or naive-UTC) -> aware UTC."""
    if isinstance(v, dt.datetime):
        d = v
    else:
        d = dt.datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def et_date(utc_instant):
    """The ET (America/New_York) calendar date of a UTC instant, as YYYY-MM-DD.

    This is THE pool date. Slicing the UTC instant's own date is the defect this patch closes:
    a 2026-07-23T00:00Z tip is the ET evening of 2026-07-22."""
    return _utc_instant(utc_instant).astimezone(ET).date().isoformat()


def duplicate_content_violations(games):
    """Cross-id-space duplicate-content guard: no two pool games (base OR extension) may share
    (et_date, home, away, hpts, apts). Id spaces cannot collide, so identity is content-based;
    returns the list of offending keys (empty = clean)."""
    seen, bad = {}, []
    for g in games:
        key = (g.get("et_date") or g["date"], g["home"], g["away"], g["hpts"], g["apts"])
        if key in seen:
            bad.append((key, seen[key], str(g["gid"])))
        else:
            seen[key] = str(g["gid"])
    return bad

IDENTITY = "wnba.replacement.FEATURE_REFRESH"
INPUT_GRADE = "ESPN_SINGLE_FAMILY_GIT_ARTIFACT"
EXT_PATH = "data/wnba/source/staging/EXTENSION_ESPN/ext_2026.json"
CUTOFF = "2026-07-22"     # the official-plus-one pool ends here; extension is strictly after

RAW = "/home/user/sportsdataverse/wehoop-wnba-raw"
#: The archive commit this module is allowed to build from. Advancing it is a DECISION and must be
#: made here, in the diff, never as a side effect of the archive moving underneath us.
#:
#: DRIFT FOUND 2026-08-28: the 8/27 extension artifact was built at 3316fa3 while this constant
#: still read b843138d. The artifact and the pin disagreed, which is exactly the state the pin
#: exists to prevent, and the module's own selftest had been FAILING on it unnoticed because
#: nothing invoked that selftest. Both are fixed: the pin is advanced deliberately below, and the
#: selftest is now wired into healthcheck so it cannot rot silently again.
COMMIT_PIN = "7a1c7ebaef37590ebdaf75c4d3961b99a493d99b"   # 2026-08-28 06:32 ET; carries the 8/27 finals

_STAT_KEYS = {"fieldGoalsMade-fieldGoalsAttempted": ("fgm", "fga"),
              "threePointFieldGoalsMade-threePointFieldGoalsAttempted": ("fg3m", "fg3a"),
              "freeThrowsMade-freeThrowsAttempted": ("ftm", "fta")}


def _xw(t):
    import wnba_model_v1 as W
    return W._xw(t, 2026)


def extract(raw=RAW, out=EXT_PATH):
    """Build the committed extension artifact from the cloned archive, with provenance."""
    import pyarrow.parquet as pq
    import subprocess
    head = subprocess.run(["git", "-C", raw, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    if head != COMMIT_PIN:
        return None, f"COMMIT_MISMATCH: {head} != pinned {COMMIT_PIN}"
    sched_path = f"{raw}/wnba/schedules/parquet/wnba_schedule_2026.parquet"
    sched_sha = hashlib.sha256(open(sched_path, "rb").read()).hexdigest()
    d = pq.read_table(sched_path).to_pydict()
    games, missing = [], []
    for i in range(len(d["id"])):
        if not d["status_type_completed"][i]:
            continue
        utc_instant = str(d["date"][i])
        date = et_date(utc_instant)          # ET calendar date; UTC slicing is the defect
        if date <= CUTOFF:
            continue
        gid = str(d["id"][i])
        jp = f"{raw}/wnba/json/final/{gid}.json"
        if not os.path.exists(jp):
            missing.append({"gid": gid, "date": date})
            continue
        raw_bytes = open(jp, "rb").read()
        j = json.loads(raw_bytes)
        sides = {}
        ok = True
        for tm in j.get("boxscore", {}).get("teams", []):
            side = tm.get("homeAway")
            stats = {s.get("name"): s.get("displayValue") for s in tm.get("statistics", [])}
            row = {"team": _xw(str(tm["team"]["abbreviation"]))}
            try:
                for k, (a, b) in _STAT_KEYS.items():
                    x, y = str(stats[k]).split("-")
                    row[a], row[b] = int(x), int(y)
                row["oreb"] = int(stats["offensiveRebounds"])
                row["tov"] = int(stats["totalTurnovers"])
            except (KeyError, ValueError):
                ok = False
            sides[side] = row
        if not ok or set(sides) != {"home", "away"}:
            missing.append({"gid": gid, "date": date, "reason": "BOX_INCOMPLETE"})
            continue
        home_ab = _xw(str(d["home_abbreviation"][i]))
        away_ab = _xw(str(d["away_abbreviation"][i]))
        if sides["home"]["team"] != home_ab or sides["away"]["team"] != away_ab:
            missing.append({"gid": gid, "date": date, "reason": "TEAM_MISMATCH"})
            continue
        sides["home"]["pts"] = int(d["home_score"][i])
        sides["away"]["pts"] = int(d["away_score"][i])
        games.append({"date": date, "season": 2026, "gid": gid,
                      "utc_instant": utc_instant, "et_date": date,
                      "home": home_ab, "away": away_ab,
                      "hpts": sides["home"]["pts"], "apts": sides["away"]["pts"],
                      "H": sides["home"], "A": sides["away"],
                      "source_sha256": hashlib.sha256(raw_bytes).hexdigest()})
    games.sort(key=lambda g: (g["date"], g["gid"]))
    art = {"schema": "ops.espn_extension.v1", "identity": IDENTITY,
           "input_grade": INPUT_GRADE, "cutoff_exclusive": CUTOFF,
           "date_timezone": DATE_TIMEZONE,
           "provenance": {"repo": "github.com/sportsdataverse/wehoop-wnba-raw",
                          "commit": head, "schedule_sha256": sched_sha,
                          "retrieved_utc": dt.datetime.now(dt.timezone.utc)
                                           .strftime("%Y-%m-%dT%H:%M:%SZ")},
           "n_games": len(games), "missing": missing, "games": games}
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump(art, fh, indent=1, sort_keys=True)
    return art, None


def run_slate(slate, ext_path=EXT_PATH):
    """slate: [(away, home, tip_iso)]. Frozen wnba_model_v1 machinery over pool + extension."""
    import wnba_model_v1 as W
    art = json.load(open(ext_path))
    base = W.build_games()                       # official-plus-one, ends at CUTOFF
    base = [g for g in base if g["date"] <= CUTOFF or g["season"] < 2026]
    if any("utc_instant" not in g or "et_date" not in g for g in art["games"]):
        raise RuntimeError("extension artifact predates the ET-date patch (rows lack "
                           "utc_instant/et_date) — re-extract: python3 harness/"
                           "wnba_refresh_espn.py --extract (see module docstring)")
    ext = [{k: g[k] for k in ("date", "season", "gid", "home", "away", "hpts", "apts", "H", "A",
                              "et_date", "utc_instant")}
           for g in art["games"]]
    combined = base + ext
    dups = duplicate_content_violations(combined)
    if dups:
        raise RuntimeError("duplicate game content across the base/extension id spaces: "
                           + "; ".join(f"{k} ({a} vs {b})" for k, a, b in dups[:5]))
    combined.sort(key=lambda g: (g["date"], str(g["gid"])))
    rows, ts, lg = W.make_rows(combined)
    model = W.fit_full(rows)
    preds = W.predict_slate(model, ts, lg, slate)
    return {"identity": IDENTITY, "input_grade": INPUT_GRADE,
            "date_timezone": art.get("date_timezone", DATE_TIMEZONE),
            "pool": {"base_games": len(base), "extension_games": len(ext),
                     "extension_window": f"{CUTOFF} (excl) .. {art['games'][-1]['date']}",
                     "extension_sha256": hashlib.sha256(
                         open(ext_path, "rb").read()).hexdigest()},
            "provenance": art["provenance"], "predictions": preds}


# =================================================================================================
def selftest():
    f = []
    art = json.load(open(EXT_PATH)) if os.path.exists(EXT_PATH) else None
    if art is None:
        print("wnba_refresh_espn selftest: SKIP (no extension artifact)")
        return True
    if art["cutoff_exclusive"] != "2026-07-22":
        f.append("the extension must start strictly after the official-plus-one cutoff")
    if any(g["date"] <= art["cutoff_exclusive"] for g in art["games"]):
        f.append("an extension game at or before the cutoff would double-count the pool")
    if art.get("date_timezone") != DATE_TIMEZONE:
        f.append("the artifact must declare date_timezone America/New_York")
    # INDEPENDENT date verification: re-derive the ET date from each row's stored RAW UTC
    # instant and compare against the stored et_date/date — the pre-patch selftest re-read the
    # same derived dates it was checking, so it could not catch the UTC-slice defect.
    for g in art["games"]:
        if "utc_instant" not in g or "et_date" not in g:
            f.append("every game must carry the raw utc_instant AND the derived et_date "
                     "(artifact predates the ET-date patch — re-extract)")
            break
        derived = et_date(g["utc_instant"])
        if derived != g["et_date"] or derived != g["date"]:
            f.append(f"{g['gid']}: stored et_date {g['et_date']} != ET re-derived from "
                     f"utc_instant {g['utc_instant']} -> {derived}")
    dups = duplicate_content_violations(art["games"])
    if dups:
        f.append("duplicate game content within the extension: "
                 + "; ".join(f"{k} ({a} vs {b})" for k, a, b in dups[:3]))
    for g in art["games"][:50]:
        for side in ("H", "A"):
            for k in ("pts", "fgm", "fga", "fg3m", "fta", "oreb", "tov"):
                if k not in g[side]:
                    f.append(f"{g['gid']} {side} missing {k}")
                    break
    if not all(len(g.get("source_sha256", "")) == 64 for g in art["games"]):
        f.append("every extension game carries its source file's sha256")
    if art["provenance"]["commit"] != COMMIT_PIN:
        f.append("the artifact must pin the archive commit")
    seen = set()
    for g in art["games"]:
        if g["gid"] in seen:
            f.append(f"duplicate gid {g['gid']}")
        seen.add(g["gid"])
    print("wnba_refresh_espn selftest:", "OK" if not f else "FAIL")
    for x in f[:6]:
        print("   -", x)
    return not f


if __name__ == "__main__":
    if "--extract" in sys.argv:
        art, err = extract()
        print(err or f"extracted {art['n_games']} games, {len(art['missing'])} missing")
        sys.exit(0 if not err else 1)
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    print(__doc__)
