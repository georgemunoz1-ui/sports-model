"""Final diagnostic workflow gate on the process exit, bound schedule and recipient card."""
import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path


def instant(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.utcoffset() is None:
        raise ValueError("AWARE_TIME_REQUIRED")
    return stamp


def index(rows):
    events = {}
    for row in rows:
        key = row["event_id"]
        if not isinstance(key, str) or not key.strip() or key in events:
            raise ValueError("INVALID_OR_DUPLICATE_EVENT_ID")
        events[key] = row
    return events


def verify_shared_card(card, expected_events, *, league, card_date, as_of, simulations):
    """Check a dated card against the separately supplied schedule. Return observed counts."""
    if (card["league"].lower() != league.lower() or card["card_date"] != card_date
            or instant(card["as_of_utc"]) != instant(as_of) or card["simulation_count"] != simulations):
        raise ValueError("CARD_REQUEST_MISMATCH")
    if (card.get("actionable") is not False or card.get("authority") != "SHADOW_ONLY"
            or card.get("action_authority", False) is not False or card.get("allocated_units", 0) != 0):
        raise ValueError("CARD_AUTHORITY_MISMATCH")
    scheduled, actual = index(expected_events), index(card["forecasts"])
    if scheduled.keys() != actual.keys():
        raise ValueError("CARD_EVENT_SET_MISMATCH")
    counts = Counter()
    for eid, row in actual.items():
        event = scheduled[eid]
        if (any(row[k] != event[k] for k in ("home_team", "away_team"))
                or instant(row["start_time_utc"]) != instant(event["start_time_utc"])):
            raise ValueError(f"CARD_FIXTURE_MISMATCH:{eid}")
        if (row.get("action_authority") is not False or row.get("allocated_units", 0) != 0
                or row.get("dose", 0) != 0 or row.get("qualified_selection", False) is not False):
            raise ValueError(f"ROW_AUTHORITY_MISMATCH:{eid}")
        status = row["forecast_status"]
        if status == "FORECAST_GENERATED":
            allowed_winners = {event["home_team"], event["away_team"]}
            if league.lower() == "mls":
                allowed_winners.add("Draw")
            if not row.get("model_id") or row.get("model_winner") not in allowed_winners:
                raise ValueError(f"FORECAST_OUTPUT_MISSING:{eid}")
            if row.get("sim_p") != row.get("stochastic_sim_p"):
                raise ValueError(f"SIMULATION_PROBABILITY_MISMATCH:{eid}")
            for key in ("model_p", "sim_p", "stochastic_sim_p"):
                p = row.get(key)
                if type(p) not in (int, float) or not 0 <= p <= 1:
                    raise ValueError(f"INVALID_FORECAST_PROBABILITY:{eid}:{key}")
            if instant(as_of) >= instant(event["start_time_utc"]):
                raise ValueError(f"FORECAST_AFTER_START:{eid}")
        elif status in {"BLOCKED", "POST_START"}:
            if any(row.get(k) is not None for k in ("model_winner", "model_p", "analytic_p", "sim_p",
                                                    "stochastic_sim_p", "projected_margin", "projected_total",
                                                    "projected_home_points", "projected_away_points")):
                raise ValueError(f"REFUSAL_CONTAINS_FORECAST:{eid}")
            if not isinstance(row.get("refusal_reason"), str) or not row["refusal_reason"].strip():
                raise ValueError(f"MISSING_REFUSAL_REASON:{eid}")
        else:
            raise ValueError(f"UNKNOWN_FORECAST_STATUS:{eid}")
        counts[status] += 1
    if card.get("scheduled_game_count") != len(scheduled) or card.get("forecast_count") != counts["FORECAST_GENERATED"]:
        raise ValueError("CARD_COUNTER_MISMATCH")
    return counts


def expected_events(env, evidence, league, card_date):
    artifact_id = env.get("PACKAGE_ARTIFACT_ID")
    if not artifact_id:
        if league != "mlb":
            raise ValueError("CURRENT_PACKAGE_ACQUIRE_REQUIRED")
        # The legacy MLB adapter uses a separately pinned, single-date repo package.
        from pipelines.cards.adapters import mlb
        package = mlb._load()
        if package["slate_date"] != card_date:
            raise ValueError("LEGACY_PACKAGE_WRONG_DATE")
        return package["events"], None
    receipt = json.loads((evidence / "package-inputs.json").read_bytes())
    if (receipt["artifact_id"] != artifact_id or receipt["archive_sha256"] != env["PACKAGE_ARCHIVE_SHA256"]
            or receipt["league"] != league or receipt.get("action_authority") is not False):
        raise ValueError("PACKAGE_RECEIPT_MISMATCH")
    data = Path(receipt["package_path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != receipt["package_sha256"]:
        raise ValueError("PACKAGE_READBACK_MISMATCH")
    package = json.loads(data)
    if card_date not in package["covered_dates"]:
        raise ValueError("REQUESTED_DATE_NOT_CAPTURED")
    field = "gameday" if league == "nfl" else "slate_date"
    return [e for e in package["events"] if e[field] == card_date], receipt["package_sha256"]


def assess(output, evidence, env):
    """Produce a failure manifest even when acquisition or generator setup failed."""
    league = env.get("LEAGUE", "").lower()
    manifest = dict(request_id=env.get("REQUEST_ID"), github_run_id=env.get("GITHUB_RUN_ID"),
                    github_run_attempt=env.get("GITHUB_RUN_ATTEMPT"), git_sha=env.get("GITHUB_SHA"),
                    league=league.upper(), card_date=env.get("CARD_DATE"), mode="DIAGNOSTIC_SHADOW",
                    as_of_utc=env.get("AS_OF_UTC"), action_authority=False, market_overlay_enabled=False,
                    generator_exit_code=None, overall_status="FAIL")
    try:
        if env.get("REQUEST_ERROR"):
            raise ValueError(env["REQUEST_ERROR"])
        if not env.get("FORECAST_EXIT_CODE"):
            raise ValueError("GENERATOR_EXIT_NOT_RECORDED")
        rc = int(env["FORECAST_EXIT_CODE"])
        manifest["generator_exit_code"] = rc
        failure = output / "runner_failure.json"
        if failure.is_file():
            fail = json.loads(failure.read_bytes())
            raise ValueError(str(fail.get("reason") or "RUNNER_REPORTED_FAILURE"))
        events, package_sha = expected_events(env, evidence, league, env["CARD_DATE"])
        manifest["package_sha256"] = package_sha
        native = None
        if league == "nfl":
            native = json.loads((output / "nfl_runner_receipt.json").read_bytes())
            if native.get("status") != "COMPLETED":
                raise ValueError("NFL_RUNNER_RECEIPT_BLOCKED_OR_MISMATCH" + (":" + native["reason"] if native.get("reason") else ""))
        raw = (output / "diagnostic_card.json").read_bytes()
        card = json.loads(raw)
        manifest["card_sha256"] = hashlib.sha256(raw).hexdigest()
        if league != "nfl" and package_sha and card.get("package_binding") != {
                "sha256": package_sha, "league": league, "date": env["CARD_DATE"]}:
            raise ValueError("CARD_PACKAGE_BINDING_MISMATCH")
        counts = verify_shared_card(card, events, league=league, card_date=env["CARD_DATE"],
                                    as_of=env["AS_OF_UTC"], simulations=int(env["SIMULATION_COUNT"]))
        from .recipient_card import verify_recipient_card
        manifest["recipient_readback"] = verify_recipient_card(card, output / "diagnostic_card.html")
        manifest.update(scheduled_events=len(events), forecasted_events=counts["FORECAST_GENERATED"],
                        pregame_events=len(events) - counts["POST_START"], simulation_count=card["simulation_count"],
                        forecast_coverage_pct=card.get("pregame_coverage"), generated_at_utc=card.get("generated_at_utc"),
                        incident_count=len(card.get("incidents", [])))
        pit = card.get("pit_provenance") or {}
        manifest.update({
            key: pit[key] for key in (
                "requested_as_of_utc", "actual_data_vintage_utc", "max_source_timestamp_utc",
                "min_source_timestamp_utc", "pit_mode", "pit_reconstruction_supported",
                "pit_delta_seconds", "pit_status", "pit_reason", "pit_threshold_seconds", "data_vintage_basis")
            if key in pit
        })
        if native is not None:
            native_events = index(native["events"])
            rows = index(card["forecasts"])
            if (native_events.keys() != rows.keys() or any(
                    n.get("status") != "COMPLETED" or not n.get("forecast_sha256")
                    or n["forecast_sha256"] != rows[eid].get("forecast_sha256") for eid, n in native_events.items())):
                raise ValueError("NFL_RECEIPT_EVENT_MISMATCH")
            if (native.get("schema") != "nfl.runner_receipt.v1" or native.get("execution_mode") != "PREGAME_DIAGNOSTIC" or card.get("execution_mode") != "PREGAME_DIAGNOSTIC"
                    or native.get("action_authority") is not False or native.get("canonical_prospective_eligible") is not False
                    or card.get("canonical_prospective_eligible") is not False
                    or native.get("package_sha256") != package_sha or native.get("date") != env["CARD_DATE"]
                    or native.get("league") != "nfl" or native.get("card_sha256") != manifest["card_sha256"]
                    or native.get("html_sha256") != manifest["recipient_readback"]["sha256"]):
                raise ValueError("NFL_RUNNER_RECEIPT_BLOCKED_OR_MISMATCH")
        artifacts = {"json": "diagnostic_card.json", "html": "diagnostic_card.html",
                     "pit_integrity": "pit_integrity.json", "log": "run.log"}
        if league != "nfl":
            artifacts.update(csv="diagnostic_card.csv", markdown="diagnostic_card.md")
        if league == "mlb":
            artifacts.update({f"divergence_{ext}": f"divergence/divergence_report.{ext}" for ext in ("json", "csv", "md")})
        manifest["card_artifacts"] = {k: str(output / name) for k, name in artifacts.items()}
        if any(not (output / name).is_file() for name in artifacts.values()):
            raise ValueError("REQUIRED_ARTIFACT_MISSING")
        if rc != 0:
            raise ValueError(f"GENERATOR_NONZERO:{rc}")
        if not events:
            raise ValueError("NO_GAMES_VERIFICATION_REQUIRED")
        if counts["BLOCKED"] or card.get("coverage_breach_event_ids") or card.get("incidents"):
            raise ValueError("CARD_HAS_REFUSALS_OR_INCIDENTS")
        if not counts["FORECAST_GENERATED"]:
            raise ValueError("NO_PREGAME_FORECASTS")
        manifest["registration_policy"] = ("NATIVE_DIAGNOSTIC_INELIGIBLE" if native is not None
                                           else "EXISTING_REGISTRATION_RULES")
        manifest["overall_status"] = "PASS"
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        manifest["failure_reason"] = str(exc)
    return manifest


def verify_archived_card(output, downloaded):
    """A download of the uploaded artifact must reproduce the checked manifest, JSON and visible rows."""
    anchored = (output / "manifest.json").read_bytes()
    manifest = json.loads(anchored)
    if (output.resolve() == downloaded.resolve() or manifest.get("overall_status") != "PASS"
            or (downloaded / "manifest.json").read_bytes() != anchored):
        raise ValueError("ARCHIVE_MANIFEST_READBACK_MISMATCH")
    raw = (downloaded / "diagnostic_card.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["card_sha256"]:
        raise ValueError("ARCHIVE_CARD_READBACK_MISMATCH")
    from .recipient_card import verify_recipient_card
    if verify_recipient_card(json.loads(raw), downloaded / "diagnostic_card.html") != manifest["recipient_readback"]:
        raise ValueError("ARCHIVE_RECIPIENT_READBACK_MISMATCH")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readback-dir", type=Path)
    args = parser.parse_args()
    output = Path("output/card")
    if args.readback_dir:
        verify_archived_card(output, args.readback_dir)
        return 0
    output.mkdir(exist_ok=True, parents=True)
    manifest = assess(output, Path("output/run-evidence"), os.environ)
    with (output / "manifest.json").open("x") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(manifest, indent=2))
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
            stream.write("registration_policy=" + manifest.get("registration_policy", "BLOCKED") + "\n")
    return 0 if manifest["overall_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
