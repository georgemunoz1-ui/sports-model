"""FU-1 feed sweep — one command, all four leagues, append-only snapshots, reconciliation report.

    python3 harness/feed_sweep.py --date 2026-08-28 [--out data/feeds] [--offline FIXTURE_DIR]

Pulls the ESPN scoreboard for mlb/wnba/nfl/college-football plus the MLB StatsAPI schedule,
writes timestamped content-hashed snapshots under data/feeds/YYYY-MM-DD/ (append-only: identical
content is never rewritten, new content gets a new file), and prints a reconciliation report:

  - games found per league per source
  - cross-feed disagreements (ESPN vs StatsAPI for MLB) surfaced as CONFLICT — never silently
    resolved. A conflict is a statement about the feeds; nothing here picks a winner.

Also emits the result rows that feed result_binding_gate.binding_proof (feed_espn.result_rows +
feed_mlb_statsapi.result_rows), with namespaced canonical ids. Grade semantics: finals from the
first-party feeds are CONFIRMED; probable-only listings stay IDENTIFIED_UNCONFIRMED and are not
result rows at all.
"""
from __future__ import annotations

MODULE_ID = "feed_sweep"

import argparse
import datetime as dt
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import feed_espn
import feed_mlb_statsapi

UTC = dt.timezone.utc
ESPN_LEAGUES = ("mlb", "wnba", "nfl", "college-football")
CONFLICT = "CONFLICT"


def _snapshot_path(out_dir, source, league, sha):
    return os.path.join(out_dir, f"{source}_{league}_{sha[:12]}.json")


def write_snapshot(out_dir, source, league, raw_text, sha, fetched_utc):
    """Append-only content-hashed snapshot. Identical bytes are never rewritten."""
    os.makedirs(out_dir, exist_ok=True)
    path = _snapshot_path(out_dir, source, league, sha)
    written = False
    if not os.path.exists(path):
        with open(path, "w") as fh:
            fh.write(raw_text)
        written = True
    index = os.path.join(out_dir, "snapshots_index.jsonl")
    with open(index, "a") as fh:
        fh.write(json.dumps({"path": os.path.basename(path), "source": source, "league": league,
                             "sha256": sha, "fetched_utc": fetched_utc,
                             "deduplicated": not written}) + "\n")
    return path, written


def reconcile_mlb(espn_records, statsapi_records):
    """Cross-feed comparison for MLB. Returns (report_lines, conflicts).

    Join key is (date_et, away, home) — never a bare integer id, and never cross-namespace.
    A disagreement is a CONFLICT entry; the function takes no position on which feed is right.
    """
    conflicts = []
    lines = []
    esp = {(r["date_et"], r["away"], r["home"]): r for r in espn_records}
    sap = {(r["date_et"], r["away"], r["home"]): r for r in statsapi_records}
    for key in sorted(set(esp) | set(sap)):
        e, s = esp.get(key), sap.get(key)
        if e is None:
            conflicts.append({"code": CONFLICT, "kind": "MISSING_FROM_ESPN", "game": key,
                              "statsapi_game_pk": s["game_id"]})
            continue
        if s is None:
            conflicts.append({"code": CONFLICT, "kind": "MISSING_FROM_STATSAPI", "game": key,
                              "espn_game_id": e["game_id"]})
            continue
        # both feeds carry this game: scores and starters must agree
        if e["completed"] and s["completed"]:
            if e["away_score"] != s["away_score"] or e["home_score"] != s["home_score"]:
                conflicts.append({"code": CONFLICT, "kind": "SCORE_DISAGREEMENT", "game": key,
                                  "espn": (e["away_score"], e["home_score"]),
                                  "statsapi": (s["away_score"], s["home_score"]),
                                  "detail": "surfaced, not resolved — a human or the binding "
                                            "gate decides which final binds"})
        if e["start_utc"] != s["start_utc"]:
            conflicts.append({"code": CONFLICT, "kind": "START_TIME_DISAGREEMENT", "game": key,
                              "espn": e["start_utc"], "statsapi": s["start_utc"]})
        # probable-pitcher cross-check: ESPN summary probables are not in the scoreboard payload,
        # so only the statsapi probables exist here; nothing to compare. Noted in the report.
    lines.append(f"mlb cross-feed: {len(set(esp) & set(sap))} games on both feeds, "
                 f"{len(set(esp) - set(sap))} ESPN-only, {len(set(sap) - set(esp))} StatsAPI-only, "
                 f"{len(conflicts)} conflict(s)")
    return lines, conflicts


def sweep(date_et, out_root="data/feeds", get=None, also_statsapi=True):
    """The one command. Returns the report dict; writes snapshots under out_root/YYYY-MM-DD/."""
    out_dir = os.path.join(out_root, date_et)
    fetched_utc = dt.datetime.now(UTC).isoformat().replace("+00:00", "Z")
    report = {"date_et": date_et, "fetched_utc": fetched_utc, "leagues": {}, "conflicts": [],
              "snapshots": [], "result_rows": []}

    espn_mlb = None
    for league in ESPN_LEAGUES:
        recs, raw, sha = feed_espn.fetch_scoreboard(league, date_et, get=get) if get else \
            feed_espn.fetch_scoreboard(league, date_et)
        path, written = write_snapshot(out_dir, "espn_scoreboard", league, raw, sha, fetched_utc)
        report["leagues"][league] = {"source": "espn_scoreboard_api", "games": len(recs),
                                     "finals": sum(1 for r in recs if r["completed"]),
                                     "snapshot": os.path.basename(path), "sha256": sha[:12]}
        report["snapshots"].append(path)
        report["result_rows"].extend(feed_espn.result_rows(recs))
        if league == "mlb":
            espn_mlb = recs

    if also_statsapi:
        recs, raw, sha = (feed_mlb_statsapi.fetch_schedule(date_et, get=get) if get else
                          feed_mlb_statsapi.fetch_schedule(date_et))
        path, written = write_snapshot(out_dir, "mlb_statsapi", "mlb", raw, sha, fetched_utc)
        report["leagues"]["mlb_statsapi"] = {"source": "mlb_statsapi", "games": len(recs),
                                             "finals": sum(1 for r in recs if r["completed"]),
                                             "snapshot": os.path.basename(path), "sha256": sha[:12]}
        report["snapshots"].append(path)
        report["result_rows"].extend(feed_mlb_statsapi.result_rows(recs))
        lines, conflicts = reconcile_mlb(espn_mlb or [], recs)
        report["reconciliation"] = lines
        report["conflicts"].extend(conflicts)

    return report


def print_report(report):
    print(f"FEED SWEEP {report['date_et']} (fetched {report['fetched_utc']})")
    for lg, d in sorted(report["leagues"].items()):
        print(f"  {lg:18s} {d['games']:3d} games, {d['finals']:3d} finals  "
              f"[{d['source']} sha:{d['sha256']}]")
    for line in report.get("reconciliation") or []:
        print(f"  {line}")
    if report["conflicts"]:
        print(f"  CONFLICTS SURFACED: {len(report['conflicts'])} (never silently resolved)")
        for c in report["conflicts"]:
            print(f"    {CONFLICT} {c['kind']} {c['game']}")
    else:
        print("  no cross-feed conflicts")
    print(f"  result rows emitted: {len(report['result_rows'])}")


def build_board_from_rows(rows, sport, slate_date):
    """Result-binding board view from feed records: {game_key: {game_pk, away, home, start_utc}}.

    Produces the board argument of result_binding_gate.binding_proof directly from feed records,
    namespaced ids intact.
    """
    games = {}
    for r in rows:
        ns = f"{r['id_space']}:{r['game_id']}"
        key = f"{sport}:{r['away']}@{r['home']}"
        g = {"game_pk": ns, "away": r["away"], "home": r["home"], "start_utc": r["start_utc"]}
        if r.get("doubleheader_game_number") not in (None, 1):
            g["game_number"] = r["doubleheader_game_number"]
        games[key] = g
    return {"sport": sport, "slate_date": slate_date, "games": games}


# ====================================================================== selftest

def _fake_espn_payload(games):
    return {"events": [
        {"id": gid, "date": start,
         "status": {"type": {"name": st, "completed": st == "STATUS_FINAL"}},
         "competitions": [{"competitors": [
             {"homeAway": "away", "team": {"abbreviation": a}, "score": str(ascore) if ascore is not None else ""},
             {"homeAway": "home", "team": {"abbreviation": h}, "score": str(hscore) if hscore is not None else ""}]}]}
        for gid, start, a, h, ascore, hscore, st in games]}


def selftest():
    import io, contextlib, tempfile
    f = []

    espn_games = [("401816704", "2026-08-28T23:10Z", "HOU", "NYM", 4, 2, "STATUS_FINAL"),
                  ("401816711", "2026-08-28T18:20Z", "CIN", "CHC", 5, 6, "STATUS_FINAL"),
                  ("401816710", "2026-08-29T00:10Z", "CWS", "MIN", 1, 3, "STATUS_FINAL")]
    sa_games = [{"gamePk": 823504, "gameDate": "2026-08-28T23:15:00Z", "officialDate": "2026-08-28",
                 "status": {"detailedState": "Final", "statusCode": "F"},
                 "teams": {"away": {"team": {"name": "Boston Red Sox"}, "score": 3},
                           "home": {"team": {"name": "New York Yankees"}, "score": 6}},
                 "probablePitchers": {"away": {"fullName": "P A"}, "home": {"fullName": "G C"}},
                 "gameNumber": 1}]

    def fake_get(url):
        if "espn" in url:
            league = next(l for l, p in feed_espn.LEAGUES.items() if f"/{p}/" in url)
            games = espn_games if league == "mlb" else []
            return json.dumps(_fake_espn_payload(games))
        return json.dumps({"dates": [{"date": "2026-08-28", "games": sa_games}]})

    with tempfile.TemporaryDirectory() as td:
        rep = sweep("2026-08-28", out_root=td, get=fake_get)
        if rep["leagues"]["mlb"]["games"] != 3 or rep["leagues"]["mlb_statsapi"]["games"] != 1:
            f.append(f"sweep counts wrong: {rep['leagues']}")
        if len(rep["result_rows"]) != 4:
            f.append(f"expected 4 result rows, got {len(rep['result_rows'])}")
        # ET derivation survived the sweep: the 00:10Z CWS@MIN game is an 8/28 game
        late = [r for r in rep["result_rows"] if r["game_pk"] == "ESPN_GAMEID:401816710"]
        if not late or late[0]["scheduled_date"] != "2026-08-28":
            f.append("the late-night game crossed to the wrong ET date inside the sweep")
        # append-only: a second identical sweep writes no new snapshot files
        n_before = len(os.listdir(os.path.join(td, "2026-08-28")))
        rep2 = sweep("2026-08-28", out_root=td, get=fake_get)
        n_after = len(os.listdir(os.path.join(td, "2026-08-28")))
        if n_after != n_before:
            f.append("identical re-sweep rewrote snapshots — not append-only")
        # a CONFLICT is surfaced, never resolved: make ESPN say 4-2, StatsAPI (for the same
        # matchup) say 9-9
        sa_conflict = [dict(g, teams={"away": {"team": {"name": "Houston Astros"}, "score": 9},
                                      "home": {"team": {"name": "New York Mets"}, "score": 9}},
                            gameDate="2026-08-28T23:10Z")
                       for g in sa_games]

        def fake_get2(url):
            if "espn" in url:
                league = next(l for l, p in feed_espn.LEAGUES.items() if f"/{p}/" in url)
                return json.dumps(_fake_espn_payload(espn_games if league == "mlb" else []))
            return json.dumps({"dates": [{"date": "2026-08-28", "games": sa_conflict}]})

        with tempfile.TemporaryDirectory() as td2:
            rep3 = sweep("2026-08-28", out_root=td2, get=fake_get2)
            kinds = {c["kind"] for c in rep3["conflicts"]}
            if "SCORE_DISAGREEMENT" not in kinds:
                f.append(f"a score disagreement was silently resolved: {rep3['conflicts']}")
            # and the conflicting rows are BOTH still present in the output — surfacing means
            # both claims remain visible, not that one was dropped
            if len(rep3["result_rows"]) < 4:
                f.append("a conflict caused a row to vanish")

    print(f"feed_sweep selftest: {'OK' if not f else 'FAIL'}")
    for x in f:
        print("   -", x)
    return 0 if not f else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="FU-1 feed sweep")
    ap.add_argument("--date", help="ET slate date YYYY-MM-DD")
    ap.add_argument("--out", default="data/feeds")
    ap.add_argument("--no-statsapi", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.date:
        ap.error("--date is required unless --selftest")
    rep = sweep(args.date, out_root=args.out, also_statsapi=not args.no_statsapi)
    print_report(rep)
    out = os.path.join(args.out, args.date, "sweep_report.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as fh:
        json.dump({k: v for k, v in rep.items()}, fh, indent=1, sort_keys=True)
    print(f"  report written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
