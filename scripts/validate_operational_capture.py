#!/usr/bin/env python3
"""Verify a complete versioned operational capture without changing its bytes.

PASS establishes the declared capture contract and retained-byte consistency.
It does not authenticate providers, qualify a forecast, clear repository health,
or grant publication or wagering authority. Legacy unversioned captures remain
preserved; they cannot silently satisfy this new contract.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.operational_capture_contract import SCHEMA, TIMEZONE, nfl_source_urls, schedule_specs, summary_spec
from scripts.recovery_capture import ROUTES

VALIDATION_SCHEMA = "sports.operational_capture_validation.v1"
HASH = re.compile(r"[0-9a-f]{64}\Z")
REPORT_KEYS = {"schema", "capture_id", "date", "timezone", "capture_started_at_utc", "created_at_utc", "sources", "nfl_sources", "event_counts", "source_capture_only", "action_authority"}
SOURCE_KEYS = {"capture_id", "league", "kind", "url", "evidence_tier", "requested_at_utc", "provider_observed_at_utc", "historical_pregame_eligibility", "http_status", "headers", "final_url", "retrieved_at_utc", "raw_sha256", "raw_path", "status", "parse_status"}
NFL_KEYS = {"capture_id", "filename", "source_url", "requested_at_utc", "retrieved_at_utc", "status", "sha256", "headers", "http_status", "final_url"}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "DUPLICATE_JSON_KEY:" + key)
        result[key] = value
    return result


def decode(raw):
    def invalid(value):
        raise ValueError("NONFINITE_JSON:" + value)
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid)


def stamp(value):
    require(isinstance(value, str), "TIMESTAMP_STRING_REQUIRED")
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.tzinfo is not None and result.utcoffset() == dt.timedelta(0), "UTC_TIMESTAMP_REQUIRED")
    return result.astimezone(dt.timezone.utc)


def member(root, name):
    require(isinstance(name, str) and name and "\\" not in name and not any(ord(c) < 32 for c in name), "INVALID_MEMBER_PATH")
    path = PurePosixPath(name)
    require(not path.is_absolute() and path.as_posix() == name and not any(p in {".", ".."} for p in path.parts), "INVALID_MEMBER_PATH")
    full = root / path
    require(not any(p.is_symlink() for p in (full, *full.parents)), "SYMLINK_REFUSED:" + name)
    require(full.is_file() and full.resolve().is_relative_to(root.resolve()), "MEMBER_MISSING_OR_OUTSIDE_ROOT:" + name)
    return full


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def exact_keys(value, keys, reason):
    require(isinstance(value, dict) and set(value) == keys, reason)


def receipt_clock(row, capture_id, start, end):
    require(row["capture_id"] == capture_id, "CROSS_CAPTURE_RECEIPT")
    requested, retrieved = stamp(row["requested_at_utc"]), stamp(row["retrieved_at_utc"])
    require(start <= requested <= retrieved <= end, "CAPTURE_CHRONOLOGY_INVALID")
    return retrieved


def event_identity(event):
    require(isinstance(event, dict), "EVENT_OBJECT_REQUIRED")
    eid = event.get("id")
    require(isinstance(eid, str) and re.fullmatch(r"[0-9]+", eid), "EVENT_ID_REQUIRED")
    stamp(event.get("date"))
    competitions = event.get("competitions")
    require(isinstance(competitions, list) and len(competitions) == 1 and isinstance(competitions[0], dict), "EVENT_COMPETITION_REQUIRED")
    competition = competitions[0]
    require(competition.get("id") == eid, "EVENT_COMPETITION_ID_MISMATCH")
    sides = competition.get("competitors")
    require(isinstance(sides, list) and len(sides) == 2 and all(isinstance(s, dict) for s in sides), "EVENT_TEAMS_REQUIRED")
    require({s.get("homeAway") for s in sides} == {"home", "away"}, "EVENT_TEAM_ORIENTATION_INVALID")
    teams = [s.get("team") for s in sides]
    require(all(isinstance(t, dict) and isinstance(t.get("id"), str) and re.fullmatch(r"[0-9]+", t["id"]) for t in teams), "EVENT_TEAM_IDS_REQUIRED")
    require(teams[0]["id"] != teams[1]["id"], "EVENT_TEAM_ID_CONFLICT")
    status = competition.get("status", event.get("status", {}))
    require(isinstance(status, dict) and isinstance(status.get("type"), dict), "EVENT_STATUS_REQUIRED")
    kind = status["type"]
    require(type(kind.get("completed")) is bool and kind.get("state") in {"pre", "in", "post"} and isinstance(kind.get("name"), str) and bool(kind["name"]), "EVENT_STATUS_INVALID")
    if "date" in competition:
        require(stamp(competition["date"]) == stamp(event["date"]), "EVENT_START_CONFLICT")
    return eid


def verify_capture(root, expected_date, *, now=None):
    root = Path(root)
    now = now or dt.datetime.now(dt.timezone.utc)
    require(now.tzinfo is not None, "VALIDATOR_CLOCK_TIMEZONE_REQUIRED")
    expected = dt.date.fromisoformat(expected_date)
    require(root.is_dir() and not any(p.is_symlink() for p in (root, *root.parents)), "CAPTURE_ROOT_INVALID")
    manifest = decode(member(root, "manifest.json").read_bytes())
    require(isinstance(manifest, dict) and manifest, "MANIFEST_REQUIRED")
    for name, sha in manifest.items():
        require(name != "manifest.json" and isinstance(sha, str) and HASH.fullmatch(sha), "MANIFEST_ENTRY_INVALID")
        require(digest(member(root, name)) == sha, "MANIFEST_HASH_MISMATCH:" + name)
    actual = set()
    for path in root.rglob("*"):
        require(not path.is_symlink(), "SYMLINK_REFUSED:" + str(path.relative_to(root)))
        if not path.is_dir():
            require(path.is_file(), "SPECIAL_FILE_REFUSED")
            actual.add(path.relative_to(root).as_posix())
    require(actual == set(manifest) | {"manifest.json"}, "MANIFEST_FILE_SET_MISMATCH")
    require({"report.json", "events.json", "nfl/receipt.json"} <= set(manifest), "MANDATORY_MANIFEST_MEMBERS_MISSING")
    report = decode(member(root, "report.json").read_bytes())
    exact_keys(report, REPORT_KEYS, "REPORT_SCHEMA_INVALID")
    require(report["schema"] == SCHEMA and report["timezone"] == TIMEZONE, "CAPTURE_CONTRACT_VERSION_OR_TIMEZONE")
    require(report["date"] == expected.isoformat(), "CAPTURE_DATE_MISMATCH")
    require(isinstance(report["capture_id"], str) and re.fullmatch(r"[0-9a-f]{32}", report["capture_id"]), "CAPTURE_ID_INVALID")
    require(report["source_capture_only"] is True and report["action_authority"] is False, "CAPTURE_AUTHORITY_INVALID")
    start, end = stamp(report["capture_started_at_utc"]), stamp(report["created_at_utc"])
    require(start <= end <= now and start.astimezone(ZoneInfo(TIMEZONE)).date() == expected, "CAPTURE_CLOCK_OR_DATE_INVALID")
    require(isinstance(report["sources"], list) and isinstance(report["nfl_sources"], list), "SOURCE_LISTS_REQUIRED")
    index = {}
    for row in report["sources"]:
        exact_keys(row, SOURCE_KEYS, "SOURCE_RECEIPT_SCHEMA_INVALID")
        key = (row["league"], row["kind"], row["url"], row["evidence_tier"])
        require(key not in index, "DUPLICATE_SOURCE_RECEIPT")
        require(type(row["evidence_tier"]) is int, "SOURCE_TIER_INVALID")
        require(row["status"] == "CAPTURED" and row["parse_status"] == "JSON_PARSED", "SOURCE_NOT_CAPTURED")
        require(type(row["http_status"]) is int and row["http_status"] == 200 and row["final_url"] == row["url"], "SOURCE_HTTP_IDENTITY_INVALID")
        require(isinstance(row["headers"], dict) and row["provider_observed_at_utc"] is None and row["historical_pregame_eligibility"] is False, "SOURCE_PROVENANCE_SCHEMA_INVALID")
        receipt_clock(row, report["capture_id"], start, end)
        sha = row["raw_sha256"]
        require(isinstance(sha, str) and HASH.fullmatch(sha), "SOURCE_HASH_INVALID")
        require(row["raw_path"] == f"raw/{sha}.json", "SOURCE_PATH_HASH_BINDING_INVALID")
        require(manifest.get(row["raw_path"]) == sha, "SOURCE_MANIFEST_BINDING_INVALID")
        index[key] = row
    expected_specs = schedule_specs(expected)
    require(set(expected_specs) <= set(index), "MANDATORY_SCHEDULE_SOURCE_MISSING")
    reconstructed = {league: {} for league in ROUTES}
    expected_summaries = set()
    for spec in expected_specs:
        row = index[spec]
        payload = decode(member(root, row["raw_path"]).read_bytes())
        require(isinstance(payload, dict), "SOURCE_PAYLOAD_OBJECT_REQUIRED")
        if row["kind"] == "official_schedule":
            require(isinstance(payload.get("dates"), list), "MLB_OFFICIAL_DATES_REQUIRED")
            date_requested = parse_qs(urlparse(row["url"]).query)["date"][0]
            game_ids = set()
            for date_row in payload["dates"]:
                require(isinstance(date_row, dict) and date_row.get("date") == date_requested and isinstance(date_row.get("games"), list), "MLB_OFFICIAL_DATE_COVERAGE_INVALID")
                for game in date_row["games"]:
                    gid = game.get("gamePk") if isinstance(game, dict) else None
                    require(type(gid) is int and gid > 0 and gid not in game_ids, "MLB_OFFICIAL_GAME_ID_INVALID_OR_DUPLICATE")
                    require(abs((stamp(game.get("gameDate")).date() - dt.date.fromisoformat(date_requested)).days) <= 1, "MLB_OFFICIAL_START_DATE_INVALID")
                    teams = game.get("teams")
                    require(isinstance(teams, dict) and set(teams) == {"home", "away"}, "MLB_OFFICIAL_TEAMS_REQUIRED")
                    team_ids = []
                    for side in ("home", "away"):
                        require(isinstance(teams[side], dict) and isinstance(teams[side].get("team"), dict), "MLB_OFFICIAL_TEAM_REQUIRED")
                        team_id = teams[side]["team"].get("id")
                        require(type(team_id) is int and team_id > 0, "MLB_OFFICIAL_TEAM_ID_INVALID")
                        team_ids.append(team_id)
                    require(team_ids[0] != team_ids[1], "MLB_OFFICIAL_TEAM_ID_CONFLICT")
                    status = game.get("status")
                    require(isinstance(status, dict) and status.get("abstractGameState") in {"Preview", "Live", "Final"} and isinstance(status.get("detailedState"), str) and bool(status["detailedState"]), "MLB_OFFICIAL_STATUS_REQUIRED")
                    game_ids.add(gid)
            require(type(payload.get("totalGames")) is int and payload["totalGames"] == len(game_ids), "MLB_OFFICIAL_GAME_COUNT_MISMATCH")
            continue
        require(isinstance(payload.get("events"), list), "SCHEDULE_EVENTS_REQUIRED")
        local_ids = set()
        query_day = dt.datetime.strptime(parse_qs(urlparse(row["url"]).query)["dates"][0], "%Y%m%d").date()
        for event in payload["events"]:
            eid = event_identity(event)
            require(eid not in local_ids, "DUPLICATE_SCHEDULE_EVENT")
            local_ids.add(eid)
            require(abs((stamp(event["date"]).date() - query_day).days) <= 1, "EVENT_QUERY_DATE_MISMATCH")
            prior = reconstructed[row["league"]].get(eid)
            require(prior is None or prior["event"] == event, "CONFLICTING_SCHEDULE_EVENT")
            reconstructed[row["league"]][eid] = {"event": event, "source_sha256": row["raw_sha256"], "retrieved_at_utc": row["retrieved_at_utc"]}
            if row["league"] in {"wnba", "mlb", "nfl"}:
                expected_summaries.add(summary_spec(row["league"], eid))
    require(set(index) == set(expected_specs) | expected_summaries, "SOURCE_INVENTORY_MISMATCH")
    for spec in expected_summaries:
        row = index[spec]
        payload = decode(member(root, row["raw_path"]).read_bytes())
        require(isinstance(payload, dict) and isinstance(payload.get("header"), dict), "SUMMARY_HEADER_REQUIRED")
        eid = parse_qs(urlparse(row["url"]).query)["event"][0]
        require(payload["header"].get("id") == eid, "SUMMARY_EVENT_ID_MISMATCH")
        competitions = payload["header"].get("competitions")
        require(isinstance(competitions, list) and len(competitions) == 1 and isinstance(competitions[0], dict), "SUMMARY_COMPETITION_REQUIRED")
        comp = competitions[0]
        schedule = reconstructed[row["league"]][eid]["event"]
        require(comp.get("id") == eid and stamp(comp.get("date")) == stamp(schedule["date"]), "SUMMARY_START_OR_COMPETITION_ID_MISMATCH")
        sides = comp.get("competitors")
        require(isinstance(sides, list) and len(sides) == 2 and all(isinstance(s, dict) and isinstance(s.get("team"), dict) for s in sides), "SUMMARY_TEAMS_REQUIRED")
        require({s.get("homeAway") for s in sides} == {"home", "away"}, "SUMMARY_TEAM_ORIENTATION_INVALID")
        expected_teams = {s["homeAway"]: s["team"]["id"] for s in schedule["competitions"][0]["competitors"]}
        require({s["homeAway"]: s["team"].get("id") for s in sides} == expected_teams, "SUMMARY_TEAM_IDENTITY_MISMATCH")
        # Scores and final status may legitimately advance between captures.
        # This preflight binds identity; it is not a final-score reconciler.
    events = decode(member(root, "events.json").read_bytes())
    require(events == reconstructed, "EVENT_COVERAGE_OR_SOURCE_BINDING_MISMATCH")
    counts = {league: len(rows) for league, rows in reconstructed.items()}
    require(isinstance(report["event_counts"], dict) and all(type(v) is int and v >= 0 for v in report["event_counts"].values()) and report["event_counts"] == counts, "EVENT_COUNTS_MISMATCH")
    expected_nfl = nfl_source_urls(expected)
    nfl = {}
    for row in report["nfl_sources"]:
        exact_keys(row, NFL_KEYS, "NFL_RECEIPT_SCHEMA_INVALID")
        name = row["filename"]
        require(name not in nfl and name in expected_nfl and row["source_url"] == expected_nfl[name], "NFL_SOURCE_INVENTORY_INVALID")
        require(row["status"] == "captured" and isinstance(row["headers"], dict) and type(row["http_status"]) is int and row["http_status"] == 200, "NFL_SOURCE_NOT_CAPTURED")
        final = urlparse(row["final_url"])
        require(final.scheme == "https" and final.hostname and not final.username and not final.password and not final.fragment, "NFL_FINAL_URL_INVALID")
        receipt_clock(row, report["capture_id"], start, end)
        sha = row["sha256"]
        require(isinstance(sha, str) and HASH.fullmatch(sha) and manifest.get("nfl/" + name) == sha, "NFL_MANIFEST_BINDING_INVALID")
        with member(root, "nfl/" + name).open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle, strict=True)
            required = {"game_id", "season", "week"} | ({"play_id"} if name.startswith("play_by_play_") else set())
            require(reader.fieldnames is not None and len(set(reader.fieldnames)) == len(reader.fieldnames) and required <= set(reader.fieldnames), "NFL_CSV_HEADER_INVALID")
            first = next(reader, None)
            require(first is not None and None not in first and all(v is not None for v in first.values()) and all(first.get(k) for k in required), "NFL_CSV_ROWS_MISSING_OR_INVALID")
            for record in reader:
                require(None not in record and all(v is not None for v in record.values()) and all(record.get(k) for k in required), "NFL_CSV_ROW_INVALID")
        nfl[name] = row
    require(set(nfl) == set(expected_nfl), "MANDATORY_NFL_SOURCE_MISSING")
    require(decode(member(root, "nfl/receipt.json").read_bytes()) == report["nfl_sources"], "NFL_RECEIPT_MIRROR_MISMATCH")
    expected_members = {"report.json", "events.json", "nfl/receipt.json"} | {r["raw_path"] for r in index.values()} | {"nfl/" + n for n in expected_nfl}
    require(set(manifest) == expected_members, "UNREFERENCED_MANIFEST_MEMBER")
    return {"schema": VALIDATION_SCHEMA, "ok": True, "errors": [], "date": expected_date, "capture_id": report["capture_id"], "event_counts": counts,
            "source_count": len(index), "nfl_source_count": len(nfl), "manifest_sha256": digest(member(root, "manifest.json")),
            "validation_scope": "CAPTURE_CONTRACT_AND_RETAINED_BYTES", "provider_authenticity_verified": False,
            "source_capture_only": True, "action_authority": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected-date", default=dt.datetime.now(ZoneInfo(TIMEZONE)).date().isoformat())
    args = parser.parse_args(argv)
    try:
        result = verify_capture(args.root, args.expected_date)
    except (ValueError, OSError, KeyError, TypeError, csv.Error) as exc:
        result = {"schema": VALIDATION_SCHEMA, "ok": False, "errors": [str(exc)], "date": args.expected_date,
                  "source_capture_only": True, "action_authority": False}
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
