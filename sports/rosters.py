"""Source-bound personnel inventory. Membership is not game availability or impact.

This layer never changes a parent's prediction. A roster-aware product must also
have a fitted transform and an inference trace; none is inferred from a roster feed.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "sports.roster_bundle.v1"
TTL_SECONDS = 6 * 3600
ROUTES = {"nba": "basketball/nba", "wnba": "basketball/wnba",
          "nfl": "football/nfl", "cfb": "football/college-football",
          "mlb": "baseball/mlb", "nhl": "hockey/nhl", "mls": "soccer/usa.1"}
REQUIREMENTS = {
    "nba": ["rotation_minutes", "usage_sharing", "offense_defense_impact"],
    "wnba": ["rotation_minutes", "usage_sharing", "offense_defense_impact"],
    "nfl": ["starting_qb", "final_inactives", "position_group_snaps", "replacement_impact"],
    "cfb": ["starting_qb", "depth_chart", "transfer_identity", "position_group_snaps", "replacement_impact"],
    "mlb": ["starting_pitchers", "batting_order", "bullpen_availability", "lineup_impact"],
    "nhl": ["starting_goalie", "skater_time_on_ice", "special_teams", "replacement_impact"],
    "mls": ["starting_xi", "goalkeeper", "suspensions", "substitution_minutes", "replacement_impact"],
}


def fail(code):
    raise ValueError("ROSTER_" + code)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def utc(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        fail("TIMESTAMP_INVALID")
    if stamp.tzinfo is None:
        fail("TIMEZONE_REQUIRED")
    return stamp.astimezone(timezone.utc)


def read_source(root, receipt):
    if receipt.get("status") != "CAPTURED" or receipt.get("http_status") != 200:
        fail("SOURCE_NOT_CAPTURED")
    path = (Path(root) / receipt["raw_path"]).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        fail("SOURCE_PATH_OUTSIDE_BUNDLE")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt["raw_sha256"]:
        fail("SOURCE_HASH_MISMATCH")
    return json.loads(raw)


def team_directory(data):
    rows = [r["team"] for s in data.get("sports", []) for l in s.get("leagues", []) for r in l.get("teams", [])]
    ids = [str(r.get("id", "")) for r in rows]
    if not ids or not all(ids) or len(set(ids)) != len(ids) or len(ids) >= 1000:
        fail("TEAM_CENSUS_INVALID")
    return rows


def normalize_team(sport, team, data, receipt):
    if sport not in ROUTES or str(data.get("team", {}).get("id")) != str(team["id"]):
        fail("TEAM_IDENTITY_MISMATCH")
    if not isinstance(data.get("season"), dict) or not data["season"].get("year"):
        fail("SEASON_REQUIRED")
    expected = f"https://site.api.espn.com/apis/site/v2/sports/{ROUTES[sport]}/teams/{team['id']}/roster?limit=1000"
    if receipt.get("url") != expected or receipt.get("final_url", expected) != expected:
        fail("SOURCE_IDENTITY_MISMATCH")
    players = []
    for group in data.get("athletes", []):
        for a in group.get("items", [group]):
            if not a.get("id") or not a.get("displayName"):
                fail("PLAYER_IDENTITY_REQUIRED")
            injury = a.get("injuries", [])
            if not isinstance(injury, list):
                fail("INJURY_SCHEMA")
            players.append({"player_id": f"espn:{sport}:{a['id']}", "name": a["displayName"],
                            "position": (a.get("position") or {}).get("abbreviation"),
                            "roster_status": (a.get("status") or {}).get("name", "UNKNOWN"),
                            "reported_injuries": [{"status": i.get("status", "UNKNOWN"), "reported_at_utc": i.get("date")} for i in injury],
                            "event_availability": "UNCONFIRMED", "expected_exposure": None})
    ids = [a["player_id"] for a in players]
    if len(ids) >= 1000:
        fail("RESPONSE_AT_LIMIT_PAGINATION_REQUIRED")
    if not ids or len(set(ids)) != len(ids):
        fail("EMPTY_OR_DUPLICATE_PLAYERS")
    return {"team_id": f"espn:{sport}:{team['id']}", "provider_team_id": str(team["id"]),
            "team_name": team["displayName"],
            "aliases": sorted({str(team[k]) for k in ("displayName", "shortDisplayName", "location", "abbreviation") if team.get(k)}),
            "season": data["season"], "provider_timestamp_utc": data.get("timestamp"),
            "players": sorted(players, key=lambda r: r["player_id"]),
            "source": receipt, "injury_completeness": "UNVERIFIED", "lineup_confirmation": "UNCONFIRMED",
            "membership_scope": "PROVIDER_LISTED_ROSTER_NOT_GAME_ACTIVE_LIST"}


def seal(bundle):
    result = {k: v for k, v in bundle.items() if k != "bundle_sha256"}
    return dict(result, bundle_sha256=digest(result))


def league_counts(league):
    owners = {}
    for row in league['teams']:
        if row['status'] == 'PARSED':
            for p in row['snapshot']['players']:
                owners[p['player_id']] = owners.get(p['player_id'], 0) + 1
    return {'requested': len(league['requested_team_ids']),
            'parsed': sum(r['status'] == 'PARSED' for r in league['teams']),
            'failed': sum(r['status'] != 'PARSED' for r in league['teams']),
            'distinct_players': len(owners), 'conflicting_players': sum(n > 1 for n in owners.values())}


def load_bundle(path):
    """Rebuild every normalized row from retained source bytes, not caller labels."""
    path = Path(path)
    bundle = json.loads(path.read_bytes())
    if bundle.get("schema") != SCHEMA or bundle.get("bundle_sha256") != seal(bundle)["bundle_sha256"]:
        fail("BUNDLE_HASH_OR_SCHEMA")
    if bundle.get("action_authority") is not False:
        fail("RESEARCH_ONLY")
    for sport, league in bundle["sports"].items():
        if sport not in ROUTES:
            fail("SPORT_UNKNOWN")
        if league.get("census_status") != "CAPTURED":
            if league.get("teams") or league.get("requested_team_ids"):
                fail("CENSUS_UNAVAILABLE")
            continue
        receipt = league["census_source"]
        expected = f"https://site.api.espn.com/apis/site/v2/sports/{ROUTES[sport]}/teams?limit=1000"
        if receipt.get("url") != expected or receipt.get("final_url", expected) != expected:
            fail("CENSUS_SOURCE_IDENTITY")
        directory = {str(t["id"]): t for t in team_directory(read_source(path.parent, receipt))}
        requested = league["requested_team_ids"]
        if len(set(requested)) != len(requested) or not set(requested) <= set(directory):
            fail("REQUESTED_TEAM_IDENTITY")
        if league["scope"] == "ALL_PROVIDER_TEAMS" and set(requested) != set(directory):
            fail("CENSUS_TRUNCATED")
        if league["scope"] == "FBS_SCHEDULE_ID_AND_NAME_MATCH":
            import pandas as pd
            evidence = league["scope_evidence"]
            file = (path.parent / evidence["path"]).resolve()
            if sport != 'cfb' or not file.is_relative_to(path.parent.resolve()) or hashlib.sha256(file.read_bytes()).hexdigest() != evidence["sha256"]:
                fail("FBS_SCOPE_HASH")
            frame = pd.read_parquet(file)
            if frame.season.nunique() != 1 or int(frame.season.iloc[0]) != evidence["season"]:
                fail("FBS_SCOPE_SEASON")
            expected_ids = set()
            for side in ('home', 'away'):
                for r in frame[frame[f'{side}_division'] == 'fbs'].to_dict('records'):
                    tid = str(r[f'{side}_id'])
                    t = directory.get(tid, {})
                    if r[f'{side}_team'] not in [t.get(k) for k in ('displayName', 'location', 'shortDisplayName', 'nickname', 'abbreviation')]:
                        fail("FBS_SCOPE_ID_NAME")
                    expected_ids.add(tid)
            if set(requested) != expected_ids:
                fail("FBS_SCOPE_INCOMPLETE")
        elif league["scope"] != "ALL_PROVIDER_TEAMS":
            fail("SCOPE_UNKNOWN")
        rows = league["teams"]
        if [r["provider_team_id"] for r in rows] != requested:
            fail("TEAM_LEDGER_INCOMPLETE")
        owners = {}
        for row in rows:
            if row["status"] != "PARSED":
                if not row.get("reason"):
                    fail("FAILURE_REASON_REQUIRED")
                continue
            snapshot = row["snapshot"]
            rebuilt = normalize_team(sport, directory[row["provider_team_id"]], read_source(path.parent, snapshot["source"]), snapshot["source"])
            if snapshot != rebuilt:
                fail("NORMALIZATION_MISMATCH")
            for p in snapshot["players"]:
                owners.setdefault(p["player_id"], []).append(snapshot["team_id"])
        conflicts = {k: sorted(v) for k, v in owners.items() if len(v) > 1}
        if league.get("membership_conflicts") != conflicts:
            fail("MEMBERSHIP_CONFLICT_LEDGER")
        if 'counts' in league and league['counts'] != league_counts(league):
            fail("COUNTS_MISMATCH")
    return bundle


def current_snapshot(bundle, sport, event, side, cutoff):
    league = bundle["sports"].get(sport)
    if not league or league.get("census_status") != "CAPTURED":
        fail("CENSUS_UNAVAILABLE")
    cutoff = utc(cutoff)
    if cutoff >= utc(event["start_time_utc"]):
        fail("POST_START")
    # Numeric IDs from different providers are never treated as interchangeable.
    explicit = event.get(f"{side}_roster_team_id")
    name = str(event[f"{side}_team"])
    matches = []
    for row in league["teams"]:
        s = row.get("snapshot")
        if s and (s["team_id"] == explicit if explicit else name in s["aliases"]):
            matches.append(s)
    if len(matches) != 1:
        fail("TEAM_UNRESOLVED:" + side)
    s = matches[0]
    if explicit and name not in s['aliases']:
        fail("EVENT_ID_NAME_MISMATCH")
    if any(s["team_id"] in owners for owners in league["membership_conflicts"].values()):
        fail("MULTIPLE_TEAM_MEMBERSHIP")
    if event.get("season") is not None and int(event["season"]) != int(s["season"]["year"]):
        fail("SEASON_MISMATCH")
    if league.get('scope_evidence', {}).get('season', s['season']['year']) != s['season']['year']:
        fail("SCOPE_SEASON_MISMATCH")
    for stamp in (league["census_source"]["retrieved_at_utc"], s["source"]["retrieved_at_utc"], s["provider_timestamp_utc"]):
        age = (cutoff - utc(stamp)).total_seconds()
        if not 0 <= age <= TTL_SECONDS:
            fail("STALE_OR_FUTURE_SOURCE")
    for p in s["players"]:
        for i in p["reported_injuries"]:
            if i["reported_at_utc"] and utc(i["reported_at_utc"]) > cutoff:
                fail("FUTURE_INJURY_REPORT")
    return s


def assess(sport, event, cutoff, bundle=None):
    """Every forecast gets an explicit gap report, even without a bundle."""
    if sport not in ROUTES:
        fail("SPORT_UNKNOWN")
    report = {"schema": "sports.roster_coverage.v1", "sport": sport, "event_id": str(event["event_id"]),
              "cutoff_utc": cutoff, "bundle_sha256": bundle.get("bundle_sha256") if bundle else None,
              "status": "ACQUIRE_REQUIRED", "teams": {}, "reasons": [],
              "roster_inputs_numerically_used": False, "roster_aware_forecast_eligible": False,
              "unmet_model_requirements": REQUIREMENTS[sport], "action_authority": False}
    if utc(cutoff) >= utc(event['start_time_utc']):
        report['status'] = 'BLOCKED'
        report['reasons'].append('ROSTER_POST_START')
    elif not bundle:
        report["reasons"].append("ROSTER_BUNDLE_NOT_SUPPLIED")
    else:
        for side in ("home", "away"):
            try:
                s = current_snapshot(bundle, sport, event, side, cutoff)
                report["teams"][side] = {"team_id": s["team_id"], "snapshot_sha256": digest(s),
                                         "source_sha256": s["source"]["raw_sha256"], "player_count": len(s["players"]),
                                         "reported_injury_count": sum(bool(p["reported_injuries"]) for p in s["players"]),
                                         "availability": "UNCONFIRMED", "lifecycle": "AVAILABLE"}
            except (ValueError, KeyError, TypeError) as exc:
                report["reasons"].append(f"{side}:{exc}")
        report["status"] = "AVAILABLE_NOT_USED" if len(report["teams"]) == 2 else "BLOCKED"
    report["reasons"].append("FULL_ROSTER_IMPACT_TRANSFORM_NOT_FITTED")
    return report


def attach(raw, sport, event, cutoff, bundle=None, require_roster_aware=False):
    report = assess(sport, event, cutoff, bundle)
    if require_roster_aware and not report["roster_aware_forecast_eligible"]:
        fail("AWARE_FORECAST_UNAVAILABLE:" + ";".join(report["reasons"]))
    result = dict(raw)
    result["roster_coverage"] = report
    result["warnings"] = list(raw.get("warnings", [])) + ["ROSTER:" + report["status"], "FULL_ROSTER_IMPACTS_NOT_APPLIED"]
    # Retain exact existing NFL selected-arm trace instead of promoting other arms.
    diagnostic = raw.get("diagnostics") or raw
    report["existing_parent_personnel_evidence"] = diagnostic.get("capability_report") if sport == "nfl" else None
    report["existing_parent_scope"] = {"nfl": "SELECTED_ARM_TRACE_ONLY", "mlb": "STARTING_PITCHERS_ONLY"}.get(sport, "TEAM_HISTORY_ONLY")
    report["forecast_binding"] = {"model_id": raw.get("model_id"),
                                  "input_snapshot_hash": raw.get("input_snapshot_hash") or (digest(raw["features"]) if "features" in raw else None),
                                  "model_state_config_hash": raw.get("model_state_config_hash") or raw.get("model_artifact_sha256"),
                                  "forecast_identity": raw.get("identity")}
    report["coverage_sha256"] = digest(report)
    return result


def membership_delta(previous, current):
    """Observed membership changes, not claimed transaction dates or causal effects."""
    if previous["team_id"] != current["team_id"]:
        fail("DELTA_TEAM_MISMATCH")
    if utc(previous["source"]["retrieved_at_utc"]) >= utc(current["source"]["retrieved_at_utc"]):
        fail("DELTA_CHRONOLOGY")
    before = {r["player_id"] for r in previous["players"]}
    after = {r["player_id"] for r in current["players"]}
    return {"added": sorted(after-before), "removed": sorted(before-after), "retained": sorted(before & after),
            "previous_sha256": digest(previous), "current_sha256": digest(current), "effective_transaction_times_known": False}


def validate_rotation(snapshot, allocation, *, sport, unit, total, group=None):
    """Validate a conditional workload scenario; do not invent playing chances.

Basketball: minutes; football: separately budgeted offensive/defensive snaps;
    NHL: skater and goalie minutes separately; MLB: PA or outs; MLS: minutes.
Totals other than basketball must be supplied by the explicit game scenario.
"""
    units = {"nba": {"minutes"}, "wnba": {"minutes"}, "nfl": {"snaps"}, "cfb": {"snaps"},
             "nhl": {"minutes"}, "mlb": {"plate_appearances", "outs"}, "mls": {"minutes"}}
    if sport not in units or unit not in units[sport] or not snapshot["team_id"].startswith(f"espn:{sport}:"):
        fail("EXPOSURE_UNIT_OR_SPORT")
    if sport in {"nfl", "cfb", "nhl"} and group not in ({"offense", "defense", "special_teams"} if sport in {"nfl", "cfb"} else {"skaters", "goalies"}):
        fail("EXPOSURE_GROUP_REQUIRED")
    if not math.isfinite(total) or total <= 0 or (sport in {"nba", "wnba"} and total != {"nba": 240, "wnba": 200}[sport]):
        fail("EXPOSURE_BUDGET")
    players = {p["player_id"]: p for p in snapshot["players"]}
    seen = set()
    for row in allocation:
        pid, value = row["player_id"], row["exposure"]
        if pid not in players or pid in seen:
            fail("ROTATION_MEMBERSHIP")
        seen.add(pid)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            fail("EXPOSURE_INVALID")
        if sport in {"nba", "wnba"} and value > {"nba": 48, "wnba": 40}[sport]:
            fail("PLAYER_EXPOSURE_EXCEEDS_GAME")
        if (sport == 'nhl' and value > 60) or (sport == 'mls' and value > 90):
            fail("PLAYER_EXPOSURE_EXCEEDS_GAME")
        if unit in {'snaps', 'plate_appearances', 'outs'} and value != int(value):
            fail("COUNT_EXPOSURE_MUST_BE_INTEGER")
        if sport == 'nhl' and value and (players[pid]['position'] == 'G') != (group == 'goalies'):
            fail("GOALIE_SKATER_GROUP_MISMATCH")
        statuses = [i["status"].lower() for i in players[pid]["reported_injuries"]]
        unavailable_roster = players[pid]['roster_status'].lower() in {'injured reserve', 'injured', 'suspended', 'inactive', 'injured list'}
        if value and ("out" in statuses or "suspended" in statuses or row.get("scenario_status") == "OUT" or unavailable_roster):
            fail("UNAVAILABLE_PLAYER_ALLOCATED")
        if value and row.get("scenario_status") not in {"ASSUMED_AVAILABLE", "CONFIRMED_AVAILABLE"}:
            fail("SCENARIO_AVAILABILITY_REQUIRED")
        if row.get("scenario_status") == "CONFIRMED_AVAILABLE":
            fail("EVENT_BOUND_CONFIRMATION_NOT_IMPLEMENTED")
    if not math.isclose(sum(r["exposure"] for r in allocation), total, rel_tol=0, abs_tol=1e-8):
        fail("EXPOSURE_NOT_CONSERVED")
    return {"snapshot_sha256": digest(snapshot), "allocation": allocation, "unit": unit, "group": group,
            "total": total, "scenario_probability": None, "status": "CONDITIONAL_SCENARIO_ONLY", "numerically_used": False}
