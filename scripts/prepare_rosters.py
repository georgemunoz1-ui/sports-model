#!/usr/bin/env python3
"""Capture current rosters for all seven sports, retaining every requested team.

Use a new output directory for a refresh. --resume reuses valid team receipts;
it never refreshes their timestamps. A source failure is a ledger row, not omission.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sports.rosters import ROUTES, SCHEMA, digest, load_bundle, normalize_team, read_source, seal, team_directory


def now():
    return datetime.now(timezone.utc).isoformat()


def write_once(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not isinstance(data, bytes):
        data = (json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(name, path)  # Publish the complete file; never replace a valid artifact.
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError("ROSTER_IMMUTABLE_CONFLICT:" + str(path))
    finally:
        os.unlink(name)


def capture(root, sport, url):
    receipt = {"url": url, "sport": sport, "provider": "ESPN", "evidence_tier": 2,
               "requested_at_utc": now(), "historical_pregame_eligibility": False}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "sports-model-rosters/1.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as response:
            raw = response.read(20_000_001)
            receipt.update(http_status=response.status, final_url=response.url, headers=dict(response.headers))
        receipt["retrieved_at_utc"] = now()
        if len(raw) > 20_000_000:
            raise ValueError("RESPONSE_TOO_LARGE")
        sha = hashlib.sha256(raw).hexdigest()
        path = f"raw/{sha}.json"
        write_once(root / path, raw)
        receipt.update(status="CAPTURED", raw_sha256=sha, raw_path=path)
        json.loads(raw)
    except Exception as exc:
        receipt.update(status="FAILED", retrieved_at_utc=now(), reason=f"{type(exc).__name__}:{exc}")
    return receipt


def capture_or_resume(root, sport, key, url):
    path = root / "receipts" / sport / f"{key}.json"
    if path.exists():
        receipt = json.loads(path.read_bytes())
        if receipt["url"] != url:
            raise ValueError("ROSTER_RESUME_IDENTITY")
        if receipt["status"] == "CAPTURED":
            read_source(root, receipt)
        return receipt
    receipt = capture(root, sport, url)
    write_once(path, receipt)
    return receipt


def cfb_scope(path, teams, root):
    """Use the current model's FBS census; verify its ID AND exact provider name."""
    import pandas as pd
    raw = Path(path).read_bytes()
    saved = "scope/cfb_schedule.parquet"
    write_once(root / saved, raw)
    frame = pd.read_parquet(path)
    if frame.season.nunique() != 1:
        raise ValueError("ROSTER_CFB_SINGLE_SEASON_REQUIRED")
    by_id = {str(t["id"]): t for t in teams}
    selected = set()
    for side in ("home", "away"):
        for r in frame[frame[f"{side}_division"] == "fbs"].to_dict("records"):
            tid, name = str(r[f"{side}_id"]), r[f"{side}_team"]
            t = by_id.get(tid, {})
            if name not in [t.get(k) for k in ("displayName", "location", "shortDisplayName", "nickname", "abbreviation")]:
                raise ValueError("ROSTER_CFB_ID_NAME_MISMATCH:" + name)
            selected.add(tid)
    if not selected:
        raise ValueError("ROSTER_EMPTY_FBS_CENSUS")
    return selected, {"path": saved, "sha256": hashlib.sha256(raw).hexdigest(), "season": int(frame.season.iloc[0])}


def prepare(output, sports, workers=8, cfb_schedule=None, resume=False):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=resume)
    if (root / "bundle.json").exists():
        return load_bundle(root / "bundle.json")
    bundle = {"schema": SCHEMA, "created_at_utc": now(), "sports": {}, "action_authority": False,
              "collector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "normalizer_sha256": hashlib.sha256((ROOT / "sports/rosters.py").read_bytes()).hexdigest(),
              "role": "CURRENT_MEMBERSHIP_EVIDENCE_ONLY", "historical_pit_validity_proven": False}
    def census(sport):
        url = f"https://site.api.espn.com/apis/site/v2/sports/{ROUTES[sport]}/teams?limit=1000"
        receipt = capture_or_resume(root, sport, "census", url)
        return sport, receipt
    with ThreadPoolExecutor(max_workers=workers) as pool:
        censuses = list(pool.map(census, sports))
    tasks = []
    for sport, receipt in censuses:
        league = {"census_source": receipt, "requested_team_ids": [], "teams": [], "membership_conflicts": {}}
        bundle["sports"][sport] = league
        try:
            teams = team_directory(read_source(root, receipt))
            league.update(census_status="CAPTURED", scope="ALL_PROVIDER_TEAMS", provider_team_count=len(teams))
            if sport == "cfb" and cfb_schedule:
                selected, evidence = cfb_scope(cfb_schedule, teams, root)
                teams = [t for t in teams if str(t["id"]) in selected]
                league.update(scope="FBS_SCHEDULE_ID_AND_NAME_MATCH", scope_evidence=evidence)
            teams.sort(key=lambda t: str(t["id"]))
            league["requested_team_ids"] = [str(t["id"]) for t in teams]
            tasks.extend((sport, t) for t in teams)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            league.update(census_status="FAILED", reason=str(exc))
    def roster(task):
        sport, team = task
        tid = str(team["id"])
        url = f"https://site.api.espn.com/apis/site/v2/sports/{ROUTES[sport]}/teams/{tid}/roster?limit=1000"
        row = {"provider_team_id": tid, "team_name": team["displayName"]}
        try:
            receipt = capture_or_resume(root, sport, "team-" + tid, url)
            row["source"] = receipt
            row["snapshot"] = normalize_team(sport, team, read_source(root, receipt), receipt)
            row["status"] = "PARSED"
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row.update(status="FAILED", reason=str(exc))
        return sport, row
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for sport, row in pool.map(roster, tasks):
            bundle["sports"][sport]["teams"].append(row)
    for league in bundle["sports"].values():
        owners = {}
        for row in league["teams"]:
            if row["status"] == "PARSED":
                for p in row["snapshot"]["players"]:
                    owners.setdefault(p["player_id"], []).append(row["snapshot"]["team_id"])
        league["membership_conflicts"] = {pid: sorted(v) for pid, v in owners.items() if len(v) > 1}
        league["counts"] = {"requested": len(league["requested_team_ids"]),
                            "parsed": sum(r["status"] == "PARSED" for r in league["teams"]),
                            "failed": sum(r["status"] == "FAILED" for r in league["teams"]),
                            "distinct_players": len(owners), "conflicting_players": len(league["membership_conflicts"])}
    bundle["completed_at_utc"] = now()
    write_once(root / "bundle.json", seal(bundle))
    result = load_bundle(root / "bundle.json")
    write_once(root / "manifest.json", {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in sorted(root.rglob("*")) if p.is_file() and not p.name.startswith(".pending-")})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sport", action="append", choices=list(ROUTES))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--cfb-schedule", type=Path, help="Current single-season schedule parquet with FBS division and team IDs/names")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.workers <= 16:
        parser.error("workers must be 1..16")
    sports = args.sport or list(ROUTES)
    if len(set(sports)) != len(sports):
        parser.error("duplicate sports")
    bundle = prepare(args.output, sports, args.workers, args.cfb_schedule, args.resume)
    print(json.dumps({s: {"census_status": l["census_status"], "scope": l.get("scope"), **l.get("counts", {})}
                      for s, l in bundle["sports"].items()}, indent=2))
    if any(l["census_status"] != "CAPTURED" or l["counts"]["failed"] or l["counts"]["conflicting_players"] for l in bundle["sports"].values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
