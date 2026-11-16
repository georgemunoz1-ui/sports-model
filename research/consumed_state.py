"""Append-only shadow freeze and pregame recheck. Numerical parents are read-only."""
import argparse
import fcntl
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
import tempfile
from contextlib import contextmanager

from pipelines.cards.personnel_review import _fixtures
from research.personnel_events import ROLES, load_observations, review_fixture
from sports.rosters import digest, utc

CHANNELS = ("results", "rosters", "schedule", "quotes")
MATERIAL = {"QB1_CHANGE", "STARTER_CHANGE", "TRADE", "IR_PLACEMENT", "TOP_CONTRIBUTOR_INJURY"}


def file_hash(raw):
    return hashlib.sha256(raw).hexdigest()


def source_json(root, ref):
    path = (root / ref["path"]).resolve()
    if not path.is_relative_to(root):
        raise ValueError("source outside manifest directory")
    raw = path.read_bytes()
    if file_hash(raw) != ref["sha256"]:
        raise ValueError("source digest mismatch")
    return json.loads(raw)


def index_events(rows):
    indexed = {}
    for row in rows:
        key = row["id"]
        if not isinstance(key, str) or not key or key in indexed:
            raise ValueError("missing or duplicate event identity")
        utc(row["known_at"])
        indexed[key] = row
    return indexed


def channel_state(channel, row, snapshot, evidence, cutoff, now):
    """A producer's normalized census covers one fixture/channel through the review clock."""
    source = evidence[channel]
    trace = snapshot["consumed_channels"][channel]
    if source["scope"] != row["event_id"] or source["channel"] != channel:
        raise ValueError("census fixture/channel mismatch")
    covered = utc(source["complete_through"])
    captured = utc(source["captured_at"])
    if source["complete"] is not True or not cutoff <= covered <= captured <= now:
        raise ValueError("incomplete or stale census")
    # A census certifies only its own endpoint. Report it explicitly on every receipt.
    available = index_events(source["events"])
    used = index_events(trace["events"])
    if not utc(trace["read_at"]) <= cutoff or any(utc(v["known_at"]) > utc(trace["read_at"]) for v in used.values()):
        raise ValueError("invalid consumption clock")
    if any(utc(v["known_at"]) > covered for v in available.values()):
        raise ValueError("census contains later information")
    if not used.keys() <= available.keys():
        raise ValueError("consumed events absent from retained census")
    missed = sorted(k for k, v in available.items() if used.get(k) != v)
    return {
        "last_consumed_event_utc": max((utc(v["known_at"]) for v in used.values()), default=None),
        "read_at": trace["read_at"], "complete_through": source["complete_through"],
        "census_sha256": digest(source), "consumed_events_sha256": digest(trace["events"]),
        "consumed_count": len(used), "unconsumed_ids": missed, "unconsumed_count": len(missed),
    }, available


def nfl_history(event, forecast, evidence):
    """Queryable facts from the exact native state. Never stand in for a current census."""
    trace = forecast if forecast.get("assimilation") else forecast.get("diagnostics", {})
    state, schedule = evidence.state, evidence.schedule
    used = set(state["consumed_game_ids"])
    if set(trace["assimilation"]["consumed_game_ids"]) != used:
        raise ValueError("NFL assimilation list differs from retained state")
    target = schedule[event["event_id"]]
    scored = {k for k, v in schedule.items()
              if v["season"] == target["season"] and v["game_type"] == "REG"
              and int(v["week"]) <= int(target["week"]) and v["result"] != ""}
    missing = sorted(scored - used)
    teams = {}
    for team in (event["away_team"], event["home_team"]):
        games = [schedule[k] for k in used if team in (schedule[k]["away_team"], schedule[k]["home_team"])]
        def kickoff(g):
            start = datetime.fromisoformat(g["gameday"] + "T" + g["gametime"])
            return start.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
        last = max(games, key=kickoff) if games else None
        teams[team] = {"last_consumed_game_id": last["game_id"] if last else None,
                       "last_consumed_kickoff_utc": kickoff(last).isoformat() if last else None,
                       "unconsumed_game_ids": [k for k in missing if team in (schedule[k]["away_team"], schedule[k]["home_team"])]}
    return {"state_sha256": evidence.state_sha256, "schedule_sha256": evidence.schedule_sha256,
            "observed_at": state["schedule_source"]["receipt"]["retrieved_at_utc"],
            "consumed_game_ids": sorted(used), "league_games_unconsumed": len(missing),
            "unconsumed_game_ids": missing, "teams": teams}


def evaluate(card, inventories, personnel, now, max_age=None):
    fixtures = list(_fixtures(card))
    if not fixtures:
        raise ValueError("empty card")
    seen = set()
    rows = []
    for sport, event, stamp, forecast in fixtures:
        league, eid = sport.upper(), event["event_id"]
        key = (league, eid)
        if key in seen or league not in ROLES:
            raise ValueError("duplicate or unsupported fixture")
        seen.add(key)
        cutoff, start = utc(stamp), utc(event["start_time_utc"])
        review = review_fixture(league, event, stamp, forecast=forecast, observations=personnel)
        reasons, channels = [], {}
        if not cutoff <= now < start:
            reasons.append("OUTSIDE_PREGAME_WINDOW")
        if forecast and forecast.get("action_authority", False) is not False:
            reasons.append("UNSUPPORTED_AUTHORITY")
        if not forecast:
            reasons.append("NO_FORECAST")
        issues = {"DIFFERENT_STARTER_REPORTED", "ASSIGNED_PLAYER_REPORTED_OUT", "DIFFERENT_STARTER_EXPECTED",
                  "PARTICIPANT_ID_CONFLICT", "MODEL_USE_UNVERIFIED", "PRIOR_TEAM_DEPARTURE"}
        notices = [n for n in review["observations"] if utc(n["retrieved_at_utc"]) <= now]
        if review["status"] == "CONFLICTING_REPORTS" or any(n["comparison"] in issues for n in notices):
            reasons.append("PERSONNEL_RECONCILIATION_REQUIRED")
        if any(n["source_status"] == "REVIEWED_OFFICIAL_REPORT" and n["fixture_context_verified"]
               and utc(n["published_at_utc"]) > cutoff for n in notices):
            reasons.append("PERSONNEL_REFREEZE_REQUIRED")
        snapshot = (forecast or {}).get("model_input_snapshot")
        bound = isinstance(snapshot, dict) and digest(snapshot) == forecast.get("input_snapshot_hash")
        native = None
        if league == "NFL" and review["roles"] and getattr(personnel, "state", None):
            native = nfl_history(event, forecast, personnel)
            if native["league_games_unconsumed"]:
                reasons.append("NFL_COMPLETED_RESULTS_UNCONSUMED")
        expected_fixture = {"league": league, "event_id": eid, "away_team": event.get("away_team"),
                            "home_team": event.get("home_team"), "start_utc": event["start_time_utc"],
                            "model_id": (forecast or {}).get("model_id"), "cutoff_utc": stamp}
        bound = bound and snapshot.get("consumed_fixture") == expected_fixture
        evidence = inventories.get(key, {})
        for channel in CHANNELS:
            try:
                if not bound:
                    raise ValueError("missing hash-bound input snapshot")
                block, available = channel_state(channel, event, snapshot, evidence, cutoff, now)
                source = evidence[channel]
                if source["league"] != league:
                    raise ValueError("census league mismatch")
                if max_age is None or not 0 <= (now - utc(source["complete_through"])).total_seconds() <= max_age:
                    reasons.append("CENSUS_FRESHNESS_UNVERIFIED_" + channel.upper())
                if channel == "results":
                    block["games_unconsumed"] = block["unconsumed_count"]
                    if source["population"] != "LEAGUE_SEASON_TO_DATE":
                        raise ValueError("league results census required")
                    if league == "CBB":
                        local = ZoneInfo("America/Los_Angeles")
                        if utc(source["complete_through"]).astimezone(local).date() < start.astimezone(local).date():
                            reasons.append("CBB_PREVIOUS_DAY_INCOMPLETE")
                if channel in ("results", "rosters"):
                    teams = (event["away_team"], event["home_team"])
                    if any(not isinstance(v["teams"], list) or not v["teams"] for v in available.values()):
                        raise ValueError("missing event teams")
                    block["unconsumed_by_team"] = {
                        t: [k for k in block["unconsumed_ids"] if t in available[k]["teams"]] for t in teams}
                last = block["last_consumed_event_utc"]
                block["last_consumed_event_utc"] = last.isoformat() if last else None
                channels[channel] = block
                missed = block["unconsumed_ids"]
                if channel == "results" and missed:
                    reasons.append("RESULTS_REFRESH_REQUIRED")
                if channel == "rosters":
                    teams = {str(event["away_team"]), str(event["home_team"])}
                    block["transactions_unconsumed"] = sum(available[k]["kind"] in {"TRADE", "IR_PLACEMENT"} for k in missed)
                    expected = evidence[channel]["confirmed_starters"]
                    assigned = snapshot["consumed_starters"]
                    if (set(expected) != teams or expected != assigned or
                            any(not isinstance(ids, list) or not ids or len(ids) != len(set(ids))
                                or any(not isinstance(i, str) or not i for i in ids) for ids in expected.values())):
                        reasons.append("STARTER_MISMATCH_OR_UNCONFIRMED")
                    for notice in available.values():
                        if notice["kind"] in MATERIAL and not notice.get("player_id"):
                            raise ValueError("material notice lacks player identity")
                        if notice["kind"] in {"QB1_CHANGE", "STARTER_CHANGE", "IR_PLACEMENT"}:
                            affected = teams.intersection(notice["teams"])
                            if len(affected) != 1:
                                raise ValueError("unresolved role team")
                            club = next(iter(affected))
                            if (notice["player_id"] in expected[club]) != (notice["kind"] != "IR_PLACEMENT"):
                                reasons.append("ROSTER_CENSUS_CONFLICT")
                    if any(available[k]["kind"] in MATERIAL for k in missed):
                        reasons.append("PERSONNEL_REFREEZE_REQUIRED")
                    elif missed:
                        reasons.append("UNRECONCILED_ROSTER_EVENT")
                if channel == "schedule":
                    scheduled = available[eid]
                    if missed or scheduled["status"] != "SCHEDULED" or utc(scheduled["start_utc"]) != start:
                        reasons.append("SCHEDULE_RECONCILIATION_REQUIRED")
                    for r in available.values():
                        if r["id"] != eid and r["status"] == "SCHEDULED" and cutoff < utc(r["start_utc"]) < start:
                            reasons.append("INTERVENING_FIXTURE_RECHECK_REQUIRED")
            except (KeyError, TypeError, ValueError) as err:
                reasons.append("WATERMARK_UNVERIFIED_" + channel.upper())
                channels[channel] = {"error": str(err), "unconsumed_count": None}
        rows.append({"league": league, "event_id": eid, "cutoff_utc": stamp,
                     "forecast_sha256": digest(forecast) if forecast else None, "consumed_state": channels,
                     "watermark_sha256": digest(channels), "reasons": sorted(set(reasons)),
                     "native_result_history": native, "reviewed_personnel": notices})
    return rows


def load_inventory(path):
    if path is None:
        return {}
    manifest = json.loads(path.read_bytes())
    if manifest["schema"] != "sports.fixture_channel_census.v1":
        raise ValueError("unknown census format")
    result = {}
    for item in manifest["fixtures"]:
        key = (item["league"].upper(), item["event_id"])
        if key in result:
            raise ValueError("duplicate fixture census")
        result[key] = {k: source_json(path.resolve().parent, ref) for k, ref in item["channels"].items()}
    return result


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
    try:
        tmp.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n")
        os.link(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


@contextmanager
def journal_lock(journal):
    if journal is None:
        yield
        return
    journal.mkdir(parents=True, exist_ok=True)
    with (journal / "writer.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def latest_freezes(journal):
    latest = {}
    invalidations = {}
    invalidation_reasons = {}
    for path in journal.glob("*.json"):
        raw = path.read_bytes()
        if path.stem != file_hash(raw):
            raise ValueError("journal receipt digest mismatch")
        record = json.loads(raw)
        if record["kind"] in {"SHADOW_FREEZE", "SHADOW_REFREEZE"}:
            for row in record["fixtures"]:
                key = row["league"], row["event_id"]
                value = utc(row["cutoff_utc"]), path.stem, record["parent_file_sha256"]
                if key not in latest or value > latest[key]:
                    latest[key] = value
        if record["kind"] == "STALENESS_REVIEW":
            for row in record["fixtures"]:
                pin = row.get("invalidates_freeze_sha256")
                if pin:
                    k = row["league"], row["event_id"], pin
                    timestamp = utc(record["recorded_at_utc"])
                    invalidations[k] = max(invalidations.get(k, timestamp), timestamp)
                    invalidation_reasons.setdefault(k, set()).update(row.get("reasons") or ())
    return latest, invalidations, invalidation_reasons


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["freeze", "recheck"])
    parser.add_argument("parent", type=Path)
    parser.add_argument("output", type=Path, help="New file only")
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--max-census-age-seconds", type=int, help="Approved capture lag for this shadow run")
    parser.add_argument("--personnel-events", type=Path)
    parser.add_argument("--journal", type=Path, help="Shared append-only shadow freeze directory")
    parser.add_argument("--previous", type=Path, help="Prior shadow freeze for a marked successor")
    args = parser.parse_args(argv)
    return run(args.mode, args.parent, args.output, args.inventory, args.personnel_events,
               args.max_census_age_seconds, args.previous, args.journal)


def run(mode, parent, output, inventory=None, personnel_events=None, max_age=None, previous=None, journal=None):
    with journal_lock(journal):
        return _locked_run(mode, parent, output, inventory, personnel_events, max_age, previous, journal)


def _locked_run(mode, parent, output, inventory, personnel_events, max_age, previous, journal):
    if output.exists():
        raise FileExistsError(output)
    if journal and output.resolve().is_relative_to(journal.resolve()):
        raise ValueError("export outside the authoritative journal")
    raw = parent.read_bytes()
    card = json.loads(raw)
    now = datetime.now(timezone.utc)
    errors = []
    try:
        rows = evaluate(card, load_inventory(inventory),
                        load_observations(personnel_events) if personnel_events else (), now, max_age)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        rows = []
        errors.append(str(exc))
    blocked = bool(errors) or any(r["reasons"] for r in rows)
    receipt = {"schema": "sports.consumed_state.shadow.v1", "recorded_at_utc": now.isoformat(),
               "action_authority": False, "canonical_registration": False, "errors": errors,
               "parent_file_sha256": file_hash(raw), "max_census_age_seconds": max_age, "fixtures": rows}
    history, invalidations, invalidation_reasons = latest_freezes(journal) if journal else ({}, {}, {})
    if mode == "freeze" and journal is None:
        errors.append("MISSING_FREEZE_JOURNAL")
    predecessors = set()
    for row in rows:
        prior = history.get((row["league"], row["event_id"]))
        if prior:
            old_cutoff, old_hash, prior_parent = prior
            invalid_key = row["league"], row["event_id"], old_hash
            floor = invalidations.get(invalid_key, old_cutoff)
            # Honor a recorded invalidation: stale evidence cannot silently clear it.
            if (mode == "recheck" and not row["reasons"] and invalid_key in invalidations
                    and prior_parent == receipt["parent_file_sha256"]):
                evidence = [utc(row["cutoff_utc"])] + [utc(c["complete_through"])
                    for c in row["consumed_state"].values() if isinstance(c, dict) and c.get("complete_through")]
                if max(evidence) <= invalidations[invalid_key]:
                    row["reasons"] = sorted(invalidation_reasons.get(invalid_key) or {"PERSONNEL_REFREEZE_REQUIRED"})
            if mode == "recheck" and prior_parent == receipt["parent_file_sha256"] and row["reasons"]:
                row["invalidates_freeze_sha256"] = old_hash
            predecessors.add(old_hash)
            row["prior_freeze_sha256"] = old_hash
            if mode == "freeze" and utc(row["cutoff_utc"]) <= max(old_cutoff, floor):
                errors.append("REFREEZE_REQUIRES_NEW_INFERENCE_CUTOFF")
    if previous:
        prev_raw = previous.read_bytes()
        prev = json.loads(prev_raw)
        if journal and predecessors != {file_hash(prev_raw)}:
            raise ValueError("prior file differs from authoritative journal")
        if prev["schema"] != receipt["schema"] or prev["kind"] not in {"SHADOW_FREEZE", "SHADOW_REFREEZE"}:
            raise ValueError("invalid predecessor")
        old = {(r["league"], r["event_id"]): r for r in prev["fixtures"]}
        if set(old) != {(r["league"], r["event_id"]) for r in rows}:
            raise ValueError("predecessor fixture set differs")
        if mode == "freeze" and (utc(prev["recorded_at_utc"]) >= now or
                any(utc(r["cutoff_utc"]) <= utc(old[r["league"], r["event_id"]]["cutoff_utc"]) for r in rows)):
            raise ValueError("successor requires a later inference cutoff")
        if mode == "recheck" and prev["parent_file_sha256"] != file_hash(raw):
            raise ValueError("recheck requires original parent")
        receipt["previous_freeze_sha256"] = file_hash(prev_raw)
    if mode == "freeze" and not blocked and not errors:
        written = datetime.now(timezone.utc)
        if any(written >= utc(e["start_time_utc"]) for _, e, _, _ in _fixtures(card)):
            errors.append("STARTED_DURING_VERIFICATION")
        if any((written - utc(c["complete_through"])).total_seconds() > max_age
               for row in rows for c in row["consumed_state"].values()):
            errors.append("CENSUS_EXPIRED_DURING_VERIFICATION")
        receipt["recorded_at_utc"] = written.isoformat()
    blocked = blocked or bool(errors) or any(r["reasons"] for r in rows)
    if mode == "recheck":
        receipt["kind"] = "STALENESS_REVIEW"
    elif blocked:
        receipt["kind"] = "FREEZE_REFUSED"
        output = output.with_name(output.name + ".refusal.json")
    else:
        receipt["kind"] = "SHADOW_REFREEZE" if predecessors else "SHADOW_FREEZE"
    if mode == "freeze" and not blocked:
        # Numeric rows stay in the immutable parent. Bind each row to its consumed-state block.
        for (sport, event, _, forecast), row in zip(_fixtures(card), rows):
            row["estimates"] = {key: forecast[key] for key in ("model_winner", "model_p", "projected_margin",
                                                               "projected_total") if key in forecast}
    if journal:
        serial = (json.dumps(receipt, indent=2, allow_nan=False) + "\n").encode()
        save(journal / (file_hash(serial) + ".json"), receipt)
    save(output, receipt)
    return 2 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
