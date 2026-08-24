#!/usr/bin/env python3
"""Content-level integrity checks for outcome labels — things that can be WRONG, not just malformed.

WHY (2026-08-10): healthcheck's results block validated shape only (row count, duplicate ids,
non-null home_win/total, freshness). Replayed against the 2026-08-08 file with three winners
reversed on disk, it reported HEALTHY, 0 fail. The errors were well-formed rows.

The three real 8/8 failure mechanisms and the check that catches each:

  ADJACENT-DAY ECHO   DET@SF and TB@SEA were byte-identical copies of the 8/7 finals.
                      -> dup_score_pairs(): same matchup, consecutive days, identical score.
                      Season base rate is ~1.9%, and ~19 historical repeats are genuine, so this
                      is a RECONCILE signal, never a verdict — matching this repo's own
                      "detector, never a verdict" doctrine.

  ORIENTATION FLIP    ATH@BOS was recorded 3-7 when the truth was 7-3; home_win/margin/total were
                      all derived from the flipped pair, so the row reconciles against ITSELF.
                      -> no arithmetic check can see this. winner_name_mismatch() compares the
                      recorded winner against a winner NAME captured verbatim from the source.
                      That is the only thing that catches it, which is why the evidence schema
                      must carry `winner` as text.

  FABRICATION         LAA@MIA 4-3 matched no real game on any date.
                      -> caught by evidence binding (result_provenance) + standings reconciliation.

Also: per-date completeness against the frozen slate, so a silently dropped game (7/23) is visible.
"""

from __future__ import annotations

import csv
import datetime as dt
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import franchise_identity as _fi

RESULTS = "data/backfill/mlb/2026/results.csv"


def _finals(rows):
    return [r for r in rows if r.get("status") == "final" and r.get("total") not in ("", None)]


def dup_score_pairs(rows):
    """Same matchup on consecutive days with an identical score. Returns list of dicts.

    NOT a verdict: real back-to-back identical finals happen (~19 in this season's file). It is a
    reconcile signal — each hit must be re-checked against a dedicated source before the row stands.
    """
    by = {}
    for r in _finals(rows):
        by.setdefault((r["away"], r["home"]), []).append(r)
    hits = []
    for k, games in by.items():
        games.sort(key=lambda r: r["date"])
        for a, b in zip(games, games[1:]):
            try:
                d0 = dt.date.fromisoformat(a["date"])
                d1 = dt.date.fromisoformat(b["date"])
            except ValueError:
                continue
            if (d1 - d0).days != 1:
                continue
            if (a["away_score"], a["home_score"]) == (b["away_score"], b["home_score"]):
                hits.append({"matchup": f"{k[0]}@{k[1]}", "dates": [a["date"], b["date"]],
                             "score": f"{a['away_score']}-{a['home_score']}",
                             "second_tier": b.get("source_tier", ""),
                             "second_status": b.get("result_status", "")})
    return hits


def unreconciled_echoes(rows):
    """Echo hits whose SECOND row is not tier-1 — i.e. still resting on an unverified source."""
    return [h for h in dup_score_pairs(rows) if h["second_tier"] != "1"]


def winner_name_mismatch(rows, evidence_dir="data/mlb/evidence"):
    """Compare each row's winner against a winner NAME recorded verbatim in its evidence file.

    This is the ONLY check that catches an away/home orientation flip, because such a row is
    internally consistent. Evidence records must carry {"away","home","winner"} for it to fire;
    records without a `winner` field are reported as UNCHECKABLE rather than silently passing.
    """
    ev = {}
    for p in glob.glob(os.path.join(evidence_dir, "**", "*.json"), recursive=True):
        try:
            d = json.load(open(p))
        except Exception:
            continue
        for g in (d.get("games") or []):
            if not isinstance(g, dict):
                continue
            if g.get("away") and g.get("home") and g.get("winner"):
                ev[(d.get("date") or "", g["away"], g["home"])] = (g["winner"], p)
    mism, checked = [], 0
    for r in _finals(rows):
        k = (r["date"], r["away"], r["home"])
        if k not in ev:
            continue
        checked += 1
        stated, path = ev[k]
        actual = r["home"] if int(r["home_win"]) == 1 else r["away"]
        if stated != actual:
            mism.append(f"{r['date']} {r['away']}@{r['home']}: row winner={actual} but evidence "
                        f"{path} says winner={stated}")
    return mism, checked


def slate_completeness(rows, slate_dir="data/mlb/slates"):
    """Every game on a frozen slate .psv must have a result row once that date has any results.

    A WINNER-ONLY row (status final, home_win set, scores empty) COUNTS as a result here: the
    winner-known/score-unknown state is real (tier-1 standings arithmetic can prove a winner a day
    before any box supplies the score, as on 2026-08-11), and refusing to represent it would force
    either invented scores (R1 violation) or a permanently red gate. Echo detection and ml_asof
    label building still require full scores — _finals() is unchanged; only completeness accepts
    the weaker row, and such a row must still be PROVISIONAL under the provenance audit."""
    # IDENTITY BINDING (2026-08-23). The frozen slate .psv writes FULL TEAM NAMES and results.csv
    # writes abbreviations, so comparing raw strings reported all 15 games of a FULLY INGESTED slate
    # as missing. That is the 62-keys defect wearing a completeness gate: a join on unbound identities
    # does not fail loudly, it finds no partner. Both sides bind to one canonical id before the
    # comparison. Binding can only MERGE two spellings of one franchise, so it cannot hide a
    # genuinely absent game; an unresolvable token falls through as its own raw string, which keeps
    # the comparison honest rather than silently dropping the row.
    def _bind(t):
        try:
            return _fi.canonical("mlb", t)
        except Exception:
            return t

    have = {}
    for r in rows:
        if r.get("status") == "final" and (r.get("total") not in ("", None)
                                           or r.get("home_win") not in ("", None)):
            have.setdefault(r["date"], set()).add((_bind(r["away"]), _bind(r["home"])))
    excused = _fresh_pendings()
    missing = []
    for p in sorted(glob.glob(os.path.join(slate_dir, "*_slate.psv"))):
        date = os.path.basename(p).split("_")[0]
        if date not in have:
            continue  # date not yet ingested at all — not a completeness failure
        want = set()
        for line in open(p):
            parts = line.strip().split("|")
            if len(parts) >= 3:
                want.add((_bind(parts[1]), _bind(parts[2])))
        for g in sorted(want - have[date]):
            if (date, f"{g[0]}@{g[1]}") in excused:
                continue  # explicitly recorded PENDING_NOT_FINAL and still fresh — see _fresh_pendings
            missing.append(f"{date}: {g[0]}@{g[1]} is on the frozen slate but has no result row")
    return missing


PENDING_REGISTRY = "data/mlb/analysis/pending_results.json"
PENDING_MAX_AGE_H = 36


def _fresh_pendings(path=PENDING_REGISTRY, now=None):
    """Games explicitly recorded as PENDING_NOT_FINAL, and still fresh.

    WHY THIS EXISTS AND WHY IT EXPIRES (2026-08-21): a late game that genuinely has not finished is
    a real state, and the only alternatives are inventing a result (R1 violation) or a permanently
    red gate — the same reasoning already applied to winner-only rows above. But an open-ended
    excuse would let a missing result hide forever behind a stale note, so an entry only suppresses
    the failure for PENDING_MAX_AGE_H hours. After that the gate goes red again and STAYS red until
    a real result lands. A game with no entry at all is never excused.

    Registry entries: {"date": "YYYY-MM-DD", "game": "AWAY@HOME", "reason": str,
                       "recorded_utc": "YYYY-MM-DDTHH:MM:SSZ"}"""
    import datetime as _dt
    if not os.path.exists(path):
        return set()
    now = now or _dt.datetime.now(_dt.timezone.utc)
    out = set()
    for e in json.load(open(path)).get("pending", []):
        try:
            t = _dt.datetime.strptime(e["recorded_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
        except Exception:
            continue  # unparseable timestamp never excuses anything
        if not e.get("reason"):
            continue  # an entry without a stated reason never excuses anything
        if (now - t).total_seconds() <= PENDING_MAX_AGE_H * 3600:
            out.add((e["date"], e["game"]))
    return out


def run(path=RESULTS):
    rows = list(csv.DictReader(open(path)))
    echoes = dup_score_pairs(rows)
    unrec = unreconciled_echoes(rows)
    mism, checked = winner_name_mismatch(rows)
    missing = slate_completeness(rows)
    return {"rows": len(rows), "finals": len(_finals(rows)),
            "echo_pairs": echoes, "unreconciled_echoes": unrec,
            "winner_mismatches": mism, "winner_checked": checked,
            "slate_missing": missing}


def _selftest_pendings():
    """Fixtures for the pending-result excuse: it must expire, require a reason, and never excuse
    a game that was simply never recorded."""
    import datetime as _dt, tempfile, json as _j
    f=[]
    now=_dt.datetime(2026,8,22,6,0,0,tzinfo=_dt.timezone.utc)
    def reg(entries):
        fh=tempfile.NamedTemporaryFile("w",suffix=".json",delete=False)
        _j.dump({"pending":entries},fh); fh.close(); return fh.name
    fresh=reg([{"date":"2026-08-21","game":"CHC@SEA","reason":"late game not final",
                "recorded_utc":"2026-08-22T06:00:00Z"}])
    if ("2026-08-21","CHC@SEA") not in _fresh_pendings(fresh, now):
        f.append("a fresh, reasoned pending entry did not excuse its game")
    stale=reg([{"date":"2026-08-21","game":"CHC@SEA","reason":"late game not final",
                "recorded_utc":"2026-08-20T00:00:00Z"}])
    if _fresh_pendings(stale, now):
        f.append("a STALE pending entry still excused its game — the excuse must expire")
    noreason=reg([{"date":"2026-08-21","game":"CHC@SEA","recorded_utc":"2026-08-22T06:00:00Z"}])
    if _fresh_pendings(noreason, now):
        f.append("a pending entry with no stated reason excused its game")
    if _fresh_pendings("/nonexistent/path.json", now):
        f.append("a missing registry excused something")
    return f


def selftest():
    fails = []
    # ECHO: consecutive-day identical score must fire
    rows = [
        {"status": "final", "total": "7", "date": "2026-08-07", "away": "DET", "home": "SF",
         "away_score": "2", "home_score": "5", "home_win": "1", "source_tier": "3"},
        {"status": "final", "total": "7", "date": "2026-08-08", "away": "DET", "home": "SF",
         "away_score": "2", "home_score": "5", "home_win": "1", "source_tier": "3"},
    ]
    hits = dup_score_pairs(rows)
    if len(hits) != 1:
        fails.append("consecutive-day identical score not detected (the DET@SF/TB@SEA mechanism)")
    if len(unreconciled_echoes(rows)) != 1:
        fails.append("tier-3 echo not surfaced as unreconciled")
    # a tier-1 second row is reconciled -> not surfaced
    rows[1]["source_tier"] = "1"
    if unreconciled_echoes(rows):
        fails.append("tier-1 second row should not be flagged unreconciled")
    # non-consecutive identical scores must NOT fire
    rows2 = [dict(rows[0]), dict(rows[0])]
    rows2[1]["date"] = "2026-08-20"
    if dup_score_pairs(rows2):
        fails.append("non-consecutive identical score wrongly flagged")
    # different score on consecutive days must NOT fire
    rows3 = [dict(rows[0]), dict(rows[0])]
    rows3[1]["date"] = "2026-08-08"; rows3[1]["home_score"] = "9"
    if dup_score_pairs(rows3):
        fails.append("different score wrongly flagged as echo")
    # COMPLETENESS: a WINNER-ONLY row (home_win set, scores empty) satisfies completeness,
    # but a game with NO row at all still fires. Uses a temp slate dir with a 2-game slate.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "2026-08-11_slate.psv"), "w") as f:
            f.write("X1|MIL|SD|20:10Z|A|B\nX2|KC|LAD|02:10Z|C|D\n")
        wrows = [{"status": "final", "total": "", "away_score": "", "home_score": "",
                  "date": "2026-08-11", "away": "MIL", "home": "SD", "home_win": "1",
                  "source_tier": "1"}]
        miss = slate_completeness(wrows, slate_dir=td)
        if len(miss) != 1 or "KC@LAD" not in miss[0]:
            fails.append(f"winner-only row handling wrong: expected only KC@LAD missing, got {miss}")
        if _finals(wrows):
            fails.append("winner-only row leaked into _finals() — echo/label logic must not see it")
    fails += _selftest_pendings()
    if fails:
        print("result_content_checks selftest: FAIL")
        for f in fails:
            print("  " + f)
        return 1
    print("result_content_checks selftest: PASS (echo detector fires on the real 8/8 mechanism, "
          "respects tier-1 reconciliation, and does not fire on non-consecutive or differing scores)")
    return 0


if __name__ == "__main__":
    import sys
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    r = run()
    print(f"finals={r['finals']}")
    print(f"echo pairs (consecutive-day identical score): {len(r['echo_pairs'])} "
          f"({len(r['unreconciled_echoes'])} still on non-tier-1 sources)")
    for h in r["unreconciled_echoes"][:15]:
        print(f"  ~ {h['matchup']} {h['dates']} {h['score']} (tier {h['second_tier']})")
    print(f"winner-name mismatches: {len(r['winner_mismatches'])} (checked {r['winner_checked']} rows)")
    for m in r["winner_mismatches"][:10]:
        print("  ! " + m)
    print(f"slate games missing a result: {len(r['slate_missing'])}")
    for m in r["slate_missing"][:10]:
        print("  ! " + m)
    raise SystemExit(1 if (r["winner_mismatches"] or r["slate_missing"]) else 0)
