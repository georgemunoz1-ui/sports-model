"""A selected-model CFB pregame path; archive and canonical writer are separate steps.

This module never promotes models, fabricates acquisition, or grants authority.
It reconciles the exact binary/report contract consumed by prepare_cfb_current,
then executes that existing builder and the existing shared-card command.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = ZoneInfo("America/Los_Angeles")
SCHEMA = "sports.daily_research.v1"


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def instant(value):
    stamp = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return stamp.astimezone(dt.timezone.utc)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def _fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "sports-model-daily-research/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.status != 200 or response.url != url:
            raise ValueError("UNEXPECTED_SOURCE_RESPONSE")
        raw = response.read(80_000_001)
    if len(raw) > 80_000_000:
        raise ValueError("SOURCE_SIZE_LIMIT")
    return raw


def _capture(root, spec, fetcher):
    relative, url, pin, kind = spec
    record = {"name": relative.removeprefix("binary/"), "url": url, "path": relative,
              "kind": kind, "requested_at_utc": utcnow().isoformat(),
              "provider_observed_at_utc": None, "expected_sha256": pin,
              "provider_authenticity": "HTTPS_PROVIDER_ENDPOINT_NOT_SIGNED",
              "historical_pregame_eligibility": False}
    try:
        raw = fetcher(url)
        record["retrieved_at_utc"] = utcnow().isoformat()
        sha = hashlib.sha256(raw).hexdigest()
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(raw)
        record.update(sha256=sha, byte_count=len(raw))
        if pin and pin != sha:
            raise ValueError("PIN_MISMATCH")
        if kind == "espn_fbs_schedule":
            payload = json.loads(raw)
            if not isinstance(payload.get("events"), list):
                raise ValueError("SCHEDULE_EVENTS_REQUIRED")
        record["status"] = "CAPTURED"
    except (ValueError, KeyError, TypeError, OSError) as exc:
        record.update(status="FAILED", error=str(exc), retrieved_at_utc=utcnow().isoformat())
    return record


def capture_cfb(root, date, *, fetcher=None, next_slate=False):
    """Preserve exact raw bytes and receipts, including all failed acquisitions."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    day = dt.date.fromisoformat(date)
    pinned = json.loads((ROOT / "data/cfb/model/CFB_V2_ACQUISITION_MANIFEST.json").read_text())
    commit = pinned["source"]["commit"]
    specs = [("binary/" + f["path"],
              f"https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/{commit}/" + f["path"],
              f["sha256"], "pinned_cfb_history") for f in pinned["files"]]
    specs.append(("binary/cfb_current.parquet",
                  f"https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/schedules/parquet/cfb_schedules_{day.year}.parquet",
                  None, "cfb_current"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda spec: _capture(root, spec, fetcher or _fetch), specs))
    requested_date = date
    discovery_error = None
    if next_slate and all(r["status"] == "CAPTURED" for r in rows):
        try:
            import pandas as pd
            frame = pd.read_parquet(root / "binary/cfb_current.parquet")
            required = {"start_date", "completed", "home_division", "away_division", "week"}
            if not required <= set(frame.columns):
                raise ValueError("CURRENT_SCHEDULE_COLUMNS_MISSING:" + ",".join(sorted(required - set(frame.columns))))
            now = utcnow()
            candidates = [instant(r["start_date"]).astimezone(TZ).date() for r in frame.to_dict("records")
                          if not r["completed"] and r["home_division"] == "fbs" and r["away_division"] == "fbs"
                          and int(r["week"]) >= 2 and instant(r["start_date"]) > now
                          and day <= instant(r["start_date"]).astimezone(TZ).date() <= day + dt.timedelta(days=6)]
            if candidates:
                day = min(candidates)
                date = day.isoformat()
        except (ValueError, KeyError, TypeError, OSError) as exc:
            # Parsing failure must not erase already captured raw bytes/receipts.
            discovery_error = type(exc).__name__ + ":" + str(exc)
    # ESPN's scoreboard accepts individual dates here; retain adjacent days for timezone reconciliation.
    for offset in (-1, 0, 1):
        schedule_day = day + dt.timedelta(days=offset)
        spec = (f"raw/espn_schedule_{schedule_day:%Y%m%d}.json",
                f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates={schedule_day:%Y%m%d}&groups=80&limit=1000",
                None, "espn_fbs_schedule")
        rows.append(_capture(root, spec, fetcher or _fetch))
    report = {"schema": "sports.daily_cfb_capture.v1", "created_at_utc": utcnow().isoformat(),
              "slate_date": date, "requested_slate_date": requested_date, "next_slate_discovery": next_slate,
              "discovery_error": discovery_error,
              "timezone": str(TZ), "source_capture_only": True,
              "binary_sources": [r for r in rows if r["kind"] != "espn_fbs_schedule"],
              "sources": [r for r in rows if r["kind"] == "espn_fbs_schedule"],
              "action_authority": False}
    write(root / "report.json", report)
    # This is an explicit model-specific contract, not refresh_all_sports' text-extract schema.
    acquisition = {"schema": "sports.daily_cfb_acquisition.v1", "consumer": "scripts/prepare_cfb_current.py",
                   "report_sha256": digest(root / "report.json"), "slate_date": date,
                   "sources": [{"path": r["path"], "source": r["url"], "sha256": r.get("sha256"),
                                "retrieved_at": r["retrieved_at_utc"], "source_available_at": None,
                                "status": r["status"], "parser": r["kind"]} for r in rows],
                   "provider_observation_time_policy": "UNKNOWN_NOT_BACKFILLED",
                   "action_authority": False}
    write(root / "acquisition.json", acquisition)
    write(root / "manifest.json", {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob("*")) if p.is_file()})
    failures = [r for r in rows if r["status"] != "CAPTURED"]
    if failures:
        raise ValueError("ACQUISITION_FAILED:" + ",".join(r["path"] for r in failures))
    if discovery_error:
        raise ValueError("NEXT_SLATE_DISCOVERY_FAILED:" + discovery_error)
    return report


def schedule_payload(root):
    root = Path(root)
    report = json.loads((root / "report.json").read_text())
    events = {}
    for receipt in report["sources"]:
        payload = json.loads((root / receipt["path"]).read_text())
        if not isinstance(payload.get("events"), list):
            raise ValueError("SCHEDULE_EVENTS_REQUIRED")
        for event in payload["events"]:
            eid = str(event["id"])
            if eid in events and events[eid] != event:
                raise ValueError("CONFLICTING_ADJACENT_SCHEDULE_EVENT")
            events[eid] = event
    return {"events": list(events.values())}


def verify_acquisition(root):
    """Bind each consumed report entry to raw bytes and the explicit contract."""
    from scripts.verify_nfl_weekly_sources import manifest
    root = Path(root)
    manifest(root, "manifest.json")
    acquisition = json.loads((root / "acquisition.json").read_text())
    report = json.loads((root / "report.json").read_text())
    if acquisition.get("schema") != "sports.daily_cfb_acquisition.v1" or acquisition["report_sha256"] != digest(root / "report.json"):
        raise ValueError("ACQUISITION_REPORT_MISMATCH")
    rows = report["binary_sources"] + report["sources"]
    if len(rows) != len(acquisition["sources"]) or len({r["path"] for r in rows}) != len(rows):
        raise ValueError("ACQUISITION_SOURCE_SET_MISMATCH")
    index = {r["path"]: r for r in acquisition["sources"]}
    for row in rows:
        path = root / row["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("SOURCE_PATH_OUTSIDE_BUNDLE")
        contract = index[row["path"]]
        if row["status"] != "CAPTURED" or contract["status"] != "CAPTURED" or digest(path) != row["sha256"]:
            raise ValueError("SOURCE_BYTES_OR_STATUS_MISMATCH")
        if (contract["sha256"], contract["source"], contract["retrieved_at"], contract["parser"]) != (row["sha256"], row["url"], row["retrieved_at_utc"], row["kind"]):
            raise ValueError("ACQUISITION_SOURCE_BINDING_MISMATCH")
        if not instant(row["requested_at_utc"]) <= instant(row["retrieved_at_utc"]) <= utcnow():
            raise ValueError("CAPTURE_CHRONOLOGY_INVALID")
    return rows


def reconcile_schedule(current_rows, payload, date, now):
    """Exact provider ID, side and start matching; no fuzzy joins or empty fallback."""
    if not isinstance(payload.get("events"), list):
        raise ValueError("SCHEDULE_EVENTS_REQUIRED")
    seen, provider = set(), {}
    for e in payload["events"]:
        eid = str(e["id"])
        if eid in seen:
            raise ValueError("DUPLICATE_SCHEDULE_EVENT")
        seen.add(eid)
        if instant(e["date"]).astimezone(TZ).date().isoformat() != date:
            continue
        competitions = e["competitions"]
        if len(competitions) != 1:
            raise ValueError("AMBIGUOUS_SCHEDULE_EVENT")
        comp = competitions[0]
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        if set(sides) != {"home", "away"} or len(comp["competitors"]) != 2:
            raise ValueError("SCHEDULE_TEAM_IDENTITIES_REQUIRED")
        status = comp.get("status", e.get("status", {})).get("type", {})
        if not isinstance(status, dict) or not isinstance(status.get("completed"), bool) or not status.get("state") or not status.get("name"):
            raise ValueError("PROVIDER_EVENT_STATUS_REQUIRED:" + eid)
        provider[eid] = {"event": e, "sides": sides, "status": status}
    current, coverage = {}, []
    for r in current_rows:
        if int(r["season"]) != int(date[:4]):
            raise ValueError("CURRENT_SOURCE_SEASON_MISMATCH")
        eid = str(int(r["game_id"]))
        if eid in current:
            raise ValueError("DUPLICATE_CURRENT_EVENT")
        current[eid] = r
    # ESPN group 80 covers FBS schedules, including FBS/FCS. Missing classification blocks.
    for eid, source in provider.items():
        if eid not in current:
            raise ValueError("SCHEDULE_EVENT_UNCLASSIFIED:" + eid)
        row = current[eid]
        if any(row.get(side + "_division") not in {"fbs", "fcs"} for side in ("home", "away")):
            raise ValueError("SCHEDULE_DIVISION_UNVERIFIED:" + eid)
        if instant(row["start_date"]) != instant(source["event"]["date"]):
            raise ValueError("SCHEDULE_START_CONFLICT:" + eid)
        for side in ("home", "away"):
            team = source["sides"][side]["team"]
            if row[side + "_team"] not in {team.get("location"), team.get("displayName"), team.get("shortDisplayName")}:
                raise ValueError("SCHEDULE_TEAM_CONFLICT:" + eid + ":" + side)
    for eid, row in current.items():
        if instant(row["start_date"]).astimezone(TZ).date().isoformat() != date:
            continue
        selected = row["home_division"] == "fbs" and row["away_division"] == "fbs"
        if selected and eid not in provider:
            raise ValueError("SCHEDULE_EVENT_MISSING_FROM_PROVIDER:" + eid)
        status = "NOT_SUPPORTED_FBS_VS_FCS_OR_LOWER"
        if selected:
            if row.get("start_time_tbd") is True:
                raise ValueError("SCHEDULE_START_TIME_TBD:" + eid)
            status = "POST_START" if instant(row["start_date"]) <= now else "PREGAME"
            event_status = provider[eid]["status"]
            if status == "PREGAME" and (event_status["name"], event_status["state"], event_status["completed"]) != ("STATUS_SCHEDULED", "pre", False):
                raise ValueError("FUTURE_EVENT_NOT_VERIFIED_SCHEDULED:" + eid + ":" + str(event_status.get("name")))
            if int(row["week"]) < 2:
                status = "NOT_SUPPORTED_WEEK1_REQUIRES_SEPARATE_ARM"
            if bool(row["completed"]) and instant(row["start_date"]) > now:
                raise ValueError("FUTURE_FINAL")
        coverage.append({"event_id": "CFB:" + eid, "home_team": row["home_team"], "away_team": row["away_team"],
                         "start_time_utc": instant(row["start_date"]).isoformat(), "week": int(row["week"]),
                         "status": status, "selected_scope": selected,
                         "provider_schedule_matched": eid in provider})
    return sorted(coverage, key=lambda r: (r["start_time_utc"], r["event_id"]))


def verify_card(card, coverage, package, cutoff, now):
    from scripts.canonical_forecasts import card_rows, firewall
    firewall(card)
    if card.get("official_release", False) is not False or card.get("wagering_authority", "OFF") != "OFF":
        raise ValueError("RESEARCH_AUTHORITY_REQUIRED")
    expected = {r["event_id"] for r in coverage if r["status"] == "PREGAME" and instant(r["start_time_utc"]) > now}
    generated = {r["event_id"] for r in card["forecasts"] if r["forecast_status"] == "FORECAST_GENERATED"}
    if generated != expected or card.get("coverage_breach_event_ids") or card.get("incidents"):
        raise ValueError("CARD_COVERAGE_INCOMPLETE")
    if card["requested_as_of_utc"] != cutoff or card["league"] != "CFB":
        raise ValueError("CARD_IDENTITY_MISMATCH")
    if package["model_id"] != "cfb.fbs.elo_form_logit_ridge.v1_0.shadow":
        raise ValueError("UNEXPECTED_SELECTED_MODEL")
    if card["pit_provenance"]["source_attestation"]["status"] != "RAW_BYTES_AND_RECEIPTS_VERIFIED":
        raise ValueError("SOURCE_RETENTION_UNVERIFIED")
    schedule_index = {r["event_id"]: r for r in coverage}
    for row in card["forecasts"]:
        if row["forecast_status"] != "FORECAST_GENERATED":
            continue
        event = schedule_index[row["event_id"]]
        if any(row[k] != event[k] for k in ("home_team", "away_team")) or instant(row["start_time_utc"]) != instant(event["start_time_utc"]):
            raise ValueError("FORECAST_SCHEDULE_BINDING_MISMATCH")
        if row["model_id"] != package["model_id"] or row["diagnostics"]["package_sha256"] != package["_file_sha256"]:
            raise ValueError("FORECAST_PACKAGE_BINDING_MISMATCH")
        if row.get("dose") != 0:
            raise ValueError("NONZERO_DOSE")
    if generated:
        card_rows(card, now.isoformat())  # Same actual writer gates, no registration here.
    return generated


def run(date, output, simulations=100000, next_slate=False):
    from scripts.daily_research_archive import seal_directory
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = utcnow()
    record = {"schema": SCHEMA, "started_at_utc": started.isoformat(), "slate_date": date, "timezone": str(TZ),
              "league": "CFB", "forecast_count": 0, "registered_count": 0, "status": "FAILED",
              "registration_status": "NOT_ATTEMPTED_REQUIRES_REMOTE_ARCHIVE_READBACK",
              "publication_eligibility": "INELIGIBLE", "predictive_validation": "NOT_ASSESSED",
              "wagering_authority": "OFF", "official_release": False, "action_authority": False,
              "market_overlay_enabled": False, "steps": [], "forward_forecast_run": False}
    try:
        day = dt.date.fromisoformat(date)
        today = started.astimezone(TZ).date()
        if not today <= day <= today + dt.timedelta(days=6):
            raise ValueError("CURRENT_OR_NEXT_SIX_DAYS_REQUIRED_NO_BACKDATE")
        if type(simulations) is not int or not 1000 <= simulations <= 1000000:
            raise ValueError("SIMULATION_COUNT_RANGE")
        record["code_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        retained = ["pipelines/daily_research.py", "scripts/run_daily_research.py", "scripts/prepare_cfb_current.py",
                    "scripts/generate_card_force.py", "scripts/canonical_forecasts.py", "scripts/daily_research_archive.py",
                    "harness/cfb_v1_port.py", "models/current/common.py", "models/current/linear.py", "models/current/cfb.py",
                    "pipelines/cards/adapters/cfb.py", "pipelines/cards/selection.py", "requirements-daily-research.lock",
                    "data/model_selection/defaults_v1.json", "data/cfb/model/CFB_V2_ACQUISITION_MANIFEST.json"]
        record["code_pins"] = {}
        for relative in retained:
            source = ROOT / relative
            destination = output / "code" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            raw = source.read_bytes()
            with destination.open("xb") as f:
                f.write(raw)
            record["code_pins"][relative] = hashlib.sha256(raw).hexdigest()
        declared = dict(line.split("==", 1) for line in (ROOT / "requirements-daily-research.lock").read_text().splitlines()
                        if line.strip() and not line.startswith("#"))
        actual = {}
        for name in declared:
            try:
                actual[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                actual[name] = None
        record["runtime"] = {"python": sys.version, "platform": platform.platform(), "packages": actual,
                             "declared_lock_versions": declared, "matches_dependency_lock": actual == declared,
                             "runner_image": os.environ.get("ImageVersion"),
                             "github_run_id": os.environ.get("GITHUB_RUN_ID"), "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT")}
        capture_report = capture_cfb(output / "source", date, next_slate=next_slate)
        date = capture_report["slate_date"]
        record["slate_date"] = date
        record["requested_slate_date"] = day.isoformat()
        record["next_slate_discovery"] = next_slate
        verify_acquisition(output / "source")
        import pandas as pd
        frame = pd.read_parquet(output / "source/binary/cfb_current.parquet")
        payload = schedule_payload(output / "source")
        coverage = reconcile_schedule(frame.to_dict("records"), payload, date, utcnow())
        write(output / "coverage.json", {"schema": "sports.daily_cfb_coverage.v1", "slate_date": date, "events": coverage,
                                          "scope": "SELECTED_WEEK2_PLUS_FBS_VS_FBS", "action_authority": False})
        record["scheduled_count"] = len(coverage)
        pregame = [r for r in coverage if r["status"] == "PREGAME"]
        if not pregame:
            record.update(status="NO_GAMES_VERIFIED" if not coverage else "NO_SELECTED_PREGAME_EVENTS", forecast_count=0)
            write(output / "daily_card.json", {**record, "events": coverage})
            return record
        # Existing builder freezes state before the earliest pending week; incomplete earlier weeks block.
        pending = frame[(~frame.completed) & (pd.to_datetime(frame.start_date, utc=True) > pd.Timestamp(utcnow())) &
                        (pd.to_datetime(frame.start_date, utc=True) < pd.Timestamp(utcnow() + dt.timedelta(days=7)))]
        first_week = int(pending.week.min())
        prior = frame[(frame.week < first_week) & (frame.home_division == "fbs") & (frame.away_division == "fbs")]
        if not bool(prior.completed.all()) or bool(prior.home_points.isna().any()) or bool(prior.away_points.isna().any()):
            raise ValueError("PRIOR_WEEK_CURRENT_SOURCE_INCOMPLETE")
        commands = [[sys.executable, "scripts/prepare_cfb_current.py", "--source", str(output / "source"), "--output", str(output / "packages")]]
        env = os.environ.copy()
        # Do not inherit ad-hoc alternative-model or market environment switches.
        env.pop("SPORTS_INITIAL_BASELINES", None)
        env["SPORTS_RESEARCH_PACKAGE_DIR"] = str(output / "packages")
        env["SPORTS_SOURCE_BUNDLES"] = json.dumps([str(output / "source")])
        for command in commands:
            with (output / "prepare.log").open("x") as log:
                result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            record["steps"].append({"command": command, "returncode": result.returncode})
            if result.returncode:
                raise ValueError("SELECTED_PACKAGE_PREPARATION_FAILED")
        package_path = output / "packages/cfb/package.json"
        package = json.loads(package_path.read_text())
        package["_file_sha256"] = digest(package_path)
        cutoff = utcnow().isoformat()
        command = [sys.executable, "scripts/generate_card_force.py", "--date", date, "--league", "cfb", "--as-of-utc", cutoff,
                   "--simulations", str(simulations), "--output-dir", str(output / "card")]
        with (output / "forecast.log").open("x") as log:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        record["steps"].append({"command": command, "returncode": result.returncode})
        if result.returncode:
            raise ValueError("SHARED_CARD_EXECUTION_INCOMPLETE")
        card = json.loads((output / "card/diagnostic_card.json").read_text())
        generated = verify_card(card, coverage, package, cutoff, utcnow())
        record.update(status="FORECASTS_AWAITING_VERIFIED_ARCHIVE_AND_REGISTRATION", forecast_count=len(generated),
                      card_sha256=digest(output / "card/diagnostic_card.json"), package_sha256=package["_file_sha256"],
                      source_manifest_sha256=digest(output / "source/manifest.json"), cutoff_utc=cutoff,
                      forward_forecast_run=bool(generated))
        forecasts = {r["event_id"]: r for r in card["forecasts"]}
        write(output / "daily_card.json", {**record, "events": [{**r, "forecast": forecasts.get(r["event_id"])} for r in coverage],
                                             "products": {"winner": "SELECTED_RESEARCH", "cover": "UNAVAILABLE_NO_QUALIFIED_EXACT_LINE_DISTRIBUTION", "total": "UNSUPPORTED_SELECTED_PARENT"}})
        return record
    except Exception as exc:
        record.update(status="FAILED", error_type=type(exc).__name__, error=str(exc))
        return record
    finally:
        record["completed_at_utc"] = utcnow().isoformat()
        write(output / "run.json", record)
        seal_directory(output)
