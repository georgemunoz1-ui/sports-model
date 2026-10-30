#!/usr/bin/env python3
"""Acquire and validate a successor MLB research packet; never forecast or clear release."""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.recovery_capture import capture, save_json, ROUTES
from scripts.prepare_mlb_official_current import prepare
from models.current import common
from pipelines.cards.adapters import mlb

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def census(payload, day):
    dates = [d for d in payload["dates"] if d["date"] == day]
    games = [g for d in dates for g in d["games"]]
    if payload["totalGames"] != len(games) or any(d["totalGames"] != len(d["games"]) for d in dates):
        raise ValueError("DAILY_CENSUS_MISMATCH")
    if len({g["gamePk"] for g in games}) != len(games):
        raise ValueError("DUPLICATE_GAME")
    return games

def pbp_check(game, feed):
    gid = str(game["gamePk"])
    if str(feed.get("gamePk")) != gid or feed["gameData"]["status"]["abstractGameState"] != "Final":
        raise ValueError("PBP_IDENTITY_OR_NOT_FINAL:" + gid)
    live = feed["liveData"]
    plays = live["plays"]["allPlays"]
    if not plays or not all(p.get("about", {}).get("isComplete") for p in plays):
        raise ValueError("PBP_INCOMPLETE_PLAY:" + gid)
    indices = [p["about"]["atBatIndex"] for p in plays]
    if indices != list(range(len(plays))):
        raise ValueError("PBP_SEQUENCE_GAP:" + gid)
    lines = live["linescore"]["teams"]
    for side in ("home", "away"):
        if lines[side]["runs"] != game["teams"][side]["score"]:
            raise ValueError("PBP_FINAL_SCORE_MISMATCH:" + gid)
    last = plays[-1]["result"]
    if last["homeScore"] != lines["home"]["runs"] or last["awayScore"] != lines["away"]["runs"]:
        raise ValueError("PBP_LAST_PLAY_SCORE_MISMATCH:" + gid)
    return {"game_id": gid, "plays": len(plays), "status": "FINAL_SEQUENCE_AND_SCORE_RECONCILED",
            "scope": "PRIOR_DAY_ONLY; NOT_FULL_SEASON_PBP_OR_PREDICTIVE_VALIDATION"}

def fetch_many(root, specs):
    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(lambda spec: capture(root, spec), specs))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    day = dt.date.fromisoformat(a.date)
    if day != now.astimezone(ZoneInfo("America/Los_Angeles")).date():
        raise ValueError("REQUEST_MUST_MATCH_CURRENT_PACIFIC_DATE")
    # Existing builder keys its official-date filter to Eastern time. Do not
    # silently cross that boundary with an incompatible request.
    if day != now.astimezone(ZoneInfo("America/New_York")).date():
        raise ValueError("OFFICIAL_DATE_BOUNDARY_REQUIRES_EXPLICIT_BUILDER_SUPPORT")
    prior = day - dt.timedelta(days=1)
    a.output.mkdir(parents=True, exist_ok=False)
    raw = a.output / "sources"
    raw.mkdir()
    protected = ["docs/releases/official_release_blocker_register.json",
                 "data/governance/health_triage_sessions.jsonl",
                 "data/mlb/current_v1/runtime.json", "data/model_selection/defaults_v1.json",
                 "state.json"]
    before = {name: sha(ROOT / name) for name in protected}
    base = "https://statsapi.mlb.com/api"
    specs = [
        ("mlb","official_season", f"{base}/v1/schedule?sportId=1&startDate={day.year}-03-01&endDate={day}&gameType=R",1),
        ("mlb","official_schedule", f"{base}/v1/schedule?sportId=1&date={day}&hydrate=probablePitcher,linescore,venue",1),
        ("mlb","official_schedule", f"{base}/v1/schedule?sportId=1&date={prior}&hydrate=probablePitcher,linescore,venue",1)]
    for league, route in ROUTES.items():
        for d in (prior, day):
            specs.append((league,"provider_schedule",
                f"https://site.api.espn.com/apis/site/v2/sports/{route}/scoreboard?dates={d:%Y%m%d}&limit=1000",2))
    results = fetch_many(raw, specs)
    official = results[:3]
    if any(r["status"] != "CAPTURED" for r, _ in official):
        save_json(raw/"failure.json", {"sources":[r for r,_ in results]})
        raise ValueError("OFFICIAL_SCHEDULE_CAPTURE_FAILED")
    games = census(official[1][1], str(day))
    previous = census(official[2][1], str(prior))
    finals = [g for g in previous if g["status"]["abstractGameState"] == "Final"
              and g["status"]["detailedState"] not in ("Postponed","Cancelled","Suspended")]
    details = {}
    for g in games:
        for side in ("home", "away"):
            pid = g["teams"][side].get("probablePitcher", {}).get("id")
            if pid:
                u = f"{base}/v1/people/{pid}/stats?stats=gameLog&group=pitching&season={day.year}"
                details[u] = ("mlb","starter_game_logs",u,1)
        u = f"{base}/v1.1/game/{g['gamePk']}/feed/live"
        details[u] = ("mlb","current_event_feed",u,1)
    for g in finals:
        u = f"{base}/v1.1/game/{g['gamePk']}/feed/live"
        details[u] = ("mlb","prior_day_pbp",u,1)
    results += fetch_many(raw, list(details.values()))
    save_json(raw/"report.json", {"created_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
        "requested_date":str(day), "sources":[r for r,_ in results], "action_authority":False})
    save_json(raw/"manifest.json", {str(f.relative_to(raw)):sha(f) for f in raw.rglob("*") if f.is_file()})
    feeds = {str(j["gamePk"]):j for r,j in results if j and r["kind"] in ("prior_day_pbp","current_event_feed")}
    checks, errors = [], []
    for g in finals:
        try:
            checks.append(pbp_check(g, feeds[str(g["gamePk"])]))
        except (KeyError, ValueError) as exc:
            errors.append(str(exc))
    cutoff = dt.datetime.now(dt.timezone.utc)
    dispositions = []
    for g in games:
        started = common.utc(g["gameDate"]) <= cutoff
        status = g["status"]["detailedState"]
        if status in ("Postponed","Cancelled","Suspended"):
            disposition = status.upper()
        elif started or g["status"]["abstractGameState"] != "Preview":
            disposition = "POST_START"
        else:
            disposition = "MANUAL_PRE_CUTOFF_REVIEW_REQUIRED"
        feed = feeds.get(str(g["gamePk"]), {})
        gd = feed.get("gameData", {})
        teams = {}
        for side in ("home","away"):
            team = g["teams"][side]
            teams[side] = {"team":team["team"]["name"],
                "probable_starter":team.get("probablePitcher"),
                "starter_confirmed_at_utc":None, "lineup_confirmed_at_utc":None}
        dispositions.append({"event_id":"MLB:"+str(g["gamePk"]), "start_time_utc":g["gameDate"],
            "disposition":disposition, "teams":teams, "weather_source_available":bool(gd.get("weather")),
            "weather_consumed_by_selected_model":False, "injury_effective_at_utc":None,
            "injury_retrieved_at_utc":None, "event_forecast_cutoff":None})
    package_check = {}
    try:
        pkg = prepare(raw, a.output/"packages")
        os.environ["SPORTS_RESEARCH_PACKAGE_DIR"] = str((a.output/"packages").resolve())
        loaded, h = common.load("mlb")
        check_time = dt.datetime.now(dt.timezone.utc).isoformat()
        common.current(loaded, check_time)
        scheduled = mlb.load_schedule(str(day), check_time)
        context = mlb.build_context(scheduled, check_time)
        package_check = {"status":"CURRENT_PACKAGE_CONTEXT_EXECUTED", "sha256":h,
            "events":len(scheduled), "model_lineage":pkg["model_lineage"],
            "context_model_id":context["package"]["model_id"], "checked_at_utc":check_time}
    except Exception as exc:
        package_check = {"status":"FAILED", "error":type(exc).__name__+":"+str(exc)}
        errors.append(package_check["error"])
    after = {name:sha(ROOT/name) for name in protected}
    if before != after:
        raise ValueError("PROTECTED_ARTIFACT_CHANGED")
    provider_counts = [{"league":r["league"], "url":r["url"], "events":len(j.get("events",[])) if j else None}
                       for r,j in results if r["kind"]=="provider_schedule"]
    report = {"schema":"mlb.readiness.no_forecast.v1",
        "writer_clock_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
        "code_commit":os.environ.get("GITHUB_SHA"), "requested_date":str(day),
        "official_schedule_events":len(games), "prior_day_finals":len(finals),
        "prior_day_nonfinal_dispositions":[{"game_id":g["gamePk"],"status":g["status"]["detailedState"]}
                                         for g in previous if g not in finals],
        "first_start_utc":min((g["gameDate"] for g in games),default=None),
        "source_requests":len(results), "source_failures":[{"kind":r["kind"],"url":r["url"],"error":r.get("error")}
                                                         for r,_ in results if r["status"]!="CAPTURED"],
        "prior_day_pbp_checks":checks, "errors":errors, "package":package_check,
        "event_dispositions":dispositions, "provider_schedules":provider_counts,
        "protected_artifacts_unchanged":True, "protected_sha256":before,
        "manual_validation_complete":False, "official_release_eligible":False,
        "forecast_execution":"NOT_RUN", "action_authority":"OFF","dose":0.0,
        "remaining":["EVENT_SPECIFIC_CONFIRMED_STARTER_AND_LINEUP_TIMESTAMPS",
                     "INJURY_EFFECTIVE_AND_RETRIEVAL_TIMES","BULLPEN_AVAILABILITY",
                     "VENUE_WEATHER_REVIEW","FINAL_DECLARED_CUTOFF","STANDING_RELEASE_OBLIGATIONS"]}
    save_json(a.output/"readiness.json",report)
    save_json(a.output/"manifest.json",{str(f.relative_to(a.output)):sha(f) for f in a.output.rglob("*") if f.is_file()})
    print(json.dumps({k:v for k,v in report.items() if k not in ("event_dispositions","protected_sha256","provider_schedules")},indent=2))
    return 1 if errors or report["source_failures"] else 0

if __name__ == "__main__":
    raise SystemExit(main())
