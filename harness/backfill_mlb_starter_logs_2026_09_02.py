#!/usr/bin/env python3
"""Backfill official MLB starter box-score lines for 2026-08-24..2026-09-02.

Purpose
-------
The canonical results backfill repairs game outcomes, but the model also consumes
per-pitcher start logs. The late-August Lancebroz refresh contains useful SO/BB/TBF
observations while ER is explicitly placeholder on many rows. This one-off repair
uses official MLB StatsAPI boxscores keyed by the already-verified gamePk universe
and writes the forward log format:

    date|opp|IP|ER|SO|BB|TBF|GS

Rules
-----
* Exactly the 135 official finals in the requested date window are eligible.
* Exactly 270 starter slots must resolve (away + home for every game).
* Official rows may replace 7-field lean/placeholder rows for the same pitcher/date.
* Existing 8/10-field rows must agree with official stats or the run hard-fails.
* Missing pitcher log files are created.
* Superseded pitcher/date entries are removed from _placeholders.json only after
  genuine official ER/BB are written.
* Evidence and report are deterministic/idempotent after the first successful run.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
RESULTS = BASE / "data/backfill/mlb/2026/results.csv"
LOG_DIR = BASE / "data/backfill/mlb/2026/pitcher_logs"
PLACEHOLDERS = LOG_DIR / "_placeholders.json"
EVIDENCE = BASE / "data/mlb/evidence/backfill_starters_2026-08-24_2026-09-02.json"
REPORT = BASE / "reports/backfill/2026-09-02_mlb_gap_backfill.json"
START = "2026-08-24"
END = "2026-09-02"
EXPECTED_GAMES = 135
EXPECTED_SLOTS = EXPECTED_GAMES * 2
BOX_URL = "https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"

TEAM_ABBR = {
    "Arizona Diamondbacks": "AZ", "Athletics": "ATH", "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS", "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS", "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL", "Detroit Tigers": "DET", "Houston Astros": "HOU",
    "Kansas City Royals": "KC", "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN",
    "New York Mets": "NYM", "New York Yankees": "NYY", "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD", "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
}
EXPECTED_BY_DATE = {
    "2026-08-24": 10, "2026-08-25": 15, "2026-08-26": 15, "2026-08-27": 7,
    "2026-08-28": 15, "2026-08-29": 17, "2026-08-30": 14, "2026-08-31": 12,
    "2026-09-01": 15, "2026-09-02": 15,
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_json(url: str, tries: int = 4) -> dict:
    err = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sports-model-backfill/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            err = exc
            if attempt + 1 < tries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"fetch failed after {tries} tries: {url}: {err}")


def load_games() -> list[dict]:
    rows = list(csv.DictReader(RESULTS.open(newline="", encoding="utf-8")))
    selected = [r for r in rows if r.get("status") == "final" and START <= r.get("date", "") <= END]
    counts = Counter(r["date"] for r in selected)
    assert dict(sorted(counts.items())) == EXPECTED_BY_DATE, (dict(sorted(counts.items())), EXPECTED_BY_DATE)
    assert len(selected) == EXPECTED_GAMES
    ids = [r["game_id"] for r in selected]
    assert len(ids) == len(set(ids)), "duplicate game ids inside target window"
    for r in selected:
        assert r.get("source_tier") == "1" and r.get("result_status") == "FINAL", r["game_id"]
        assert r["away"] in TEAM_ABBR and r["home"] in TEAM_ABBR, (r["away"], r["home"])
    return sorted(selected, key=lambda r: (r["date"], r["game_id"]))


def game_pk(row: dict) -> str:
    gid = row["game_id"]
    pk = gid.rsplit(":", 1)[-1]
    assert pk.isdigit(), gid
    return pk


def _pitching_stats(team_box: dict, pid: int) -> dict:
    key = f"ID{pid}"
    player = team_box.get("players", {}).get(key) or {}
    return (player.get("stats") or {}).get("pitching") or {}


def choose_starter(team_box: dict) -> tuple[int, dict, str]:
    pitchers = [int(x) for x in team_box.get("pitchers", [])]
    assert pitchers, "boxscore team has no pitchers"
    explicit = []
    for pid in pitchers:
        st = _pitching_stats(team_box, pid)
        if int(st.get("gamesStarted") or 0) == 1:
            explicit.append(pid)
    if len(explicit) > 1:
        raise AssertionError(f"multiple gamesStarted=1 pitchers in one team box: {explicit}")
    pid = explicit[0] if explicit else pitchers[0]
    player = team_box.get("players", {}).get(f"ID{pid}") or {}
    name = ((player.get("person") or {}).get("fullName") or "").strip()
    st = (player.get("stats") or {}).get("pitching") or {}
    if not name:
        raise AssertionError(f"starter {pid} missing fullName")
    required = ["inningsPitched", "earnedRuns", "strikeOuts", "baseOnBalls", "battersFaced"]
    missing = [k for k in required if k not in st]
    if missing:
        raise AssertionError(f"starter {pid} {name} missing stats {missing}")
    out = {
        "inningsPitched": str(st["inningsPitched"]),
        "earnedRuns": int(st["earnedRuns"]),
        "strikeOuts": int(st["strikeOuts"]),
        "baseOnBalls": int(st["baseOnBalls"]),
        "battersFaced": int(st["battersFaced"]),
    }
    if out["battersFaced"] <= 0:
        raise AssertionError(f"starter {pid} {name} has invalid TBF={out['battersFaced']}")
    return pid, out, name


def fetch_starters(games: list[dict]) -> list[dict]:
    slots = []
    for i, r in enumerate(games, 1):
        pk = game_pk(r)
        url = BOX_URL.format(game_pk=pk)
        box = fetch_json(url)
        teams = box.get("teams") or {}
        for side in ("away", "home"):
            pid, st, name = choose_starter(teams[side])
            opp_name = r["home"] if side == "away" else r["away"]
            rec = {
                "date": r["date"], "gamePk": pk, "side": side,
                "pitcher_id": str(pid), "pitcher_name": name,
                "team": TEAM_ABBR[r[side]], "opp": TEAM_ABBR[opp_name],
                "IP": st["inningsPitched"], "ER": st["earnedRuns"],
                "SO": st["strikeOuts"], "BB": st["baseOnBalls"], "TBF": st["battersFaced"],
                "GS": 1, "official_url": url,
            }
            slots.append(rec)
        if i % 25 == 0 or i == len(games):
            print(f"fetched boxscores {i}/{len(games)}; starter slots={len(slots)}")
    assert len(slots) == EXPECTED_SLOTS
    keys = [(x["date"], x["gamePk"], x["side"]) for x in slots]
    assert len(keys) == len(set(keys)), "duplicate starter slot"
    return slots


def split_existing(line: str) -> dict | None:
    p = line.rstrip("\n").split("|")
    if len(p) == 10:
        return {"width": 10, "date": p[0], "opp": p[2], "IP": p[4], "ER": p[5], "SO": p[6], "BB": p[7], "TBF": p[8], "GS": p[9]}
    if len(p) == 8:
        return {"width": 8, "date": p[0], "opp": p[1], "IP": p[2], "ER": p[3], "SO": p[4], "BB": p[5], "TBF": p[6], "GS": p[7]}
    if len(p) == 7:
        return {"width": 7, "date": p[0], "opp": "", "IP": p[1], "ER": p[2], "SO": p[3], "BB": p[4], "TBF": p[5], "GS": p[6]}
    return None


def same_stats(old: dict, new: dict) -> bool:
    try:
        return (
            float(old["IP"]) == float(new["IP"])
            and int(float(old["ER"])) == int(new["ER"])
            and int(float(old["SO"])) == int(new["SO"])
            and int(float(old["BB"])) == int(new["BB"])
            and int(float(old["TBF"])) == int(new["TBF"])
            and int(float(old["GS"])) == 1
        )
    except (ValueError, TypeError):
        return False


def official_line(x: dict) -> str:
    return f"{x['date']}|{x['opp']}|{x['IP']}|{x['ER']}|{x['SO']}|{x['BB']}|{x['TBF']}|1"


def update_logs(slots: list[dict], apply: bool) -> dict:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stats = Counter()
    unique_pids = set()
    changed_dates = set()
    by_pid = {}
    for x in slots:
        by_pid.setdefault(x["pitcher_id"], []).append(x)
    for pid, items in sorted(by_pid.items(), key=lambda kv: int(kv[0])):
        unique_pids.add(pid)
        path = LOG_DIR / f"{pid}.txt"
        existed = path.exists()
        lines = path.read_text(encoding="utf-8").splitlines() if existed else []
        # Fail on duplicate target dates already present; same pitcher starting twice on a date
        # requires explicit doubleheader reconciliation rather than silent collapse.
        target_dates = Counter(x["date"] for x in items)
        dup_target = [d for d, n in target_dates.items() if n > 1]
        if dup_target:
            raise AssertionError(f"pitcher {pid} has multiple starter slots on same date {dup_target}")
        parsed = [split_existing(ln) for ln in lines]
        for x in sorted(items, key=lambda z: z["date"]):
            idxs = [i for i, p in enumerate(parsed) if p and p["date"] == x["date"]]
            if len(idxs) > 1:
                raise AssertionError(f"pitcher {pid} duplicate existing rows on {x['date']}")
            new_ln = official_line(x)
            if not idxs:
                lines.append(new_ln); parsed.append(split_existing(new_ln)); stats["rows_appended"] += 1
                changed_dates.add((pid, x["date"]))
                continue
            i = idxs[0]; old = parsed[i]
            if old["width"] == 7:
                lines[i] = new_ln; parsed[i] = split_existing(new_ln); stats["rows_replaced_lean"] += 1
                changed_dates.add((pid, x["date"]))
            elif same_stats(old, x):
                # Normalize to forward 8-field form only when an identical row is already present.
                if lines[i] != new_ln:
                    lines[i] = new_ln; parsed[i] = split_existing(new_ln); stats["rows_normalized"] += 1
                    changed_dates.add((pid, x["date"]))
                else:
                    stats["rows_already_official"] += 1
            else:
                raise AssertionError(
                    f"official conflict pid={pid} date={x['date']} old={lines[i]!r} new={new_ln!r}"
                )
        # Keep deterministic chronological order while preserving non-target legacy rows.
        def sort_key(ln: str):
            p = split_existing(ln)
            return (p["date"] if p else "9999-99-99", ln)
        lines = sorted(lines, key=sort_key)
        content = "\n".join(lines) + ("\n" if lines else "")
        if apply:
            path.write_text(content, encoding="utf-8")
        if not existed:
            stats["log_files_created"] += 1
    stats["unique_pitchers_touched"] = len(unique_pids)
    stats["starter_slots_processed"] = len(slots)
    return {"stats": dict(stats), "changed_dates": sorted([{"pitcher_id": p, "date": d} for p, d in changed_dates], key=lambda x: (x["date"], int(x["pitcher_id"]))) }


def update_placeholders(changed_dates: list[dict], apply: bool) -> int:
    if not PLACEHOLDERS.exists():
        return 0
    payload = json.loads(PLACEHOLDERS.read_text(encoding="utf-8"))
    keys = {(x["pitcher_id"], x["date"]) for x in changed_dates}
    old_rows = list(payload.get("rows") or [])
    keep = [r for r in old_rows if (str(r.get("pitcher_id")), r.get("date")) not in keys]
    removed = len(old_rows) - len(keep)
    if removed and apply:
        payload["rows"] = keep
        payload["last_superseded_by"] = {
            "source": "official MLB StatsAPI boxscore starter backfill",
            "window": [START, END],
            "removed_rows": removed,
        }
        PLACEHOLDERS.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return removed


def evidence_payload(slots: list[dict]) -> dict:
    previous = None
    if EVIDENCE.exists():
        try:
            previous = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = None
    retrieved = (previous or {}).get("retrieved_at_utc") or os.environ.get("BACKFILL_RETRIEVED_AT_UTC") or "2026-09-03T08:30:00Z"
    return {
        "record_id": "MLB-STARTER-BACKFILL-2026-08-24-2026-09-02",
        "schema_version": "mlb-starter-boxscore-backfill-v1",
        "source": "MLB StatsAPI official game boxscore",
        "source_tier": 1,
        "window": [START, END],
        "retrieved_at_utc": retrieved,
        "starter_slots": slots,
    }


def write_json_if_apply(path: Path, payload: dict, apply: bool):
    text = json.dumps(payload, indent=1, sort_keys=True) + "\n"
    if apply:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return sha256_bytes(text.encode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    games = load_games()
    slots = fetch_starters(games)
    evidence = evidence_payload(slots)
    evidence_sha = write_json_if_apply(EVIDENCE, evidence, args.apply)
    log_result = update_logs(slots, args.apply)
    removed = update_placeholders(log_result["changed_dates"], args.apply)
    max_obs = max(x["date"] for x in slots)
    report = {
        "record_id": "MLB-GAP-BACKFILL-2026-09-02",
        "status": "BACKFILL_COMPLETE" if len(slots) == EXPECTED_SLOTS else "BACKFILL_INCOMPLETE",
        "window": [START, END],
        "result_games_expected": EXPECTED_GAMES,
        "result_games_present": len(games),
        "result_coverage_pct": round(100.0 * len(games) / EXPECTED_GAMES, 4),
        "result_counts_by_date": EXPECTED_BY_DATE,
        "starter_slots_expected": EXPECTED_SLOTS,
        "starter_slots_fetched": len(slots),
        "starter_coverage_pct": round(100.0 * len(slots) / EXPECTED_SLOTS, 4),
        "max_starter_observation_date": max_obs,
        "unique_pitchers_touched": log_result["stats"].get("unique_pitchers_touched", 0),
        "log_files_created": log_result["stats"].get("log_files_created", 0),
        "log_rows_appended": log_result["stats"].get("rows_appended", 0),
        "log_rows_replaced_lean": log_result["stats"].get("rows_replaced_lean", 0),
        "log_rows_normalized": log_result["stats"].get("rows_normalized", 0),
        "log_rows_already_official": log_result["stats"].get("rows_already_official", 0),
        "placeholder_rows_superseded": removed,
        "evidence_path": str(EVIDENCE.relative_to(BASE)),
        "evidence_sha256": evidence_sha,
        "errors": [],
        "healthcheck": {"status": "PENDING_WORKFLOW", "exit_code": None},
    }
    write_json_if_apply(REPORT, report, args.apply)
    print(json.dumps(report, sort_keys=True))
    assert len(games) == EXPECTED_GAMES
    assert len(slots) == EXPECTED_SLOTS
    assert max_obs == END
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
