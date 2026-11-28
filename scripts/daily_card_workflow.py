#!/usr/bin/env python3
"""Research-only current-day orchestration; no registration, model promotion or wager authority."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
from urllib.parse import parse_qs, urlparse
from zipfile import ZipFile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PACIFIC = ZoneInfo("America/Los_Angeles")
EASTERN = ZoneInfo("America/New_York")
UTC = dt.timezone.utc
CBB_COMMIT = "fd0634c324c720362e77b9be4042c34e0c730bdb"
SCOPE = ROOT / "research/nhl-season-scope-2026-27-v2.json"
LEAGUES = ("cfb", "cbb", "nba", "nhl", "nfl")
DRAWS = 100000
SHA = re.compile(r"[0-9a-f]{64}")
SCHEDULE_BASE = "https://site.api.espn.com/apis/site/v2/sports/"
ROUTES = {"nba": "basketball/nba", "nhl": "hockey/nhl", "nfl": "football/nfl"}
NFL_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"


def now():
    return dt.datetime.now(UTC)


def instant(s):
    t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return t.astimezone(UTC)


def validate_date(value, clock=None):
    clock = clock or now()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
        raise ValueError("EXACT_ISO_DATE_REQUIRED")
    day = dt.date.fromisoformat(value)
    if day.isoformat() != value or day != clock.astimezone(PACIFIC).date():
        raise ValueError("LIVE_PACIFIC_DATE_REQUIRED")
    return day


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def inside(root, relative):
    root = Path(root).resolve()
    relative = Path(relative)
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root) or not path.is_file():
        raise ValueError("MISSING_OR_ESCAPING_ARTIFACT_PATH:" + str(relative))
    return path


def manifest(root, name="manifest.json"):
    root = Path(root)
    return {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob("*"))
            if p.is_file() and p != root / name}


def verify_manifest(root, name="manifest.json"):
    root = Path(root)
    expected = read(root / name)
    if not isinstance(expected, dict) or not expected:
        raise ValueError("EMPTY_MANIFEST:" + str(root))
    for rel, sha in expected.items():
        if not isinstance(sha, str) or not SHA.fullmatch(sha) or digest(inside(root, rel)) != sha:
            raise ValueError("MANIFEST_MISMATCH:" + str(rel))
    if set(expected) != set(manifest(root, name)):
        raise ValueError("MANIFEST_FILE_CENSUS_MISMATCH:" + str(root))
    return expected


def run(script, *args, cwd=ROOT, env=None, allowed=(0,)):
    command = [sys.executable, str(Path(cwd) / "scripts" / (script + ".py")), *map(str, args)]
    print("RUN", json.dumps(command), flush=True)
    rc = subprocess.run(command, cwd=cwd, env=env, check=False).returncode
    if rc not in allowed:
        raise RuntimeError(script + ":EXIT_" + str(rc))
    return rc


def stage(output, day, label, fn):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": "sports.daily_card_stage.v1", "stage": label,
               "date": day, "started_at_utc": now().isoformat(),
               "run_id": os.getenv("GITHUB_RUN_ID"), "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
               "code_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
               "action_authority": False, "official_units": 0, "qualification": "NO_PICK"}
    rc = 0
    try:
        validate_date(day)
        if os.getenv("VALIDATED_ATTEMPT") and os.getenv("VALIDATED_ATTEMPT") != os.getenv("GITHUB_RUN_ATTEMPT"):
            raise ValueError("RERUN_ALL_JOBS_OR_NEW_DISPATCH_REQUIRED")
        result = fn(output)
        receipt.update(result)
        if result["status"] not in {"ACQUIRED", "VERIFIED_NATIVE_OUTPUT", "NO_SCHEDULED_EVENTS_IN_RECONCILED_SCOPE"}:
            rc = 2
    except Exception as exc:
        receipt.update(status="BLOCKED_OR_FAILED", reason=type(exc).__name__ + ":" + str(exc))
        rc = 2
    receipt["finished_at_utc"] = now().isoformat()
    write(output / "stage_receipt.json", receipt)
    write(output / "stage_manifest.json", manifest(output, "stage_manifest.json"))
    print(json.dumps(receipt, indent=2), flush=True)
    return rc


def acquire(kind, day, output):
    # Only parent is created. Native collectors own exclusive target creation.
    dest = output / day / kind
    dest.parent.mkdir(parents=True, exist_ok=True)
    script = "capture_operational_inputs" if kind == "operational" else "capture_model_recovery"
    run(script, "--output", dest)
    verify_manifest(dest)
    report = read(dest / "report.json")
    if report.get("action_authority") is not False:
        raise ValueError("RESEARCH_SOURCE_REQUIRED")
    if kind == "operational" and report.get("date") != day:
        raise ValueError("ACQUISITION_DATE_MISMATCH")
    failures = [r for r in report.get("sources", []) + report.get("binary_sources", []) + report.get("nfl_sources", [])
                if str(r.get("status", "")).upper() != "CAPTURED"]
    # Failed unrelated sources do not block unaffected leagues. Each builder
    # rechecks its own source receipts and manifests.
    return {"status": "ACQUIRED", "source_failures": len(failures),
            "bundle": str(dest.relative_to(output)), "bundle_manifest_sha256": digest(dest / "manifest.json")}


def captured_schedule(root, league, day, cutoff=None):
    """Exact adjacent-day ESPN requests; retain provider scope, not an official ID crosswalk."""
    from scripts.nhl_history_applicability import receipt
    root = Path(root)
    cutoff = cutoff or now()
    report = read(root / "report.json")
    if report.get("date") != day or report.get("timezone") != PACIFIC.key or report.get("action_authority") is not False:
        raise ValueError("OPERATIONAL_REPORT_SCOPE")
    dates = {(dt.date.fromisoformat(day) + dt.timedelta(days=i)).strftime("%Y%m%d") for i in (-1, 0, 1)}
    endpoint = SCHEDULE_BASE + ROUTES[league] + "/scoreboard"
    selected = []
    seen = set()
    events = {}
    for row in report["sources"]:
        if row.get("league") != league or row.get("kind") != "schedule":
            continue
        u = urlparse(row["url"])
        q = parse_qs(u.query)
        stamp = q.get("dates", [""])[0]
        if stamp not in dates:
            continue
        if u.scheme + "://" + u.netloc + u.path != endpoint or q.get("limit") != ["1000"] or stamp in seen:
            raise ValueError("SCHEDULE_REQUEST_IDENTITY")
        seen.add(stamp)
        body = receipt(root, row, cutoff)
        raw_events = body.get("events")
        if not isinstance(raw_events, list) or len(raw_events) >= 1000:
            raise ValueError("SCHEDULE_CENSUS_UNVERIFIED")
        ids = set()
        for event in raw_events:
            eid = str(event["id"])
            if not eid or eid in ids:
                raise ValueError("DUPLICATE_PROVIDER_EVENT")
            ids.add(eid)
            instant(event["date"])
            record = {"event": event, "source_sha256": row["raw_sha256"],
                      "retrieved_at_utc": row["retrieved_at_utc"]}
            if eid in events and events[eid]["event"] != event:
                raise ValueError("CONFLICTING_PROVIDER_EVENT:" + eid)
            events[eid] = record
        selected.append(row)
    if seen != dates:
        raise ValueError("ADJACENT_SCHEDULE_CAPTURE_INCOMPLETE:" + league)
    return selected, events


def make_nhl_current(operational, day, dest, cutoff=None):
    from scripts.nhl_history_applicability import load_scope, SCOPE_SHA256
    load_scope(SCOPE)
    if digest(SCOPE) != SCOPE_SHA256:
        raise ValueError("NHL_SCOPE_PIN")
    rows, events = captured_schedule(operational, "nhl", day, cutoff)
    dest.mkdir(parents=True, exist_ok=False)
    for row in rows:
        path = Path(row["raw_path"])
        source = inside(operational, path)
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(source, target)
    write(dest / "events.json", {"nhl": events})
    write(dest / "report.json", {"season_scope_sha256": SCOPE_SHA256, "timezone": PACIFIC.key,
          "covered_dates": [day], "pending_requests": 0, "sources": rows,
          "source_capture_only": True, "derived_from_operational_manifest_sha256": digest(operational / "manifest.json"),
          "action_authority": False})
    write(dest / "manifest.json", manifest(dest))
    verify_manifest(dest)


def verify_draws(card_path, day, league, expected_model=None):
    """Check retained native draw arrays, exact hashes, clocks and authority; no new forecasts."""
    import numpy as np
    card_path = Path(card_path)
    card = read(card_path)
    if (card["card_date"] != day or card["league"].lower() != league or card["actionable"] is not False
            or card["authority"] != "SHADOW_ONLY" or card["simulation_count"] != DRAWS):
        raise ValueError("CARD_IDENTITY_OR_AUTHORITY")
    if card["pit_provenance"]["source_attestation"]["status"] != "RAW_BYTES_AND_RECEIPTS_VERIFIED":
        raise ValueError("SOURCE_ATTESTATION_REQUIRED")
    generated_at = instant(card["generated_at_utc"])
    cutoff = instant(card["as_of_utc"])
    if cutoff > generated_at:
        raise ValueError("CARD_CLOCK_ORDER")
    rows = [r for r in card["forecasts"] if r.get("forecast_status") == "FORECAST_GENERATED"]
    if len({r["event_id"] for r in rows}) != len(rows) or len(rows) != card["forecast_count"]:
        raise ValueError("FORECAST_COUNT_OR_DUPLICATE")
    verified, late = [], []
    for r in rows:
        if (r.get("action_authority") is not False or r.get("dose") != 0
                or not r.get("model_id") or not r.get("input_snapshot_hash") or not r.get("model_state_config_hash")):
            raise ValueError("ROW_AUTHORITY_OR_BINDING")
        if expected_model and r["model_id"] != expected_model:
            raise ValueError("MODEL_ID_MISMATCH")
        # Paths persisted on the producing runner are not portable. Resolve from
        # the event-bound directory name below the downloaded card's draws root.
        folder_name = Path(r["simulation"]["draw_directory"]).name
        event_name = r["event_id"].replace(":", "_")
        if folder_name not in {event_name, event_name + ".semantic-v2"}:
            raise ValueError("DRAW_DIRECTORY_IDENTITY")
        folder = card_path.parent / "draws" / folder_name
        files = verify_manifest(folder)
        if "winner_draws.npy" not in files:
            raise ValueError("WINNER_DRAWS_REQUIRED")
        arrays = {p.stem: np.load(p, allow_pickle=False) for p in folder.glob("*.npy")}
        if not arrays or any(len(a) != DRAWS for a in arrays.values()):
            raise ValueError("DRAW_COUNT_MISMATCH")
        winner = arrays["winner_draws"]
        if winner.shape != (DRAWS,) or not np.isin(winner, [0, 1]).all():
            raise ValueError("WINNER_DRAW_DOMAIN")
        home = float(winner.mean())
        if r["model_winner"] not in {r["home_team"], r["away_team"]}:
            raise ValueError("WINNER_IDENTITY")
        probability = home if r["model_winner"] == r["home_team"] else 1 - home
        if abs(probability - float(r["sim_p"])) > 1e-12:
            raise ValueError("DRAW_PROBABILITY_MISMATCH")
        if league != "nfl" and r.get("identity_semantics") != "market_blind_numeric.v2":
            raise ValueError("MARKET_BLIND_IDENTITY_REQUIRED")
        if generated_at >= instant(r["start_time_utc"]):
            late.append(r["event_id"])
        else:
            verified.append(r["event_id"])
    return {"card_sha256": digest(card_path), "native_scheduled": card["scheduled_game_count"],
            "native_forecast_count": len(rows), "verified_event_ids": verified, "late_event_ids": late,
            "retained_winner_draws_verified": len(rows) * DRAWS, "native_incidents": len(card["incidents"]),
            "missing_pregame_ids": card.get("coverage_breach_event_ids", []),
            "pit_status": card["pit_provenance"]["pit_status"],
            "qualification": "NO_PICK", "action_authority": False}


def native_status(result):
    if result["native_incidents"] or result["missing_pregame_ids"] or result["late_event_ids"]:
        return "PARTIAL_NATIVE_OUTPUT"
    if not result["verified_event_ids"]:
        return "NO_NATIVE_FORECAST_CENSUS_NOT_ESTABLISHED"
    return "VERIFIED_NATIVE_OUTPUT"


def shared(league, day, inputs, output):
    operational, recovery = inputs / "operational", inputs / "recovery"
    packages = output / "packages"
    if league == "cfb":
        verify_manifest(recovery)
        run("prepare_cfb_current", "--source", recovery, "--output", packages)
        roots = [recovery]
    else:
        verify_manifest(operational)
        # Verify adjacent-day census before fitting. Native NBA uses the full
        # operational window for source-bound provider-season inference.
        captured_schedule(operational, league, day)
        history = output / "history"
        if league == "nba":
            current = operational
            run("capture_team_histories", "--league", league, "--nba-current-bundle", current, "--output", history)
            extra = ["--nba-acquisition-scope", history / "nba_acquisition_scope.json"]
        elif league == "nhl":
            current = output / "current"
            make_nhl_current(operational, day, current)
            run("capture_team_histories", "--league", league, "--season-scope", SCOPE, "--output", history)
            extra = ["--season-scope", SCOPE]
        else:
            raise ValueError("UNSUPPORTED_SHARED_LEAGUE")
        verify_manifest(history)
        run("prepare_initial_baselines", "--league", league, "--history", history, "--current", current,
            "--output", packages, *extra)
        roots = [current, history]
    pkg = read(packages / league / "package.json")
    env = dict(os.environ, SPORTS_RESEARCH_PACKAGE_DIR=str(packages), SPORTS_SOURCE_BUNDLES=json.dumps([str(p.resolve()) for p in roots]))
    flags = ["--initial-research-baselines"] if league in {"nba", "nhl"} else []
    card_dir = output / "card"
    run("generate_card_force", "--league", league, "--date", day, "--as-of-utc", now().isoformat(),
        "--simulations", DRAWS, "--identity-semantics", "market_blind_numeric.v2", "--output-dir", card_dir, *flags, env=env)
    result = verify_draws(card_dir / "diagnostic_card.json", day, league, pkg["model_id"])
    result.update(status=native_status(result), card="card/diagnostic_card.json",
                  package_sha256=digest(packages / league / "package.json"), scope="NATIVE_PACKAGE_SCOPE_ONLY",
                  market_comparison="NOT_PERFORMED", independent_full_slate_census_verified=False)
    return result


def cbb(day, checkout, output):
    code = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
    if code != CBB_COMMIT:
        raise ValueError("CBB_COMMIT_PIN_MISMATCH")
    recon, inputs, native = output / "reconciliation", output / "inputs", output / "native"
    for script in ("capture_cbb_daily", "cbb_shadow", "verify_cbb_shadow"):
        run(script, "--help", cwd=checkout)
    rc = run("capture_cbb_daily", "--date", day, "--output", recon, cwd=checkout, allowed=(0, 2))
    coverage = read(recon / "coverage.json")
    if coverage.get("status") == "BLOCKED" or not (recon / "manifest.json").is_file():
        raise ValueError("CBB_RECONCILIATION_BLOCKED:" + str(coverage.get("reason")))
    run("cbb_shadow", "capture", "--date", day, "--inputs", inputs, cwd=checkout)
    run("cbb_shadow", "card", "--date", day, "--inputs", inputs, "--output", native,
        "--reconciliation-inputs", recon, "--reconciliation-manifest-sha256", digest(recon / "manifest.json"), cwd=checkout)
    path = native / "card.json"
    run("verify_cbb_shadow", "--inputs", inputs, "--run", native, "--out", output / "verification.json",
        "--card-sha256", digest(path), "--reconciliation-inputs", recon, cwd=checkout)
    card, verified = read(path), read(output / "verification.json")
    rows = [r for r in card["forecasts"] if r["forecast_status"] == "FORECAST_GENERATED"]
    if (card["action_authority"] is not False or card["canonical_registration"] is not False
            or verified["status"] != "PASS" or verified["forecasts_replayed"] != len(rows)
            or verified["paired_draws_replayed"] != len(rows) * DRAWS):
        raise ValueError("CBB_VERIFICATION_CONTRACT")
    if any(instant(card["generated_at_utc"]) >= instant(r["start_time_utc"]) for r in rows):
        raise ValueError("CBB_WRITER_AFTER_START")
    status = "VERIFIED_NATIVE_OUTPUT" if rc == 0 and rows else "PARTIAL_NATIVE_OUTPUT"
    return {"status": status, "card": "native/card.json", "card_sha256": digest(path),
            "native_scheduled": card["scheduled"], "native_forecast_count": len(rows),
            "verified_event_ids": [r["event_id"] for r in rows], "retained_paired_draws_verified": len(rows) * DRAWS,
            "cbb_code_sha": code, "reconciliation_status": coverage["status"],
            "held_or_excluded_rows": card["scheduled"] - len(rows),
            "scope": "CBB_MENS_D1_NATIVE_RECONCILIATION", "market_comparison": "NOT_PERFORMED"}


def nfl_source(root, filename, expected_url):
    report = read(root / "report.json")
    receipts = read(root / "nfl/receipt.json")
    if receipts != report["nfl_sources"]:
        raise ValueError("NFL_RECEIPT_LIST_MISMATCH")
    matches = [r for r in receipts if r["filename"] == filename]
    if len(matches) != 1:
        raise ValueError("NFL_RECEIPT_REQUIRED:" + filename)
    r = matches[0]
    path = inside(root, "nfl/" + filename)
    if r["status"] != "captured" or r["source_url"] != expected_url or digest(path) != r["sha256"]:
        raise ValueError("NFL_SOURCE_INVALID:" + filename)
    fetched = instant(r["retrieved_at_utc"])
    if instant(r["requested_at_utc"]) > fetched or not dt.timedelta(0) <= now() - fetched <= dt.timedelta(hours=6):
        raise ValueError("NFL_SOURCE_CLOCK:" + filename)
    return path, r


def nfl_schedule(root, day):
    from models.nfl.contextual import weekly_state as ws
    schedule_path, rec = nfl_source(root, "games.csv", NFL_URL)
    date = dt.date.fromisoformat(day)
    season = date.year if date.month >= 7 else date.year - 1
    source = ws.capture(schedule_path, rec)
    frame = ws._schedule(source, season, now().isoformat())
    games = []
    for r in frame.to_dict("records"):
        if not isinstance(r["gameday"], str) or not isinstance(r["gametime"], str):
            raise ValueError("NFL_SCHEDULE_TIME_UNKNOWN")
        t = dt.datetime.fromisoformat(r["gameday"] + "T" + r["gametime"]).replace(tzinfo=EASTERN)
        if t.astimezone(PACIFIC).date() == date:
            games.append({"event_id": r["game_id"], "week": int(r["week"]), "gameday": r["gameday"],
                          "start_time_utc": t.astimezone(UTC).isoformat(),
                          "home_team": r["home_team"], "away_team": r["away_team"]})
    provider_receipts, events = captured_schedule(root, "nfl", day)
    scoped = [v["event"] for v in events.values()
              if instant(v["event"]["date"]).astimezone(PACIFIC).date() == date]
    # Any postseason/preseason event is outside the native weekly contract.
    if any(e["season"]["type"] != 2 for e in scoped):
        raise ValueError("NFL_PROVIDER_OUTSIDE_REGULAR_SEASON_SCOPE")
    if Counter(instant(e["date"]) for e in scoped) != Counter(instant(g["start_time_utc"]) for g in games):
        raise ValueError("NFL_PROVIDER_KICKOFF_CENSUS_CONFLICT")
    return games, rec, source, season, {"nflverse_full_regular_season_verified": True,
            "provider_kickoff_census_match": True, "provider_event_identity_crosswalk_verified": False,
            "schedule_source_sha256": rec["sha256"], "provider_source_sha256": [r["raw_sha256"] for r in provider_receipts]}


def restore_state(output, expected_id, seed):
    pin = os.getenv("NFL_WEEKLY_STATE_SEED_SHA256", "")
    artifact_id = os.getenv("NFL_STATE_ARTIFACT_ID", "")
    archive_sha = os.getenv("NFL_STATE_ARCHIVE_SHA256", "")
    if not (SHA.fullmatch(expected_id or "") and SHA.fullmatch(seed or "") and seed == pin
            and re.fullmatch(r"[1-9]\d*", artifact_id) and SHA.fullmatch(archive_sha)):
        raise ValueError("BLOCKED_NFL_STATE:INDEPENDENT_SEED_STATE_AND_ARCHIVE_PINS_REQUIRED")
    archive = output / "state-input.zip"
    repo = os.environ["GITHUB_REPOSITORY"]
    with archive.open("xb") as f:
        subprocess.run(["gh", "api", "repos/" + repo + "/actions/artifacts/" + artifact_id + "/zip"],
                       stdout=f, check=True)
    if digest(archive) != archive_sha:
        raise ValueError("NFL_ARCHIVE_DIGEST_MISMATCH")
    restored = output / "restored"
    restored.mkdir()
    with ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist()) > 8 * 1024**3:
            raise ValueError("NFL_ARCHIVE_SIZE_LIMIT")
        seen = set()
        for i in z.infolist():
            name = Path(i.filename)
            target = (restored / name).resolve()
            if name.is_absolute() or not target.is_relative_to(restored) or stat.S_ISLNK(i.external_attr >> 16):
                raise ValueError("NFL_ARCHIVE_PATH_UNSAFE")
            if target in seen:
                raise ValueError("NFL_ARCHIVE_DUPLICATE_PATH")
            seen.add(target)
            if i.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(i) as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
    store = restored / "state"
    if (store / "HEAD").read_text().strip() != expected_id:
        raise ValueError("NFL_STATE_HEAD_MISMATCH")
    shutil.copytree(store, output / "state")
    return output / "state", restored, {"artifact_id": artifact_id, "archive_sha256": archive_sha}


def retain_nfl_schedule(state, source_root, dest):
    """A future state restore must keep the exact schedule receipt, not refresh its clock."""
    from scripts.source_attestation import attest_sources
    receipt = state["schedule_source"]["receipt"]
    fetch = {"source": receipt["source_url"], "sha256": receipt["sha256"],
             "fetched_at_utc": receipt["retrieved_at_utc"]}
    attest_sources([fetch], [source_root], now().isoformat())
    dest.mkdir()
    (dest / "nfl").mkdir()
    path = dest / "nfl/games.csv"
    path.write_bytes(state["schedule_source"]["text"].encode("utf-8"))
    if digest(path) != receipt["sha256"]:
        raise ValueError("STATE_SCHEDULE_BYTE_MISMATCH")
    write(dest / "report.json", {"nfl_sources": [{**receipt, "filename": "games.csv", "status": "captured"}],
                                  "sources": [], "action_authority": False})
    write(dest / "manifest.json", manifest(dest))
    verify_manifest(dest)


def nfl(day, inputs, output):
    from models.nfl.contextual import weekly_state as ws
    from models.nfl.contextual.model import load_artifact
    root = inputs / "operational"
    verify_manifest(root)
    games, schedule_receipt, schedule, season, census = nfl_schedule(root, day)
    write(output / "schedule.json", {"date": day, "games": games, **census})
    if not games:
        return {"status": "NO_SCHEDULED_EVENTS_IN_RECONCILED_SCOPE", "native_scheduled": 0,
                "native_forecast_count": 0, "scope": "NFL_REGULAR_SEASON", **census}
    future = [g for g in games if instant(g["start_time_utc"]) > now()]
    if not future:
        return {"status": "POST_START_NO_NEW_FORECAST", "native_scheduled": len(games), "native_forecast_count": 0}
    if {g["gameday"] for g in future} != {day} or len({g["week"] for g in future}) != 1:
        raise ValueError("NFL_PACIFIC_EASTERN_OR_WEEK_SCOPE_CONFLICT")
    state_id, seed = os.getenv("NFL_STATE_ID", ""), os.getenv("NFL_SEED_ID", "")
    store, restored, archive = restore_state(output, state_id, seed)
    model = load_artifact(ROOT / "data/nfl/contextual_v1/model_packed.json")
    state = ws.load_verified(store, state_id, model, now().isoformat(), seed)
    week = future[0]["week"]
    if state["season"] != season or state["completed_week"] > week - 1:
        raise ValueError("NFL_STATE_WRONG_SEASON_OR_WEEK")
    source_root = restored / "state_source"
    if state["completed_week"] < week - 1:
        filename = "play_by_play_" + str(season) + ".csv"
        url = "https://github.com/nflverse/nflverse-data/releases/download/pbp/" + filename
        pbp_path, pbp_receipt = nfl_source(root, filename, url)
        pbp = ws.capture(pbp_path, pbp_receipt)
        for w in range(state["completed_week"] + 1, week):
            state_id = ws.advance(store, state_id, seed, model, schedule, pbp, w, now().isoformat())
        state = ws.load_verified(store, state_id, model, now().isoformat(), seed)
        source_root = root
    else:
        verify_manifest(source_root)
    retain_nfl_schedule(state, source_root, output / "state_source")
    write(output / "state_binding.json", {"state_id": state_id, "seed_id": seed, "completed_week": state["completed_week"], **archive})
    # Native code refuses a stale schedule or incomplete state; no fallback to archived default package.
    run("run_fresh_nfl_research", "--store", store, "--state-id", state_id, "--seed-id", seed,
        "--source-bundles", output / "state_source", "--date", day, "--output", output / "card", "--simulations", DRAWS)
    path = output / "card/diagnostic_card.json"
    native = read(output / "card/fresh_run_receipt.json")
    if native.get("forecast_consumption_verified") is not True or native.get("state_id") != state_id:
        raise ValueError("NFL_NATIVE_STATE_CONSUMPTION_UNVERIFIED")
    result = verify_draws(path, day, "nfl")
    expected = {g["event_id"] for g in future}
    if set(result["verified_event_ids"]) != expected:
        result["missing_pregame_ids"] = sorted(expected - set(result["verified_event_ids"]))
    result.update(status=native_status(result), card="card/diagnostic_card.json", state_id=state_id,
                  native_schedule_census=len(games), scope="NFL_REGULAR_SEASON_SELECTED_QB", **census)
    return result


def finalize(day, inputs, output):
    output.mkdir(parents=True, exist_ok=False)
    stages = {}
    board = []
    run_id, attempt = os.getenv("GITHUB_RUN_ID"), os.getenv("GITHUB_RUN_ATTEMPT")
    for label in ("raw-operational", "raw-recovery", *LEAGUES):
        name = f"evidence-{label}-{day}-{run_id}-{attempt}"
        root = inputs / name
        try:
            verify_manifest(root, "stage_manifest.json")
            r = read(root / "stage_receipt.json")
            if (r["stage"] != label or r["date"] != day or r["run_id"] != run_id
                    or r["run_attempt"] != attempt or r["action_authority"] is not False):
                raise ValueError("STAGE_RECEIPT_IDENTITY")
            stages[label] = {**r, "artifact": name, "stage_manifest_sha256": digest(root / "stage_manifest.json")}
            if r.get("card"):
                path = inside(root, r["card"])
                if digest(path) != r["card_sha256"]:
                    raise ValueError("CARD_READBACK_HASH")
                # Copy only exact native card bytes, not a second copy of huge raw/draw artifacts.
                native = output / "native" / label / path.name
                native.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, native)
                card = read(path)
                eligible = set(r.get("verified_event_ids", []))
                for row in card["forecasts"]:
                    p = row.get("model_p")
                    sim = row.get("sim_p")
                    winner = row.get("model_winner")
                    margin = row.get("projected_margin")
                    total = row.get("projected_total")
                    if label == "cbb" and row.get("p_home_win") is not None:
                        home = row["p_home_win"] >= .5
                        p = row["p_home_win"] if home else 1 - row["p_home_win"]
                        sim = row["p_home_win_sim"] if home else 1 - row["p_home_win_sim"]
                        winner = row["home_team"] if home else row["away_team"]
                        margin = row.get("home_margin")
                        margin = margin if home else -margin
                        total = row.get("total")
                    verified = row["event_id"] in eligible
                    board.append({"league": label, "event_id": row["event_id"], "away": row.get("away_team"),
                                  "home": row.get("home_team"), "start_utc": row.get("start_time_utc"),
                                  "native_status": row.get("forecast_status"), "verified_pregame": verified,
                                  "model_id": row.get("model_id"), "winner": winner if verified else None,
                                  "winner_probability": p if verified else None,
                                  "simulated_winner_probability": sim if verified else None,
                                  "projected_winner_margin": margin if verified else None,
                                  "projected_total": total if verified else None,
                                  "market_status": "NO_AUTHENTIC_EXACT_LINE_COMPARISON", "qualification": "NO_PICK"})
        except Exception as e:
            stages[label] = {"status": "MISSING_OR_INVALID_ARTIFACT", "artifact": name, "reason": str(e)}
    for league in ("mlb", "wnba", "mls"):
        stages[league] = {"status": "OUT_OF_SCOPE_THIS_FIVE_LEAGUE_WORKFLOW"}
    jobs = json.loads(os.getenv("JOB_RESULTS", "{}"))
    accepted = {"ACQUIRED", "VERIFIED_NATIVE_OUTPUT", "NO_SCHEDULED_EVENTS_IN_RECONCILED_SCOPE"}
    failed = [k for k in ("raw-operational", "raw-recovery", *LEAGUES) if stages[k]["status"] not in accepted]
    failed_jobs = [k for k, v in jobs.items() if v.get("result") != "success"]
    status = "NATIVE_EVIDENCE_AVAILABLE_FULL_SLATE_NOT_CERTIFIED"
    if failed or failed_jobs or os.getenv("DOWNLOAD_OUTCOME") != "success":
        status = "PARTIAL_OR_BLOCKED"
    report = {"schema": "sports.daily_card_aggregate.v1", "date": day, "status": status,
              "job_results": {k: v.get("result") for k, v in jobs.items()}, "stage_results": stages,
              "failed_stages": failed, "failed_jobs": failed_jobs, "board_rows": len(board),
              "full_slate_certified": False, "durable_archive_verified": False,
              "official_release": "RED/HOLD", "action_authority": False, "official_units": 0, "qualification": "NO_PICK"}
    write(output / "report.json", report)
    write(output / "board.json", board)
    fields = ["league", "event_id", "away", "home", "start_utc", "native_status", "verified_pregame",
              "model_id", "winner", "winner_probability", "simulated_winner_probability",
              "projected_winner_margin", "projected_total", "market_status", "qualification"]
    with (output / "board.csv").open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(board)
    cells = lambda xs: "".join("<td>" + html.escape(str(x if x is not None else "")) + "</td>" for x in xs)
    rows = "".join("<tr>" + cells([r[k] for k in fields]) + "</tr>" for r in board)
    (output / "board.html").write_text("<!doctype html><meta charset=utf-8><title>Research daily card</title>"
        "<h1>" + html.escape(day + " — " + status) + "</h1><p>RED/HOLD; NO_PICK; ACTION OFF; 0 units. "
        "Native forecast scope only; no verified full slate or market comparison.</p><table><thead><tr>" +
        cells(fields) + "</tr></thead><tbody>" + rows + "</tbody></table>", encoding="utf-8")
    write(output / "manifest.json", manifest(output))
    print(json.dumps({"status": status, "failed_stages": failed, "failed_jobs": failed_jobs, "board_rows": len(board)}))
    return 2 if status == "PARTIAL_OR_BLOCKED" else 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest="command", required=True)
    subs.add_parser("validate")
    for command in ("acquire", "shared", "cbb", "nfl", "finalize"):
        s = subs.add_parser(command)
        s.add_argument("--date", required=True)
        s.add_argument("--output", type=Path, required=True)
        if command == "acquire":
            s.add_argument("--kind", choices=("operational", "recovery"), required=True)
        if command == "shared":
            s.add_argument("--league", choices=("cfb", "nba", "nhl"), required=True)
        if command in {"shared", "nfl", "finalize"}:
            s.add_argument("--inputs", type=Path, required=True)
        if command == "cbb":
            s.add_argument("--checkout", type=Path, required=True)
    a = p.parse_args()
    if a.command == "validate":
        requested = os.getenv("REQUESTED_DATE", "")
        if not requested and os.getenv("GITHUB_EVENT_NAME") == "pull_request":
            requested = now().astimezone(PACIFIC).date().isoformat()
        day = validate_date(requested).isoformat()
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write("date=" + day + "\nattempt=" + os.environ["GITHUB_RUN_ATTEMPT"] + "\n")
        return 0
    if a.command == "finalize":
        # Finalization may occur after midnight; validation belongs to the
        # original acquisition clock, not a new forecast.
        return finalize(a.date, a.inputs.resolve(), a.output.resolve())
    if a.command == "acquire":
        return stage(a.output, a.date, "raw-" + a.kind, lambda out: acquire(a.kind, a.date, out))
    if a.command == "shared":
        return stage(a.output, a.date, a.league, lambda out: shared(a.league, a.date, a.inputs.resolve(), out))
    if a.command == "cbb":
        return stage(a.output, a.date, "cbb", lambda out: cbb(a.date, a.checkout.resolve(), out))
    return stage(a.output, a.date, "nfl", lambda out: nfl(a.date, a.inputs.resolve(), out))


if __name__ == "__main__":
    raise SystemExit(main())
