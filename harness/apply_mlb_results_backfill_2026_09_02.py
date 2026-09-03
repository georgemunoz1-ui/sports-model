#!/usr/bin/env python3
"""Apply the 2026-08-24..2026-09-02 official MLB result backfill.

The source evidence is committed separately and is treated as immutable Tier-1
MLB.com evidence. This script is intentionally idempotent: running it twice must
produce the same results.csv bytes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
RESULTS = BASE / "data/backfill/mlb/2026/results.csv"
EVIDENCE = [
    BASE / "data/mlb/evidence/backfill_2026-08-24.json",
    BASE / "data/mlb/evidence/backfill_2026-08-25_2026-09-01.json",
    BASE / "data/mlb/evidence/backfill_2026-09-02.json",
]
INGESTED_UTC = "2026-09-03T07:15:00Z"
EXPECTED_START = "2026-08-24"
EXPECTED_END = "2026-09-02"
EXPECTED_NEW_GAMES = 135
IDENTITY_FIELDS = ("date", "away", "home", "away_score", "home_score", "home_win", "margin", "total")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_evidence():
    games = []
    seen = set()
    for path in EVIDENCE:
        raw = path.read_bytes()
        payload = json.loads(raw)
        evidence_sha = sha256_bytes(raw)
        inherited_date = payload.get("date")
        assert payload.get("source_tier") == 1, f"non-tier-1 evidence: {path}"
        for g in payload["games"]:
            game = dict(g)
            game["date"] = game.get("date") or inherited_date
            game["evidence_path"] = str(path.relative_to(BASE))
            game["evidence_sha256"] = evidence_sha
            gid = str(game["gamePk"])
            assert gid.isdigit(), f"invalid gamePk {gid!r}"
            assert gid not in seen, f"duplicate evidence gamePk {gid}"
            seen.add(gid)
            assert game["official_url"].startswith("https://www.mlb.com/gameday/"), game
            assert gid in game["official_url"], game
            aw, hm = int(game["away_score"]), int(game["home_score"])
            assert aw != hm, f"unexpected tied final: {game}"
            expected_winner = game["home"] if hm > aw else game["away"]
            assert game["winner"] == expected_winner, f"winner mismatch: {game}"
            assert game["date"], f"missing date: {game}"
            games.append(game)
    dates = [g["date"] for g in games]
    assert min(dates) == EXPECTED_START, (min(dates), EXPECTED_START)
    assert max(dates) == EXPECTED_END, (max(dates), EXPECTED_END)
    assert len(games) == EXPECTED_NEW_GAMES, (len(games), EXPECTED_NEW_GAMES)
    return games


def canonical_row(game, fieldnames):
    aw, hm = int(game["away_score"]), int(game["home_score"])
    values = {
        "sport": "mlb", "season": "2026", "game_id": f"mlb:2026:{game['gamePk']}",
        "date": game["date"], "status": "final", "away": game["away"], "home": game["home"],
        "away_score": str(aw), "home_score": str(hm), "home_win": "1" if hm > aw else "0",
        "margin": str(hm - aw), "total": str(hm + aw), "neutral_site": str(int(game.get("neutral_site", 0))),
        "venue": game["venue"], "close_ml_away": "", "close_ml_home": "", "close_spread_home": "",
        "close_total": "", "features_json": "", "source": "MLB.com Gameday", "ingested_utc": INGESTED_UTC,
        "source_tier": "1", "result_status": "FINAL", "evidence_path": game["evidence_path"],
        "evidence_sha256": game["evidence_sha256"],
    }
    missing = set(fieldnames) - set(values)
    extra = set(values) - set(fieldnames)
    assert not missing and not extra, f"schema mismatch missing={missing} extra={extra}"
    return {k: values[k] for k in fieldnames}


def render(apply: bool):
    with RESULTS.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f); fieldnames = reader.fieldnames; rows = list(reader)
    assert fieldnames, "results.csv missing header"
    old_ids = {r["game_id"] for r in rows}
    assert len(old_ids) == len(rows), "base results.csv already has duplicate game_id"
    generated = [canonical_row(g, fieldnames) for g in load_evidence()]
    generated_by_id = {r["game_id"]: r for r in generated}
    existing_by_id = {r["game_id"]: r for r in rows}

    overlaps=[]; conflicts=[]; additions=[]
    for gid, new in generated_by_id.items():
        if gid not in existing_by_id:
            additions.append(new); continue
        old=existing_by_id[gid]
        diffs={k:{"existing":old[k],"official":new[k]} for k in IDENTITY_FIELDS if old[k] != new[k]}
        if diffs: conflicts.append({"game_id":gid,"diffs":diffs})
        else: overlaps.append(gid)
    if conflicts:
        print(json.dumps({"status":"CONFLICT","overlap_count":len(overlaps),"conflicts":conflicts}, sort_keys=True))
        raise SystemExit(2)

    merged = rows + additions
    merged.sort(key=lambda r: (r["date"], r["game_id"]))
    ids = [r["game_id"] for r in merged]
    assert len(ids) == len(set(ids)), "duplicate game_id after merge"
    assert max(r["date"] for r in merged if r["status"] == "final") >= EXPECTED_END
    buf = io.StringIO(newline=""); writer = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader(); writer.writerows(merged); out=buf.getvalue()
    print(json.dumps({"base_rows":len(rows),"evidence_games":len(generated),"existing_verified_overlaps":len(overlaps),
        "new_rows":len(additions),"merged_rows":len(merged),"max_final_date":max(r["date"] for r in merged if r["status"]=="final"),
        "output_sha256":hashlib.sha256(out.encode()).hexdigest(),"mode":"apply" if apply else "check"}, sort_keys=True))
    if apply: RESULTS.write_text(out, encoding="utf-8", newline="")


if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument("--apply", action="store_true"); args=p.parse_args(); render(args.apply)
